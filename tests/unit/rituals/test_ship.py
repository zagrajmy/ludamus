"""Pushing one branch, and what happens to the triage it carries."""

from typing import TYPE_CHECKING

import pytest
from vekna.lexicon import RitualError, done, goto

from ludamus.edges.rituals.shell import COVERAGE, PR_FIX, plain
from ludamus.edges.rituals.ship import (
    AHEAD,
    DIFF,
    FETCH,
    Branch,
    Instructed,
    Landing,
    Ship,
    Shipped,
    gates,
    hand_back,
    land,
    look,
    paged,
    pick,
    push_branch,
    read_triage,
    ship,
    work,
)

if TYPE_CHECKING:
    from vekna.trial import Trial

_STATUS = "git status --porcelain"
_REPORT = "Diff Coverage\nsrc/thing.py (80.0%): Missing lines 12-14\n"
_COVERED = "Diff Coverage\nTotal: 10 lines\nMissing: 0 lines\n"


class TestPick:
    def test_the_first_branch_ahead_is_taken(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=FETCH)
        trial.shell.replies(when=AHEAD, stdout="feature\n")

        transition = trial.walk(pick, Ship(bound=2))

        assert transition == goto(look, branch)

    def test_nothing_ahead_ends_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=FETCH)
        trial.shell.replies(when=AHEAD, stdout="\n")

        transition = trial.walk(pick, Ship(bound=2))

        assert transition == done(Shipped())

    # Everything below this line moves a branch under you and commits what it
    # finds, so work left in the tree is work that would end up on it.
    def test_a_dirty_worktree_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS, stdout=" M src/thing.py\n")

        with pytest.raises(RitualError, match="the worktree is not clean"):
            trial.walk(pick, Ship(bound=2))

    def test_a_failed_fetch_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=FETCH, exit_code=1, stderr="no route to host")

        with pytest.raises(RitualError, match="could not fetch"):
            trial.walk(pick, Ship(bound=2))

    # A tree it could not read is not a tree it may call clean.
    def test_a_failed_status_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS, exit_code=128, stderr="not a repository")

        with pytest.raises(RitualError, match="git status failed"):
            trial.walk(pick, Ship(bound=2))

    def test_a_failed_listing_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=FETCH)
        trial.shell.replies(when=AHEAD, exit_code=1, stderr="bad format")

        with pytest.raises(RitualError, match="could not list the branches"):
            trial.walk(pick, Ship(bound=2))


class TestLook:
    def test_the_diff_is_shown_before_the_question(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=paged(DIFF))
        trial.decide.answers(answer=True)

        transition = trial.walk(look, branch)

        assert transition == goto(push_branch, branch)
        assert trial.shell.commands[-1] == paged(DIFF)

    def test_saying_no_ends_the_cast_without_pushing(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=paged(DIFF))
        trial.decide.answers(answer=False)

        transition = trial.walk(look, branch)

        assert transition == done(Shipped(branch="feature"))

    def test_a_failed_checkout_fails_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*", exit_code=1, stderr="in the way")

        with pytest.raises(RitualError, match="could not check out feature"):
            trial.walk(look, branch)


