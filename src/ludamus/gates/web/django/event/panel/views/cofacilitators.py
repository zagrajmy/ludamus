"""Turn a session field's free-text answers into facilitators of their own."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import facilitator_tab_urls
from ludamus.gates.web.django.dynamic_fields import (
    answered_value,
    dynamic_fields_form,
    field_descriptors,
)
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
    PanelContext,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.panel import CofacilitatorEntry

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts import FieldDescriptor
    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.panel import (
        CofacilitatorCandidateDTO,
        CofacilitatorSessionDetailDTO,
    )


def _chosen_field(
    *, raw: str, fields: list[OrganizerFieldDTO]
) -> OrganizerFieldDTO | None:
    """Return the field the operator asked for, or the event's first one."""
    if raw.isdigit() and (
        chosen := next((f for f in fields if f.pk == int(raw)), None)
    ):
        return chosen
    return fields[0] if fields else None


class CofacilitatorsPageView(EventPanelAccessMixin, EventContextMixin, View):
    """List the sessions whose chosen field still names people in free text."""

    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.cofacilitator_panel
        fields = service.list_fields(current_event.pk)
        chosen = _chosen_field(raw=self.request.GET.get("field", ""), fields=fields)
        try:
            sessions = (
                service.list_sessions(event_id=current_event.pk, field_id=chosen.pk)
                if chosen
                else []
            )
        except NotFoundError:
            sessions = []

        context["active_nav"] = "facilitators"
        context["active_tab"] = "cofacilitators"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["fields"] = fields
        context["chosen_field"] = chosen
        context["sessions"] = sessions
        return TemplateResponse(self.request, "panel/cofacilitators.html", context)


def _candidate_prefix(index: int) -> str:
    return f"cofacilitator{index}"


class _CandidateRow(TypedDict):
    candidate: CofacilitatorCandidateDTO
    prefix: str
    target: str
    name: str
    existing_id: str
    descriptors: list[FieldDescriptor]
    form: forms.Form
    error: str


def _entries(
    *, rows: list[_CandidateRow], fields: list[OrganizerFieldDTO]
) -> list[CofacilitatorEntry]:
    """Read back what the organizer decided about each person, row by row."""
    entries: list[CofacilitatorEntry] = []
    for row in rows:
        if row["target"] == "existing":
            if not row["existing_id"].isdigit():
                row["error"] = _("Pick the facilitator to link.")
                continue
            entries.append(
                CofacilitatorEntry(
                    display_name="",
                    base_slug="",
                    facilitator_id=int(row["existing_id"]),
                    values={},
                )
            )
        elif row["target"] == "new":
            if not (name := row["name"].strip()):
                row["error"] = _("Give the new facilitator a name.")
                continue
            if not row["form"].is_valid():
                row["error"] = _("Check the answers below.")
                continue
            entries.append(
                CofacilitatorEntry(
                    display_name=name,
                    base_slug=slugify(name),
                    facilitator_id=None,
                    values={
                        field.pk: answered_value(
                            prefix=row["prefix"], field_def=field, form=row["form"]
                        )
                        for field in fields
                    },
                )
            )
    return entries


