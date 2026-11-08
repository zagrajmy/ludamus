"""The public event page: the schedule, the viewer's seats and proposals."""

from __future__ import annotations

from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from django.http import Http404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.decorators.vary import vary_on_cookie as vary_cookie
from django.views.generic.base import TemplateView

from ludamus.gates.web.django.access import has_panel_access, panel_access
from ludamus.gates.web.django.entities import UserInfo
from ludamus.gates.web.django.event.event_presentation import (
    ParticipationInfo,
    SessionData,
    build_display_field_row,
    filter_availability,
    filterable_tag_fields,
    mask_session_card,
)
from ludamus.gates.web.django.event.ics import event_calendar_entry
from ludamus.gates.web.django.event.schedule import (
    CardDay,
    build_card_days,
    build_room_lanes,
    build_schedule_days,
)
from ludamus.gates.web.django.event.status_pills import event_status_pills
from ludamus.gates.web.django.meta import (
    LinkPreview,
    markdown_summary,
    session_link_preview,
)
from ludamus.gates.web.django.sphere.marks import attach_guild_marks
from ludamus.pacts.calendar import google_calendar_url
from ludamus.pacts.enrollment import NO_ENROLLMENT_ACCESS
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.ids import EventId, SessionId
from ludamus.pacts.sessions import PROGRAMME_DAY_STARTS_AT_HOUR

if TYPE_CHECKING:
    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.enrollment import EnrollmentAccessDTO
    from ludamus.pacts.event import EventDTO
    from ludamus.pacts.ids import UserId
    from ludamus.pacts.session_cards import SessionCardDTO
    from ludamus.pacts.user import UserDTO

# Above this many scheduled sessions, the card grid becomes unwieldy and the
# event page switches to the compact schedule (a dense chronological list with
# an hour scrubber). Tunable; not a business invariant, so it lives here rather
# than in specs.
COMPACT_SCHEDULE_MIN_SESSIONS = 20


