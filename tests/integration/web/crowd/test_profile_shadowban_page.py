from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    Session,
    SessionParticipation,
    SessionParticipationStatus,
    User,
)
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts.safety import ShadowbanCandidateDTO, ShadowbanMeetSessionDTO
from tests.integration.conftest import SessionFactory, UserFactory
from tests.integration.utils import assert_response


def _meet(session: Session) -> ShadowbanMeetSessionDTO:
    return ShadowbanMeetSessionDTO(
        session_id=session.pk,
        title=session.title,
        event_slug=session.event.slug,
        event_name=session.event.name,
        sphere_name=session.event.sphere.name,
        sphere_domain=session.event.sphere.site.domain,
    )


def _candidate_dto(
    user: User,
    *,
    is_shadowbanned: bool,
    met_sessions: list[ShadowbanMeetSessionDTO] | None = None,
) -> ShadowbanCandidateDTO:
    avatar_url = (
        gravatar_url(user.email) or ""
        if user.use_gravatar
        else user.avatar_url or gravatar_url(user.email) or ""
    )
    return ShadowbanCandidateDTO(
        pk=user.pk,
        full_name=user.full_name,
        username=user.username,
        slug=user.slug,
        avatar_url=avatar_url,
        is_shadowbanned=is_shadowbanned,
        met_sessions=met_sessions or [],
    )


