from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.inits.services import Services
from ludamus.links.db.django.enrollment import ParticipationPromotionRepository
from ludamus.links.db.django.models import (
    Notification,
    Party,
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.links.db.django.party import PartyRepository
from ludamus.links.db.django.transaction import DjangoTransaction
from ludamus.pacts.enrollment_member import SessionUserParticipationData
from ludamus.pacts.notifications import NotificationKind
from ludamus.pacts.party import (
    EnrollmentPartyChoiceDTO,
    PartyConsentMode,
    PartyMembershipStatus,
)
from ludamus.pacts.user import CompanionDTO
from tests.integration.conftest import UserFactory, sponsor_user
from tests.integration.utils import assert_response
from tests.integration.web.event.helpers import (
    enroll_page_context,
    participation_row,
    party_context,
    party_member,
)


def _url(agenda_item):
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={
            "event_slug": agenda_item.session.event.slug,
            "session_id": agenda_item.session.pk,
        },
    )


def _reassign_presenter(agenda_item):
    # The session fixture is presented by active_user, and a host can't enroll
    # in their own session — hand the session to someone else.
    agenda_item.session.presenter = UserFactory(username="host", name="Host")
    agenda_item.session.save()


def _join(party, user, *, status=PartyMembershipStatus.ACTIVE):
    return PartyMembership.objects.create(
        party=party,
        member=user,
        consent_mode=PartyConsentMode.ACCEPT_INVITES,
        status=status,
    )


def _commit_after_party_read(monkeypatch, competing):
    # A competing request commits `competing` after this one read the viewer's
    # parties and before it writes anything. Fires once.
    read = PartyRepository.owned_companions
    pending = [competing]

    def read_before_competitor(**kwargs):
        companions = read(**kwargs)
        while pending:
            pending.pop()()
        return companions

    monkeypatch.setattr(
        PartyRepository, "owned_companions", staticmethod(read_before_competitor)
    )


class TestPartyThatDoesNotEnroll:
    @pytest.mark.usefixtures("enrollment_config")
    def test_post_through_an_own_led_one_enrolls_and_turns_enrolling_on(
        self, authenticated_client, active_user, agenda_item
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(party.pk), f"user_{active_user.pk}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, f"Enrolled: {active_user.name}")],
        )
        party.refresh_from_db()
        assert party.enrolls_together is True
        assert SessionParticipation.objects.get().party_id == party.pk

    def test_get_does_not_turn_enrolling_on(
        self, authenticated_client, active_user, agenda_item
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)

        response = authenticated_client.get(_url(agenda_item), {"party": party.pk})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="event/enroll_select.html",
            context_data=enroll_page_context(
                viewer=active_user,
                agenda_item=agenda_item,
                **party_context(
                    party,
                    leader_name=active_user.name,
                    members=[
                        party_member(
                            active_user,
                            is_leader=True,
                            consent_mode=PartyConsentMode.ACCEPT_INVITES,
                        )
                    ],
                    enrolls_together=False,
                ),
            ),
        )
        party.refresh_from_db()
        assert party.enrolls_together is False

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_through_one_someone_else_leads_is_refused(
        self, authenticated_client, active_user, agenda_item
    ):
        leader = UserFactory(username="leader", name="Lena Leader")
        party = Party.objects.create(
            leader=leader, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(party.pk), f"user_{active_user.pk}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[
                (messages.ERROR, "Choose one of your parties or enroll by yourself.")
            ],
        )
        party.refresh_from_db()
        assert party.enrolls_together is False
        assert not SessionParticipation.objects.exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_only_cancelling_leaves_it_off(
        self, authenticated_client, active_user, agenda_item
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(party.pk), f"user_{active_user.pk}": "cancel"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, f"Cancelled: {active_user.name}")],
        )
        party.refresh_from_db()
        assert party.enrolls_together is False
        assert not SessionParticipation.objects.exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_skipping_everyone_leaves_it_off(
        self, authenticated_client, active_user, agenda_item
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)
        agenda_item.session.presenter.shadowbanned.add(active_user)

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(party.pk), f"user_{active_user.pk}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[
                (
                    messages.WARNING,
                    (
                        "Skipped (already enrolled or conflicts): "
                        f"{active_user.name} (not available)"
                    ),
                )
            ],
        )
        party.refresh_from_db()
        assert party.enrolls_together is False
        assert not SessionParticipation.objects.exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_cancelling_and_skipping_cancels_and_leaves_it_off(
        self, authenticated_client, active_user, companion, agenda_item
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)
        agenda_item.session.presenter.shadowbanned.add(companion)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(
            _url(agenda_item),
            data={
                "party": str(party.pk),
                f"user_{active_user.pk}": "cancel",
                f"user_{companion.pk}": "enroll",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[
                (messages.SUCCESS, f"Cancelled: {active_user.name}"),
                (
                    messages.WARNING,
                    (
                        "Skipped (already enrolled or conflicts): "
                        f"{companion.name} (not available)"
                    ),
                ),
            ],
        )
        party.refresh_from_db()
        assert party.enrolls_together is False
        assert not SessionParticipation.objects.exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_changing_nothing_leaves_it_off(
        self, authenticated_client, active_user, agenda_item
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={"party": str(party.pk), "enroll_mode": "desired"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[(messages.WARNING, "No changes.")],
        )
        party.refresh_from_db()
        assert party.enrolls_together is False

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_turns_it_back_on_when_switched_off_mid_request(
        self, authenticated_client, active_user, agenda_item, monkeypatch
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=True
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)
        _commit_after_party_read(
            monkeypatch,
            lambda: Party.objects.filter(pk=party.pk).update(enrolls_together=False),
        )

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(party.pk), f"user_{active_user.pk}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, f"Enrolled: {active_user.name}")],
        )
        party.refresh_from_db()
        assert party.enrolls_together is True
        assert SessionParticipation.objects.get().party_id == party.pk

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_through_one_deleted_mid_request_is_refused(
        self, authenticated_client, active_user, agenda_item, monkeypatch
    ):
        party = Party.objects.create(
            leader=active_user, name="Ekipa", enrolls_together=False
        )
        _join(party, active_user)
        _reassign_presenter(agenda_item)
        _commit_after_party_read(
            monkeypatch, lambda: Party.objects.filter(pk=party.pk).delete()
        )

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(party.pk), f"user_{active_user.pk}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[
                (messages.ERROR, "Choose one of your parties or enroll by yourself.")
            ],
        )
        assert not SessionParticipation.objects.exists()


