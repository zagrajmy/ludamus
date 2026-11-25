import pytest

from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.listing import (
    ListingContact,
    ListingContactMissingError,
    ListingDeclinedNotification,
    ListingInterestedNotification,
    ListingPartyContactDTO,
    ListingPartyInviteNotification,
    ListingResponsesDTO,
    ListingResponseStage,
    ListingResponseTab,
    ListingStatus,
    ListingStatusError,
)
from tests.unit.test_listing_service.fakes import (
    AUTHOR_PK,
    DISCORD_ONLY,
    SPHERE_PK,
    STRANGER_PK,
    WRITE,
    FakeListings,
    FakeNotifier,
    FakeParties,
    FakeResponses,
    ids_of,
    make_service,
    open_listing,
)


class TestRespond:
    def _respond(self, service, listing, *, contact=ListingContact.DISCORD):
        service.respond(
            pk=listing.pk,
            sphere_id=SPHERE_PK,
            user_id=STRANGER_PK,
            message="Count me in",
            contact=contact,
        )

    def test_saves_a_waiting_response_and_tells_the_author(self):
        listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
        listing = open_listing(listings)

        self._respond(
            make_service(listings, responses=responses, notifier=notifier), listing
        )

        assert (responses.waiting_user_ids(listing.pk), notifier.sent) == (
            [STRANGER_PK],
            [
                (
                    "interested",
                    ListingInterestedNotification(
                        recipient_user_id=AUTHOR_PK,
                        listing_id=listing.pk,
                        listing_title="Zew Cthulhu",
                        responder_name="Ola",
                        message="Count me in",
                    ),
                )
            ],
        )

    @pytest.mark.parametrize(
        "case", ("draft", "closed", "own listing", "already responded")
    )
    def test_refuses_where_no_response_is_due(self, case):
        listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
        listing = open_listing(
            listings, author_id=STRANGER_PK if case == "own listing" else AUTHOR_PK
        )
        match case:
            case "draft":
                listings.update(listing.pk, {"status": ListingStatus.DRAFT})
            case "closed":
                listings.close(listing.pk)
            case "already responded":
                responses.add(listing.pk)
        before = dict(responses.rows)

        with pytest.raises(ListingStatusError):
            self._respond(
                make_service(listings, responses=responses, notifier=notifier), listing
            )

        assert (responses.rows, notifier.sent) == (before, [])

    def test_refuses_a_contact_missing_from_the_responders_profile(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)

        with pytest.raises(ListingContactMissingError):
            self._respond(
                make_service(listings, responses=responses),
                listing,
                contact=ListingContact.EMAIL,
            )

        assert not responses.rows


class TestWithdraw:
    def test_deletes_a_waiting_response(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)
        responses.add(listing.pk)

        make_service(listings, responses=responses).withdraw(
            pk=listing.pk, sphere_id=SPHERE_PK, user_id=STRANGER_PK
        )

        assert not responses.rows

    def test_refuses_without_a_response(self):
        listings = FakeListings()
        listing = open_listing(listings)

        with pytest.raises(ListingStatusError):
            make_service(listings).withdraw(
                pk=listing.pk, sphere_id=SPHERE_PK, user_id=STRANGER_PK
            )

    def test_refuses_a_declined_response(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)
        responses.decline(pk=responses.add(listing.pk), message="")
        before = dict(responses.rows)

        with pytest.raises(ListingStatusError):
            make_service(listings, responses=responses).withdraw(
                pk=listing.pk, sphere_id=SPHERE_PK, user_id=STRANGER_PK
            )

        assert responses.rows == before


class TestDecline:
    def _decline(self, service, listing, response_pk):
        service.decline(
            **ids_of(listing), response_id=response_pk, message="Table is full"
        )

    def test_declines_and_tells_the_responder_why(self):
        listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
        listing = open_listing(listings)
        response_pk = responses.add(listing.pk)

        self._decline(
            make_service(listings, responses=responses, notifier=notifier),
            listing,
            response_pk,
        )

        assert (
            responses.rows[response_pk].stage,
            responses.rows[response_pk].decline_message,
            notifier.sent,
        ) == (
            ListingResponseStage.DECLINED,
            "Table is full",
            [
                (
                    "declined",
                    ListingDeclinedNotification(
                        recipient_user_id=STRANGER_PK,
                        listing_id=listing.pk,
                        listing_title="Zew Cthulhu",
                        message="Table is full",
                    ),
                )
            ],
        )

    def test_refuses_a_response_no_longer_waiting(self):
        listings, notifier = FakeListings(), FakeNotifier()
        responses = FakeResponses(listings)
        listing = open_listing(listings)
        response_pk = responses.add(listing.pk)
        responses.dismiss_waiting([listing.pk])

        with pytest.raises(ListingStatusError):
            self._decline(
                make_service(listings, responses=responses, notifier=notifier),
                listing,
                response_pk,
            )

        assert (responses.rows[response_pk].stage, notifier.sent) == (
            ListingResponseStage.NOT_CHOSEN,
            [],
        )

    def test_response_to_another_listing_is_not_found(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)
        other_pk = responses.add(open_listing(listings).pk)

        with pytest.raises(NotFoundError):
            self._decline(
                make_service(listings, responses=responses), listing, other_pk
            )

        assert responses.rows[other_pk].stage is ListingResponseStage.WAITING


