"""Nighttime pull request maintenance, one pull request at a time.

    vekna cast pr_check [--bound N]

Every pull request you have open is taken in turn, oldest-modified first: its
base branch is merged in, the gates are made green, the coverage gap is closed,
the night's work is pushed, and a quality review is posted unless the branch
already carries ``pr::thermo``. A branch ends the night green or blocked, and
the report says which.

What the night does not do is read the review it posted. Answering a review is
somebody's decision and this runs at 3am with nobody to ask — so every action
item stays an open thread, and ``pr_review`` is the cast that goes through them with
you in the morning.

The push comes before the review and not after: an inline review comment has to
anchor to a line of the pull request's diff, and a line that exists only in this
clone is a line GitHub answers 422 on. So a review of unpushed work is a review
that loses half its comments to the fallback.

A branch the gates would not go green on is still reviewed. It stands down
rather than stopping: the worktree is released, so the reading happens on the
last commit that was any good, and then it is reviewed like any other before
being reported blocked. This is not a gate and does not try to fail fast — an
hour more spent is worth a pull request read properly.

A pull request labelled ``pr::wait`` is left alone entirely: it is dropped at
the listing, so nothing checks it out and it appears nowhere in the report.
That is how you park a branch for a night — or for a month — without closing
it.

The review is one inline comment per action item, anchored to the code it is
about, and the branch is labelled ``pr::thermo`` once it is posted. That label
is the only thing standing between a branch and another review: drop it after
changing the branch meaningfully, and the next run reviews it again.

A blocked branch's review is provisional, and the label goes on all the same.
The code it read is by construction about to change — you fix the gate in the
morning, and that is a meaningful change, so this is one of the times to take
the label off. It is kept rather than withheld because a branch that stays red
for a week would otherwise be reviewed from scratch every night of it.

It runs unattended, so it asks you nothing. That is a deliberate break with the
usual bargain, where spending another agent attempt is a ``decide``: at 3am a
prompt is a hang, so the budgets below take that decision instead. Agents still
work permissively inside a step, and what holds them is still the step boundary
— a gate is green or it is not, a budget is spent or it is not.

Two things end the whole run rather than one branch: a worktree that is not
clean, and an agent that dies mid-flight (a spent token budget, a killed CLI).
Both still print the report first, then fail the cast.

Budgets are per step and per branch: a step may be retried ``--bound`` times,
going green clears its count, and moving to the next pull request clears them
all. A step that runs out stops trying to fix that pull request only: the
worktree is released, the branch stands down into the reading above, and it is
reported blocked. A verdict a step already gave up on once is not paid for
twice — the next branch whose gate says the same thing stands down without
spending its budget on an answer this run already has.
"""

from pydantic import ValidationError
from vekna.folio.shell import shell
from vekna.lexicon import RitualError, Transition, done, emit_delta, goto, ritual, step

from .agent import COVER, ask, fix_gates, resolve, thermo
from .shell import (
    CONTINUE_MERGE,
    COVERAGE,
    LIST,
    MISSING,
    PR_FIX,
    REMOTE,
    STASHED,
    THERMO_LABEL,
    ahead,
    already_seen,
    commit,
    coverage_report,
    label,
    plain,
    quoted,
    release,
    said,
    stash_name,
    verdict,
)
from .state import (
    Checked,
    Closed,
    Labels,
    PrCheck,
    Run,
    Work,
    abandoned,
    charged,
    cleared,
    exhausted,
    joined,
    report_card,
    run_with,
    spent,
    summary,
    telling,
    unreadable,
    wanted,
    work_with,
)

# The backstop, not the control — the per-step bounds are. Six pull requests
# through ~9 steps each, with three repair loops that may each burn `--bound`
# extra turns, comes to a little under 200 at the maximum bound; this sits
# above that, because tripping it costs the report as well as the run.
_MAX_STEPS = 240


@ritual("pr_check", max_steps=_MAX_STEPS)
def pr_check(components: PrCheck) -> Transition:
    return goto(list_prs, Run(bound=components.bound))


@step
async def list_prs(run: Run) -> Transition:
    # `gh`, not an agent holding a fetch tool: it reads private repositories,
    # returns JSON, and listing needs no judgement.
    listed = await shell(LIST, stream=False)
    if listed.exit_code:
        reason = f"gh could not list your pull requests: {listed.stderr.strip()}"
        return goto(report, run_with(run, stopped=reason))
    try:
        queue = wanted(listed.stdout)
    except ValidationError as error:
        return goto(report, run_with(run, stopped=unreadable(error)))
    return goto(next_pr, run_with(run, queue=queue))