@method_decorator([cache_control(private=True, max_age=180), vary_cookie], name="get")
class EventPageView(TemplateView):
    template_name = "event/event.html"
    request: RootRequest
    event: EventDTO

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        # The slug names the event; the page renders the event, not its URL.
        del kwargs["slug"]
        context = super().get_context_data(**kwargs)
        try:
            self.event = self.request.services.events.read_by_slug(
                self.request.context.current_sphere_id, self.kwargs["slug"]
            )
        except NotFoundError:
            raise Http404 from None

        if not self.event.is_open and not has_panel_access(self.request):
            raise Http404

        event_id = EventId(self.event.pk)
        schedule = self.request.services.event_schedule
        # Every published session of this event, as flat rows. A private track
        # is unlisted here for everyone, panel access included, so a manager
        # previewing the page sees the schedule participants will get.
        scheduled = schedule.scheduled_cards(
            event_id=event_id, roster_up_to=COMPACT_SCHEDULE_MIN_SESSIONS
        )

        shadowbanned_ids: frozenset[UserId] = frozenset()
        banned_by: set[UserId] = set()
        if current_user_id := self.request.context.current_user_id:
            banned_by = self.request.services.shadowban.banning_owner_ids(
                current_user_id
            )
            shadowbanned_ids = frozenset(
                self.request.services.shadowban.banned_user_ids(current_user_id)
            )

        # A window restricted to pass holders is not open to everyone, so the
        # cards, the pill and the modal all read enrollment off this one
        # viewer-scoped answer.
        access = self.request.services.enrollment.access(
            event=self.event, viewer_slug=self.request.context.current_user_slug
        )
        notices = schedule.enrollment_notices(event_id)

        sessions_data = self._get_session_data(
            scheduled,
            shadowbanned_ids,
            access=access,
            limits_to_end_time=notices.limits_to_end_time,
        )

        # Hard event ban: a banned viewer sees every session as full (with
        # simulacra participants) and gets no Enroll action, so the event looks
        # full and they are never told they are banned.
        event_banned = current_user_id is not None and (
            self.request.services.event_bans.is_banned(
                event_id=event_id, user_id=current_user_id
            )
        )
        sessions_data = {
            sid: mask_session_card(
                data, event_banned=event_banned, banned_presenter_ids=banned_by
            )
            for sid, data in sessions_data.items()
        }
        has_maps = self.request.services.event_maps.has_maps(self.event.pk)

        hour_data = self._get_hour_data(sessions_data)

        scheduled_count = len(sessions_data)
        if compact_schedule := scheduled_count >= COMPACT_SCHEDULE_MIN_SESSIONS:
            self._set_bookmark_counts(sessions_data)
            if current_user_id:
                self._set_user_bookmarks(sessions_data, current_user_id)

        total_enrolled = sum(s.enrolled_count for s in sessions_data.values())
        user_enrolled_sessions = [s for s in sessions_data.values() if s.user_enrolled]
        # Gates the filter panel's enrollment checkbox; a limit of 0 takes no
        # enrollment, so an event of drop-ins offers nothing to narrow to.
        has_enrollable_sessions = any(
            data.takes_enrollment for data in sessions_data.values()
        )

        # The day-major grouping only feeds the card-grid layout; the compact
        # schedule renders from schedule_days instead, so skip the pass there.
        card_days: list[CardDay] = (
            [] if compact_schedule else build_card_days(hour_data)
        )

        schedule_days = build_schedule_days(sessions_data) if compact_schedule else []
        # The compact schedule offers two layouts: the chronological ledger
        # (default) and a rooms grid (?view=rooms) with a column per room.
        rooms_view = compact_schedule and self.request.GET.get("view") == "rooms"
        slug = self.event.slug
        event_url = reverse("web:chronology:event", kwargs={"slug": slug})
        calendar_entry = event_calendar_entry(self.event, request=self.request)

        context.update(
            {
                "event": self.event,
                "hour_data": hour_data,
                "sessions": list(sessions_data.values()),
                "scheduled_count": scheduled_count,
                "compact_schedule": compact_schedule,
                "schedule_days": schedule_days,
                "programme_day_start_hour": PROGRAMME_DAY_STARTS_AT_HOUR,
                "active_tab": "rooms" if rooms_view else "list",
                "has_enrollable_sessions": has_enrollable_sessions,
                "room_lanes": build_room_lanes(schedule_days) if rooms_view else None,
                "schedule_list_url": event_url,
                "schedule_rooms_url": f"{event_url}?view=rooms",
                "maps_url": (
                    reverse("web:chronology:event-maps", kwargs={"slug": slug})
                    if has_maps
                    else None
                ),
                "print_url": reverse(
                    "web:chronology:event-print", kwargs={"slug": slug}
                ),
                "google_calendar_url": google_calendar_url(calendar_entry),
                "card_days": card_days,
                "total_enrolled": total_enrolled,
                "user_enrolled_sessions": user_enrolled_sessions,
                "event_banned": event_banned,
                "status_pills": event_status_pills(
                    is_live=self.event.is_live,
                    is_ended=self.event.is_ended,
                    is_proposal_active=self.event.is_proposal_active,
                    access=access,
                ),
                "enrollment_notices": notices.banners,
                "filterable_tag_categories": filterable_tag_fields(
                    schedule.public_select_fields(event_id), sessions_data.values()
                ),
            }
        )
        context.update(self._get_anonymous_context())
        context.update(filter_availability(sessions_data.values()))
        context.update(self._get_pending_sessions_context(shadowbanned_ids))
        context["link_preview"] = self._link_preview(sessions_data)

        return context

    # SAFETY: only a session the schedule already lists. A private or
    # unpublished one never reaches sessions_data, so its title can't leak.
    def _link_preview(self, sessions_data: dict[int, SessionData]) -> LinkPreview:
        raw = self.request.GET.get("session", "")
        if raw.isdecimal() and (data := sessions_data.get(int(raw))) is not None:
            return session_link_preview(data=data, event_name=self.event.name)
        return LinkPreview(description=markdown_summary(self.event.description))

    def _get_anonymous_context(self) -> dict[str, Any]:
        if self.request.context.current_user_id and self.request.session.get(
            "anonymous_enrollment_active"
        ):
            self._clear_anonymous_session()
            return {}

        if (
            not self.request.session.get("anonymous_enrollment_active")
            or self.request.context.current_user_id
        ):
            return {}

        anonymous_user_code = self.request.session.get("anonymous_user_code")
        session_site_id = self.request.session.get("anonymous_site_id")
        if not (
            anonymous_user_code
            and session_site_id == self.request.context.current_site_id
        ):
            self._clear_anonymous_session()
            return {}

        anonymous_user = None
        with suppress(NotFoundError):
            anonymous_user = (
                self.request.services.anonymous_enrollment.get_user_by_code(
                    code=anonymous_user_code
                )
            )
        if not anonymous_user:
            self._clear_anonymous_session()
            return {}

        return {"anonymous_code": anonymous_user.slug.removeprefix("code_")}

    def _clear_anonymous_session(self) -> None:
        self.request.session.pop("anonymous_user_code", None)
        self.request.session.pop("anonymous_enrollment_active", None)
        self.request.session.pop("anonymous_event_id", None)
        self.request.session.pop("anonymous_site_id", None)

    def _get_pending_sessions_context(
        self, shadowbanned_ids: frozenset[UserId]
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "pending_sessions": [],
            "pending_review_visible": False,
            "pending_wizard_view": False,
            "own_pending_proposals": [],
        }
        if (
            not self.request.context.current_user_slug
            or self.request.context.current_user_id is None
        ):
            return context

        schedule = self.request.services.event_schedule
        event_id = EventId(self.event.pk)
        # The review block only renders while the call for proposals runs,
        # so one place decides that — building its cards for a shut CFP meant
        # a whole card pipeline per organizer page view, discarded in the
        # template. Its dates, not whether facilitators can reach it: an
        # organizer previewing an unpublished event still reviews.
        if (access := panel_access(self.request)).granted:
            if not self.event.is_proposal_window_open:
                return context
            return context | {
                "pending_sessions": self._proposal_cards(
                    schedule.review_queue(event_id), shadowbanned_ids
                ),
                "pending_review_visible": True,
                # The wizard is the superuser's view of a sphere they have no
                # part in; one who also holds a role here reviews as that role.
                "pending_wizard_view": access.is_superuser and access.role is None,
            }

        return context | {
            "own_pending_proposals": self._proposal_cards(
                schedule.own_proposals(
                    event_id=event_id, presenter_id=self.request.context.current_user_id
                ),
                shadowbanned_ids,
            )
        }

    def _proposal_cards(
        self, proposals: list[SessionCardDTO], shadowbanned_ids: frozenset[UserId]
    ) -> list[SessionData]:
        # The shadowban ids, but deliberately not mask_session_card: the mask
        # rewrites participants_limit to a fabricated fill, and an organizer
        # has to judge the capacity the author actually asked for. The ids
        # alone are what the danger ring reads, and without them a presenter
        # the viewer shadowbanned would be ringed on their scheduled card and
        # clean on their proposal, on the same page.
        # A proposal holds no agenda item, so no window can seat it yet and
        # no viewer's windows reach the card.
        return list(
            self._get_session_data(
                proposals,
                shadowbanned_ids,
                access=NO_ENROLLMENT_ACCESS,
                limits_to_end_time=False,
            ).values()
        )

    def _set_user_participations(self, sessions: dict[int, SessionData]) -> None:
        # The viewer's seats mark the cards: a signed-in viewer's together with
        # their companions', an anonymous viewer's alone.
        if slug := self.request.context.current_user_slug:
            user_ids = [
                self.request.services.enrollment.read_viewer(slug).pk,
                *(
                    companion.pk
                    for companion in self.request.services.companions.list_companions(
                        slug
                    )
                ),
            ]
        elif (anonymous_user := self._anonymous_viewer()) is not None:
            user_ids = [anonymous_user.pk]
        else:
            return
        held = self.request.services.event_schedule.viewer_seats(
            session_ids=list(sessions), user_ids=user_ids
        )
        for session_id, seats in held.items():
            sessions[session_id].user_enrolled = seats.enrolled
            sessions[session_id].user_waiting = seats.waiting

    def _anonymous_viewer(self) -> UserDTO | None:
        session = self.request.session
        if not (
            session.get("anonymous_enrollment_active")
            and session.get("anonymous_user_code")
        ):
            return None
        # An anonymous code is for one site: another site's code says nothing
        # about this page's sessions.
        if session.get("anonymous_site_id") != self.request.context.current_site_id:
            return None
        with suppress(NotFoundError):
            return self.request.services.anonymous_enrollment.get_user_by_code(
                code=session["anonymous_user_code"]
            )
        return None

    def _set_bookmark_counts(self, sessions_data: dict[int, SessionData]) -> None:
        counts = self.request.services.bookmarks.bookmark_counts(
            event_id=EventId(self.event.pk)
        )
        for sid, data in sessions_data.items():
            data.bookmark_count = counts.get(SessionId(sid), 0)

    def _set_user_bookmarks(
        self, sessions_data: dict[int, SessionData], current_user_id: UserId
    ) -> None:
        # Bookmarks are only surfaced on the compact schedule (the lightweight
        # "I want to attend" gesture for big events). One query for the whole set.
        bookmarked_ids = self.request.services.bookmarks.bookmarked_session_ids(
            user_id=current_user_id, event_id=EventId(self.event.pk)
        )
        for sid, data in sessions_data.items():
            data.user_bookmarked = sid in bookmarked_ids

    @staticmethod
    def _get_hour_data(
        sessions_data: dict[int, SessionData],
    ) -> dict[datetime, list[SessionData]]:
        # Keeps the cards' order, which is the schedule's: earliest first.
        sessions_by_hour: dict[datetime, list[SessionData]] = defaultdict(list)
        for data in sessions_data.values():
            if data.agenda_item is not None:
                sessions_by_hour[data.agenda_item.start_time].append(data)
        return dict(sessions_by_hour)

    def _edit_allowed(self) -> bool:
        if (event_override := self.event.allow_facilitator_session_edit) is not None:
            return event_override
        return self.request.services.sites.read(
            self.request.context.current_sphere_id
        ).allow_facilitator_session_edit

    def _get_session_data(
        self,
        cards: list[SessionCardDTO],
        shadowbanned_ids: frozenset[UserId] = frozenset(),
        *,
        access: EnrollmentAccessDTO,
        limits_to_end_time: bool,
    ) -> dict[int, SessionData]:
        edit_allowed = self._edit_allowed()
        current_user_id = self.request.context.current_user_id

        sessions_data = {}
        for card in cards:
            session = card.session
            if card.presenter is not None:
                presenter = UserInfo.from_user_dto(card.presenter)
            else:
                presenter_name = session.facilitator_name or ""
                presenter = UserInfo(
                    avatar_url=None,
                    discord_username="",
                    full_name=presenter_name,
                    name=presenter_name,
                    pk=0,
                    slug="",
                    username=presenter_name,
                )
            sessions_data[session.pk] = SessionData(
                can_edit=(
                    edit_allowed
                    and current_user_id is not None
                    and session.presenter_id == current_user_id
                ),
                effective_participants_limit=card.effective_participants_limit,
                agenda_item=card.agenda_item,
                session=session,
                presenter=presenter,
                presenter_is_shadowbanned=presenter.pk in shadowbanned_ids,
                field_values=card.field_values,
                # Unfiltered: the schedule read drops a session with any
                # private track outright, so the only cards left carrying one
                # are proposals, whose readers are organizers and the author.
                track_names=card.track_names,
                category_name=card.category_name,
                # An unscheduled proposal can't be enrolled in yet. A session
                # inside a window that turns this viewer away is not available
                # to them, whatever its seat count says.
                is_enrollment_available=(
                    card.agenda_item is not None
                    and access.seats(card.enrollment_window_ids)
                ),
                is_full=card.is_full,
                loc=card.location,
                enrolled_count=card.enrolled_count,
                waiting_count=card.waiting_count,
                session_participations=[
                    ParticipationInfo(
                        user=UserInfo.from_user_dto(seat.user),
                        status=seat.status,
                        creation_time=seat.creation_time,
                        is_shadowbanned=seat.user.pk in shadowbanned_ids,
                    )
                    for seat in card.participations
                ],
                preferred_time_slots=card.preferred_time_slots,
            )

        current_time = datetime.now(tz=UTC)
        for session_data in sessions_data.values():
            session_data.displayed_field_rows = [
                build_display_field_row(fv)
                for fv in session_data.field_values
                if fv.show_on_cards
            ]

            if session_data.agenda_item is None:
                continue
            session_start = session_data.agenda_item.start_time

            # Calculate if session is ongoing (has already started) or fully over
            session_data.is_ongoing = session_start <= current_time
            session_data.is_ended = session_data.agenda_item.end_time <= current_time

            # An open window that seats only sessions starting before it ends
            # shows a session already under way as in progress.
            if limits_to_end_time and session_data.is_ongoing:
                session_data.should_show_as_inactive = True

        # Set user participation data for authenticated users and anonymous users
        self._set_user_participations(sessions_data)
        attach_guild_marks(
            sessions_data,
            guilds=self.request.services.guilds,
            sphere_id=self.request.context.current_sphere_id,
        )

        return sessions_data
