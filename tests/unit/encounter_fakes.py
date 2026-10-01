from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from ludamus.mills.encounter import EncounterService
from ludamus.mills.encounter_calendar import EncounterGuests
from ludamus.pacts import EncounterDTO, NotFoundError
from ludamus.pacts.crowd import UserDTO, UserType
from ludamus.pacts.encounter import EncounterInviteeDTO, EncountersPolicy, InviteeStatus
from tests.unit.factories import FakeTransaction

CREATOR_ID = 10
OTHER_USER_ID = 20
SPHERE_ID = 3
START_TIME = datetime(2026, 8, 1, 18, 0, tzinfo=UTC)


def make_encounter(pk=1, *, max_participants=0):
    return EncounterDTO(
        creation_time=START_TIME - timedelta(days=7),
        creator_id=CREATOR_ID,
        description="",
        end_time=None,
        game="Gloomhaven",
        max_participants=max_participants,
        pk=pk,
        place="",
        share_code=f"CODE{pk}",
        sphere_id=SPHERE_ID,
        start_time=START_TIME,
        title=f"Encounter {pk}",
    )


def make_user(pk=CREATOR_ID, **overrides):
    fields = {
        "avatar_url": "",
        "date_joined": START_TIME - timedelta(days=30),
        "discord_username": "",
        "email": f"user{pk}@example.com",
        "full_name": "",
        "is_active": True,
        "is_authenticated": True,
        "is_staff": False,
        "is_superuser": False,
        "name": "",
        "pk": pk,
        "slug": f"user-{pk}",
        "use_gravatar": True,
        "user_type": UserType.ACTIVE,
        "username": "creator",
    }
    return UserDTO(**{**fields, **overrides})


class FakeSites:
    def __init__(self, policy):
        self.policy = policy

    def read(self, sphere_id):
        del sphere_id
        return SimpleNamespace(
            encounters_policy=self.policy,
            name="Sphere",
            site=SimpleNamespace(domain="sphere.example.com"),
        )


class FakeUsers:
    def __init__(self, users=()):
        self.users = {user.pk: user for user in users}

    def read_by_id(self, pk):
        try:
            return self.users[pk]
        except KeyError:
            raise NotFoundError from None

    def read_by_ids(self, pks):
        return [self.users[pk] for pk in pks if pk in self.users]

    def read_by_email(self, email):
        for user in self.users.values():
            if user.email == email:
                return user
        raise NotFoundError


class FakeSpheres:
    def __init__(self, roles=None):
        self.roles = roles or {}

    def manager_role(self, sphere_id, user_slug):
        del sphere_id
        return self.roles.get(user_slug)


class FakeEncounters:
    def __init__(self, rows=(), *, past=()):
        self.rows = {row.pk: row for row in rows}
        self.past = {row.pk: row for row in past}

    def _in_sphere(self, sphere_id):
        return [
            row
            for row in {**self.rows, **self.past}.values()
            if row.sphere_id == sphere_id
        ]

    def create(self, data):
        pk = max(self.rows, default=0) + 1
        self.rows[pk] = make_encounter(pk).model_copy(update=dict(data))
        return self.rows[pk]

    def read(self, pk, sphere_id):
        row = self.rows.get(pk)
        if row is None or row.sphere_id != sphere_id:
            raise NotFoundError
        return row

    def read_by_share_code(self, share_code, sphere_id):
        rows = [
            row for row in self._in_sphere(sphere_id) if row.share_code == share_code
        ]
        if not rows:
            raise NotFoundError
        return rows[0]

    def read_by_share_code_in_any_sphere(self, share_code):
        for row in self.rows.values():
            if row.share_code == share_code:
                return row
        raise NotFoundError

    def update(self, pk, data):
        self.rows[pk] = self.rows[pk].model_copy(update=dict(data))

    def delete(self, pk):
        del self.rows[pk]

    def list_visible_upcoming(self, sphere_id, user_id, limit):
        del user_id
        rows = [row for row in self.rows.values() if row.sphere_id == sphere_id]
        return rows[:limit] if limit is not None else rows

    def list_visible_past(self, sphere_id, user_id, limit):
        del user_id
        return [row for row in self.past.values() if row.sphere_id == sphere_id][:limit]


class FakeRSVPs:
    def __init__(self, signups=(), *, recent_ips=()):
        # (encounter_id, user_id) pairs
        self.signups = list(signups)
        self.recent_ips = set(recent_ips)

    def create(self, encounter_id, ip_address, user_id):
        self.signups.append((encounter_id, user_id))
        self.recent_ips.add(ip_address)

    def list_by_encounter(self, encounter_id):
        return [
            SimpleNamespace(user_id=user_id)
            for enc, user_id in self.signups
            if enc == encounter_id
        ]

    def count_by_encounter(self, encounter_id):
        return len(self.list_by_encounter(encounter_id))

    def count_by_encounters(self, encounter_ids):
        return {pk: self.count_by_encounter(pk) for pk in encounter_ids}

    def recent_rsvp_exists(self, ip_address, seconds=60):
        del seconds
        return ip_address in self.recent_ips

    def user_has_rsvpd(self, encounter_id, user_id):
        return (encounter_id, user_id) in self.signups

    def delete_by_user(self, encounter_id, user_id):
        self.signups.remove((encounter_id, user_id))


