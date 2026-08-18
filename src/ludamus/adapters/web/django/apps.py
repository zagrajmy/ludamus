import atexit
from typing import TYPE_CHECKING, Any

from django.apps import AppConfig
from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from posthog import Posthog, identify_context

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.http import HttpRequest

posthog_client: Posthog | None = None


def get_posthog_client() -> Posthog | None:
    return posthog_client


class WebMainConfig(AppConfig):
    name = "ludamus.adapters.web.django"
    label = "web_main"

    def ready(self) -> None:  # ruff: ignore[no-self-use]
        global posthog_client  # ruff: ignore[global-statement]

        if not settings.POSTHOG_API_KEY:
            if settings.DEBUG:
                raise RuntimeError(
                    "POSTHOG_API_KEY variable required by PostHog is missing or "
                    "un-configured, this causes events to be silently missed. This "
                    "error stops appearing once POSTHOG_API_KEY is configured"
                )
            return
        if not settings.POSTHOG_HOST:
            if settings.DEBUG:
                raise RuntimeError(
                    "POSTHOG_HOST variable required by PostHog is missing or "
                    "un-configured, this causes events to be silently missed. This "
                    "error stops appearing once POSTHOG_HOST is configured"
                )
            return

        posthog_client = Posthog(
            project_api_key=settings.POSTHOG_API_KEY,
            host=settings.POSTHOG_HOST,
            enable_exception_autocapture=True,
        )
        atexit.register(posthog_client.shutdown)


@receiver(user_logged_in)
def identify_posthog_user(
    _sender: type[Any], _request: HttpRequest, user: AbstractBaseUser, **_kwargs: Any
) -> None:
    identify_context(str(user.pk))
