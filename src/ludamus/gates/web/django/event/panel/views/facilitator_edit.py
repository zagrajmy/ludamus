from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.gates.web.django.event.panel.views.facilitator_fields import (
    personal_descriptors,
    personal_entries,
    personal_fields_form,
    stored_descriptors,
)
from ludamus.gates.web.django.forms import FacilitatorEditForm
from ludamus.pacts import FacilitatorUpdateData, NotFoundError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.pacts.guild import GuildMarkDTO, GuildServiceProtocol, GuildSummaryDTO


class _GuildAttachContext(TypedDict):
    guild: GuildMarkDTO | None
    guild_options: list[GuildSummaryDTO]


def _guild_attach(
    *, guilds: GuildServiceProtocol, sphere_id: int, facilitator_pk: int
) -> _GuildAttachContext:
    return {
        "guild": guilds.mark_for_facilitator(
            sphere_id=sphere_id, facilitator_pk=facilitator_pk
        ),
        "guild_options": guilds.list_for_sphere(sphere_id=sphere_id),
    }


class FacilitatorEditPageView(EventPanelAccessMixin, EventContextMixin, View):
    request: EventPanelRequest

    def get(
        self, _request: EventPanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            detail = self.request.services.facilitator_panel.detail_context(
                event_id=current_event.pk, facilitator_slug=facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        facilitator = detail.facilitator
        context["active_nav"] = "facilitators"
        context["facilitator"] = facilitator
        context["form"] = FacilitatorEditForm(
            initial={
                "accreditation_type": facilitator.accreditation_type,
                "internal_comment": facilitator.internal_comment,
            }
        )
        context["field_descriptors"] = stored_descriptors(detail.personal_data_items)
        context.update(
            _guild_attach(
                guilds=self.request.services.guilds,
                sphere_id=current_event.sphere_id,
                facilitator_pk=facilitator.pk,
            )
        )
        return TemplateResponse(self.request, "panel/facilitator-edit.html", context)

    def post(
        self, _request: EventPanelRequest, slug: str, facilitator_slug: str
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            detail = self.request.services.facilitator_panel.detail_context(
                event_id=current_event.pk, facilitator_slug=facilitator_slug
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:facilitators", slug=slug)

        facilitator = detail.facilitator
        form = FacilitatorEditForm(self.request.POST)
        all_personal_fields = self.request.services.facilitator_panel.list_fields(
            current_event.pk
        )
        fields_form = personal_fields_form(
            fields=all_personal_fields, data=self.request.POST
        )
        if not form.is_valid() or not fields_form.is_valid():
            context["active_nav"] = "facilitators"
            context["facilitator"] = facilitator
            context["form"] = form
            context["field_descriptors"] = personal_descriptors(
                all_personal_fields, fields_form
            )
            context.update(
                _guild_attach(
                    guilds=self.request.services.guilds,
                    sphere_id=current_event.sphere_id,
                    facilitator_pk=facilitator.pk,
                )
            )
            return TemplateResponse(
                self.request, "panel/facilitator-edit.html", context
            )

        entries = personal_entries(
            form=fields_form,
            fields=all_personal_fields,
            facilitator_id=facilitator.pk,
            event_id=current_event.pk,
        )
        self.request.services.personal_data_field_values.update_facilitator(
            event_id=current_event.pk,
            facilitator_id=facilitator.pk,
            data=FacilitatorUpdateData(
                accreditation_type=form.cleaned_data["accreditation_type"],
                internal_comment=form.cleaned_data["internal_comment"],
            ),
            entries=entries,
            user_id=self.request.context.current_user_id,
        )

        messages.success(self.request, _("Facilitator updated successfully."))
        return redirect(
            "panel:facilitator-detail", slug=slug, facilitator_slug=facilitator_slug
        )
