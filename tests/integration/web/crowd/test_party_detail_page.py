from http import HTTPStatus
from unittest.mock import ANY

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    EventBan,
    Party,
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
    sponsor_user,
)
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
        "companion_form": ANY if party_dto.is_leader else None,
        "invite_token": "",
        "history": [],
        "profile_active_tab": "parties",
    }
    context.update(overrides)
    return context


class TestPartyDetailPageView:
    def test_get_led_party_shows_members_and_forms(
        self, authenticated_client, active_user, companion
    ):
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=companion)

        response = authenticated_client.get(_url(party))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [_member_dto(active_user, party), _member_dto(companion, party)],
                    is_default=True,
                ),
                invite_token=party.invite_token,
            ),
            template_name=TEMPLATE,
            contains=[companion.get_full_name(), "Invite a member", "Delete party"],
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
        self, authenticated_client, active_user, companion, session, agenda_item
    ):
        active_user.use_gravatar = True
        active_user.save(update_fields=["use_gravatar"])
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=companion)
        session.title = "Wspólna Wyprawa"
        session.save()
        self._enroll_party(party, session, active_user, companion)

        response = authenticated_client.get(_url(party))
        history = response.context["history"]

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [_member_dto(active_user, party), _member_dto(companion, party)],
                    is_default=True,
                ),
                invite_token=party.invite_token,
                history=[
                    {
                        "event_name": session.event.name,
                        "event_slug": session.event.slug,
                        "cards": history[0]["cards"],
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
        assert card.session_participations[0].user.avatar_url == gravatar_url(
            active_user.email
        )
        assert card.agenda_item.start_time == agenda_item.start_time
        assert not card.pretend_full

    def test_history_query_count_is_constant_across_space_depth(
        self, authenticated_client, active_user, session, agenda_item
    ):
        party = sponsor_user(leader=active_user, member=active_user)
        self._enroll_party(party, session, active_user)
        root = SpaceFactory(event=session.event, name="Root")
        branch = SpaceFactory(event=session.event, name="Branch", parent=root)
        leaf = SpaceFactory(event=session.event, name="Leaf", parent=branch)
        authenticated_client.get(_url(party))

        with CaptureQueriesContext(connection) as shallow_queries:
            shallow_response = authenticated_client.get(_url(party))

        agenda_item.space = leaf
        agenda_item.save(update_fields=["space"])
        with CaptureQueriesContext(connection) as deep_queries:
            deep_response = authenticated_client.get(_url(party))

        assert_response(
            shallow_response,
            HTTPStatus.OK,
            context_data=shallow_response.context_data,
            template_name=TEMPLATE,
        )
        assert_response(
            deep_response,
            HTTPStatus.OK,
            context_data=deep_response.context_data,
            template_name=TEMPLATE,
        )
        assert len(deep_queries) == len(shallow_queries)
        assert deep_response.context["history"][0]["cards"][0].loc["path"] == (
            "Root > Branch > Leaf"
        )

    def test_event_ban_lookup_is_one_query_across_history_groups(
        self, authenticated_client, active_user, session, agenda_item
    ):
        _ = agenda_item
        party = sponsor_user(leader=active_user, member=active_user)
        self._enroll_party(party, session, active_user)
        authenticated_client.get(_url(party))

        with CaptureQueriesContext(connection) as one_group_queries:
            authenticated_client.get(_url(party))

        other_event = EventFactory()
        other_session = SessionFactory(event=other_event)
        AgendaItemFactory(session=other_session, space=SpaceFactory(event=other_event))
        self._enroll_party(party, other_session, active_user)
        with CaptureQueriesContext(connection) as two_group_queries:
            authenticated_client.get(_url(party))

        one_group_count = sum(
            '"event_ban"' in query["sql"] for query in one_group_queries
        )
        two_group_count = sum(
            '"event_ban"' in query["sql"] for query in two_group_queries
        )
        assert one_group_count == two_group_count == 1

    def test_history_skips_solo_enrollments(
        self, authenticated_client, active_user, companion, session, agenda_item
    ):
        _ = agenda_item
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=companion)
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
                    [_member_dto(active_user, party), _member_dto(companion, party)],
                    is_default=True,
                ),
                invite_token=party.invite_token,
            ),
            template_name=TEMPLATE,
            contains="No sessions together yet",
        )

    def test_history_card_is_pretend_full_when_presenter_shadowbanned_viewer(
        self, authenticated_client, active_user, companion, session, agenda_item
    ):
        _ = agenda_item
        party = sponsor_user(leader=active_user, member=active_user)
        sponsor_user(leader=active_user, member=companion)
        self._enroll_party(party, session, active_user, companion)
        banner = UserFactory(username="gm", name="GM", email="gm@example.com")
        session.presenter = banner
        session.save()
        banner.shadowbanned.add(active_user)

        response = authenticated_client.get(_url(party))
        history = response.context["history"]

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=_context(
                _party_dto(
                    party,
                    active_user,
                    [_member_dto(active_user, party), _member_dto(companion, party)],
                    is_default=True,
                ),
                invite_token=party.invite_token,
                history=[
                    {
                        "event_name": session.event.name,
                        "event_slug": session.event.slug,
                        "cards": history[0]["cards"],
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

    def test_history_card_is_pretend_full_when_viewer_is_event_banned(
        self, authenticated_client, active_user, session, agenda_item
    ):
        _ = agenda_item
        party = sponsor_user(leader=active_user, member=active_user)
        self._enroll_party(party, session, active_user)
        EventBan.objects.create(event=session.event, user=active_user)

        response = authenticated_client.get(_url(party))

        [group] = response.context["history"]
        [card] = group["cards"]
        assert card.pretend_full
        assert card.is_full
        assert all(
            participation.user.pk < 0 for participation in card.session_participations
        )
