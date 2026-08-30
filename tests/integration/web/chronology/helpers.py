"""Shared arrange helpers for chronology integration tests."""

from dataclasses import replace
from unittest.mock import ANY

from django.utils.timezone import localtime

from ludamus.gates.web.django.chronology.enrollment_presentation import (
    PartyMemberFlags,
    SessionUserParticipationData,
)
from ludamus.gates.web.django.chronology.event_presentation import (
    ParticipationInfo,
    SessionData,
)
from ludamus.gates.web.django.chronology.schedule import (
    ScheduleDay,
    ScheduleHour,
    ScheduleTile,
    build_card_days,
)
from ludamus.gates.web.django.entities import UserInfo
from ludamus.links.db.django.models import SessionParticipation
from ludamus.links.db.django.repositories.chronology import location_data
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import (
    NO_LOCATION,
    AgendaItemDTO,
    SessionDTO,
    SessionParticipationStatus,
    TimeSlotDTO,
)
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.party import (
    EnrollmentPartyChoiceDTO,
    EnrollmentPartyMemberDTO,
    PartyConsentMode,
    PartyMembershipStatus,
    SelectedEnrollmentPartyDTO,
)
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import RequestTimeMatcher


def session_card(agenda_item, *, presenter, **overrides):
    # The event page's per-session card. Callers override only what their
    # scenario changes; the rest is an unenrolled, not-yet-open session.
    session = agenda_item.session
    space = agenda_item.space
    # Built and then `replace`d rather than merged as dicts: a field renamed on
    # `SessionData` then fails here, in one place, instead of in every caller.
    card = SessionData(
        agenda_item=AgendaItemDTO.model_validate(agenda_item),
        effective_participants_limit=session.participants_limit,
        enrolled_count=0,
        is_enrollment_available=False,
        is_full=False,
        is_ongoing=False,
        presenter=UserInfo.from_user_dto(
            UserDTO.model_validate(presenter), gravatar_url=gravatar_url
        ),
        session_participations=[],
        session=SessionDTO.model_validate(session),
        should_show_as_inactive=False,
        loc=location_data(space),
        user_enrolled=False,
        user_waiting=False,
    )
    return replace(card, **overrides)


def proposal_card(session, *, presenter, slots=(), **overrides):
    # A pending proposal's card: the same component as session_card, minus
    # everything an agenda item supplies — no time, no space, nothing to enroll
    # in — plus the slots the author would accept.
    # `slots` is stated by the caller, in the order the card should show them,
    # rather than re-read from the session: an expectation that re-runs the
    # production query cannot catch that query ordering wrongly.
    card = SessionData(
        agenda_item=None,
        category_name=session.category.name if session.category else "",
        effective_participants_limit=session.participants_limit,
        enrolled_count=0,
        is_enrollment_available=False,
        is_full=False,
        loc=NO_LOCATION,
        preferred_time_slots=[TimeSlotDTO.model_validate(slot) for slot in slots],
        presenter=UserInfo.from_user_dto(
            UserDTO.model_validate(presenter), gravatar_url=gravatar_url
        ),
        session=SessionDTO.model_validate(session),
        session_participations=[],
    )
    return replace(card, **overrides)


def schedule_context(url):
    # The compact-schedule context keys shared by every card-layout response;
    # splatted into the exact-equality context assertions so adding a key is a
    # one-line change instead of a 36-site sweep.
    return {
        "compact_schedule": False,
        "schedule_days": [],
        "active_tab": "list",
        "room_lanes": None,
        "schedule_list_url": url,
        "schedule_rooms_url": f"{url}?view=rooms",
    }


def event_page_context(event, *, url, **overrides):
    # Every key the event page renders with, defaulted to an event with no
    # schedule. `url` is the page's own path, which the view echoes back as the
    # list/rooms view links.
    # Callers keep stating their scenario through the three availability lanes;
    # the page itself renders from the day-major grouping built from them.
    ended = overrides.pop("ended_hour_data", {})
    current = overrides.pop("current_hour_data", {})
    future_unavailable = overrides.pop("future_unavailable_hour_data", {})
    context = {
        "enrollment_requires_slots": False,
        "event": event,
        "filterable_tag_categories": [],
        "track_filter_names": [],
        "category_filter_names": [],
        "hour_data": {},
        "object": event,
        "pending_review_visible": False,
        "pending_sessions": [],
        "pending_wizard_view": False,
        "own_pending_proposals": [],
        "sessions": [],
        "user_enrollment_config": None,
        "total_enrolled": 0,
        "user_enrolled_sessions": [],
        "event_banned": False,
        **schedule_context(url),
        "user_enrolled_session_titles": [],
        "view": ANY,
    }
    context |= overrides
    context.setdefault("has_enrollable_sessions", False)
    context.setdefault("scheduled_count", 0)
    context.setdefault(
        "card_days",
        build_card_days(
            ended=ended, current=current, future_unavailable=future_unavailable
        ),
    )
    return context


