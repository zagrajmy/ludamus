"""The reading half: the quality review, and what it leaves on the branch."""

from typing import TYPE_CHECKING

from vekna.lexicon import Goto, goto

from ludamus.edges.rituals.pr_check import finish_pr, quality_review, set_aside
from ludamus.edges.rituals.shell import THERMO_LABEL
from ludamus.edges.rituals.state import Closed, Work

if TYPE_CHECKING:
    from vekna.trial import Trial

_LABELS = "gh pr view 7 --json labels"


class TestQualityReview:
    def test_a_review_is_posted_and_the_branch_is_labelled(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_LABELS, stdout='{"labels": [{"name": "bug"}]}')
        trial.shell.replies(when="gh pr edit*")
        trial.coding.replies("posted four comments")

        transition = trial.walk(quality_review, work)

        assert transition == goto(finish_pr, Closed(work=work, outcome="green"))
        assert trial.shell.commands[1] == f"gh pr edit 7 --add-label {THERMO_LABEL}"
        assert "thermo-nuclear code quality review" in trial.coding.prompts[0]
        assert "main...HEAD" in trial.coding.prompts[0]

    # A branch nobody could build is reviewed all the same, and the row says
    # which of the two it was.
    def test_a_blocked_branch_ends_the_night_blocked(
        self, trial: Trial, work: Work
    ) -> None:
        stood = work.model_copy(update={"blocked": True})
        trial.shell.replies(when=_LABELS, stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*")
        trial.coding.replies("posted them")

        transition = trial.walk(quality_review, stood)

        assert transition == goto(finish_pr, Closed(work=stood, outcome="blocked"))

    # The label is the only thing standing between a branch and another review,
    # and an earlier night's review is not this night's work to label.
    def test_a_branch_already_labelled_is_not_reviewed_again(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(
            when=_LABELS, stdout=f'{{"labels": [{{"name": "{THERMO_LABEL}"}}]}}'
        )

        transition = trial.walk(quality_review, work)

        assert transition == goto(finish_pr, Closed(work=work, outcome="green"))
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
