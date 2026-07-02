from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts.safety import ShadowbanCandidateDTO
from tests.integration.conftest import SessionFactory, UserFactory
from tests.integration.utils import assert_response


class TestProfileShadowbanPageView:
    URL = reverse("web:crowd:profile-shadowbans")

    def test_unauthenticated_redirects(self, client):
        response = client.get(self.URL)

        assert response.status_code == HTTPStatus.FOUND

    def test_get_empty(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"candidates": []},
            template_name="crowd/user/shadowbans.html",
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
        # No account enumeration: a miss looks exactly like a hit.
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
                "candidates": [
                    ShadowbanCandidateDTO(
                        pk=player.pk,
                        name="Player Three",
                        slug=player.slug,
                        is_shadowbanned=True,
                    )
                ]
            },
            template_name="crowd/user/shadowbans.html",
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

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "candidates": [
                    ShadowbanCandidateDTO(
                        pk=player.pk,
                        name="Player Five",
                        slug=player.slug,
                        is_shadowbanned=False,
                    )
                ]
            },
            template_name="crowd/user/shadowbans.html",
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
