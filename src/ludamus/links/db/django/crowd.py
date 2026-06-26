from __future__ import annotations

from django.contrib.auth.hashers import make_password

from ludamus.adapters.db.django.models import User, UserType
from ludamus.pacts.crowd import ClaimableProfileDTO, ClaimRepositoryProtocol


class ClaimRepository(ClaimRepositoryProtocol):
    @staticmethod
    def issue_token(*, manager_slug: str, user_slug: str, token: str) -> bool:
        updated = User.objects.filter(
            slug=user_slug,
            manager__slug=manager_slug,
            user_type=UserType.CONNECTED,
        ).update(claim_token=token)
        return bool(updated)

    @staticmethod
    def read_claimable(token: str) -> ClaimableProfileDTO | None:
        if not token:
            return None
        user = (
            User.objects
            .filter(claim_token=token, user_type=UserType.CONNECTED)
            .select_related("manager")
            .first()
        )
        if user is None:
            return None
        return ClaimableProfileDTO(
            name=user.name,
            slug=user.slug,
            manager_name=user.manager.name if user.manager else "",
        )

    @staticmethod
    def username_exists(username: str) -> bool:
        return User.objects.filter(username=username).exists()

    @staticmethod
    def convert(
        *, token: str, username: str, email: str, avatar_url: str
    ) -> str | None:
        user = User.objects.filter(
            claim_token=token, user_type=UserType.CONNECTED
        ).first()
        if user is None:
            return None
        user.username = username
        user.user_type = UserType.ACTIVE
        user.manager = None
        user.password = make_password(None)
        user.claim_token = ""
        if email and not User.objects.filter(email=email).exclude(pk=user.pk).exists():
            user.email = email
        if avatar_url:
            user.avatar_url = avatar_url
        user.save()
        return user.slug
