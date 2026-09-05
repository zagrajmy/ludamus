"""Proposal intake: everything the propose wizard reads and the submit it writes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.mills.submissions.mapping import generate_unique_slug
from ludamus.pacts import (
    FacilitatorData,
    NotFoundError,
    PersonalDataFieldValueData,
    ProposeSessionResult,
    SessionData,
    SessionFieldValueData,
    SessionStatus,
)
from ludamus.pacts.chronology import SessionPlacement
from ludamus.pacts.durations import normalize_duration
from ludamus.pacts.propose import (
    ClaimAlreadyPendingError,
    ProposeOpennessDTO,
    ProposeSessionServiceProtocol,
    SpotRequiredError,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.pacts.submissions import is_empty_answer
from ludamus.specs.proposal import PROPOSAL_RATE_LIMIT_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ludamus.pacts import (
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
    from ludamus.pacts.fields import FieldValue
    from ludamus.pacts.propose import ProposeRepos, SpotClaim
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.timetable import TimetableServiceProtocol


def _category_is_open(
    *, category: ProposalCategoryDTO, event: EventDTO, now: datetime
) -> bool:
    """Report openness: a category window governs alone, its absence defers.

    Returns:
        True when the category's own window holds now, or, with no window of
        its own, when the event's proposal window is open.
    """
    if category.start_time is None and category.end_time is None:
        return event.is_proposal_active
    return (category.start_time is None or category.start_time <= now) and (
        category.end_time is None or now <= category.end_time
    )


class ProposeSessionService(ProposeSessionServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repos: ProposeRepos,
        cache: CacheProtocol,
        timetable: TimetableServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._repos = repos
        self._cache = cache
        self._timetable = timetable

    @staticmethod
    def _generate_unique_slug(title: str, exists: Callable[[str], bool]) -> str:
        return generate_unique_slug(title, exists)

    def get_event(self, slug: str, sphere_id: int) -> EventDTO:
        return self._repos.events.read_by_slug(slug, sphere_id)

    def get_proposal_settings(self, event_id: int) -> EventProposalSettingsDTO:
        return self._repos.event_proposal_settings.read_by_event(event_id)

    def get_or_create_proposal_settings(
        self, event_id: int
    ) -> EventProposalSettingsDTO:
        return self._repos.event_proposal_settings.read_or_create_by_event(event_id)

    def get_openness(self, event_id: int) -> ProposeOpennessDTO:
        event = self._repos.events.read(event_id)
        if not event.is_published:
            return ProposeOpennessDTO(is_open=False, categories=[], is_impromptu=False)
        now = datetime.now(tz=UTC)
        categories = [
            category
            for category in self._repos.categories.list_by_event(event_id)
            if _category_is_open(category=category, event=event, now=now)
        ]
        return ProposeOpennessDTO(
            is_open=event.is_proposal_active or bool(categories),
            categories=categories,
            is_impromptu=not event.is_proposal_active,
        )

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
        self, *, event_id: int, user_id: int | None
    ) -> dict[str, str | list[str] | bool]:
        if user_id is None:
            return {}
        try:
            facilitator = self._repos.facilitators.read_by_user_and_event(
                user_id, event_id
            )
        except NotFoundError:
            return {}
        return self._repos.personal_data_field_values.read_for_facilitator_event(
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
        self, *, event: EventDTO, display_name: str, user_id: int | None
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

    def _require_claim(
        self, *, event_id: int, presenter_id: int | None, spot: SpotClaim | None
    ) -> tuple[SpotClaim, int]:
        """Check the walk-up may claim now, resolving the cell and its claimant.

        Returns:
            The cell to place and the id of the person claiming it.
        """
        if spot is None:
            raise SpotRequiredError
        if presenter_id is None:
            msg = "an impromptu claim needs a logged-in author"
            raise ValueError(msg)
        # The constraint is the enforcement; this count only earns the friendly
        # message before anything is written.
        if self._repos.sessions.count_pending_impromptu_claims(event_id, presenter_id):
            raise ClaimAlreadyPendingError
        return spot, presenter_id

    def submit(
        self,
        event: EventDTO,
        wizard_data: WizardData,
        *,
        cover_image: UploadedFileProtocol | None = None,
        user_id: int | None = None,
        user_slug: str | None = None,
        spot: SpotClaim | None = None,
    ) -> ProposeSessionResult:
        session_data = wizard_data.get("session_data", {})
        if "title" not in session_data:
            msg = "session_data must contain 'title'"
            raise ValueError(msg)
        title = str(session_data["title"])
        description = str(session_data.get("description", ""))
        raw_limit = session_data.get("participants_limit") or 0
        participants_limit = int(str(raw_limit))
        category_id = wizard_data["category_id"]
        time_slot_ids = wizard_data.get("time_slot_ids", [])

        if user_id is not None and user_slug is not None:
            current_user = self._repos.users.read(user_slug)
            default_display_name = current_user.name
            presenter_id = current_user.pk
        else:
            default_display_name = ""
            presenter_id = None

        # Claim-mode is the event's own answer, not the wizard's: every step is
        # its own postable endpoint, so a walk-up that never reached the picker
        # must be refused rather than written as an ordinary proposal. Same
        # reading as `get_openness`, off the event already in hand.
        claim = (
            self._require_claim(event_id=event.pk, presenter_id=presenter_id, spot=spot)
            if event.is_published and not event.is_proposal_active
            else None
        )

        display_name = str(session_data.get("display_name", default_display_name))
        slug = self._generate_unique_slug(
            title, lambda s: self._repos.sessions.slug_exists(event.pk, s)
        )

        with self._transaction.atomic():
            facilitator = self._find_or_create_facilitator(
                event=event, display_name=display_name, user_id=user_id
            )

            create_data = SessionData(
                event_id=event.pk,
                presenter_id=presenter_id,
                display_name=display_name,
                category_id=category_id,
                title=title,
                slug=slug,
                description=description,
                duration=normalize_duration(str(session_data.get("duration") or "")),
                participants_limit=participants_limit,
                min_age=int(str(session_data.get("min_age") or 0)),
                contact_email=wizard_data.get("contact_email", ""),
                status=SessionStatus.PENDING,
                is_impromptu=claim is not None,
            )
            if cover_image:
                create_data["cover_image"] = cover_image

            session_id = self._create_session(
                create_data,
                time_slot_ids=time_slot_ids,
                facilitator_id=facilitator.pk,
                claimant=claim[1] if claim else None,
            )

            self._save_session_field_values(
                session_id=session_id, event_id=event.pk, session_data=session_data
            )

            if personal_data := wizard_data.get("personal_data", {}):
                self._save_personal_data(
                    event_id=event.pk,
                    personal_data=personal_data,
                    facilitator=facilitator,
                )

            if track_pks := wizard_data.get("track_pks", []):
                # Track ids come from wizard state, so they are trusted only
                # after being matched against this event's own public tracks —
                # a foreign event's track must never be attached.
                allowed = {
                    track.pk
                    for track in self._repos.tracks.list_public_by_event(event.pk)
                }
                if scoped := [pk for pk in track_pks if pk in allowed]:
                    self._repos.sessions.set_session_tracks(session_id, scoped)

            if claim is not None:
                claimed_spot, claimant = claim
                self._claim(
                    session_id=session_id,
                    event_id=event.pk,
                    spot=claimed_spot,
                    presenter_id=claimant,
                )

        return ProposeSessionResult(session_id=session_id, title=title)

    def _create_session(
        self,
        create_data: SessionData,
        *,
        time_slot_ids: list[int],
        facilitator_id: int,
        claimant: int | None,
    ) -> int:
        """Insert the session, mapping a lost race for the one-claim cap.

        Returns:
            The new session's id.
        """
        if claimant is None:
            return self._repos.sessions.create(
                create_data,
                time_slot_ids=time_slot_ids,
                facilitator_ids=[facilitator_id],
            )
        # Only the insert is wrapped, and the re-query decides what failed:
        # the transaction layer flattens every integrity failure into one
        # exception whose text is the driver's, so a blanket catch would report
        # a foreign key or a slug collision as a second claim.
        try:
            with self._transaction.savepoint():
                return self._repos.sessions.create(
                    create_data,
                    time_slot_ids=time_slot_ids,
                    facilitator_ids=[facilitator_id],
                )
        except DatabaseConstraintError as exc:
            if self._repos.sessions.count_pending_impromptu_claims(
                create_data["event_id"], claimant
            ):
                raise ClaimAlreadyPendingError from exc
            raise

    def _claim(
        self, *, session_id: int, event_id: int, spot: SpotClaim, presenter_id: int
    ) -> None:
        # read_time_slot scopes the slot to the session's own event, so a slot
        # id smuggled past the picker is NotFound rather than a placement.
        time_slot = self._repos.sessions.read_time_slot(session_id, spot.time_slot_pk)
        self._timetable.claim_spot(
            session_pk=session_id,
            placement=SessionPlacement(
                space_pk=spot.space_pk,
                start_time=time_slot.start_time,
                end_time=time_slot.end_time,
            ),
            event_pk=event_id,
            user_pk=presenter_id,
        )

    def _save_session_field_values(
        self,
        *,
        session_id: int,
        event_id: int,
        session_data: Mapping[str, FieldValue | int],
    ) -> None:
        values: list[SessionFieldValueData] = []
        for key, value in session_data.items():
            if not key.startswith("session_"):
                continue
            slug = key.removeprefix("session_")
            if slug.endswith("_custom"):
                continue
            # Organizer fields are text/select/checkbox only, so an answer is
            # never a plain int. The ints session_data also carries are builtins
            # (participants_limit, min_age), which never wear the prefix.
            if isinstance(value, int) and not isinstance(value, bool):
                continue
            # A question the submitter left blank stores no row: the proposal
            # is new, so absence can only mean "never answered". Checked before
            # the field lookup — a blank never needs the query.
            if value is None or is_empty_answer(value=value):
                continue
            try:
                field_dto = self._repos.session_fields.read_by_slug(event_id, slug)
            except NotFoundError:
                continue
            values.append(
                SessionFieldValueData(
                    session_id=session_id, field_id=field_dto.pk, value=value
                )
            )
        if values:
            self._repos.sessions.save_field_values(session_id, values)

    def _save_personal_data(
        self,
        *,
        event_id: int,
        personal_data: dict[str, str],
        facilitator: FacilitatorDTO,
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
            self._repos.personal_data_field_values.save(entries)
