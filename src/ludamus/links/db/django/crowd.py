from typing import TYPE_CHECKING

from django.contrib.auth.hashers import make_password

from ludamus.links.db.django.companions import active_companions, sponsor_of
from ludamus.links.db.django.models import (
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    ClaimableProfileDTO,
    ClaimRepositoryProtocol,
    CompanionDTO,
    CompanionRepositoryProtocol,
    ProfileParticipationRepositoryProtocol,
    UserData,
    UserDTO,
    UserRepositoryProtocol,
    UserType,
)
from ludamus.pacts.party import PartyConsentMode

if TYPE_CHECKING:

    from ludamus.links.db.django.models import User
else:
    from django.contrib.auth import get_user_model

    User = get_user_model()


class UserRepository(UserRepositoryProtocol):
    def __init__(self, user_type: UserType) -> None:
        self._user_type = user_type

    @staticmethod
    def create(user_data: UserData) -> None:
        User.objects.create(**user_data)

    def read(self, slug: str) -> UserDTO:
        try:
            user = User.objects.get(slug=slug, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception

        return UserDTO.model_validate(user)

    def read_by_id(self, pk: int) -> UserDTO:
        try:
            user = User.objects.get(pk=pk, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(user)

    def read_by_ids(self, pks: list[int]) -> list[UserDTO]:
        return [
            UserDTO.model_validate(user)
            for user in User.objects.filter(
                pk__in=pks, user_type=self._user_type
            ).order_by("pk")
        ]

    def read_by_username(self, username: str) -> UserDTO:
        try:
            user = User.objects.get(username=username, user_type=self._user_type)
        except User.DoesNotExist as exception:
            raise NotFoundError from exception
        return UserDTO.model_validate(user)

    @staticmethod
    def update(user_slug: str, user_data: UserData) -> None:
        User.objects.filter(slug=user_slug).update(**user_data)

    @staticmethod
    def email_exists(email: str, exclude_slug: str | None = None) -> bool:
        if not email:
            return False

        query = User.objects.filter(email__iexact=email)
        if exclude_slug:
            query = query.exclude(slug=exclude_slug)

        return query.exists()


class CompanionRepository(CompanionRepositoryProtocol):
    @staticmethod
    def read_all(manager_slug: str) -> list[CompanionDTO]:
        if not User.objects.filter(
            user_type=UserType.ACTIVE, slug=manager_slug
        ).exists():
            raise NotFoundError

        return [
            CompanionDTO.model_validate(companion)
            for companion in active_companions(manager_slug).order_by("pk")
        ]

    @staticmethod
    def create(manager_slug: str, user_data: UserData) -> None:
        manager = User.objects.get(user_type=UserType.ACTIVE, slug=manager_slug)
        User.objects.create(**user_data, manager=manager)

    @staticmethod
    def read(manager_slug: str, user_slug: str) -> CompanionDTO:
        companion = active_companions(manager_slug).filter(slug=user_slug).first()
        if companion is None:
            raise NotFoundError
        return CompanionDTO.model_validate(companion)

    @staticmethod
    def update(manager_slug: str, user_slug: str, user_data: UserData) -> None:
        User.objects.filter(
            pk__in=active_companions(manager_slug).filter(slug=user_slug)
        ).update(**user_data)

    @staticmethod
    def delete(manager_slug: str, user_slug: str) -> None:
        companions = active_companions(manager_slug)
        if (user := companions.filter(slug=user_slug).first()) is None:
            raise NotFoundError
        user.delete()


class ProfileStatsRepository(ProfileParticipationRepositoryProtocol):
    @staticmethod
    def confirmed_count(user_id: int) -> int:
        return SessionParticipation.objects.filter(
            user_id=user_id, status=SessionParticipationStatus.CONFIRMED
        ).count()


class ClaimRepository(ClaimRepositoryProtocol):
    @staticmethod
    def issue_token(*, manager_slug: str, user_slug: str, token: str) -> bool:
        updated = User.objects.filter(
            pk__in=active_companions(manager_slug).filter(slug=user_slug)
        ).update(claim_token=token)
        return bool(updated)

    @staticmethod
    def read_claimable(token: str) -> ClaimableProfileDTO | None:
        if not token:
            return None
        user = User.objects.filter(
            claim_token=token, user_type=UserType.CONNECTED
        ).first()
        if user is None:
            return None
        sponsor = sponsor_of(user)
        return ClaimableProfileDTO(
            name=user.name, slug=user.slug, manager_name=sponsor.name if sponsor else ""
        )

    @staticmethod
    def username_exists(username: str) -> bool:
        return User.objects.filter(username=username).exists()

    @staticmethod
    def convert(*, token: str, username: str) -> str | None:
        # Email/avatar from the provider are applied afterwards by the login
        # callback's _apply_user_updates (with its own collision handling), so
        # this stays a pure identity flip and never duplicates that rule.
        # A single conditional UPDATE (like issue_token) keeps redemption
        # atomic: of two concurrent redeems, exactly one matches the token.
        # Guard the sentinel: every non-claimed row carries claim_token="",
        # so an empty token must never reach the filter below.
        if not token:
            return None
        updated = User.objects.filter(
            claim_token=token, user_type=UserType.CONNECTED
        ).update(
            username=username,
            user_type=UserType.ACTIVE,
            manager=None,
            password=make_password(None),
            claim_token="",
        )
        if not updated:
            return None
        user = User.objects.get(username=username)
        # The claimed member keeps their seat in the party but now has a login
        # and a say: further enrollments by the leader need their accept (O-9).
        PartyMembership.objects.filter(member=user).update(
            consent_mode=PartyConsentMode.ACCEPT_INVITES
        )
        return user.slug
