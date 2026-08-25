"""What a cast carries, and what it leaves behind.

The payload models every step routes forward, the budget arithmetic those
payloads hold, and the report the morning reads.
"""

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.aliases import AliasPath

# This branch has had its review. Inline review comments are invisible to
# `gh pr view --json comments`, so a label is what the step can actually see —
# and a label is also something you can take off, which is the point: removing
# it is how you ask for the review again.
THERMO_LABEL = "pr::thermo"
# Hands off this one. It is read at the listing and nowhere else, so a branch
# wearing it is never taken, never touched, and never reported on — which is
# the whole point: it is how you keep a pull request out of the night without
# closing it.
WAIT_LABEL = "pr::wait"

# A bound counts attempts at one step, so zero would mean a step that may never
# be tried at all; past five a repair loop has stopped being a repair loop.
Bound = Annotated[int, Field(ge=1, le=5)]


class PrSweep(BaseModel):
    bound: Bound = 3


# Which pass a cast is. The two share every step that takes a branch and writes
# a row; they part at the gate — the fast pass merges and makes `pr-fix` green,
# the slow one measures coverage and writes the tests.
Mode = Literal["refresh", "cover"]


# What CI says about one thing it ran, in the check-runs API's own words.
# `conclusion` is null while a run is still going, which is why nothing reads
# it as anything but "not success yet". `title` is the one-line summary a job
# writes for itself: absent for most of the board, and for `codecov/patch` the
# patch coverage this branch achieved — the number the slow pass would
# otherwise have to read out of English prose. It is pulled up out of the
# `output` it arrives under, whose other half is a markdown report nothing
# here reads.
# `populate_by_name` is not for any caller — nothing builds a `Check` by hand.
# Without it mypy's pydantic plugin cannot name the aliased field in the
# generated `__init__` and falls back to `**kwargs: Any`, which this project
# refuses.
class Check(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    conclusion: str | None = None
    title: str | None = Field(
        default=None, validation_alias=AliasPath("output", "title")
    )


# The check-runs endpoint wraps the board in one key, and it stays wrapped
# until it is parsed: unwrapping it with `--jq` would move the reading into
# the command string, and every other answer `gh` gives these rituals is made
# sense of by a model.
class Board(BaseModel):
    check_runs: list[Check] = []


# `gh --json labels` hands back an object per label; the name is the whole
# question here.
class Label(BaseModel):
    name: str


class Labels(BaseModel):
    labels: list[Label]


# Aliased rather than renamed downstream: `gh --json` picks the spelling, and
# one mapping here beats camelCase running through every step.
class PullRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    number: int
    title: str
    url: str
    branch: str = Field(alias="headRefName")
    base: str = Field(alias="baseRefName")
    updated_at: str = Field(alias="updatedAt")
    # As they stood at the listing. Only the wait label is read from here, and
    # only once: everything later re-reads gh, because this ritual adds labels
    # of its own as it goes.
    labels: list[Label] = []


def wears(pull: PullRequest, name: str) -> bool:
    return any(label.name == name for label in pull.labels)


def unreadable(error: ValidationError) -> str:
    return f"gh returned something unreadable: {error}"


class Checked(BaseModel):
    number: int
    branch: str
    url: str
    # What the night can say about the branch: whether the gates went green and
    # the work went up. What the review threads say is `pr_review`'s to read.
    # `skipped` is neither — the branch was never taken, so there is nothing to
    # call green or broken.
    outcome: Literal["green", "blocked", "skipped"]
    # None when git could not say. Nothing to push and "we could not tell" are
    # different answers, and the report prints them differently.
    unpushed: int | None
    note: str = ""


# Every step carries this, because the report is owed however the cast ends.
class Run(BaseModel):
    bound: int
    # The fast pass by default: it is the one every shared step was written for,
    # and the slow one says so at its entrypoint.
    mode: Mode = "refresh"
    queue: list[PullRequest] = []
    checked: list[Checked] = []
    stopped: str = ""
    # Every verdict a gate on this run has given up on, carried across branches
    # so the next one can recognise it. A night where the same thing is broken
    # everywhere — an unreachable host, a browser that will not start — is a
    # night that should pay for that answer once, not once per pull request.
    # One list for both gates rather than one apiece: `pr-fix` and `diff-cover`
    # run the same unit suite, so a test that kills one kills the other, and a
    # branch whose coverage run says what last branch's gate run said is stopped
    # by the same thing. Recognising it across the two is the point, not a leak.
    seen: list[str] = []


# `budgets` dies with this payload, which is what "a branch change clears all
# budgets" means — a fresh Work is built per pull request and inherits nothing.
class Work(BaseModel):
    run: Run
    pr: PullRequest
    budgets: dict[str, int] = {}
    merging: bool = False
    # What the repair loop should run next, empty for the step's own gate. The
    # narrow task mise named when the gate broke, so an agent's attempt is
    # judged by the thing that was wrong rather than by the whole chain in front
    # of it. One field for both loops rather than one apiece: a cast takes one
    # pass or the other, so `gate_check` and `cover` never run in the same one.
    gate: str = ""
    # The merge brought nothing in, so the tree is the one CI has already
    # graded. Only ever true before any agent has touched the branch.
    unchanged: bool = False
    note: str = ""
    # What stopped this branch, in the words of whatever stopped it. Written
    # once, by the step that gave up, and never written over: a branch that
    # stands down goes on to be reviewed and triaged like any other, and every
    # ending down there sets `note` for its own purposes. Read by two people who
    # want different things — the review agent, which is told not to raise it,
    # and the morning, which is told it first.
    reason: str = ""
    # This branch will not be made green tonight, and is being read anyway. The
    # reading steps that follow need to know: a branch nobody can merge must not
    # come out reported green.
    blocked: bool = False


class TriageItem(BaseModel):
    where: str
    # What the thread itself asked for, in one line. Without it the decision is
    # taken on the reading's verdict alone, with no sight of the comment behind
    # it.
    raised: str
    what: str
    # p4 is not a smaller p3: it is the thread that has no work in it at all —
    # already done, no longer true, or simply wrong — and it is sorted out of
    # the way so the reading you go through is only the items worth a decision.
    priority: Literal["p1", "p2", "p3", "p4"]
    # What the reading would do about it, which is what happens when you say
    # nothing: an item you agree with costs you a return key.
    action: Literal["fix", "reject", "file"]
    # The thread this came off, so the round that answers it addresses the
    # thread the item is about rather than the one it matched by eye. The
    # graphql node id, which is what the resolve mutation takes.
    thread: str


# What the agent returns, and no more: which branch this triage belongs to is
# the ritual's to know, not the agent's to repeat back.
class TriageNotes(BaseModel):
    items: list[TriageItem]


class Closed(BaseModel):
    work: Work
    outcome: Literal["green", "blocked"]


# What the night did, branch by branch, and nothing sorted into work lists on
# top: this pass refreshes pull requests, it does not triage them, and a list
# headed "ready to test" is a claim only `pr_review` and you can make.
class Report(BaseModel):
    checked: list[Checked] = []
    not_reached: list[str] = []
    failed: str = ""


# Every step routes state forward by building the next one from the last, and
# `model_copy(update=...)` is typed `Mapping[str, Any]` — one untyped expression
# per hop, spreading through every payload a strict checker looks at. These are
# the same move written so the checker can follow it: the field list lives here
# once, and `None` means "whatever the last one had".
def run_with(
    run: Run,
    *,
    queue: list[PullRequest] | None = None,
    checked: list[Checked] | None = None,
    stopped: str | None = None,
    seen: list[str] | None = None,
) -> Run:
    return Run(
        bound=run.bound,
        mode=run.mode,
        queue=run.queue if queue is None else queue,
        checked=run.checked if checked is None else checked,
        stopped=run.stopped if stopped is None else stopped,
        seen=run.seen if seen is None else seen,
    )


def work_with(
    work: Work,
    *,
    run: Run | None = None,
    budgets: dict[str, int] | None = None,
    merging: bool | None = None,
    gate: str | None = None,
    unchanged: bool | None = None,
    note: str | None = None,
    reason: str | None = None,
    blocked: bool | None = None,
) -> Work:
    return Work(
        run=work.run if run is None else run,
        pr=work.pr,
        budgets=work.budgets if budgets is None else budgets,
        merging=work.merging if merging is None else merging,
        gate=work.gate if gate is None else gate,
        unchanged=work.unchanged if unchanged is None else unchanged,
        note=work.note if note is None else note,
        reason=work.reason if reason is None else reason,
        blocked=work.blocked if blocked is None else blocked,
    )


# A note grows by joining rather than replacing, so no half of it writes over
# another's. The separator is decided here and nowhere else.
def joined(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


# Why the branch stopped comes first, which is the order the morning wants it
# in. Every ending goes through here, so no ending can write over another's
# half.
def telling(work: Work, *extra: str) -> str:
    return joined(work.reason, work.note, *extra)


def counted(items: list[TriageItem]) -> str:
    tally = Counter(item.priority for item in items)
    return ", ".join(
        f"{priority}: {tally[priority]}" for priority in ("p1", "p2", "p3", "p4")
    )


# --- budgets ---------------------------------------------------------------


def spent(work: Work, name: str) -> int:
    return work.budgets.get(name, 0)


def exhausted(work: Work, name: str) -> bool:
    return spent(work, name) >= work.run.bound


def charged(work: Work, name: str) -> Work:
    return work_with(work, budgets={**work.budgets, name: spent(work, name) + 1})


# A step that goes green hands its budget back, so a step reached a second time
# on the same branch — coverage work sending the gates red again — starts over
# rather than inheriting what the first pass spent.
def cleared(work: Work, name: str) -> Work:
    kept = {step: count for step, count in work.budgets.items() if step != name}
    return work_with(work, budgets=kept)


# --- endings ---------------------------------------------------------------


# A pull request gives up and the run carries on: the note travels with the
# work, and the `goto(set_aside, ...)` stays written out at every call site,
# because the graph `vekna rituals show` draws is read off each step's source
# text and a target named inside a helper is an edge the drawing loses.


# The run gives up with a pull request in flight: it goes into the report as
# blocked, because the branch is left wherever the failure left it.
def abandoned(work: Work, reason: str) -> Run:
    row = Checked(
        number=work.pr.number,
        branch=work.pr.branch,
        url=work.pr.url,
        outcome="blocked",
        unpushed=None,
        note=f"left mid-flight: {reason}",
    )
    return run_with(work.run, checked=[*work.run.checked, row], stopped=reason)


# --- the report ------------------------------------------------------------

_OUTCOME = {
    "green": "green and reviewed",
    "blocked": "blocked",
    "skipped": "left alone",
}


def _line(row: Checked) -> str:
    ahead = "unknown" if row.unpushed is None else f"{row.unpushed} unpushed"
    # A blocked row's note carries the gate's verdict, which is a dozen lines of
    # someone else's output. Indented under the row rather than run into it: the
    # rows are a scannable list, and a note that starts in column zero ends that
    # list wherever it lands.
    wrapped = row.note.replace("\n", "\n      ")
    note = f" — {wrapped}" if row.note else ""
    return f"  #{row.number} {row.branch}: {_OUTCOME[row.outcome]}, {ahead}{note}"


def report_card(run: Run) -> Report:
    return Report(
        checked=run.checked,
        not_reached=[pull.branch for pull in run.queue],
        failed=run.stopped,
    )


def summary(run: Run) -> str:
    card = report_card(run)
    lines = [f"pr_{run.mode} — {len(run.checked)} checked", ""]
    lines += [_line(row) for row in run.checked] or ["  (none)"]
    # Only when there are any, unlike the rows: a pass that reached every pull
    # request is the normal night, and a line saying "none" on every one of them
    # trains the eye past it.
    if card.not_reached:
        lines += ["", f"not reached: {', '.join(card.not_reached)}"]
    if card.failed:
        lines += ["", f"the run failed: {card.failed}"]
    return "\n".join(lines) + "\n"
