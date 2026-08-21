"""Announcement CRUD shared by the sphere panel and the event panel.

A panel describes itself once, through `page()`: which scope it writes to,
where its list lives, and what chrome its templates need. Form handling, the
not-found translation and the messages live here, so the platform scope of
issue #617 arrives as a third `page()` rather than a third copy of the views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, NamedTuple

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.forms import AnnouncementForm
from ludamus.pacts import NotFoundError, RedirectError
from ludamus.pacts.multiverse import AnnouncementData

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse

    from ludamus.pacts.multiverse import (
        AnnouncementDTO,
        AnnouncementScope,
        AnnouncementsServiceProtocol,
    )


class AnnouncementPage(NamedTuple):
    announcements: AnnouncementsServiceProtocol
    scope: AnnouncementScope
    list_url: str
    context: dict[str, object]


def _not_found(page: AnnouncementPage) -> RedirectError:
    return RedirectError(page.list_url, error=_("Announcement not found."))


def _form_data(form: AnnouncementForm) -> AnnouncementData:
    return AnnouncementData(
        title=form.cleaned_data["title"],
        content=form.cleaned_data["content"],
        is_published=form.cleaned_data["is_published"],
    )


class AnnouncementViewBase(View):
    template_name: ClassVar[str]
    # Supplied by the panel mixin the concrete view is built from; declared as
    # an attribute rather than an abstract method so the four bases below stay
    # ordinary classes.
    page: Callable[..., AnnouncementPage]

    @staticmethod
    def read(page: AnnouncementPage, pk: int) -> AnnouncementDTO:
        try:
            return page.announcements.get(page.scope, pk)
        except NotFoundError:
            raise _not_found(page) from None

    def render_form(
        self,
        page: AnnouncementPage,
        *,
        form: AnnouncementForm,
        announcement: AnnouncementDTO | None,
    ) -> HttpResponse:
        return TemplateResponse(
            self.request,
            self.template_name,
            {**page.context, "form": form, "announcement": announcement},
        )


class AnnouncementsListBase(AnnouncementViewBase):
    def get(self, _request: HttpRequest, **kwargs: str) -> HttpResponse:
        page = self.page(**kwargs)
        return TemplateResponse(
            self.request,
            self.template_name,
            {
                **page.context,
                "announcements": page.announcements.list_for_scope(page.scope),
            },
        )


class AnnouncementCreateBase(AnnouncementViewBase):
    def get(self, _request: HttpRequest, **kwargs: str) -> HttpResponse:
        return self.render_form(
            self.page(**kwargs), form=AnnouncementForm(), announcement=None
        )

    def post(self, _request: HttpRequest, **kwargs: str) -> HttpResponse:
        page = self.page(**kwargs)
        form = AnnouncementForm(self.request.POST)
        if not form.is_valid():
            return self.render_form(page, form=form, announcement=None)

        page.announcements.create(page.scope, _form_data(form))
        messages.success(self.request, _("Announcement created successfully."))
        return redirect(page.list_url)


class AnnouncementEditBase(AnnouncementViewBase):
    def get(self, _request: HttpRequest, pk: int, **kwargs: str) -> HttpResponse:
        page = self.page(**kwargs)
        announcement = self.read(page, pk)
        form = AnnouncementForm(
            initial={
                "title": announcement.title,
                "content": announcement.content,
                "is_published": announcement.is_published,
            }
        )
        return self.render_form(page, form=form, announcement=announcement)

    def post(self, _request: HttpRequest, pk: int, **kwargs: str) -> HttpResponse:
        page = self.page(**kwargs)
        form = AnnouncementForm(self.request.POST)
        if not form.is_valid():
            # The read is the scope check as much as the template's subtitle: a
            # pk from another panel bounces instead of re-rendering an edit
            # page for something the caller cannot reach.
            return self.render_form(page, form=form, announcement=self.read(page, pk))

        try:
            page.announcements.update(page.scope, pk, _form_data(form))
        except NotFoundError:
            raise _not_found(page) from None

        messages.success(self.request, _("Announcement updated successfully."))
        return redirect(page.list_url)


class AnnouncementDeleteBase(AnnouncementViewBase):
    def post(self, _request: HttpRequest, pk: int, **kwargs: str) -> HttpResponse:
        page = self.page(**kwargs)
        try:
            page.announcements.delete(page.scope, pk)
        except NotFoundError:
            raise _not_found(page) from None

        messages.success(self.request, _("Announcement deleted successfully."))
        return redirect(page.list_url)
