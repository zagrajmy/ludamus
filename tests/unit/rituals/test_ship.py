"""Taking one triaged branch, working through it, and shipping what comes out."""

import json
from typing import TYPE_CHECKING

import pytest
from vekna.lexicon import RitualError, done, goto

from ludamus.edges.rituals.agent import triage_work
from ludamus.edges.rituals.shell import (
    COVERAGE,
    LIST,
    PR_FIX,
    TRIAGE_TITLE,
    WAIT_LABEL,
    plain,
    triage_comment,
)
from ludamus.edges.rituals.ship import (
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
    ship,
    work,
)

if TYPE_CHECKING:
    from vekna.trial import Trial

_STATUS = "git status --porcelain"
_HERE = "git rev-parse --abbrev-ref HEAD"
_TRIAGE = f"{TRIAGE_TITLE}\n\np1: the guard is missing\n"
_READ = triage_comment(7)
_PAGED = paged(_READ)
# The command as it is answered, rather than as it is run: `when` is a glob, and
# the jq in it is full of brackets a glob reads as a character class.
_READS = "gh pr view 7 --json comments*"
_PAGES = "if :*gh pr view 7 --json comments*"
_REPORT = "Diff Coverage\nsrc/thing.py (80.0%): Missing lines 12-14\n"
_COVERED = "Diff Coverage\nTotal: 10 lines\nMissing: 0 lines\n"


# Fixed per name rather than counted off the listing: `feature` is the pull
# request every fixture here is built around, and the triage is now read by
# number.
_NUMBERS = {"feature": 7, "older": 3, "main": 9}


def _listing(*branches: str, waiting: str = "") -> str:
    rows = [
        {
            "number": _NUMBERS[name],
            "title": f"Add {name}",
            "url": f"https://github.com/fancysnake/ludamus/pull/{_NUMBERS[name]}",
            "headRefName": name,
            "baseRefName": "main",
            # Ascending with the listing, so the first name given is also the
            # one that has been waiting longest.
            "updatedAt": f"2026-08-0{spot}T22:00:00Z",
            "labels": [{"name": WAIT_LABEL}] if name == waiting else [],
        }
        for spot, name in enumerate(branches, start=1)
    ]
    return json.dumps(rows)


def _triaged(trial: Trial, *branches: str) -> None:
    for name in branches:
        pattern = f"gh pr view {_NUMBERS[name]} --json comments*"
        trial.shell.replies(when=pattern, stdout=_TRIAGE)


class TestPick:
    def test_the_branch_you_are_standing_on_is_preferred(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("older", "feature"))
        _triaged(trial, "feature")
        trial.shell.replies(when=_HERE, stdout="feature\n")

        transition = trial.walk(pick, Ship(bound=2))

        assert transition == goto(look, branch)
        # The other one is never even asked about: the branch you are on is
        # read first, and a triage on it is where the looking stops.
        assert triage_comment(_NUMBERS["older"]) not in trial.shell.commands

    # Somebody else's terminal is on the other one, and neither cast has to know
    # that to leave it alone.
    def test_a_branch_you_are_not_on_is_taken_oldest_first(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("older", "feature"))
        _triaged(trial, "older", "feature")
        trial.shell.replies(when=_HERE, stdout="main\n")

        transition = trial.walk(pick, Ship(bound=2))

        assert transition == goto(look, Branch(name="older", number=3, bound=2))

    # An empty read, not a failed one: `gh` is content with a pull request
    # nobody has commented on.
    def test_a_pull_request_without_a_triage_is_not_taken(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=_HERE, stdout="feature\n")
        trial.shell.replies(when=_READS)

        transition = trial.walk(pick, Ship(bound=2))

        assert transition == done(Shipped(outcome="nothing"))

    # The label is how a branch is parked, and a triage comment on it does not
    # un-park it.
    def test_a_waiting_pull_request_is_left_alone(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature", waiting="feature"))
        trial.shell.replies(when=_HERE, stdout="feature\n")

        transition = trial.walk(pick, Ship(bound=2))

        assert transition == done(Shipped(outcome="nothing"))
        assert _READ not in trial.shell.commands

    # This cast ends in a commit and a push on whatever branch it takes.
    def test_main_is_never_taken(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("main"))
        trial.shell.replies(when=_HERE, stdout="main\n")

        transition = trial.walk(pick, Ship(bound=2))

        assert transition == done(Shipped(outcome="nothing"))

    # Everything below this line moves a branch under you and commits what it
    # finds, so work left in the tree is work that would end up on it.
    def test_a_dirty_worktree_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS, stdout=" M src/thing.py\n")

        with pytest.raises(RitualError, match="the worktree is not clean"):
            trial.walk(pick, Ship(bound=2))

    # A tree it could not read is not a tree it may call clean.
    def test_a_failed_status_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS, exit_code=128, stderr="not a repository")

        with pytest.raises(RitualError, match="git status failed"):
            trial.walk(pick, Ship(bound=2))

    def test_a_failed_listing_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, exit_code=1, stderr="rate limited")

        with pytest.raises(RitualError, match="could not list your pull requests"):
            trial.walk(pick, Ship(bound=2))

    def test_a_listing_that_cannot_be_read_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout="{}")

        with pytest.raises(RitualError, match="something unreadable"):
            trial.walk(pick, Ship(bound=2))

    def test_a_head_git_will_not_name_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=_HERE, exit_code=128, stderr="no HEAD")

        with pytest.raises(RitualError, match="could not read the current branch"):
            trial.walk(pick, Ship(bound=2))


