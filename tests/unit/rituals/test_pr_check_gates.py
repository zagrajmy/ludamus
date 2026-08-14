"""Making it green: the gate loop, the commit and the coverage loop."""

from typing import TYPE_CHECKING

from vekna.lexicon import goto

from ludamus.edges.rituals.pr_check import (
    cover,
    finish_merge,
    gate_check,
    push_work,
    quality_review,
    set_aside,
    stand_down,
)
from ludamus.edges.rituals.shell import BUDGET, COVERAGE, PR_FIX, REMOTE, plain
from ludamus.edges.rituals.state import Run

if TYPE_CHECKING:
    from vekna.trial import Trial

    from ludamus.edges.rituals.state import Work

_MISSING = "src/ludamus/thing.py (80.0%): Missing lines 12-14"
_PUSH = f"git push {REMOTE} feature"
# The same suite failing the same way on two branches, an hour and two commits
# apart: only the timing and the tally moved.
_RED = "1 failed\n  panel.spec.ts:77:5 > redirects when empty\n210 passed (6.8m)"
_RED_AGAIN = "1 failed\n  panel.spec.ts:77:5 > redirects when empty\n212 passed (5.5m)"
_CLEAN = """-------------
Diff Coverage
Diff: main...HEAD
-------------
src/ludamus/thing.py (100%)
-------------
Total:   10 lines
Missing: 0 lines
Coverage: 100%
-------------
"""
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
        trial.shell.replies(when=plain(PR_FIX))

        transition = trial.walk(gate_check, spent)

        assert transition == goto(finish_merge, work)
        # `CI=1`, so what comes back is a log rather than a terminal recording.
        assert trial.shell.commands == [plain(PR_FIX)]

    def test_a_red_gate_hands_both_streams_to_the_agent(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(
            when=plain(PR_FIX),
            exit_code=1,
            stdout="E501 line too long",
            stderr="1 failed",
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
        # The step runs the sweep itself the moment the agent stops, so the
        # agent is left the narrow loop instead.
        assert "Do not run the whole-repository sweeps" in trial.coding.prompts[0]
        assert "one linter" in trial.coding.prompts[0]

    # It stands down rather than stopping: a branch that will not go green is
    # still a branch to review, and the verdict rides along so the morning is
    # told what was red without being handed the whole log.
    def test_a_spent_budget_stands_the_branch_down_without_asking_again(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"gate_check": 3}})
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="still red")

        transition = trial.walk(gate_check, spent)

        assert transition == goto(
            stand_down,
            spent.model_copy(
                update={
                    "reason": f"`{PR_FIX}` is still red:\nstill red",
                    "run": Run(bound=3, seen=["still red"]),
                }
            ),
        )
        assert not trial.coding.prompts

    # Timings and tallies move between branches; the failing test does not. A
    # night where one thing is broken everywhere pays for that answer once.
    def test_a_failure_this_run_gave_up_on_is_not_repaired_again(
        self, trial: Trial, work: Work
    ) -> None:
        again = work.model_copy(update={"run": Run(bound=3, seen=[_RED])})
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout=_RED_AGAIN)

        transition = trial.walk(gate_check, again)

        assert transition == goto(
            stand_down,
            again.model_copy(
                update={"reason": f"`{PR_FIX}` is red as it already was:\n{_RED_AGAIN}"}
            ),
        )
        assert not trial.coding.prompts

    # Asked before the first repair and not after, or a branch whose gate says
    # the same thing twice running would be read as the night's standing
    # failure and dropped mid-loop.
    def test_a_repair_that_changed_nothing_still_gets_its_budget(
        self, trial: Trial, work: Work
    ) -> None:
        tried = work.model_copy(
            update={"budgets": {"gate_check": 1}, "run": Run(bound=3, seen=[_RED])}
        )
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout=_RED_AGAIN)
        trial.coding.replies("tried again")

        transition = trial.walk(gate_check, tried)

        assert transition == goto(
            gate_check, tried.model_copy(update={"budgets": {"gate_check": 2}})
        )


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
    # Read off the report's own word and not the exit code, which does not carry
    # this: the task runs `diff-cover` with no `--fail-under`, so a run that
    # names missing lines still ends 0.
    def test_missing_lines_reach_the_agent(self, trial: Trial, work: Work) -> None:
        trial.shell.replies(when=plain(COVERAGE), stdout=_MISSING)
        trial.coding.replies("wrote the tests")

        transition = trial.walk(cover, work)

        assert transition == goto(
            cover, work.model_copy(update={"budgets": {"cover": 1}})
        )
        assert _MISSING in trial.coding.prompts[0]
        assert "Do not run the whole-repository sweeps" in trial.coding.prompts[0]
        assert trial.shell.commands == [plain(COVERAGE)]

    # This is what let a red suite through: it names no missing lines, so it was
    # read as the coverage tool failing rather than the branch, and the pull
    # request was dropped instead of repaired.
    def test_a_red_suite_is_repaired_like_any_other_gate(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=plain(COVERAGE), exit_code=1, stdout=_RED)
        trial.coding.replies("fixed the test")

        transition = trial.walk(cover, work)

        assert transition == goto(
            cover, work.model_copy(update={"budgets": {"cover": 1}})
        )
        # Named for what is actually red, not for the other gate.
        assert trial.coding.prompts[0].startswith(f"`{COVERAGE}` is this project")
        assert "do not disable a lint rule" in trial.coding.prompts[0]

    def test_a_red_suite_that_stays_red_stands_the_branch_down(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"cover": 3}})
        trial.shell.replies(when=plain(COVERAGE), exit_code=1, stdout=_RED)

        transition = trial.walk(cover, spent)

        assert transition == goto(
            stand_down,
            spent.model_copy(
                update={
                    "reason": f"`{COVERAGE}` is still red:\n{_RED}",
                    "run": Run(bound=3, seen=[_RED]),
                }
            ),
        )
        assert not trial.coding.prompts

    # The whole listing is the work list. A tail of it is an agent asked to
    # cover lines it was never shown, and then another full unit and e2e run to
    # reveal the next few.
    def test_every_file_reaches_the_agent_out_from_under_the_suite(
        self, trial: Trial, work: Work
    ) -> None:
        # Longer than the budget on its own, which is the whole point: what a
        # branch has left uncovered is not something a token count can bound.
        listing = "\n".join(
            f"src/ludamus/thing{index}.py (80.0%): Missing lines 12-14"
            for index in range(BUDGET // 20)
        )
        transcript = "\n".join(f"tests/test_{index}.py PASSED" for index in range(4000))
        trial.shell.replies(
            when=plain(COVERAGE),
            stdout=f"{transcript}\n-------------\nDiff Coverage\n{listing}\n",
        )
        trial.coding.replies("wrote the tests")

        transition = trial.walk(cover, work)

        assert transition == goto(
            cover, work.model_copy(update={"budgets": {"cover": 1}})
        )
        assert listing in trial.coding.prompts[0]
        assert "tests/test_0.py PASSED" not in trial.coding.prompts[0]

    # diff-cover's summary block says "Missing: 0 lines" on a clean report too,
    # so the bare word would send every green run round the loop again.
    def test_a_clean_report_is_not_read_as_missing_lines(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=plain(COVERAGE), stdout=_CLEAN)

        transition = trial.walk(cover, work)

        assert transition == goto(push_work, work)
        assert not trial.coding.prompts

    def test_a_first_pass_with_nothing_missing_commits_nothing(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=plain(COVERAGE))

        transition = trial.walk(cover, work)

        # A commit rite that can never commit anything is noise in the tree.
        assert transition == goto(push_work, work)
        assert trial.shell.commands == [plain(COVERAGE)]

    def test_tests_that_were_written_are_committed_and_the_budget_cleared(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"cover": 1}})
        trial.shell.replies(when=plain(COVERAGE))
        trial.shell.replies(when="git add -A*")

        transition = trial.walk(cover, spent)

        assert transition == goto(push_work, work)
        assert trial.shell.commands == [plain(COVERAGE), _TEST_COMMIT]

    def test_a_spent_budget_stands_the_branch_down(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"cover": 3}})
        trial.shell.replies(when=plain(COVERAGE), stdout=_MISSING)

        transition = trial.walk(cover, spent)

        assert transition == goto(
            stand_down,
            spent.model_copy(
                # No `seen`: what lines a branch left uncovered is that branch's
                # own business, and two of them missing lines in the same file
                # would look like one standing failure from here.
                update={
                    "reason": f"`{COVERAGE}` still reports missing lines:\n{_MISSING}"
                }
            ),
        )
        assert not trial.coding.prompts

    # The tool falling over rather than the branch — no report at all, so the
    # trimmed log is what there is to hand on.
    def test_a_run_that_printed_no_report_is_still_repaired(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(
            when=plain(COVERAGE), exit_code=2, stderr="no coverage data"
        )
        trial.coding.replies("looked at it")

        transition = trial.walk(cover, work)

        assert transition == goto(
            cover, work.model_copy(update={"budgets": {"cover": 1}})
        )
        assert "no coverage data" in trial.coding.prompts[0]


class TestPushWork:
    def test_the_night_goes_up_before_the_review_reads_it(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_PUSH)

        transition = trial.walk(push_work, work)

        assert transition == goto(quality_review, work)
        assert trial.shell.commands == [_PUSH]

    # Not fatal and not `set_aside`: a push that will not go through costs the
    # review its anchors and nothing else. The branch is still worth reading.
    def test_a_push_that_will_not_go_through_is_carried_into_the_review(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_PUSH, exit_code=1, stderr="the remote hung up")

        transition = trial.walk(push_work, work)

        assert transition == goto(
            quality_review,
            work.model_copy(update={"note": "could not push: the remote hung up"}),
        )

    # A branch that stood down arrives carrying its stash, and the push's own
    # complaint must not be written over it.
    def test_a_note_already_on_the_branch_keeps_its_half(
        self, trial: Trial, work: Work
    ) -> None:
        stashed = work.model_copy(update={"note": 'stashed as "left unfinished"'})
        trial.shell.replies(when=_PUSH, exit_code=1, stderr="the remote hung up")

        transition = trial.walk(push_work, stashed)

        assert transition == goto(
            quality_review,
            stashed.model_copy(
                update={
                    "note": (
                        'stashed as "left unfinished"; '
                        "could not push: the remote hung up"
                    )
                }
            ),
        )
