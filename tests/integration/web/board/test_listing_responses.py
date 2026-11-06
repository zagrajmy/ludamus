from http import HTTPStatus
from unittest.mock import ANY

from django.contrib.messages import constants
from django.urls import reverse

from ludamus.links.db.django.models import (
    ListingResponse,
    Notification,
    Party,
    PartyMembership,
)
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.listing import (
    ListingContact,
    ListingResponseDTO,
    ListingResponseStatus,
    ListingResponseTab,
    ListingStatus,
)
from ludamus.pacts.party import PartyMembershipStatus
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


def _invite(response):
    return reverse(
        "web:board:invite",
        kwargs={"pk": response.listing_id, "response_pk": response.pk},
    )


def _response_dto(response, *, joined=False, contact_address=""):
    response = ListingResponse.objects.select_related("user", "party").get(
        pk=response.pk
    )
    return ListingResponseDTO(
        joined=joined,
        contact_address=contact_address,
        party_name=response.party.name if response.party else "",
        contact=ListingContact(response.contact),
        pk=response.pk,
        listing_id=response.listing_id,
        user_id=response.user_id,
        user_name=response.user.full_name,
        message=response.message,
        status=ListingResponseStatus(response.status),
        decline_message=response.decline_message,
        creation_time=response.creation_time,
    )


def _counts(*, waiting=0, invited=0, joined=0, declined=0):
    return {
        ListingResponseTab.WAITING: waiting,
        ListingResponseTab.INVITED: invited,
        ListingResponseTab.JOINED: joined,
        ListingResponseTab.DECLINED: declined,
    }


def _party(leader, *members, name="Drużyna"):
    party = Party.objects.create(leader=leader, name=name)
    for member in (leader, *members):
        PartyMembership.objects.create(
            party=party, member=member, status=PartyMembershipStatus.ACTIVE
        )
    return party


