"""Repository for what a sphere pays Zagrajmy: its `SpherePlan` row."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models.functions import Now

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
    def update(*, sphere_id: int, data: SpherePlanData) -> None:
        SpherePlan.objects.filter(sphere_id=sphere_id).update(
            **data, modification_time=Now()
        )

    @staticmethod
    def lock_by_customer(*, customer_id: str) -> SpherePlanDTO | None:
        if not customer_id:
            return None
        plan = (
            SpherePlan.objects.select_for_update()
            .filter(stripe_customer_id=customer_id)
            .first()
        )
        return None if plan is None else SpherePlanDTO.model_validate(plan)
