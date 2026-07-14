from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.adapters.db.django.models import Session

_SIMULACRA_FILL = 8


def fake_full_session(session: Session) -> None:
    if session.participants_limit == 0:
        session.participants_limit = _SIMULACRA_FILL
    session.__dict__["enrolled_count_cached"] = session.effective_participants_limit
    session.__dict__["waiting_count_cached"] = 0
