"""Sphere announcement views (news shown on the sphere landing page)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.template.response import TemplateResponse
from django.urls import reverse

from ludamus.gates.web.django.announcements import (
    AnnouncementCreateBase,
    AnnouncementDeleteBase,
    AnnouncementEditBase,
    AnnouncementPage,
    AnnouncementsListBase,
)
from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.sphere.panel_context import sphere_settings_context
from ludamus.pacts.multiverse import AnnouncementScope

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


class SphereAnnouncementPageMixin(SphereAccessMixin):
    request: MultiverseRequest

    def page(self, **_kwargs: str) -> AnnouncementPage:
        return AnnouncementPage(
            announcements=self.request.services.announcements,
            scope=AnnouncementScope(sphere_id=self.request.context.current_sphere_id),
            list_url=reverse("multiverse:panel:announcements"),
            context=sphere_settings_context(self.request, active_tab="announcements"),
        )


class AnnouncementsPageView(SphereAnnouncementPageMixin, AnnouncementsListBase):
    request: MultiverseRequest
    template_name = "multiverse/panel/announcements/list.html"


class AnnouncementCreatePageView(SphereAnnouncementPageMixin, AnnouncementCreateBase):
    request: MultiverseRequest
    template_name = "multiverse/panel/announcements/create.html"


class AnnouncementEditPageView(SphereAnnouncementPageMixin, AnnouncementEditBase):
    request: MultiverseRequest
    template_name = "multiverse/panel/announcements/edit.html"


class AnnouncementDeletePageView(SphereAnnouncementPageMixin, AnnouncementDeleteBase):
    request: MultiverseRequest
    template_name = "multiverse/panel/announcements/delete.html"

    def get(self, _request: HttpRequest, pk: int, **kwargs: str) -> HttpResponse:
        page = self.page(**kwargs)
        return TemplateResponse(
            self.request,
            self.template_name,
            {**page.context, "announcement": self.read(page, pk)},
        )
