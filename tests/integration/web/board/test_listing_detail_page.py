from datetime import UTC, datetime
from http import HTTPStatus

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.links.db.django.models import Tag, TagCategory
from ludamus.pacts.listing import ListingContact, ListingStatus
from tests.integration.conftest import PNG_BYTES, ListingFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.board.expected import listing_dto


def _url(listing):
    return reverse("web:board:detail", kwargs={"pk": listing.pk})


class TestListingDetailPageView:
    def test_anyone_sees_an_open_listing(self, client, sphere):
        listing = ListingFactory(sphere=sphere)

        response = client.get(_url(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing),
                "is_author": False,
                "open_for_days": 30,
                "own_response": None,
                "response_form": None,
                "waiting_count": None,
            },
            template_name="board/detail.html",
        )

    def test_author_sees_their_draft(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            status=ListingStatus.DRAFT,
            opened_at=None,
        )

        response = authenticated_client.get(_url(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing),
                "is_author": True,
                "open_for_days": 30,
                "own_response": None,
                "response_form": None,
                "waiting_count": 0,
            },
            template_name="board/detail.html",
        )

    def test_someone_elses_draft_is_not_found(self, authenticated_client, sphere):
        listing = ListingFactory(
            sphere=sphere, status=ListingStatus.DRAFT, opened_at=None
        )

        response = authenticated_client.get(_url(listing))

        assert_response_404(response)

    def test_listing_of_another_sphere_is_not_found(self, client, non_root_sphere):
        listing = ListingFactory(sphere=non_root_sphere)

        response = client.get(_url(listing))

        assert_response_404(response)

    def test_author_sees_every_detail_of_their_open_listing(
        self, authenticated_client, active_user, sphere
    ):
        active_user.discord_username = "gm#1"
        active_user.save()
        listing = ListingFactory(
            sphere=sphere,
            author=active_user,
            header_image=SimpleUploadedFile(
                "header.png", PNG_BYTES, content_type="image/png"
            ),
            description="Bring **dice**.",
            seats=4,
            medium="Foundry",
            place="Kraków",
            starts_at=datetime(2031, 5, 1, 17, 0, tzinfo=UTC),
            contact=ListingContact.DISCORD,
        )
        genre = TagCategory.objects.create(slug="genre", name="Genre")
        listing.picked_tags.set(
            [
                Tag.objects.create(category=genre, slug="horror", name="Horror"),
                Tag.objects.create(category=genre, slug="osr", name="OSR"),
            ]
        )

        response = authenticated_client.get(_url(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing),
                "is_author": True,
                "open_for_days": 30,
                "own_response": None,
                "response_form": None,
                "waiting_count": 0,
            },
            template_name="board/detail.html",
        )
