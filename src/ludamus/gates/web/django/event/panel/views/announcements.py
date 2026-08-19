"""Event announcement views (news shown on the public event page)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.multiverse.panel.forms import AnnouncementForm
from ludamus.pacts import NotFoundError, RedirectError
from ludamus.pacts.multiverse import AnnouncementData, AnnouncementScope

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.event.panel.views.base import PanelContext
    from ludamus.pacts.multiverse import AnnouncementDTO


def _announcement_not_found(slug: str) -> RedirectError:
    return RedirectError(
        reverse("panel:announcements", kwargs={"slug": slug}),
        error=_("Announcement not found."),
    )


def _form_data(form: AnnouncementForm) -> AnnouncementData:
    return AnnouncementData(
        title=form.cleaned_data["title"],
        content=form.cleaned_data["content"],
        is_published=form.cleaned_data["is_published"],
    )


class AnnouncementsPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.require_event_context(slug)
        context["active_nav"] = "announcements"
        context["announcements"] = self.request.services.announcements.list_for_scope(
            AnnouncementScope(event_id=current_event.pk)
        )
        return TemplateResponse(self.request, "panel/announcements.html", context)


class AnnouncementCreatePageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, _current_event = self.require_event_context(slug)
        return self._render(context, AnnouncementForm(initial={"is_published": True}))

    def post(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.require_event_context(slug)
        form = AnnouncementForm(self.request.POST)
        if not form.is_valid():
            return self._render(context, form)

        self.request.services.announcements.create(
            AnnouncementScope(event_id=current_event.pk), _form_data(form)
        )
        messages.success(self.request, _("Announcement created."))
        return redirect("panel:announcements", slug=slug)

    def _render(self, context: PanelContext, form: AnnouncementForm) -> HttpResponse:
        context["active_nav"] = "announcements"
        context["form"] = form
        context["announcement_pk"] = None
        return TemplateResponse(self.request, "panel/announcement-form.html", context)


class AnnouncementEditPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.require_event_context(slug)
        announcement = self._read(event_pk=current_event.pk, pk=pk, slug=slug)
        form = AnnouncementForm(
            initial={
                "title": announcement.title,
                "content": announcement.content,
                "is_published": announcement.is_published,
            }
        )
        return self._render(context, form=form, announcement_pk=pk)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.require_event_context(slug)
        scope = AnnouncementScope(event_id=current_event.pk)
        # Scope-check before the form, so a pk from another event bounces
        # instead of re-rendering an edit page for something unreachable.
        self._read(event_pk=current_event.pk, pk=pk, slug=slug)

        form = AnnouncementForm(self.request.POST)
        if not form.is_valid():
            return self._render(context, form=form, announcement_pk=pk)

        self.request.services.announcements.update(scope, pk, _form_data(form))
        messages.success(self.request, _("Announcement updated."))
        return redirect("panel:announcements", slug=slug)

    def _read(self, *, event_pk: int, pk: int, slug: str) -> AnnouncementDTO:
        try:
            return self.request.services.announcements.get(
                AnnouncementScope(event_id=event_pk), pk
            )
        except NotFoundError:
            raise _announcement_not_found(slug) from None

    def _render(
        self, context: PanelContext, *, form: AnnouncementForm, announcement_pk: int
    ) -> HttpResponse:
        context["active_nav"] = "announcements"
        context["form"] = form
        context["announcement_pk"] = announcement_pk
        return TemplateResponse(self.request, "panel/announcement-form.html", context)


class AnnouncementDeleteActionView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest
    http_method_names = ("post",)

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.require_event_context(slug)
        try:
            self.request.services.announcements.delete(
                AnnouncementScope(event_id=current_event.pk), pk
            )
        except NotFoundError:
            raise _announcement_not_found(slug) from None

        messages.success(self.request, _("Announcement deleted."))
        return redirect("panel:announcements", slug=slug)
