"""How a branch ends, how the night ends, and the report that is always owed."""

import json
from typing import TYPE_CHECKING

import pytest
from vekna.lexicon import RitualError, done, goto

from ludamus.edges.rituals.pr_check import (
    finish_pr,
    next_pr,
    pr_check,
    report,
    set_aside,
)
from ludamus.edges.rituals.shell import COVERAGE, PR_FIX, plain
from ludamus.edges.rituals.state import (
    Checked,
    Closed,
    PrCheck,
    PullRequest,
    Report,
    Run,
    Work,
)

if TYPE_CHECKING:
    from vekna.trial import Trial

_AHEAD = "test feature = *"
_PUSH = "git push https-origin feature"
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
    # Asked of git rather than tracked in the payload: what needs pushing is
    # what origin has not got, whoever put it there.
    def test_the_row_carries_what_origin_has_not_got(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_AHEAD, stdout="2\n")

        transition = trial.walk(finish_pr, Closed(work=work, outcome="green"))

        assert transition == goto(next_pr, Run(bound=3, checked=[_GREEN_ROW]))

    # "Nothing to push" and "we could not tell" are different answers, and the
    # report prints them differently.
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
    # An abandoned branch cannot be left dirty for the next one, and its work is
    # not ours to throw away either — so the report names the stash.
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
                                '"pr_check left feature unfinished"'
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

    # A branch that stood down and then failed a reading step has two things to
    # say, and the second must not cost it the first: the morning has to hear
    # the red gate, not only the `gh` call that came after it.
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

    # `pr_review` reads the review the night posted, and one posted on a branch
    # that would not push is anchored to an older head. A row cannot be in both
    # lists: the push is what makes it ready.
    def test_a_green_row_that_would_not_push_is_not_ready(self, trial: Trial) -> None:
        transition = trial.walk(report, Run(bound=3, checked=[_GREEN_ROW]))

        assert transition == done(Report(checked=[_GREEN_ROW], to_push=["feature"]))
        assert "ready to test:  none" in trial.deltas[0]

    # Unknown counts as needing a push: this is read by someone deciding what to
    # do next, and "we could not tell" is not "nothing to do".
    def test_a_row_git_could_not_count_still_needs_pushing(self, trial: Trial) -> None:
        unknown = _GREEN_ROW.model_copy(update={"outcome": "blocked", "unpushed": None})

        transition = trial.walk(report, Run(bound=3, checked=[unknown]))

        assert transition == done(
            Report(checked=[unknown], to_push=["feature"], to_fix=["feature"])
        )
        assert "unknown" in trial.deltas[0]

    # The rows are a scannable list, and a verdict is a dozen lines of someone
    # else's output. It goes under the row, not through it.
    def test_a_verdict_in_a_note_is_indented_under_its_row(self, trial: Trial) -> None:
        blocked = _GREEN_ROW.model_copy(
            update={
                "outcome": "blocked",
                "note": f"`{PR_FIX}` is still red:\n1 failed\n2 passed",
            }
        )

        trial.walk(report, Run(bound=3, checked=[blocked]))

        assert "is still red:\n      1 failed\n      2 passed" in trial.deltas[0]

    # The summary goes out before the failure is raised, which is the whole
    # reason every ending routes here rather than raising where it happened.
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
        trial.shell.replies(when="git checkout feature*")
        trial.shell.replies(when="git merge --no-edit*")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when=plain(COVERAGE))
        trial.shell.replies(when="gh pr view 7 --json labels", stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*", always=True)
        trial.shell.replies(when="git add -A*", always=True)
        trial.shell.replies(when=_PUSH)
        # Nothing left over, because the push and this count speak to the same
        # remote.
        trial.shell.replies(when=_AHEAD, stdout="0\n")
        trial.coding.replies("posted the review", when="Review the changes*")

        result = trial.cast(pr_check, PrCheck(bound=3))

        assert result == Report(
            checked=[_GREEN_ROW.model_copy(update={"unpushed": 0})], ready=["feature"]
        )
        assert trial.steps == [
            "list_prs",
            "next_pr",
            "check_clean",
            "sync_branch",
            "merge_base",
            "gate_check",
            "finish_merge",
            "cover",
            "push_work",
            "quality_review",
            "finish_pr",
            "next_pr",
            "report",
        ]

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
        trial.shell.replies(when="git checkout feature*")
        trial.shell.replies(when="git merge --no-edit*")
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="red")
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="still red")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when=plain(COVERAGE))
        trial.shell.replies(when="gh pr view 7 --json labels", stdout='{"labels": []}')
        trial.shell.replies(when="gh pr edit*", always=True)
        trial.shell.replies(when="git add -A*", always=True)
        trial.shell.replies(when=_PUSH)
        trial.shell.replies(when=_AHEAD, stdout="2\n")
        trial.coding.replies("tried", when="*is this project's gate*", always=True)
        trial.coding.replies("posted the review", when="Review the changes*")

        result = trial.cast(pr_check, PrCheck(bound=3))

        assert result == Report(checked=[_GREEN_ROW], to_push=["feature"])
        assert trial.steps.count("gate_check") == _GATE_ROUNDS
        assert trial.coding.calls[0].resume is None
        assert trial.coding.calls[1].resume == "s1"

    # This is not a gate and does not fail fast: a pull request nobody can build
    # still has reviewers waiting, so the branch stands down and takes the same
    # review as any other before it is reported blocked.
    def test_a_branch_that_will_not_go_green_is_still_reviewed(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        trial.shell.replies(
            when="gh pr list*", stdout=json.dumps([pull.model_dump(by_alias=True)])
        )
        trial.shell.replies(when="git status --porcelain")
        trial.shell.replies(when="git fetch*")
        trial.shell.replies(when="git checkout feature*")
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

        result = trial.cast(pr_check, PrCheck(bound=1))

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
            "gate_check",
            "gate_check",
            "stand_down",
            "push_work",
            "quality_review",
            "finish_pr",
            "next_pr",
            "report",
        ]
        # The review is told what already stopped it, so it does not spend an
        # action item on a thing the report says.
        assert "already known not to be green" in trial.coding.prompts[1]

    # Fatal by design, and the report still comes out first.
    def test_a_dirty_worktree_fails_the_cast_after_the_report(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        trial.shell.replies(
            when="gh pr list*", stdout=json.dumps([pull.model_dump(by_alias=True)])
        )
        trial.shell.replies(when="git status --porcelain", stdout=" M src/thing.py\n")

        with pytest.raises(RitualError, match="the worktree is not clean"):
            trial.cast(pr_check, PrCheck(bound=3))

        assert "the run failed: the worktree is not clean" in trial.deltas[-1]
        assert trial.steps == ["list_prs", "next_pr", "check_clean", "report"]