class TestHostingMember:
    @pytest.mark.usefixtures("enrollment_config")
    def test_leader_cannot_release_a_hosting_members_own_row(
        self, authenticated_client, active_user, agenda_item
    ):
        party = sponsor_user(leader=active_user, member=active_user)
        gm = UserFactory(username="gm-member", email="gm-member@example.com")
        PartyMembership.objects.create(
            party=party,
            member=gm,
            consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
            status=PartyMembershipStatus.ACTIVE,
        )
        session = agenda_item.session
        session.presenter = gm
        session.save(update_fields=["presenter_id"])
        row = SessionParticipation.objects.create(
            session=session, user=gm, status=SessionParticipationStatus.WAITING
        )

        response = authenticated_client.post(
            _url(agenda_item), data={"party": str(party.pk), "enroll_mode": "desired"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[(messages.WARNING, "No changes.")],
        )
        assert SessionParticipation.objects.filter(pk=row.pk).exists()


class TestEnrollRecordsParty:
    @pytest.mark.usefixtures("enrollment_config")
    def test_post_records_default_party_on_all_seats(
        self, authenticated_client, active_user, party_companion, agenda_item
    ):
        party = sponsor_user(leader=active_user, member=active_user)
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item),
            data={
                "party": str(party.pk),
                f"user_{active_user.pk}": "enroll",
                f"user_{party_companion.pk}": "enroll",
            },
        )

        expected = f"Enrolled: {active_user.name}, {party_companion.name}"
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, expected)],
        )
        participations = SessionParticipation.objects.filter(
            session=agenda_item.session
        )
        assert {(p.user_id, p.party_id) for p in participations} == {
            (active_user.pk, party.pk),
            (party_companion.pk, party.pk),
        }

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_solo_user_records_no_party(
        self, authenticated_client, active_user, agenda_item
    ):
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{active_user.pk}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        participation = SessionParticipation.objects.get(user=active_user)
        assert participation.party_id is None

    @pytest.mark.usefixtures("enrollment_config", "party_companion")
    def test_default_party_is_recorded_without_explicit_field(
        self, authenticated_client, active_user, agenda_item
    ):
        # No explicit party parameter defaults to the viewer's own led party,
        # so the group promotes together — visible and escapable via the
        # always-shown selector.
        party = sponsor_user(leader=active_user, member=active_user)
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{active_user.pk}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        participation = SessionParticipation.objects.get(user=active_user)
        assert participation.party_id == party.pk

    @pytest.mark.usefixtures("enrollment_config", "companion")
    def test_post_just_myself_records_no_party(
        self, authenticated_client, active_user, agenda_item
    ):
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": "none", f"user_{active_user.pk}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        participation = SessionParticipation.objects.get(user=active_user)
        assert participation.party_id is None

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_enrolls_companion_belonging_to_no_party(
        self, authenticated_client, active_user, companion, agenda_item
    ):
        # The profile's "add companion" flow joins no party, so a roster gated
        # on party membership left such a companion unenrollable.
        party = sponsor_user(leader=active_user, member=active_user)
        PartyMembership.objects.filter(member=companion).delete()
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{companion.pk}": "enroll"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, f"Enrolled: {companion.name}")],
        )
        participation = SessionParticipation.objects.get(user=companion)
        assert participation.party_id == party.pk

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_enrolls_companion_of_a_viewer_without_parties(
        self, authenticated_client, companion, agenda_item
    ):
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item), data={f"user_{companion.pk}": "enroll"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/event/{agenda_item.session.event.slug}/",
            messages=[(messages.SUCCESS, f"Enrolled: {companion.name}")],
        )
        participation = SessionParticipation.objects.get(user=companion)
        assert participation.party_id is None

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_alien_party_is_rejected(
        self, authenticated_client, active_user, agenda_item
    ):
        stranger = UserFactory(username="stranger", name="Sam Stranger")
        alien = Party.objects.create(leader=stranger, name="Obcy")
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(alien.pk), f"user_{active_user.pk}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[
                (messages.ERROR, "Choose one of your parties or enroll by yourself.")
            ],
        )
        assert not SessionParticipation.objects.filter(user=active_user).exists()