class TestLook:
    def test_the_triage_is_shown_before_the_questions(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=_PAGES)
        trial.decide.answers(answer=True, when="work on feature?")
        trial.decide.answers(answer="fix p1, file p3", when="*done with it?*")

        transition = trial.walk(look, branch)

        assert transition == goto(
            work, Instructed(branch=branch, prompt=triage_work(7) + "fix p1, file p3")
        )
        assert _PAGED in trial.shell.commands

    # The standing prompt is a complete instruction on its own, so saying
    # nothing is saying "do that".
    def test_saying_nothing_sends_the_standing_instruction(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=_PAGES)
        trial.decide.answers(answer=True, when="work on feature?")
        trial.decide.answers(answer="", when="*done with it?*")

        transition = trial.walk(look, branch)

        assert transition == goto(
            work, Instructed(branch=branch, prompt=triage_work(7))
        )

    def test_saying_no_ends_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=_PAGES)
        trial.decide.answers(answer=False, when="work on feature?")

        transition = trial.walk(look, branch)

        assert transition == done(Shipped(outcome="declined", branch="feature"))

    def test_a_failed_checkout_fails_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*", exit_code=1, stderr="in the way")

        with pytest.raises(RitualError, match="could not check out feature"):
            trial.walk(look, branch)


class TestWork:
    def test_the_prompt_is_sent_as_it_was_assembled(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.coding.replies("resolved two threads")

        transition = trial.walk(
            work, Instructed(branch=branch, prompt=triage_work(7) + "fix p1")
        )

        assert transition == goto(hand_back, branch)
        assert triage_comment(7, part="{id, body}") in trial.coding.prompts[0]
        assert trial.coding.prompts[0].endswith("fix p1")

    # The agent is mid-thread by then, and repeating the standing instructions
    # would argue with what it has just been told.
    def test_a_later_round_is_the_instruction_alone(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.coding.replies("done")

        transition = trial.walk(
            work, Instructed(branch=branch, prompt="also rename it")
        )

        assert transition == goto(hand_back, branch)
        assert trial.coding.prompts == ["also rename it"]

    # An agent that dies mid-flight — a spent token budget, a killed CLI — and
    # the unscripted call is that failure's shape here.
    def test_an_agent_that_dies_fails_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        with pytest.raises(RitualError, match="stopped mid-flight"):
            trial.walk(work, Instructed(branch=branch, prompt="fix p1"))


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
            work, Instructed(branch=branch, prompt="drop the helper")
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
        trial.shell.replies(when="git push*")

        transition = trial.walk(land, branch)

        assert transition == done(Shipped(outcome="shipped", branch="feature"))

    def test_a_failed_commit_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git add*", exit_code=1, stderr="hook refused")

        with pytest.raises(RitualError, match="could not commit the triage work"):
            trial.walk(land, branch)

    def test_a_failed_push_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push*", exit_code=1, stderr="rejected")

        with pytest.raises(RitualError, match="could not push feature"):
            trial.walk(land, branch)


class TestShip:
    def test_a_night_with_no_triage_ends_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=_HERE, stdout="feature\n")
        trial.shell.replies(when=_READS)

        result = trial.cast(ship, Ship(bound=2))

        assert result == Shipped(outcome="nothing")
        assert trial.steps == ["pick"]

    def test_a_triaged_branch_goes_all_the_way_to_the_gates(self, trial: Trial) -> None:
        trial.shell.replies(when=_STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        _triaged(trial, "feature")
        trial.shell.replies(when=_HERE, stdout="feature\n")
        trial.shell.replies(when="git checkout*")
        trial.shell.replies(when=_PAGES)
        trial.decide.answers(answer=True, when="work on feature?")
        trial.decide.answers(answer="fix p1 and p2", when="*done with it?*")
        trial.coding.replies("resolved the threads")
        trial.decide.answers(answer="ship", when="*ship it?*")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when=plain(COVERAGE), stdout=_COVERED)
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push*")

        result = trial.cast(ship, Ship(bound=2))

        assert result == Shipped(outcome="shipped", branch="feature")
        assert trial.steps == ["pick", "look", "work", "hand_back", "gates", "land"]