class FakeInvitees:
    """Invitee rows that behave like the Django repository.

    `rows` maps (encounter_id, email) to status; `born` maps the same keys to
    (creator_id, creation_time). Addresses in `invited_today` become rows of
    a deleted encounter (encounter_id None) the creator filled within the
    daily window, which the cap counts but no list shows.
    """

    def __init__(self, rows=(), *, users=None, rsvps=None, invited_today=()):
        self.rows = dict(rows)
        self.rows |= {(None, email): InviteeStatus.INVITED for email in invited_today}
        now = datetime.now(UTC)
        self.born = dict.fromkeys(self.rows, (CREATOR_ID, now))
        self.users = users or FakeUsers()
        self.rsvps = rsvps or FakeRSVPs()

    def _key(self, encounter_id, email):
        return next(
            (
                (enc, address)
                for enc, address in self.rows
                if enc == encounter_id and address.casefold() == email.casefold()
            ),
            None,
        )

    def _account(self, email):
        try:
            return self.users.read_by_email(email).pk
        except NotFoundError:
            return None

    def list_by_encounter(self, encounter_id):
        return [
            EncounterInviteeDTO(
                email=email, status=status, user_id=self._account(email)
            )
            for (enc, email), status in self.rows.items()
            if enc == encounter_id and status is not InviteeStatus.REMOVED
        ]

    # NOTE: the mill adds only addresses off the list and removes only ones
    # on it, so an existing row here is always a removed one.
    def add(self, *, encounter_id, emails, creator_id):
        for email in emails:
            self.born.setdefault((encounter_id, email), (creator_id, datetime.now(UTC)))
            self.rows[encounter_id, email] = InviteeStatus.INVITED

    def remove(self, encounter_id, emails):
        for email in emails:
            self.rows[encounter_id, email] = InviteeStatus.REMOVED

    def set_status(self, *, encounter_id, email, status):
        key = self._key(encounter_id, email)
        if key is None or self.rows[key] is InviteeStatus.REMOVED:
            return False
        self.rows[key] = status
        return True

    def read_status(self, encounter_id, email):
        key = self._key(encounter_id, email)
        return None if key is None else self.rows[key]

    def count_accepted_without_signup(self, encounter_id):
        return sum(
            1
            for invitee in self.list_by_encounter(encounter_id)
            if invitee.status is InviteeStatus.ACCEPTED
            and not (
                invitee.user_id
                and self.rsvps.user_has_rsvpd(encounter_id, invitee.user_id)
            )
        )

    def emails_invited_by_creator_since(self, creator_id, since):
        return {
            email
            for (_enc, email), (creator, created) in self.born.items()
            if creator == creator_id and created >= since
        }

    def purge_stale(self, before):
        stale = [
            key
            for key, (_creator, created) in self.born.items()
            if created < before
            and (key[0] is None or self.rows[key] is InviteeStatus.REMOVED)
        ]
        for key in stale:
            del self.rows[key], self.born[key]
        return len(stale)


class FakeMailer:
    def __init__(self):
        self.invites = []

    @property
    def sent(self):
        return [(i.reason, i.attendee_email) for i in self.invites]

    def send(self, invites):
        self.invites += invites


class FakeReplyAddresses:
    @staticmethod
    def address_for(*, uid, attendee_email):
        return f"rsvp+{uid}+{attendee_email}@example.com"

    def matches(self, *, address, uid, attendee_email):
        return address == self.address_for(uid=uid, attendee_email=attendee_email)


class EncounterWorld:
    """One set of in-memory collaborators the encounter mills share."""

    def __init__(
        self,
        *,
        policy=EncountersPolicy.EVERYONE,
        encounters=(),
        signups=(),
        recent_ips=(),
        users=None,
        invitees=(),
        invited_today=(),
    ):
        self.encounters = FakeEncounters(encounters)
        self.rsvps = FakeRSVPs(signups, recent_ips=recent_ips)
        self.users = FakeUsers(
            users
            if users is not None
            else [make_user(CREATOR_ID), make_user(OTHER_USER_ID)]
        )
        self.invitees = FakeInvitees(
            invitees, users=self.users, rsvps=self.rsvps, invited_today=invited_today
        )
        self.sites = FakeSites(policy)
        self.mailer = FakeMailer()
        self.guests = EncounterGuests(
            rsvps=self.rsvps,
            invitees=self.invitees,
            users=self.users,
            sites=self.sites,
            mailer=self.mailer,
        )

    def service(self):
        return EncounterService(
            transaction=FakeTransaction(),
            encounters=self.encounters,
            rsvps=self.rsvps,
            users=self.users,
            spheres=FakeSpheres(),
            sites=self.sites,
            guests=self.guests,
        )
