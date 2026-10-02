"""Anonymous enrollment: a code in the URL stands in for an account.

Owns its decisions and transactional boundary, delegating IO to injected
ports so the logic stays unit-testable with fakes.
"""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.mills.crowd import build_anonymous_user
from ludamus.mills.enrollment_windows import EnrollmentPolicy
from ludamus.pacts.crowd import UserData, UserDTO
from ludamus.pacts.enrollment import (
    AnonymousActivationDTO,
    AnonymousCancelResultDTO,
    AnonymousEnrollmentError,
    AnonymousEnrollmentErrorCode,
    AnonymousEnrollmentServiceProtocol,
    AnonymousEnrollOutcome,
    AnonymousEnrollPageDTO,
    AnonymousEnrollResultDTO,
    AnonymousLoadDTO,
    AnonymousSessionContextDTO,
)
from ludamus.pacts.legacy import OCCUPYING_PARTICIPATION_STATUSES, NotFoundError

if TYPE_CHECKING:

    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.enrollment import (
        AnonymousEnrollmentRepositoryProtocol,
        AnonymousEnrollmentRequestDTO,
        WaitlistPromotionServiceProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class AnonymousEnrollmentService(AnonymousEnrollmentServiceProtocol):
    SLUG_TEMPLATE = "code_{code}"

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        user_repository: UserRepositoryProtocol,
        enrollment_repository: AnonymousEnrollmentRepositoryProtocol,
        waitlist_promotion: WaitlistPromotionServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._user_repository = user_repository
        self._enrollment_repository = enrollment_repository
        self._waitlist_promotion = waitlist_promotion

    def get_user_by_code(self, code: str) -> UserDTO:
        slug = self.SLUG_TEMPLATE.format(code=code)
        user = self._user_repository.read(slug)
        return UserDTO.model_validate(user)

    def build_user(self, code: str) -> UserData:
        return build_anonymous_user(self.SLUG_TEMPLATE.format(code=code))

    def activate(self, *, event_slug: str) -> AnonymousActivationDTO:
        try:
            event = self._enrollment_repository.read_event(event_slug)
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.EVENT_NOT_FOUND
            ) from None
        policy = EnrollmentPolicy.for_anonymous(event.active_windows)
        if not policy.can_enroll:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.NOT_AVAILABLE_FOR_EVENT,
                event_slug=event.slug,
            )
        code = token_urlsafe(4).lower()
        self._user_repository.create(self.build_user(code))
        return AnonymousActivationDTO(
            code=code, event_id=event.event_id, event_slug=event.slug
        )

    def get_enroll_page(
        self, enrollment_request: AnonymousEnrollmentRequestDTO
    ) -> AnonymousEnrollPageDTO:
        session, user = self._validate(enrollment_request)
        status = self._enrollment_repository.read_participation_status(
            session_id=session.session_id, user_id=user.pk
        )
        if status is None and not session.allows_anonymous_enrollment:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED,
                event_slug=session.event_slug,
            )
        return AnonymousEnrollPageDTO(
            session=session,
            user_name=user.full_name,
            anonymous_code=user.slug.removeprefix("code_"),
            needs_user_data=not user.name,
            enrollment_status=status,
        )

    def enroll(
        self, enrollment_request: AnonymousEnrollmentRequestDTO, name: str
    ) -> AnonymousEnrollResultDTO:
        session = self._session_context(enrollment_request)
        self._require_open(session, enrollment_request)
        user = self._user_for(enrollment_request, session)
        self._update_name(user, name)
        if self._enrollment_repository.has_conflicts(
            session_id=session.session_id, user=user
        ):
            return AnonymousEnrollResultDTO(
                outcome=AnonymousEnrollOutcome.CONFLICT,
                session_title=session.title,
                event_slug=session.event_slug,
            )
        with self._transaction.atomic():
            seating = self._enrollment_repository.lock_seating(session.session_id)
            policy = EnrollmentPolicy.for_anonymous(seating.eligible_windows)
            if not policy.can_enroll:
                raise AnonymousEnrollmentError(
                    AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED,
                    event_slug=session.event_slug,
                )
            if policy.is_full(
                participants_limit=seating.participants_limit,
                enrolled_count=seating.enrolled_count,
            ):
                self._enrollment_repository.create_waiting(
                    session_id=session.session_id, user_id=user.pk
                )
                outcome = AnonymousEnrollOutcome.WAITLISTED
            else:
                self._enrollment_repository.create_or_confirm(
                    session_id=session.session_id, user_id=user.pk
                )
                outcome = AnonymousEnrollOutcome.ENROLLED
        return AnonymousEnrollResultDTO(
            outcome=outcome, session_title=seating.title, event_slug=session.event_slug
        )

    def cancel(
        self, enrollment_request: AnonymousEnrollmentRequestDTO, name: str
    ) -> AnonymousCancelResultDTO:
        session, user = self._validate(enrollment_request)
        self._update_name(user, name)
        with self._transaction.atomic():
            seating = self._enrollment_repository.lock_seating(session.session_id)
            status = self._enrollment_repository.delete_participation(
                session_id=session.session_id, user_id=user.pk
            )
        # A freed confirmed (or held offered) seat promotes/offers the next
        # waiter, who is notified by the promotion service after the mutation
        # commits.
        if status in OCCUPYING_PARTICIPATION_STATUSES:
            self._waitlist_promotion.fill_freed_seats(session_id=session.session_id)
        return AnonymousCancelResultDTO(
            cancelled=status is not None,
            session_title=seating.title,
            event_slug=session.event_slug,
        )

    def load_by_code(self, *, code: str) -> AnonymousLoadDTO:
        try:
            user = self.get_user_by_code(code)
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.USER_NOT_FOUND
            ) from None
        load = self._enrollment_repository.first_enrollment_event(user.pk)
        if load is None:
            raise AnonymousEnrollmentError(AnonymousEnrollmentErrorCode.NO_ENROLLMENTS)
        return load

    def event_slug_by_id(self, event_id: int) -> str | None:
        return self._enrollment_repository.event_slug_by_id(event_id)

    def _validate(
        self, enrollment_request: AnonymousEnrollmentRequestDTO
    ) -> tuple[AnonymousSessionContextDTO, UserDTO]:
        session = self._session_context(enrollment_request)
        return session, self._user_for(enrollment_request, session)

    def _session_context(
        self, enrollment_request: AnonymousEnrollmentRequestDTO
    ) -> AnonymousSessionContextDTO:
        request = enrollment_request
        try:
            raw_session = self._enrollment_repository.read_session(
                session_id=request.session_id,
                event_slug=request.event_slug,
                site_id=request.site_id,
            )
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.SESSION_NOT_FOUND
            ) from None
        policy = EnrollmentPolicy.for_anonymous(raw_session.eligible_windows)
        session = AnonymousSessionContextDTO.from_session(
            session=raw_session,
            allows_anonymous_enrollment=(
                raw_session.has_agenda_item and policy.can_enroll
            ),
            effective_participants_limit=policy.effective_participants_limit(
                participants_limit=raw_session.participants_limit
            ),
        )
        if (
            request.anonymous_event_id is None
            or session.event_id != request.anonymous_event_id
        ):
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.NOT_FOR_THIS_SESSION,
                event_slug=self._anonymous_event_slug(request),
            )
        return session

    def _require_open(
        self,
        session: AnonymousSessionContextDTO,
        request: AnonymousEnrollmentRequestDTO,
    ) -> None:
        if not session.has_agenda_item:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.NO_ENROLLMENT_CONFIG,
                event_slug=self._anonymous_event_slug(request),
            )
        if not session.allows_anonymous_enrollment:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED,
                event_slug=session.event_slug,
            )

    def _user_for(
        self,
        enrollment_request: AnonymousEnrollmentRequestDTO,
        session: AnonymousSessionContextDTO,
    ) -> UserDTO:
        request = enrollment_request
        if not request.code:
            raise AnonymousEnrollmentError(AnonymousEnrollmentErrorCode.SESSION_EXPIRED)
        try:
            user = self.get_user_by_code(request.code)
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.USER_NOT_FOUND
            ) from None
        if (
            not session.has_agenda_item
            and self._enrollment_repository.read_participation_status(
                session_id=session.session_id, user_id=user.pk
            )
            is None
        ):
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.NO_ENROLLMENT_CONFIG,
                event_slug=self._anonymous_event_slug(request),
            )
        return user

    def _anonymous_event_slug(
        self, enrollment_request: AnonymousEnrollmentRequestDTO
    ) -> str | None:
        if enrollment_request.anonymous_event_id is None:
            return None
        return self._enrollment_repository.event_slug_by_id(
            enrollment_request.anonymous_event_id
        )

    def _update_name(self, user: UserDTO, name: str) -> None:
        if name:
            user.name = name
            self._user_repository.update(user.slug, UserData(name=name))
        if not user.name:
            raise AnonymousEnrollmentError(AnonymousEnrollmentErrorCode.NAME_REQUIRED)
