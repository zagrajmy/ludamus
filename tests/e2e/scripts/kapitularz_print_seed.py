from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import get_current_timezone

from ludamus.adapters.db.django.models import (
    AgendaItem,
    EnrollmentConfig,
    Event,
    Facilitator,
    Session,
    SessionParticipation,
    Space,
    Sphere,
    TimeSlot,
    Track,
    User,
)
from ludamus.pacts.legacy import SessionParticipationStatus, SessionStatus

EVENT_SLUG = "kapitularz-2025-anonymized"
EVENT_START_HOUR = 10
EXPECTED_SESSION_COUNT = 110
EXPECTED_PARTICIPANT_COUNT = 555
EXTRA_ENROLLMENT_SESSION_COUNT = 5
HOST_COUNT = 72


@dataclass(frozen=True)
class TrackSpec:
    name: str
    slug: str
    space_indexes: tuple[int, ...]


@dataclass(frozen=True)
class SessionSpec:
    day: int
    hour: int
    track_slug: str


SPACE_SPECS = (
    ("Workshop Studio", 24),
    ("Miniature Painting", 18),
    ("RPG Table 1", 5),
    ("RPG Table 2", 5),
    ("RPG Table 3", 5),
    ("RPG Table 4", 5),
    ("RPG Table 5", 5),
    ("RPG Table 6", 5),
    ("RPG Table 7", 5),
    ("RPG Table 8", 5),
    ("RPG Table 9", 5),
    ("Story Tent 1", 6),
    ("Story Tent 2", 6),
    ("Story Tent 3", 6),
    ("Story Tent 4", 6),
    ("Cosplay Forum", 40),
    ("Cosplay Craft", 20),
    ("Cosplay Machines", 12),
    ("Contest Stage", 70),
    ("Publisher Table 1", 8),
    ("Publisher Table 2", 8),
    ("Lecture Room 1", 35),
    ("Lecture Room 2", 35),
    ("Lecture Room 3", 35),
    ("Open Play A", 16),
    ("Open Play B", 16),
)

TRACK_SPECS = (
    TrackSpec("RPG", "rpg", tuple(range(2, 15))),
    TrackSpec("Cosplay", "cosplay", (15, 16, 17, 18)),
    TrackSpec("Workshops", "workshops", (0, 21, 22, 23)),
    TrackSpec("Miniature Painting", "miniature-painting", (1,)),
    TrackSpec("Publisher Tables", "publisher-tables", (19, 20, 24, 25)),
    TrackSpec("Contests", "contests", (18, 21, 22, 23)),
)

DAY_HOUR_COUNTS = (
    (
        0,
        (
            (10, 6),
            (11, 3),
            (12, 2),
            (13, 2),
            (14, 3),
            (16, 3),
            (18, 2),
            (19, 1),
            (20, 1),
        ),
    ),
    (
        1,
        (
            (10, 16),
            (11, 5),
            (12, 4),
            (13, 3),
            (14, 8),
            (15, 1),
            (16, 8),
            (17, 3),
            (18, 5),
            (19, 2),
            (20, 1),
            (22, 1),
        ),
    ),
    (
        2,
        (
            (10, 8),
            (11, 2),
            (12, 2),
            (13, 1),
            (14, 3),
            (15, 1),
            (16, 5),
            (17, 3),
            (18, 4),
            (20, 1),
        ),
    ),
)

TITLE_PARTS = (
    "Clockwork",
    "Lantern",
    "Archive",
    "Signal",
    "Harbor",
    "Foundry",
    "Mosaic",
    "Signal Tower",
    "Orchard",
    "Crossroads",
    "Last Train",
    "Night Market",
)

SESSION_KINDS = (
    "RPG scenario",
    "painting clinic",
    "systems workshop",
    "cosplay lab",
    "design talk",
    "open tournament",
    "publisher demo",
)


def seed_kapitularz_print_event(sphere: Sphere) -> None:
    Event.objects.filter(slug=EVENT_SLUG, sphere=sphere).delete()

    local_tz = get_current_timezone()
    start_day = (timezone.now() + timedelta(days=21)).astimezone(local_tz).date()
    event_start = datetime.combine(start_day, time(10, 0), tzinfo=local_tz)
    event = Event.objects.create(
        sphere=sphere,
        name="Kapitularz 2025 Anonymized",
        slug=EVENT_SLUG,
        description=(
            "Synthetic, anonymized convention-scale programme for print previews. "
            "The fixture preserves the public density of the source event without "
            "keeping host, participant, or session identities."
        ),
        start_time=event_start,
        end_time=event_start + timedelta(days=2, hours=13),
        publication_time=timezone.now() - timedelta(days=2),
    )
    EnrollmentConfig.objects.create(
        event=event,
        start_time=timezone.now() - timedelta(days=1),
        end_time=event.end_time,
        percentage_slots=100,
        allow_anonymous_enrollment=True,
    )

    venue = Space.objects.create(
        event=event,
        parent=None,
        name="Default Venue",
        slug="default-venue",
        description="Anonymized convention venue",
    )
    area = Space.objects.create(
        event=event,
        parent=venue,
        name="Default Area",
        slug="default-area",
        description=(
            "Main programme area with RPG rooms, workshop tables, contest stage, "
            "publisher demos, cosplay stations, and painting desks."
        ),
    )
    spaces = _create_spaces(area)
    tracks = _create_tracks(event, spaces)
    facilitators = _create_facilitators(event)
    participants = _create_participants()
    session_specs = _session_specs()

    _create_time_slots(event, session_specs)
    sessions = _create_sessions(event, tracks, facilitators, session_specs)
    _create_participations(sessions, participants)

    assert len(sessions) == EXPECTED_SESSION_COUNT
    assert len(participants) == EXPECTED_PARTICIPANT_COUNT


