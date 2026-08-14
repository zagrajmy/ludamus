"""Answer the review `pr_check` left on a branch, then ship it.

    vekna cast ship [--bound N]

The follow-up to `pr_check`, and its opposite in every way that matters: it
takes exactly one branch, it asks you before it does anything, and it is the
thing that commits what comes out. `pr_check` runs at 3am and answers nobody;
this runs while you are sitting there and does nothing you have not said.

One branch, and then it stops. A branch is a candidate when its pull request is
open, yours, labelled `pr::thermo`, not labelled `pr::wait` or `pr::qa`, and
carrying a review thread nobody has settled — and of those, the branch you are
standing on wins.

The triage is read here rather than fetched: an agent reads the open threads
against the code as it stands and hands back one item per thread, with a
priority and what it would do about it. That list goes on your terminal and
nowhere else — nothing is posted, and the threads are untouched until you have
been through them.

Then you answer them one at a time, in your own words: what the thing is
supposed to do, why an item is wrong, which of two readings was meant. Saying
nothing takes the reading's own proposal. What comes out of that goes to one
agent, which fixes what you said to fix, files what you said to file, and
answers and settles every thread either way.

Then you read what it did and say `fix` or `ship`. `fix` takes another
instruction and hands it to the same agent, which remembers the round before.
`ship` runs this project's two gates, repairs them up to `--bound` times, and
commits and pushes what came out. A branch that ends with nothing left open
earns `pr::qa`, which is also what takes it out of every later cast's reckoning.

Nothing here is a queue, which is what makes it safe to run in several terminals
at once: preferring the branch you are on means two terminals on two branches
never reach for the same work.
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
    LIST,
    MISSING,
    PR_FIX,
    QA_LABEL,
    REMOTE,
    THERMO_LABEL,
    commit,
    coverage_report,
    label,
    plain,
    quoted,
    said,
    unsettled,
)
from .state import Bound, TriageItem, TriageNotes, counted, unreadable, wanted, wears

# The human loop above has no business bound — it goes round as long as you keep
# saying `fix`, which is a person spending their own evening. This is the
# engine's backstop and nothing else.
_MAX_STEPS = 200

# Every agent call in the cast joins one thread, so the round you asked for
# after reading the last one meets an agent that remembers writing it.
_THREAD = "ship"

_STATUS = "git status --porcelain"

# Never this one, whatever `gh` says about it. This ritual ends in a commit and
# a push on the branch it takes, and a pull request opened from main — someone
# else's fork, a mistake — would send both straight there.
_MAIN = "main"

# Which branch you are standing on, which is the one this ritual would rather
# take than any other.
_HERE = "git rev-parse --abbrev-ref HEAD"


# Every fatal call in this ritual is the same three lines around one command, so
# they are written once and each step keeps the two things that differ: what to
# run, and what to say when it will not run. `pr_check` cannot share this — it
# routes to `set_aside` where this raises — and after it, a bare `await shell()`
# in this file means the exit code is data rather than a failure.
async def _ran(command: str, complaint: str, *, stream: bool = True) -> ShellResult:
    result = await shell(command, stream=stream)
    if result.exit_code:
        msg = f"{complaint}: {said(result)}"
        raise RitualError(msg)
    return result


class Ship(BaseModel):
    bound: Bound = 3


class Branch(BaseModel):
    name: str
    # Carried rather than looked up again: everything below this reads or answers
    # review threads, and those are addressed by pull request and not by branch.
    number: int
    bound: Bound


class Triage(BaseModel):
    branch: Branch
    items: list[TriageItem]


class Instructed(BaseModel):
    branch: Branch
    # The whole thing the agent is sent, assembled where the difference between
    # the opening round and a later one is known: the first says what the job
    # is, and the ones after land in the same keyed session, which already
    # knows. It is also what the grimoire then shows, which is the better half
    # of carrying it here rather than a sentence to be joined further on.
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


@ritual("ship", max_steps=_MAX_STEPS)
def ship(components: Ship) -> Transition:
    return goto(pick, Ship(bound=components.bound))


@step
async def pick(components: Ship) -> Transition:
    # Fatal, and first: this checks out a branch and later commits everything it
    # finds, so work sitting in the tree now would be carried onto someone
    # else's branch and committed there.
    status = await _ran(_STATUS, "git status failed", stream=False)
    if dirty := status.stdout.strip():
        msg = f"the worktree is not clean:\n{dirty}"
        raise RitualError(msg)
    listed = await _ran(LIST, "gh could not list your pull requests", stream=False)
    try:
        pulls = wanted(listed.stdout)
    except ValidationError as error:
        raise RitualError(unreadable(error)) from error
    # Reviewed by the night and not yet answered by anyone: `pr::thermo` is what
    # says a review was posted, and an unsettled thread is what says it is still
    # waiting. A branch with neither has nothing here to do.
    reviewed = [
        pull
        for pull in pulls
        if pull.branch != _MAIN
        and wears(pull, THERMO_LABEL)
        and not wears(pull, QA_LABEL)
    ]
    here = await _ran(_HERE, "could not read the current branch", stream=False)
    # You have just finished working on this branch and the review on it is what
    # you sat down for. Anything else is a cast that moves you off it to read
    # something you were not thinking about — and it is also what keeps two
    # terminals on two branches from reaching for the same one.
    mine = here.stdout.strip()
    ordered = [pull for pull in reviewed if pull.branch == mine] + [
        pull for pull in reviewed if pull.branch != mine
    ]
    # A call per pull request, asked in the order the answer is wanted in, so the
    # branch you are standing on costs one and stops there.
    for pull in ordered:
        if await _open_threads(pull.number):
            branch = Branch(
                name=pull.branch, number=pull.number, bound=components.bound
            )
            return goto(look, branch)
    emit_delta("no pull request of yours has a review waiting")
    return done(Shipped(outcome="nothing"))


# What is outstanding on a pull request, and `None` where `gh` would not say.
# A count nobody could take is not "nothing to do": `pick` skips that branch
# rather than claiming it is clean, and the ending below says so out loud.
async def _open_threads(number: int) -> int | None:
    asked = await shell(unsettled(number), stream=False)
    text = asked.stdout.strip()
    if asked.exit_code or not text.isdigit():
        return None
    return int(text)


@step
async def look(branch: Branch) -> Transition:
    await _ran(
        f"git checkout {quoted(branch.name)}", f"could not check out {branch.name}"
    )
    if not await decide(f"read the review on {branch.name}?"):
        return done(Shipped(outcome="declined", branch=branch.name))
    # Read on the branch and not before it: an item is triaged against the code
    # as it stands, and until the checkout above that was somebody else's code.
    read = await ask_for(triage_read(branch.number), output=TriageNotes, opts=READING)
    if isinstance(read, Fallen | Misread):
        raise RitualError(read.reason)
    # `pick` only got here on a thread nobody had settled, so an empty reading is
    # the reading disagreeing with `gh` rather than a branch with nothing to do.
    # Nothing is committed and nothing is labelled on the strength of that.
    if not read.items:
        emit_delta(f"the reading found nothing on {branch.name}, but gh says otherwise")
        return done(Shipped(outcome="nothing", branch=branch.name))
    return goto(plan, Triage(branch=branch, items=read.items))


# One item to a line, priority first, because this is read on a terminal by
# somebody deciding what to do with it rather than by an agent.
def _shown(index: int, item: TriageItem) -> str:
    return f"{index}. [{item.priority}/{item.action}] {item.where} — {item.what}"


@step
async def plan(triage: Triage) -> Transition:
    tally = counted(TriageNotes(items=triage.items))
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
        # Free text and not a choice: an item is answered by saying how the thing
        # is supposed to work, which no four options carry. An empty answer is an
        # answer too — the reading already proposed something, and saying nothing
        # is agreeing with it.
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
# vekna's `bypassPermissions` default — deliberately, and it is why this ritual
# only ever reaches here on a triage you have read yourself and a branch you
# said yes to.
@step
async def work(instructed: Instructed) -> Transition:
    if fallen := await ask(instructed.prompt, key=_THREAD):
        raise RitualError(fallen.reason)
    return goto(hand_back, instructed.branch)


@step
async def hand_back(branch: Branch) -> Transition:
    if await decide("fix something else, or ship it?", options=_MOVES) == "ship":
        return goto(gates, Landing(branch=branch))
    more = await decide("what should it fix?", free=True)
    return goto(work, Instructed(branch=branch, prompt=more))


# Spending another agent attempt is normally yours to approve, and here it is
# not: you asked for `ship`, which is the approval. What holds the loop is the
# bound.
async def _fix(landing: Landing, prompt: str) -> None:
    if landing.tries >= landing.branch.bound:
        msg = f"the gates are still red after {landing.tries} attempts"
        raise RitualError(msg)
    if fallen := await ask(prompt, key=_THREAD):
        raise RitualError(fallen.reason)


@step
async def gates(landing: Landing) -> Transition:
    # Captured rather than streamed, and run `plain`: what comes back is read by
    # an agent, and a terminal recording is not that.
    ran = await shell(plain(PR_FIX), stream=False)
    if ran.exit_code:
        prompt = fix_gates(said(ran))
    else:
        covered = await shell(plain(COVERAGE), stream=False)
        report = coverage_report(covered)
        # Three ways in and one way round, so which prompt to send is the only
        # thing the branches above decide.
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
    # The remote by name, as `pr_check` pushes it: what this ends on is the same
    # branch that ritual put up, and neither of them is going to guess at an
    # upstream the other did not set.
    await _ran(
        f"git push {REMOTE} {quoted(branch.name)}", f"could not push {branch.name}"
    )
    return goto(settle, branch)


# The last thing anybody asks of the branch, and the one place `pr::qa` is put
# on: the work is committed and up, and the label says every thread that stood
# open when this started has been answered and settled. Asked of `gh` rather
# than assumed off the round that just ran — the agent was told to settle each
# thread, and told is not done.
# Not fatal either way: what is left over is yours to look at, and the branch is
# shipped whatever the count says.
@step
async def settle(branch: Branch) -> Transition:
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
