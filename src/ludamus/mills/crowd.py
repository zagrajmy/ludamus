"""Crowd subdomain business logic.

Profiles and account lifecycle. Django-free; receives specific repo protocols
plus a transaction. First feature: claiming a managed profile.
"""

from __future__ import annotations

import secrets
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.mills.slugs import unique_slug
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
    EmailVerificationServiceProtocol,
    ProfileServiceProtocol,
    RedeemOutcome,
    RedeemResultDTO,
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
        if self._users.email_unavailable(
            email=data.get("email", ""), now=datetime.now(UTC)
        ):
            data["email"] = ""
            data["email_verified"] = False
            email_conflict = True
        # NOTE: the slug is unique table-wide, so a CONNECTED or ANONYMOUS
        # row can own the one the provider sub slugifies to; uniquifying also
        # caps it to the SlugField width, which an over-long sub would blow.
        data["slug"] = unique_slug(
            base=data.get("slug", ""), default="user", exists=self._users.slug_exists
        )
        try:
            with self._transaction.savepoint():
                self._users.create(data)
        except DatabaseConstraintError:
            # NOTE: a concurrent callback for the same identity may have
            # inserted the row between our read_by_username miss and this
            # insert; adopt it. With no such row the insert failed for a real
            # reason, so let the database error surface, not a NotFoundError.
            with suppress(NotFoundError):
                return self._users.read_by_username(username), email_conflict
            raise
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
        updates.update(
            self._email_updates(
                user=user, claim_email=claim_email, claim_verified=claim_verified
            )
        )
        return updates

    def _email_updates(
        self, *, user: UserDTO, claim_email: str, claim_verified: bool
    ) -> UserData:
        if not claim_email:
            return UserData()
        if claim_email == user.email:
            proves_stored = claim_verified and not user.email_verified
            return UserData(email_verified=True) if proves_stored else UserData()
        # A verified stored address is the user's deliberate choice; the
        # provider's claim must not revert it on the next login.
        keep_stored = bool(user.email and user.email_verified)
        taken = self._users.email_unavailable(
            email=claim_email, now=datetime.now(UTC), exclude_slug=user.slug
        )
        if keep_stored or taken:
            return UserData()
        # The claim replaces the address, so a confirm link still out for a
        # pending one is stale — drop the reservation before redeeming it
        # could overwrite what the provider just proved.
        return UserData(
            email=claim_email, email_verified=claim_verified, pending_email=""
        )

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
        reminders: EmailVerificationReminderRepositoryProtocol,
        tokens: EmailTokenCodecProtocol,
        notifier: EmailVerificationNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._reminders = reminders
        self._tokens = tokens
        self._notifier = notifier

    def request_verification(self, user_slug: str) -> VerificationRequestOutcome:
        return self._request(self._users.read(user_slug), now=datetime.now(UTC))

    def count_due(self, *, now: datetime) -> int:
        return self._reminders.count_due(
            now=now, interval=EMAIL_VERIFICATION_REMINDER_INTERVAL
        )

    def send_due_reminders(self, *, now: datetime) -> int:
        # The sweep re-runs the request rather than re-mailing the link already
        # on the row: links live 24 hours and the re-nag interval is longer, so
        # the stored one is dead, and stamping the column here would race the
        # resend throttle.
        return sum(
            self._request(user, now=now) is VerificationRequestOutcome.SENT
            for user in self._reminders.list_due(
                now=now, interval=EMAIL_VERIFICATION_REMINDER_INTERVAL
            )
        )

    def _request(self, user: UserDTO, *, now: datetime) -> VerificationRequestOutcome:
        target = user.pending_email or ("" if user.email_verified else user.email)
        if not target:
            return VerificationRequestOutcome.NOT_NEEDED
        with self._transaction.atomic():
            # The throttle is claimed, not read: `user` is a snapshot the sweep
            # may have taken before a resend stamped the row, so checking it
            # here would let both send.
            if not self._users.claim_verification_send(
                user_slug=user.slug,
                now=now,
                throttle=EMAIL_VERIFICATION_RESEND_THROTTLE,
            ):
                return VerificationRequestOutcome.THROTTLED
            self._send_confirm_link(user=user, address=target)
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
        if self._users.email_unavailable(
            email=address, now=datetime.now(UTC), exclude_slug=user_slug
        ):
            return ChangeRequestOutcome.TAKEN
        # A fresh change is deliberate intent, so it skips the resend
        # throttle — otherwise correcting a typo'd address would be blocked
        # by the mail just sent to the typo.
        with self._transaction.atomic():
            self._users.update(
                user_slug,
                UserData(
                    pending_email=address, email_verification_sent_at=datetime.now(UTC)
                ),
            )
            self._send_confirm_link(user=user, address=address)
            # The cancel link is the whole point of this notice, so it goes
            # only to an address someone proved they control.
            if user.deliverable_email:
                cancel_token = self._tokens.dumps(
                    EmailTokenPayload(
                        act=EmailVerificationAction.CANCEL, uid=user.pk, addr=address
                    )
                )
                self._notifier.notify_email_change_requested(
                    EmailChangeRequestedNotification(
                        recipient_user_id=user.pk,
                        recipient_email=user.deliverable_email,
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

    def redeem(self, token: str) -> RedeemResultDTO:
        if (resolved := self._resolve(token)) is None:
            return RedeemResultDTO(outcome=RedeemOutcome.EXPIRED)
        user, payload = resolved
        return RedeemResultDTO(outcome=self._redeem(user, payload), action=payload.act)

    def _redeem(self, user: UserDTO, payload: EmailTokenPayload) -> RedeemOutcome:
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
                if user.deliverable_email:
                    self._notifier.notify_email_change_completed(
                        EmailChangeCompletedNotification(
                            recipient_user_id=user.pk,
                            recipient_email=user.deliverable_email,
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

    def _send_confirm_link(self, *, user: UserDTO, address: str) -> None:
        # The caller owns the send stamp: `_request` claims it as its throttle,
        # a change writes it alongside the pending address.
        token = self._tokens.dumps(
            EmailTokenPayload(
                act=EmailVerificationAction.CONFIRM, uid=user.pk, addr=address
            )
        )
        self._notifier.notify_email_verification(
            EmailVerificationNotification(
                recipient_user_id=user.pk, recipient_email=address, token=token
            )
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
