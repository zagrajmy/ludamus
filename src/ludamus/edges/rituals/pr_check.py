"""Nighttime pull request maintenance, one pull request at a time.

    vekna cast pr_check [--bound N]

Every pull request you have open is taken in turn, oldest-modified first: its
base branch is merged in, the gates are made green, the coverage gap is closed,
a quality review is posted unless the branch already carries ``pr::thermo``, and
the open review comments are triaged. A branch ends the night either labelled
``pr::qa`` with a ``qa.md`` of manual scenarios, or carrying a ``triage.md``
that says what still has to be done. Whatever this run put in front of you to
read — a quality review it posted, a triage it wrote — also earns the branch
``pr::cr``. Nothing is ever pushed: the report says which branches are waiting
for that, and pushing stays yours.

A pull request labelled ``pr::wait`` is left alone entirely: it is dropped at
the listing, so nothing checks it out and it appears nowhere in the report.
That is how you park a branch for a night — or for a month — without closing
it.

The review is one inline comment per action item, anchored to the code it is
about, and the branch is labelled ``pr::thermo`` once it is posted. That label
is the only thing standing between a branch and another review: drop it after
changing the branch meaningfully, and the next run reviews it again.

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
all. A step that runs out gives up on that pull request only — the worktree is
released, the branch is reported blocked, and the next one starts.
"""

from pydantic import ValidationError
from vekna.folio.shell import shell
from vekna.lexicon import RitualError, Transition, done, emit_delta, goto, ritual, step