def _joined_response(listing, user, **fields):
    party = _party(listing.author, user)
    return ListingResponse.objects.create(
        listing=listing,
        user=user,
        contact=ListingContact.EMAIL,
        status=ListingResponseStatus.INVITED,
        party=party,
        **fields,
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

    def test_a_long_title_is_cut_to_fit_the_bell(self, authenticated_client, sphere):
        listing = ListingFactory(sphere=sphere, title="x" * 255)

        authenticated_client.post(
            _respond(listing), {"message": "Hi!", "contact": ListingContact.EMAIL}
        )

        assert _bell(listing.author) == [
            (
                NotificationKind.LISTING_INTERESTED,
                f"Test User is interested in {'x' * 227}…",
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
                "author_contact": "",
                "party_members": [],
                "joined_responses": [],
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
                "author_contact": "",
                "party_members": [],
                "joined_responses": [],
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
                "counts": _counts(waiting=1, declined=1),
                "active_tab": "waiting",
                "decline_form": ANY,
                "invite_form": ANY,
            },
            template_name="board/responses.html",
        )

    def test_someone_elses_listing_is_not_found(self, authenticated_client, sphere):
        listing = ListingFactory(sphere=sphere)

        response = authenticated_client.get(_responses(listing))

        assert_response_404(response)

    def test_own_listing_of_another_sphere_is_not_found(
        self, authenticated_client, active_user, non_root_sphere
    ):
        listing = ListingFactory(sphere=non_root_sphere, author=active_user)

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


class TestListingResponseInviteActionView:
    def test_adds_them_to_a_new_party_named_after_the_listing(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user, title="Mörk Borg")
        responder = UserFactory()
        waiting = ListingResponse.objects.create(
            listing=listing, user=responder, contact=ListingContact.EMAIL
        )

        response = authenticated_client.post(_invite(waiting), {"party": "new"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=(
                (constants.SUCCESS, "Invitation sent. They join once they accept it."),
            ),
            url=_responses(listing),
        )
        party = Party.objects.get()
        assert (party.leader_id, party.name) == (active_user.pk, "Mörk Borg")
        assert dict(
            PartyMembership.objects.filter(party=party).values_list("member", "status")
        ) == {
            active_user.pk: PartyMembershipStatus.ACTIVE,
            responder.pk: PartyMembershipStatus.INVITED,
        }
        waiting.refresh_from_db()
        assert (waiting.status, waiting.party_id) == (
            ListingResponseStatus.INVITED,
            party.pk,
        )
        assert list(
            Notification.objects.filter(recipient=responder).values_list(
                "kind", "title", "body"
            )
        ) == [
            (
                NotificationKind.PARTY_INVITE,
                "Test User invited you to Mörk Borg",
                (
                    "You showed interest in Mörk Borg. Accept the invitation to "
                    "join the party, and you and the author see each other's "
                    "contact."
                ),
            )
        ]

    def test_adds_them_to_a_party_the_author_leads(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user)
        party = _party(active_user, name="Wtorki")
        waiting = ListingResponse.objects.create(
            listing=listing, user=UserFactory(), contact=ListingContact.EMAIL
        )

        authenticated_client.post(_invite(waiting), {"party": str(party.pk)})

        waiting.refresh_from_db()
        assert (Party.objects.count(), waiting.party_id) == (1, party.pk)
        assert PartyMembership.objects.get(party=party, member=waiting.user).status == (
            PartyMembershipStatus.INVITED
        )

    def test_a_party_led_by_someone_else_is_not_found(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user)
        foreign = _party(UserFactory())
        waiting = ListingResponse.objects.create(
            listing=listing, user=UserFactory(), contact=ListingContact.EMAIL
        )

        response = authenticated_client.post(
            _invite(waiting), {"party": str(foreign.pk)}
        )

        assert_response_404(response)
        waiting.refresh_from_db()
        assert (waiting.status, waiting.party_id) == (
            ListingResponseStatus.WAITING,
            None,
        )
        assert not PartyMembership.objects.filter(member=waiting.user).exists()
        assert not Notification.objects.exists()

    def test_a_response_to_another_listing_is_not_found(
        self, authenticated_client, active_user, sphere
    ):
        own = ListingFactory(sphere=sphere, author=active_user)
        foreign = ListingResponse.objects.create(
            listing=ListingFactory(sphere=sphere),
            user=UserFactory(),
            contact=ListingContact.EMAIL,
        )

        response = authenticated_client.post(
            reverse(
                "web:board:invite", kwargs={"pk": own.pk, "response_pk": foreign.pk}
            ),
            {"party": "new"},
        )

        assert_response_404(response)
        foreign.refresh_from_db()
        assert foreign.status == ListingResponseStatus.WAITING
        assert not Party.objects.exists()

    def test_a_declined_response_is_reported_stale(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user)
        declined = ListingResponse.objects.create(
            listing=listing,
            user=UserFactory(),
            contact=ListingContact.EMAIL,
            status=ListingResponseStatus.DECLINED,
        )

        response = authenticated_client.post(_invite(declined), {"party": "new"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.ERROR, STALE),),
            url=_responses(listing),
        )
        assert not Party.objects.exists()


class TestJoinedResponders:
    def test_author_sees_the_contact_of_whoever_joined(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere, author=active_user)
        joined = _joined_response(listing, UserFactory(email="ola@example.com"))

        response = authenticated_client.get(_responses(listing) + "?tab=joined")

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing, party_formed=True),
                "responses": [
                    _response_dto(
                        joined, joined=True, contact_address="ola@example.com"
                    )
                ],
                "counts": _counts(joined=1),
                "active_tab": "joined",
                "decline_form": ANY,
                "invite_form": ANY,
            },
            template_name="board/responses.html",
        )

    def test_member_sees_the_authors_contact(
        self, authenticated_client, active_user, sphere
    ):
        author = UserFactory(email="gm@example.com")
        listing = ListingFactory(sphere=sphere, author=author)
        own = _joined_response(listing, active_user)

        response = authenticated_client.get(_detail(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "listing": listing_dto(listing, party_formed=True),
                "is_author": False,
                "open_for_days": 30,
                "own_response": _response_dto(own, joined=True),
                "response_form": None,
                "waiting_count": None,
                "author_contact": "gm@example.com",
                "party_members": [],
                "joined_responses": [],
            },
            template_name="board/detail.html",
        )

    def test_an_invited_responder_sees_no_contact_until_they_accept(
        self, authenticated_client, active_user, sphere
    ):
        listing = ListingFactory(sphere=sphere)
        own = _joined_response(listing, active_user)
        PartyMembership.objects.filter(member=active_user).update(
            status=PartyMembershipStatus.INVITED
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
                "author_contact": "",
                "party_members": [],
                "joined_responses": [],
            },
            template_name="board/detail.html",
        )

    def test_joining_the_shown_party_by_link_counts(self, client, sphere):
        author, responder = UserFactory(), UserFactory()
        party = _party(author, responder)
        listing = ListingFactory(sphere=sphere, author=author, party=party)
        joined_response = ListingResponse.objects.create(
            listing=listing, user=responder, contact=ListingContact.EMAIL
        )
        client.force_login(author)

        client.post(reverse("web:board:close", kwargs={"pk": listing.pk}))
        response = client.get(_detail(listing))

        assert_response(
            response,
            HTTPStatus.OK,
            messages=((constants.SUCCESS, "Listing closed."),),
            context_data={
                "listing": listing_dto(listing, party_formed=True),
                "is_author": True,
                "open_for_days": 30,
                "own_response": None,
                "response_form": None,
                "waiting_count": 0,
                "author_contact": "",
                "party_members": [author.full_name, responder.full_name],
                "joined_responses": [
                    _response_dto(
                        joined_response, joined=True, contact_address=responder.email
                    )
                ],
            },
            template_name="board/detail.html",
        )
        assert ListingResponse.objects.get().status == ListingResponseStatus.WAITING
        assert not Notification.objects.filter(recipient=responder).exists()