class TestResponses:
    def test_lists_responses_in_the_asked_tab(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)
        waiting_pk = responses.add(listing.pk)
        responses.decline(pk=responses.add(listing.pk, user_id=4), message="")

        result = make_service(listings, responses=responses).responses(
            **ids_of(listing), tab=ListingResponseTab.WAITING
        )

        assert result == ListingResponsesDTO(
            listing=listing,
            responses=[responses.rows[waiting_pk]],
            counts={
                ListingResponseTab.WAITING: 1,
                ListingResponseTab.INVITED: 0,
                ListingResponseTab.JOINED: 0,
                ListingResponseTab.DECLINED: 1,
            },
            parties=[],
        )

    def test_another_authors_listing_is_not_found(self):
        listings = FakeListings()
        listing = open_listing(listings, author_id=STRANGER_PK)

        with pytest.raises(NotFoundError):
            make_service(listings).responses(
                **ids_of(listing), tab=ListingResponseTab.WAITING
            )


class TestAddToParty:
    def _add(self, service, listing, response_pk, *, party_id=None):
        service.add_to_party(
            **ids_of(listing), response_id=response_pk, party_id=party_id
        )

    def test_new_party_takes_the_listing_title_and_invites_them(self):
        listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
        parties = FakeParties(listings)
        listing = open_listing(listings)
        response_pk = responses.add(listing.pk)

        self._add(
            make_service(
                listings, responses=responses, notifier=notifier, parties=parties
            ),
            listing,
            response_pk,
        )

        assert (
            listings.parties,
            parties.members,
            responses.rows[response_pk].stage,
            notifier.sent,
        ) == (
            {100: (AUTHOR_PK, "Zew Cthulhu")},
            {(100, AUTHOR_PK), (100, STRANGER_PK)},
            ListingResponseStage.INVITED,
            [
                (
                    "party_invited",
                    ListingPartyInviteNotification(
                        recipient_user_id=STRANGER_PK,
                        listing_id=listing.pk,
                        listing_title="Zew Cthulhu",
                        party_name="Zew Cthulhu",
                        author_name="",
                    ),
                )
            ],
        )

    def test_someone_already_in_the_party_is_not_invited_again(self):
        listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
        parties = FakeParties(listings)
        listing = open_listing(listings)
        party_pk = parties.create(leader_pk=AUTHOR_PK, name="Wtorki")
        parties.get_or_create_membership(party_pk=party_pk, user_pk=STRANGER_PK)
        parties.active.add((party_pk, STRANGER_PK))
        response_pk = responses.add(listing.pk)

        self._add(
            make_service(
                listings, responses=responses, notifier=notifier, parties=parties
            ),
            listing,
            response_pk,
            party_id=party_pk,
        )

        assert (responses.rows[response_pk].stage, notifier.sent) == (
            ListingResponseStage.INVITED,
            [],
        )

    def test_a_pending_invite_still_hears_about_the_listing(self):
        listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
        parties = FakeParties(listings)
        listing = open_listing(listings)
        party_pk = parties.create(leader_pk=AUTHOR_PK, name="Wtorki")
        parties.get_or_create_membership(party_pk=party_pk, user_pk=STRANGER_PK)
        response_pk = responses.add(listing.pk)

        self._add(
            make_service(
                listings, responses=responses, notifier=notifier, parties=parties
            ),
            listing,
            response_pk,
            party_id=party_pk,
        )

        assert notifier.sent == [
            (
                "party_invited",
                ListingPartyInviteNotification(
                    recipient_user_id=STRANGER_PK,
                    listing_id=listing.pk,
                    listing_title="Zew Cthulhu",
                    party_name="Wtorki",
                    author_name="",
                ),
            )
        ]

    def test_a_party_the_author_does_not_lead_is_not_found(self):
        listings, responses, notifier = FakeListings(), FakeResponses(), FakeNotifier()
        parties = FakeParties(listings)
        listing = open_listing(listings)
        foreign_pk = parties.create(leader_pk=STRANGER_PK, name="")
        response_pk = responses.add(listing.pk, user_id=4)

        with pytest.raises(NotFoundError):
            self._add(
                make_service(
                    listings, responses=responses, notifier=notifier, parties=parties
                ),
                listing,
                response_pk,
                party_id=foreign_pk,
            )

        assert (
            responses.rows[response_pk].stage,
            (foreign_pk, 4) in parties.members,
            notifier.sent,
        ) == (ListingResponseStage.WAITING, False, [])

    def test_refuses_a_response_no_longer_waiting(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)
        response_pk = responses.add(listing.pk)
        responses.decline(pk=response_pk, message="")

        with pytest.raises(ListingStatusError):
            self._add(make_service(listings, responses=responses), listing, response_pk)

        assert not listings.parties

    def test_response_to_another_listing_is_not_found(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = open_listing(listings)
        other_pk = responses.add(open_listing(listings).pk)

        with pytest.raises(NotFoundError):
            self._add(make_service(listings, responses=responses), listing, other_pk)

        assert not listings.parties


class TestShownParty:
    def test_create_refuses_a_party_the_author_does_not_lead(self):
        listings = FakeListings()
        listings.parties[100] = (STRANGER_PK, "")

        with pytest.raises(NotFoundError):
            make_service(listings).create(
                WRITE | {
                    "sphere_id": SPHERE_PK,
                    "author_id": AUTHOR_PK,
                    "party_id": 100,
                },
                tag_ids=[],
                publish_at=None,
            )

        assert not listings.rows

    def test_update_refuses_switching_to_a_party_the_author_does_not_lead(self):
        listings = FakeListings()
        listings.parties[100] = (STRANGER_PK, "")
        listing = open_listing(listings)

        with pytest.raises(NotFoundError):
            make_service(listings).update(
                **ids_of(listing), data=WRITE | {"party_id": 100}, tag_ids=[]
            )

        assert listings.rows[listing.pk] == listing

    def test_detail_names_the_members_of_the_shown_party(self):
        listings = FakeListings()
        listings.parties[100] = (AUTHOR_PK, "")
        listing = open_listing(listings, party_id=100)

        detail = make_service(listings).detail(
            pk=listing.pk, sphere_id=SPHERE_PK, viewer_id=None
        )

        assert detail.party_members == ["member of 100"]


class TestPartyContacts:
    @staticmethod
    def _tied_listing(listings):
        listings.parties[100] = (AUTHOR_PK, "")
        return open_listing(listings, party_id=100)

    def test_the_author_gets_each_joined_responders_contact(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = self._tied_listing(listings)
        responses.join(responses.add(listing.pk))

        contacts = (
            make_service(listings, responses=responses, **DISCORD_ONLY)
            .party_listings(party_id=100, viewer_id=AUTHOR_PK)
            .contacts
        )

        assert contacts == {
            STRANGER_PK: ListingPartyContactDTO(
                contact=ListingContact.DISCORD, address="ola#1"
            )
        }

    def test_a_joined_responder_gets_the_authors_contact(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = self._tied_listing(listings)
        responses.join(responses.add(listing.pk))

        contacts = (
            make_service(listings, responses=responses, **DISCORD_ONLY)
            .party_listings(party_id=100, viewer_id=STRANGER_PK)
            .contacts
        )

        assert contacts == {
            AUTHOR_PK: ListingPartyContactDTO(
                contact=ListingContact.DISCORD, address="gm#1"
            )
        }

    def test_a_responder_who_has_not_joined_gets_nothing(self):
        listings, responses = FakeListings(), FakeResponses()
        listing = self._tied_listing(listings)
        responses.add(listing.pk)

        contacts = (
            make_service(listings, responses=responses, **DISCORD_ONLY)
            .party_listings(party_id=100, viewer_id=STRANGER_PK)
            .contacts
        )

        assert contacts == {}

    def test_a_member_who_never_responded_gets_nothing(self):
        listings = FakeListings()
        self._tied_listing(listings)

        contacts = (
            make_service(listings, **DISCORD_ONLY)
            .party_listings(party_id=100, viewer_id=STRANGER_PK)
            .contacts
        )

        assert contacts == {}
