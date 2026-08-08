"""Making it green: the gate loop, the commit and the coverage loop."""

from typing import TYPE_CHECKING

from vekna.lexicon import goto

from ludamus.edges.rituals.pr_check import (
    cover,
    finish_merge,
    gate_check,
    quality_review,
    set_aside,
)
from ludamus.edges.rituals.shell import COVERAGE, PR_FIX

if TYPE_CHECKING:
    from vekna.trial import Trial

    from ludamus.edges.rituals.state import Work

_MISSING = "src/ludamus/thing.py (80.0%): Missing lines 12-14"
_MERGE_COMMIT = (
    "git add -A && (git diff --cached --quiet || "
    "git commit -m 'chore: merge main and fix the gates')"
)
_TEST_COMMIT = (
    "git add -A && (git diff --cached --quiet || "
    "git commit -m 'test: cover the lines this branch changes')"
)


class TestGateCheck:
    def test_a_green_gate_finishes_the_merge_and_clears_the_budget(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"gate_check": 2}})
        trial.shell.replies(when=PR_FIX)

        transition = trial.walk(gate_check, spent)

        assert transition == goto(finish_merge, work)
        assert trial.shell.commands == [PR_FIX]

    def test_a_red_gate_hands_both_streams_to_the_agent(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(
            when=PR_FIX, exit_code=1, stdout="E501 line too long", stderr="1 failed"
        )
        trial.coding.replies("fixed it")

        transition = trial.walk(gate_check, work)

        assert transition == goto(
            gate_check, work.model_copy(update={"budgets": {"gate_check": 1}})
        )
        # A task that dies before it starts complains on stderr and nowhere
        # else, so both streams reach the repair agent.
        assert "E501 line too long\n1 failed" in trial.coding.prompts[0]
        assert "do not disable a lint rule" in trial.coding.prompts[0]

    def test_a_spent_budget_sets_the_branch_aside_without_asking_again(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"gate_check": 3}})
        trial.shell.replies(when=PR_FIX, exit_code=1, stdout="still red")

        transition = trial.walk(gate_check, spent)

        assert transition == goto(
            set_aside, spent.model_copy(update={"note": f"`{PR_FIX}` is still red"})
        )
        assert not trial.coding.prompts


class TestFinishMerge:
    def test_an_open_merge_is_continued_before_the_repairs_are_committed(
        self, trial: Trial, work: Work
    ) -> None:
        merging = work.model_copy(update={"merging": True})
        trial.shell.replies(when="if git rev-parse*MERGE_HEAD*")
        trial.shell.replies(when="git add -A*")

        transition = trial.walk(finish_merge, merging)

        assert transition == goto(cover, work)
        assert trial.shell.commands[1] == _MERGE_COMMIT

    def test_a_clean_merge_only_commits(self, trial: Trial, work: Work) -> None:
        trial.shell.replies(when="git add -A*")

        transition = trial.walk(finish_merge, work)

        assert transition == goto(cover, work)
        assert trial.shell.commands == [_MERGE_COMMIT]

    def test_a_merge_that_will_not_continue_is_set_aside(
        self, trial: Trial, work: Work
    ) -> None:
        merging = work.model_copy(update={"merging": True})
        trial.shell.replies(
            when="if git rev-parse*", exit_code=1, stderr="still conflicted"
        )

        transition = trial.walk(finish_merge, merging)

        assert transition == goto(
            set_aside,
            merging.model_copy(
                update={"note": "could not finish the merge: still conflicted"}
            ),
        )


class TestCover:
    # Read off the report's own word rather than the exit code, which is also
    # non-zero for a threshold this ritual has no business moving.
    def test_missing_lines_reach_the_agent(self, trial: Trial, work: Work) -> None:
        trial.shell.replies(when=COVERAGE, exit_code=1, stdout=_MISSING)
        trial.coding.replies("wrote the tests")

        transition = trial.walk(cover, work)

        assert transition == goto(
            cover, work.model_copy(update={"budgets": {"cover": 1}})
        )
        assert _MISSING in trial.coding.prompts[0]
        assert trial.shell.commands == [COVERAGE]

    def test_a_first_pass_with_nothing_missing_commits_nothing(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=COVERAGE)

        transition = trial.walk(cover, work)

        # A commit rite that can never commit anything is noise in the tree.
        assert transition == goto(quality_review, work)
        assert trial.shell.commands == [COVERAGE]

    def test_tests_that_were_written_are_committed_and_the_budget_cleared(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"cover": 1}})
        trial.shell.replies(when=COVERAGE)
        trial.shell.replies(when="git add -A*")

        transition = trial.walk(cover, spent)

        assert transition == goto(quality_review, work)
        assert trial.shell.commands == [COVERAGE, _TEST_COMMIT]

    def test_a_spent_budget_sets_the_branch_aside(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"cover": 3}})
        trial.shell.replies(when=COVERAGE, exit_code=1, stdout=_MISSING)

        transition = trial.walk(cover, spent)

        assert transition == goto(
            set_aside,
            spent.model_copy(
                update={"note": f"`{COVERAGE}` still reports missing lines"}
            ),
        )
        assert not trial.coding.prompts

    # A red run that names no missing lines is the tool failing, not the branch:
    # handing that to an agent would spend a turn on nothing.
    def test_a_report_that_failed_without_naming_lines_is_set_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=COVERAGE, exit_code=2, stderr="no coverage data")

        transition = trial.walk(cover, work)

        assert transition == goto(
            set_aside,
            work.model_copy(
                update={
                    "note": (
                        f"`{COVERAGE}` failed without naming missing lines: "
                        "no coverage data"
                    )
                }
            ),
        )
        assert not trial.coding.prompts
