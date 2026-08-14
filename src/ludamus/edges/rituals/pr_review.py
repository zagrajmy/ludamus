"""Answer the review `pr_check` left on a branch, then ship it.

    vekna cast pr_review [--bound N]

The follow-up to `pr_check`, and its opposite: one branch, nothing done without
you saying so, and it is what commits the result.

A branch is a candidate when its pull request is open, yours, labelled
`pr::thermo`, not labelled `pr::wait` or `pr::qa`, and carrying a review thread
nobody has settled. Of those, the branch you are standing on wins — which is
also what keeps two terminals on two branches off each other's work.

The triage is read rather than fetched: an agent reads the open threads against
the code as it stands and hands back one item per thread, with a priority and
what it would do about it. That goes on your terminal and nowhere else, and the
threads are untouched until you have been through them.

You answer the items one at a time, in your own words; saying nothing takes the
reading's own proposal. One agent then fixes what you said to fix, files what
you said to file, and answers and settles every thread either way.

Then `fix` hands another instruction to the same agent, which remembers the
round before, or `ship` runs this project's two gates, repairs them up to
`--bound` times, and commits and pushes what came out. A branch that ends with
nothing left open earns `pr::qa`, which also takes it out of every later cast's
reckoning.
"""

from itertools import starmap
from typing import Literal

from pydantic import BaseModel, ValidationError
from vekna.folio.flow import decide
from vekna.folio.shell import ShellResult, shell
from vekna.lexicon import RitualError, Transition, done, emit_delta, goto, ritual, step

from .agent import (
    COVER,
    READING,
    Fallen,
    Misread,
    ask,
    ask_for,
    fix_gates,
    triage_read,
    triage_work,
)
from .shell import (
    COVERAGE,
    HERE,
    LIST,
    MISSING,
    PR_FIX,
    QA_LABEL,
    STATUS,
    THERMO_LABEL,
    checkout,
    commit,
    coverage_report,
    label,
    plain,
    push,
    said,
    unsettled,
)
from .state import Bound, TriageItem, TriageNotes, counted, unreadable, wanted, wears

# The engine's backstop and nothing else: the `fix` loop is bounded by the
# person sitting at it.
_MAX_STEPS = 200

# One thread for every agent call in the cast, so a later round meets an agent
# that remembers writing the one before.
_THREAD = "pr_review"

# Never this one, whatever `gh` says. This ritual ends in a commit and a push on
# the branch it takes, and a pull request opened from main — someone else's
# fork, a mistake — would send both straight there.
_MAIN = "main"


# `pr_check` cannot share this — it routes to `set_aside` where this raises —
# and once it exists, a bare `await shell()` in this file means the exit code is
# data rather than a failure.
async def _ran(command: str, complaint: str, *, stream: bool = True) -> ShellResult:
    result = await shell(command, stream=stream)
    if result.exit_code:
        msg = f"{complaint}: {said(result)}"
        raise RitualError(msg)
    return result


class PrReview(BaseModel):
    bound: Bound = 3


class Branch(BaseModel):
    name: str
    # Carried rather than looked up again: review threads are addressed by pull
    # request and not by branch.
    number: int
    bound: Bound


class Triage(BaseModel):
    branch: Branch
    items: list[TriageItem]


class Instructed(BaseModel):
    branch: Branch
    # The whole thing the agent is sent, assembled where the difference between
    # the opening round and a later one is known: the first says what the job
    # is, the ones after land in the same keyed session, which already knows.
    # It is also what the grimoire then shows.
    prompt: str


class Landing(BaseModel):
    branch: Branch
    tries: int = 0


Outcome = Literal["nothing", "declined", "shipped"]


class Shipped(BaseModel):
    outcome: Outcome
    branch: str = ""


Move = Literal["fix", "ship"]
_MOVES: tuple[Move, ...] = ("fix", "ship")


@ritual("pr_review", max_steps=_MAX_STEPS)
def pr_review(components: PrReview) -> Transition:
    return goto(pick, PrReview(bound=components.bound))


