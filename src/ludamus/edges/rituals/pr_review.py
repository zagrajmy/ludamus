"""Answer the reviews `pr_refresh` left on your branches, then ship them.

    vekna cast pr_review [--bound N]

The follow-up to `pr_refresh`, and its opposite: nothing done without you saying
so, and it is what commits the result.

A branch is a candidate when its pull request is open, yours, labelled
`pr::thermo`, not labelled `pr::wait` or `pr::qa`, and carrying a review thread
nobody has settled. They are taken one after another, longest-waiting first,
until every one of them has been through — except that the branch you are
standing on goes first, which is also what keeps two terminals on two branches
off each other's work. A branch whose checkout will not go through, because
another worktree is standing on it, is reported and the next one is offered.

Each branch is asked about as its turn comes, and saying no to one moves on to
the next rather than ending the cast. The count of what is still open is asked
per branch, when its turn comes, rather than for all of them up front: the
sweeps run alongside this and a branch's threads can be settled while the cast
is standing on another one.

The triage is read rather than fetched: an agent reads the open threads against
the code as it stands and hands back one item per thread, with a priority and
what it would do about it. That goes on your terminal and nowhere else, and the
threads are untouched until you have been through them.

You answer the items one at a time, in your own words; saying nothing takes the
reading's own proposal. One agent then fixes what you said to fix, files what
you said to file, and answers and settles every thread either way.

Then `pr-fix` runs, is repaired up to `--bound` times, and what came out is
committed and pushed — no question in between, because the answers you gave
were the decision. A repair runs the one task mise said was
broken, not the whole gate; the gate itself runs again once that comes back
green. Diff coverage is not measured here — that is `pr_sweep`'s slow pass, and
it is the longest job in the toolchain. A branch that ends with nothing left
open earns `pr::qa`, which also takes it out of every later cast's reckoning.

A gate that will not go green after `--bound` attempts ends the cast rather
than moving on: the repair work is sitting uncommitted in the worktree, and
taking another branch would either commit it there or throw it away. The
branches already shipped are shipped, and the report says where it stopped.
"""

from itertools import starmap
from typing import Literal

from pydantic import BaseModel, ValidationError
from vekna.folio.flow import decide
from vekna.folio.shell import ShellResult, shell
from vekna.lexicon import RitualError, Transition, done, emit_delta, goto, ritual, step

from .agent import (
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
    HERE,
    LIST,
    PR_FIX,
    STATUS,
    checkout,
    commit,
    label,
    narrowed,
    plain,
    push,
    said,
    unsettled,
    wanted,
)
from .state import (
    QA_LABEL,
    THERMO_LABEL,
    Bound,
    PullRequest,
    TriageItem,
    TriageNotes,
    counted,
    unreadable,
    wears,
)

# The engine's backstop and nothing else: the `fix` loop is bounded by the
# person sitting at it, and the branch loop by how many of them carry a review.
# A dozen steps a branch, and a cast that goes through twenty of them is a
# morning nobody has.
_MAX_STEPS = 400

# One thread for every agent call in the cast, so a later round meets an agent
# that remembers writing the one before.
_THREAD = "pr_review"

# Never this one, whatever `gh` says. This ritual ends in a commit and a push on
# the branch it takes, and a pull request opened from main — someone else's
# fork, a mistake — would send both straight there.
_MAIN = "main"


# The sweeps cannot share this — they route to `set_aside` where this raises —
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


Outcome = Literal["shipped", "declined", "elsewhere", "unread", "nothing"]


# One branch's ending, in the words of the step that ended it. A branch with
# nothing open gets none of these: most of them have nothing open, and a report
# that says so line by line is a report nobody reads to the end.
class Reviewed(BaseModel):
    branch: str
    outcome: Outcome
    note: str = ""


# What the cast is still to do and what it has done. Carried through every step,
# because every ending goes round again — and the last one owes the report.
class Picking(BaseModel):
    bound: Bound
    queue: list[PullRequest] = []
    reviewed: list[Reviewed] = []
    stopped: str = ""


class Branch(BaseModel):
    # The rest of the cast, riding along: a branch is taken off the queue when
    # it is picked, so what is here is what comes after this one.
    picking: Picking
    name: str
    # Carried rather than looked up again: review threads are addressed by pull
    # request and not by branch.
    number: int

    @property
    def bound(self) -> int:
        return self.picking.bound


