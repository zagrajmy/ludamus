from __future__ import annotations

import requests

# Cloudflare answers from the edge, so a revocation that takes longer is
# stuck, and the caller's retry does better than waiting on it.
_TIMEOUT_SECONDS = 10


class ParleyWorkerClient:
    def __init__(self, agent_host: str) -> None:
        local = agent_host.startswith(("localhost", "127.0.0.1"))
        self._revoke_url = f"{'http' if local else 'https'}://{agent_host}/revoke"

    def revoke(self, token: str) -> None:
        body: dict[str, str] = {"token": token}
        response = requests.post(self._revoke_url, json=body, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
