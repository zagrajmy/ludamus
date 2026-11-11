"""What the management commands run, handed over by `inits` at startup.

Django finds a command by its module name and constructs it itself, so no
composition root gets to pass it anything. `InitsConfig.ready()` registers the
services and the sweeps here instead, before any command can run — the same
shape as the analytics redaction builder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ludamus.pacts.services import ServicesProtocol
    from ludamus.pacts.sweeps import Sweep


class _Wiring:
    def __init__(self) -> None:
        self.services: Callable[[], ServicesProtocol] | None = None
        self.sweeps: dict[str, Sweep] = {}


_wiring = _Wiring()


def register(
    *, make_services: Callable[[], ServicesProtocol], sweeps: Iterable[Sweep]
) -> None:
    _wiring.services = make_services
    _wiring.sweeps = {sweep.command: sweep for sweep in sweeps}


def services() -> ServicesProtocol:
    if _wiring.services is None:
        msg = "No services registered for the management commands."
        raise ImproperlyConfigured(msg)
    return _wiring.services()


def sweep(command: str) -> Sweep:
    try:
        return _wiring.sweeps[command]
    except KeyError:
        msg = f"No sweep registered for the {command!r} command."
        raise ImproperlyConfigured(msg) from None