@step
async def pick(components: PrReview) -> Transition:
    """Take the branch whose review is waiting, the one you stand on first."""
    # Fatal, and first: this checks out a branch and later commits everything it
    # finds, so work in the tree now would be committed onto someone else's
    # branch.
    status = await _ran(STATUS, "git status failed", stream=False)
    if dirty := status.stdout.strip():
        msg = f"the worktree is not clean:\n{dirty}"
        raise RitualError(msg)
    listed = await _ran(LIST, "gh could not list your pull requests", stream=False)
    try:
        pulls = wanted(listed.stdout)
    except ValidationError as error:
        raise RitualError(unreadable(error)) from error
    # Reviewed by the night and not yet answered: `pr::thermo` says a review was
    # posted, an unsettled thread says it is still waiting. A branch with
    # neither has nothing here to do.
    reviewed = [
        pull
        for pull in pulls
        if pull.branch != _MAIN
        and wears(pull, THERMO_LABEL)
        and not wears(pull, QA_LABEL)
    ]
    here = await _ran(HERE, "could not read the current branch", stream=False)
    # You have just finished working on this branch and its review is what you
    # sat down for. Anything else moves you off it to read something you were
    # not thinking about — and it keeps two terminals off each other's work.
    mine = here.stdout.strip()
    ordered = [pull for pull in reviewed if pull.branch == mine] + [
        pull for pull in reviewed if pull.branch != mine
    ]
    # A call per pull request, in the order the answer is wanted, so the branch
    # you are standing on costs one and stops there.
    mute: list[str] = []
    for pull in ordered:
        left = await _open_threads(pull.number)
        if left is None:
            mute.append(pull.branch)
        elif left:
            branch = Branch(
                name=pull.branch, number=pull.number, bound=components.bound
            )
            return goto(look, branch)
    # Said apart from the ending below: a branch nobody could get a count for is
    # what makes "no review waiting" a guess, and whoever reads that sentence
    # has to know which branches it skipped.
    if mute:
        emit_delta(f"gh would not say what is open on {', '.join(mute)}")
    emit_delta("no pull request of yours has a review waiting")
    return done(Shipped(outcome="nothing"))


# `None` where `gh` would not say, which is not "nothing to do": `pick` skips
# that branch rather than calling it clean, and names it.
async def _open_threads(number: int) -> int | None:
    asked = await shell(unsettled(number), stream=False)
    text = asked.stdout.strip()
    if asked.exit_code or not text.isdigit():
        return None
    return int(text)


@step
async def look(branch: Branch) -> Transition:
    """Check the branch out and read its open threads into a triage."""
    # Asked before the checkout: `pick` falls through to a branch you are not on
    # precisely when yours had nothing waiting, so a `no` from the other side of
    # the move leaves you standing on someone else's branch.
    if not await decide(f"read the review on {branch.name}?"):
        return done(Shipped(outcome="declined", branch=branch.name))
    await _ran(checkout(branch.name), f"could not check out {branch.name}")
    # Read after the checkout: an item is triaged against the code as it stands,
    # and until then that was somebody else's code.
    read = await ask_for(triage_read(branch.number), output=TriageNotes, opts=READING)
    if isinstance(read, Fallen | Misread):
        raise RitualError(read.reason)
    # `pick` only got here on an unsettled thread, so an empty reading is the
    # reading disagreeing with `gh` rather than a branch with nothing to do.
    # Nothing is committed and nothing is labelled on that.
    if not read.items:
        emit_delta(f"the reading found nothing on {branch.name}, but gh says otherwise")
        return done(Shipped(outcome="nothing", branch=branch.name))
    return goto(plan, Triage(branch=branch, items=read.items))


# One item to a line: this is read on a terminal by somebody deciding what to do
# with it, not by an agent.
def _shown(index: int, item: TriageItem) -> str:
    return f"{index}. [{item.priority}/{item.action}] {item.where} — {item.what}"


