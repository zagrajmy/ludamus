from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.multiverse.panel.forms import AnnouncementForm
from ludamus.gates.web.django.multiverse.panel.views.base import sphere_panel_context
from ludamus.pacts import NotFoundError, RedirectError
from ludamus.pacts.multiverse import AnnouncementData

if TYPE_CHECKING:
    from django.http import HttpResponse


def _announcement_not_found() -> RedirectError:
    return RedirectError(
        reverse("multiverse:panel:announcements"), error=_("Announcement not found.")
    )


def _form_data(form: AnnouncementForm) -> AnnouncementData:
    return AnnouncementData(
        title=form.cleaned_data["title"],
        content=form.cleaned_data["content"],
        is_published=form.cleaned_data["is_published"],
    )


class AnnouncementsPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        announcements = self.request.services.announcements.list_for_sphere(sphere_id)
        return TemplateResponse(
            self.request,
            "multiverse/panel/announcements/list.html",
            {
                **sphere_panel_context(self.request, active_tab="announcements"),
                "announcements": announcements,
            },
        )


class AnnouncementCreatePageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        return TemplateResponse(
            self.request,
            "multiverse/panel/announcements/create.html",
            {
                **sphere_panel_context(self.request, active_tab="announcements"),
                "form": AnnouncementForm(),
            },
        )

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = AnnouncementForm(self.request.POST)
        if not form.is_valid():
            return TemplateResponse(
                self.request,
                "multiverse/panel/announcements/create.html",
                {
                    **sphere_panel_context(self.request, active_tab="announcements"),
                    "form": form,
                },
            )

        sphere_id = self.request.context.current_sphere_id
        self.request.services.announcements.create(sphere_id, _form_data(form))
        messages.success(self.request, _("Announcement created successfully."))
        return redirect("multiverse:panel:announcements")


class AnnouncementEditPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            announcement = self.request.services.announcements.get(sphere_id, pk)
        except NotFoundError:
            raise _announcement_not_found() from None

        form = AnnouncementForm(
            initial={
                "title": announcement.title,
                "content": announcement.content,
                "is_published": announcement.is_published,
            }
        )
        return TemplateResponse(
            self.request,
            "multiverse/panel/announcements/edit.html",
            {
                **sphere_panel_context(self.request, active_tab="announcements"),
                "form": form,
                "announcement": announcement,
            },
        )

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            announcement = self.request.services.announcements.get(sphere_id, pk)
        except NotFoundError:
            raise _announcement_not_found() from None

        form = AnnouncementForm(self.request.POST)
        if not form.is_valid():
            return TemplateResponse(
                self.request,
                "multiverse/panel/announcements/edit.html",
                {
                    **sphere_panel_context(self.request, active_tab="announcements"),
                    "form": form,
                    "announcement": announcement,
                },
            )

        self.request.services.announcements.update(sphere_id, pk, data=_form_data(form))
        messages.success(self.request, _("Announcement updated successfully."))
        return redirect("multiverse:panel:announcements")


class AnnouncementDeletePageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            announcement = self.request.services.announcements.get(sphere_id, pk)
        except NotFoundError:
            raise _announcement_not_found() from None

        return TemplateResponse(
            self.request,
            "multiverse/panel/announcements/delete.html",
            {
                **sphere_panel_context(self.request, active_tab="announcements"),
                "announcement": announcement,
            },
        )

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        try:
            self.request.services.announcements.delete(sphere_id, pk)
        except NotFoundError:
            raise _announcement_not_found() from None

        messages.success(self.request, _("Announcement deleted successfully."))
        return redirect("multiverse:panel:announcements")
