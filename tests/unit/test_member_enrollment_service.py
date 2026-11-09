from datetime import UTC, datetime
from unittest.mock import MagicMock, call

import pytest

from ludamus.mills.enrollment_member import (
    MemberEnrollmentPeers,
    MemberEnrollmentService,
)
from ludamus.pacts.enrollment import (
    EnrollmentWindowSnapshot,
    SeatHoldRequest,
    SessionParticipationStatus,
    SessionSeatingDTO,
    VirtualEnrollmentConfig,
)
from ludamus.pacts.enrollment_member import (
    INCLUDE_VALUE,
    AccessProblem,
    AllowanceRefusal,
    AllowanceSpentError,
    EnrollAgendaDTO,
    EnrollFooterDTO,
    EnrollmentChoice,
    EnrollRefusal,
    EnrollSessionDTO,
    MemberEnrollError,
    MemberEnrollErrorCode,
    MemberEnrollOutcome,
    MemberEnrollQuery,
    MemberEnrollSubmission,
    NothingToChangeError,
    PartyMemberFlags,
    RosterMember,
    SeatsShortError,
    SessionUserParticipationData,
    SkippedPerson,
    SkipReason,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.party import (
    EnrollmentPartiesDTO,
    EnrollmentPartyMemberDTO,
    PartyConsentMode,
    PartyEnrolledNotification,
    PartyMembershipStatus,
    SelectedEnrollmentPartyDTO,
)
from ludamus.pacts.session_cards import SessionCardStatsDTO
from ludamus.pacts.user import CompanionDTO
from tests.unit.factories import FakeTransaction, event_dto, user_dto

Status = SessionParticipationStatus
_SESSION_ID = 40
_VIEWER = user_dto(pk=1, slug="viewer", full_name="Vera", name="Vera", email="v@x.pl")
_COMPANION = CompanionDTO(
    **user_dto(pk=2, slug="kid", full_name="Kid", name="Kid").model_dump()
)
_MEMBER = user_dto(pk=3, slug="mira", full_name="Mira", name="Mira", email="m@x.pl")
_PRESENTER_ID = 9
_PARTY_ID = 77


def _window(**overrides):
    return EnrollmentWindowSnapshot(
        **{"percentage_slots": 100, "max_waitlist_sessions": 2} | overrides
    )


def _seats(*, limit=4, enrolled=0):
    return SessionCardStatsDTO(
        participants_limit=limit,
        seating_percentage=100,
        enrolled_count=enrolled,
        waiting_count=0,
        enrollment_window_ids=frozenset({1}),
    )


def _session(*, windows=None, limit=4, enrolled=0, **overrides):
    values = {
        "pk": _SESSION_ID,
        "title": "Smoki",
        "cover_image_url": "",
        "facilitator_name": "GM",
        "description": "",
        "min_age": 0,
        "participants_limit": limit,
        "presenter_id": _PRESENTER_ID,
        "presenter": None,
        "agenda_item": EnrollAgendaDTO(
            start_time=datetime(2026, 7, 1, 10, tzinfo=UTC),
            end_time=datetime(2026, 7, 1, 12, tzinfo=UTC),
            space="Hall > Room",
        ),
        "is_publicly_scheduled": True,
        "event": event_dto(pk=5),
        "seats": _seats(limit=limit, enrolled=enrolled),
        "eligible_windows": [_window()] if windows is None else windows,
    }
    return EnrollSessionDTO(**values | overrides)


class FakeSeats:
    def __init__(self, *, session=None, statuses=None, **cfg):
        self.session = session or _session()
        self.statuses = dict(statuses or {})
        self.people = {
            "conflicted": set(cfg.get("conflicted", ())),
            "overlapping": set(cfg.get("overlapping", ())),
            "waiting": cfg.get("waiting", {}),
        }
        self.guests = cfg.get("guests", 0)
        self.seating = cfg.get("seating")
        self.on_lock = cfg.get("on_lock")
        self.log = []

    def read_session(self, *, session_id, event_slug, sphere_id):
        if self.session is None or session_id != _SESSION_ID:
            raise NotFoundError
        self.log.append(("read_session", event_slug, sphere_id))
        return self.session

    def read_statuses(self, *, session_id, user_ids):
        return {pk: s for pk, s in self.statuses.items() if pk in user_ids}

    def conflicted_user_ids(self, *, session_id, user_ids):
        return self.people["conflicted"] & set(user_ids)

    def overlapping_user_ids(self, *, session_id, user_ids):
        return self.people["overlapping"] & set(user_ids)

    def waitlist_counts(self, *, event_id, user_ids):
        return {pk: n for pk, n in self.people["waiting"].items() if pk in user_ids}

    def guest_count(self, *, session_id, host_id):
        return self.guests

    def lock_seating(self, session_id):
        self.log.append(("lock_session", session_id))
        if self.on_lock:
            self.on_lock(self)
        return self.seating or SessionSeatingDTO(
            title=self.session.title,
            participants_limit=self.session.participants_limit,
            presenter_id=self.session.presenter_id,
            enrolled_count=sum(
                s in {Status.CONFIRMED, Status.OFFERED} for s in self.statuses.values()
            )
            + self.guests,
            eligible_windows=self.session.eligible_windows,
        )

    def lock_seat_holders(self, *, user_ids, waiters_of=None):
        self.log.append(("lock_people", sorted(user_ids), waiters_of))

    def seat(self, *, session_id, user_id, status, party_id):
        self.log.append(("seat", user_id, status, party_id))
        self.statuses[user_id] = status

    def release(self, *, session_id, user_id):
        self.log.append(("release", user_id))
        return self.statuses.pop(user_id, None)

    def release_guests(self, *, session_id, host_id, count):
        self.log.append(("release_guests", host_id, count))
        self.guests -= count

    def read_seats(self, session_id):
        return _seats(enrolled=len(self.statuses))


_PASSES = VirtualEnrollmentConfig(user_slots=5)


def _peers(*, parties=None, config=_PASSES, **cfg):
    enrollment = MagicMock()
    enrollment.read_viewer.return_value = _VIEWER
    enrollment.read_users.return_value = cfg.get("users", [_MEMBER])
    enrollment.virtual_config.return_value = config
    enrollment.has_slot_access.return_value = cfg.get("member_access", True)
    enrollment.can_enroll_users.side_effect = cfg.get("passes", lambda **_: True)
    enrollment.get_used_slots.return_value = 2
    enrollment.get_vc_available_slots.return_value = 0
    party_service = MagicMock()
    party_service.enrollment_selection.return_value = parties or EnrollmentPartiesDTO(
        choices=[]
    )
    shadowban = MagicMock()
    shadowban.banned_user_ids.return_value = set(cfg.get("shadowbanned", ()))
    bans = MagicMock()
    bans.is_banned.return_value = cfg.get("banned", False)
    return MemberEnrollmentPeers(
        enrollment=enrollment,
        waitlist_promotion=MagicMock(),
        shadowban=shadowban,
        parties=party_service,
        event_bans=bans,
    )


def _service(repo, peers):
    return MemberEnrollmentService(
        transaction=FakeTransaction(), repository=repo, peers=peers
    )


def _query(**overrides):
    values = {
        "event_slug": "konwent",
        "session_id": _SESSION_ID,
        "sphere_id": 1,
        "viewer_id": _VIEWER.pk,
        "viewer_slug": _VIEWER.slug,
        "requested_party": None,
    }
    return MemberEnrollQuery(**values | overrides)


def _led_party(*, consent=PartyConsentMode.ACCEPT_BY_DEFAULT, **member):
    values = {
        "user_pk": _MEMBER.pk,
        "name": "Mira",
        "slug": "mira",
        "is_login_less": False,
        "is_leader": False,
        "consent_mode": consent,
        "status": PartyMembershipStatus.ACTIVE,
    }
    return EnrollmentPartiesDTO(
        choices=[],
        selected=SelectedEnrollmentPartyDTO(
            pk=_PARTY_ID,
            name="Ekipa",
            leader_name="Vera",
            is_own_led=True,
            members=[
                EnrollmentPartyMemberDTO(**values | member),
                EnrollmentPartyMemberDTO(
                    **values | {"user_pk": _VIEWER.pk, "is_leader": True}
                ),
            ],
        ),
        companions=[_COMPANION],
    )


def _page(repo=None, peers=None, **query):
    repo = repo or FakeSeats()
    peers = peers or _peers()
    return _service(repo, peers).read_page(_query(**query)), repo, peers


def _submit(repo, peers, choices, *, guests=None, desired=False, **query):
    service = _service(repo, peers)
    page = service.read_page(_query(**query))
    return service.submit(
        page=page,
        submission=MemberEnrollSubmission(
            choices=choices, guests=guests, desired=desired
        ),
    )


class TestReadPageRefusals:
    def _code(self, repo=None, peers=None, **query):
        with pytest.raises(MemberEnrollError) as excinfo:
            _page(repo, peers, **query)
        return excinfo.value.code

    def test_unknown_session(self):
        assert (
            self._code(FakeSeats(), session_id=1)
            == MemberEnrollErrorCode.SESSION_NOT_FOUND
        )

    def test_a_scheduled_session_hidden_from_the_public(self):
        repo = FakeSeats(session=_session(is_publicly_scheduled=False))

        assert self._code(repo) == MemberEnrollErrorCode.SESSION_NOT_FOUND

    def test_an_unscheduled_session_the_viewer_holds_nothing_on(self):
        repo = FakeSeats(session=_session(agenda_item=None))

        assert self._code(repo) == MemberEnrollErrorCode.NO_ENROLLMENT_CONFIG

    def test_an_unscheduled_session_still_shows_the_viewers_own_row(self):
        repo = FakeSeats(
            session=_session(agenda_item=None), statuses={_VIEWER.pk: Status.WAITING}
        )

        page, _, _ = _page(repo)

        assert page.user_data[0].user_waiting

    def test_an_event_ban(self):
        assert self._code(peers=_peers(banned=True)) == MemberEnrollErrorCode.BANNED

    def test_a_party_that_is_not_the_viewers(self):
        peers = _peers(parties=EnrollmentPartiesDTO(choices=[], requested_invalid=True))

        assert self._code(peers=peers) == MemberEnrollErrorCode.INVALID_PARTY


class TestReadPage:
    def test_viewer_alone_on_an_open_session(self):
        page, repo, peers = _page()

        assert [member.user for member in page.household] == [_VIEWER]
        assert page.user_data == (SessionUserParticipationData(user=_VIEWER),)
        assert page.fields[0].choices == {
            EnrollmentChoice.ENROLL,
            EnrollmentChoice.WAITLIST,
        }
        assert page.guest_count is None
        assert page.slot_allowance is None
        assert page.enroll_refusal is None
        assert page.access_problem is None
        assert page.party_id is None
        assert repo.log == [("read_session", "konwent", 1)]
        peers.event_bans.is_banned.assert_called_once_with(event_id=5, user_id=1)

    def test_companions_then_members_of_the_viewers_own_party(self):
        repo = FakeSeats(
            statuses={_MEMBER.pk: Status.OFFERED}, overlapping={_COMPANION.pk}
        )
        peers = _peers(parties=_led_party(consent=PartyConsentMode.ACCEPT_INVITES))

        page, _, _ = _page(repo, peers)

        assert page.household == (
            RosterMember(user=_VIEWER),
            RosterMember(user=_COMPANION),
            RosterMember(user=_MEMBER, needs_accept=True),
        )
        assert page.user_data[1:] == (
            SessionUserParticipationData(user=_COMPANION, has_time_conflict=True),
            SessionUserParticipationData(
                user=_MEMBER,
                seat_held=True,
                membership=PartyMemberFlags(is_member=True, needs_accept=True),
            ),
        )
        assert page.party_id == _PARTY_ID
        peers.enrollment.read_users.assert_called_once_with([_MEMBER.pk])
        # Only a restricted event asks a member for their own passes.
        peers.enrollment.has_slot_access.assert_not_called()

    def test_an_offer_to_someone_who_need_not_accept_is_a_pending_offer(self):
        repo = FakeSeats(statuses={_VIEWER.pk: Status.OFFERED})

        page, _, _ = _page(repo)

        assert page.user_data[0].offer_pending
        assert not page.user_data[0].seat_held

    @pytest.mark.parametrize(
        "member",
        (
            {"is_login_less": True},
            {"status": PartyMembershipStatus.INVITED},
            {"is_leader": True},
        ),
    )
    def test_party_people_nobody_acts_for(self, member):
        page, _, peers = _page(peers=_peers(parties=_led_party(**member)))

        assert [m.user for m in page.household] == [_VIEWER, _COMPANION]
        peers.enrollment.read_users.assert_not_called()

    def test_a_party_someone_else_leads_brings_no_members(self):
        parties = _led_party()
        parties = parties.model_copy(
            update={
                "selected": parties.selected.model_copy(update={"is_own_led": False}),
                "companions": [],
            }
        )

        page, _, _ = _page(peers=_peers(parties=parties))

        assert [m.user for m in page.household] == [_VIEWER]

    def test_a_member_whose_account_is_gone_is_left_out(self):
        page, _, _ = _page(peers=_peers(parties=_led_party(), users=[]))

        assert [m.user for m in page.household] == [_VIEWER, _COMPANION]

    def test_a_restricted_event_asks_each_member_for_passes(self):
        repo = FakeSeats(
            session=_session(windows=[_window(restrict_to_configured_users=True)])
        )
        peers = _peers(parties=_led_party(), member_access=False)

        page, _, _ = _page(repo, peers)

        assert page.household[-1] == RosterMember(user=_MEMBER, can_enroll=False)
        assert page.user_data[-1].membership.blocked
        assert page.slot_allowance == VirtualEnrollmentConfig(user_slots=5)
        peers.enrollment.has_slot_access.assert_called_once_with(
            event=repo.session.event, user_email=_MEMBER.email
        )

    def test_anonymous_seats_open_the_guests_stepper(self):
        guests = 2
        repo = FakeSeats(
            session=_session(windows=[_window(allow_anonymous_enrollment=True)]),
            guests=guests,
        )

        page, _, _ = _page(repo)

        assert page.guest_count == guests

    def test_a_full_waiting_list_cap_offers_no_place_on_it(self):
        page, _, _ = _page(FakeSeats(waiting={_VIEWER.pk: 2}))

        assert page.fields[0].choices == {EnrollmentChoice.ENROLL}

    @pytest.mark.parametrize(
        ("windows", "config", "refusal", "problem"),
        (
            ([], None, EnrollRefusal.NOT_AVAILABLE, None),
            (
                [_window(restrict_to_configured_users=True)],
                None,
                EnrollRefusal.ACCESS_REQUIRED,
                AccessProblem.ACCESS,
            ),
            (
                [_window(restrict_to_configured_users=True)],
                VirtualEnrollmentConfig(),
                EnrollRefusal.ACCESS_REQUIRED,
                None,
            ),
        ),
    )
    def test_why_enroll_is_refused(self, windows, config, refusal, problem):
        repo = FakeSeats(session=_session(windows=windows))

        page, _, _ = _page(repo, _peers(config=config))

        assert (page.enroll_refusal, page.access_problem) == (refusal, problem)

    def test_a_restricted_viewer_without_an_address(self):
        repo = FakeSeats(
            session=_session(windows=[_window(restrict_to_configured_users=True)])
        )
        peers = _peers(config=None)
        peers.enrollment.read_viewer.return_value = _VIEWER.model_copy(
            update={"email": ""}
        )

        page, _, _ = _page(repo, peers)

        assert page.enroll_refusal == EnrollRefusal.EMAIL_REQUIRED
        assert page.access_problem == AccessProblem.EMAIL
        assert not page.actor_configured


class TestAllowanceRefusal:
    def _restricted(self, **cfg):
        return FakeSeats(
            session=_session(windows=[_window(restrict_to_configured_users=True)]),
            **cfg,
        )

    def test_an_unrestricted_window_spends_no_passes(self):
        page, repo, peers = _page()

        assert (
            _service(repo, peers).allowance_refusal(
                page=page, choices={_VIEWER.pk: "enroll"}
            )
            is None
        )
        peers.enrollment.can_enroll_users.assert_not_called()

    def test_ticking_someone_already_in_spends_nothing(self):
        repo = self._restricted(statuses={_VIEWER.pk: Status.CONFIRMED})
        page, _, peers = _page(repo)

        refusal = _service(repo, peers).allowance_refusal(
            page=page, choices={_VIEWER.pk: INCLUDE_VALUE}
        )

        assert refusal is None
        peers.enrollment.can_enroll_users.assert_not_called()

    def test_passes_that_cover_the_newcomers(self):
        repo = self._restricted()
        peers = _peers(parties=_led_party())
        page, _, _ = _page(repo, peers)

        refusal = _service(repo, peers).allowance_refusal(
            page=page,
            choices={
                _VIEWER.pk: INCLUDE_VALUE,
                _COMPANION.pk: "",
                _MEMBER.pk: "enroll",
            },
        )

        assert refusal is None
        # A member's seat spends the member's passes, not the viewer's.
        peers.enrollment.can_enroll_users.assert_called_once_with(
            users=[_VIEWER, _COMPANION],
            event=repo.session.event,
            virtual_config=VirtualEnrollmentConfig(user_slots=5),
            users_to_enroll=[_VIEWER],
        )

    def test_spent_passes_name_the_first_newcomer(self):
        repo = self._restricted()
        peers = _peers(parties=_led_party(), passes=lambda **_: False)
        page, _, _ = _page(repo, peers)

        refusal = _service(repo, peers).allowance_refusal(
            page=page, choices={_VIEWER.pk: "", _COMPANION.pk: "enroll"}
        )

        assert refusal == AllowanceRefusal(
            user_id=_COMPANION.pk, name="Kid", used=2, allowed=5, available=0
        )


class TestSubmitRefusals:
    def test_a_seat_with_no_window_to_take_it_from(self):
        repo = FakeSeats(session=_session(windows=[]))

        with pytest.raises(MemberEnrollError) as excinfo:
            _submit(repo, _peers(), {_VIEWER.pk: "waitlist"})

        assert excinfo.value.code == MemberEnrollErrorCode.NO_ELIGIBLE_WINDOW
        assert ("lock_session", _SESSION_ID) not in repo.log

    def test_an_empty_submit_with_no_window_is_still_a_missing_window(self):
        with pytest.raises(MemberEnrollError):
            _submit(FakeSeats(session=_session(windows=[])), _peers(), {})

    def test_cancels_need_no_window(self):
        repo = FakeSeats(
            session=_session(windows=[]), statuses={_VIEWER.pk: Status.CONFIRMED}
        )

        outcome = _submit(repo, _peers(), {_VIEWER.pk: "cancel"})

        assert outcome == MemberEnrollOutcome(cancelled=["Vera"])

    @pytest.mark.parametrize(
        ("guests", "desired", "quiet"),
        ((None, False, False), (None, True, True), (1, False, True)),
    )
    def test_nothing_to_change(self, guests, desired, quiet):
        repo = FakeSeats(
            session=_session(windows=[_window(allow_anonymous_enrollment=True)]),
            guests=1,
        )

        with pytest.raises(NothingToChangeError) as excinfo:
            _submit(repo, _peers(), {_VIEWER.pk: ""}, guests=guests, desired=desired)

        assert excinfo.value.quiet is quiet
        assert ("lock_session", _SESSION_ID) not in repo.log

    @pytest.mark.parametrize(
        ("choice", "desired"), (("include", True), ("enroll", False))
    )
    def test_a_seat_the_first_click_took_is_no_change_not_a_shortage(
        self, choice, desired
    ):
        # The page was read before an earlier submit seated the viewer and
        # filled the session; under the lock the ask is already true.
        repo = FakeSeats(session=_session(limit=1))
        repo.on_lock = lambda seats: seats.statuses.update(
            {_VIEWER.pk: Status.CONFIRMED}
        )

        with pytest.raises(NothingToChangeError) as excinfo:
            _submit(repo, _peers(), {_VIEWER.pk: choice}, desired=desired)

        assert excinfo.value.quiet
        assert [entry for entry in repo.log if entry[0] == "seat"] == []

    def test_more_account_holders_than_seats(self):
        peers = _peers(parties=_led_party())
        repo = FakeSeats(session=_session(limit=1))

        with pytest.raises(SeatsShortError) as excinfo:
            _submit(repo, peers, {_VIEWER.pk: "enroll", _COMPANION.pk: "enroll"})

        assert (excinfo.value.requested, excinfo.value.available) == (2, 1)
        assert not excinfo.value.blame_guests

    def test_guests_beyond_the_seats(self):
        repo = FakeSeats(
            session=_session(
                limit=2, windows=[_window(allow_anonymous_enrollment=True)]
            )
        )

        with pytest.raises(SeatsShortError) as excinfo:
            _submit(repo, _peers(), {_VIEWER.pk: "enroll"}, guests=2)

        assert (excinfo.value.requested, excinfo.value.available) == (3, 2)
        assert excinfo.value.blame_guests

    def test_guests_with_no_window_left_get_only_the_seats_this_batch_frees(self):
        # The windows closed between the page and the lock: account holders
        # cancel, and guests may take back exactly what they freed.
        repo = FakeSeats(
            session=_session(windows=[_window(allow_anonymous_enrollment=True)]),
            statuses={_VIEWER.pk: Status.CONFIRMED},
            seating=SessionSeatingDTO(
                title="Smoki",
                participants_limit=4,
                enrolled_count=1,
                eligible_windows=[],
            ),
        )

        with pytest.raises(SeatsShortError) as excinfo:
            _submit(repo, _peers(), {_VIEWER.pk: "cancel"}, guests=2)

        assert (excinfo.value.requested, excinfo.value.available) == (2, 1)
        assert excinfo.value.blame_guests

    def test_passes_spent_while_the_form_was_checked(self):
        answers = iter([True, False])
        repo = FakeSeats(
            session=_session(windows=[_window(restrict_to_configured_users=True)])
        )
        peers = _peers(passes=lambda **_: next(answers))
        service = _service(repo, peers)
        page = service.read_page(_query())
        choices = {_VIEWER.pk: "enroll"}

        assert service.allowance_refusal(page=page, choices=choices) is None
        with pytest.raises(AllowanceSpentError) as excinfo:
            service.submit(
                page=page,
                submission=MemberEnrollSubmission(
                    choices=choices, guests=None, desired=False
                ),
            )

        assert excinfo.value.refusal.user_id == _VIEWER.pk
        assert ("seat", _VIEWER.pk, Status.CONFIRMED, None) not in repo.log


class TestSubmitExplicit:
    def test_seats_the_viewer_under_the_lock_order(self):
        repo = FakeSeats()
        peers = _peers()

        outcome = _submit(repo, peers, {_VIEWER.pk: "enroll"})

        assert outcome == MemberEnrollOutcome(enrolled=["Vera"])
        assert repo.log[1:] == [
            ("lock_session", _SESSION_ID),
            ("lock_people", [1, 1], None),
            ("seat", 1, Status.CONFIRMED, None),
        ]
        peers.waitlist_promotion.fill_freed_seats.assert_not_called()
        peers.shadowban.notify_signups.assert_called_once_with(
            session_id=_SESSION_ID, signed_up=[(1, "Vera")]
        )

    def test_a_cancel_frees_the_seat_for_a_companion_and_refills_after(self):
        peers = _peers(parties=_led_party())
        repo = FakeSeats(
            session=_session(limit=1), statuses={_VIEWER.pk: Status.CONFIRMED}
        )

        outcome = _submit(repo, peers, {_COMPANION.pk: "enroll", _VIEWER.pk: "cancel"})

        assert outcome == MemberEnrollOutcome(enrolled=["Kid"], cancelled=["Vera"])
        assert ("lock_people", [1, 1, 2], _SESSION_ID) in repo.log
        assert repo.log.index(("release", 1)) < repo.log.index(
            ("seat", 2, Status.CONFIRMED, _PARTY_ID)
        )
        peers.waitlist_promotion.fill_freed_seats.assert_called_once_with(
            session_id=_SESSION_ID
        )

    def test_a_waiting_place_given_up_refills_nothing(self):
        repo = FakeSeats(statuses={_VIEWER.pk: Status.WAITING})
        peers = _peers()

        _submit(repo, peers, {_VIEWER.pk: "cancel"})

        peers.waitlist_promotion.fill_freed_seats.assert_not_called()

    def test_a_cancel_whose_row_is_already_gone_is_skipped(self):
        repo = FakeSeats(statuses={_VIEWER.pk: Status.CONFIRMED})
        repo.on_lock = lambda seats: seats.statuses.clear()

        outcome = _submit(repo, _peers(), {_VIEWER.pk: "cancel"})

        assert outcome == MemberEnrollOutcome(
            skipped=[SkippedPerson("Vera", SkipReason.NO_ENROLLMENT_TO_CANCEL)]
        )

    def test_moving_to_the_waiting_list_rewrites_the_row(self):
        repo = FakeSeats(statuses={_VIEWER.pk: Status.CONFIRMED})
        peers = _peers()

        outcome = _submit(repo, peers, {_VIEWER.pk: "waitlist"})

        assert outcome == MemberEnrollOutcome(waitlisted=["Vera"])
        # Not a sign-up: the presenter was told when the row was new.
        peers.shadowban.notify_signups.assert_called_once_with(
            session_id=_SESSION_ID, signed_up=[]
        )

    def test_inactive_people_and_include_values_post_nothing(self):
        peers = _peers(parties=_led_party())
        peers.parties.enrollment_selection.return_value = _led_party().model_copy(
            update={"companions": [_COMPANION.model_copy(update={"is_active": False})]}
        )

        with pytest.raises(NothingToChangeError):
            _submit(
                FakeSeats(), peers, {_VIEWER.pk: INCLUDE_VALUE, _COMPANION.pk: "enroll"}
            )

    def test_skips_say_why(self):
        repo = FakeSeats(conflicted={_COMPANION.pk})
        peers = _peers(
            parties=_led_party(consent=PartyConsentMode.ACCEPT_INVITES),
            shadowbanned={_VIEWER.pk},
        )
        repo.on_lock = lambda seats: seats.statuses.update({_MEMBER.pk: Status.WAITING})

        outcome = _submit(
            repo,
            peers,
            {_VIEWER.pk: "enroll", _COMPANION.pk: "enroll", _MEMBER.pk: "enroll"},
        )

        assert outcome == MemberEnrollOutcome(
            skipped=[
                SkippedPerson("Vera", SkipReason.NOT_AVAILABLE),
                SkippedPerson("Kid", SkipReason.TIME_CONFLICT),
                SkippedPerson("Mira", SkipReason.MANAGES_OWN),
            ]
        )
        peers.shadowban.banned_user_ids.assert_called_once_with(_PRESENTER_ID)

    def test_the_presenter_is_never_seated_at_their_own_table(self):
        repo = FakeSeats(session=_session(presenter_id=_VIEWER.pk))

        outcome = _submit(repo, _peers(), {_VIEWER.pk: "enroll"})

        assert outcome == MemberEnrollOutcome(
            skipped=[SkippedPerson("Vera", SkipReason.SESSION_HOST)]
        )

    def test_a_session_nobody_presents_bans_nobody(self):
        repo = FakeSeats(session=_session(presenter_id=None))
        peers = _peers()

        _submit(repo, peers, {_VIEWER.pk: "enroll"})

        peers.shadowban.banned_user_ids.assert_not_called()

    def test_a_member_who_must_accept_gets_a_held_seat(self):
        repo = FakeSeats()
        peers = _peers(parties=_led_party(consent=PartyConsentMode.ACCEPT_INVITES))

        outcome = _submit(repo, peers, {_MEMBER.pk: "enroll"})

        assert outcome == MemberEnrollOutcome(held=["Mira"])
        peers.waitlist_promotion.hold_seat.assert_called_once_with(
            hold=SeatHoldRequest(
                session_id=_SESSION_ID,
                session_title="Smoki",
                user_id=_MEMBER.pk,
                party_id=_PARTY_ID,
                actor_name="Vera",
            )
        )
        peers.parties.announce_member_enrolled.assert_not_called()

    def test_a_trusting_member_seated_directly_is_told(self):
        peers = _peers(parties=_led_party())

        outcome = _submit(FakeSeats(), peers, {_MEMBER.pk: "enroll"})

        assert outcome == MemberEnrollOutcome(enrolled=["Mira"])
        peers.parties.announce_member_enrolled.assert_called_once_with(
            PartyEnrolledNotification(
                recipient_user_id=_MEMBER.pk,
                actor_name="Vera",
                session_id=_SESSION_ID,
                session_title="Smoki",
                event_slug="konwent",
            )
        )


class TestSubmitDesired:
    def test_fills_seats_in_household_order_then_waits(self):
        peers = _peers(parties=_led_party())
        repo = FakeSeats(session=_session(limit=1))

        outcome = _submit(
            repo,
            peers,
            {_VIEWER.pk: INCLUDE_VALUE, _COMPANION.pk: INCLUDE_VALUE, _MEMBER.pk: ""},
            desired=True,
        )

        assert outcome == MemberEnrollOutcome(enrolled=["Vera"], waitlisted=["Kid"])

    def test_unticking_someone_in_cancels_and_their_seat_goes_round(self):
        peers = _peers(parties=_led_party())
        repo = FakeSeats(
            session=_session(limit=1), statuses={_VIEWER.pk: Status.CONFIRMED}
        )

        outcome = _submit(
            repo, peers, {_VIEWER.pk: "", _COMPANION.pk: INCLUDE_VALUE}, desired=True
        )

        assert outcome == MemberEnrollOutcome(enrolled=["Kid"], cancelled=["Vera"])

    def test_someone_in_or_clashing_is_left_where_they_are(self):
        repo = FakeSeats(
            statuses={_VIEWER.pk: Status.WAITING}, conflicted={_COMPANION.pk}
        )
        peers = _peers(parties=_led_party())

        with pytest.raises(NothingToChangeError) as excinfo:
            _submit(
                repo,
                peers,
                {_VIEWER.pk: INCLUDE_VALUE, _COMPANION.pk: INCLUDE_VALUE},
                desired=True,
            )

        assert excinfo.value.quiet

    def test_an_unticked_seat_the_person_owns_stays(self):
        # A trusting member's own row offers no cancel.
        repo = FakeSeats(statuses={_MEMBER.pk: Status.CONFIRMED})
        peers = _peers(parties=_led_party())

        with pytest.raises(NothingToChangeError):
            _submit(repo, peers, {_VIEWER.pk: "", _MEMBER.pk: ""}, desired=True)

    def test_a_held_seat_needs_a_free_seat(self):
        peers = _peers(parties=_led_party(consent=PartyConsentMode.ACCEPT_INVITES))
        repo = FakeSeats(session=_session(limit=1))

        outcome = _submit(
            repo,
            peers,
            {_VIEWER.pk: INCLUDE_VALUE, _MEMBER.pk: INCLUDE_VALUE},
            desired=True,
        )

        assert outcome == MemberEnrollOutcome(enrolled=["Vera"])

    def test_a_held_seat_with_room(self):
        peers = _peers(parties=_led_party(consent=PartyConsentMode.ACCEPT_INVITES))

        outcome = _submit(FakeSeats(), peers, {_MEMBER.pk: INCLUDE_VALUE}, desired=True)

        assert outcome == MemberEnrollOutcome(held=["Mira"])

    def test_someone_who_can_neither_sit_nor_wait_is_left_out(self):
        # Full, and the waiting-list cap reached.
        repo = FakeSeats(session=_session(limit=0), waiting={_VIEWER.pk: 2})

        with pytest.raises(NothingToChangeError):
            _submit(repo, _peers(), {_VIEWER.pk: INCLUDE_VALUE}, desired=True)

    def test_an_inactive_companion_ticked_in_is_left_out(self):
        peers = _peers(parties=_led_party())
        peers.parties.enrollment_selection.return_value = _led_party().model_copy(
            update={"companions": [_COMPANION.model_copy(update={"is_active": False})]}
        )

        outcome = _submit(
            FakeSeats(),
            peers,
            {_VIEWER.pk: INCLUDE_VALUE, _COMPANION.pk: INCLUDE_VALUE},
            desired=True,
        )

        assert outcome == MemberEnrollOutcome(enrolled=["Vera"])

    def test_a_ticked_box_with_no_move_behind_it_asks_for_nothing(self):
        # No window, so no move: the submit asks for no seat and reports the
        # missing window, as an empty one does.
        repo = FakeSeats(session=_session(windows=[]))

        with pytest.raises(MemberEnrollError):
            _submit(repo, _peers(), {_VIEWER.pk: INCLUDE_VALUE}, desired=True)

    def test_passes_still_cover_the_newcomer_under_the_lock(self):
        repo = FakeSeats(
            session=_session(windows=[_window(restrict_to_configured_users=True)])
        )
        peers = _peers()

        outcome = _submit(repo, peers, {_VIEWER.pk: INCLUDE_VALUE}, desired=True)

        assert outcome == MemberEnrollOutcome(enrolled=["Vera"])
        assert peers.enrollment.can_enroll_users.call_count == 1

    def test_a_full_session_with_no_waiting_list_brings_nobody_in(self):
        repo = FakeSeats(session=_session(limit=1, enrolled=1), waiting={_VIEWER.pk: 2})

        with pytest.raises(NothingToChangeError):
            _submit(repo, _peers(), {_VIEWER.pk: INCLUDE_VALUE}, desired=True)


class TestGuests:
    def _repo(self, **cfg):
        return FakeSeats(
            session=_session(windows=[_window(allow_anonymous_enrollment=True)]), **cfg
        )

    def test_more_guests_are_created_for_the_viewer(self):
        repo = self._repo(guests=1)
        peers = _peers()

        outcome = _submit(repo, peers, {_VIEWER.pk: ""}, guests=3)

        peers.enrollment.create_guests.assert_called_once_with(
            session_id=_SESSION_ID,
            count=2,
            party_id=None,
            enrolled_by_id=_VIEWER.pk,
            viewer_name="Vera",
        )
        assert outcome == MemberEnrollOutcome(guest_total=1)
        peers.waitlist_promotion.fill_freed_seats.assert_not_called()

    def test_fewer_guests_free_seats_and_refill(self):
        repo = self._repo(guests=3)
        peers = _peers()

        outcome = _submit(repo, peers, {_VIEWER.pk: ""}, guests=1)

        assert outcome == MemberEnrollOutcome(guest_total=1)
        assert ("lock_people", [1], _SESSION_ID) in repo.log
        assert ("release_guests", _VIEWER.pk, 2) in repo.log
        peers.waitlist_promotion.fill_freed_seats.assert_called_once_with(
            session_id=_SESSION_ID
        )

    def test_a_replayed_target_changes_nothing_under_the_lock(self):
        # The page saw one guest; another tab already raised it to two.
        repo = self._repo(guests=1)
        repo.on_lock = lambda seats: setattr(seats, "guests", 2)
        peers = _peers()

        outcome = _submit(repo, peers, {_VIEWER.pk: ""}, guests=2)

        assert outcome == MemberEnrollOutcome()
        peers.enrollment.create_guests.assert_not_called()


class TestReadFooter:
    def test_the_viewers_row_and_fresh_seats(self):
        repo = FakeSeats(statuses={_VIEWER.pk: Status.WAITING, 8: Status.CONFIRMED})

        footer = _service(repo, _peers()).read_footer(
            session_id=_SESSION_ID, viewer_id=_VIEWER.pk
        )

        assert footer == EnrollFooterDTO(
            seats=_seats(enrolled=2), viewer_status=Status.WAITING
        )

    def test_the_holds_and_refill_ride_the_batch(self):
        repo = FakeSeats()
        peers = _peers(parties=_led_party(consent=PartyConsentMode.ACCEPT_INVITES))

        _submit(repo, peers, {_MEMBER.pk: "enroll", _VIEWER.pk: "enroll"})

        assert peers.waitlist_promotion.mock_calls[0] == call.hold_seat(
            hold=SeatHoldRequest(
                session_id=_SESSION_ID,
                session_title="Smoki",
                user_id=_MEMBER.pk,
                party_id=_PARTY_ID,
                actor_name="Vera",
            )
        )