@step
def next_pr(run: Run) -> Transition:
    if not run.queue:
        return goto(report, run)
    pull, *rest = run.queue
    # A fresh Work per pull request, so no budget survives the branch change.
    return goto(check_clean, Work(run=run_with(run, queue=rest), pr=pull))


@step
async def check_clean(work: Work) -> Transition:
    status = await shell("git status --porcelain", stream=False)
    if status.exit_code:
        return goto(report, abandoned(work, f"git status failed: {said(status)}"))
    if dirty := status.stdout.strip():
        # Fatal by design: everything below this line moves branches around, and
        # doing that over someone's uncommitted work is how it gets lost.
        return goto(report, abandoned(work, f"the worktree is not clean:\n{dirty}"))
    return goto(sync_branch, work)


@step
async def sync_branch(work: Work) -> Transition:
    pull = work.pr
    synced = await shell(
        f"git fetch --prune {REMOTE} && git checkout {quoted(pull.base)}"
        f" && git pull --ff-only {REMOTE} {quoted(pull.base)}"
    )
    if synced.exit_code:
        reason = f"could not update {pull.base}: {said(synced)}"
        return goto(report, abandoned(work, reason))
    # `merge --ff-only`, never `reset --hard`: a branch this ritual worked on
    # last night carries commits the remote has not seen, and they are the whole
    # point of the report. A branch that has genuinely diverged stops here.
    taken = await shell(
        f"git checkout {quoted(pull.branch)} && "
        f"git merge --ff-only {quoted(f'{REMOTE}/{pull.branch}')}"
    )
    if taken.exit_code:
        return goto(
            set_aside, work_with(work, note=f"could not take the branch: {said(taken)}")
        )
    return goto(merge_base, work)


@step
async def merge_base(work: Work) -> Transition:
    merged = await shell(f"git merge --no-edit {quoted(work.pr.base)}")
    if merged.exit_code == 0:
        return goto(gate_check, work)
    unmerged = await shell("git diff --name-only --diff-filter=U", stream=False)
    # A merge fails for reasons no agent can fix — a stale index lock, a missing
    # ref — and those are not conflicts. Unmerged paths are what a conflict is.
    if not unmerged.stdout.strip():
        return goto(
            set_aside,
            work_with(work, note=f"git merge failed without conflicts: {said(merged)}"),
        )
    return goto(resolve_conflicts, work_with(work, merging=True))


@step
async def resolve_conflicts(work: Work) -> Transition:
    unmerged = await shell("git diff --name-only --diff-filter=U", stream=False)
    if not unmerged.stdout.strip():
        return goto(gate_check, cleared(work, resolve_conflicts.name))
    if exhausted(work, resolve_conflicts.name):
        return goto(
            stand_down, work_with(work, reason="the merge conflicts were not resolved")
        )
    if fallen := await ask(
        resolve(base=work.pr.base, branch=work.pr.branch, files=unmerged.stdout),
        key=f"merge-{work.pr.number}",
    ):
        return goto(report, abandoned(work, fallen.reason))
    # Back through this same step, which re-reads git rather than believing the
    # agent: what decides whether the conflict is gone is the index.
    return goto(resolve_conflicts, charged(work, resolve_conflicts.name))


@step
async def gate_check(work: Work) -> Transition:
    # Captured rather than streamed, and run `plain`: what comes back here is
    # read twice over — once by an agent, once by you in the morning — and a
    # terminal recording is neither.
    gates = await shell(plain(PR_FIX), stream=False)
    if gates.exit_code == 0:
        return goto(finish_merge, cleared(work, gate_check.name))
    said_now = verdict(gates)
    # Asked before the first repair and not after, so this reads "the branch
    # arrived broken the same way", never "the agent failed to fix it twice".
    if not spent(work, gate_check.name) and already_seen(said_now, work.run.seen):
        return goto(
            stand_down,
            work_with(work, reason=f"`{PR_FIX}` is red as it already was:\n{said_now}"),
        )
    if exhausted(work, gate_check.name):
        return goto(
            stand_down,
            work_with(
                work,
                reason=f"`{PR_FIX}` is still red:\n{said_now}",
                run=run_with(work.run, seen=[*work.run.seen, said_now]),
            ),
        )
    if fallen := await ask(fix_gates(said(gates)), key=f"gates-{work.pr.number}"):
        return goto(report, abandoned(work, fallen.reason))
    return goto(gate_check, charged(work, gate_check.name))