def _create_spaces(area: Space) -> list[Space]:
    return [
        Space.objects.create(
            parent=area,
            name=name,
            slug=slugify(name),
            capacity=capacity,
            order=order,
            event=area.event,
        )
        for order, (name, capacity) in enumerate(SPACE_SPECS)
    ]


def _create_tracks(event: Event, spaces: list[Space]) -> dict[str, Track]:
    tracks: dict[str, Track] = {}
    for spec in TRACK_SPECS:
        track = Track.objects.create(
            event=event, name=spec.name, slug=spec.slug, is_public=True
        )
        track.spaces.set(spaces[index] for index in spec.space_indexes)
        tracks[spec.slug] = track
    return tracks


def _create_facilitators(event: Event) -> list[Facilitator]:
    return [
        Facilitator.objects.create(
            event=event, display_name=f"Host {index:03}", slug=f"host-{index:03}"
        )
        for index in range(1, HOST_COUNT + 1)
    ]


def _create_participants() -> list[User]:
    participants = [
        User(
            username=f"kapitularz-participant-{index:03}",
            email=f"participant-{index:03}@example.test",
            name=f"Participant {index:03}",
            slug=f"kapitularz-participant-{index:03}",
            password="",
        )
        for index in range(1, EXPECTED_PARTICIPANT_COUNT + 1)
    ]
    return list(User.objects.bulk_create(participants))


def _session_specs() -> list[SessionSpec]:
    weighted_tracks = (
        "rpg",
        "rpg",
        "rpg",
        "rpg",
        "cosplay",
        "workshops",
        "miniature-painting",
        "publisher-tables",
        "contests",
        "rpg",
    )
    specs: list[SessionSpec] = []
    for day, hour_counts in DAY_HOUR_COUNTS:
        for hour, count in hour_counts:
            for _ in range(count):
                track_slug = weighted_tracks[len(specs) % len(weighted_tracks)]
                specs.append(SessionSpec(day=day, hour=hour, track_slug=track_slug))
    return specs


def _create_time_slots(event: Event, specs: list[SessionSpec]) -> None:
    for day, hour in sorted({(spec.day, spec.hour) for spec in specs}):
        start = event.start_time + timedelta(days=day, hours=hour - EVENT_START_HOUR)
        TimeSlot.objects.create(
            event=event, start_time=start, end_time=start + timedelta(hours=1)
        )


def _create_sessions(
    event: Event,
    tracks: dict[str, Track],
    facilitators: list[Facilitator],
    specs: list[SessionSpec],
) -> list[Session]:
    sessions: list[Session] = []
    for index, spec in enumerate(specs, start=1):
        track = tracks[spec.track_slug]
        track_spaces = list(track.spaces.order_by("order", "name"))
        space = track_spaces[(index - 1) % len(track_spaces)]
        facilitator = facilitators[(index * 7) % len(facilitators)]
        duration_hours = (1, 1, 2, 2, 3)[index % 5]
        title = _title(index, spec.track_slug)
        session = Session.objects.create(
            event=event,
            title=title,
            slug=f"kapitularz-print-session-{index:03}",
            display_name=facilitator.display_name,
            contact_email=f"host-{index:03}@example.test",
            description=_description(index, spec.track_slug),
            requirements="No personal data in this synthetic fixture.",
            needs="Standard table setup.",
            duration=f"PT{duration_hours}H",
            participants_limit=_participants_limit(spec.track_slug, index),
            min_age=(0, 10, 12, 14, 16)[index % 5],
            status=SessionStatus.ACCEPTED,
        )
        session.facilitators.add(facilitator)
        session.tracks.add(track)
        start = event.start_time + timedelta(
            days=spec.day, hours=spec.hour - EVENT_START_HOUR
        )
        AgendaItem.objects.create(
            space=space,
            session=session,
            session_confirmed=True,
            start_time=start,
            end_time=start + timedelta(hours=duration_hours),
        )
        sessions.append(session)
    return sessions


def _title(index: int, track_slug: str) -> str:
    part = TITLE_PARTS[index % len(TITLE_PARTS)]
    kind = SESSION_KINDS[index % len(SESSION_KINDS)]
    track_name = track_slug.replace("-", " ").title()
    return f"{track_name}: {part} {kind} {index:03}"


def _description(index: int, track_slug: str) -> str:
    focus = track_slug.replace("-", " ")
    return (
        f"Synthetic {focus} programme item {index:03}. "
        "Participants get a realistic convention description with goals, "
        "table expectations, pacing notes, and accessibility context. "
        "All host and attendee identities are generated placeholders."
    )


def _participants_limit(track_slug: str, index: int) -> int:
    if track_slug == "contests":
        return 70
    if track_slug in {"workshops", "cosplay"}:
        return (12, 16, 20, 24)[index % 4]
    if track_slug == "miniature-painting":
        return 18
    if track_slug == "publisher-tables":
        return 8
    return (4, 5, 6)[index % 3]


def _create_participations(sessions: list[Session], participants: list[User]) -> None:
    assignments: list[SessionParticipation] = []
    participant_index = 0
    for session_index, session in enumerate(sessions):
        count = 5 + (1 if session_index < EXTRA_ENROLLMENT_SESSION_COUNT else 0)
        for _ in range(count):
            assignments.append(
                SessionParticipation(
                    session=session,
                    user=participants[participant_index],
                    status=SessionParticipationStatus.CONFIRMED,
                )
            )
            participant_index += 1
    SessionParticipation.objects.bulk_create(assignments)
