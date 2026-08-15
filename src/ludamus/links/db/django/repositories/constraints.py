from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db import IntegrityError


def violates_constraint(exc: IntegrityError, *names: str) -> bool:
    # Postgres names the violated constraint in the error diagnostics. SQLite
    # only spells it out in the message, and how it spells it depends on the
    # constraint: a functional index gives its own name, a plain unique
    # constraint gives the column list instead — hence several accepted names.
    diag = getattr(exc.__cause__, "diag", None)
    if getattr(diag, "constraint_name", None) in names:
        return True
    message = str(exc)
    return any(name in message for name in names)
