"""Realistic worst-case data, seeded by ``bootstrap_worst_case.py``.

Imported only after Django is set up, so the models load at the top.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path

from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone
from django.utils.timezone import get_current_timezone

from ludamus.links.db.django.models import (
    AgendaItem,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    Facilitator,
    Notification,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldValue,
    SessionParticipation,
    Space,
    Sphere,
    Track,
    User,
)
from ludamus.pacts import SessionStatus
from ludamus.pacts.legacy import NotificationKind, SessionParticipationStatus

REPO_ROOT = Path(__file__).resolve().parents[3]

LONG_NAME = "Aleksandra Wiśniewska-Kowalczyk"
LONG_EMAIL = "bartholomew.fitzgerald@northwind-industries-holdings.example.com"
# A path the dev server answers with 404, so the avatar's fallback is what
# renders.
DEAD_AVATAR = "http://localhost:8000/static/worst-case/avatar-gone.jpg"
UNREAD_NOTIFICATIONS = 1284

EVENT_NAME = (
    "Międzynarodowy Festiwal Gier Fabularnych, Planszowych i Bitewnych "
    "„Smocza Jama” — Edycja Jubileuszowa XXV"
)
EVENT_DESCRIPTION = (
    "Trzy dni grania w Centrum Kultury w Kędzierzynie-Koźlu.\n\n"
    "Regulamin, mapa dojazdu i harmonogram w PDF: "
    "https://example.com/smocza-jama/2026/dokumenty/regulamin-uczestnictwa-"
    "i-zasady-bezpieczenstwa-v12-final.pdf\n\n"
    "Pytania? Napisz do nas: " + LONG_EMAIL
)
VENUE_NAME = "Centrum Kultury i Sztuki im. Krzysztofa Kamila Baczyńskiego"
VENUE_ADDRESS = "ul. Generała Władysława Andersa 12/14 lok. 3, 47-200 Kędzierzyn-Koźle"
LONG_CATEGORY = "Sesja RPG (scenariusze jednostrzałowe i kampanie)"
LONG_TRACK = "Blok programowy dla dzieci i młodzieży (8–14 lat) z opiekunami"
TAGS = (
    "horror",
    "śledztwo",
    "dla początkujących",
    "18+",
    "lata 20.",
    "Zew Cthulhu 7. edycja",
    "gotowe postacie",
    "sandbox",
    "intryga",
    "walka",
    "Bezpieczeństwo emocjonalne: linie i zasłony (X-card)",
    "po angielsku",
)


def _event(
    sphere: Sphere, *, name: str, slug: str, description: str, days: int
) -> Event:

    now = timezone.now()
    start = datetime.combine(
        (now + timedelta(days=days)).date(), time(10, 0), tzinfo=get_current_timezone()
    )
    event = Event.objects.create(
        sphere=sphere,
        name=name,
        slug=slug,
        description=description,
        start_time=start,
        end_time=start + timedelta(hours=34),
        publication_time=now - timedelta(days=1),
        proposal_start_time=now - timedelta(days=1),
        proposal_end_time=now + timedelta(days=7),
    )
    EnrollmentConfig.objects.create(
        event=event,
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=7),
        percentage_slots=100,
        banner_text=(
            "Zapisy otwarte do niedzieli do 23:59. Na sesje dla dzieci zapisuje "
            "opiekun, a dziecko musi mieć ukończone 8 lat w dniu wydarzenia."
        ),
    )
    return event


def _scheduled(
    *,
    event: Event,
    space: Space,
    title: str,
    slug: str,
    facilitator: str,
    hour: int,
    hours: int = 2,
    seats: int = 6,
    min_age: int = 0,
    description: str = "",
) -> Session:

    session = Session.objects.create(
        event=event,
        facilitator_name=facilitator,
        title=title,
        slug=slug,
        description=description,
        participants_limit=seats,
        min_age=min_age,
        status=SessionStatus.ACCEPTED,
        schedule_confirmed=True,
    )
    AgendaItem.objects.create(
        space=space,
        session=session,
        session_confirmed=True,
        start_time=event.start_time + timedelta(hours=hour),
        end_time=event.start_time + timedelta(hours=hour + hours),
    )
    facilitator_row, _ = Facilitator.objects.get_or_create(
        event=event, slug=slug[:50], defaults={"display_name": facilitator}
    )
    session.facilitators.add(facilitator_row)
    return session


def _worst_user() -> User:

    user = User.objects.create_user(
        username="e2e-worst",
        email=LONG_EMAIL,
        password="e2e-worst-123",
        name=LONG_NAME,
        slug="e2e-worst",
        avatar_url=DEAD_AVATAR,
    )
    Notification.objects.bulk_create(
        Notification(
            recipient=user,
            kind=NotificationKind.WAITLIST_PROMOTED.value,
            title=(
                "Zwolniło się miejsce: Zew Cthulhu: Maski Nyarlathotepa — "
                "kampania jednostrzałowa dla początkujących i zaawansowanych "
                "badaczy tajemnic"
            ),
            body="Masz potwierdzone miejsce. Jeśli nie możesz przyjść, zwolnij je.",
            url="/events/",
        )
        for _ in range(UNREAD_NOTIFICATIONS)
    )
    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()
    (REPO_ROOT / "tests" / "e2e" / ".auth-state-worst.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "sessionid",
                        "value": session.session_key,
                        "domain": "localhost",
                        "path": "/",
                        "httpOnly": True,
                        "secure": False,
                        "sameSite": "Lax",
                    }
                ],
                "origins": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return user


def _tags(event: Event, sessions: list[Session]) -> None:

    field = SessionField.objects.create(
        event=event,
        name="Tagi",
        question="Czego mogą się spodziewać gracze?",
        slug="tagi",
        field_type="select",
        is_multiple=True,
        allow_custom=True,
        is_public=True,
        icon="tag",
    )
    for order, tag in enumerate(TAGS):
        SessionFieldOption.objects.create(
            field=field, value=tag, label=tag, order=order
        )
    SessionFieldValue.objects.create(session=sessions[0], field=field, value=list(TAGS))
    SessionFieldValue.objects.create(session=sessions[1], field=field, value=["18+"])


def _worst_case_event(sphere: Sphere, user: User) -> None:

    event = _event(
        sphere,
        name=EVENT_NAME,
        slug="worst-case",
        description=EVENT_DESCRIPTION,
        days=3,
    )
    venue = Space.objects.create(
        event=event, name=VENUE_NAME, slug="centrum-kultury", description=VENUE_ADDRESS
    )
    hall = Space.objects.create(
        event=event,
        parent=venue,
        name="Sala Widowiskowo-Konferencyjna",
        slug="sala-widowiskowa",
    )
    room_long = Space.objects.create(
        event=event,
        parent=hall,
        name="Sala nr 12 (I piętro, wejście od dziedzińca, obok szatni)",
        slug="sala-12",
        capacity=1284,
    )
    room_short = Space.objects.create(
        event=event, parent=hall, name="B", slug="b", capacity=1
    )
    room_unsized = Space.objects.create(
        event=event, parent=venue, name="Hol", slug="hol", capacity=None
    )

    category = ProposalCategory.objects.create(
        event=event, name=LONG_CATEGORY, slug="sesja-rpg"
    )
    short_category = ProposalCategory.objects.create(
        event=event, name="LARP", slug="larp"
    )
    track = Track.objects.create(event=event, name=LONG_TRACK, slug="dzieci")
    track.spaces.set([room_long, room_short])

    cthulhu = _scheduled(
        event=event,
        space=room_long,
        title=(
            "Zew Cthulhu: Maski Nyarlathotepa — kampania jednostrzałowa dla "
            "początkujących i zaawansowanych badaczy tajemnic"
        ),
        slug="maski-nyarlathotepa",
        facilitator=LONG_NAME,
        hour=1,
        hours=4,
        seats=1,
        min_age=18,
        description=EVENT_DESCRIPTION,
    )
    go = _scheduled(
        event=event,
        space=room_short,
        title="Go",
        slug="go",
        facilitator="Jo",
        hour=1,
        seats=1284,
    )
    emailed = _scheduled(
        event=event,
        space=room_unsized,
        title="Warsztaty malowania figurek",
        slug="malowanie-figurek",
        facilitator=LONG_EMAIL,
        hour=1,
    )
    markup = _scheduled(
        event=event,
        space=room_long,
        title="<script>alert(1)</script> & **Kości** w <b>ogniu</b>",
        slug="markup",
        facilitator="王秀英",
        hour=6,
    )
    _scheduled(
        event=event,
        space=room_short,
        title="🦊 Lisie opowieści",
        slug="lisie-opowiesci",
        facilitator="Đặng Thị Ngọc Hân",
        hour=6,
        seats=0,
    )
    rtl = _scheduled(
        event=event,
        space=room_unsized,
        title="Benachrichtigungseinstellungen: kooperacyjna gra w biurokrację",
        slug="biurokracja",
        facilitator="نور الهدى عبد الرحمن",
        hour=6,
    )
    crowded = _scheduled(
        event=event,
        space=room_long,
        title="Turniej Magic: The Gathering",
        slug="turniej-mtg",
        facilitator="Christopher Alexander Montgomery III",
        hour=24,
        hours=10,
    )
    for name in (
        "Konstantin Oberhauser-Wettstein",
        "Seán O'Brien-Ó Súilleabháin",
        "María José de la Cruz y Fernández",
        "J",
    ):
        crowded.facilitators.add(
            Facilitator.objects.create(
                event=event,
                display_name=name,
                slug=name.lower().replace(" ", "-").replace("'", "")[:50],
            )
        )

    cthulhu.category = category
    rtl.category = short_category
    for session in (cthulhu, rtl):
        session.save(update_fields=["category"])
    cthulhu.tracks.add(track)
    go.tracks.add(track)
    _tags(event, [cthulhu, go])

    SessionParticipation.objects.create(
        session=cthulhu, user=user, status=SessionParticipationStatus.CONFIRMED.value
    )
    for session in (go, markup, emailed):
        SessionParticipation.objects.create(
            session=session,
            user=user,
            status=SessionParticipationStatus.CONFIRMED.value,
        )

    for title, facilitator in (
        (
            (
                "Q3 Board Deck — FINAL (revised) v12 [approved by legal]: gra o "
                "korporacji, w której wszyscy są na spotkaniu"
            ),
            LONG_NAME,
        ),
        ("?", "J"),
    ):
        Session.objects.create(
            event=event,
            presenter=user,
            facilitator_name=facilitator,
            contact_email=LONG_EMAIL,
            category=category,
            title=title,
            slug=f"proposal-{len(title)}",
            description="",
            duration="PT4H",
            participants_limit=1,
            min_age=0,
            status=SessionStatus.PENDING,
        )

    Encounter.objects.create(
        sphere=sphere,
        creator=user,
        title=(
            "Wieczór z planszówkami u Aleksandry — przynieście swoje gry, "
            "przekąski zapewniam, parking pod blokiem"
        ),
        description=EVENT_DESCRIPTION,
        game="Twilight Imperium: Fourth Edition — Prophecy of Kings",
        start_time=timezone.now() + timedelta(days=4, hours=6),
        end_time=timezone.now() + timedelta(days=5, hours=2),
        place=VENUE_ADDRESS,
        max_participants=1,
        share_code="WORST1",
    )
    jo_encounter = Encounter.objects.create(
        sphere=sphere,
        creator=user,
        title="Go",
        game="",
        start_time=timezone.now() + timedelta(days=5),
        place="",
        max_participants=0,
        share_code="WORST2",
    )
    EncounterRSVP.objects.create(encounter=jo_encounter, user=user)


def _one_event(sphere: Sphere, user: User) -> None:

    event = _event(sphere, name="Gra", slug="worst-case-one", description="", days=4)
    venue = Space.objects.create(event=event, name="Dom", slug="dom", capacity=1)
    session = _scheduled(
        event=event,
        space=venue,
        title="Jedna sesja",
        slug="jedna",
        facilitator="Jo",
        hour=1,
        seats=1,
    )
    SessionParticipation.objects.create(
        session=session, user=user, status=SessionParticipationStatus.CONFIRMED.value
    )


def _empty_event(sphere: Sphere) -> None:
    _event(sphere, name="Pusto", slug="worst-case-empty", description="", days=5)


def seed() -> None:

    sphere = Event.objects.get(slug="autumn-open").sphere
    user = _worst_user()
    _worst_case_event(sphere, user)
    _one_event(sphere, user)
    _empty_event(sphere)
    sphere.managers.add(user)
    print("Seeded worst-case, worst-case-one and worst-case-empty events.")
