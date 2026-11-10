from __future__ import annotations

from urllib.parse import urlsplit

import requests

# Cloudflare answers from the edge, so a revocation that takes longer is
# stuck, and the caller's retry does better than waiting on it.
_TIMEOUT_SECONDS = 10


def is_local(agent_host: str) -> bool:
    hostname = urlsplit(f"//{agent_host}").hostname or ""
    return hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(
        ".localhost"
    )


class ParleyWorkerClient:
    def __init__(self, agent_host: str) -> None:
        scheme = "http" if is_local(agent_host) else "https"
        self._revoke_url = f"{scheme}://{agent_host}/revoke"

    def revoke(self, token: str) -> None:
        body: dict[str, str] = {"token": token}
        response = requests.post(self._revoke_url, json=body, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
