"""Crowd subdomain business logic.

Profiles and account lifecycle. Django-free; receives specific repo protocols
plus a transaction. First feature: claiming a managed profile.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    AuthProvisionDTO,
    AvatarPageDTO,
    ChangeRequestOutcome,
    ClaimOutcome,
    ClaimResultDTO,
    ClaimServiceProtocol,
    CompanionsServiceProtocol,
    CrowdAuthServiceProtocol,
    EmailChangeCompletedNotification,
    EmailChangeRequestedNotification,
    EmailLinkDTO,
    EmailTokenPayload,
    EmailVerificationAction,
    EmailVerificationNotification,
    EmailVerificationReminderServiceProtocol,
    EmailVerificationServiceProtocol,
    ProfileServiceProtocol,
    RedeemOutcome,
    UserData,
    VerificationRequestOutcome,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.specs.crowd import (
    EMAIL_VERIFICATION_REMINDER_INTERVAL,
    EMAIL_VERIFICATION_RESEND_THROTTLE,
)

if TYPE_CHECKING:
    from ludamus.pacts.crowd import (
        AvatarUrlProviderProtocol,
        ClaimableProfileDTO,
        ClaimRepositoryProtocol,
        CompanionDTO,
        CompanionRepositoryProtocol,
        EmailTokenCodecProtocol,
        EmailVerificationNotifierProtocol,
        EmailVerificationReminderRepositoryProtocol,
        ProfileParticipationRepositoryProtocol,
        SphereDomainRepositoryProtocol,
        UserDTO,
        UserRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


def _token() -> str:
    return secrets.token_urlsafe(48)


class ClaimService(ClaimServiceProtocol):
    """Issue and redeem links that turn a managed profile into a real account."""

    def __init__(
        self, transaction: TransactionProtocol, claims: ClaimRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._claims = claims

    def issue(self, *, manager_slug: str, user_slug: str) -> str | None:
        token = _token()
        with self._transaction.atomic():
            if not self._claims.issue_token(
                manager_slug=manager_slug, user_slug=user_slug, token=token
            ):
                return None
        return token

    def read_claimable(self, token: str) -> ClaimableProfileDTO | None:
        return self._claims.read_claimable(token)

    def redeem(self, *, token: str, username: str) -> ClaimResultDTO:
        with self._transaction.atomic():
            # The recipient already authenticates as someone else; converting
            # this row would collide on the unique username. Refusing keeps the
            # same-row conversion clean — merging into an existing account is a
            # deliberate non-goal for now.
            if self._claims.username_exists(username):
                return ClaimResultDTO(outcome=ClaimOutcome.ALREADY_AUTHENTICATED)
            # convert returns None for an unknown/spent token, so it is the sole
            # authority on validity — no separate read-back probe.
            if (slug := self._claims.convert(token=token, username=username)) is None:
                return ClaimResultDTO(outcome=ClaimOutcome.INVALID)
            return ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug=slug)


class CrowdAuthService(CrowdAuthServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        users: UserRepositoryProtocol,
        spheres: SphereDomainRepositoryProtocol,
        claims: ClaimServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._spheres = spheres
        self._claims = claims

    def provision_user(
        self, *, username: str, create_data: UserData, claim_token: str = ""
    ) -> AuthProvisionDTO:
        claim_outcome: ClaimOutcome | None = None
        if claim_token:
            result = self._claims.redeem(token=claim_token, username=username)
            claim_outcome = result.outcome
            if result.outcome == ClaimOutcome.CONVERTED:
                return AuthProvisionDTO(
                    user=self._users.read(result.user_slug), claim_outcome=claim_outcome
                )
        email_conflict = False
        try:
            user = self._users.read_by_username(username)
        except NotFoundError:
            user, email_conflict = self._create_user(
                username=username, create_data=create_data
            )
        return AuthProvisionDTO(
            user=user, claim_outcome=claim_outcome, email_conflict=email_conflict
        )

    def _create_user(
        self, *, username: str, create_data: UserData
    ) -> tuple[UserDTO, bool]:
        data = create_data.copy()
        email_conflict = False
        if self._users.email_exists(data.get("email", "")):
            data["email"] = ""
            data["email_verified"] = False
            email_conflict = True
        try:
            with self._transaction.savepoint():
                self._users.create(data)
        except DatabaseConstraintError:
            # A concurrent callback for the same identity inserted the row
            # between our read_by_username miss and this insert; adopt it.
            pass
        return self._users.read_by_username(username), email_conflict

    def sync_identity(self, *, user_slug: str, data: UserData) -> UserDTO:
        user = self._users.read(user_slug)
        if updates := self._identity_updates(user=user, data=data):
            with self._transaction.atomic():
                self._users.update(user_slug, updates)
            return self._users.read(user_slug)
        return user

    def _identity_updates(self, *, user: UserDTO, data: UserData) -> UserData:
        updates = data.copy()
        claim_email = updates.pop("email", "")
        claim_verified = updates.pop("email_verified", False)
        if updates.get("avatar_url") == user.avatar_url:
            updates.pop("avatar_url", None)
        if "name" in updates and (user.name or "").strip():
            del updates["name"]
        if claim_email and claim_email != user.email:
            # A verified stored address is the user's deliberate choice; the
            # provider's claim must not revert it on the next login.
            keep_stored = bool(user.email and user.email_verified)
            taken = self._users.email_exists(claim_email, exclude_slug=user.slug)
            if not keep_stored and not taken:
                updates["email"] = claim_email
                updates["email_verified"] = claim_verified
        elif claim_email and claim_verified and not user.email_verified:
            updates["email_verified"] = True
        return updates

    def is_known_sphere_domain(self, domain: str) -> bool:
        return self._spheres.domain_exists(domain)


class EmailVerificationService(EmailVerificationServiceProtocol):
    """Prove control of an email address via signed, single-use links.

    The link is a signed payload (action, user, address) — no token column.
    Single-use falls out of the state check redemption runs anyway: a spent
    link no longer matches `email` / `pending_email` and lands on the same
    page as an expired one.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        users: UserRepositoryProtocol,
        tokens: EmailTokenCodecProtocol,
        notifier: EmailVerificationNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._tokens = tokens
        self._notifier = notifier

    def request_verification(self, user_slug: str) -> VerificationRequestOutcome:
        user = self._users.read(user_slug)
        target = user.pending_email or ("" if user.email_verified else user.email)
        if not target:
            return VerificationRequestOutcome.NOT_NEEDED
        now = datetime.now(UTC)
        sent_at = user.email_verification_sent_at
        if sent_at and now - sent_at < EMAIL_VERIFICATION_RESEND_THROTTLE:
            return VerificationRequestOutcome.THROTTLED
        with self._transaction.atomic():
            self._send_confirm_link(user=user, address=target, now=now)
        return VerificationRequestOutcome.SENT

    def request_change(
        self, *, user_slug: str, new_address: str
    ) -> ChangeRequestOutcome:
        user = self._users.read(user_slug)
        address = new_address.strip()
        if address and address in {user.email, user.pending_email}:
            return ChangeRequestOutcome.UNCHANGED
        if not address:
            if not user.email and not user.pending_email:
                return ChangeRequestOutcome.UNCHANGED
            with self._transaction.atomic():
                self._users.update(
                    user_slug,
                    UserData(
                        email="",
                        email_verified=False,
                        pending_email="",
                        email_verification_sent_at=None,
                    ),
                )
            return ChangeRequestOutcome.CLEARED
        if self._users.email_exists(address, exclude_slug=user_slug):
            return ChangeRequestOutcome.TAKEN
        # A fresh change is deliberate intent, so it skips the resend
        # throttle — otherwise correcting a typo'd address would be blocked
        # by the mail just sent to the typo.
        with self._transaction.atomic():
            self._users.update(user_slug, UserData(pending_email=address))
            self._send_confirm_link(user=user, address=address, now=datetime.now(UTC))
            if user.email:
                cancel_token = self._tokens.dumps(
                    EmailTokenPayload(
                        act=EmailVerificationAction.CANCEL, uid=user.pk, addr=address
                    )
                )
                self._notifier.notify_email_change_requested(
                    EmailChangeRequestedNotification(
                        recipient_user_id=user.pk,
                        recipient_email=user.email,
                        new_address=address,
                        cancel_token=cancel_token,
                    )
                )
        return ChangeRequestOutcome.REQUESTED

    def describe(self, token: str) -> EmailLinkDTO | None:
        if (resolved := self._resolve(token)) is None:
            return None
        user, payload = resolved
        if not self._redeemable(user, payload):
            return None
        return EmailLinkDTO(action=payload.act, address=payload.addr)

    def redeem(self, token: str) -> RedeemOutcome:
        if (resolved := self._resolve(token)) is None:
            return RedeemOutcome.EXPIRED
        user, payload = resolved
        if not self._redeemable(user, payload):
            return RedeemOutcome.ALREADY_USED
        if payload.act is EmailVerificationAction.CANCEL:
            with self._transaction.atomic():
                self._users.update(user.slug, UserData(pending_email=""))
            return RedeemOutcome.CANCELLED
        if payload.addr == user.pending_email:
            return self._promote_pending(user)
        with self._transaction.atomic():
            self._users.update(user.slug, UserData(email_verified=True))
        return RedeemOutcome.VERIFIED

    def _resolve(self, token: str) -> tuple[UserDTO, EmailTokenPayload] | None:
        if (payload := self._tokens.loads(token)) is None:
            return None
        try:
            user = self._users.read_by_id(payload.uid)
        except NotFoundError:
            return None
        return user, payload

    @staticmethod
    def _redeemable(user: UserDTO, payload: EmailTokenPayload) -> bool:
        if payload.act is EmailVerificationAction.CANCEL:
            return bool(payload.addr) and payload.addr == user.pending_email
        return bool(payload.addr) and (
            payload.addr == user.pending_email
            or (payload.addr == user.email and not user.email_verified)
        )

    def _promote_pending(self, user: UserDTO) -> RedeemOutcome:
        address = user.pending_email
        try:
            with self._transaction.savepoint():
                self._users.update(
                    user.slug,
                    UserData(email=address, email_verified=True, pending_email=""),
                )
                if user.email:
                    self._notifier.notify_email_change_completed(
                        EmailChangeCompletedNotification(
                            recipient_user_id=user.pk,
                            recipient_email=user.email,
                            new_address=address,
                        )
                    )
        except DatabaseConstraintError:
            # Two accounts reserved the same address and the other one
            # promoted first; the reservation is dead, so drop it.
            with self._transaction.atomic():
                self._users.update(user.slug, UserData(pending_email=""))
            return RedeemOutcome.ADDRESS_TAKEN
        return RedeemOutcome.CHANGE_APPLIED if user.email else RedeemOutcome.VERIFIED

    def _send_confirm_link(self, *, user: UserDTO, address: str, now: datetime) -> None:
        token = self._tokens.dumps(
            EmailTokenPayload(
                act=EmailVerificationAction.CONFIRM, uid=user.pk, addr=address
            )
        )
        self._users.update(user.slug, UserData(email_verification_sent_at=now))
        self._notifier.notify_email_verification(
            EmailVerificationNotification(
                recipient_user_id=user.pk, recipient_email=address, token=token
            )
        )