@step
async def plan(triage: Triage) -> Transition:
    """Put the triage on your terminal and take your answer to each item."""
    tally = counted(triage.items)
    emit_delta(
        "\n".join(
            [
                f"{len(triage.items)} outstanding — {tally}",
                "",
                *starmap(_shown, enumerate(triage.items, start=1)),
            ]
        )
    )
    told: list[str] = []
    for number, item in enumerate(triage.items, start=1):
        # Free text and not a choice: an item is answered by saying how the
        # thing is supposed to work, which no four options carry. An empty
        # answer agrees with the reading's own proposal.
        said_now = await decide(f"{_shown(number, item)}\n->", free=True)
        told.append(said_now or f"{item.action} it, as the reading says")
    return goto(work, Instructed(branch=triage.branch, prompt=_asked(triage, told)))


def _asked(triage: Triage, told: list[str]) -> str:
    items = "\n\n".join(
        f"{_shown(number, item)}\n   thread: {item.thread}\n   what I want: {answer}"
        for number, (item, answer) in enumerate(
            zip(triage.items, told, strict=True), start=1
        )
    )
    return triage_work(triage.branch.number, items)


# The agent writes code, opens issues and answers review threads, so it runs at
# vekna's `bypassPermissions` default — which is why this is only ever reached
# on a triage you read yourself and a branch you said yes to.
@step
async def work(instructed: Instructed) -> Transition:
    if fallen := await ask(instructed.prompt, key=_THREAD):
        raise RitualError(fallen.reason)
    return goto(hand_back, instructed.branch)


@step
async def hand_back(branch: Branch) -> Transition:
    if await decide("fix something else, or ship it?", options=_MOVES) == "ship":
        return goto(gates, Landing(branch=branch))
    # Read rather than forwarded, as in `plan`: an empty line here means nothing
    # more to fix, and the agent on the other side of it writes code and would
    # make something of an empty instruction.
    if not (more := await decide("what should it fix?", free=True)):
        return goto(gates, Landing(branch=branch))
    return goto(work, Instructed(branch=branch, prompt=more))


# Another agent attempt is normally yours to approve; here `ship` was the
# approval, and the bound is what holds the loop.
async def _fix(landing: Landing, prompt: str) -> None:
    if landing.tries >= landing.branch.bound:
        msg = f"the gates are still red after {landing.tries} attempts"
        raise RitualError(msg)
    if fallen := await ask(prompt, key=_THREAD):
        raise RitualError(fallen.reason)


@step
async def gates(landing: Landing) -> Transition:
    """Run both gates, repairing them up to the bound."""
    # Captured rather than streamed, and run `plain`: an agent reads this, and a
    # terminal recording is not what it wants.
    ran = await shell(plain(PR_FIX), stream=False)
    if ran.exit_code:
        prompt = fix_gates(said(ran))
    else:
        covered = await shell(plain(COVERAGE), stream=False)
        report = coverage_report(covered)
        # Three ways in and one way round, so which prompt to send is all the
        # branches above decide.
        if MISSING in report:
            prompt = COVER + report
        elif covered.exit_code:
            prompt = fix_gates(said(covered), gate=COVERAGE)
        else:
            return goto(land, landing.branch)
    await _fix(landing, prompt)
    return goto(gates, Landing(branch=landing.branch, tries=landing.tries + 1))


@step
async def land(branch: Branch) -> Transition:
    await _ran(
        commit("chore: act on the review triage"), "could not commit the triage work"
    )
    # The same push `pr_check` makes: this ends on the branch that ritual put
    # up, and neither guesses at an upstream the other did not set.
    await _ran(push(branch.name), f"could not push {branch.name}")
    return goto(settle, branch)


# The one place `pr::qa` goes on, and it is a claim about the threads: asked of
# `gh` rather than assumed off the round that just ran, because the agent was
# told to settle each one, and told is not done.
# Not fatal either way: the branch is shipped whatever the count says, and what
# is left over is yours to look at.
@step
async def settle(branch: Branch) -> Transition:
    """Label the branch where gh says nothing is left open."""
    left = await _open_threads(branch.number)
    if left is None:
        emit_delta(f"gh would not say what is left open on {branch.name}")
    elif left:
        emit_delta(f"{left} review threads are still open on {branch.name}")
    else:
        labelled = await shell(label(QA_LABEL, number=branch.number))
        if labelled.exit_code:
            emit_delta(f"could not add the {QA_LABEL} label: {said(labelled)}")
    return done(Shipped(outcome="shipped", branch=branch.name))
