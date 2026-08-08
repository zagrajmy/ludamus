"""Taking a branch: listing, the clean check, the sync and the merge."""

import json
from typing import TYPE_CHECKING

from vekna.lexicon import Goto, goto

from ludamus.edges.rituals.pr_check import (
    check_clean,
    gate_check,
    list_prs,
    merge_base,
    next_pr,
    report,
    resolve_conflicts,
    set_aside,
    sync_branch,
)
from ludamus.edges.rituals.shell import LIST
from ludamus.edges.rituals.state import PullRequest, Run, Work

if TYPE_CHECKING:
    from vekna.trial import Trial

_STATUS = "git status --porcelain"
_UNMERGED = "git diff --name-only --diff-filter=U"


def _listed(*pulls: PullRequest) -> str:
    return json.dumps([pull.model_dump(by_alias=True) for pull in pulls])


class TestListPrs:
    def test_the_queue_is_ordered_oldest_modified_first(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        fresher = pull.model_copy(update={"number": 9, "updated_at": "2026-08-05"})
        trial.shell.replies(when="gh pr list*", stdout=_listed(fresher, pull))

        transition = trial.walk(list_prs, Run(bound=3))

        assert transition == goto(next_pr, Run(bound=3, queue=[pull, fresher]))
        assert trial.shell.commands == [LIST]

    def test_gh_failing_reports_rather_than_raising(self, trial: Trial) -> None:
        trial.shell.replies(when="gh pr list*", exit_code=1, stderr="no auth\n")

        transition = trial.walk(list_prs, Run(bound=3))

        assert transition == goto(
            report,
            Run(bound=3, stopped="gh could not list your pull requests: no auth"),
        )

    def test_unreadable_json_reports_rather_than_raising(self, trial: Trial) -> None:
        trial.shell.replies(when="gh pr list*", stdout="{not json")

        transition = trial.walk(list_prs, Run(bound=3))

        assert isinstance(transition, Goto)
        assert transition.target is report
        assert isinstance(transition.payload, Run)
        assert transition.payload.stopped.startswith("gh returned something unreadable")


class TestNextPr:
    def test_a_pull_request_is_taken_off_the_queue_with_no_budget_carried(
        self, trial: Trial, pull: PullRequest
    ) -> None:
        # The budgets belong to the branch that spent them, and this is the
        # only place a branch changes.
        run = Run(bound=3, queue=[pull])

        transition = trial.walk(next_pr, run)

        assert transition == goto(check_clean, Work(run=Run(bound=3), pr=pull))
        assert not trial.shell.commands

    def test_an_empty_queue_ends_at_the_report(self, trial: Trial) -> None:
        transition = trial.walk(next_pr, Run(bound=3, checked=[]))

        assert transition == goto(report, Run(bound=3))


class TestCheckClean:
    def test_a_clean_worktree_goes_on_to_the_sync(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_STATUS)

        transition = trial.walk(check_clean, work)

        assert transition == goto(sync_branch, work)
        assert trial.shell.commands == [_STATUS]

    # Fatal by design: everything past this step moves branches around, and
    # doing that over uncommitted work is how it gets lost.
    def test_a_dirty_worktree_ends_the_whole_run(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_STATUS, stdout=" M src/thing.py\n")

        transition = trial.walk(check_clean, work)

        assert isinstance(transition, Goto)
        assert transition.target is report
        assert isinstance(transition.payload, Run)
        dirty = "the worktree is not clean:\nM src/thing.py"
        assert transition.payload.stopped == dirty
        assert [row.outcome for row in transition.payload.checked] == ["blocked"]


class TestSyncBranch:
    def test_the_base_and_the_branch_are_taken_before_the_merge(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="git fetch*", always=True)
        trial.shell.replies(when="git checkout feature*", always=True)

        transition = trial.walk(sync_branch, work)

        assert transition == goto(merge_base, work)
        assert trial.shell.commands == [
            "git fetch --prune origin && git checkout main && git pull --ff-only",
            "git checkout feature && git merge --ff-only origin/feature",
        ]

    def test_a_base_that_will_not_update_ends_the_whole_run(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="git fetch*", exit_code=1, stderr="network down")

        transition = trial.walk(sync_branch, work)

        assert isinstance(transition, Goto)
        assert transition.target is report
        assert isinstance(transition.payload, Run)
        assert transition.payload.stopped == "could not update main: network down"

    # `merge --ff-only`, never `reset --hard`: a branch this ritual worked on
    # last night carries commits origin has not seen. A diverged branch is set
    # aside rather than flattened.
    def test_a_branch_that_has_diverged_is_set_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="git fetch*")
        trial.shell.replies(
            when="git checkout feature*", exit_code=1, stderr="diverged"
        )

        transition = trial.walk(sync_branch, work)

        assert transition == goto(
            set_aside,
            work.model_copy(update={"note": "could not take the branch: diverged"}),
        )


