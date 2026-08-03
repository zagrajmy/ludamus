from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic.base import View

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest


class LegacyPrintRedirectView(View):
    material: str | None = None

    def get(self, request: RootRequest, slug: str) -> HttpResponse:
        query = request.GET.copy()
        if self.material is not None:
            query["material"] = self.material

        target = reverse("web:chronology:event-print", kwargs={"slug": slug})
        if query:
            target = f"{target}?{query.urlencode()}"
        return redirect(target)
