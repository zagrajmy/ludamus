"""What the ritual says to git, gh and mise, and what it makes of the answer.

Every command a step runs is built here, and every reading of what came back is
written beside the command it reads — so what a step does stays readable as a
decision rather than as quoting.
"""

import re
import shlex

from pydantic import TypeAdapter, ValidationError
from vekna.folio.shell import ShellResult, shell

from .state import WAIT_LABEL, Check, PullRequest, wears

# This project's two gates, by the names this project gives them.
PR_FIX = "mise run pr-fix"
COVERAGE = "mise run diff-cover"

# The same measurement without the browser: the unit and integration suites and
# the diff report, and no Playwright boot behind it. What a repair loop re-runs
# to find out whether the tests an agent just wrote landed — `COVERAGE` is what
# says so for the record, and it runs once, at the end.
# It reads `.coverage.unit` alone, so a line only the e2e suite reaches shows up
# here as uncovered. That makes it a superset of what is really missing, which
# is the safe direction for a loop: it never calls a gap closed that is not, and
# the prompt says which measurement this is. See `COVER`.
FAST_COVERAGE = "mise run test:py:cov:diff"

# Every remote call these rituals make, over https rather than ssh: the sandbox
# remaps root to `nobody`, and ssh refuses an `/etc/ssh/ssh_config.d` it reads
# as owned by a stranger. Both remotes point at the same repository, so this is
# a route and not a destination.
# One name for fetching and pushing alike, because `ahead` counts against the
# remote-tracking ref a push moves: fetching from one and pushing to the other
# would report every branch it had just pushed as unpushed.
REMOTE = "https-origin"


# `CI=1` puts every tool in the chain into its log shape rather than its
# terminal one — no colour, no cursor tricks. Held apart from the names above
# because those are what the prompts say and what you would type yourself.
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

PULLS: TypeAdapter[list[PullRequest]] = TypeAdapter(list[PullRequest])


# A sort key, and it has to be spelled out: `attrgetter` is `attrgetter[Any]`
# and a lambda's parameter is untyped, so mypy rejects both here. This is the
# only shape of the three that carries a type.
def modified(pull: PullRequest) -> str:
    return pull.updated_at


# Both rituals ask the same question of `LIST` and differ only in what they do
# when it will not parse, so the answer is written once and the routing stays
# with each caller.
# Parked branches are dropped here rather than skipped later, so one is never
# checked out, never counted as reached, and never in a report at all.
# Oldest-modified first: the branch drifting from its base the longest is the
# one most likely to need the night.
def wanted(listing: str) -> list[PullRequest]:
    pulls = PULLS.validate_json(listing)
    return sorted((pull for pull in pulls if not wears(pull, WAIT_LABEL)), key=modified)


# What CI made of the branch as it stands. Asked rather than assumed, and only
# by the slow pass: the whole point of it is not to spend an hour of suites on a
# pull request whose coverage and tests are already green on the server.
# The exit code is deliberately ignored by the caller — `gh pr checks` answers
# non-zero for a failing or pending run, which is the answer being asked for.
def checks(number: int) -> str:
    return f"gh pr checks {number} --json name,state"


CHECKS: TypeAdapter[list[Check]] = TypeAdapter(list[Check])

# The checks whose unhappiness the slow pass exists to answer: codecov posts
# `codecov/patch` and `codecov/project` (plus `/client` variants), and the suite
# runs as `test` and `test-postgres`.
_COVER_CHECKS = ("codecov/", "test")
_PASSED = "SUCCESS"


# True unless the pull request positively says otherwise: a listing that will
# not parse, a `gh` that would not answer, a branch CI has not reported on yet —
# all of them mean nobody has told us the coverage is fine, and the slow pass is
# the thing that finds out. Only a green codecov and a green suite buy a skip.
def wants_cover(listing: str) -> bool:
    try:
        checked = CHECKS.validate_json(listing)
    except ValidationError:
        return True
    watched = [check for check in checked if check.name.startswith(_COVER_CHECKS)]
    return not watched or any(check.state != _PASSED for check in watched)


# The CI jobs the gate would only be running again: `checks` is the linters and
# the translation catalogue, `test` and `test-postgres` are the suite, and
# `pr-fix` is both of them. The rest of the board is not this pass's business —
# tingle counts debt, codecov belongs to the slow pass, the code readers post
# comments — and no amount of `pr-fix` turns any of it green, so a red one there
# is not worth the hour.
_GATE_CHECKS = ("checks", "test")


# False where nobody has said — an empty listing, a `gh` that would not answer,
# a check still running — because the gate is what finds out, and a skip granted
# on silence is a red branch pushed and reviewed as green.
def gates_green(listing: str) -> bool:
    try:
        checked = CHECKS.validate_json(listing)
    except ValidationError:
        return False
    watched = [check for check in checked if check.name.startswith(_GATE_CHECKS)]
    return bool(watched) and all(check.state == _PASSED for check in watched)


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
# Every caller hands this to an agent, so the trimming happens here rather than
# at each prompt. What a person is shown is `verdict` below, a smaller answer to
# a different question.
def said(result: ShellResult) -> str:
    return "\n".join(
        _tail(_plain_text(part))
        for part in (result.stdout, result.stderr)
        if part.strip()
    )


# A budget has no business here: this listing is not something an agent reads
# for a verdict, it is the work list, and a tail of it is an agent asked to
# cover lines it was never shown — then another full unit and e2e run to reveal
# the rest. The banner is what the transcript above it can be cut at. Only where
# the report never got printed does the trimmed log stand in for it.
def coverage_report(result: ShellResult) -> str:
    _, banner, rest = result.stdout.partition(BANNER)
    return banner + rest if banner else said(result)


# What a report row can carry, counted in lines because this one is read by a
# person: a dozen is the tail every tool in these chains puts its tally in.
VERDICT_LINES = 12


# For the report rather than for an agent, so only one stream, unlike `said`:
# stdout is where every tool in these chains says how it ended — pytest's short
# summary, ruff's count, Playwright's tally — while stderr carries mise's task
# chatter and, under e2e, a web server logging every request it served, which is
# thousands of lines of nothing.
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


# How mise names the task that failed: the leaf's own name, in the prefix it
# labels that task's output with. A chain stops at the first failure, so the
# first match is the one that broke and anything after it is a parent repeating
# the news.
_FAILED_TASK = re.compile(r"^\[([\w:.-]+)] ERROR task failed", re.MULTILINE)


# The one task worth re-running while a repair is underway, instead of the whole
# gate: `pr-fix` reinstalls three package managers and formats the repository
# before it reaches the thing that is broken, and paying for that once per
# attempt is most of what a repair loop costs. The whole gate still runs, once,
# when the narrow one goes green — a task passing on its own is not the gate
# passing.
# Empty where the output does not say: a gate that died before mise named
# anything, or a shape mise no longer prints. Then the caller runs the gate it
# would have run anyway.
def narrowed(result: ShellResult) -> str:
    for part in (result.stdout, result.stderr):
        if found := _FAILED_TASK.search(_plain_text(part)):
            return f"mise run {found.group(1)}"
    return ""


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
    return f"a pr sweep left {branch} unfinished"


# The next pull request begins with a clean worktree check, so an abandoned
# branch cannot be left dirty — and its work is not ours to throw away either.
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