def compact_day(cards):
    # The compact schedule's single day: one hour bucket holding every card,
    # plus a tile per card. Fixtures that schedule everything in one hour.
    starts = [localtime(card.agenda_item.start_time) for card in cards]
    hour_start = starts[0].replace(minute=0, second=0, microsecond=0)
    tiles = [
        ScheduleTile(
            data=card,
            start=localtime(card.agenda_item.start_time),
            end=localtime(card.agenda_item.end_time),
        )
        for card in cards
    ]
    return ScheduleDay(
        day_start=hour_start,
        hours=[ScheduleHour(start=hour_start, tiles=tiles)],
        tiles=tiles,
    )


def party_context(party=None, *, leader_name="", members=()):
    # The enroll page's party plumbing. The default is a viewer who is in no
    # party at all; a scenario that gives them one they lead states the pills
    # the page should show, rather than asking the service the view asks.
    if party is None:
        return {"party_choices": [], "selected_party": None}
    pill = {
        "pk": party.pk,
        "name": party.name,
        "leader_name": leader_name,
        "is_own_led": True,
    }
    return {
        "party_choices": [EnrollmentPartyChoiceDTO(**pill)],
        "selected_party": SelectedEnrollmentPartyDTO(**pill, members=list(members)),
    }


def party_member(
    user,
    *,
    is_leader=False,
    is_login_less=False,
    consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
    status=PartyMembershipStatus.ACTIVE,
):
    # A row of the selected party. The leader comes first, which is the order
    # the page lists them in.
    return EnrollmentPartyMemberDTO(
        user_pk=user.pk,
        name=user.name,
        slug=user.slug,
        is_login_less=is_login_less,
        is_leader=is_leader,
        consent_mode=consent_mode,
        status=status,
    )


def participation_row(
    user,
    *,
    user_enrolled=False,
    user_waiting=False,
    seat_held=False,
    offer_pending=False,
    has_time_conflict=False,
    is_member=False,
    needs_accept=False,
    blocked=False,
):
    return SessionUserParticipationData(
        user=UserDTO.model_validate(user),
        user_enrolled=user_enrolled,
        user_waiting=user_waiting,
        seat_held=seat_held,
        offer_pending=offer_pending,
        has_time_conflict=has_time_conflict,
        membership=PartyMemberFlags(
            is_member=is_member, needs_accept=needs_accept, blocked=blocked
        ),
    )


def enroll_context(
    *,
    session,
    user_data,
    companions=(),
    shadowban_warnings=(),
    party_choices=(),
    selected_party=None,
):
    return {
        # The two party keys, as `party_context` spells them: a caller with a
        # party splices its result straight in.
        "party_choices": list(party_choices),
        "selected_party": selected_party,
        "companions": list(companions),
        "event": session.event,
        "form": ANY,
        "session": session,
        "shadowban_warnings": list(shadowban_warnings),
        "user_data": user_data,
    }


def enroll_page_context(*, viewer, agenda_item, **overrides):
    # The enroll page as it renders for a viewer with no companions, no party
    # and no participation yet.
    return (
        enroll_context(
            session=agenda_item.session, user_data=[participation_row(viewer)]
        )
        | overrides
    )


def make_half_full_session(event, *, participants_limit=2):
    # A scheduled session with one confirmed and one offered seat, so the
    # offered seat is what pushes it to full. The seats come back with it: a
    # caller stating the roster needs the people, not another query.
    space = SpaceFactory(event=event)
    session = SessionFactory(
        event=event, category=None, participants_limit=participants_limit
    )
    AgendaItemFactory(session=session, space=space)
    seats = [
        SessionParticipation.objects.create(
            session=session, user=UserFactory(), status=status
        )
        for status in (
            SessionParticipationStatus.CONFIRMED,
            SessionParticipationStatus.OFFERED,
        )
    ]
    return session, seats


SIMULACRA_NAMES = ("Aleksandra Nowak", "Piotr Kowalski", "Maria Wiśniewska")
# There is no one behind a simulacrum: no avatar, no handle, nothing to click
# through to.
NO_PROFILE = {"avatar_url": None, "discord_username": "", "slug": "", "username": ""}


def simulacra():
    # The invented seat-holders a pretend-full card shows instead of the real
    # roster: negative pks, and a `creation_time` minted while the request runs.
    return [
        ParticipationInfo(
            user=UserInfo(name=name, full_name=name, pk=-index - 1, **NO_PROFILE),
            status=SessionParticipationStatus.CONFIRMED.value,
            creation_time=RequestTimeMatcher(),
        )
        for index, name in enumerate(SIMULACRA_NAMES)
    ]


def masked_card(agenda_item, *, presenter, seats, **overrides):
    # The card a banned viewer gets in place of the real one. It has to be
    # indistinguishable from a genuinely full session — every seat taken, and
    # enrollment open, because a session that takes none would never have been
    # full — so the caller states the whole disguise rather than the flag.
    return session_card(
        agenda_item,
        presenter=presenter,
        session=SessionDTO.model_validate(agenda_item.session).model_copy(
            update={"participants_limit": seats}
        ),
        effective_participants_limit=seats,
        enrolled_count=seats,
        is_full=True,
        is_enrollment_available=True,
        pretend_full=True,
        session_participations=simulacra(),
        **overrides,
    )
