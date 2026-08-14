"""Taking one reviewed branch, answering it item by item, and shipping it."""

import json
from typing import TYPE_CHECKING

import pytest
from vekna.folio.coding_claude import ClaudeOptions
from vekna.lexicon import RitualError, done, goto

from ludamus.edges.rituals.pr_review import (
    Branch,
    Instructed,
    Landing,
    PrReview,
    Shipped,
    Triage,
    gates,
    hand_back,
    land,
    look,
    pick,
    plan,
    pr_review,
    settle,
    work,
)
from ludamus.edges.rituals.shell import (
    COVERAGE,
    HERE,
    LIST,
    PR_FIX,
    QA_LABEL,
    STATUS,
    THERMO_LABEL,
    WAIT_LABEL,
    checkout,
    label,
    plain,
    unsettled,
)
from ludamus.edges.rituals.state import TriageItem, TriageNotes

if TYPE_CHECKING:
    from vekna.trial import Trial

_REPORT = "Diff Coverage\nsrc/thing.py (80.0%): Missing lines 12-14\n"
_COVERED = "Diff Coverage\nTotal: 10 lines\nMissing: 0 lines\n"
_READING = "Triage the open review threads*"
_ITEM = TriageItem(
    where="src/thing.py",
    what="the guard is missing",
    priority="p1",
    action="fix",
    thread="PRRT_1",
)
_ALSO = TriageItem(
    where="docs/thing.md",
    what="stale example",
    priority="p3",
    action="file",
    thread="PRRT_2",
)

# Fixed per name rather than counted off the listing: `feature` is the pull
# request every fixture here is built around, and the threads are read by number.
_NUMBERS = {"feature": 7, "older": 3, "main": 9}


# The command as it is answered rather than as it is run: `when` is a glob, and
# the jq that ends this one is full of brackets a glob reads as a character
# class.
def _asks(name: str) -> str:
    return f"slug=*-F number={_NUMBERS[name]} -q *"


def _listing(*branches: str, waiting: str = "", tested: str = "") -> str:
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
            "labels": [
                {"name": one}
                for one in (
                    THERMO_LABEL,
                    *([WAIT_LABEL] if name == waiting else []),
                    *([QA_LABEL] if name == tested else []),
                )
            ],
        }
        for spot, name in enumerate(branches, start=1)
    ]
    return json.dumps(rows)


def _open(trial: Trial, *branches: str, count: str = "2\n") -> None:
    for name in branches:
        trial.shell.replies(when=_asks(name), stdout=count)


class TestPick:
    def test_the_branch_you_are_standing_on_is_preferred(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("older", "feature"))
        _open(trial, "feature")
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == goto(look, branch)
        # The other one is never even asked about: the branch you are on is
        # asked first, and an open thread on it is where the looking stops.
        assert unsettled(_NUMBERS["older"]) not in trial.shell.commands

    # Somebody else's terminal is on the other one, and neither cast has to know
    # that to leave it alone.
    def test_a_branch_you_are_not_on_is_taken_oldest_first(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("older", "feature"))
        _open(trial, "older", "feature")
        trial.shell.replies(when=HERE, stdout="main\n")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == goto(look, Branch(name="older", number=3, bound=2))

    def test_a_branch_with_every_thread_settled_is_not_taken(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")
        _open(trial, "feature", count="0\n")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == done(Shipped(outcome="nothing"))

    # No review has been posted on it, so there is nothing here to answer. The
    # night is what puts that label on.
    def test_an_unreviewed_pull_request_is_not_taken(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=json.dumps([]))
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == done(Shipped(outcome="nothing"))

    # Answered in full by an earlier cast, and the label is what says so.
    def test_a_pull_request_already_labelled_for_qa_is_not_taken(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature", tested="feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == done(Shipped(outcome="nothing"))
        assert unsettled(_NUMBERS["feature"]) not in trial.shell.commands

    # The label is how a branch is parked, and an open thread on it does not
    # un-park it.
    def test_a_waiting_pull_request_is_left_alone(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature", waiting="feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == done(Shipped(outcome="nothing"))
        assert unsettled(7) not in trial.shell.commands

    # This cast ends in a commit and a push on whatever branch it takes.
    def test_main_is_never_taken(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("main"))
        trial.shell.replies(when=HERE, stdout="main\n")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == done(Shipped(outcome="nothing"))

    # A count nobody could take is not a branch with nothing to do, and it is
    # not one to check out on a guess either. It is also not silence: the
    # ending says there is no review waiting, and that sentence is a guess
    # unless it names the branches it could not read.
    def test_a_count_gh_will_not_give_skips_the_branch_and_is_said_out_loud(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")
        trial.shell.replies(when=_asks("feature"), exit_code=1, stderr="rate limited")

        transition = trial.walk(pick, PrReview(bound=2))

        assert transition == done(Shipped(outcome="nothing"))
        assert trial.deltas == [
            "gh would not say what is open on feature",
            "no pull request of yours has a review waiting",
        ]

    # Every count came back, so there is nothing to confess and the ending
    # stands on its own.
    def test_counts_that_all_came_back_say_nothing_extra(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")
        _open(trial, "feature", count="0\n")

        trial.walk(pick, PrReview(bound=2))

        assert trial.deltas == ["no pull request of yours has a review waiting"]

    # Everything below this line moves a branch under you and commits what it
    # finds, so work left in the tree is work that would end up on it.
    def test_a_dirty_worktree_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS, stdout=" M src/thing.py\n")

        with pytest.raises(RitualError, match="the worktree is not clean"):
            trial.walk(pick, PrReview(bound=2))

    # A tree it could not read is not a tree it may call clean.
    def test_a_failed_status_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS, exit_code=128, stderr="not a repository")

        with pytest.raises(RitualError, match="git status failed"):
            trial.walk(pick, PrReview(bound=2))

    def test_a_failed_listing_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, exit_code=1, stderr="rate limited")

        with pytest.raises(RitualError, match="could not list your pull requests"):
            trial.walk(pick, PrReview(bound=2))

    def test_a_listing_that_cannot_be_read_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout="{}")

        with pytest.raises(RitualError, match="something unreadable"):
            trial.walk(pick, PrReview(bound=2))

    def test_a_head_git_will_not_name_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=HERE, exit_code=128, stderr="no HEAD")

        with pytest.raises(RitualError, match="could not read the current branch"):
            trial.walk(pick, PrReview(bound=2))