class CofacilitatorResolvePageView(EventPanelAccessMixin, EventContextMixin, View):
    """Decide, person by person, who a session's answer actually names."""

    request: EventPanelRequest

    def _field(self, event_id: int) -> OrganizerFieldDTO:
        # Reached from the list, which names the field; opened bare, it means
        # the same field the list would have shown.
        raw = self.request.GET.get("field", "") or self.request.POST.get("field", "")
        service = self.request.services.cofacilitator_panel
        field = _chosen_field(raw=raw, fields=service.list_fields(event_id))
        if field is None:
            raise NotFoundError
        return field

    @staticmethod
    def _rows(
        *, detail: CofacilitatorSessionDetailDTO, data: QueryDict | None
    ) -> list[_CandidateRow]:
        rows: list[_CandidateRow] = []
        for candidate in detail.candidates:
            prefix = _candidate_prefix(candidate.index)
            form = dynamic_fields_form(
                prefix=prefix,
                fields=[(field, False) for field in detail.personal_fields],
                data=data,
                initial=candidate.values,
            )
            # An exact name match is a suggestion the organizer confirms; two
            # people can share a name, so nothing is linked until they say so.
            # One already on the session is somebody else's finished work, so
            # the row defaults to leaving it alone rather than adding it twice.
            matched_target = "existing" if candidate.match else "new"
            default_target = "skip" if candidate.already_linked else matched_target
            rows.append(
                {
                    "candidate": candidate,
                    "prefix": prefix,
                    "target": (
                        data.get(f"{prefix}_target", default_target)
                        if data
                        else default_target
                    ),
                    "name": (
                        data.get(f"{prefix}_name", candidate.name)
                        if data
                        else candidate.name
                    ),
                    "existing_id": (
                        data.get(f"{prefix}_existing", "")
                        if data
                        else str(candidate.match.pk if candidate.match else "")
                    ),
                    "descriptors": field_descriptors(
                        prefix=prefix,
                        fields=[(field, False) for field in detail.personal_fields],
                        form=form,
                    ),
                    "form": form,
                    "error": "",
                }
            )
        return rows

    def _context(
        self,
        *,
        context: PanelContext,
        slug: str,
        detail: CofacilitatorSessionDetailDTO,
        field: OrganizerFieldDTO,
        rows: list[_CandidateRow],
        event_id: int,
    ) -> PanelContext:
        context["active_nav"] = "facilitators"
        context["active_tab"] = "cofacilitators"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["session"] = detail
        context["chosen_field"] = field
        context["rows"] = rows
        # ponytail: the whole roster in one select; swap for the searching
        # picker the merge screen uses if an event outgrows a plain dropdown.
        context["existing_facilitators"] = (
            self.request.services.cofacilitator_panel.list_candidates_for_linking(
                event_id
            )
        )
        return context

    def get(
        self, _request: EventPanelRequest, slug: str, session_id: int
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.cofacilitator_panel
        try:
            field = self._field(current_event.pk)
            detail = service.read_session(
                event_id=current_event.pk, session_id=session_id, field_id=field.pk
            )
        except NotFoundError:
            messages.error(self.request, _("Session not found."))
            return redirect("panel:cofacilitators", slug=slug)

        return TemplateResponse(
            self.request,
            "panel/cofacilitator-resolve.html",
            self._context(
                context=context,
                slug=slug,
                detail=detail,
                field=field,
                rows=self._rows(detail=detail, data=None),
                event_id=current_event.pk,
            ),
        )

    def post(
        self, _request: EventPanelRequest, slug: str, session_id: int
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.cofacilitator_panel
        try:
            field = self._field(current_event.pk)
            detail = service.read_session(
                event_id=current_event.pk, session_id=session_id, field_id=field.pk
            )
        except NotFoundError:
            messages.error(self.request, _("Session not found."))
            return redirect("panel:cofacilitators", slug=slug)

        rows = self._rows(detail=detail, data=self.request.POST)
        entries = _entries(rows=rows, fields=detail.personal_fields)
        if any(row["error"] for row in rows):
            return TemplateResponse(
                self.request,
                "panel/cofacilitator-resolve.html",
                self._context(
                    context=context,
                    slug=slug,
                    detail=detail,
                    field=field,
                    rows=rows,
                    event_id=current_event.pk,
                ),
            )

        try:
            added = service.add_facilitators(
                event_id=current_event.pk,
                session_id=session_id,
                entries=entries,
                user_id=self.request.context.current_user_id,
            )
        except NotFoundError:
            messages.error(self.request, _("Facilitator not found."))
            return redirect("panel:cofacilitators", slug=slug)

        messages.success(
            self.request,
            ngettext(
                "%(count)d facilitator added to the session.",
                "%(count)d facilitators added to the session.",
                added,
            )
            % {"count": added},
        )
        return redirect(
            reverse(
                "panel:cofacilitator-resolve",
                kwargs={"slug": slug, "session_id": session_id},
            )
            + f"?field={field.pk}"
        )


class CofacilitatorClearActionView(EventPanelAccessMixin, EventContextMixin, View):
    """Empty the answer once everyone it named has their own record."""

    request: EventPanelRequest
    http_method_names = ("post",)

    def post(
        self, _request: EventPanelRequest, slug: str, session_id: int
    ) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        raw = self.request.POST.get("field", "")
        try:
            self.request.services.cofacilitator_panel.clear_field(
                event_id=current_event.pk,
                session_id=session_id,
                field_id=int(raw) if raw.isdigit() else 0,
            )
        except NotFoundError:
            messages.error(self.request, _("Session not found."))
            return redirect("panel:cofacilitators", slug=slug)

        messages.success(self.request, _("Answer cleared."))
        return redirect(
            f"{reverse('panel:cofacilitators', kwargs={'slug': slug})}?field={raw}"
        )
