"""How a branch ends, how the night ends, and the report that is always owed."""

import json
from typing import TYPE_CHECKING

import pytest
from vekna.lexicon import RitualError, done, goto

from ludamus.edges.rituals.pr_sweep import (
    finish_pr,
    next_pr,
    pr_cover,
    pr_refresh,
    report,
    set_aside,
    skip_pr,
)
from ludamus.edges.rituals.shell import COVERAGE, PR_FIX, checks, plain
from ludamus.edges.rituals.state import (
    Checked,
    Closed,
    PrSweep,
    PullRequest,
    Report,
    Run,
    Work,
)

if TYPE_CHECKING:
    from vekna.trial import Trial

_AHEAD = "test feature = *"
_PUSH = "git push https-origin feature"
_MISSING = "src/ludamus/thing.py (80.0%): Missing lines 12-14"
_RELEASE = "if git rev-parse*MERGE_HEAD*git stash push*"
# Red, red, green: enough to prove the second repair meets the same agent.
_GATE_ROUNDS = 3
_GREEN_ROW = Checked(
    number=7,
    branch="feature",
    url="https://github.com/fancysnake/ludamus/pull/7",
    outcome="green",
    unpushed=2,
)


class TestFinishPr:
    def test_the_row_carries_what_origin_has_not_got(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_AHEAD, stdout="2\n")

        transition = trial.walk(finish_pr, Closed(work=work, outcome="green"))

        assert transition == goto(next_pr, Run(bound=3, checked=[_GREEN_ROW]))

    def test_a_head_that_is_not_this_branch_counts_as_unknown(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_AHEAD, exit_code=1)

        transition = trial.walk(finish_pr, Closed(work=work, outcome="green"))

        assert transition == goto(
            next_pr,
            Run(bound=3, checked=[_GREEN_ROW.model_copy(update={"unpushed": None})]),
        )


class TestSetAside:
    def test_uncommitted_work_is_stashed_under_a_name_the_report_says(
        self, trial: Trial, work: Work
    ) -> None:
        aside = work.model_copy(update={"note": "`mise run pr-fix` is still red"})
        trial.shell.replies(when=_RELEASE, stdout="stashed\n")
        trial.shell.replies(when=_AHEAD, stdout="1\n")

        transition = trial.walk(set_aside, aside)

        assert transition == goto(
            next_pr,
            Run(
                bound=3,
                checked=[
                    _GREEN_ROW.model_copy(
                        update={
                            "outcome": "blocked",
                            "unpushed": 1,
                            "note": (
                                "`mise run pr-fix` is still red; stashed as "
                                '"a pr sweep left feature unfinished"'
                            ),
                        }
                    )
                ],
            ),
        )

    def test_a_clean_worktree_leaves_no_stash_in_the_note(
        self, trial: Trial, work: Work
    ) -> None:
        aside = work.model_copy(update={"note": "the agent posted no triage"})
        trial.shell.replies(when=_RELEASE)
        trial.shell.replies(when=_AHEAD, stdout="0\n")

        transition = trial.walk(set_aside, aside)

        assert transition == goto(
            next_pr,
            Run(
                bound=3,
                checked=[
                    _GREEN_ROW.model_copy(
                        update={
                            "outcome": "blocked",
                            "unpushed": 0,
                            "note": "the agent posted no triage",
                        }
                    )
                ],
            ),
        )

    def test_a_branch_that_stood_down_keeps_its_reason_through_a_later_failure(
        self, trial: Trial, work: Work
    ) -> None:
        stood = work.model_copy(
            update={
                "reason": f"`{PR_FIX}` is still red:\n1 failed",
                "note": "gh could not read the labels: no such pull request",
                "blocked": True,
            }
        )
        trial.shell.replies(when=_RELEASE)
        trial.shell.replies(when=_AHEAD, stdout="1\n")

        transition = trial.walk(set_aside, stood)

        assert transition == goto(
            next_pr,
            Run(
                bound=3,
                checked=[
                    _GREEN_ROW.model_copy(
                        update={
                            "outcome": "blocked",
                            "unpushed": 1,
                            "note": (
                                f"`{PR_FIX}` is still red:\n1 failed; "
                                "gh could not read the labels: no such pull request"
                            ),
                        }
                    )
                ],
            ),
        )

    def test_a_worktree_that_will_not_release_says_so_in_the_note(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_RELEASE, exit_code=1, stderr="stash failed")
        trial.shell.replies(when=_AHEAD, exit_code=1)

        transition = trial.walk(set_aside, work)

        assert transition == goto(
            next_pr,
            Run(
                bound=3,
                checked=[
                    _GREEN_ROW.model_copy(
                        update={
                            "outcome": "blocked",
                            "unpushed": None,
                            "note": "the worktree could not be released: stash failed",
                        }
                    )
                ],
            ),
        )


