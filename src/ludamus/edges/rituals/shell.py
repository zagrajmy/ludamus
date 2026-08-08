"""What the ritual says to git, gh and mise.

Command text and nothing else: every function here builds a string a step runs,
so what a step does stays readable as a decision rather than as quoting.
"""

import shlex

from vekna.folio.shell import ShellResult, shell

# This project's two gates, by the names this project gives them.
PR_FIX = "mise run pr-fix"
COVERAGE = "mise run diff-cover"

# `labels` rides along so the wait label can be read without a call per pull
# request: the listing is the only place every open branch is in hand at once.
LIST = (
    "gh pr list --author @me --state open "
    "--json number,title,headRefName,baseRefName,url,updatedAt,labels"
)

# This branch has had its review. Inline review comments are invisible to
# `gh pr view --json comments`, so a label is what the step can actually see —
# and a label is also something you can take off, which is the point: removing
# it is how you ask for the review again.
THERMO_LABEL = "pr::thermo"
QA_LABEL = "pr::qa"
# What this run put in front of a human to read: a quality review it posted, or
# a triage it wrote. A pull request that was already labelled reviewed on an
# earlier night does not earn the label again — the label marks the night's
# work, not the branch's history.
CR_LABEL = "pr::cr"
# Hands off this one. It is read at the listing and nowhere else, so a branch
# wearing it is never taken, never touched, and never reported on — which is
# the whole point: it is how you keep a pull request out of the night without
# closing it.
WAIT_LABEL = "pr::wait"

STASHED = "stashed"

# How much of a gate's output is worth paying for. A mise task list stops at the
# first failure, and every tool in it puts its verdict last — pytest's short
# summary, diff-cover's missing lines — so the tail is the part that says what
# is wrong. What sits above it is a suite naming three and a half thousand tests
# that passed, and an agent told to re-run one failing test by name does not
# need to read them.
TAIL = 20


def quoted(value: str) -> str:
    return shlex.quote(value)


# Both streams: a task that dies before it starts says so on stderr and nowhere
# else, and an empty complaint is the one thing a repair agent cannot work with.
# Trimmed here rather than at each prompt, because every caller does the same
# two things with this — hand it to an agent, or put it in the report — and both
# want the verdict, not the transcript.
def said(result: ShellResult) -> str:
    joined = "\n".join(part for part in (result.stdout, result.stderr) if part.strip())
    lines = joined.split("\n")
    if len(lines) <= TAIL:
        return joined
    dropped = len(lines) - TAIL
    return "\n".join([f"[{dropped} earlier lines omitted]", *lines[-TAIL:]])


def commit(message: str) -> str:
    return (
        "git add -A && (git diff --cached --quiet || "
        f"git commit -m {quoted(message)})"
    )


# Idempotent on gh's side, so a branch that already carries a label costs one
# call and no complaint. Several go on in one call rather than one apiece: two
# labels put on for the same reason should not be able to half-happen.
def label(*labels: str, number: int) -> str:
    added = " ".join(f"--add-label {quoted(one)}" for one in labels)
    return f"gh pr edit {number} {added}"


# The agent was told not to commit the merge, but a step checks rather than
# trusts: MERGE_HEAD is gone when it committed anyway, and then there is no
# merge left to continue.
CONTINUE_MERGE = (
    "if git rev-parse -q --verify MERGE_HEAD >/dev/null; then "
    "git add -A && git -c core.editor=true merge --continue; fi"
)


# Naming the stash is only worth anything if the morning report says the name,
# so the step that releases puts this in the row's note.
def stash_name(branch: str) -> str:
    return f"pr_check left {branch} unfinished"


# What a blocked pull request leaves behind. The next one begins with a clean
# worktree check, so an abandoned branch cannot be left dirty — and its work is
# not ours to throw away either. A conflicted merge goes back where it was; the
# rest goes into a named stash the report points at.
# The dirty check is what makes the report's claim true: `git stash push` on a
# clean tree exits 0 having saved nothing, so a note written off the exit code
# alone would name a stash that is not there. Echoing our own marker beats
# reading git's prose for the same answer.
def release(branch: str) -> str:
    return (
        "if git rev-parse -q --verify MERGE_HEAD >/dev/null; "
        "then git merge --abort; fi; "
        'if [ -n "$(git status --porcelain)" ]; '
        f"then git stash push -u -m {quoted(stash_name(branch))} >/dev/null "
        f"&& echo {STASHED}; fi"
    )


# HEAD is asked for by name first, because it is not always this branch: a
# `set_aside` reached from a failed checkout is still standing on the base, and
# counting `origin/<branch>..HEAD` there measures the base against the branch
# and reports the answer as unpushed commits. A non-zero exit falls through to
# None below, which is exactly "we could not tell".
async def ahead(branch: str) -> int | None:
    counted = await shell(
        f'test {quoted(branch)} = "$(git rev-parse --abbrev-ref HEAD)" && '
        f"git rev-list --count {quoted(f'https-origin/{branch}..HEAD')}",
        stream=False,
    )
    if counted.exit_code:
        return None
    text = counted.stdout.strip()
    return int(text) if text.isdigit() else None
