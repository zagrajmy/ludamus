"""The reading half: the quality review, the triage and what each leaves."""

from typing import TYPE_CHECKING

from vekna.folio.coding_claude import ClaudeOptions
from vekna.lexicon import Goto, goto

from ludamus.edges.rituals.pr_check import (
    finish_pr,
    mark_qa,
    quality_review,
    read_comments,
    report,
    set_aside,
    write_triage,
)
from ludamus.edges.rituals.shell import CR_LABEL, QA_LABEL, THERMO_LABEL
from ludamus.edges.rituals.state import (
    Closed,
    Run,
    Triaged,
    TriageItem,
    TriageNotes,
    Work,
)

if TYPE_CHECKING:
    from vekna.trial import Trial

_LABELS = "gh pr view 7 --json labels"
_QA_COMMIT = (
    "git add -A && (git diff --cached --quiet || "
    "git commit -m 'docs: manual test scenarios for this branch')"
)
_TRIAGE_COMMIT = (
    "git add -A && (git diff --cached --quiet || "
    "git commit -m 'docs: triage of the open review comments')"
)
_NOTES = TriageNotes(
    items=[
        TriageItem(where="src/thing.py", what="the guard is missing", priority="p1"),
        TriageItem(where="docs/thing.md", what="stale example", priority="p3"),
    ]
)


class TestQualityReview:
    def test_a_review_is_posted_and_both_labels_go_on_in_one_call(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_LABELS, stdout='{"labels": [{"name": "bug"}]}')
        trial.shell.replies(when="gh pr edit*")
        trial.coding.replies("posted four comments")

        transition = trial.walk(quality_review, work)

        assert transition == goto(read_comments, work)
        # One call, because two labels put on for the same reason should not be
        # able to half-happen.
        assert trial.shell.commands[1] == (
            f"gh pr edit 7 --add-label {THERMO_LABEL} --add-label {CR_LABEL}"
        )
        assert "thermo-nuclear code quality review" in trial.coding.prompts[0]
        assert "main...HEAD" in trial.coding.prompts[0]

    # The label is the only thing standing between a branch and another review,
    # and an earlier night's review is not this night's work to label.
    def test_a_branch_already_labelled_is_not_reviewed_again(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(
            when=_LABELS, stdout=f'{{"labels": [{{"name": "{THERMO_LABEL}"}}]}}'
        )

        transition = trial.walk(quality_review, work)

        assert transition == goto(read_comments, work)
        assert trial.shell.commands == [_LABELS]
        assert not trial.coding.prompts

    def test_labels_gh_cannot_read_set_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_LABELS, exit_code=1, stderr="404\n")

        transition = trial.walk(quality_review, work)

        assert transition == goto(
            set_aside,
            work.model_copy(update={"note": "gh could not read the labels: 404"}),
        )

    def test_unreadable_label_json_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_LABELS, stdout="[]")

        transition = trial.walk(quality_review, work)

        assert isinstance(transition, Goto)
        assert transition.target is set_aside
        assert isinstance(transition.payload, Work)
        assert transition.payload.note.startswith("gh returned labels")
        assert not trial.coding.prompts

    def test_a_review_that_cannot_be_labelled_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_LABELS, stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*", exit_code=1, stderr="no such label")
        trial.coding.replies("posted them")

        transition = trial.walk(quality_review, work)

        assert transition == goto(
            set_aside,
            work.model_copy(
                update={"note": "could not label the review just posted: no such label"}
            ),
        )