class EmailVerificationReminderService(EmailVerificationReminderServiceProtocol):
    """Bulk re-nag sweep, kept apart from the request-scoped service.

    Every reminder goes through `request_verification`, never a copy of it:
    links live 24 hours and the re-nag interval is longer, so mailing "the
    link already on the row" would mail a dead one, and a sweep stamping the
    column itself would race the resend throttle.
    """

    def __init__(
        self,
        *,
        reminders: EmailVerificationReminderRepositoryProtocol,
        verification: EmailVerificationServiceProtocol,
    ) -> None:
        self._reminders = reminders
        self._verification = verification

    def count_due(self, *, now: datetime) -> int:
        return len(self._due(now))

    def send_due_reminders(self, *, now: datetime) -> int:
        sent = 0
        for slug in self._due(now):
            outcome = self._verification.request_verification(slug)
            sent += outcome == VerificationRequestOutcome.SENT
        return sent

    def _due(self, now: datetime) -> list[str]:
        return self._reminders.list_due(
            now=now, interval=EMAIL_VERIFICATION_REMINDER_INTERVAL
        )


class ProfileService(ProfileServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        users: UserRepositoryProtocol,
        participations: ProfileParticipationRepositoryProtocol,
        avatar_url: AvatarUrlProviderProtocol,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._participations = participations
        self._avatar_url = avatar_url

    def read(self, user_slug: str) -> UserDTO:
        return self._users.read(user_slug)

    def confirmed_participations_count(self, user_id: int) -> int:
        return self._participations.confirmed_count(user_id)

    def update(self, user_slug: str, data: UserData) -> None:
        with self._transaction.atomic():
            self._users.update(user_slug, data)

    def read_avatar(self, user_slug: str) -> AvatarPageDTO:
        user = self._users.read(user_slug)
        return AvatarPageDTO(
            user=user,
            gravatar_url=self._avatar_url(user.email),
            has_auth0_avatar=bool(user.avatar_url),
        )

    def set_avatar_preference(self, user_slug: str, *, use_gravatar: bool) -> None:
        with self._transaction.atomic():
            self._users.update(user_slug, UserData(use_gravatar=use_gravatar))


class CompanionsService(CompanionsServiceProtocol):
    def __init__(
        self, transaction: TransactionProtocol, companions: CompanionRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._companions = companions

    def list_companions(self, manager_slug: str) -> list[CompanionDTO]:
        return self._companions.read_all(manager_slug)

    def read(self, *, manager_slug: str, user_slug: str) -> CompanionDTO:
        return self._companions.read(manager_slug, user_slug)

    def create(self, *, manager_slug: str, user_data: UserData) -> None:
        with self._transaction.atomic():
            self._companions.create(manager_slug, user_data=user_data)

    def update(self, *, manager_slug: str, user_slug: str, user_data: UserData) -> None:
        with self._transaction.atomic():
            self._companions.update(manager_slug, user_slug, user_data)

    def delete(self, *, manager_slug: str, user_slug: str) -> None:
        with self._transaction.atomic():
            self._companions.delete(manager_slug, user_slug)
