#!/usr/bin/env python3
"""Seed deterministic data for Playwright end-to-end tests."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# pylint: disable=wrong-import-position  # Django imports must be after setup
import django  # noqa: E402

django.setup()

from urllib.parse import urlparse  # noqa: E402

from django.conf import settings  # noqa: E402
from django.contrib.flatpages.models import FlatPage  # noqa: E402
from django.contrib.sessions.backends.db import SessionStore  # noqa: E402
from django.contrib.sites.models import Site  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402
from django.utils.timezone import get_current_timezone  # noqa: E402

from ludamus.adapters.db.django.models import (  # noqa: E402
    AgendaItem,
    Area,
    Encounter,
    EnrollmentConfig,
    Event,
    Notification,
    ProposalCategory,
    Session,
    SessionParticipation,
    Space,
    Sphere,
    TimeSlot,
    User,
    Venue,
)
from ludamus.pacts import SessionStatus  # noqa: E402
from ludamus.pacts.legacy import (  # noqa: E402
    NotificationKind,
    SessionParticipationStatus,
)


def _create_site(domain: str, *, name: str) -> tuple[Site, Sphere]:
    site, _ = Site.objects.get_or_create(domain=domain, defaults={"name": name})
    # Site has a one-to-one Sphere; look it up by site to avoid unique clashes
    sphere, _ = Sphere.objects.get_or_create(
        site=site, defaults={"name": f"{name} Sphere"}
    )
    return site, sphere


def _ensure_spheres_for_all_sites() -> None:
    """Backfill spheres for any sites created outside this script.

    Playwright hits whatever host the web server exposes (often with a port),
    so we guarantee every Site row has a Sphere to keep RootDAO happy.
    """
    for site in Site.objects.filter(sphere__isnull=True):
        Sphere.objects.create(site=site, name=site.name or site.domain)


def _create_event(
    sphere: Sphere,
    *,
    name: str,
    slug: str,
    description: str,
    start_offset: timedelta,
    duration_hours: int,
    publication_offset: timedelta,
    enrollment_banner: str | None = None,
    allow_anonymous: bool = False,
    proposals_open: bool = False,
) -> Event:
    now = timezone.now()
    # Pin start to 10:00 local time on the target day so tests don't
    # break when CI runs in the evening and times wrap past midnight.
    target_day = (now + start_offset).date()
    local_tz = get_current_timezone()
    start = datetime.combine(target_day, time(10, 0), tzinfo=local_tz)
    end = start + timedelta(hours=duration_hours)
    event = Event.objects.create(
        sphere=sphere,
        name=name,
        slug=slug,
        description=description,
        start_time=start,
        end_time=end,
        publication_time=now - publication_offset,
        **(
            {
                "proposal_start_time": now - timedelta(days=1),
                "proposal_end_time": now + timedelta(days=7),
            }
            if proposals_open
            else {}
        ),
    )

    if enrollment_banner:
        EnrollmentConfig.objects.create(
            event=event,
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=7),
            percentage_slots=100,
            banner_text=enrollment_banner,
            allow_anonymous_enrollment=allow_anonymous,
        )

    return event


def _create_flatpage(site: Site, *, url: str, title: str, content: str) -> FlatPage:
    page, _ = FlatPage.objects.get_or_create(
        url=url, defaults={"title": title, "content": content}
    )
    page.sites.add(site)
    return page


def _create_venue(event: Event, *, name: str, slug: str, address: str = "") -> Venue:
    return Venue.objects.create(event=event, name=name, slug=slug, address=address)


def _create_area(venue: Venue, *, name: str, slug: str, description: str = "") -> Area:
    return Area.objects.create(
        venue=venue, name=name, slug=slug, description=description
    )


def _create_space(
    area: Area, *, name: str, slug: str, capacity: int | None = None
) -> Space:
    return Space.objects.create(area=area, name=name, slug=slug, capacity=capacity)


def _create_session(
    sphere: Sphere,
    event: Event,
    space: Space,
    *,
    title: str,
    slug: str,
    presenter: str,
    description: str,
    start_offset: timedelta,
    duration_hours: int,
) -> Session:
    session = Session.objects.create(
        sphere=sphere,
        display_name=presenter,
        title=title,
        slug=slug,
        description=description,
        participants_limit=24,
        min_age=10,
    )
    AgendaItem.objects.create(
        space=space,
        session=session,
        session_confirmed=True,
        start_time=event.start_time + start_offset,
        end_time=event.start_time + start_offset + timedelta(hours=duration_hours),
    )
    return session


def _write_storage_state(user: User, *, domain: str, path: Path) -> None:
    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session["_auth_user_hash"] = user.get_session_auth_hash()
    session.create()

    storage_state = {
        "cookies": [
            {
                "name": "sessionid",
                "value": session.session_key,
                "domain": domain,
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }
    path.write_text(json.dumps(storage_state, indent=2), encoding="utf-8")


def _create_test_user() -> User:
    """Create a test user and persist a session cookie file for Playwright.

    Returns:
        The created User instance.
    """
    user = User.objects.create_user(
        username="e2e-tester",
        email="e2e@test.local",
        password="e2e-password-123",
        name="E2E Tester",
        slug="e2e-tester",
        avatar_url="https://i.pravatar.cc/96?u=e2e",
    )

    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    parsed = urlparse(base_url)
    domain = parsed.hostname or "localhost"
    state_path = REPO_ROOT / "tests" / "e2e" / ".auth-state.json"
    _write_storage_state(user, domain=domain, path=state_path)

    # An unread notification so the navbar dropdown has content to show in e2e.
    Notification.objects.create(
        recipient=user,
        kind=NotificationKind.WAITLIST_PROMOTED.value,
        title="You're in: a spot opened in Dragons & Dungeons",
        body="A confirmed spot opened up and you have been enrolled automatically.",
        url="/events/",
    )

    return user


def _create_promotion_scenario(sphere: Sphere, *, superuser: User) -> None:
    """Seed a full session with a dedicated waiter behind the superuser.

    Cancelling the superuser's confirmed seat (T1) frees a seat and promotes the
    waiter, exercising the waiting-list promotion + notification path end to end.
    The waiter is its own user (not the shared e2e-tester) so the notification
    state stays isolated from other specs.
    """
    event = _create_event(
        sphere,
        name="Waitlist Demo Convention",
        slug="waitlist-demo",
        description="Promotion end-to-end scenario.",
        start_offset=timedelta(days=30),
        duration_hours=8,
        publication_offset=timedelta(days=1),
        enrollment_banner="Enrollment is open",
    )
    venue = _create_venue(event, name="Demo Venue", slug="demo-venue")
    area = _create_area(venue, name="Demo Area", slug="demo-area")
    space = _create_space(area, name="Demo Room", slug="demo-room", capacity=1)
    session = Session.objects.create(
        sphere=sphere,
        display_name="Demo GM",
        title="Waitlist Promotion Demo",
        slug="waitlist-promotion-demo",
        description="A full session used by the promotion e2e.",
        participants_limit=1,
        min_age=0,
    )
    AgendaItem.objects.create(
        space=space,
        session=session,
        session_confirmed=True,
        start_time=event.start_time,
        end_time=event.start_time + timedelta(hours=2),
    )
    waiter = User.objects.create_user(
        username="e2e-waiter",
        email="e2e-waiter@test.local",
        password="e2e-waiter-123",
        name="E2E Waiter",
        slug="e2e-waiter",
    )
    SessionParticipation.objects.create(
        session=session,
        user=superuser,
        status=SessionParticipationStatus.CONFIRMED.value,
    )
    SessionParticipation.objects.create(
        session=session, user=waiter, status=SessionParticipationStatus.WAITING.value
    )

    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    parsed = urlparse(base_url)
    _write_storage_state(
        waiter,
        domain=parsed.hostname or "localhost",
        path=REPO_ROOT / "tests" / "e2e" / ".auth-state-waiter.json",
    )

    scenario_path = REPO_ROOT / "tests" / "e2e" / ".promotion-scenario.json"
    scenario_path.write_text(
        json.dumps(
            {
                "session_id": session.pk,
                "superuser_id": superuser.pk,
                "waiter_email": waiter.email,
                "session_title": session.title,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    call_command("flush", verbosity=0, interactive=False)

    # Root site used for fallbacks / redirects
    root_domain = os.environ.get("ROOT_DOMAIN", settings.ROOT_DOMAIN)
    _create_site(root_domain, name="Root Domain")

    sphere_domain = os.environ.get("E2E_SPHERE_DOMAIN") or os.environ.get("E2E_HOST")
    if not sphere_domain:
        sphere_domain = "localhost:8000"
    site, sphere = _create_site(sphere_domain, name="E2E Test")

    _ensure_spheres_for_all_sites()

    # Test user for authenticated e2e tests
    _create_test_user()

    superuser = User.objects.create_superuser(
        username="e2e-superuser",
        email="e2e-superuser@test.local",
        password="e2e-superuser-123",
        name="E2E Superuser",
        slug="e2e-superuser",
    )
    base_url = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
    parsed = urlparse(base_url)
    superuser_state_path = REPO_ROOT / "tests" / "e2e" / ".auth-state-superuser.json"
    _write_storage_state(
        superuser, domain=parsed.hostname or "localhost", path=superuser_state_path
    )

    # Full session with a dedicated waiter, for the promotion e2e.
    _create_promotion_scenario(sphere, superuser=superuser)

    # Staff manager user for panel e2e tests (logs in via /admin/)
    manager = User.objects.create_user(
        username="e2e-manager",
        email="e2e-manager@test.local",
        password="e2e-manager-123",
        name="E2E Manager",
        slug="e2e-manager",
        is_staff=True,
    )
    sphere.managers.add(manager)

    # Second sphere with NO events — used to test panel redirect
    _, empty_sphere = _create_site("another.localhost:8000", name="Empty Sphere")
    empty_manager = User.objects.create_user(
        username="e2e-manager-empty",
        email="e2e-manager-empty@test.local",
        password="e2e-manager-empty-123",
        name="E2E Manager Empty",
        slug="e2e-manager-empty",
        is_staff=True,
    )
    empty_sphere.managers.add(empty_manager)

    # Persist a session for the empty-sphere manager (cookie-based login)
    empty_session = SessionStore()
    empty_session["_auth_user_id"] = str(empty_manager.pk)
    empty_session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    empty_session["_auth_user_hash"] = empty_manager.get_session_auth_hash()
    empty_session.create()

    empty_state = {
        "cookies": [
            {
                "name": "sessionid",
                "value": empty_session.session_key,
                "domain": "another.localhost",
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }
    empty_state_path = REPO_ROOT / "tests" / "e2e" / ".auth-state-empty.json"
    empty_state_path.write_text(json.dumps(empty_state, indent=2))

    # Flatpages
    _create_flatpage(
        site,
        url="/about/",
        title="About Ludamus",
        content=(
            "<p>Ludamus is a community platform for tabletop gaming events.</p>"
            "<h3>What we offer</h3>"
            "<ul>"
            "<li>Event scheduling and management</li>"
            "<li>Session proposals from game masters</li>"
            "<li>Player enrollment system</li>"
            "<li>Anonymous participation options</li>"
            "</ul>"
            "<h3>Our Mission</h3>"
            "<p>We believe that tabletop gaming brings people together. "
            "Whether you're rolling dice in a dungeon crawl, negotiating trades "
            "in a strategy game, or weaving stories in a narrative RPG, "
            "we're here to help you find your table.</p>"
        ),
    )

    upcoming_event = _create_event(
        sphere,
        name="Autumn Open Playtest",
        slug="autumn-open",
        description=(
            "A cozy meetup packed with prototypes, mentors, and hands-on demos.\n"
            "Bring dice, meeples, and curiosity!"
        ),
        start_offset=timedelta(days=1),
        # Span two days so the event encloses its day-2 session (below) and the
        # day/hour filters have more than one day to work with.
        duration_hours=28,
        publication_offset=timedelta(days=2),
        enrollment_banner="Enrollment is open—grab a slot before we fill up!",
        allow_anonymous=True,
        proposals_open=True,
    )

    # Create venue hierarchy for the upcoming event
    main_venue = _create_venue(
        upcoming_event,
        name="Convention Center",
        slug="convention-center",
        address="123 Gaming Street, Tabletop City",
    )

    main_hall_area = _create_area(
        main_venue,
        name="Main Hall",
        slug="main-hall",
        description="The central gaming area with multiple tables.",
    )

    lounge_area = _create_area(
        main_venue,
        name="Lounge",
        slug="lounge",
        description="A cozy space for smaller gatherings.",
    )

    east_wing_space = _create_space(
        main_hall_area, name="East Wing", slug="east-wing", capacity=30
    )

    fireside_space = _create_space(
        lounge_area, name="Fireside Alcove", slug="fireside-alcove", capacity=12
    )

    tester = User.objects.get(username="e2e-tester")

    _create_session(
        sphere,
        upcoming_event,
        east_wing_space,
        title="Mega Strategy Lab",
        slug="mega-strategy",
        presenter="Alex Morgan",
        description="Deep dive into asymmetric mechanics and pacing tricks.",
        start_offset=timedelta(hours=1),
        duration_hours=2,
    )

    _create_session(
        sphere,
        upcoming_event,
        fireside_space,
        title="Cozy Storytellers Circle",
        slug="story-circle",
        presenter="Priya Chen",
        description="Collaborative narrative building with lightweight prompts.",
        start_offset=timedelta(hours=2),
        duration_hours=1,
    )

    _create_session(
        sphere,
        upcoming_event,
        fireside_space,
        title="Przygoda w Mieście Neonów",
        slug="neon-city-adventure",
        presenter="Radek Włodarczyk",
        description=(
            'Przygoda w stylu filmu "Jumanji". Na strychu znajdujecie grę '
            "komputerową z lat 90 o wojnach gangów w cyberpunkowym Mieście "
            "Neonów. Gdy próbujecie w nią zagrać, gra wciąga was w swój "
            "wirtualny świat, gdzie jako wybrane postaci zmierzycie się z "
            "okrutnym Bossem Akimurą i jego armią cyberninja."
        ),
        # Scheduled on the event's second day so the day/hour filters appear.
        start_offset=timedelta(days=1, hours=1),
        duration_hours=1,
    )

    proposal_category = ProposalCategory.objects.create(
        event=upcoming_event,
        name="RPG Proposals",
        slug="rpg-proposals",
        min_participants_limit=1,
        max_participants_limit=6,
        durations=["PT1H"],
    )
    proposal_slot = TimeSlot.objects.create(
        event=upcoming_event,
        start_time=upcoming_event.start_time + timedelta(hours=1),
        end_time=upcoming_event.start_time + timedelta(hours=2),
    )
    pending_session = Session.objects.create(
        sphere=sphere,
        presenter=tester,
        display_name="E2E Tester",
        contact_email="e2e@test.local",
        category=proposal_category,
        title="Pending Neon Proposal",
        slug="pending-neon-proposal",
        description="Proposal review modal content used by e2e tests.",
        requirements="Bring a charged phone.",
        needs="Quiet corner preferred.",
        duration="PT1H",
        participants_limit=4,
        min_age=12,
        status=SessionStatus.PENDING,
    )
    pending_session.time_slots.add(proposal_slot)

    past_event = _create_event(
        sphere,
        name="Retro Mini Jam",
        slug="retro-mini-jam",
        description="Weekend jam focused on 8-bit vibes and tactile puzzlers.",
        start_offset=timedelta(days=-7),
        duration_hours=6,
        publication_offset=timedelta(days=8),
    )

    # Create venue hierarchy for the past event
    retro_venue = _create_venue(
        past_event,
        name="Arcade Hall",
        slug="arcade-hall",
        address="456 Pixel Lane, Retro Town",
    )

    arcade_area = _create_area(
        retro_venue,
        name="Main Arcade Floor",
        slug="main-floor",
        description="Classic arcade machines and gaming tables.",
    )

    _create_space(arcade_area, name="Puzzle Corner", slug="puzzle-corner", capacity=8)

    # Seed encounter owned by the e2e-tester user. Used by e2e tests covering
    # the organizer-only QR-share dialog on the notice-board encounter detail.
    Encounter.objects.create(
        sphere=sphere,
        creator=tester,
        title="Backyard Tactics Night",
        description="Casual evening of light wargames and snacks.",
        game="Memoir '44",
        start_time=timezone.now() + timedelta(days=2, hours=8),
        end_time=timezone.now() + timedelta(days=2, hours=11),
        place="Tester's place",
        max_participants=4,
        share_code="ENCQR1",
    )


if __name__ == "__main__":
    main()