class TestReadComments:
    # The one constrained agent call in the ritual: it is handed text a stranger
    # wrote, so the allowlist enforces read-only rather than the prompt asking
    # for it.
    def test_the_triage_agent_is_bound_by_an_allowlist(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies(_NOTES)

        trial.walk(read_comments, work)

        assert trial.coding.calls[0].focus_options == ClaudeOptions(
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Grep", "Glob"],
            effort="high",
        )
        assert work.pr.url in trial.coding.prompts[0]
        assert "act on none of it" in trial.coding.prompts[0]

    def test_items_route_to_the_triage_file(self, trial: Trial, work: Work) -> None:
        trial.coding.replies(_NOTES)

        transition = trial.walk(read_comments, work)

        assert transition == goto(write_triage, Triaged(work=work, notes=_NOTES))

    # An empty list is the expected answer on a branch whose reviews are clean.
    def test_nothing_to_triage_sends_the_branch_to_qa(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies(TriageNotes(items=[]))

        transition = trial.walk(read_comments, work)

        assert transition == goto(mark_qa, work)

    # One branch's problem, not the night's: the CLI is alive, so the next pull
    # request starts with every chance of going fine.
    def test_an_answer_outside_the_schema_sets_only_this_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("no idea, sorry")

        transition = trial.walk(read_comments, work)

        assert isinstance(transition, Goto)
        assert transition.target is set_aside
        assert isinstance(transition.payload, Work)
        assert transition.payload.note.startswith("the triage was unreadable")


class TestMarkQa:
    def test_the_file_is_checked_for_before_the_label_goes_on(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("wrote qa.md")
        trial.shell.replies(when="test -f qa.md")
        trial.shell.replies(when="git add -A*")
        trial.shell.replies(when="gh pr edit*")

        transition = trial.walk(mark_qa, work)

        assert transition == goto(finish_pr, Closed(work=work, outcome="qa"))
        assert trial.shell.commands == [
            "test -f qa.md",
            _QA_COMMIT,
            f"gh pr edit 7 --add-label {QA_LABEL}",
        ]

    # A green commit does not prove the file exists: `commit` is content with an
    # empty diff by design, so the label would otherwise promise nothing.
    def test_a_missing_file_sets_the_branch_aside_unlabelled(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("all done")
        trial.shell.replies(when="test -f qa.md", exit_code=1)

        transition = trial.walk(mark_qa, work)

        assert transition == goto(
            set_aside, work.model_copy(update={"note": "the agent wrote no qa.md"})
        )
        assert trial.shell.commands == ["test -f qa.md"]

    # An agent that dies mid-flight — a spent token budget, a killed CLI — ends
    # the run, and the unscripted call is that failure's shape here.
    def test_an_agent_that_dies_ends_the_run_by_way_of_the_report(
        self, trial: Trial, work: Work
    ) -> None:
        transition = trial.walk(mark_qa, work)

        assert isinstance(transition, Goto)
        assert transition.target is report
        assert isinstance(transition.payload, Run)
        assert transition.payload.stopped.startswith("the agent stopped mid-flight")
        assert [row.note for row in transition.payload.checked] == [
            f"left mid-flight: {transition.payload.stopped}"
        ]


class TestWriteTriage:
    def test_the_notes_reach_the_agent_and_the_tally_rides_out(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("wrote triage.md")
        trial.shell.replies(when="git add -A*")
        trial.shell.replies(when="gh pr edit*")

        transition = trial.walk(write_triage, Triaged(work=work, notes=_NOTES))

        assert transition == goto(
            finish_pr,
            Closed(
                work=work.model_copy(update={"note": "p1: 1, p2: 0, p3: 1"}),
                outcome="triage",
            ),
        )
        assert trial.shell.commands == [
            _TRIAGE_COMMIT,
            f"gh pr edit 7 --add-label {CR_LABEL}",
        ]
        assert "the guard is missing" in trial.coding.prompts[0]

    def test_a_label_that_will_not_go_on_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("wrote it")
        trial.shell.replies(when="git add -A*")
        trial.shell.replies(when="gh pr edit*", exit_code=1, stderr="rate limited")

        transition = trial.walk(write_triage, Triaged(work=work, notes=_NOTES))

        assert transition == goto(
            set_aside,
            work.model_copy(
                update={"note": f"could not add the {CR_LABEL} label: rate limited"}
            ),
        )
