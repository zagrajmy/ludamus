"""Taking every reviewed branch in turn, answering it item by item, shipping it."""

import json
from typing import TYPE_CHECKING, Any

import pytest
from vekna.folio.coding_claude import ClaudeOptions
from vekna.lexicon import RitualError, done, goto

from ludamus.edges.rituals.pr_review import (
    Branch,
    Instructed,
    Landing,
    Picking,
    PrReview,
    Reviewed,
    Triage,
    gates,
    hand_back,
    land,
    look,
    pick,
    plan,
    pr_review,
    queue_up,
    recap,
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
from ludamus.edges.rituals.state import PullRequest, TriageItem, TriageNotes

if TYPE_CHECKING:
    from vekna.trial import Trial

_READING = "Triage the open review threads*"
_ITEM = TriageItem(
    where="src/thing.py",
    raised="add a guard before the loop",
    what="the guard is missing",
    priority="p1",
    action="fix",
    thread="PRRT_1",
)
_ALSO = TriageItem(
    where="docs/thing.md",
    raised="the example in the docs no longer runs",
    what="stale example",
    priority="p3",
    action="file",
    thread="PRRT_2",
)
_STALE = TriageItem(
    where="src/thing.py",
    raised="rename the helper",
    what="the line it points at is gone",
    priority="p4",
    action="reject",
    thread="PRRT_3",
)

# Fixed per name rather than counted off the listing: `feature` is the pull
# request every fixture here is built around, threads are read by number, and a
# branch keeps its place in the queue however it is listed.
_NUMBERS = {"feature": 7, "older": 3, "main": 9}
_SPOTS = {"older": 1, "feature": 2, "main": 3}


# The command as it is answered rather than as it is run: `when` is a glob, and
# the jq that ends this one is full of brackets a glob reads as a character class.
def _asks(name: str) -> str:
    return f"slug=*-F number={_NUMBERS[name]} -q *"


def _row(name: str, *, waiting: str = "", tested: str = "") -> dict[str, Any]:
    return {
        "number": _NUMBERS[name],
        "title": f"Add {name}",
        "url": f"https://github.com/fancysnake/ludamus/pull/{_NUMBERS[name]}",
        "headRefName": name,
        "baseRefName": "main",
        # Ascending with the spot, so the lower one is also the one that has
        # been waiting longest.
        "updatedAt": f"2026-08-0{_SPOTS[name]}T22:00:00Z",
        "labels": [
            {"name": one}
            for one in (
                THERMO_LABEL,
                *([WAIT_LABEL] if name == waiting else []),
                *([QA_LABEL] if name == tested else []),
            )
        ],
    }


def _listing(*branches: str, waiting: str = "", tested: str = "") -> str:
    return json.dumps([_row(name, waiting=waiting, tested=tested) for name in branches])


# The same rows as objects, in the order the queue is expected to hold them.
def _queued(*branches: str) -> list[PullRequest]:
    return [PullRequest.model_validate(_row(name)) for name in branches]


def _picked(bound: int = 2, **rest: Any) -> Picking:
    return Picking(bound=bound, **rest)


class TestQueueUp:
    def test_the_branch_you_are_standing_on_is_first(self, trial: Trial) -> None:
        trial.shell.replies(when=LIST, stdout=_listing("older", "feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(queue_up, _picked())

        assert transition == goto(pick, _picked(queue=_queued("feature", "older")))

    def test_the_rest_wait_in_the_order_they_have_been_waiting(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=LIST, stdout=_listing("feature", "older"))
        trial.shell.replies(when=HERE, stdout="main\n")

        transition = trial.walk(queue_up, _picked())

        assert transition == goto(pick, _picked(queue=_queued("older", "feature")))

    def test_an_unreviewed_pull_request_is_not_queued(self, trial: Trial) -> None:
        trial.shell.replies(when=LIST, stdout=json.dumps([]))
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(queue_up, _picked())

        assert transition == goto(pick, _picked())

    def test_a_pull_request_already_labelled_for_qa_is_not_queued(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=LIST, stdout=_listing("feature", tested="feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(queue_up, _picked())

        assert transition == goto(pick, _picked())

    # An open thread on a parked branch does not un-park it.
    def test_a_waiting_pull_request_is_left_alone(self, trial: Trial) -> None:
        trial.shell.replies(when=LIST, stdout=_listing("feature", waiting="feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")

        transition = trial.walk(queue_up, _picked())

        assert transition == goto(pick, _picked())

    def test_main_is_never_queued(self, trial: Trial) -> None:
        trial.shell.replies(when=LIST, stdout=_listing("main"))
        trial.shell.replies(when=HERE, stdout="main\n")

        transition = trial.walk(queue_up, _picked())

        assert transition == goto(pick, _picked())

    def test_a_failed_listing_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=LIST, exit_code=1, stderr="rate limited")

        with pytest.raises(RitualError, match="could not list your pull requests"):
            trial.walk(queue_up, _picked())

    def test_a_listing_that_cannot_be_read_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=LIST, stdout="{}")

        with pytest.raises(RitualError, match="something unreadable"):
            trial.walk(queue_up, _picked())

    def test_a_head_git_will_not_name_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=HERE, exit_code=128, stderr="no HEAD")

        with pytest.raises(RitualError, match="could not read the current branch"):
            trial.walk(queue_up, _picked())


class TestPick:
    def test_a_branch_with_a_thread_open_is_taken_off_the_queue_and_read(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=_asks("feature"), stdout="2\n")

        transition = trial.walk(pick, _picked(queue=_queued("feature")))

        assert transition == goto(look, branch)

    def test_the_branches_behind_it_ride_along(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=_asks("feature"), stdout="2\n")

        transition = trial.walk(pick, _picked(queue=_queued("feature", "older")))

        assert transition == goto(
            look,
            Branch(picking=_picked(queue=_queued("older")), name="feature", number=7),
        )
        # Asked for the branch whose turn it is and no other: the sweeps run
        # alongside this, and what is open on `older` is answered when `older`
        # comes up rather than now.
        assert unsettled(_NUMBERS["older"]) not in trial.shell.commands

    def test_a_branch_with_every_thread_settled_is_passed_over_without_a_row(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=_asks("feature"), stdout="0\n")

        transition = trial.walk(pick, _picked(queue=_queued("feature")))

        assert transition == goto(pick, _picked())
        assert not trial.deltas

    def test_a_count_gh_will_not_give_is_reported_and_the_cast_goes_on(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=STATUS)
        trial.shell.replies(when=_asks("feature"), exit_code=1, stderr="rate limited")

        transition = trial.walk(pick, _picked(queue=_queued("feature")))

        assert transition == goto(
            pick, _picked(reviewed=[Reviewed(branch="feature", outcome="unread")])
        )
        assert trial.deltas == ["gh would not say what is open on feature"]

    def test_an_empty_queue_ends_at_the_report(self, trial: Trial) -> None:
        transition = trial.walk(pick, _picked())

        assert transition == goto(recap, _picked())
        assert not trial.shell.commands

    def test_a_dirty_worktree_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS, stdout=" M src/thing.py\n")

        with pytest.raises(RitualError, match="the worktree is not clean"):
            trial.walk(pick, _picked(queue=_queued("feature")))

    # A tree it could not read is not a tree it may call clean.
    def test_a_failed_status_fails_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS, exit_code=128, stderr="not a repository")

        with pytest.raises(RitualError, match="git status failed"):
            trial.walk(pick, _picked(queue=_queued("feature")))


class TestLook:
    def test_the_reading_runs_on_the_branch_and_its_items_go_on(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies(TriageNotes(items=[_ITEM]), when=_READING)

        transition = trial.walk(look, branch)

        assert transition == goto(plan, Triage(branch=branch, items=[_ITEM]))
        assert trial.shell.commands == [checkout("feature")]

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

    # One you do not want to read now is not a reason to stop: the cast goes
    # through every branch that has a review waiting.
    def test_saying_no_takes_the_next_branch(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer=False, when="read the review*")

        transition = trial.walk(look, branch)

        assert transition == goto(
            pick, _picked(reviewed=[Reviewed(branch="feature", outcome="declined")])
        )
        assert not trial.coding.prompts
        assert not trial.shell.commands

    def test_a_reading_that_finds_nothing_takes_the_next_branch(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies(TriageNotes(items=[]), when=_READING)

        transition = trial.walk(look, branch)

        assert transition == goto(
            pick, _picked(reviewed=[Reviewed(branch="feature", outcome="nothing")])
        )

    # An answer outside the schema and an agent that died mid-flight both end a
    # cast with nothing to show for itself yet.
    def test_a_reading_that_cannot_be_read_fails_the_cast(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when="git checkout*")
        trial.decide.answers(answer=True, when="read the review*")
        trial.coding.replies("no idea, sorry", when=_READING)

        with pytest.raises(RitualError, match="did not answer in the shape"):
            trial.walk(look, branch)

    # Another worktree is standing on it, and there is a whole list of other
    # pull requests this could be reading instead.
    def test_a_branch_that_will_not_check_out_is_reported_and_left(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer=True, when="read the review*")
        trial.shell.replies(when="git checkout*", exit_code=1, stderr="in the way")

        transition = trial.walk(look, branch)

        assert transition == goto(
            pick,
            _picked(
                reviewed=[
                    Reviewed(branch="feature", outcome="elsewhere", note="in the way")
                ]
            ),
        )
        assert "checked out elsewhere" in trial.deltas[-1]
        assert not trial.coding.prompts


class TestPlan:
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

        assert "2 outstanding — p1: 1, p2: 0, p3: 1, p4: 0" in trial.deltas[0]
        assert "the guard is missing" in trial.deltas[0]

    def test_a_comment_with_no_work_in_it_is_counted_as_p4(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer="", when="1.*")

        trial.walk(plan, Triage(branch=branch, items=[_STALE]))

        assert "1 outstanding — p1: 0, p2: 0, p3: 0, p4: 1" in trial.deltas[0]
        assert "[p4/reject]" in trial.deltas[0]


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

    def test_a_later_round_is_the_instruction_alone(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.coding.replies("done")

        transition = trial.walk(
            work, Instructed(branch=branch, prompt="also rename it")
        )

        assert transition == goto(hand_back, branch)
        assert trial.coding.prompts == ["also rename it"]

    # An agent that dies mid-flight — a spent token budget, a killed CLI — which
    # the unscripted call stands in for here.
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

    def test_saying_nothing_ships_rather_than_asking_the_agent(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.decide.answers(answer="fix", when="*ship it?*")
        trial.decide.answers(answer="", when="*fix?*")

        transition = trial.walk(hand_back, branch)

        assert transition == goto(gates, Landing(branch=branch))
        assert not trial.coding.prompts


class TestGates:
    def test_a_green_gate_lands_the_branch(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when=plain(PR_FIX))

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

    # `pr-fix` reinstalls three package managers and formats the repository
    # before it reaches the thing that broke, and a repair does not pay for
    # that to find out whether one linter is happy now.
    def test_the_task_mise_named_is_what_the_repair_is_judged_by(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(
            when=plain(PR_FIX),
            exit_code=1,
            stdout="thing.py:1: error: Bad",
            stderr="[lint:mypy] ERROR task failed",
        )
        trial.coding.replies("typed it")

        transition = trial.walk(gates, Landing(branch=branch))

        assert transition == goto(
            gates, Landing(branch=branch, tries=1, gate="mise run lint:mypy")
        )

    def test_a_narrow_task_going_green_buys_the_gate_rather_than_the_landing(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=plain("mise run lint:mypy"))

        transition = trial.walk(
            gates, Landing(branch=branch, tries=1, gate="mise run lint:mypy")
        )

        assert transition == goto(gates, Landing(branch=branch, tries=1))
        assert trial.shell.commands == [plain("mise run lint:mypy")]

    # Diff coverage is `pr_sweep`'s slow pass and nobody else's: it is the
    # longest job in the toolchain, and shipping a triage does not wait on it.
    def test_the_coverage_gate_is_not_run(self, trial: Trial, branch: Branch) -> None:
        trial.shell.replies(when=plain(PR_FIX))

        trial.walk(gates, Landing(branch=branch))

        assert plain(COVERAGE) not in trial.shell.commands

    # The repair work is uncommitted, so there is no moving on to another
    # branch from here.
    def test_a_spent_bound_stops_the_cast_at_the_report(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=plain(PR_FIX), exit_code=1, stdout="still red")

        transition = trial.walk(gates, Landing(branch=branch, tries=2))

        assert transition == goto(
            recap, _picked(stopped=f"`{PR_FIX}` is still red after 2 attempts")
        )
        assert not trial.coding.prompts


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
    def test_a_branch_with_nothing_left_open_earns_the_label(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_asks("feature"), stdout="0\n")
        trial.shell.replies(when="gh pr edit*")

        transition = trial.walk(settle, branch)

        assert transition == goto(
            pick, _picked(reviewed=[Reviewed(branch="feature", outcome="shipped")])
        )
        assert f"gh pr edit 7 --add-label {QA_LABEL}" in trial.shell.commands

    def test_threads_left_open_are_reported_and_not_labelled(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_asks("feature"), stdout="2\n")

        transition = trial.walk(settle, branch)

        assert transition == goto(
            pick,
            _picked(
                reviewed=[
                    Reviewed(
                        branch="feature",
                        outcome="shipped",
                        note="2 review threads are still open",
                    )
                ]
            ),
        )
        assert "2 review threads are still open" in trial.deltas[0]
        # A failed `gh pr edit` is swallowed into a delta here, so the label
        # going on wrongly would look just like this passing.
        assert label(QA_LABEL, number=7) not in trial.shell.commands

    def test_a_count_gh_will_not_give_labels_nothing(
        self, trial: Trial, branch: Branch
    ) -> None:
        trial.shell.replies(when=_asks("feature"), exit_code=1, stderr="rate limited")

        transition = trial.walk(settle, branch)

        assert transition == goto(
            pick,
            _picked(
                reviewed=[
                    Reviewed(
                        branch="feature",
                        outcome="shipped",
                        note="gh would not say what is left open",
                    )
                ]
            ),
        )
        # The label is a claim about the threads, and a count nobody could take
        # is in no position to make it.
        assert label(QA_LABEL, number=7) not in trial.shell.commands


class TestReport:
    def test_every_branch_is_said_and_the_cast_ends_with_the_card(
        self, trial: Trial
    ) -> None:
        card = _picked(
            reviewed=[
                Reviewed(branch="feature", outcome="shipped"),
                Reviewed(branch="older", outcome="declined"),
            ]
        )

        transition = trial.walk(recap, card)

        assert transition == done(card)
        assert trial.deltas == [
            "pr_review — 2 branches\n  feature: shipped\n  older: left for later"
        ]

    def test_a_cast_that_stopped_says_so_and_what_it_never_reached(
        self, trial: Trial
    ) -> None:
        stopped = _picked(queue=_queued("older"), stopped="`pr-fix` is still red")

        with pytest.raises(RitualError, match="still red"):
            trial.walk(recap, stopped)

        # The report comes out before the failure, which is the whole reason a
        # red gate routes here rather than raising where it happened.
        assert "the cast stopped" in trial.deltas[0]
        assert "not reached:    older" in trial.deltas[0]

    def test_a_morning_with_nothing_waiting_says_so(self, trial: Trial) -> None:
        trial.walk(recap, _picked())

        assert "(none had a review waiting)" in trial.deltas[0]


class TestPrReview:
    def test_a_morning_with_nothing_waiting_ends_the_cast(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS, always=True)
        trial.shell.replies(when=LIST, stdout=_listing("feature"))
        trial.shell.replies(when=HERE, stdout="feature\n")
        trial.shell.replies(when=_asks("feature"), stdout="0\n")

        result = trial.cast(pr_review, PrReview(bound=2))

        assert result == _picked()
        assert trial.steps == ["queue_up", "pick", "pick", "recap"]

    def test_a_reviewed_branch_goes_all_the_way_to_the_label(
        self, trial: Trial
    ) -> None:
        trial.shell.replies(when=STATUS, always=True)
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
        trial.shell.replies(when="git add*")
        trial.shell.replies(when="git push*")
        trial.shell.replies(when=_asks("feature"), stdout="0\n")
        trial.shell.replies(when="gh pr edit*")

        result = trial.cast(pr_review, PrReview(bound=2))

        assert result == _picked(
            reviewed=[Reviewed(branch="feature", outcome="shipped")]
        )
        assert trial.steps == [
            "queue_up",
            "pick",
            "look",
            "plan",
            "work",
            "hand_back",
            "gates",
            "land",
            "settle",
            "pick",
            "recap",
        ]

    # The whole point of the loop: one branch shipped and the next one taken,
    # in one sitting.
    def test_the_cast_goes_on_to_the_next_branch(self, trial: Trial) -> None:
        trial.shell.replies(when=STATUS, always=True)
        trial.shell.replies(when=LIST, stdout=_listing("older", "feature"))
        trial.shell.replies(when=HERE, stdout="main\n")
        trial.shell.replies(when=_asks("older"), stdout="1\n")
        trial.shell.replies(when=_asks("feature"), stdout="1\n")
        # Neither is read, so both fall through to the next branch — what is
        # under test here is that there is a next branch at all.
        trial.decide.answers(answer=False, when="read the review*", always=True)

        result = trial.cast(pr_review, PrReview(bound=2))

        assert result == _picked(
            reviewed=[
                Reviewed(branch="older", outcome="declined"),
                Reviewed(branch="feature", outcome="declined"),
            ]
        )
        assert trial.steps == [
            "queue_up",
            "pick",
            "look",
            "pick",
            "look",
            "pick",
            "recap",
        ]
