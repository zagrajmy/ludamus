from http import HTTPStatus
from unittest.mock import ANY

from django.contrib.messages import constants
from django.urls import reverse

from ludamus.links.db.django.models import ListingResponse, Notification
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.listing import (
    ListingContact,
    ListingResponseDTO,
    ListingResponseStatus,
    ListingStatus,
)
from tests.integration.conftest import ListingFactory, UserFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_response,
    assert_response_404,
)
from tests.integration.web.board.expected import listing_dto

STALE = "This listing has already changed. Nothing was done."


def _detail(listing):
    return reverse("web:board:detail", kwargs={"pk": listing.pk})


def _respond(listing):
    return reverse("web:board:respond", kwargs={"pk": listing.pk})


def _responses(listing):
    return reverse("web:board:responses", kwargs={"pk": listing.pk})


def _decline(response):
    return reverse(
        "web:board:decline",
        kwargs={"pk": response.listing_id, "response_pk": response.pk},
    )


def _response_dto(response):
    response = ListingResponse.objects.select_related("user").get(pk=response.pk)
    return ListingResponseDTO(
        pk=response.pk,
        listing_id=response.listing_id,
        user_id=response.user_id,
        user_name=response.user.full_name,
        message=response.message,
        status=ListingResponseStatus(response.status),
        decline_message=response.decline_message,
        creation_time=response.creation_time,
    )


def _bell(user):
    return list(
        Notification.objects.filter(recipient=user).values_list("kind", "title")
    )


class TestListingRespondActionView:
    def test_records_the_response_and_rings_the_author(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, title="Mörk Borg")

        response = authenticated_client.post(
            _respond(listing), {"message": "Hi!", "contact": ListingContact.EMAIL}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "The author will see you're interested."),),
            url=_detail(listing),
        )
        assert list(
            ListingResponse.objects.values_list("user", "message", "contact", "status")
        ) == [(active_user.pk, "Hi!", "email", "waiting")]
        assert _bell(listing.author) == [
            (
                NotificationKind.LISTING_INTERESTED,
                "Test User is interested in Mörk Borg",
            )
        ]

    def test_shows_the_viewer_their_response(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere)
        own = ListingResponse.objects.create(
            listing=listing, user=active_user, contact=ListingContact.EMAIL
        )

        response = authenticated_client.get(_detail(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing),
                "is_author": False,
                "open_for_days": 30,
                "own_response": _response_dto(own),
                "response_form": None,
                "waiting_count": None,
            },
            template_name="board/detail.html",
        )

    def test_a_second_response_is_refused(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere)
        ListingResponse.objects.create(
            listing=listing, user=active_user, contact=ListingContact.EMAIL
        )

        response = authenticated_client.post(
            _respond(listing), {"contact": ListingContact.EMAIL}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.ERROR, STALE),),
            url=_detail(listing),
        )
        assert ListingResponse.objects.count() == 1

    def test_the_author_cannot_respond(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(sphere=sphere, author=active_user)

        response = authenticated_client.post(
            _respond(listing), {"contact": ListingContact.EMAIL}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.ERROR, STALE),),
            url=_detail(listing),
        )
        assert not ListingResponse.objects.exists()

    def test_a_closed_listing_takes_no_responses(self, authenticated_client, sphere):
        listing = ListingFactory(sphere=sphere, status=ListingStatus.CLOSED)

        response = authenticated_client.post(
            _respond(listing), {"contact": ListingContact.EMAIL}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.ERROR, STALE),),
            url=_detail(listing),
        )
        assert not ListingResponse.objects.exists()

    def test_discord_without_a_discord_name_rerenders_with_the_fix(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere)

        response = authenticated_client.post(
            _respond(listing), {"contact": ListingContact.DISCORD}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing),
                "is_author": False,
                "open_for_days": 30,
                "own_response": None,
                "response_form": FormErrorsMatcher(
                    contact=[
                        (
                            "Select a valid choice. discord is not one of the "
                            "available choices."
                        )
                    ]
                ),
                "waiting_count": None,
            },
            template_name="board/detail.html",
        )
        assert not ListingResponse.objects.exists()