class Triage(BaseModel):
    branch: Branch
    items: list[TriageItem]


class Instructed(BaseModel):
    branch: Branch
    # The whole thing the agent is sent, assembled where the triage and your
    # answers to it are both in hand. It is also what the grimoire then shows.
    prompt: str


class Landing(BaseModel):
    branch: Branch
    tries: int = 0
    # The task that broke last time, where mise named one. Empty is the whole
    # gate, which is what runs first and what has the last word.
    gate: str = ""


@ritual("pr_review", max_steps=_MAX_STEPS)
def pr_review(components: PrReview) -> Transition:
    return goto(queue_up, Picking(bound=components.bound))


@step
async def queue_up(picking: Picking) -> Transition:
    """Ask gh which of your branches carry a review, and queue them."""
    listed = await _ran(LIST, "gh could not list your pull requests", stream=False)
    try:
        pulls = wanted(listed.stdout)
    except ValidationError as error:
        raise RitualError(unreadable(error)) from error
    # Reviewed by the night and not yet answered: `pr::thermo` says a review was
    # posted, and whether it is still waiting is asked branch by branch in
    # `pick`. A branch without the label has nothing here to do.
    carrying = [
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
    # The rest follow oldest-modified first, which is the order `wanted` leaves
    # them in: the review that has been waiting longest is answered first.
    mine = here.stdout.strip()
    ordered = [pull for pull in carrying if pull.branch == mine] + [
        pull for pull in carrying if pull.branch != mine
    ]
    return goto(pick, _with(picking, queue=ordered))


# The same move `state.run_with` is: build the next payload from the last one,
# with a field list a type checker can follow.
def _with(
    picking: Picking,
    *,
    queue: list[PullRequest] | None = None,
    reviewed: list[Reviewed] | None = None,
    stopped: str = "",
) -> Picking:
    return Picking(
        bound=picking.bound,
        queue=picking.queue if queue is None else queue,
        reviewed=picking.reviewed if reviewed is None else reviewed,
        stopped=stopped or picking.stopped,
    )


# What a branch's turn came to, written where its turn ended. The queue has
# already had this branch taken off it, so what goes forward is the rest.
def _rowed(branch: Branch, outcome: Outcome, note: str = "") -> Picking:
    row = Reviewed(branch=branch.name, outcome=outcome, note=note)
    return _with(branch.picking, reviewed=[*branch.picking.reviewed, row])


@step
async def pick(picking: Picking) -> Transition:
    """Take the next branch whose review is still waiting."""
    if not picking.queue:
        return goto(recap, picking)
    # Fatal, and before every checkout, not only the first: this moves branches
    # around and later commits everything it finds, so work left in the tree
    # would be committed onto the next branch it takes.
    status = await _ran(STATUS, "git status failed", stream=False)
    if dirty := status.stdout.strip():
        msg = f"the worktree is not clean:\n{dirty}"
        raise RitualError(msg)
    pull, *rest = picking.queue
    left = await _open_threads(pull.number)
    branch = Branch(
        picking=_with(picking, queue=rest), name=pull.branch, number=pull.number
    )
    if left is None:
        # A branch nobody could get a count for is not a branch with nothing to
        # do, so it is said out loud rather than passed over quietly.
        emit_delta(f"gh would not say what is open on {branch.name}")
        return goto(pick, _rowed(branch, "unread"))
    if not left:
        # The ordinary case, and the reason it earns no row: most branches have
        # nothing open, and a report listing every one of them is a report
        # nobody reads to the end.
        return goto(pick, branch.picking)
    return goto(look, branch)


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
    # Asked before the checkout: a `no` from the other side of the move leaves
    # you standing on a branch you did not ask for. Declining takes the next
    # one — this goes through every branch that has a review waiting, and one
    # you do not want to read now is not a reason to stop.
    if not await decide(f"read the review on {branch.name}?"):
        return goto(pick, _rowed(branch, "declined"))
    taken = await shell(checkout(branch.name))
    # Not fatal, unlike every other command here: a checkout that will not go
    # through is another worktree standing on the branch, and there is a whole
    # list of other pull requests this could be reading instead.
    if taken.exit_code:
        emit_delta(f"{branch.name} is checked out elsewhere: {said(taken)}")
        return goto(pick, _rowed(branch, "elsewhere", said(taken)))
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
        return goto(pick, _rowed(branch, "nothing"))
    return goto(plan, Triage(branch=branch, items=read.items))


# What the thread asked and what the reading would do about it, in that order:
# this is read on a terminal by somebody deciding what to do with it, not by an
# agent, and the verdict alone does not say what it is a verdict on.
def _shown(index: int, item: TriageItem) -> str:
    return (
        f"{index}. [{item.priority}/{item.action}] {item.where} — {item.raised}\n"
        f"   -> {item.what}"
    )


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
    # Straight to the gate, with nothing asked: the triage was answered item by
    # item a step ago, so a question here is the cast asking whether you meant
    # what you just said.
    if fallen := await ask(instructed.prompt, key=_THREAD):
        raise RitualError(fallen.reason)
    return goto(gates, Landing(branch=instructed.branch))


@step
async def gates(landing: Landing) -> Transition:
    """Run the gate, repairing it up to the bound."""
    # The task that broke last time round, where mise named one: an agent
    # working on `lint:mypy` is judged by `lint:mypy`, and not by three package
    # installs and a formatter run in front of it.
    gate = landing.gate or PR_FIX
    # Captured rather than streamed, and run `plain`: an agent reads this, and a
    # terminal recording is not what it wants.
    ran = await shell(plain(gate), stream=False)
    if not ran.exit_code:
        # A task passing on its own is the reason to spend the gate, not the
        # gate passing. What lands the branch is the whole chain going green.
        if gate != PR_FIX:
            return goto(gates, Landing(branch=landing.branch, tries=landing.tries))
        return goto(land, landing.branch)
    # The repair work is in the worktree and uncommitted, so there is no moving
    # on to the next branch from here: it would be committed there or thrown
    # away. The branches already shipped keep their rows.
    if landing.tries >= landing.branch.bound:
        stopped = f"`{gate}` is still red after {landing.tries} attempts"
        return goto(recap, _with(landing.branch.picking, stopped=stopped))
    # Another agent attempt is normally yours to approve; here `ship` was the
    # approval, and the bound is what holds the loop.
    if fallen := await ask(fix_gates(said(ran), gate=gate), key=_THREAD):
        raise RitualError(fallen.reason)
    return goto(
        gates,
        Landing(branch=landing.branch, tries=landing.tries + 1, gate=narrowed(ran)),
    )


@step
async def land(branch: Branch) -> Transition:
    await _ran(
        commit("chore: act on the review triage"), "could not commit the triage work"
    )
    # The same push the sweeps make: this ends on the branch they put
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
    note = ""
    if left is None:
        note = "gh would not say what is left open"
    elif left:
        note = f"{left} review threads are still open"
    else:
        labelled = await shell(label(QA_LABEL, number=branch.number))
        if labelled.exit_code:
            note = f"could not add the {QA_LABEL} label: {said(labelled)}"
    if note:
        emit_delta(f"{branch.name}: {note}")
    return goto(pick, _rowed(branch, "shipped", note))


_TOLD = {
    "shipped": "shipped",
    "declined": "left for later",
    "elsewhere": "checked out elsewhere",
    "unread": "gh would not say what is open",
    "nothing": "the reading found nothing",
}


# Every ending comes here, so the report is owed however the cast ends — the
# same bargain the sweeps make, and the reason a red gate routes rather than
# raises.
@step
def recap(picking: Picking) -> Transition:
    """Say what each branch came to, and fail the cast where one stopped it."""
    lines = [f"pr_review — {len(picking.reviewed)} branches"]
    lines += [
        f"  {row.branch}: {_TOLD[row.outcome]}" + (f" — {row.note}" if row.note else "")
        for row in picking.reviewed
    ] or ["  (none had a review waiting)"]
    if picking.stopped:
        # What is left in the queue only means anything here: a cast that ran
        # to the end left nothing in it.
        left = ", ".join(pull.branch for pull in picking.queue)
        lines += ["", f"the cast stopped: {picking.stopped}"]
        lines += [f"not reached:    {left}"] if left else []
    emit_delta("\n".join(lines))
    if picking.stopped:
        raise RitualError(picking.stopped)
    return done(picking)
