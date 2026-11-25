import itertools
from datetime import UTC, datetime

from ludamus.mills.listing import ListingService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.listing import (
    ListingBoardRowDTO,
    ListingContact,
    ListingDTO,
    ListingNotification,
    ListingPartyChoiceDTO,
    ListingPartyContactDTO,
    ListingResponseDTO,
    ListingResponseStage,
    ListingResponseTab,
    ListingSeeking,
    ListingStatus,
)
from ludamus.pacts.tags import TagDTO
from tests.unit.factories import FakeTransaction, user_dto

SPHERE_PK = 1
AUTHOR_PK = 2
STRANGER_PK = 3
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

WRITE = {
    "seeking": ListingSeeking.PLAYERS,
    "title": "Zew Cthulhu",
    "what": "one-shot",
    "description": "",
    "seats": 4,
    "medium": "",
    "place": "",
    "starts_at": None,
    "when_text": "",
    "contact": ListingContact.DISCORD,
    "party_id": None,
}


class FakeListings:
    def __init__(self):
        self.rows: dict[int, ListingDTO] = {}
        self.tags: dict[int, list[int]] = {}
        # pk -> (leader, name); shared with FakeParties, which stores parties.
        self.parties: dict[int, tuple[int, str]] = {}

    def create(self, data):
        pk = len(self.rows) + 1
        self.rows[pk] = ListingDTO(
            pk=pk,
            author_name="",
            tags=[],
            status=ListingStatus.DRAFT,
            opened_at=None,
            header_image_url="",
            header_image_original_name="",
            party_formed=False,
            **data,
        )
        return pk

    def add(self, **overrides):
        pk = self.create(
            WRITE | {"sphere_id": SPHERE_PK, "author_id": AUTHOR_PK} | overrides
        )
        return self.rows[pk]

    def update(self, pk, data):
        self.rows[pk] = self.rows[pk].model_copy(update=data)

    def set_tags(self, *, pk, tag_ids):
        self.tags[pk] = tag_ids

    def read(self, *, pk, sphere_id):
        assert sphere_id == SPHERE_PK
        return self.rows[pk]

    lock = read

    def read_authored(self, *, pk, sphere_id, author_id):
        listing = self.read(pk=pk, sphere_id=sphere_id)
        if listing.author_id != author_id:
            raise NotFoundError
        return listing

    lock_authored = read_authored

    def open(self, *, pk, at):
        self.update(pk, {"status": ListingStatus.OPEN, "opened_at": at})

    def close(self, pk):
        self.update(pk, {"status": ListingStatus.CLOSED})

    def close_opened_before(self, cutoff):
        stale = [
            pk
            for pk, listing in self.rows.items()
            if listing.status is ListingStatus.OPEN
            and listing.opened_at is not None
            and listing.opened_at < cutoff
        ]
        for pk in stale:
            self.close(pk)
        return stale

    def led_parties(self, leader_id):
        return [
            ListingPartyChoiceDTO(pk=pk, name=name)
            for pk, (leader, name) in self.parties.items()
            if leader == leader_id
        ]

    def list_for_party(self, party_id):
        return [row for row in self.rows.values() if row.party_id == party_id]

    def party_member_names(self, party_id):
        return [f"member of {party_id}"]

    def read_many(self, pks):
        return [self.rows[pk] for pk in pks]

    def board_rows(self, *, sphere_id, seeking, statuses):
        return [
            ListingBoardRowDTO(
                pk=listing.pk,
                status=listing.status,
                title=listing.title,
                what=listing.what,
                tag_ids=self.tags.get(listing.pk, []),
            )
            for listing in reversed(self.rows.values())
            if listing.sphere_id == sphere_id
            and listing.status in statuses
            and seeking in {None, listing.seeking}
        ]


HORROR, COSMIC, GOTHIC, FANTASY, SCIFI = 10, 11, 12, 13, 14
COC, DND = 20, 21
ONE_SHOT = 30
CALM = 40


class FakeTags:
    @staticmethod
    def read_all():
        return [
            TagDTO(
                pk=pk,
                category_slug=category_slug,
                slug=name.casefold(),
                name=name,
                parent_slug=parent_slug,
            )
            for pk, category_slug, name, parent_slug in (
                (HORROR, "genre", "Horror", None),
                (COSMIC, "genre", "Cosmic", "horror"),
                (GOTHIC, "genre", "Gothic", "horror"),
                (FANTASY, "genre", "Fantasy", None),
                (SCIFI, "genre", "Scifi", None),
                (COC, "system", "CoC", None),
                (DND, "system", "DnD", None),
                (ONE_SHOT, "length", "One-shot", None),
                (CALM, "mood", "Calm", None),
            )
        ]

    @staticmethod
    def category_names():
        return {
            "system": "System",
            "mood": "Mood",
            "length": "Length",
            "genre": "Genre",
        }


class FakeUsers:
    def __init__(self, **profile):
        self.users = {
            AUTHOR_PK: user_dto(pk=AUTHOR_PK, **profile),
            STRANGER_PK: user_dto(
                pk=STRANGER_PK, full_name="Ola", discord_username="ola#1", email=""
            ),
        }

    def read_by_id(self, pk):
        return self.users[pk]


