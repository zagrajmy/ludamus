"""What the ritual says to git, gh and mise.

Command text and nothing else: every function here builds a string a step runs,
so what a step does stays readable as a decision rather than as quoting.
"""

import re
import shlex

from vekna.folio.shell import ShellResult, shell

# This project's two gates, by the names this project gives them.
PR_FIX = "mise run pr-fix"
COVERAGE = "mise run diff-cover"

# Every remote call these rituals make, over https rather than ssh: the sandbox
# remaps root to `nobody`, and ssh refuses an `/etc/ssh/ssh_config.d` it reads
# as owned by a stranger. Both remotes point at the same repository, so this is
# a route and not a destination.
# One name for fetching and pushing alike, because `ahead` counts against the
# remote-tracking ref a push moves: fetching from one and pushing to the other
# would report every branch it had just pushed as unpushed.
REMOTE = "https-origin"


# What a step actually runs a gate as. `CI=1` puts every tool in the chain into
# its log shape rather than its terminal one — no colour, no cursor tricks.
# Held apart from the names above because those are what the prompts say and
# what you would type yourself; nobody needs to read the prefix.
# It changes more than the rendering, and that is worth knowing before a gate's
# answer is read as the answer you would have got yourself: under `tests/e2e` it
# retries a failure twice before it counts, pins the workers, refuses
# `test.only`, and turns an empty client-coverage report into a failure.
def plain(task: str) -> str:
    return f"CI=1 {task}"


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
# Every review thread on this branch is answered and settled, and the gates were
# green when that happened. Put on by `pr_review` and nothing else: `pr_check`
# never reads the threads, so the night cannot claim it.
QA_LABEL = "pr::qa"
# Hands off this one. It is read at the listing and nowhere else, so a branch
# wearing it is never taken, never touched, and never reported on — which is
# the whole point: it is how you keep a pull request out of the night without
# closing it.
WAIT_LABEL = "pr::wait"

STASHED = "stashed"

# How much of a gate's output is worth paying for, counted in characters rather
# than lines: what is being spent is tokens, and a line has no fixed price —
# twenty lines of ruff is a couple of hundred bytes, and twenty carrying a
# pytest assertion repr or a mypy note about a long generic type is orders of
# magnitude more. A mise task list stops at the first failure, and every tool in
# it puts its verdict last — pytest's short summary, ruff's count — so what fits
# at the end is the part that says what is wrong. What sits above it is a suite
# naming three and a half thousand tests that passed, and an agent told to
# re-run one failing test by name does not need to read them.
BUDGET = 4000

# diff-cover's report is self-delimiting — its own banner, then everything to
# the end of the run — so the one caller that reads the report needs no budget
# at all. See `coverage_report`.
BANNER = "Diff Coverage"

# The report's own words for a line no test reached, read from the output
# because the exit code does not carry it: the task runs `diff-cover` with no
# `--fail-under`, so a run that names missing lines still ends 0. Both words and
# not just "Missing": the summary block says "Missing: 0 lines" on a clean
# report too, so the bare word matches every run there is.
MISSING = "Missing lines"


def quoted(value: str) -> str:
    return shlex.quote(value)


# Porcelain because a step puts an `if` around it: empty output is a clean
# worktree.
STATUS = "git status --porcelain"

# Where the worktree stands, which is not always the branch a step is working
# on.
HERE = "git rev-parse --abbrev-ref HEAD"


def checkout(branch: str) -> str:
    return f"git checkout {quoted(branch)}"


# The remote by name rather than the branch's upstream, which a branch a ritual
# has just merged on may not have. It is the one `ahead` counts against.
def push(branch: str) -> str:
    return f"git push {REMOTE} {quoted(branch)}"


# The review threads on a pull request, with everything either reader wants.
# GraphQL rather than `pulls/<number>/comments`, because the REST endpoint
# carries no resolution state: it answers a settled thread and a live one
# identically, and a cast that cannot tell them apart works twice.
# Both ids ride along, because `pr_review` replies and then settles: the reply
# endpoint takes `databaseId` and the mutation takes `id`.
_THREADS = """\
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) { nodes {
        id isResolved path line
        comments(first: 50) { nodes { databaseId author { login } body } } } } } } }"""


# One command, whoever runs it: a step counting what is outstanding and an agent
# reading what it says ask the same question of the same query.
# `gh` knows which repository this is, but graphql variables are not a REST path
# and nothing fills an `{owner}` in for them — so the slug is asked for once and
# split by the shell rather than by a second call.
def threads(number: int, *, part: str = "") -> str:
    asked = f" -q {quoted(part)}" if part else ""
    return (
        'slug="$(gh repo view --json nameWithOwner -q .nameWithOwner)" && '
        f"gh api graphql -f query={quoted(_THREADS)}"
        ' -f owner="${slug%/*}" -f repo="${slug#*/}"'
        f" -F number={number}{asked}"
    )


_OPEN_ONES = (
    "[.data.repository.pullRequest.reviewThreads.nodes[]"
    " | select(.isResolved | not)] | length"
)


