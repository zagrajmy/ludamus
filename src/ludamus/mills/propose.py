from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.mills.event import is_proposal_active
from ludamus.mills.submissions.mapping import generate_unique_slug
from ludamus.pacts.durations import normalize_duration
from ludamus.pacts.legacy import (
    FacilitatorData,
    NotFoundError,
    PersonalDataFieldValueData,
    ProposeSessionResult,
    SessionData,
    SessionFieldValueData,
    SessionStatus,
)
from ludamus.pacts.propose import ProposeSessionServiceProtocol
from ludamus.pacts.submissions import is_empty_answer
from ludamus.specs.proposal import PROPOSAL_RATE_LIMIT_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable

    from ludamus.pacts.legacy import (
        CacheProtocol,
        EventDTO,
        EventProposalSettingsDTO,
        FacilitatorDTO,
        PersonalFieldRequirementDTO,
        ProposalCategoryDTO,
        SessionFieldRequirementDTO,
        TimeSlotRequirementDTO,
        TrackDTO,
        UploadedFileProtocol,
        WizardData,
    )
    from ludamus.pacts.propose import ProposeRepos
    from ludamus.pacts.services import TransactionProtocol


def _as_answer(value: object) -> str | list[str] | bool | None:
    """Narrow a wizard's untyped session value to what a field row can hold."""
    if isinstance(value, str | bool):
        return value
    if isinstance(value, list):
        return [str(item) for item in value]
    return None


