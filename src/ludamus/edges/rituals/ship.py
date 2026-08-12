"""Work through the triage `pr_check` left on a branch, then ship it.

    vekna cast ship [--bound N]

The follow-up to `pr_check`, and its opposite in every way that matters: it
takes exactly one branch, it asks you before it does anything, and it is the
thing that commits what comes out. `pr_check` runs at 3am and answers nobody;
this runs while you are sitting there and does nothing you have not read.

One branch, and then it stops. A branch is a candidate when its pull request is
open, yours, not labelled `pr::wait`, and a triage for it is waiting in
`.local` — and of those, the branch you are standing on wins. The triage goes
through your pager, you say what should be done with it, and an agent does that:
fixes what you said to fix, answers and resolves the review threads either way,
and files the rest as issues.

Then you read what it did and say `fix` or `ship`. `fix` takes another
instruction and hands it to the same agent, which remembers the round before.
`ship` runs this project's two gates, repairs them up to `--bound` times, and
commits and pushes what came out.

Nothing here is a queue, which is what makes it safe to run in several terminals
at once: preferring the branch you are on means two terminals on two branches
never reach for the same work, and a triage this cast answers is deleted from
`.local`, which takes that branch out of every later cast's reckoning.
"""

from typing import Literal

from pydantic import BaseModel, ValidationError
from vekna.folio.flow import decide
from vekna.folio.shell import ShellResult, shell
from vekna.lexicon import RitualError, Transition, done, emit_delta, goto, ritual, step

from .agent import COVER, ask, fix_gates, triage_work
from .shell import (
    COVERAGE,
    LIST,
    MISSING,
    PR_FIX,
    TRIAGE_GLOB,
    WAIT_LABEL,
    commit,
    coverage_report,
    plain,
    quoted,
    rooted,
    said,
    triage_path,
)
from .state import PULLS, Bound, modified, wears

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


# The one place this ritual writes to the terminal instead of into the rite.
# `>/dev/tty` gives the command a terminal, so `cat` pages and you can scroll
# it; `</dev/tty` is where the pager reads your keys, since the cast holds stdin
# for its own prompts. Whether that terminal is there at all is asked first, and
# not by running the command and reading its exit code: quitting the pager early
# kills the command with a broken pipe, and a fallback hung off that would
# answer by dumping the whole file you just walked away from.
def paged(command: str) -> str:
    return (
        # `2>/dev/null` first, because a redirection that fails is reported by
        # bash on the stderr it has at that moment.
        f"if : 2>/dev/null >/dev/tty; then {command} >/dev/tty </dev/tty 2>&1;"
        f" else {command}; fi"
    )


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
    bound: Bound


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
        pulls = PULLS.validate_json(listed.stdout)
    except ValidationError as error:
        msg = f"gh returned something unreadable: {error}"
        raise RitualError(msg) from error
    # The exit code is data: `ls` matching nothing is the answer that no branch
    # was triaged, not a failure to look.
    found = await shell(rooted(f"ls -1 {TRIAGE_GLOB} 2>/dev/null"), stream=False)
    waiting = set(found.stdout.split())
    carried = [
        pull
        for pull in sorted(pulls, key=modified)
        if pull.branch != _MAIN
        and not wears(pull, WAIT_LABEL)
        and triage_path(pull.branch) in waiting
    ]
    if not carried:
        emit_delta("no pull request of yours is carrying a triage")
        return done(Shipped(outcome="nothing"))
    here = await _ran(_HERE, "could not read the current branch", stream=False)
    # You have just finished working on this branch and the triage on it is what
    # you sat down for. Anything else is a cast that moves you off it to page
    # something you were not thinking about — and it is also what keeps two
    # terminals on two branches from reaching for the same one.
    mine = here.stdout.strip()
    taking = next((pull for pull in carried if pull.branch == mine), carried[0])
    return goto(look, Branch(name=taking.branch, bound=components.bound))


@step
async def look(branch: Branch) -> Transition:
    path = triage_path(branch.name)
    await _ran(
        f"git checkout {quoted(branch.name)}", f"could not check out {branch.name}"
    )
    # Not read back: this is shown to you, on your terminal, and what it says is
    # the thing you are about to answer.
    await shell(paged(rooted(f"cat {quoted(path)}")))
    if not await decide(f"work on {branch.name}?"):
        return done(Shipped(outcome="declined", branch=branch.name))
    # An empty answer is an answer: the prompt below is already a complete
    # instruction, and saying nothing means "do that".
    told = await decide("what should be done with it?", free=True)
    return goto(work, Instructed(branch=branch, prompt=triage_work(path) + told))


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
        f"git push origin {quoted(branch.name)}", f"could not push {branch.name}"
    )
    return done(Shipped(outcome="shipped", branch=branch.name))
