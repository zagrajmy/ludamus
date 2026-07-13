from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Party,
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.crowd.test_profile_parties_page import (
    _member_dto,
    _party_dto,
)

TEMPLATE = "crowd/user/party_detail.html"


def _url(party):
    return reverse("web:crowd:party-detail", kwargs={"pk": party.pk})


def _context(party_dto, **overrides):
    context = {
        "party": party_dto,
        "rename_form": ANY if party_dto.is_leader else None,
        "invite_form": ANY if party_dto.is_leader else None,
        "history": [],
        "profile_active_tab": "parties",
    }
    context.update(overrides)
    return context


class TestPartyDetailPageView:
    def test_get_led_party_shows_members_and_forms(
        self, authenticated_client, active_user, connected_user
    ):
        party = Party.objects.get(leader=active_user)

        response = authenticated_client.get(_url(party))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [
                        _member_dto(active_user, party),
                        _member_dto(connected_user, party),
                    ],
                    is_default=True,
                )
            ),
            template_name=TEMPLATE,
            contains=[
                connected_user.get_full_name(),
                "Invite a member",
                "Delete party",
            ],
        )

    def test_get_membership_shows_leave_and_consent(
        self, authenticated_client, active_user
    ):
        friend = UserFactory(username="friend", name="Frida Friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        PartyMembership.objects.create(
            party=party,
            member=active_user,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.ACTIVE,
        )

        response = authenticated_client.get(_url(party))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [_member_dto(friend, party), _member_dto(active_user, party)],
                    is_default=False,
                )
            ),
            template_name=TEMPLATE,
            contains=["Leave party", "Allow direct enrollment"],
        )

    def test_get_foreign_party_is_not_found(self, authenticated_client):
        stranger = UserFactory(username="stranger")
        party = Party.objects.create(leader=stranger, name="Theirs")

        response = authenticated_client.get(_url(party))

        assert_response_404(response)

    def test_get_pending_invite_is_not_found(self, authenticated_client, active_user):
        friend = UserFactory(username="friend")
        party = Party.objects.create(leader=friend, name="Ekipa")
        PartyMembership.objects.create(party=party, member=friend)
        PartyMembership.objects.create(
            party=party,
            member=active_user,
            consent_mode=PartyConsentMode.ACCEPT_INVITES,
            status=PartyMembershipStatus.INVITED,
        )

        response = authenticated_client.get(_url(party))

        assert_response_404(response)

    def test_get_requires_login(self, client, active_user):
        party = Party.objects.create(leader=active_user, name="Ekipa")

        response = client.get(_url(party))

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={_url(party)}"
        )


class TestPartyDetailSessionHistory:
    def _enroll_party(self, party, session, *users):
        for user in users:
            SessionParticipation.objects.create(
                session=session,
                user=user,
                party=party,
                status=SessionParticipationStatus.CONFIRMED,
            )

    def test_history_groups_party_sessions_by_event(
        self, authenticated_client, active_user, connected_user, session, agenda_item
    ):
        party = Party.objects.get(leader=active_user)
        session.title = "Wspólna Wyprawa"
        session.save()
        self._enroll_party(party, session, active_user, connected_user)

        response = authenticated_client.get(_url(party))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [
                        _member_dto(active_user, party),
                        _member_dto(connected_user, party),
                    ],
                    is_default=True,
                ),
                history=[
                    {
                        "event_name": session.event.name,
                        "event_slug": session.event.slug,
                        "cards": ANY,
                    }
                ],
            ),
            template_name=TEMPLATE,
            contains=["Wspólna Wyprawa", session.event.name],
        )
        [group] = response.context["history"]
        [card] = group["cards"]
        assert card.session.pk == session.pk
        assert card.user_enrolled
        assert card.agenda_item.start_time == agenda_item.start_time
        assert not card.pretend_full

    def test_history_skips_solo_enrollments(
        self, authenticated_client, active_user, connected_user, session, agenda_item
    ):
        _ = agenda_item
        party = Party.objects.get(leader=active_user)
        SessionParticipation.objects.create(
            session=session,
            user=active_user,
            party=None,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.get(_url(party))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [
                        _member_dto(active_user, party),
                        _member_dto(connected_user, party),
                    ],
                    is_default=True,
                )
            ),
            template_name=TEMPLATE,
            contains="No sessions together yet",
        )

    def test_history_card_is_pretend_full_when_presenter_shadowbanned_viewer(
        self, authenticated_client, active_user, connected_user, session, agenda_item
    ):
        _ = agenda_item
        party = Party.objects.get(leader=active_user)
        self._enroll_party(party, session, active_user, connected_user)
        banner = UserFactory(username="gm", name="GM", email="gm@example.com")
        session.presenter = banner
        session.save()
        banner.shadowbanned.add(active_user)

        response = authenticated_client.get(_url(party))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [
                        _member_dto(active_user, party),
                        _member_dto(connected_user, party),
                    ],
                    is_default=True,
                ),
                history=[
                    {
                        "event_name": session.event.name,
                        "event_slug": session.event.slug,
                        "cards": ANY,
                    }
                ],
            ),
            template_name=TEMPLATE,
        )
        [group] = response.context["history"]
        [card] = group["cards"]
        assert card.pretend_full
        assert card.is_full
        assert all(p.user.pk < 0 for p in card.session_participations)
