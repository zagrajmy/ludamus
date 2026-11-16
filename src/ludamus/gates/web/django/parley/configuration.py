"""Whether this deployment runs the chat at all."""

from django.conf import settings


def chat_configured() -> bool:
    # Only where the chat can sign passes and reach a Worker; elsewhere its
    # button could never connect.
    agent_host: str = settings.PARLEY_AGENT_HOST
    private_key: str = settings.PARLEY_SIGNING_PRIVATE_KEY
    return bool(agent_host and private_key)