class FakeResponses:
    def __init__(self, listings=None):
        self.listings = listings
        self.rows: dict[int, ListingResponseDTO] = {}
        self._pks = itertools.count(1)

    def create(self, data):
        pk = next(self._pks)
        self.rows[pk] = ListingResponseDTO(
            pk=pk,
            listing_id=data["listing_id"],
            user_id=data["user_id"],
            user_name="",
            message=data["message"],
            stage=ListingResponseStage.WAITING,
            decline_message="",
            creation_time=NOW,
            party_name="",
            contact=None,
            author_contact=None,
        )
        return pk

    def add(self, listing_id, *, user_id=STRANGER_PK):
        return self.create(
            {
                "listing_id": listing_id,
                "user_id": user_id,
                "message": "",
                "contact": ListingContact.DISCORD,
            }
        )

    def read(self, *, pk, listing_id):
        response = self.rows.get(pk)
        if response is None or response.listing_id != listing_id:
            raise NotFoundError
        return response

    def read_own(self, *, listing_id, user_id):
        return next(
            (
                response
                for response in self.rows.values()
                if (response.listing_id, response.user_id) == (listing_id, user_id)
            ),
            None,
        )

    def list_in_tab(self, *, listing_id, tab):
        return [
            response
            for response in self.rows.values()
            if response.listing_id == listing_id and response.stage.value == tab.value
        ]

    def count_by_tab(self, listing_id):
        return {
            tab: len(self.list_in_tab(listing_id=listing_id, tab=tab))
            for tab in ListingResponseTab
        }

    def waiting_user_ids(self, listing_id):
        return [
            response.user_id
            for response in self.list_in_tab(
                listing_id=listing_id, tab=ListingResponseTab.WAITING
            )
        ]

    def decline(self, *, pk, message):
        self._set(pk, stage=ListingResponseStage.DECLINED, decline_message=message)

    def invite(self, *, pk, party_id):
        self._set(pk, stage=ListingResponseStage.INVITED, party_name=str(party_id))

    def dismiss_waiting(self, listing_ids):
        dismissed = []
        for listing_id in listing_ids:
            for response in self.list_in_tab(
                listing_id=listing_id, tab=ListingResponseTab.WAITING
            ):
                self._set(response.pk, stage=ListingResponseStage.NOT_CHOSEN)
                dismissed.append(
                    ListingNotification(
                        recipient_user_id=response.user_id,
                        listing_id=listing_id,
                        listing_title=self.listings.rows[listing_id].title,
                    )
                )
        return dismissed

    def delete(self, pk):
        del self.rows[pk]

    def join(self, pk):
        self._set(
            pk,
            stage=ListingResponseStage.JOINED,
            contact=ListingPartyContactDTO(
                contact=ListingContact.DISCORD, address="ola#1"
            ),
            author_contact=ListingPartyContactDTO(
                contact=ListingContact.DISCORD, address="gm#1"
            ),
        )

    def _set(self, pk, **changes):
        self.rows[pk] = self.rows[pk].model_copy(update=changes)


class FakeParties:
    def __init__(self, listings):
        self.listings = listings
        self.members: set[tuple[int, int]] = set()
        self.active: set[tuple[int, int]] = set()

    def create(self, *, leader_pk, name, enrolls_together=True):
        pk = 100 + len(self.listings.parties)
        self.listings.parties[pk] = (leader_pk, name)
        self.members.add((pk, leader_pk))
        self.active.add((pk, leader_pk))
        return pk

    def read_active_member_party(self, *, member_pk, party_pk):
        return (party_pk, member_pk) if (party_pk, member_pk) in self.active else None

    def get_or_create_membership(self, *, party_pk, user_pk):
        created = (party_pk, user_pk) not in self.members
        self.members.add((party_pk, user_pk))
        return created


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, ListingNotification]] = []

    def notify_listing_interested(self, notification):
        self.sent.append(("interested", notification))

    def notify_listing_declined(self, notification):
        self.sent.append(("declined", notification))

    def notify_listing_not_chosen(self, notification):
        self.sent.append(("not_chosen", notification))

    def notify_listing_changed(self, notification):
        self.sent.append(("changed", notification))

    def notify_listing_party_invited(self, notification):
        self.sent.append(("party_invited", notification))


def make_service(listings, *, responses=None, notifier=None, parties=None, **profile):
    return ListingService(
        transaction=FakeTransaction(),
        listings=listings,
        responses=responses or FakeResponses(),
        users=FakeUsers(**profile),
        tags=FakeTags(),
        parties=parties or FakeParties(listings),
        notifier=notifier or FakeNotifier(),
    )


def ids_of(listing):
    return {"pk": listing.pk, "sphere_id": SPHERE_PK, "author_id": AUTHOR_PK}


DISCORD_ONLY = {"discord_username": "gm#1", "email": ""}
NO_CONTACT = {"discord_username": "", "email": ""}


def open_listing(listings, **overrides):
    listing = listings.add(**overrides)
    listings.open(pk=listing.pk, at=NOW)
    return listings.rows[listing.pk]