class TestSkipPr:
    def test_a_branch_never_taken_touches_neither_the_worktree_nor_the_count(
        self, trial: Trial, work: Work
    ) -> None:
        held = work.model_copy(
            update={"note": "could not take the branch: already used by worktree"}
        )

        transition = trial.walk(skip_pr, held)

        assert transition == goto(
            next_pr,
            Run(
                bound=3,
                checked=[
                    _GREEN_ROW.model_copy(
                        update={
                            "outcome": "skipped",
                            "unpushed": None,
                            "note": (
                                "could not take the branch: already used by worktree"
                            ),
                        }
                    )
                ],
            ),
        )
        assert not trial.shell.commands


class TestReport:
    def test_a_finished_night_answers_with_the_card_and_prints_it(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        landed = _GREEN_ROW.model_copy(update={"unpushed": 0})
        run = Run(bound=3, queue=[pull], checked=[landed])

        transition = trial.walk(report, run)

        assert transition == done(
            Report(checked=[landed], ready=["feature"], not_reached=["feature"])
        )
        assert "ready to test:  feature" in trial.deltas[0]
        assert f"not reached:    {pull.branch}" in trial.deltas[0]

    def test_a_green_row_that_would_not_push_is_not_ready(self, trial: Trial) -> None:
        transition = trial.walk(report, Run(bound=3, checked=[_GREEN_ROW]))

        assert transition == done(Report(checked=[_GREEN_ROW], to_push=["feature"]))
        assert "ready to test:  none" in trial.deltas[0]

    def test_a_row_git_could_not_count_still_needs_pushing(self, trial: Trial) -> None:
        unknown = _GREEN_ROW.model_copy(update={"outcome": "blocked", "unpushed": None})

        transition = trial.walk(report, Run(bound=3, checked=[unknown]))

        assert transition == done(
            Report(checked=[unknown], to_push=["feature"], to_fix=["feature"])
        )
        assert "unknown" in trial.deltas[0]

    def test_a_skipped_row_is_on_none_of_the_work_lists(self, trial: Trial) -> None:
        left = _GREEN_ROW.model_copy(
            update={"outcome": "skipped", "unpushed": None, "branch": "busy"}
        )

        transition = trial.walk(report, Run(bound=3, checked=[left]))

        assert transition == done(Report(checked=[left], left_alone=["busy"]))
        assert "needs pushing:  none" in trial.deltas[0]
        assert "left alone:     busy" in trial.deltas[0]

    def test_a_verdict_in_a_note_is_indented_under_its_row(self, trial: Trial) -> None:
        blocked = _GREEN_ROW.model_copy(
            update={
                "outcome": "blocked",
                "note": f"`{PR_FIX}` is still red:\n1 failed\n2 passed",
            }
        )

        trial.walk(report, Run(bound=3, checked=[blocked]))

        assert "is still red:\n      1 failed\n      2 passed" in trial.deltas[0]

    def test_a_stopped_run_prints_the_report_and_then_fails_the_cast(
        self, trial: Trial
    ) -> None:
        run = Run(bound=3, checked=[_GREEN_ROW], stopped="the worktree is not clean")

        with pytest.raises(RitualError, match="the worktree is not clean"):
            trial.walk(report, run)

        assert "the run failed: the worktree is not clean" in trial.deltas[0]


class TestWholeCast:
    def test_a_clean_branch_walks_the_night_and_ends_green(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        trial.shell.replies(
            when="gh pr list*", stdout=json.dumps([pull.model_dump(by_alias=True)])
        )
        trial.shell.replies(when="git status --porcelain")
        trial.shell.replies(when="git fetch*")
        trial.shell.replies(when="git checkout feature")
        trial.shell.replies(when="git merge --ff-only*")
        trial.shell.replies(when="git merge --no-edit*")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when="gh pr view 7 --json labels", stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*", always=True)
        trial.shell.replies(when="git add -A*", always=True)
        trial.shell.replies(when=_PUSH)
        # Nothing left over, because the push and this count speak to the same
        # remote.
        trial.shell.replies(when=_AHEAD, stdout="0\n")
        trial.coding.replies("posted the review", when="Review the changes*")

        result = trial.cast(pr_refresh, PrSweep(bound=3))

        assert result == Report(
            checked=[_GREEN_ROW.model_copy(update={"unpushed": 0})], ready=["feature"]
        )
        # No coverage anywhere in it: that is the hour the fast pass exists to
        # not spend.
        assert trial.steps == [
            "list_prs",
            "next_pr",
            "check_clean",
            "sync_branch",
            "merge_base",
            "take_pass",
            "gate_check",
            "finish_merge",
            "push_work",
            "quality_review",
            "finish_pr",
            "next_pr",
            "report",
        ]
        assert plain(COVERAGE) not in trial.shell.commands

    def test_the_slow_pass_covers_what_ci_complained_about_and_posts_no_review(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        trial.shell.replies(
            when="gh pr list*", stdout=json.dumps([pull.model_dump(by_alias=True)])
        )
        trial.shell.replies(when="git status --porcelain")
        trial.shell.replies(when="git fetch*")
        trial.shell.replies(when="git checkout feature")
        trial.shell.replies(when="git merge --ff-only*")
        trial.shell.replies(when="git merge --no-edit*")
        trial.shell.replies(
            when=checks(7), stdout='[{"name": "codecov/patch", "state": "FAILURE"}]'
        )
        trial.shell.replies(when=plain(COVERAGE), stdout=_MISSING)
        trial.shell.replies(when=plain(COVERAGE))
        trial.shell.replies(when="git add -A*", always=True)
        trial.shell.replies(when=_PUSH)
        trial.shell.replies(when=_AHEAD, stdout="0\n")
        trial.coding.replies("wrote the tests", when="The diff coverage report*")

        result = trial.cast(pr_cover, PrSweep(bound=3))

        assert result == Report(
            checked=[_GREEN_ROW.model_copy(update={"unpushed": 0})], ready=["feature"]
        )
        assert trial.steps == [
            "list_prs",
            "next_pr",
            "check_clean",
            "sync_branch",
            "merge_base",
            "take_pass",
            "finish_merge",
            "check_ci",
            "cover",
            "cover",
            "push_work",
            "finish_pr",
            "next_pr",
            "report",
        ]
        assert plain(PR_FIX) not in trial.shell.commands

    def test_a_branch_another_worktree_holds_is_left_alone_and_the_rest_go_on(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        held = pull.model_copy(update={"number": 9, "branch": "busy"})
        trial.shell.replies(
            when="gh pr list*",
            stdout=json.dumps([one.model_dump(by_alias=True) for one in (held, pull)]),
        )
        trial.shell.replies(when="git status --porcelain", always=True)
        trial.shell.replies(when="git fetch*", always=True)
        trial.shell.replies(
            when="git checkout busy", exit_code=1, stderr="already used by worktree"
        )
        trial.shell.replies(when="git checkout feature")
        trial.shell.replies(when="git merge --ff-only*")
        trial.shell.replies(when="git merge --no-edit*")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when="gh pr view 7 --json labels", stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*", always=True)
        trial.shell.replies(when="git add -A*", always=True)
        trial.shell.replies(when=_PUSH)
        trial.shell.replies(when=_AHEAD, stdout="0\n")
        trial.coding.replies("posted the review", when="Review the changes*")

        result = trial.cast(pr_refresh, PrSweep(bound=3))

        assert result == Report(
            checked=[
                _GREEN_ROW.model_copy(
                    update={
                        "number": 9,
                        "branch": "busy",
                        "outcome": "skipped",
                        "unpushed": None,
                        "note": "could not take the branch: already used by worktree",
                    }
                ),
                _GREEN_ROW.model_copy(update={"unpushed": 0}),
            ],
            ready=["feature"],
            left_alone=["busy"],
        )
        assert "skip_pr" in trial.steps

    # The repair loop is keyed, so the second attempt meets an agent that
    # remembers what the first one already tried.
    def test_a_gate_repaired_twice_keeps_the_agent_on_one_thread(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        trial.shell.replies(
            when="gh pr list*", stdout=json.dumps([pull.model_dump(by_alias=True)])
        )
        trial.shell.replies(when="git status --porcelain")
        trial.shell.replies(when="git fetch*")
        trial.shell.replies(when="git checkout feature")
        trial.shell.replies(when="git merge --ff-only*")
        trial.shell.replies(when="git merge --no-edit*")
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="red")
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="still red")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when="gh pr view 7 --json labels", stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*", always=True)
        trial.shell.replies(when="git add -A*", always=True)
        trial.shell.replies(when=_PUSH)
        trial.shell.replies(when=_AHEAD, stdout="2\n")
        trial.coding.replies("tried", when="*is this project's gate*", always=True)
        trial.coding.replies("posted the review", when="Review the changes*")

        result = trial.cast(pr_refresh, PrSweep(bound=3))

        assert result == Report(checked=[_GREEN_ROW], to_push=["feature"])
        assert trial.steps.count("gate_check") == _GATE_ROUNDS
        assert trial.coding.calls[0].resume is None
        assert trial.coding.calls[1].resume == "s1"

    def test_a_branch_that_will_not_go_green_is_still_reviewed(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        trial.shell.replies(
            when="gh pr list*", stdout=json.dumps([pull.model_dump(by_alias=True)])
        )
        trial.shell.replies(when="git status --porcelain")
        trial.shell.replies(when="git fetch*")
        trial.shell.replies(when="git checkout feature")
        trial.shell.replies(when="git merge --ff-only*")
        trial.shell.replies(when="git merge --no-edit*")
        trial.shell.replies(
            when=plain(PR_FIX), exit_code=1, stdout="1 failed", always=True
        )
        trial.shell.replies(when=_RELEASE)
        trial.shell.replies(when="gh pr view 7 --json labels", stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*", always=True)
        trial.shell.replies(when="git add -A*", always=True)
        trial.shell.replies(when=_PUSH)
        trial.shell.replies(when=_AHEAD, stdout="3\n")
        trial.coding.replies("tried", when="*is this project's gate*", always=True)
        trial.coding.replies("posted the review", when="Review the changes*")

        result = trial.cast(pr_refresh, PrSweep(bound=1))

        assert result == Report(
            checked=[
                _GREEN_ROW.model_copy(
                    update={
                        "outcome": "blocked",
                        "unpushed": 3,
                        "note": "`mise run pr-fix` is still red:\n1 failed",
                    }
                )
            ],
            to_push=["feature"],
            to_fix=["feature"],
        )
        assert trial.steps == [
            "list_prs",
            "next_pr",
            "check_clean",
            "sync_branch",
            "merge_base",
            "take_pass",
            "gate_check",
            "gate_check",
            "stand_down",
            "push_work",
            "quality_review",
            "finish_pr",
            "next_pr",
            "report",
        ]
        assert "already known not to be green" in trial.coding.prompts[1]

    def test_a_dirty_worktree_fails_the_cast_after_the_report(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        trial.shell.replies(
            when="gh pr list*", stdout=json.dumps([pull.model_dump(by_alias=True)])
        )
        trial.shell.replies(when="git status --porcelain", stdout=" M src/thing.py\n")

        with pytest.raises(RitualError, match="the worktree is not clean"):
            trial.cast(pr_refresh, PrSweep(bound=3))

        assert "the run failed: the worktree is not clean" in trial.deltas[-1]
        assert trial.steps == ["list_prs", "next_pr", "check_clean", "report"]
