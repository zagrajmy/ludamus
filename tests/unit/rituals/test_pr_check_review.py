"""The reading half: the quality review, the triage and what each leaves."""

from typing import TYPE_CHECKING

from vekna.folio.coding_claude import ClaudeOptions
from vekna.lexicon import Goto, goto

from ludamus.edges.rituals.pr_check import (
    finish_pr,
    mark_qa,
    quality_review,
    read_comments,
    set_aside,
    write_triage,
)
from ludamus.edges.rituals.shell import (
    CR_LABEL,
    QA_LABEL,
    THERMO_LABEL,
    TRIAGE_TITLE,
    triage_comment,
)
from ludamus.edges.rituals.state import Closed, Triaged, TriageItem, TriageNotes, Work

if TYPE_CHECKING:
    from vekna.trial import Trial

_LABELS = "gh pr view 7 --json labels"
_READ_TRIAGE = triage_comment(7)
# The command as it is answered, rather than as it is run: `when` is a glob, and
# the jq in it is full of brackets a glob reads as a character class.
_READS = "gh pr view 7 --json comments*"
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
    # One call and no agent: the label is the whole of what a clean branch earns.
    def test_a_clean_branch_is_labelled_and_finished(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="gh pr edit*")

        transition = trial.walk(mark_qa, work)

        assert transition == goto(finish_pr, Closed(work=work, outcome="qa"))
        assert trial.shell.commands == [f"gh pr edit 7 --add-label {QA_LABEL}"]
        assert not trial.coding.prompts

    # The label is what the morning reads to pick something to test, so a branch
    # that could not be labelled is not one to report as ready.
    def test_a_label_that_will_not_go_on_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="gh pr edit*", exit_code=1, stderr="gh is unhappy")

        transition = trial.walk(mark_qa, work)

        assert transition == goto(
            set_aside,
            work.model_copy(
                update={"note": f"could not add the {QA_LABEL} label: gh is unhappy"}
            ),
        )


class TestWriteTriage:
    def test_the_notes_reach_the_agent_and_the_tally_rides_out(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("wrote the triage")
        trial.shell.replies(when=_READS, stdout=f"{TRIAGE_TITLE}\np1: one\n")
        trial.shell.replies(when="gh pr edit*")

        transition = trial.walk(write_triage, Triaged(work=work, notes=_NOTES))

        assert transition == goto(
            finish_pr,
            Closed(
                work=work.model_copy(update={"note": "p1: 1, p2: 0, p3: 1"}),
                outcome="triage",
            ),
        )
        # Posted on the pull request and never committed: the triage is a note
        # to `ship`, not part of the branch.
        assert trial.shell.commands == [
            _READ_TRIAGE,
            f"gh pr edit 7 --add-label {CR_LABEL}",
        ]
        assert "the guard is missing" in trial.coding.prompts[0]

    # The label promises a triage, so the comment is read back: nothing is
    # committed here, and an agent that answered without posting would otherwise
    # earn the branch a promise nobody can keep.
    def test_a_triage_that_was_never_posted_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("thought about it")
        trial.shell.replies(when=_READS)

        transition = trial.walk(write_triage, Triaged(work=work, notes=_NOTES))

        assert transition == goto(
            set_aside, work.model_copy(update={"note": "the agent posted no triage"})
        )

    # A triage nothing can read is one `ship` will not find either, so a `gh`
    # that would not answer lands in the same place.
    def test_a_reading_that_fails_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("posted it")
        trial.shell.replies(when=_READS, exit_code=1, stderr="rate limited")

        transition = trial.walk(write_triage, Triaged(work=work, notes=_NOTES))

        assert transition == goto(
            set_aside, work.model_copy(update={"note": "the agent posted no triage"})
        )

    def test_a_label_that_will_not_go_on_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.coding.replies("wrote it")
        trial.shell.replies(when=_READS, stdout=f"{TRIAGE_TITLE}\np1: one\n")
        trial.shell.replies(when="gh pr edit*", exit_code=1, stderr="rate limited")

        transition = trial.walk(write_triage, Triaged(work=work, notes=_NOTES))

        assert transition == goto(
            set_aside,
            work.model_copy(
                update={"note": f"could not add the {CR_LABEL} label: rate limited"}
            ),
        )
