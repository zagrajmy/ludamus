"""Repository for what a sphere pays Zagrajmy: its `SpherePlan` row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import SpherePlan
from ludamus.pacts.billing import SpherePlanDTO, SpherePlanRepositoryProtocol

if TYPE_CHECKING:
    from ludamus.pacts.billing import SpherePlanData


class SpherePlanRepository(SpherePlanRepositoryProtocol):
    @staticmethod
    def read(*, sphere_id: int) -> SpherePlanDTO | None:
        plan = SpherePlan.objects.filter(sphere_id=sphere_id).first()
        return None if plan is None else SpherePlanDTO.model_validate(plan)

    @staticmethod
    def save(*, sphere_id: int, data: SpherePlanData) -> SpherePlanDTO:
        plan, _ = SpherePlan.objects.update_or_create(
            sphere_id=sphere_id, defaults=dict(data)
        )
        return SpherePlanDTO.model_validate(plan)

    @staticmethod
    def find_sphere_by_customer(*, customer_id: str) -> int | None:
        if not customer_id:
            return None
        return (
            SpherePlan.objects.filter(stripe_customer_id=customer_id)
            .values_list("sphere_id", flat=True)
            .first()
        )