# How many threads nobody has settled, which is the whole of what `pr_review`
# asks of a candidate — and, at the end, of the branch it just worked on.
def unsettled(number: int) -> str:
    return threads(number, part=_OPEN_ONES)


# Cursor moves and colour. `plain` above stops most of these being written at
# all; this is for the tools that colour anyway, and for a log captured before
# anyone thought about it. Stripped off everything this module hands on, agent
# and report alike: an escape code is not something either reader wants, and in
# `said` it is budget spent on cursor positions.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _plain_text(text: str) -> str:
    return _ANSI.sub("", text)


# The budget buys whole lines, and the last line is bought whether it fits or
# not: a tool that pretty-prints a value onto one long line would otherwise
# spend the budget and hand back nothing.
def _tail(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    left = BUDGET
    for line in reversed(lines):
        left -= len(line) + 1
        if left < 0 and kept:
            break
        kept.append(line)
    if len(kept) == len(lines):
        return "\n".join(lines)
    kept.reverse()
    return "\n".join([f"[{len(lines) - len(kept)} earlier lines omitted]", *kept])


# Both streams: a task that dies before it starts says so on stderr and nowhere
# else, and an empty complaint is the one thing a repair agent cannot work with.
# Each stream gets the budget on its own rather than sharing one, because mise
# puts its own task chatter on stderr and the tool's verdict on stdout, and a
# shared budget is won by whichever stream is longer — which is the chatter.
# Trimmed here rather than at each prompt, because every caller of this hands it
# to an agent and they all want the same thing: enough of the end to diagnose
# from. What the report puts in front of a person is `verdict` below, which is a
# different question and a much smaller answer.
def said(result: ShellResult) -> str:
    return "\n".join(
        _tail(_plain_text(part))
        for part in (result.stdout, result.stderr)
        if part.strip()
    )


# Cutting at diff-cover's own banner drops the suite transcript above it whole
# and hands on the listing entire, however many files it names. A budget has no
# business here: this listing is not something an agent reads for a verdict, it
# is the work list, and a tail of it is an agent asked to cover lines it was
# never shown — then another full unit and e2e run to reveal the rest. Only
# where the report never got printed does the trimmed log stand in for it.
def coverage_report(result: ShellResult) -> str:
    _, banner, rest = result.stdout.partition(BANNER)
    return banner + rest if banner else said(result)


# What a report row can carry, counted in lines because this one is read by a
# person: a dozen is the tail every tool in these chains puts its tally in.
VERDICT_LINES = 12


# The one-screen answer to "what went wrong", for the report rather than for an
# agent. Only one stream, unlike `said`: stdout is where every tool in these
# chains says how it ended — pytest's short summary, ruff's count, Playwright's
# tally — while stderr carries mise's task chatter and, under e2e, a web server
# logging every request it served, which is thousands of lines of nothing.
# Where stdout said nothing at all, stderr is all there is, and that is the task
# that died before it started.
# Blank lines go too: a progress reporter writing over itself leaves hundreds of
# them, and they would spend the whole allowance saying nothing.
def verdict(result: ShellResult) -> str:
    spoken = result.stdout if result.stdout.strip() else result.stderr
    lines = [
        stripped
        for line in _plain_text(spoken).splitlines()
        if (stripped := line.rstrip())
    ]
    return "\n".join(lines[-VERDICT_LINES:])


# Timings, counts and timestamps differ on every run, so two runs of the same
# broken suite never match character for character. What is left once the digits
# go is the failing test's name and the tool that named it, which is the thing
# worth recognising twice.
# ponytail: a different failure at the same file and a different line collides
# with this. What that costs is one branch's repair attempts skipped, and the
# report still says what it saw — worth more than a check that never fires.
def same_verdict(one: str, other: str) -> bool:
    return bool(one) and re.sub(r"\d+", "", one) == re.sub(r"\d+", "", other)


# Against everything the run has given up on, not just the last one: two things
# broken at once — a host that will not resolve and a browser that will not
# start — alternate down the queue, and a memo of one recognises neither.
def already_seen(one: str, seen: list[str]) -> bool:
    return any(same_verdict(one, other) for other in seen)


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
        f'if [ -n "$({STATUS})" ]; '
        f"then git stash push -u -m {quoted(stash_name(branch))} >/dev/null "
        f"&& echo {STASHED}; fi"
    )


# HEAD is asked for by name first, because it is not always this branch: a
# `set_aside` reached from a failed checkout is still standing on the base, and
# counting `<remote>/<branch>..HEAD` there measures the base against the branch
# and reports the answer as unpushed commits. A non-zero exit falls through to
# None below, which is exactly "we could not tell".
async def ahead(branch: str) -> int | None:
    counted = await shell(
        f'test {quoted(branch)} = "$({HERE})" && '
        f"git rev-list --count {quoted(f'{REMOTE}/{branch}..HEAD')}",
        stream=False,
    )
    if counted.exit_code:
        return None
    text = counted.stdout.strip()
    return int(text) if text.isdigit() else None
