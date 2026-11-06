from typing import TypedDict

from authlib.integrations.django_client import OAuth
from django.conf import settings

oauth = OAuth()


class ClientKwargs(TypedDict):
    scope: str


oauth.register(
    "auth0",
    client_id=settings.AUTH0_CLIENT_ID,  # type: ignore [misc]
    client_secret=settings.AUTH0_CLIENT_SECRET,  # type: ignore [misc]
    client_kwargs=ClientKwargs(scope="openid profile email"),
    server_metadata_url=(
        f"https://{settings.AUTH0_DOMAIN}/"  # type: ignore [misc]
        ".well-known/openid-configuration"
    ),
)