class TestLook:
    # The reading happens after the checkout: an item is triaged against this
    # branch's code, and until then that is somebody else's code.
    def test_the_reading_runs_on_the_branch_and_its_items_go_on(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies(TriageNotes(items=[_ITEM]), when=_READING)

        transition = trial.walk(look, branch)

        assert transition == goto(plan, Triage(branch=branch, items=[_ITEM]))
        assert trial.shell.commands == [checkout("feature")]

    # The one constrained agent call in either ritual: it is handed text a
    # stranger wrote, so the allowlist enforces read-only rather than the prompt
    # asking for it.
    def test_the_reading_agent_is_bound_by_an_allowlist(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies(TriageNotes(items=[_ITEM]), when=_READING)

        trial.walk(look, branch)

        assert trial.coding.calls[0].focus_options == ClaudeOptions(
            permission_mode="dontAsk",
            allowed_tools=["Bash", "Read", "Grep", "Glob"],
            effort="high",
        )

    # Asked before anything moves: `pick` reaches a branch you are not standing
    # on exactly when yours had nothing waiting, so a `no` that had already
    # checked out would leave you on a branch you never asked for.
    def test_saying_no_ends_the_cast_where_you_were_standing(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=False, when="read the review*")

        transition = trial.walk(look, branch)

        assert transition == done(Shipped(outcome="declined", branch="feature"))
        assert not trial.coding.prompts
        assert not trial.shell.commands

    # `pick` only got here on a thread nobody had settled, so this is the
    # reading disagreeing with gh — and nothing is committed on that.
    def test_a_reading_that_finds_nothing_ends_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies(TriageNotes(items=[]), when=_READING)

        transition = trial.walk(look, branch)

        assert transition == done(Shipped(outcome="nothing", branch="feature"))

    # An answer outside the schema, and an agent that died mid-flight, both end
    # a cast that has nothing to show for itself yet.
    def test_a_reading_that_cannot_be_read_fails_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies("no idea, sorry", when=_READING)

        with pytest.raises(RitualError, match="did not answer in the shape"):
            trial.walk(look, branch)

    def test_a_failed_checkout_fails_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer=True, when="read the review*")
        trial.shell.replies(when="git checkout*", exit_code=1, stderr="in the way")

        with pytest.raises(RitualError, match="could not check out feature"):
            trial.walk(look, branch)


class TestPlan:
    # What you say about an item rides down with that item's own thread, so the
    # round that answers it is not matching your words to a thread by eye.
    def test_every_item_is_asked_about_and_carries_your_answer(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer="it guards the empty case", when="1.*")
        trial.decide.answers(answer="not worth an issue, reject it", when="2.*")

        transition = trial.walk(plan, Triage(branch=branch, items=[_ITEM, _ALSO]))

        assert isinstance(transition.payload, Instructed)
        prompt = transition.payload.prompt
        assert "thread: PRRT_1\n   what I want: it guards the empty case" in prompt
        assert "thread: PRRT_2\n   what I want: not worth an issue, reject it" in prompt

    # The reading already proposed something, and saying nothing is agreeing
    # with it.
    def test_saying_nothing_takes_the_readings_own_proposal(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer="", when="1.*")

        transition = trial.walk(plan, Triage(branch=branch, items=[_ITEM]))

        assert isinstance(transition.payload, Instructed)
        assert "what I want: fix it, as the reading says" in transition.payload.prompt

    def test_the_triage_goes_on_your_terminal_before_the_first_question(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer="", when="1.*")
        trial.decide.answers(answer="", when="2.*")

        trial.walk(plan, Triage(branch=branch, items=[_ITEM, _ALSO]))

        assert "2 outstanding — p1: 1, p2: 0, p3: 1" in trial.deltas[0]
        assert "the guard is missing" in trial.deltas[0]


class TestWork:
    def test_the_prompt_is_sent_as_it_was_assembled(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.coding.replies("settled two threads")

        transition = trial.walk(
            work, Instructed(branch=branch, prompt="the triage: fix p1")
        )

        assert transition == goto(hand_back, branch)
        assert trial.coding.prompts == ["the triage: fix p1"]

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

    # An empty line is an answer here too, and the obvious one: nothing more to
    # fix. Forwarded it would be an empty instruction to an agent that writes
    # code, which is a round of unpredictable edits bought with a stray return.
    def test_saying_nothing_ships_rather_than_asking_the_agent(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer="fix", when="*ship it?*")
        trial.decide.answers(answer="", when="*fix?*")

        transition = trial.walk(hand_back, branch)

        assert transition == goto(gates, Landing(branch=branch))
        assert not trial.coding.prompts


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
    def test_the_work_is_committed_and_pushed(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push*")

        transition = trial.walk(land, branch)

        assert transition == goto(settle, branch)

    def test_a_failed_commit_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git add*", exit_code=1, stderr="hook refused")

        with pytest.raises(RitualError, match="could not commit the triage work"):
            trial.walk(land, branch)

    def test_a_failed_push_fails_the_cast(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push*", exit_code=1, stderr="rejected")

        with pytest.raises(RitualError, match="could not push feature"):
            trial.walk(land, branch)


class TestSettle:
    # The label is a claim about the threads, so it is asked of gh rather than
    # assumed off the round that said it had settled them.
    def test_a_branch_with_nothing_left_open_earns_the_label(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_asks("feature"), stdout="0\n")
        trial.shell.replies(when="gh pr edit*")

        transition = trial.walk(settle, branch)

        assert transition == done(Shipped(outcome="shipped", branch="feature"))
        assert f"gh pr edit 7 --add-label {QA_LABEL}" in trial.shell.commands

    # Shipped either way — the work is committed and up by now — and what is
    # left over is said out loud rather than labelled over.
    def test_threads_left_open_are_reported_and_not_labelled(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_asks("feature"), stdout="2\n")

        transition = trial.walk(settle, branch)

        assert transition == done(Shipped(outcome="shipped", branch="feature"))
        assert "2 review threads are still open on feature" in trial.deltas[0]
        # A failed `gh pr edit` is swallowed into a delta here, so the label
        # going on wrongly would look exactly like this test passing.
        assert label(QA_LABEL, number=7) not in trial.shell.commands

    def test_a_count_gh_will_not_give_labels_nothing(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_asks("feature"), exit_code=1, stderr="rate limited")

        transition = trial.walk(settle, branch)

        assert transition == done(Shipped(outcome="shipped", branch="feature"))
        assert "would not say what is left open" in trial.deltas[0]


class TestPrReview:
    def test_a_morning_with_nothing_waiting_ends_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")
        _open(trial, "feature", count="0\n")

        result = trial.cast(pr_review, PrReview(bound=2))

        assert result == Shipped(outcome="nothing")
        assert trial.steps == ["pick"]

    def test_a_reviewed_branch_goes_all_the_way_to_the_label(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=_asks("feature"), stdout="1\n")
        trial.shell.replies(when=HERE, stdout="feature\n")
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies(TriageNotes(items=[_ITEM]), when=_READING)
        trial.decide.answers(answer="fix it", when="1.*")
        trial.coding.replies("settled the thread", when="Below is a triage*")
        trial.decide.answers(answer="ship", when="*ship it?*")
        trial.shell.replies(when=plain(PR_FIX))
        trial.shell.replies(when=plain(COVERAGE), stdout=_COVERED)
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push*")
        trial.shell.replies(when=_asks("feature"), stdout="0\n")
        trial.shell.replies(when="gh pr edit*")

        result = trial.cast(pr_review, PrReview(bound=2))

        assert result == Shipped(outcome="shipped", branch="feature")
        assert trial.steps == [
            "pick",
            "look",
            "plan",
            "work",
            "hand_back",
            "gates",
            "land",
            "settle",
        ]