class TestPushBranch:
    def test_a_branch_without_a_triage_is_done_once_pushed(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git push")
        trial.shell.replies(when="test -f triage.md", exit_code=1)

        transition = trial.walk(push_branch, branch)

        assert transition == done(Shipped(branch="feature", pushed=True))

    def test_a_triage_is_read_next(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git push")
        trial.shell.replies(when="test -f triage.md")

        transition = trial.walk(push_branch, branch)

        assert transition == goto(read_triage, branch)

    def test_a_failed_push_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git push", exit_code=1, stderr="rejected")

        with pytest.raises(RitualError, match="could not push feature"):
            trial.walk(push_branch, branch)


class TestReadTriage:
    def test_what_you_say_opens_the_first_round(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=paged("cat triage.md"))
        trial.decide.answers(answer="fix p1, file p3")

        transition = trial.walk(read_triage, branch)

        assert transition == goto(
            work,
            Instructed(branch=branch, instructions="fix p1, file p3", opening=True),
        )


class TestWork:
    def test_the_opening_round_says_what_the_job_is(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.coding.replies("resolved two threads")

        transition = trial.walk(
            work, Instructed(branch=branch, instructions="fix p1", opening=True)
        )

        assert transition == goto(hand_back, branch)
        assert "triage.md" in trial.coding.prompts[0]
        assert trial.coding.prompts[0].endswith("fix p1")

    # The agent is mid-thread by then, and repeating the standing instructions
    # would argue with what it has just been told.
    def test_a_later_round_is_the_instruction_alone(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.coding.replies("done")

        transition = trial.walk(
            work, Instructed(branch=branch, instructions="also rename it")
        )

        assert transition == goto(hand_back, branch)
        assert trial.coding.prompts == ["also rename it"]

    # An agent that dies mid-flight — a spent token budget, a killed CLI — and
    # the unscripted call is that failure's shape here.
    def test_an_agent_that_dies_fails_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        with pytest.raises(RitualError, match="stopped mid-flight"):
            trial.walk(work, Instructed(branch=branch, instructions="fix p1"))


class TestHandBack:
    def test_shipping_goes_to_the_gates(self, trial: Trial, branch: Branch) -> None:
        trial.decide.answers(answer="ship")

        transition = trial.walk(hand_back, branch)

        assert transition == goto(gates, Landing(branch=branch))

    def test_fixing_asks_what_and_goes_round_again(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer="fix", when="*ship it?*")
        trial.decide.answers(answer="drop the helper", when="*fix?*")

        transition = trial.walk(hand_back, branch)

        assert transition == goto(
            work, Instructed(branch=branch, instructions="drop the helper")
        )


class TestGates:
    def test_both_gates_green_lands_the_branch(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when=plain(COVERAGE), stdout=_COVERED)

        transition = trial.walk(gates, Landing(branch=branch))

        assert transition == goto(land, branch)

    def test_a_red_gate_is_handed_to_the_agent(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="E501 too long")
        trial.coding.replies("shortened it")

        transition = trial.walk(gates, Landing(branch=branch))

        assert transition == goto(gates, Landing(branch=branch, tries=1))
        assert "E501 too long" in trial.coding.prompts[0]

    # diff-cover runs without --fail-under, so this one exits 0 and says so in
    # the report instead.
    def test_missing_lines_are_covered_though_the_gate_exits_zero(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when=plain(COVERAGE), stdout=_REPORT)
        trial.coding.replies("wrote the tests")

        transition = trial.walk(gates, Landing(branch=branch))

        assert transition == goto(gates, Landing(branch=branch, tries=1))
        assert "Missing lines 12-14" in trial.coding.prompts[0]

    # A coverage run that will not finish is a red gate like any other, not a
    # branch with nothing left to cover.
    def test_a_coverage_run_that_dies_is_repaired_as_a_gate(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(
            when=plain(COVERAGE), exit_code=1, stderr="no browser to run"
        )
        trial.coding.replies("installed it")

        transition = trial.walk(gates, Landing(branch=branch))

        assert transition == goto(gates, Landing(branch=branch, tries=1))
        assert COVERAGE in trial.coding.prompts[0]

    def test_a_spent_bound_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="still red")

        with pytest.raises(RitualError, match="still red after 2 attempts"):
            trial.walk(gates, Landing(branch=branch, tries=2))


class TestLand:
    def test_the_triage_work_is_committed_and_pushed(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push")

        transition = trial.walk(land, branch)

        assert transition == done(Shipped(branch="feature", pushed=True, triaged=True))

    def test_a_failed_commit_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git add*", exit_code=1, stderr="hook refused")

        with pytest.raises(RitualError, match="could not commit the triage work"):
            trial.walk(land, branch)

    def test_a_failed_push_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push", exit_code=1, stderr="rejected")

        with pytest.raises(RitualError, match="could not push feature"):
            trial.walk(land, branch)


class TestShip:
    def test_a_branch_with_no_triage_is_pushed_and_that_is_all(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=FETCH)
        trial.shell.replies(when=AHEAD, stdout="feature\n")
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=paged(DIFF))
        trial.decide.answers(answer=True)
        trial.shell.replies(when="git push")
        trial.shell.replies(when="test -f triage.md", exit_code=1)

        result = trial.cast(ship, Ship(bound=2))

        assert result == Shipped(branch="feature", pushed=True)
        assert trial.steps == ["pick", "look", "push_branch"]

    def test_a_triaged_branch_goes_all_the_way_to_the_gates(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=FETCH)
        trial.shell.replies(when=AHEAD, stdout="feature\n")
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=paged(DIFF))
        trial.decide.answers(answer=True, when="push feature?")
        trial.shell.replies(when="git push", always=True)
        trial.shell.replies(when="test -f triage.md")
        trial.shell.replies(when=paged("cat triage.md"))
        trial.decide.answers(answer="fix p1 and p2", when="*done with it?*")
        trial.coding.replies("resolved the threads")
        trial.decide.answers(answer="ship", when="*ship it?*")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when=plain(COVERAGE), stdout=_COVERED)
        trial.shell.replies(when="git add*")

        result = trial.cast(ship, Ship(bound=2))

        assert result == Shipped(branch="feature", pushed=True, triaged=True)
        assert trial.steps == [
            "pick",
            "look",
            "push_branch",
            "read_triage",
            "work",
            "hand_back",
            "gates",
            "land",
        ]