class TestPartySelector:
    # A single enrolling party is applied automatically, with no selector:
    # the checkboxes alone decide who enrolls. The selector shows once there
    # is another party to pick; tests/e2e covers its markup.
    def test_default_party_applies_without_selector(
        self, authenticated_client, active_user, party_companion, agenda_item
    ):
        sponsor_user(leader=active_user, member=active_user)

        response = authenticated_client.get(_url(agenda_item))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Enrolling as" not in content
        assert party_companion.name in content

    def test_no_party_note_without_any_party(self, authenticated_client, agenda_item):
        response = authenticated_client.get(_url(agenda_item))

        assert response.status_code == HTTPStatus.OK
        assert "Enrolling as" not in response.content.decode()

    def test_just_myself_keeps_own_companions(
        self, authenticated_client, active_user, companion, agenda_item
    ):
        sponsor_user(leader=active_user, member=active_user)
        # "Just myself" drops the party's members, not the viewer's own
        # companions — nobody else can seat those.
        response = authenticated_client.get(_url(agenda_item), {"party": "none"})

        content = response.content.decode()
        assert companion.name in content
        assert 'name="party" value="none"' in content

    def test_get_alien_party_is_rejected(self, authenticated_client, agenda_item):
        stranger = UserFactory(username="stranger", name="Sam Stranger")
        alien = Party.objects.create(leader=stranger, name="Obcy")

        response = authenticated_client.get(_url(agenda_item), {"party": alien.pk})

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=_url(agenda_item),
            messages=[
                (messages.ERROR, "Choose one of your parties or enroll by yourself.")
            ],
        )

    def test_manage_companions_footnote_is_always_there(
        self, authenticated_client, agenda_item
    ):
        response = authenticated_client.get(_url(agenda_item))

        assert "Manage companions in your profile settings" in response.content.decode()

    def test_own_led_party_wins_the_default_with_multiple_parties(
        self, authenticated_client, active_user, party_companion, agenda_item
    ):
        own = sponsor_user(leader=active_user, member=active_user)
        friend = UserFactory(username="friend", name="Frida Friend")
        crew = Party.objects.create(leader=friend, name="Ekipa")
        _join(crew, friend)
        _join(crew, active_user)

        response = authenticated_client.get(_url(agenda_item))

        pills = party_context(
            own,
            leader_name=active_user.name,
            members=[
                party_member(active_user, is_leader=True),
                party_member(party_companion, is_login_less=True),
            ],
        )
        crew_pill = EnrollmentPartyChoiceDTO(
            pk=crew.pk,
            name="Ekipa",
            leader_name="Frida Friend",
            is_own_led=False,
            enrolls_together=True,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="event/enroll_select.html",
            context_data=enroll_page_context(
                viewer=active_user,
                agenda_item=agenda_item,
                user_data=[
                    participation_row(active_user),
                    SessionUserParticipationData(
                        user=CompanionDTO.model_validate(party_companion),
                        user_enrolled=False,
                        user_waiting=False,
                        has_time_conflict=False,
                    ),
                ],
                companions=[CompanionDTO.model_validate(party_companion)],
                party_choices=[*pills["party_choices"], crew_pill],
                selected_party=pills["selected_party"],
                offers_party_choice=True,
            ),
        )

    def test_unnamed_foreign_party_is_offered_under_its_leader(
        self, authenticated_client, active_user, agenda_item
    ):
        friend = UserFactory(username="friend", name="Frida Friend")
        crew = Party.objects.create(leader=friend, name="")
        _join(crew, friend)
        _join(crew, active_user)

        response = authenticated_client.get(_url(agenda_item), {"party": "none"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="event/enroll_select.html",
            context_data=enroll_page_context(
                viewer=active_user,
                agenda_item=agenda_item,
                party_choices=[
                    EnrollmentPartyChoiceDTO(
                        pk=crew.pk,
                        name="",
                        leader_name="Frida Friend",
                        is_own_led=False,
                        enrolls_together=True,
                    )
                ],
                offers_party_choice=True,
            ),
        )

    def test_foreign_party_lists_only_self(
        self, authenticated_client, active_user, companion, agenda_item
    ):
        friend = UserFactory(username="friend", name="Frida Friend")
        crew = Party.objects.create(leader=friend, name="Ekipa")
        _join(crew, friend)
        _join(crew, active_user)

        response = authenticated_client.get(_url(agenda_item), {"party": crew.pk})

        content = response.content.decode()
        assert companion.name not in content
        assert f'name="party" value="{crew.pk}"' in content

    @pytest.mark.usefixtures("enrollment_config", "companion")
    def test_post_through_foreign_party_groups_by_it(
        self, authenticated_client, active_user, agenda_item
    ):
        friend = UserFactory(username="friend", name="Frida Friend")
        crew = Party.objects.create(leader=friend, name="Ekipa")
        _join(crew, friend)
        _join(crew, active_user)
        _reassign_presenter(agenda_item)

        response = authenticated_client.post(
            _url(agenda_item),
            data={"party": str(crew.pk), f"user_{active_user.pk}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        participation = SessionParticipation.objects.get(user=active_user)
        assert participation.party_id == crew.pk


class TestPartyWaitlistPromotion:
    @pytest.mark.usefixtures("enrollment_config")
    def test_lock_and_read_state_carries_party_id(self, active_user, agenda_item):
        party = Party.objects.create(leader=active_user, name="Ekipa")
        _join(party, active_user)
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=active_user,
            status=SessionParticipationStatus.WAITING,
            party=party,
        )

        with DjangoTransaction().atomic():
            state = ParticipationPromotionRepository().lock_and_read_state(
                agenda_item.session.pk
            )

        assert state is not None
        [waiting] = state.waiting
        assert waiting.party_id == party.pk

    @pytest.mark.usefixtures("enrollment_config")
    def test_party_of_two_real_users_promotes_and_notifies_both(self, agenda_item):
        # Fresh users: the session fixture's presenter is active_user, and a
        # presenter is never promoted into their own session.
        leader = UserFactory(
            username="lead", name="Lena Leader", email="lena@example.com"
        )
        friend = UserFactory(
            username="friend", name="Frida Friend", email="frida@example.com"
        )
        party = Party.objects.create(leader=leader, name="Ekipa")
        _join(party, leader)
        _join(party, friend)
        for user in (leader, friend):
            SessionParticipation.objects.create(
                session=agenda_item.session,
                user=user,
                status=SessionParticipationStatus.WAITING,
                party=party,
            )

        result = Services().waitlist_promotion.fill_freed_seats(
            session_id=agenda_item.session.pk
        )

        waiting_pks = set(
            SessionParticipation.objects.filter(
                session=agenda_item.session
            ).values_list("pk", flat=True)
        )
        assert set(result.promoted) == waiting_pks
        promoted_kind = NotificationKind.WAITLIST_PROMOTED
        recipients = set(
            Notification.objects.filter(kind=promoted_kind).values_list(
                "recipient_id", flat=True
            )
        )
        assert recipients == {leader.pk, friend.pk}
