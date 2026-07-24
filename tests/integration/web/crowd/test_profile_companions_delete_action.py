from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import (
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
    User,
)
from tests.integration.conftest import SessionFactory, sponsor_user
from tests.integration.utils import assert_response


class TestProfileCompanionDeleteActionView:
    URL_NAME = "web:crowd:profile-companions-delete"

    def _get_url(self, slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    def test_post_ok(self, authenticated_client, companion):
        response = authenticated_client.post(self._get_url(companion.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Companion deleted successfully.")],
            url=reverse("web:crowd:profile-parties"),
        )

        assert not User.objects.filter(pk=companion.pk).exists()

    def test_post_deletes_companion_memberships_and_enrollments(
        self, authenticated_client, active_user, companion
    ):
        party = sponsor_user(leader=active_user, member=companion)
        session = SessionFactory()
        SessionParticipation.objects.create(
            user=companion,
            session=session,
            party=party,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.post(self._get_url(companion.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Companion deleted successfully.")],
            url=reverse("web:crowd:profile-parties"),
        )
        assert not User.objects.filter(pk=companion.pk).exists()
        assert not PartyMembership.objects.filter(member_id=companion.pk).exists()
        assert not SessionParticipation.objects.filter(user_id=companion.pk).exists()