class TestProfileShadowbanPageView:
    URL = reverse("web:crowd:profile-safety")

    def test_unauthenticated_redirects(self, client):
        response = client.get(self.URL)

        assert response.status_code == HTTPStatus.FOUND

    def test_get_empty(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"candidates": [], "profile_active_tab": "safety"},
            template_name="crowd/user/safety.html",
        )

    def test_add_by_username(self, authenticated_client, active_user):
        player = UserFactory(
            username="player1", email="player1@example.com", name="Player One"
        )

        response = authenticated_client.post(self.URL, data={"identifier": "player1"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "If a matching player exists, they have been shadowbanned.",
                )
            ],
            url=self.URL,
        )
        assert list(active_user.shadowbanned.all()) == [player]

    def test_add_by_email(self, authenticated_client, active_user):
        player = UserFactory(
            username="player2", email="player2@example.com", name="Player Two"
        )

        response = authenticated_client.post(
            self.URL, data={"identifier": "player2@example.com"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "If a matching player exists, they have been shadowbanned.",
                )
            ],
            url=self.URL,
        )
        assert list(active_user.shadowbanned.all()) == [player]

    def test_add_by_identifier_not_found_is_neutral(
        self, authenticated_client, active_user
    ):
        response = authenticated_client.post(self.URL, data={"identifier": "ghost"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "If a matching player exists, they have been shadowbanned.",
                )
            ],
            url=self.URL,
        )
        assert not active_user.shadowbanned.exists()

    def test_cannot_shadowban_self(self, authenticated_client, active_user):
        response = authenticated_client.post(
            self.URL, data={"identifier": active_user.username}
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not active_user.shadowbanned.exists()

    def test_get_lists_shadowbanned_player(self, authenticated_client, active_user):
        player = UserFactory(
            username="player3", email="player3@example.com", name="Player Three"
        )
        active_user.shadowbanned.add(player)

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "candidates": [_candidate_dto(player, is_shadowbanned=True)],
                "profile_active_tab": "safety",
            },
            template_name="crowd/user/safety.html",
        )

    def test_get_lists_player_met_in_own_session(
        self, authenticated_client, active_user
    ):
        player = UserFactory(
            username="player5", email="player5@example.com", name="Player Five"
        )
        session = SessionFactory(presenter=active_user)
        SessionParticipation.objects.create(
            session=session,
            user=player,
            status=SessionParticipationStatus.CONFIRMED.value,
        )

        response = authenticated_client.get(self.URL)

        event = session.event
        sep = chr(0x203A)
        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "candidates": [
                    _candidate_dto(
                        player, is_shadowbanned=False, met_sessions=[_meet(session)]
                    )
                ],
                "profile_active_tab": "safety",
            },
            template_name="crowd/user/safety.html",
            contains=[
                f"//{event.sphere.site.domain}/event/{event.slug}/?session={session.pk}",
                f"{event.sphere.name} {sep} {event.name} {sep} ",
                f'<span class="underline">{session.title}</span>',
            ],
        )

    def test_get_lists_players_met_at_a_shared_session(
        self, authenticated_client, active_user
    ):
        table_mate = UserFactory(
            username="mate", email="mate@example.com", name="Table Mate"
        )
        session = SessionFactory()
        for player in (active_user, table_mate):
            SessionParticipation.objects.create(
                session=session,
                user=player,
                status=SessionParticipationStatus.CONFIRMED.value,
            )

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "candidates": [
                    _candidate_dto(
                        table_mate, is_shadowbanned=False, met_sessions=[_meet(session)]
                    )
                ],
                "profile_active_tab": "safety",
            },
            template_name="crowd/user/safety.html",
        )

    def test_waitlisted_co_participant_is_not_met(
        self, authenticated_client, active_user
    ):
        waiter = UserFactory(username="wait", email="wait@example.com", name="Waiter")
        session = SessionFactory()
        SessionParticipation.objects.create(
            session=session,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED.value,
        )
        SessionParticipation.objects.create(
            session=session,
            user=waiter,
            status=SessionParticipationStatus.WAITING.value,
        )

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"candidates": [], "profile_active_tab": "safety"},
            template_name="crowd/user/safety.html",
        )

    def test_waitlisted_owner_has_not_met_confirmed_player(
        self, authenticated_client, active_user
    ):
        seated = UserFactory(username="seat", email="seat@example.com", name="Seated")
        session = SessionFactory()
        SessionParticipation.objects.create(
            session=session,
            user=active_user,
            status=SessionParticipationStatus.WAITING.value,
        )
        SessionParticipation.objects.create(
            session=session,
            user=seated,
            status=SessionParticipationStatus.CONFIRMED.value,
        )

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"candidates": [], "profile_active_tab": "safety"},
            template_name="crowd/user/safety.html",
        )

    def test_get_lists_shadowbanned_players_first(
        self, authenticated_client, active_user
    ):
        anna = UserFactory(username="anna", email="anna@example.com", name="Anna")
        bob = UserFactory(username="bob", email="bob@example.com", name="Bob")
        yara = UserFactory(username="yara", email="yara@example.com", name="Yara")
        zoe = UserFactory(username="zoe", email="zoe@example.com", name="Zoe")
        session = SessionFactory(presenter=active_user)
        for player in (anna, bob, yara, zoe):
            SessionParticipation.objects.create(
                session=session,
                user=player,
                status=SessionParticipationStatus.CONFIRMED.value,
            )
        active_user.shadowbanned.add(anna, zoe)

        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "candidates": [
                    _candidate_dto(
                        anna, is_shadowbanned=True, met_sessions=[_meet(session)]
                    ),
                    _candidate_dto(
                        zoe, is_shadowbanned=True, met_sessions=[_meet(session)]
                    ),
                    _candidate_dto(
                        bob, is_shadowbanned=False, met_sessions=[_meet(session)]
                    ),
                    _candidate_dto(
                        yara, is_shadowbanned=False, met_sessions=[_meet(session)]
                    ),
                ],
                "profile_active_tab": "safety",
            },
            template_name="crowd/user/safety.html",
        )

    def test_shadowban_by_slug(self, authenticated_client, active_user):
        player = UserFactory(
            username="player6", email="player6@example.com", name="Player Six"
        )

        response = authenticated_client.post(
            self.URL, data={"slug": player.slug, "banned": "true"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Player shadowbanned.")],
            url=self.URL,
        )
        assert list(active_user.shadowbanned.all()) == [player]

    def test_post_without_identifier_or_slug_is_noop(
        self, authenticated_client, active_user
    ):
        response = authenticated_client.post(self.URL, data={})

        assert_response(response, HTTPStatus.FOUND, url=self.URL)
        assert not active_user.shadowbanned.exists()

    def test_remove_shadowban(self, authenticated_client, active_user):
        player = UserFactory(
            username="player4", email="player4@example.com", name="Player Four"
        )
        active_user.shadowbanned.add(player)

        response = authenticated_client.post(
            self.URL, data={"slug": player.slug, "banned": "false"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Shadowban removed.")],
            url=self.URL,
        )
        assert not active_user.shadowbanned.exists()
