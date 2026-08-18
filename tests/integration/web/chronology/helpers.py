"""Shared arrange helpers for chronology integration tests."""

from dataclasses import replace
from unittest.mock import ANY

from django.utils.timezone import localtime

from ludamus.gates.web.django.chronology.enrollment_presentation import (
    PartyMemberFlags,
    SessionUserParticipationData,
)
from ludamus.gates.web.django.chronology.event_presentation import SessionData
from ludamus.gates.web.django.chronology.schedule import (
    ScheduleDay,
    ScheduleHour,
    ScheduleTile,
)
from ludamus.gates.web.django.entities import UserInfo
from ludamus.links.db.django.models import SessionParticipation
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import (
    AgendaItemDTO,
    LocationData,
    SessionDTO,
    SessionParticipationStatus,
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
        loc=LocationData(
            space_name=space.name,
            parent_slug=space.parent.slug if space.parent else "",
            parent_name=space.parent.name if space.parent else "",
            path=str(space),
        ),
        user_enrolled=False,
        user_waiting=False,
    )
    return replace(card, **overrides)


def schedule_context(url):
    # The compact-schedule context keys shared by every card-layout response;
    # splatted into the exact-equality context assertions so adding a key is a
    # one-line change instead of a 36-site sweep.
    return {
        "compact_schedule": False,
        "schedule_days": [],
        "schedule_view_is_list": True,
        "schedule_view_is_rooms": False,
        "room_lane_days": [],
        "schedule_list_url": url,
        "schedule_rooms_url": f"{url}?view=rooms",
    }


def event_page_context(event, *, url, **overrides):
    # Every key the event page renders with, defaulted to an event with no
    # schedule. `url` is the page's own path, which the view echoes back as the
    # list/rooms view links.
    context = {
        "current_hour_data": {},
        "ended_hour_data": {},
        "enrollment_requires_slots": False,
        "event": event,
        "filterable_tag_categories": [],
        "has_track_filter": False,
        "has_category_filter": False,
        "future_unavailable_hour_data": {},
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
    return context | overrides


def compact_day(cards):
    # The compact schedule's single day: one hour bucket holding every card,
    # plus a tile per card. Fixtures that schedule everything in one hour.
    starts = [localtime(card.agenda_item.start_time) for card in cards]
    hour_start = starts[0].replace(minute=0, second=0, microsecond=0)
    return ScheduleDay(
        day_start=hour_start,
        hours=[ScheduleHour(start=hour_start, sessions=cards)],
        tiles=[
            ScheduleTile(
                data=card,
                start=localtime(card.agenda_item.start_time),
                end=localtime(card.agenda_item.end_time),
            )
            for card in cards
        ],
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
    # offered seat is what pushes it to full.
    space = SpaceFactory(event=event)
    session = SessionFactory(
        event=event, category=None, participants_limit=participants_limit
    )
    AgendaItemFactory(session=session, space=space)
    for status in (
        SessionParticipationStatus.CONFIRMED,
        SessionParticipationStatus.OFFERED,
    ):
        SessionParticipation.objects.create(
            session=session, user=UserFactory(), status=status
        )
    return session
