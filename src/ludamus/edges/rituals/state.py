"""What a cast carries, and what it leaves behind.

The payload models every step routes forward, the budget arithmetic those
payloads hold, and the report the morning reads.
"""

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .shell import QA_LABEL

# A bound counts attempts at one step, so zero would mean a step that may never
# be tried at all; past five a repair loop has stopped being a repair loop.
Bound = Annotated[int, Field(ge=1, le=5)]


class PrCheck(BaseModel):
    bound: Bound = 3


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


PULLS: TypeAdapter[list[PullRequest]] = TypeAdapter(list[PullRequest])


# `gh pr view --json labels` hands back an object per label; the name is the
# whole question here.
class Label(BaseModel):
    name: str


class Labels(BaseModel):
    labels: list[Label]


class Checked(BaseModel):
    number: int
    branch: str
    url: str
    outcome: Literal["qa", "triage", "blocked"]
    # None when git could not say. Nothing to push and "we could not tell" are
    # different answers, and the report prints them differently.
    unpushed: int | None
    note: str = ""


# The whole run: what is left to do, what was done, and why it stopped if it
# stopped. Every step carries it, because the report is owed however the cast
# ends.
class Run(BaseModel):
    bound: int
    queue: list[PullRequest] = []
    checked: list[Checked] = []
    stopped: str = ""


# One pull request in flight. `budgets` dies with this payload, which is what "a
# branch change clears all budgets" means — a fresh Work is built per pull
# request and inherits nothing.
class Work(BaseModel):
    run: Run
    pr: PullRequest
    budgets: dict[str, int] = {}
    merging: bool = False
    note: str = ""


class TriageItem(BaseModel):
    where: str
    what: str
    priority: Literal["p1", "p2", "p3"]


# What the agent returns, and no more: which branch this triage belongs to is
# the ritual's to know, not the agent's to repeat back.
class TriageNotes(BaseModel):
    items: list[TriageItem]


class Triaged(BaseModel):
    work: Work
    notes: TriageNotes


class Closed(BaseModel):
    work: Work
    outcome: Literal["qa", "triage"]


class Report(BaseModel):
    checked: list[Checked] = []
    to_push: list[str] = []
    to_fix: list[str] = []
    ready: list[str] = []
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
) -> Run:
    return Run(
        bound=run.bound,
        queue=run.queue if queue is None else queue,
        checked=run.checked if checked is None else checked,
        stopped=run.stopped if stopped is None else stopped,
    )


def work_with(
    work: Work,
    *,
    budgets: dict[str, int] | None = None,
    merging: bool | None = None,
    note: str | None = None,
) -> Work:
    return Work(
        run=work.run,
        pr=work.pr,
        budgets=work.budgets if budgets is None else budgets,
        merging=work.merging if merging is None else merging,
        note=work.note if note is None else note,
    )


# A sort key, and it has to be spelled out: `attrgetter` is `attrgetter[Any]`
# and a lambda's parameter is untyped, so mypy rejects both here. This is the
# only shape of the three that carries a type.
def modified(pull: PullRequest) -> str:
    return pull.updated_at


def counted(notes: TriageNotes) -> str:
    tally = Counter(item.priority for item in notes.items)
    return ", ".join(
        f"{priority}: {tally[priority]}" for priority in ("p1", "p2", "p3")
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
    "qa": f"ready to test ({QA_LABEL})",
    "triage": "triage.md written",
    "blocked": "blocked",
}


def _names(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


def _line(row: Checked) -> str:
    ahead = "unknown" if row.unpushed is None else f"{row.unpushed} unpushed"
    note = f" — {row.note}" if row.note else ""
    return f"  #{row.number} {row.branch}: {_OUTCOME[row.outcome]}, {ahead}{note}"


def report_card(run: Run) -> Report:
    return Report(
        checked=run.checked,
        # Unknown counts as needing a push: this is read by someone deciding
        # what to do next, and "we could not tell" is not "nothing to do".
        to_push=[
            row.branch for row in run.checked if row.unpushed is None or row.unpushed
        ],
        to_fix=[row.branch for row in run.checked if row.outcome == "triage"],
        ready=[row.branch for row in run.checked if row.outcome == "qa"],
        not_reached=[pull.branch for pull in run.queue],
        failed=run.stopped,
    )


def summary(run: Run) -> str:
    card = report_card(run)
    lines = [f"pr_check — {len(run.checked)} checked", ""]
    lines += [_line(row) for row in run.checked] or ["  (none)"]
    lines += [
        "",
        f"needs pushing:  {_names(card.to_push)}",
        f"needs fixing:   {_names(card.to_fix)}",
        f"ready to test:  {_names(card.ready)}",
    ]
    if card.not_reached:
        lines.append(f"not reached:    {_names(card.not_reached)}")
    if card.failed:
        lines += ["", f"the run failed: {card.failed}"]
    return "\n".join(lines) + "\n"