class TestListingWithdrawActionView:
    def test_takes_back_a_waiting_response(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere)
        ListingResponse.objects.create(
            listing=listing, user=active_user, contact=ListingContact.EMAIL
        )

        response = authenticated_client.post(
            reverse("web:board:withdraw", kwargs={"pk": listing.pk})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Your response is withdrawn."),),
            url=_detail(listing),
        )
        assert not ListingResponse.objects.exists()

    def test_a_declined_response_stays(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(sphere=sphere)
        ListingResponse.objects.create(
            listing=listing,
            user=active_user,
            contact=ListingContact.EMAIL,
            status=ListingResponseStatus.DECLINED,
        )

        response = authenticated_client.post(
            reverse("web:board:withdraw", kwargs={"pk": listing.pk})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.ERROR, STALE),),
            url=_detail(listing),
        )
        assert ListingResponse.objects.get().status == ListingResponseStatus.DECLINED


class TestListingResponsesPageView:
    def test_author_sees_who_is_waiting(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user)
        waiting = ListingResponse.objects.create(
            listing=listing, user=UserFactory(), contact=ListingContact.EMAIL
        )
        ListingResponse.objects.create(
            listing=listing,
            user=UserFactory(),
            contact=ListingContact.EMAIL,
            status=ListingResponseStatus.DECLINED,
        )

        response = authenticated_client.get(_responses(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing),
                "responses": [_response_dto(waiting)],
                "counts": {
                    ListingResponseStatus.WAITING: 1,
                    ListingResponseStatus.DECLINED: 1,
                    ListingResponseStatus.NOT_CHOSEN: 0,
                },
                "active_tab": "waiting",
                "decline_form": ANY,
            },
            template_name="board/responses.html",
        )

    def test_someone_elses_listing_is_not_found(self, authenticated_client, sphere):
        listing = ListingFactory(sphere=sphere)

        response = authenticated_client.get(_responses(listing))

        assert_response_404(response)


class TestListingResponseDeclineActionView:
    def test_turns_down_and_tells_them(self, authenticated_client, active_user, sphere):
        listing = ListingFactory(sphere=sphere, author=active_user, title="Mörk Borg")
        responder = UserFactory()
        waiting = ListingResponse.objects.create(
            listing=listing, user=responder, contact=ListingContact.EMAIL
        )

        response = authenticated_client.post(
            _decline(waiting), {"message": "Table is full."}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "They'll be told it's not this time."),),
            url=_responses(listing),
        )
        waiting.refresh_from_db()
        assert (waiting.status, waiting.decline_message) == (
            ListingResponseStatus.DECLINED,
            "Table is full.",
        )
        assert _bell(responder) == [
            (NotificationKind.LISTING_DECLINED, "Not this time: Mörk Borg")
        ]

    def test_a_response_to_another_listing_is_not_found(
        self, authenticated_client, active_user, sphere
    ):
        ListingFactory(sphere=sphere, author=active_user)
        own = ListingFactory(sphere=sphere, author=active_user)
        foreign = ListingResponse.objects.create(
            listing=ListingFactory(sphere=sphere),
            user=UserFactory(),
            contact=ListingContact.EMAIL,
        )

        response = authenticated_client.post(
            reverse(
                "web:board:decline", kwargs={"pk": own.pk, "response_pk": foreign.pk}
            )
        )

        assert_response_404(response)
        foreign.refresh_from_db()
        assert foreign.status == ListingResponseStatus.WAITING
        assert not Notification.objects.exists()


class TestCloseDismissesWaiting:
    def test_closing_tells_everyone_still_waiting(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user, title="Mörk Borg")
        waiting = ListingResponse.objects.create(
            listing=listing, user=UserFactory(), contact=ListingContact.EMAIL
        )
        declined = ListingResponse.objects.create(
            listing=listing,
            user=UserFactory(),
            contact=ListingContact.EMAIL,
            status=ListingResponseStatus.DECLINED,
        )

        authenticated_client.post(reverse("web:board:close", kwargs={"pk": listing.pk}))

        assert dict(ListingResponse.objects.values_list("pk", "status")) == {
            waiting.pk: ListingResponseStatus.NOT_CHOSEN,
            declined.pk: ListingResponseStatus.DECLINED,
        }
        assert list(Notification.objects.values_list("recipient", "kind", "title")) == [
            (
                waiting.user_id,
                NotificationKind.LISTING_NOT_CHOSEN,
                "Mörk Borg has closed",
            )
        ]
