"""Event announcement views (news shown on the public event page)."""

from __future__ import annotations

from django.urls import reverse

from ludamus.gates.web.django.announcements import (
    AnnouncementCreateBase,
    AnnouncementDeleteBase,
    AnnouncementEditBase,
    AnnouncementPage,
    AnnouncementsListBase,
)
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.pacts.multiverse import AnnouncementScope


class EventAnnouncementPageMixin(EventPanelAccessMixin, EventContextMixin):
    request: EventPanelRequest

    def page(self, **kwargs: str) -> AnnouncementPage:
        slug = kwargs["slug"]
        context, current_event = self.require_event_context(slug)
        context["active_nav"] = "announcements"
        return AnnouncementPage(
            announcements=self.request.services.announcements,
            scope=AnnouncementScope(event_id=current_event.pk),
            list_url=reverse("panel:announcements", kwargs={"slug": slug}),
            context=context,
        )


class AnnouncementsPageView(EventAnnouncementPageMixin, AnnouncementsListBase):
    request: EventPanelRequest
    template_name = "panel/announcements.html"


class AnnouncementCreatePageView(EventAnnouncementPageMixin, AnnouncementCreateBase):
    request: EventPanelRequest
    template_name = "panel/announcement-form.html"


class AnnouncementEditPageView(EventAnnouncementPageMixin, AnnouncementEditBase):
    request: EventPanelRequest
    template_name = "panel/announcement-form.html"


class AnnouncementDeleteActionView(EventAnnouncementPageMixin, AnnouncementDeleteBase):
    request: EventPanelRequest
    http_method_names = ("post",)
