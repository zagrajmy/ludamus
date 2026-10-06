"""Crowd subdomain business logic.

Profiles and account lifecycle. Django-free; receives specific repo protocols
plus a transaction. First feature: claiming a managed profile.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, assert_never

from ludamus.mills.slugs import slug_base, unique_slug
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    MAX_AVATAR_URL_LENGTH,
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
    LoginDTO,
    ProfileServiceProtocol,
    RedeemOutcome,
    UserData,
    UserType,
    VerificationRequestOutcome,
)
from ludamus.pacts.services import DatabaseConstraintError
from ludamus.specs.email_verification import (
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
        IdentityDTO,
        IdentityProviderProtocol,
        ProfileParticipationRepositoryProtocol,
        SphereDomainRepositoryProtocol,
        UserDTO,
        UserRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

type _Effect = Literal["cancel", "promote", "verify"]


logger = logging.getLogger(__name__)

AUTH0_USERNAME_PREFIX = "auth0|"
WORKOS_USERNAME_PREFIX = "workos|"


def _token() -> str:
    return secrets.token_urlsafe(48)


def build_anonymous_user(slug: str, name: str = "") -> UserData:
    # The single recipe for throwaway ANONYMOUS accounts (code-based
    # self-enrollment, +N headcount guests); only the slug/name vary.
    return UserData(
        username=f"anon_{secrets.token_urlsafe(8).lower()}",
        slug=slug,
        name=name,
        user_type=UserType.ANONYMOUS,
        is_active=False,
    )


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


class LegacyAccountLinker:
    """Finds the Auth0-era account behind a first WorkOS login and claims it.

    TODO: https://github.com/zagrajmy/ludamus/issues/1402 — delete once no
    active account is left on an auth0| username.
    """

    def __init__(self, *, users: UserRepositoryProtocol) -> None:
        self._users = users

    def adopt(self, identity: IdentityDTO, *, username: str) -> UserDTO | None:
        if (legacy := self._find(identity)) is None:
            return None
        self._users.update(legacy.slug, {"username": username})
        logger.info("Linked legacy account %s to %s", legacy.slug, username)
        return self._users.read(legacy.slug)

    def _find(self, identity: IdentityDTO) -> UserDTO | None:
        # The import's external_id is authoritative: when it is set but its
        # account is gone, an email match would land on someone else's row.
        if identity.legacy_id:
            with suppress(NotFoundError):
                return self._users.read_by_username(
                    f"{AUTH0_USERNAME_PREFIX}{identity.legacy_id}"
                )
            return None
        if not identity.email_verified or not identity.email:
            return None
        with suppress(NotFoundError):
            user = self._users.read_by_email(identity.email)
            if user.username.startswith(AUTH0_USERNAME_PREFIX):
                # SAFETY: Auth0 never verified the stored address, so this
                # match is weaker than external_id; keep it visible.
                logger.warning("Linking legacy account %s by verified email", user.slug)
                return user
        return None


class CrowdAuthService(CrowdAuthServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        users: UserRepositoryProtocol,
        spheres: SphereDomainRepositoryProtocol,
        claims: ClaimServiceProtocol,
        identity: IdentityProviderProtocol,
        legacy_accounts: LegacyAccountLinker,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._spheres = spheres
        self._claims = claims
        self._identity = identity
        self._legacy_accounts = legacy_accounts

    def login_url(self, *, redirect_uri: str, state: str, sign_up: bool) -> str:
        return self._identity.authorization_url(
            redirect_uri=redirect_uri, state=state, sign_up=sign_up
        )

    def logout_url(self, *, session_id: str, return_to: str) -> str:
        return self._identity.logout_url(session_id=session_id, return_to=return_to)

    def complete_login(self, *, code: str, claim_token: str = "") -> LoginDTO:
        authentication = self._identity.authenticate(code)
        identity = authentication.identity
        username = f"{WORKOS_USERNAME_PREFIX}{identity.provider_user_id}"
        avatar_url = _avatar_url(identity)
        with self._transaction.atomic():
            user = self._read_by_username(username) or self._legacy_accounts.adopt(
                identity, username=username
            )
            claim_outcome: ClaimOutcome | None = None
            if claim_token:
                result = self._claims.redeem(token=claim_token, username=username)
                claim_outcome = result.outcome
                if result.outcome == ClaimOutcome.CONVERTED:
                    user = self._users.read(result.user_slug)
            email_conflict = False
            if user is None:
                email_conflict = self._users.email_unavailable(
                    email=identity.email, now=datetime.now(UTC)
                )
                user = self._create_user(
                    username=username,
                    identity=identity,
                    email="" if email_conflict else identity.email,
                    avatar_url=avatar_url,
                )
            user = self._sync_identity(user, identity=identity, avatar_url=avatar_url)
        return LoginDTO(
            user=user,
            claim_outcome=claim_outcome,
            session_id=authentication.session_id,
            email_conflict=email_conflict,
        )

    def _read_by_username(self, username: str) -> UserDTO | None:
        with suppress(NotFoundError):
            return self._users.read_by_username(username)
        return None

    def _create_user(
        self, *, username: str, identity: IdentityDTO, email: str, avatar_url: str
    ) -> UserDTO:
        # NOTE: the slug is unique table-wide, so a CONNECTED or ANONYMOUS
        # row can own the one the provider id slugifies to; uniquifying also
        # caps it to the SlugField width, which an over-long id would blow.
        slug = unique_slug(
            base=slug_base(identity.provider_user_id),
            default="user",
            exists=self._users.slug_exists,
        )
        data = UserData(
            slug=slug,
            username=username,
            email=email,
            email_verified=bool(email and identity.email_verified),
            avatar_url=avatar_url,
            name=identity.name,
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
                return self._users.read_by_username(username)
            raise
        return self._users.read_by_username(username)

    def _sync_identity(
        self, user: UserDTO, *, identity: IdentityDTO, avatar_url: str
    ) -> UserDTO:
        updates = UserData()
        if avatar_url and user.avatar_url != avatar_url:
            updates["avatar_url"] = avatar_url
        if identity.name and not user.name.strip():
            updates["name"] = identity.name
        updates.update(
            self._email_updates(
                user=user,
                claim_email=identity.email,
                claim_verified=identity.email_verified,
            )
        )
        if not updates:
            return user
        self._users.update(user.slug, updates)
        return self._users.read(user.slug)

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


def _avatar_url(identity: IdentityDTO) -> str:
    # A URL truncated to the column width would be broken; better no avatar.
    if len(identity.avatar_url) > MAX_AVATAR_URL_LENGTH:
        logger.warning(
            "Identity avatar dropped: %s chars exceeds %s",
            len(identity.avatar_url),
            MAX_AVATAR_URL_LENGTH,
        )
        return ""
    return identity.avatar_url


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
                        action=EmailVerificationAction.CANCEL,
                        user_id=user.pk,
                        address=address,
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
        if self._effect(user, payload) is None:
            return None
        return EmailLinkDTO(action=payload.action, address=payload.address)

    def redeem(self, token: str) -> RedeemOutcome:
        if (resolved := self._resolve(token)) is None:
            return RedeemOutcome.EXPIRED
        user, payload = resolved
        match effect := self._effect(user, payload):
            case None:
                return RedeemOutcome.ALREADY_USED
            case "cancel":
                with self._transaction.atomic():
                    self._users.update(user.slug, UserData(pending_email=""))
                return RedeemOutcome.CANCELLED
            case "promote":
                return self._promote_pending(user)
            case "verify":
                with self._transaction.atomic():
                    self._users.update(user.slug, UserData(email_verified=True))
                return RedeemOutcome.VERIFIED
            case _:
                assert_never(effect)

    def _resolve(self, token: str) -> tuple[UserDTO, EmailTokenPayload] | None:
        if (payload := self._tokens.loads(token)) is None:
            return None
        try:
            user = self._users.read_by_id(payload.user_id)
        except NotFoundError:
            return None
        return user, payload

    @staticmethod
    def _effect(user: UserDTO, payload: EmailTokenPayload) -> _Effect | None:
        if not payload.address:
            return None
        if payload.address == user.pending_email:
            if payload.action is EmailVerificationAction.CANCEL:
                return "cancel"
            return "promote"
        if (
            payload.action is EmailVerificationAction.CONFIRM
            and payload.address == user.email
            and not user.email_verified
        ):
            return "verify"
        return None

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
                action=EmailVerificationAction.CONFIRM, user_id=user.pk, address=address
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
            has_provider_avatar=bool(user.avatar_url),
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
