"""Push one branch, then act on the triage `pr_check` left on it.

    vekna cast ship [--bound N]

The follow-up to `pr_check`, and its opposite in every way that matters: it
takes exactly one branch, it asks you before it does anything, and it is the
thing that pushes. `pr_check` runs at 3am and never pushes; this runs while you
are sitting there and pushes nothing you have not read.

One branch, and then it stops. The first branch that is ahead of its upstream is
checked out, its unpushed diff is put through your pager, and you say yes or no.
Say no and the cast ends there. Say yes and it is pushed — after which, if the
branch carries a `triage.md`, you are shown it and asked what to do with it, and
an agent does that: fixes what you said to fix, answers and resolves the review
threads either way, and files the rest as issues.

Then you read what it did and say `fix` or `ship`. `fix` takes another
instruction and hands it to the same agent, which remembers the round before.
`ship` runs this project's two gates, repairs them up to `--bound` times, and
commits and pushes what came out.

Nothing here is a queue, which is what makes it safe to run in several terminals
at once: each cast takes the first branch that is ahead and leaves the rest
alone. Two casts started at the same second in two workspaces can still pick the
same branch — locks are not shipped yet — but a cast that ends with a push takes
that branch out of every later cast's reckoning, so starting the next terminal
after this one has pushed is the whole protocol.
"""

from typing import Literal

from pydantic import BaseModel
from vekna.folio.flow import decide
from vekna.folio.shell import shell
from vekna.lexicon import RitualError, Transition, done, emit_delta, goto, ritual, step

from .agent import COVER, THREADS, ask, fix_gates
from .shell import COVERAGE, PR_FIX, commit, coverage_report, plain, quoted, said
from .state import Bound

# The human loop above has no business bound — it goes round as long as you keep
# saying `fix`, which is a person spending their own evening. This is the
# engine's backstop and nothing else.
_MAX_STEPS = 200

# Every agent call in the cast joins one thread, so the round you asked for
# after reading the last one meets an agent that remembers writing it.
_THREAD = "ship"

# Never this one, whatever git says about it. `git push` here reads the branch's
# upstream, so a main that is ahead would push straight to it.
MAIN = "main"

# The branch selection, in git's words rather than porcelain's: `git branch -v`
# prints the same `[ahead N]` but wraps it in a subject line, and this format has
# nothing else on the line to match by accident. `grep` finding nothing exits 1
# into a pipe, so the pipeline still ends 0 with an empty answer — which is the
# answer: nothing is waiting to be pushed.
AHEAD = (
    "git for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads/ "
    f"| grep -F '[ahead' | grep -v {quoted(f'^{MAIN} ')} | head -1 | cut -d' ' -f1"
)

# Local tracking refs are what `[ahead` is read off, and a sibling workspace that
# pushed a branch ten minutes ago left this clone still believing it is unpushed.
FETCH = "git fetch --prune"

# What is on this branch and not on its upstream.
DIFF = f"git diff {quoted('@{u}...HEAD')}"

# diff-cover runs without `--fail-under`, so a report naming lines no test
# reaches still exits 0. The words are the verdict.
MISSING = "Missing lines"


# The one place this ritual writes to the terminal instead of into the rite.
# `>/dev/tty` gives the command a terminal, so `git diff` pages and you can
# scroll it; `</dev/tty` is where the pager reads your keys, since the cast holds
# stdin for its own prompts. Whether that terminal is there at all is asked
# first, and not by running the command and reading its exit code: quitting the
# pager early kills `git diff` with a broken pipe, and a fallback hung off that
# would answer by dumping the whole diff you just walked away from.
def paged(command: str) -> str:
    return (
        # `2>/dev/null` first, because a redirection that fails is reported by
        # bash on the stderr it has at that moment.
        f"if : 2>/dev/null >/dev/tty; then {command} >/dev/tty </dev/tty 2>&1;"
        f" else {command}; fi"
    )


class Ship(BaseModel):
    bound: Bound = 3


class Branch(BaseModel):
    name: str
    bound: Bound


class Instructed(BaseModel):
    branch: Branch
    instructions: str
    # The first round has to say what the job is. Later rounds land in the same
    # keyed session, which already knows, and repeating it there would argue
    # with what the agent has just been told.
    opening: bool = False


class Landing(BaseModel):
    branch: Branch
    tries: int = 0


class Shipped(BaseModel):
    branch: str = ""
    pushed: bool = False
    triaged: bool = False


Move = Literal["fix", "ship"]
_MOVES: tuple[Move, ...] = ("fix", "ship")


# Held apart from the prompt only to keep its braces out of an f-string.
_RESOLVE = """\
gh api graphql -f query='mutation($id: ID!) {
  resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }' \\
  -f id=<thread id>\
"""

_TRIAGE_WORK = f"""\
`triage.md` at the repository root is a triage of this branch's open review
comments, written last night. The threads it was written from are still open on
the pull request. Read the file, then work through it as I say at the end.

The pull request is this branch's: `gh pr view --json number,url`. Read its open
threads with

{THREADS}

and skip every node with `isResolved: true` — somebody has already settled it.

Whatever you do with an item, the thread it came from ends up answered and
resolved, so that nothing is triaged twice:

- Fixed: make the change, reply saying what changed, resolve the thread.
- Rejected: reply saying why it will not be done, resolve the thread.
- Filed: use the `issue-maker` skill to open the issue, reply with its link,
  resolve the thread.

Reply on a thread with its first comment's `databaseId`:

    gh api repos/{{owner}}/{{repo}}/pulls/comments/<databaseId>/replies -f body=<text>

Write `{{owner}}/{{repo}}` literally — gh fills both in. Then resolve it:

{_RESOLVE}

Leave `triage.md` saying only what is still outstanding, and delete it when
nothing is: it is this branch's work list, and an item you have just answered is
not on it any more.

Do not commit and do not push — the ritual owns both, and runs the gates itself
the moment you stop. Ask me rather than guessing when the call is mine to make.

What I want done:

"""