from .agent import (
    COVER,
    QA,
    READING,
    TRIAGE_FILE,
    TRIAGE_READ,
    Fallen,
    Misread,
    ask,
    ask_for,
    fix_gates,
    resolve,
    thermo,
)
from .shell import (
    CONTINUE_MERGE,
    COVERAGE,
    CR_LABEL,
    LIST,
    PR_FIX,
    QA_LABEL,
    STASHED,
    THERMO_LABEL,
    WAIT_LABEL,
    ahead,
    commit,
    label,
    quoted,
    release,
    said,
    stash_name,
)
from .state import (
    PULLS,
    Checked,
    Closed,
    Labels,
    PrCheck,
    Run,
    Triaged,
    TriageNotes,
    Work,
    abandoned,
    charged,
    cleared,
    counted,
    exhausted,
    modified,
    report_card,
    run_with,
    spent,
    summary,
    wears,
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
        pulls = PULLS.validate_json(listed.stdout)
    except ValidationError as error:
        unreadable = f"gh returned something unreadable: {error}"
        return goto(report, run_with(run, stopped=unreadable))
    # Dropped here rather than skipped later, so a waiting branch is never
    # checked out, never counted as reached, and never in the report at all.
    wanted = [pull for pull in pulls if not wears(pull, WAIT_LABEL)]
    # Oldest-modified first: the branch that has been drifting from its base the
    # longest is the one most likely to need the night.
    queue = sorted(wanted, key=modified)
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
        f"git fetch --prune https-origin && git checkout {quoted(pull.base)}"
        f" && git pull --ff-only https-origin {quoted(pull.base)}"
    )
    if synced.exit_code:
        reason = f"could not update {pull.base}: {said(synced)}"
        return goto(report, abandoned(work, reason))
    # `merge --ff-only`, never `reset --hard`: a branch this ritual worked on
    # last night carries commits origin has not seen, and they are the whole
    # point of the report. A branch that has genuinely diverged stops here.
    taken = await shell(
        f"git checkout {quoted(pull.branch)} && "
        f"git merge --ff-only {quoted(f'https-origin/{pull.branch}')}"
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
            set_aside, work_with(work, note="the merge conflicts were not resolved")
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
    gates = await shell(PR_FIX)
    if gates.exit_code == 0:
        return goto(finish_merge, cleared(work, gate_check.name))
    if exhausted(work, gate_check.name):
        return goto(set_aside, work_with(work, note=f"`{PR_FIX}` is still red"))
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
    measured = await shell(COVERAGE)
    output = said(measured)
    # The report's own word for a line no test reached. Read from the output
    # rather than the exit code, which is also non-zero for a threshold this
    # ritual has no business moving.
    if "Missing" in output:
        if exhausted(work, cover.name):
            return goto(
                set_aside,
                work_with(work, note=f"`{COVERAGE}` still reports missing lines"),
            )
        if fallen := await ask(COVER + output, key=f"cover-{work.pr.number}"):
            return goto(report, abandoned(work, fallen.reason))
        return goto(cover, charged(work, cover.name))
    if measured.exit_code:
        reason = f"`{COVERAGE}` failed without naming missing lines"
        return goto(set_aside, work_with(work, note=f"{reason}: {output}"))
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
    return goto(quality_review, cleared(work, cover.name))


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
        unreadable = f"gh returned labels this could not read: {error}"
        return goto(set_aside, work_with(work, note=unreadable))
    # An earlier night's review, which is not this night's work to label.
    if any(one.name == THERMO_LABEL for one in labels.labels):
        return goto(read_comments, work)
    if fallen := await ask(
        thermo(number=work.pr.number, base=work.pr.base), key=f"review-{work.pr.number}"
    ):
        return goto(report, abandoned(work, fallen.reason))
    marked = await shell(label(THERMO_LABEL, CR_LABEL, number=work.pr.number))
    if marked.exit_code:
        reason = f"could not label the review just posted: {said(marked)}"
        return goto(set_aside, work_with(work, note=reason))
    return goto(read_comments, work)


@step
async def read_comments(work: Work) -> Transition:
    notes = await ask_for(
        f"{TRIAGE_READ}\npull request: {work.pr.url}", output=TriageNotes, opts=READING
    )
    if isinstance(notes, Fallen):
        return goto(report, abandoned(work, notes.reason))
    # This branch loses its triage and nothing else: the run carries on, and a
    # blocked row says why rather than a whole night ending on one bad answer.
    if isinstance(notes, Misread):
        unreadable = f"the triage was unreadable: {notes.reason}"
        return goto(set_aside, work_with(work, note=unreadable))
    # Nothing to triage is an answer, and the good one: the branch goes to QA.
    if not notes.items:
        return goto(mark_qa, work)
    return goto(write_triage, Triaged(work=work, notes=notes))


# The label is a promise about a file, so it goes on last and only once the file
# is there to promise. Asking for it first costs an agent attempt on the paths
# that then fail to label, which is the cheaper of the two mistakes: a label the
# morning trusts and a branch that carries no scenarios is the expensive one.
# The file is asked for by name because a green commit does not prove it exists
# — `commit` is content with an empty diff, by design, since the repair loops
# above reach it with nothing to say.
@step
async def mark_qa(work: Work) -> Transition:
    if fallen := await ask(QA):
        return goto(report, abandoned(work, fallen.reason))
    written = await shell("test -f qa.md")
    if written.exit_code:
        return goto(set_aside, work_with(work, note="the agent wrote no qa.md"))
    landed = await shell(commit("docs: manual test scenarios for this branch"))
    if landed.exit_code:
        return goto(
            set_aside, work_with(work, note=f"could not commit qa.md: {said(landed)}")
        )
    labelled = await shell(label(QA_LABEL, number=work.pr.number))
    if labelled.exit_code:
        reason = f"could not add the {QA_LABEL} label: {said(labelled)}"
        return goto(set_aside, work_with(work, note=reason))
    return goto(finish_pr, Closed(work=work, outcome="qa"))


@step
async def write_triage(triaged: Triaged) -> Transition:
    work = triaged.work
    if fallen := await ask(TRIAGE_FILE + triaged.notes.model_dump_json(indent=2)):
        return goto(report, abandoned(work, fallen.reason))
    landed = await shell(commit("docs: triage of the open review comments"))
    if landed.exit_code:
        return goto(
            set_aside,
            work_with(work, note=f"could not commit triage.md: {said(landed)}"),
        )
    marked = await shell(label(CR_LABEL, number=work.pr.number))
    if marked.exit_code:
        reason = f"could not add the {CR_LABEL} label: {said(marked)}"
        return goto(set_aside, work_with(work, note=reason))
    return goto(
        finish_pr,
        Closed(work=work_with(work, note=counted(triaged.notes)), outcome="triage"),
    )


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
        note=work.note,
    )
    run = work.run
    return goto(next_pr, run_with(run, checked=[*run.checked, row]))


@step
async def set_aside(work: Work) -> Transition:
    released = await shell(release(work.pr.branch))
    parts = [work.note]
    if released.exit_code:
        parts.append(f"the worktree could not be released: {said(released)}")
    elif released.stdout.strip() == STASHED:
        parts.append(f'stashed as "{stash_name(work.pr.branch)}"')
    note = "; ".join(part for part in parts if part)
    row = Checked(
        number=work.pr.number,
        branch=work.pr.branch,
        url=work.pr.url,
        outcome="blocked",
        unpushed=await ahead(work.pr.branch),
        note=note,
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