@step
async def finish_merge(work: Work) -> Transition:
    if work.merging:
        continued = await shell(CONTINUE_MERGE)
        if continued.exit_code:
            return goto(
                set_aside,
                work_with(work, note=f"could not finish the merge: {said(continued)}"),
            )
    # A clean merge leaves the gate repairs uncommitted, and a merge the agent
    # committed itself leaves them behind too. Either way this is where they
    # land — and it is a no-op when there is nothing to land.
    landed = await shell(commit(f"chore: merge {work.pr.base} and fix the gates"))
    if landed.exit_code:
        return goto(
            set_aside,
            work_with(work, note=f"could not commit the merge: {said(landed)}"),
        )
    return goto(cover, work_with(work, merging=False))


@step
async def cover(work: Work) -> Transition:
    measured = await shell(plain(COVERAGE), stream=False)
    output = coverage_report(measured)
    missing = MISSING in output
    if not missing and measured.exit_code == 0:
        # Only where tests were actually written: most branches pass here first
        # time, and a commit rite that can never commit anything is noise in the
        # tree.
        if spent(work, cover.name):
            landed = await shell(commit("test: cover the lines this branch changes"))
            if landed.exit_code:
                return goto(
                    set_aside,
                    work_with(work, note=f"could not commit the tests: {said(landed)}"),
                )
        return goto(push_work, cleared(work, cover.name))
    said_now = verdict(measured)
    # Two different jobs down one budget, because they are the same step going
    # round: lines this branch left uncovered are written up as tests, and a
    # suite that will not pass at all is repaired like any other red gate. The
    # second used to end the branch here — a red suite names no missing lines,
    # so it was read as the coverage tool failing rather than the branch.
    # Which of the two this is decides four things, so it is asked once here and
    # the branches below read straight. Only a red suite is worth remembering
    # across the night: what lines a branch left uncovered is that branch's own
    # business, and two of them missing lines in the same file look identical
    # from here. A suite that will not pass is the thing that repeats.
    if missing:
        left, asking, run = "still reports missing lines", COVER + output, work.run
    else:
        left = "is still red"
        asking = fix_gates(said(measured), gate=COVERAGE)
        run = run_with(work.run, seen=[*work.run.seen, said_now])
    # Against what the run knew on the way in, never `run` above: that one has
    # this verdict in it already and would recognise nothing but itself.
    if (
        not missing
        and not spent(work, cover.name)
        and already_seen(said_now, work.run.seen)
    ):
        return goto(
            stand_down,
            work_with(
                work, reason=f"`{COVERAGE}` failed as it already did:\n{said_now}"
            ),
        )
    if exhausted(work, cover.name):
        return goto(
            stand_down,
            work_with(work, reason=f"`{COVERAGE}` {left}:\n{said_now}", run=run),
        )
    if fallen := await ask(asking, key=f"cover-{work.pr.number}"):
        return goto(report, abandoned(work, fallen.reason))
    return goto(cover, charged(work, cover.name))


# Everything the night made of this branch goes up before it is reviewed: an
# inline comment has to name a line of the pull request's diff, and work sitting
# in this clone is not in it. The remote is named rather than left to the
# branch's upstream, because a branch this run created a merge on may have none.
# Not fatal, and not `set_aside`: a push that will not go through — someone
# else's commit on the branch, a network that is gone — costs the review its
# anchors and nothing else, and a review of code you can still read is worth
# more than a branch dropped for the night. What is left behind says so twice
# over: in this note, and in the row's own `unpushed`, which is counted off git
# at the end, whoever left it there.
@step
async def push_work(work: Work) -> Transition:
    pushed = await shell(f"git push {REMOTE} {quoted(work.pr.branch)}")
    if pushed.exit_code:
        left = f"could not push: {said(pushed)}"
        return goto(quality_review, work_with(work, note=joined(work.note, left)))
    return goto(quality_review, work)


# Where a branch's night ends, whichever way it went: green means the gates went
# green and the review is up, and blocked means it did not — the reviews are not
# the night's to have an opinion about, and `pr_review` is what answers them.
def _ended(work: Work) -> Closed:
    return Closed(work=work, outcome="blocked" if work.blocked else "green")