class ProposeSessionService(ProposeSessionServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repos: ProposeRepos,
        cache: CacheProtocol,
    ) -> None:
        self._transaction = transaction
        self._repos = repos
        self._cache = cache

    @staticmethod
    def _generate_unique_slug(title: str, exists: Callable[[str], bool]) -> str:
        return generate_unique_slug(title, exists)

    def get_event(self, slug: str, *, sphere_id: int) -> EventDTO:
        return self._repos.events.read_by_slug(slug, sphere_id)

    @staticmethod
    def is_proposal_active(event: EventDTO) -> bool:
        return is_proposal_active(event)

    def get_proposal_settings(self, event_id: int) -> EventProposalSettingsDTO:
        return self._repos.proposal_settings.read_by_event(event_id)

    def get_or_create_proposal_settings(
        self, event_id: int
    ) -> EventProposalSettingsDTO:
        return self._repos.proposal_settings.read_or_create_by_event(event_id)

    def get_categories(self, event_id: int) -> list[ProposalCategoryDTO]:
        return self._repos.categories.list_by_event(event_id)

    def get_category(self, pk: int, event_id: int) -> ProposalCategoryDTO:
        return self._repos.categories.read(pk, event_id)

    def get_personal_requirements(
        self, category_id: int
    ) -> list[PersonalFieldRequirementDTO]:
        return self._repos.categories.list_personal_field_requirements(category_id)

    def get_session_requirements(
        self, category_id: int
    ) -> list[SessionFieldRequirementDTO]:
        return self._repos.categories.list_session_field_requirements(category_id)

    def get_timeslot_requirements(
        self, category_id: int
    ) -> list[TimeSlotRequirementDTO]:
        return self._repos.categories.list_time_slot_requirements(category_id)

    def get_public_tracks(self, event_id: int) -> list[TrackDTO]:
        return self._repos.tracks.list_public_by_event(event_id)

    def get_saved_personal_data(
        self, event_id: int, *, user_id: int | None
    ) -> dict[str, str | list[str] | bool]:
        if user_id is None:
            return {}
        try:
            facilitator = self._repos.facilitators.read_by_user_and_event(
                user_id, event_id
            )
        except NotFoundError:
            return {}
        return self._repos.personal_field_values.read_for_facilitator_event(
            facilitator.pk, event_id
        )

    def check_rate_limit(self, *, ip: str, event_id: int) -> bool:
        """Reserve a submission slot for an IP, reporting whether it was free."""
        key = f"proposal_rate:{event_id}:{ip}"
        if self._cache.get(key) is not None:
            return False
        self._cache.set(key, 1, timeout=PROPOSAL_RATE_LIMIT_SECONDS)
        return True

    def _find_or_create_facilitator(
        self, event: EventDTO, display_name: str, *, user_id: int | None
    ) -> FacilitatorDTO:
        if user_id is not None:
            try:
                return self._repos.facilitators.read_by_user_and_event(
                    user_id, event.pk
                )
            except NotFoundError:
                pass
        slug = self._generate_unique_slug(
            display_name, lambda s: self._repos.facilitators.slug_exists(event.pk, s)
        )
        return self._repos.facilitators.create(
            FacilitatorData(
                event_id=event.pk, user_id=user_id, display_name=display_name, slug=slug
            )
        )

    def submit(
        self,
        event: EventDTO,
        wizard_data: WizardData,
        *,
        user_id: int | None,
        user_slug: str | None,
        cover_image: UploadedFileProtocol | None = None,
    ) -> ProposeSessionResult:
        """Create the PENDING session a completed wizard describes."""
        session_data = wizard_data.get("session_data", {})
        if "title" not in session_data:
            msg = "session_data must contain 'title'"
            raise ValueError(msg)
        title = str(session_data["title"])
        category_id = wizard_data["category_id"]

        if user_id is not None and user_slug is not None:
            current_user = self._repos.users.read(user_slug)
            default_display_name = current_user.name
            presenter_id = current_user.pk
        else:
            default_display_name = ""
            presenter_id = None

        display_name = str(session_data.get("display_name", default_display_name))
        slug = self._generate_unique_slug(
            title, lambda s: self._repos.sessions.slug_exists(event.pk, s)
        )

        with self._transaction.atomic():
            facilitator = self._find_or_create_facilitator(
                event, display_name, user_id=user_id
            )

            create_data = SessionData(
                event_id=event.pk,
                presenter_id=presenter_id,
                display_name=display_name,
                category_id=category_id,
                title=title,
                slug=slug,
                description=str(session_data.get("description", "")),
                duration=normalize_duration(str(session_data.get("duration") or "")),
                participants_limit=int(
                    str(session_data.get("participants_limit") or 0)
                ),
                min_age=int(str(session_data.get("min_age") or 0)),
                contact_email=wizard_data.get("contact_email", ""),
                status=SessionStatus.PENDING,
            )
            if cover_image:
                create_data["cover_image"] = cover_image

            session_id = self._repos.sessions.create(
                create_data,
                time_slot_ids=wizard_data.get("time_slot_ids", []),
                facilitator_ids=[facilitator.pk],
            )

            self._save_session_field_values(session_id, event.pk, session_data)

            if personal_data := wizard_data.get("personal_data", {}):
                self._save_personal_data(event.pk, personal_data, facilitator)

            if track_pks := wizard_data.get("track_pks", []):
                self._repos.sessions.set_session_tracks(session_id, track_pks)

        return ProposeSessionResult(session_id=session_id, title=title)

    def _save_session_field_values(
        self, session_id: int, event_id: int, session_data: dict[str, object]
    ) -> None:
        values: list[SessionFieldValueData] = []
        for key, value in session_data.items():
            if not key.startswith("session_"):
                continue
            slug = key.removeprefix("session_")
            if slug.endswith("_custom"):
                continue
            # A question the submitter left blank stores no row: the proposal
            # is new, so absence can only mean "never answered". Checked before
            # the field lookup — a blank never needs the query.
            answer = _as_answer(value)
            if answer is None or is_empty_answer(value=answer):
                continue
            try:
                field_dto = self._repos.session_fields.read_by_slug(event_id, slug)
            except NotFoundError:
                continue
            values.append(
                SessionFieldValueData(
                    session_id=session_id, field_id=field_dto.pk, value=answer
                )
            )
        if values:
            self._repos.sessions.save_field_values(session_id, values)

    def _save_personal_data(
        self, event_id: int, personal_data: dict[str, str], facilitator: FacilitatorDTO
    ) -> None:
        entries: list[PersonalDataFieldValueData] = []
        for key, value in personal_data.items():
            if not key.startswith("personal_"):
                continue
            slug = key.removeprefix("personal_")
            if slug.endswith("_custom"):
                continue
            if is_empty_answer(value=value):
                continue
            try:
                field_dto = self._repos.personal_fields.read_by_slug(event_id, slug)
            except NotFoundError:
                continue
            entries.append(
                PersonalDataFieldValueData(
                    facilitator_id=facilitator.pk,
                    event_id=event_id,
                    field_id=field_dto.pk,
                    value=value,
                )
            )
        if entries:
            self._repos.personal_field_values.save(entries)
