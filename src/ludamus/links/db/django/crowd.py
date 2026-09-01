from typing import TYPE_CHECKING

from django.contrib.auth.hashers import make_password
from django.db.models import Q

from ludamus.links.db.django.companions import active_companions, sponsor_of
from ludamus.links.db.django.models import (
    PartyMembership,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    EMAIL_LINK_MAX_AGE,
    ClaimableProfileDTO,
    ClaimRepositoryProtocol,
    CompanionDTO,
    CompanionRepositoryProtocol,
    EmailVerificationReminderRepositoryProtocol,
    ProfileParticipationRepositoryProtocol,
    UserData,
    UserDTO,
    UserRepositoryProtocol,
    UserType,
)
from ludamus.pacts.party import PartyConsentMode

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from django.db.models import QuerySet

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
    def claim_verification_send(
        *, user_slug: str, now: datetime, throttle: timedelta
    ) -> bool:
        """Stamp the send column, reporting whether this caller won the slot.

        The check and the stamp are one conditional UPDATE, so a double-clicked
        resend racing the reminder sweep mails the link once.
        """
        cutoff = now - throttle
        return (
            User.objects.filter(slug=user_slug)
            .filter(
                Q(email_verification_sent_at__isnull=True)
                | Q(email_verification_sent_at__lte=cutoff)
            )
            .update(email_verification_sent_at=now)
            == 1
        )

    @staticmethod
    def email_unavailable(
        *, email: str, now: datetime, exclude_slug: str | None = None
    ) -> bool:
        """Report an address as taken by, or reserved for, another account."""
        if not email:
            return False

        # A pending address reserves the email only while its confirm link is
        # still provable; the reservation expires with the link, so a typo'd
        # change never blocks the address's real owner for good.
        still_provable = now - EMAIL_LINK_MAX_AGE
        query = User.objects.filter(
            Q(email__iexact=email)
            | Q(
                pending_email__iexact=email,
                email_verification_sent_at__gte=still_provable,
            )
        )
        if exclude_slug:
            query = query.exclude(slug=exclude_slug)

        return query.exists()

    @staticmethod
    def slug_exists(slug: str) -> bool:
        # NOTE: the slug is unique table-wide, so this ignores user_type; a
        # CONNECTED or ANONYMOUS row can own a slug an ACTIVE insert wants.
        return User.objects.filter(slug=slug).exists()


class EmailVerificationReminderRepository(EmailVerificationReminderRepositoryProtocol):
    @staticmethod
    def _due(*, now: datetime, interval: timedelta) -> QuerySet[User]:
        # An unproven address is an unverified `email` or a `pending_email`;
        # a row with neither is skipped rather than left to the notifier's
        # empty check, because stamping it would lose the nag for good once
        # the user finally adds an address.
        cutoff = now - interval
        unproven = (Q(email_verified=False) & ~Q(email="")) | ~Q(pending_email="")
        return (
            User.objects.filter(user_type=UserType.ACTIVE)
            .filter(unproven)
            .filter(
                Q(email_verification_sent_at__isnull=True)
                | Q(email_verification_sent_at__lt=cutoff)
            )
        )

    @staticmethod
    def count_due(*, now: datetime, interval: timedelta) -> int:
        return EmailVerificationReminderRepository._due(
            now=now, interval=interval
        ).count()

    @staticmethod
    def list_due(*, now: datetime, interval: timedelta) -> list[UserDTO]:
        # Whole rows, not slugs: the sweep needs the address and the last-sent
        # stamp anyway, and a slug list would make it re-read every user.
        return [
            UserDTO.model_validate(user)
            for user in EmailVerificationReminderRepository._due(
                now=now, interval=interval
            ).order_by("pk")
        ]


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