@ritual("ship", max_steps=_MAX_STEPS)
def ship(components: Ship) -> Transition:
    return goto(pick, Ship(bound=components.bound))


@step
async def pick(components: Ship) -> Transition:
    # Fatal, and first: this checks out a branch and later commits everything it
    # finds, so work sitting in the tree now would be carried onto someone
    # else's branch and committed there.
    status = await shell("git status --porcelain", stream=False)
    if status.exit_code:
        msg = f"git status failed: {said(status)}"
        raise RitualError(msg)
    if dirty := status.stdout.strip():
        msg = f"the worktree is not clean:\n{dirty}"
        raise RitualError(msg)
    fetched = await shell(FETCH)
    if fetched.exit_code:
        msg = f"could not fetch: {said(fetched)}"
        raise RitualError(msg)
    found = await shell(AHEAD, stream=False)
    if found.exit_code:
        msg = f"could not list the branches: {said(found)}"
        raise RitualError(msg)
    if not (name := found.stdout.strip()):
        emit_delta("nothing is ahead of its upstream")
        return done(Shipped())
    return goto(look, Branch(name=name, bound=components.bound))


@step
async def look(branch: Branch) -> Transition:
    taken = await shell(f"git checkout {quoted(branch.name)}")
    if taken.exit_code:
        msg = f"could not check out {branch.name}: {said(taken)}"
        raise RitualError(msg)
    # Not read back: this is shown to you, on your terminal, and what it says is
    # the thing you are about to answer.
    await shell(paged(DIFF))
    if not await decide(f"push {branch.name}?"):
        return done(Shipped(branch=branch.name))
    return goto(push_branch, branch)


@step
async def push_branch(branch: Branch) -> Transition:
    pushed = await shell("git push")
    if pushed.exit_code:
        msg = f"could not push {branch.name}: {said(pushed)}"
        raise RitualError(msg)
    carried = await shell("test -f triage.md")
    if carried.exit_code:
        return done(Shipped(branch=branch.name, pushed=True))
    return goto(read_triage, branch)


@step
async def read_triage(branch: Branch) -> Transition:
    await shell(paged("cat triage.md"))
    # An empty answer is an answer: the prompt below is already a complete
    # instruction, and saying nothing means "do that".
    told = await decide("what should be done with it?", free=True)
    return goto(work, Instructed(branch=branch, instructions=told, opening=True))


# The agent writes code, opens issues and answers review threads, so it runs at
# vekna's `bypassPermissions` default — deliberately, and it is why this ritual
# only ever reaches here on a branch you have looked at and pushed yourself. Its
# own tool prompts still reach you: you are sitting in front of it.
@step
async def work(instructed: Instructed) -> Transition:
    prompt = (
        _TRIAGE_WORK + instructed.instructions
        if instructed.opening
        else instructed.instructions
    )
    if fallen := await ask(prompt, key=_THREAD):
        raise RitualError(fallen.reason)
    return goto(hand_back, instructed.branch)


@step
async def hand_back(branch: Branch) -> Transition:
    if await decide("fix something else, or ship it?", options=_MOVES) == "ship":
        return goto(gates, Landing(branch=branch))
    more = await decide("what should it fix?", free=True)
    return goto(work, Instructed(branch=branch, instructions=more))


# Spending another agent attempt is normally yours to approve, and here it is
# not: you asked for `ship`, which is the approval. What holds the loop is the
# bound.
async def _fix(landing: Landing, prompt: str) -> None:
    if landing.tries >= landing.branch.bound:
        msg = f"the gates are still red after {landing.tries} attempts"
        raise RitualError(msg)
    if fallen := await ask(prompt, key=_THREAD):
        raise RitualError(fallen.reason)


def _again(landing: Landing) -> Landing:
    return Landing(branch=landing.branch, tries=landing.tries + 1)


@step
async def gates(landing: Landing) -> Transition:
    # Captured rather than streamed, and run `plain`: what comes back is read by
    # an agent, and a terminal recording is not that.
    ran = await shell(plain(PR_FIX), stream=False)
    if ran.exit_code:
        await _fix(landing, fix_gates(said(ran)))
        return goto(gates, _again(landing))
    covered = await shell(plain(COVERAGE), stream=False)
    report = coverage_report(covered)
    if MISSING in report:
        await _fix(landing, COVER + report)
        return goto(gates, _again(landing))
    if covered.exit_code:
        await _fix(landing, fix_gates(said(covered), gate=COVERAGE))
        return goto(gates, _again(landing))
    return goto(land, landing.branch)


@step
async def land(branch: Branch) -> Transition:
    landed = await shell(commit("chore: act on the review triage"))
    if landed.exit_code:
        msg = f"could not commit the triage work: {said(landed)}"
        raise RitualError(msg)
    pushed = await shell("git push")
    if pushed.exit_code:
        msg = f"could not push {branch.name}: {said(pushed)}"
        raise RitualError(msg)
    return done(Shipped(branch=branch.name, pushed=True, triaged=True))
