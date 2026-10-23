from http import HTTPStatus
from unittest.mock import ANY

from django.contrib.messages import constants
from django.urls import reverse

from ludamus.links.db.django.models import Listing, Tag, TagCategory
from ludamus.pacts.listing import ListingStatus
from tests.integration.utils import (
    FormErrorsMatcher,
    FormFieldsMatcher,
    RequestTimeMatcher,
    assert_response,
    assert_response_404,
)

URL = reverse("web:board:create")


def _post(**overrides):
    return {
        "pair": "gm:players",
        "title": "Mörk Borg one-shot",
        "what": "A grim dungeon crawl",
        "when_text": "Friday evenings",
        "contact": "email",
    } | overrides


class TestListingCreatePageView:
    def test_login_required(self, client):
        response = client.get(URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={URL}"
        )

    def test_get(self, authenticated_client):
        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="board/create.html",
        )

    def test_get_offers_each_tag_category(self, authenticated_client):
        activity = TagCategory.objects.create(slug="activity", name="Activity")
        ttrpg = Tag.objects.create(category=activity, slug="ttrpg", name="TTRPG")
        osr = Tag.objects.create(
            category=activity, slug="osr", name="OSR", parent=ttrpg
        )
        genre = TagCategory.objects.create(slug="genre", name="Genre")
        horror = Tag.objects.create(category=genre, slug="horror", name="Horror")

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormFieldsMatcher(
                    tags={
                        "choices": [
                            (ttrpg.pk, "TTRPG"),
                            (osr.pk, "TTRPG \u203a OSR"),
                            (horror.pk, "Horror"),
                        ]
                    }
                )
            },
            template_name="board/create.html",
        )

    def test_other_sphere_has_no_form(self, authenticated_client, non_root_sphere):
        response = authenticated_client.get(URL, HTTP_HOST=non_root_sphere.site.domain)

        assert_response_404(response)

    def test_publish_stores_the_picked_tags(
        self, authenticated_client, active_user, sphere
    ):
        activity = TagCategory.objects.create(slug="activity", name="Activity")
        ttrpg = Tag.objects.create(category=activity, slug="ttrpg", name="TTRPG")
        osr = Tag.objects.create(
            category=activity, slug="osr", name="OSR", parent=ttrpg
        )
        mork = Tag.objects.create(
            category=activity, slug="mork-borg", name="Mörk Borg", parent=osr
        )

        response = authenticated_client.post(URL, _post(tags=[mork.pk], publish=""))

        listing = Listing.objects.get()
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Listing published."),),
            url=reverse("web:board:detail", kwargs={"pk": listing.pk}),
        )
        assert (listing.sphere, listing.author, listing.status, listing.opened_at) == (
            sphere,
            active_user,
            ListingStatus.OPEN,
            RequestTimeMatcher(),
        )
        assert list(listing.picked_tags.all()) == [mork]

    def test_save_draft(self, authenticated_client):
        response = authenticated_client.post(URL, _post(draft=""))

        listing = Listing.objects.get()
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Draft saved."),),
            url=reverse("web:board:detail", kwargs={"pk": listing.pk}),
        )
        assert (listing.status, listing.opened_at) == (ListingStatus.DRAFT, None)

    def test_needs_a_when(self, authenticated_client):
        response = authenticated_client.post(URL, _post(when_text=""))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormErrorsMatcher(
                    when_text=["Give a date and time, or describe when."]
                )
            },
            template_name="board/create.html",
        )
        assert not Listing.objects.exists()

    def test_refuses_a_pair_not_offered(self, authenticated_client):
        response = authenticated_client.post(URL, _post(pair="gm:gm"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormErrorsMatcher(
                    pair=[
                        (
                            "Select a valid choice. gm:gm is not one of the "
                            "available choices."
                        )
                    ]
                )
            },
            template_name="board/create.html",
        )
        assert not Listing.objects.exists()

    def test_email_contact_needs_email_on_the_profile(
        self, authenticated_client, active_user
    ):
        active_user.discord_username = "gm#1"
        active_user.email = ""
        active_user.save()

        response = authenticated_client.post(URL, _post(contact="email", publish=""))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormErrorsMatcher(
                    contact=[
                        (
                            "Select a valid choice. email is not one of the "
                            "available choices."
                        )
                    ]
                )
            },
            template_name="board/create.html",
        )
        assert not Listing.objects.exists()

    def test_without_any_contact_a_draft_still_saves(
        self, authenticated_client, active_user
    ):
        active_user.discord_username = ""
        active_user.email = ""
        active_user.save()

        response = authenticated_client.post(URL, _post(draft=""))

        listing = Listing.objects.get()
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Draft saved."),),
            url=reverse("web:board:detail", kwargs={"pk": listing.pk}),
        )
        assert listing.status == ListingStatus.DRAFT

    def test_discord_contact_needs_discord_on_the_profile(
        self, authenticated_client, active_user
    ):
        active_user.discord_username = ""
        active_user.save()

        response = authenticated_client.post(URL, _post(contact="discord", publish=""))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": FormErrorsMatcher(
                    contact=[
                        (
                            "Select a valid choice. discord is not one of the "
                            "available choices."
                        )
                    ]
                )
            },
            template_name="board/create.html",
        )
        assert not Listing.objects.exists()
