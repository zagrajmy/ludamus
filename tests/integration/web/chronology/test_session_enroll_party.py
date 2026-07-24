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
from ludamus.links.db.django.transaction import DjangoTransaction
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import UserFactory, sponsor_user
from tests.integration.utils import assert_response


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
    # There is no party selector UI: the viewer's own led party (else their
    # first party) is applied automatically, and the checkboxes alone decide
    # who enrolls. The ?party= URL contract stays for the server.
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

    def test_just_myself_hides_companions_and_hint(
        self, authenticated_client, active_user, companion, agenda_item
    ):
        sponsor_user(leader=active_user, member=active_user)
        # Companions enroll through the party; enrolling as just myself shows
        # only the viewer's own row, without the add-companions hint or the
        # party grouping hint.
        response = authenticated_client.get(_url(agenda_item), {"party": "none"})

        content = response.content.decode()
        assert companion.name not in content
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
        sponsor_user(leader=active_user, member=active_user)
        friend = UserFactory(username="friend", name="Frida Friend")
        crew = Party.objects.create(leader=friend, name="Ekipa")
        _join(crew, friend)
        _join(crew, active_user)

        response = authenticated_client.get(_url(agenda_item))

        # Own led party selected by default: its companion is listed, and the
        # foreign party is not surfaced anywhere (no selector).
        content = response.content.decode()
        assert party_companion.name in content
        assert "Ekipa" not in content

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