class TestMergeBase:
    def test_a_clean_merge_goes_straight_to_the_gates(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="git merge --no-edit*")

        transition = trial.walk(merge_base, work)

        assert transition == goto(gate_check, work)
        assert trial.shell.commands == ["git merge --no-edit main"]

    def test_conflicts_route_to_the_agent_with_the_merge_still_open(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="git merge --no-edit*", exit_code=1)
        trial.shell.replies(when=_UNMERGED, stdout="src/thing.py\n")

        transition = trial.walk(merge_base, work)

        assert transition == goto(
            resolve_conflicts, work.model_copy(update={"merging": True})
        )

    # A merge fails for reasons no agent can fix — a stale index lock, a
    # missing ref — and those are not conflicts.
    def test_a_merge_that_failed_without_conflicts_is_set_aside(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when="git merge --no-edit*", exit_code=1, stderr="lock")
        trial.shell.replies(when=_UNMERGED)

        transition = trial.walk(merge_base, work)

        assert transition == goto(
            set_aside,
            work.model_copy(
                update={"note": "git merge failed without conflicts: lock"}
            ),
        )


class TestResolveConflicts:
    def test_the_conflicted_files_reach_the_agent_and_the_budget_goes_up(
        self, trial: Trial, work: Work
    ) -> None:
        trial.shell.replies(when=_UNMERGED, stdout="src/thing.py\n")
        trial.coding.replies("resolved them")

        transition = trial.walk(resolve_conflicts, work)

        assert transition == goto(
            resolve_conflicts,
            work.model_copy(update={"budgets": {"resolve_conflicts": 1}}),
        )
        assert "src/thing.py" in trial.coding.prompts[0]
        assert "Merging main into feature" in trial.coding.prompts[0]
        # First attempt on the thread: there is nothing yet to resume. That the
        # second one resumes it is a cast-level question — the session book
        # lives on the cast, not on one step.
        assert trial.coding.calls[0].resume is None

    # The index decides, not the agent: an empty diff-filter=U is the whole
    # answer, however confidently the agent reported success.
    def test_an_empty_index_moves_on_and_hands_the_budget_back(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"resolve_conflicts": 2}})
        trial.shell.replies(when=_UNMERGED)

        transition = trial.walk(resolve_conflicts, spent)

        assert transition == goto(gate_check, work)
        assert not trial.coding.prompts

    def test_a_spent_budget_sets_the_branch_aside_without_asking_again(
        self, trial: Trial, work: Work
    ) -> None:
        spent = work.model_copy(update={"budgets": {"resolve_conflicts": 3}})
        trial.shell.replies(when=_UNMERGED, stdout="src/thing.py\n")

        transition = trial.walk(resolve_conflicts, spent)

        assert transition == goto(
            set_aside,
            spent.model_copy(update={"note": "the merge conflicts were not resolved"}),
        )
        assert not trial.coding.prompts
