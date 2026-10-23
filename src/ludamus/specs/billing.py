from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.billing import PlanKind

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.billing import SpherePlanDTO


def effective_plan(plan: SpherePlanDTO | None, *, now: datetime) -> PlanKind:
    """Say which plan a sphere is on right now; the only way to read one.

    A White Glove row counts while `paid_until` has not passed. No date means
    held until someone says otherwise: a maintainer's open-ended deal.
    """
    if (
        plan is not None
        and plan.kind is PlanKind.WHITE_GLOVE
        and (plan.paid_until is None or plan.paid_until > now)
    ):
        return PlanKind.WHITE_GLOVE
    return PlanKind.STANDARD
