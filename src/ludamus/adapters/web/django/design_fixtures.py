"""Mock data for the design system page."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from django import forms
from django.contrib.staticfiles.storage import staticfiles_storage

from ludamus.gates.web.django.chronology.event_presentation import (
    EventInfo,
    ParticipationInfo,
    SessionData,
    build_display_field_row,
)
from ludamus.gates.web.django.entities import UserInfo
from ludamus.pacts import (
    NO_LOCATION,
    AgendaItemDTO,
    LocationData,
    SessionDTO,
    SessionFieldValueDTO,
    SessionStatus,
    TimeSlotDTO,
)

_DESIGN_PLACEHOLDER_IMAGE = "placeholder-images/01.webp"

# The gallery has no upload to derive a preview from, so this is what
# links.db.django.previews.image_preview returns for the image above, pasted in
# rather than recomputed on every render of /design.
_DESIGN_PLACEHOLDER_PREVIEW = (
    "data:image/webp;base64,UklGRqIAAABXRUJQVlA4IJYAAAAQBACdASoUAAoAPrVInkmnJCKh"
    "MAgA4BaJZACdACG0ST6/K/kH478mAAD+l05QkCshhb+nBgIc7J1CWri7dT5ZudyM2n8snMolKPB"
    "SeGnsD8lCNOEVKN23Uaf8phH+om2rUZxMM8CGDBZoRi3ZfCNBXDZnEm3Qd3VWaYXCvmJVbypTlz"
    "BrF0daOZKqn0KRzQW1+gAAAAA="
)

for _dto in (AgendaItemDTO, EventInfo, SessionDTO, SessionFieldValueDTO):
    _dto.model_rebuild()


def _mock_user(full_name: str, pk: int, slug: str, username: str) -> UserInfo:
    return UserInfo(
        avatar_url=None,
        discord_username="",
        full_name=full_name,
        name=full_name,
        pk=pk,
        slug=slug,
        username=username,
    )


def _mock_venue_and_space() -> LocationData:
    return {
        "space_name": "Table 1",
        "parent_slug": "main-hall",
        "parent_name": "Main Hall",
        "path": "Main Hall > Table 1",
        "sort_key": "000000|Main Hall|main-hall|000000|Table 1|table-1",
    }


def _mock_field_values() -> list[SessionFieldValueDTO]:
    return [
        SessionFieldValueDTO(
            field_icon="book-open",
            field_id=1,
            field_name="System",
            field_question="What RPG system?",
            field_slug="system",
            field_type="select",
            is_public=True,
            value=["D&D 5e", "Pathfinder", "Fate"],
        ),
        SessionFieldValueDTO(
            field_icon="exclamation-triangle",
            field_id=2,
            field_name="Triggers",
            field_question="Content warnings?",
            field_slug="triggers",
            field_type="select",
            is_public=True,
            value=["horror", "violence"],
        ),
    ]


def mock_user() -> UserInfo:
    return _mock_user("Alex Designer", pk=1, slug="alex-designer", username="alex")


class _MockTesseraForm(forms.Form):
    name = forms.CharField(label="Name", max_length=64, required=True)
    email = forms.EmailField(label="Email", required=False)
    bio = forms.CharField(
        label="Bio", widget=forms.Textarea(attrs={"rows": 3}), required=False
    )
    color = forms.ChoiceField(
        label="Color",
        choices=[("", "Pick one…"), ("r", "Red"), ("g", "Green"), ("b", "Blue")],
        required=False,
    )
    subscribe = forms.BooleanField(label="Subscribe to updates", required=False)


def mock_form() -> forms.Form:
    return _MockTesseraForm()


def mock_event_info() -> EventInfo:
    start = datetime.now(UTC) + timedelta(days=7)
    end = start + timedelta(hours=6)
    return EventInfo(
        cover_image_url=staticfiles_storage.url(_DESIGN_PLACEHOLDER_IMAGE),
        cover_image_preview=_DESIGN_PLACEHOLDER_PREVIEW,
        description=(
            "Design system preview event. Use this to debug the "
            "event card in isolation."
        ),
        end_time=end,
        is_ended=False,
        is_live=False,
        is_proposal_active=True,
        is_published=True,
        name="Design Preview Event",
        session_count=12,
        start_time=start,
        slug="design-preview",
    )


def mock_session_data() -> SessionData:
    base_time = datetime.now(UTC) + timedelta(days=7)
    start = base_time.replace(hour=14, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)
    creation = datetime.now(UTC) - timedelta(days=30)
    field_values = _mock_field_values()
    presenter = _mock_user("Alex Designer", pk=1, slug="alex-designer", username="alex")
    participants = [
        _mock_user("Sam Player", pk=10, slug="sam-player", username="sam"),
        _mock_user("Jordan Gamer", pk=11, slug="jordan-gamer", username="jordan"),
    ]
    session_participations = [
        ParticipationInfo(user=u, status="confirmed", creation_time=creation)
        for u in participants
    ]
    return SessionData(
        agenda_item=AgendaItemDTO(
            end_time=end, pk=1, session_confirmed=True, start_time=start
        ),
        is_enrollment_available=True,
        presenter=presenter,
        session=SessionDTO(
            contact_email="alex@example.com",
            creation_time=creation,
            description=(
                "A sample session for the design page. Host and tags are mock data."
            ),
            min_age=16,
            modification_time=creation,
            participants_limit=6,
            pk=1,
            display_name="Alex Designer",
            slug="design-session",
            title="Design System Session Card",
            category_id=17,
            presenter_id=18,
            status=SessionStatus.ACCEPTED,
        ),
        is_full=False,
        effective_participants_limit=6,
        enrolled_count=2,
        session_participations=session_participations,
        loc=_mock_venue_and_space(),
        field_values=field_values,
        displayed_field_rows=[build_display_field_row(fv) for fv in field_values],
    )


def mock_session_proposal() -> SessionData:
    """Build the card's unscheduled variant: no agenda item, preferred slots."""
    data = mock_session_data()
    # Same week as the mock event, which sits seven days out — a proposal
    # asking for a slot that already happened reads as a bug in the gallery.
    start = (datetime.now(UTC) + timedelta(days=7)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    return replace(
        data,
        agenda_item=None,
        is_enrollment_available=False,
        loc=NO_LOCATION,
        session_participations=[],
        enrolled_count=0,
        preferred_time_slots=[
            TimeSlotDTO(pk=1, start_time=start, end_time=start + timedelta(hours=2)),
            TimeSlotDTO(
                pk=2,
                start_time=start + timedelta(hours=4),
                end_time=start + timedelta(hours=6),
            ),
        ],
    )


def mock_session_data_ended() -> SessionData:
    data = mock_session_data()
    base_time = datetime.now(UTC) - timedelta(hours=2)
    start = base_time.replace(hour=10, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)
    creation = datetime.now(UTC) - timedelta(days=30)
    ended_participants = [
        _mock_user("Sam Player", pk=10, slug="sam-player", username="sam"),
        _mock_user("Jordan Gamer", pk=11, slug="jordan-gamer", username="jordan"),
        _mock_user("Casey Demo", pk=12, slug="casey-demo", username="casey"),
    ]
    ended_participations = [
        ParticipationInfo(user=u, status="confirmed", creation_time=creation)
        for u in ended_participants
    ]
    return SessionData(
        agenda_item=AgendaItemDTO(
            end_time=end, pk=2, session_confirmed=True, start_time=start
        ),
        is_enrollment_available=False,
        presenter=data.presenter,
        session=SessionDTO(
            contact_email="alex@example.com",
            creation_time=creation,
            description="Ended session for design preview.",
            min_age=0,
            modification_time=creation,
            participants_limit=6,
            pk=2,
            display_name=data.presenter.full_name,
            slug="design-session-ended",
            title="Ended Session (Design Preview)",
            category_id=17,
            presenter_id=18,
            status=SessionStatus.ACCEPTED,
        ),
        is_full=True,
        effective_participants_limit=6,
        enrolled_count=6,
        session_participations=ended_participations,
        loc=_mock_venue_and_space(),
        field_values=data.field_values[:1],
        displayed_field_rows=data.displayed_field_rows[:1],
        is_ongoing=True,
        is_ended=True,
    )