# The one step with no budget and no loop, because there is nothing here to
# retry against. The other three read back what the agent did — the index, the
# gate, the coverage report — and go round again while it is still wrong. What
# this step would read back is the review it just asked for, and an agent that
# posted nothing at all is indistinguishable from one that found nothing to
# post. So the label goes on unconditionally, and a review that came out empty
# is yours to notice and ask for again by taking it off.
@step
async def quality_review(work: Work) -> Transition:
    seen = await shell(f"gh pr view {work.pr.number} --json labels", stream=False)
    if seen.exit_code:
        return goto(
            set_aside,
            work_with(
                work, note=f"gh could not read the labels: {seen.stderr.strip()}"
            ),
        )
    try:
        labels = Labels.model_validate_json(seen.stdout)
    except ValidationError as error:
        unread = f"gh returned labels this could not read: {error}"
        return goto(set_aside, work_with(work, note=unread))
    # An earlier night's review, which is not this night's work to label.
    if any(one.name == THERMO_LABEL for one in labels.labels):
        return goto(finish_pr, _ended(work))
    if fallen := await ask(
        thermo(number=work.pr.number, base=work.pr.base, reason=work.reason),
        key=f"review-{work.pr.number}",
    ):
        return goto(report, abandoned(work, fallen.reason))
    marked = await shell(label(THERMO_LABEL, number=work.pr.number))
    if marked.exit_code:
        reason = f"could not label the review just posted: {said(marked)}"
        return goto(set_aside, work_with(work, note=reason))
    return goto(finish_pr, _ended(work))


@step
async def finish_pr(closed: Closed) -> Transition:
    work = closed.work
    row = Checked(
        number=work.pr.number,
        branch=work.pr.branch,
        url=work.pr.url,
        outcome=closed.outcome,
        # Asked of git rather than tracked in the payload: what needs pushing is
        # what origin has not got, whoever put it there.
        unpushed=await ahead(work.pr.branch),
        note=telling(work),
    )
    run = work.run
    return goto(next_pr, run_with(run, checked=[*run.checked, row]))


# Giving the worktree back, and what that has to say for itself. Both endings
# below do this and only one of them stops here, so it is written once. What
# comes back is this act's own bookkeeping and nothing else — the callers join
# it to whatever else the row is carrying.
async def _released(work: Work) -> str:
    released = await shell(release(work.pr.branch))
    if released.exit_code:
        return f"the worktree could not be released: {said(released)}"
    if released.stdout.strip() == STASHED:
        return f'stashed as "{stash_name(work.pr.branch)}"'
    return ""


# A branch that will not go green, which is not the same as a branch that
# cannot be read. The worktree goes back first — half a repair is not something
# to review and not something to commit a triage on top of — and then it takes
# the same reading every other pull request gets. It is the steps above this
# that cannot come here: a checkout that failed leaves you standing on the base
# branch, and there is nothing there to review.
@step
async def stand_down(work: Work) -> Transition:
    return goto(push_work, work_with(work, note=await _released(work), blocked=True))


@step
async def set_aside(work: Work) -> Transition:
    # The worktree goes back before the count, not as an argument alongside it:
    # what is left to push is asked of a tree this step has finished with.
    released = await _released(work)
    row = Checked(
        number=work.pr.number,
        branch=work.pr.branch,
        url=work.pr.url,
        outcome="blocked",
        unpushed=await ahead(work.pr.branch),
        # A branch that stood down and then failed one of the reading steps
        # arrives here with two things to say, and the second must not cost it
        # the first: the morning needs to hear the red gate, not only the `gh`
        # call that came after it.
        # ponytail: that branch does lose the stash name its first release
        # wrote, because the reading step's own note replaced it. `stash_name`
        # is the branch and the row says the branch, so the name is still
        # derivable; a third slot to keep it whole is not worth the field.
        note=telling(work, released),
    )
    run = work.run
    return goto(next_pr, run_with(run, checked=[*run.checked, row]))


# Nothing to await: this routes and renders, and the contract lets a step say
# so. The summary is emitted before the failure is raised, which is the whole
# reason every ending routes here rather than raising where it happened.
@step
def report(run: Run) -> Transition:
    emit_delta(summary(run))
    if run.stopped:
        raise RitualError(run.stopped)
    return done(report_card(run))
