"""Crowd subdomain contracts.

User identity (DTOs, data, repository protocols) and account lifecycle.
First lifecycle feature: claiming a managed companion profile — turning a
login-less companion row into the intended person's own self-login account,
on the same row, so enrollment history is preserved.
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.ids import UserId

MAX_CONNECTED_USERS = 6  # Maximum number of connected users per manager
MAX_AVATAR_URL_LENGTH = 500  # Column width; a longer provider URL is dropped

# Signed verification links live this long. Shared contract: the token codec
# enforces it on read, and the repository's pending-address reservation
# (`email_unavailable`) expires with it, so nothing needs a cleanup job.
EMAIL_LINK_MAX_AGE = timedelta(hours=24)


class UserType(StrEnum):
    ACTIVE = "active"
    CONNECTED = "connected"
    ANONYMOUS = "anonymous"


class UserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    avatar_url: str
    date_joined: datetime
    discord_username: str
    email: str
    email_verified: bool = False
    email_verification_sent_at: datetime | None = None
    pending_email: str = ""
    full_name: str
    is_active: bool
    is_authenticated: bool
    is_staff: bool
    is_superuser: bool
    name: str
    pk: UserId
    slug: str
    use_gravatar: bool
    user_type: UserType
    username: str

    @property
    def deliverable_email(self) -> str:
        # The notifier resolves the proven address for every other mail; the
        # email-lifecycle notices need it up front, because they decide
        # whether to raise a notification at all from it.
        return self.email if self.email_verified else ""


class CompanionDTO(UserDTO):
    # The claim token is a bearer credential for taking over the profile, so
    # it lives only on the manager-facing companion read model — never on
    # the app-wide UserDTO.
    claim_token: str = ""


class UserData(TypedDict, total=False):
    avatar_url: str
    discord_username: str
    email: str
    email_verified: bool
    email_verification_sent_at: datetime | None
    pending_email: str
    is_active: bool
    name: str
    password: str
    slug: str
    use_gravatar: bool
    user_type: UserType
    username: str


class UserRepositoryProtocol(Protocol):
    @staticmethod
    def create(user_data: UserData) -> None: ...
    def read(self, slug: str) -> UserDTO: ...
    def read_by_id(self, pk: int) -> UserDTO: ...
    def read_by_ids(self, pks: list[int]) -> list[UserDTO]: ...
    def read_by_username(self, username: str) -> UserDTO: ...
    @staticmethod
    def update(user_slug: str, user_data: UserData) -> None: ...
    @staticmethod
    def email_unavailable(
        *, email: str, now: datetime, exclude_slug: str | None = None
    ) -> bool: ...
    @staticmethod
    def claim_verification_send(
        *, user_slug: str, now: datetime, throttle: timedelta
    ) -> bool: ...
    @staticmethod
    def slug_exists(slug: str) -> bool: ...


class CompanionRepositoryProtocol(Protocol):
    @staticmethod
    def create(manager_slug: str, user_data: UserData) -> None: ...
    @staticmethod
    def read_all(manager_slug: str) -> list[CompanionDTO]: ...
    @staticmethod
    def read(manager_slug: str, user_slug: str) -> CompanionDTO: ...
    @staticmethod
    def delete(manager_slug: str, user_slug: str) -> None: ...
    @staticmethod
    def update(manager_slug: str, user_slug: str, user_data: UserData) -> None: ...


class ClaimableProfileDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    slug: str
    manager_name: str


class ClaimOutcome(StrEnum):
    CONVERTED = "converted"
    ALREADY_AUTHENTICATED = "already_authenticated"
    INVALID = "invalid"


class ClaimResultDTO(BaseModel):
    outcome: ClaimOutcome
    user_slug: str = ""


class ClaimRepositoryProtocol(Protocol):
    @staticmethod
    def issue_token(*, manager_slug: str, user_slug: str, token: str) -> bool: ...
    @staticmethod
    def read_claimable(token: str) -> ClaimableProfileDTO | None: ...
    @staticmethod
    def username_exists(username: str) -> bool: ...
    @staticmethod
    def convert(*, token: str, username: str) -> str | None: ...


class ClaimServiceProtocol(Protocol):
    def issue(self, *, manager_slug: str, user_slug: str) -> str | None: ...
    def read_claimable(self, token: str) -> ClaimableProfileDTO | None: ...
    def redeem(self, *, token: str, username: str) -> ClaimResultDTO: ...


class SphereDomainRepositoryProtocol(Protocol):
    @staticmethod
    def domain_exists(domain: str) -> bool: ...


class AuthProvisionDTO(BaseModel):
    user: UserDTO
    claim_outcome: ClaimOutcome | None = None
    # The provider's address collided with another account's, so the new
    # account was created without one; the login callback tells the user.
    email_conflict: bool = False


class CrowdAuthServiceProtocol(Protocol):
    def provision_user(
        self, *, username: str, create_data: UserData, claim_token: str = ""
    ) -> AuthProvisionDTO: ...
    def sync_identity(self, *, user_slug: str, data: UserData) -> UserDTO: ...
    def is_known_sphere_domain(self, domain: str) -> bool: ...


class ProfileParticipationRepositoryProtocol(Protocol):
    @staticmethod
    def confirmed_count(user_id: int) -> int: ...


class AvatarUrlProviderProtocol(Protocol):
    def __call__(self, email: str) -> str | None: ...


class AvatarPageDTO(BaseModel):
    user: UserDTO
    gravatar_url: str | None
    has_auth0_avatar: bool


class ProfileServiceProtocol(Protocol):
    def read(self, user_slug: str) -> UserDTO: ...
    def confirmed_participations_count(self, user_id: int) -> int: ...
    def update(self, user_slug: str, data: UserData) -> None: ...
    def read_avatar(self, user_slug: str) -> AvatarPageDTO: ...
    def set_avatar_preference(self, user_slug: str, *, use_gravatar: bool) -> None: ...


class EmailVerificationAction(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"


class EmailTokenPayload(BaseModel):
    # `act` and `addr` are signed in, so a link only performs the action it
    # was minted for and only against the address it was mailed to.
    act: EmailVerificationAction
    uid: int
    addr: str


class EmailTokenCodecProtocol(Protocol):
    @staticmethod
    def dumps(payload: EmailTokenPayload) -> str: ...
    @staticmethod
    def loads(token: str) -> EmailTokenPayload | None: ...


class RedeemOutcome(StrEnum):
    VERIFIED = "verified"
    CHANGE_APPLIED = "change_applied"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ALREADY_USED = "already_used"
    ADDRESS_TAKEN = "address_taken"


class VerificationRequestOutcome(StrEnum):
    SENT = "sent"
    THROTTLED = "throttled"
    NOT_NEEDED = "not_needed"


class ChangeRequestOutcome(StrEnum):
    REQUESTED = "requested"
    UNCHANGED = "unchanged"
    CLEARED = "cleared"
    TAKEN = "taken"


class EmailLinkDTO(BaseModel):
    action: EmailVerificationAction
    address: str


class RedeemResultDTO(BaseModel):
    outcome: RedeemOutcome
    # None only when the token did not resolve at all, so there is no signed
    # action to name.
    action: EmailVerificationAction | None = None


class EmailVerificationNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    token: str


class EmailChangeRequestedNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str  # the pre-change address
    new_address: str
    cancel_token: str


class EmailChangeCompletedNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str  # the pre-change address
    new_address: str


class EmailVerificationNotifierProtocol(Protocol):
    def notify_email_verification(
        self, notification: EmailVerificationNotification
    ) -> None: ...
    def notify_email_change_requested(
        self, notification: EmailChangeRequestedNotification
    ) -> None: ...
    def notify_email_change_completed(
        self, notification: EmailChangeCompletedNotification
    ) -> None: ...


class EmailVerificationServiceProtocol(Protocol):
    def request_verification(self, user_slug: str) -> VerificationRequestOutcome: ...
    def count_due(self, *, now: datetime) -> int: ...
    def send_due_reminders(self, *, now: datetime) -> int: ...
    def request_change(
        self, *, user_slug: str, new_address: str
    ) -> ChangeRequestOutcome: ...
    def describe(self, token: str) -> EmailLinkDTO | None: ...
    def redeem(self, token: str) -> RedeemResultDTO: ...


class EmailVerificationReminderRepositoryProtocol(Protocol):
    @staticmethod
    def count_due(*, now: datetime, interval: timedelta) -> int: ...
    @staticmethod
    def list_due(*, now: datetime, interval: timedelta) -> list[UserDTO]: ...


class CompanionsServiceProtocol(Protocol):
    def list_companions(self, manager_slug: str) -> list[CompanionDTO]: ...
    def read(self, *, manager_slug: str, user_slug: str) -> CompanionDTO: ...
    def create(self, *, manager_slug: str, user_data: UserData) -> None: ...
    def update(
        self, *, manager_slug: str, user_slug: str, user_data: UserData
    ) -> None: ...
    def delete(self, *, manager_slug: str, user_slug: str) -> None: ...
