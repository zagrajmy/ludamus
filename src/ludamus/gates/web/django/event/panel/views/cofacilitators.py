"""Turn a session field's free-text answers into facilitators of their own."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, NamedTuple, TypedDict

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import facilitator_tab_urls
from ludamus.gates.web.django.dynamic_fields import answered_value
from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
    PanelContext,
)
from ludamus.gates.web.django.event.panel.views.facilitator_fields import (
    personal_descriptors,
    personal_fields_form,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.panel import CreateFacilitator, LinkFacilitator, SkipFragment

if TYPE_CHECKING:
    from django import forms
    from django.http import QueryDict

    from ludamus.pacts import FieldDescriptor
    from ludamus.pacts.fields import OrganizerFieldDTO
    from ludamus.pacts.panel import (
        CofacilitatorCandidateDTO,
        CofacilitatorEntry,
        CofacilitatorSessionDetailDTO,
        CofacilitatorSessionDTO,
    )

_RESOLVE_TEMPLATE = "panel/cofacilitator-resolve.html"
# What one row can say a name is. The radios read their state off this.
_TARGETS = ("new", "existing", "skip")


class CofacilitatorsPageView(EventPanelAccessMixin, EventContextMixin, View):
    """List the sessions whose chosen field still names people in free text."""

    request: EventPanelRequest

    def get(self, _request: EventPanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.cofacilitator_panel
        chosen: OrganizerFieldDTO | None = None
        sessions: list[CofacilitatorSessionDTO] = []
        # Another organizer can delete the field between the two reads; the
        # page then lists nothing, rather than failing.
        with suppress(NotFoundError):
            chosen = service.resolve_field(
                event_id=current_event.pk, raw=self.request.GET.get("field", "")
            )
            sessions = service.list_sessions(
                event_id=current_event.pk, field_id=chosen.pk
            )

        context["active_nav"] = "facilitators"
        context["active_tab"] = "cofacilitators"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["fields"] = service.list_fields(current_event.pk)
        context["chosen_field"] = chosen
        context["sessions"] = sessions
        return TemplateResponse(self.request, "panel/cofacilitators.html", context)


def _candidate_prefix(index: int) -> str:
    return f"cofacilitator{index}"


class _CandidateRow(TypedDict):
    candidate: CofacilitatorCandidateDTO
    prefix: str
    target: str
    checked: dict[str, bool]
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
        fragment = row["candidate"].name
        if row["target"] == "skip":
            entries.append(SkipFragment(fragment=fragment))
        elif row["target"] == "existing":
            if not row["existing_id"].isdigit():
                row["error"] = _("Pick the facilitator to link.")
                continue
            entries.append(
                LinkFacilitator(
                    fragment=fragment, facilitator_id=int(row["existing_id"])
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
                CreateFacilitator(
                    fragment=fragment,
                    display_name=name,
                    base_slug=slugify(name),
                    values={
                        field.pk: answered_value(
                            prefix=row["prefix"], field_def=field, form=row["form"]
                        )
                        for field in fields
                    },
                )
            )
    return entries


class _Loaded(NamedTuple):
    """Everything both verbs of the resolve page start from."""

    context: PanelContext
    event_id: int
    field: OrganizerFieldDTO
    detail: CofacilitatorSessionDetailDTO


class CofacilitatorResolvePageView(EventPanelAccessMixin, EventContextMixin, View):
    """Decide, person by person, who a session's answer actually names."""

    request: EventPanelRequest

    def _load(self, *, slug: str, session_id: int) -> _Loaded | HttpResponse:
        """Read the event, the field and the answer, or say where to go instead.

        Returns:
            The loaded page, or the redirect that replaces it.
        """
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        service = self.request.services.cofacilitator_panel
        # Reached from the list, which names the field; opened bare, it means
        # the same field the list would have shown.
        raw = self.request.GET.get("field", "") or self.request.POST.get("field", "")
        try:
            field = service.resolve_field(event_id=current_event.pk, raw=raw)
        except NotFoundError:
            messages.error(self.request, _("Field not found."))
            return redirect("panel:cofacilitators", slug=slug)

        try:
            detail = service.read_session(
                event_id=current_event.pk, session_id=session_id, field_id=field.pk
            )
        except NotFoundError:
            messages.error(self.request, _("Session not found."))
            return redirect("panel:cofacilitators", slug=slug)

        return _Loaded(
            context=context, event_id=current_event.pk, field=field, detail=detail
        )

    @staticmethod
    def _rows(
        *, detail: CofacilitatorSessionDetailDTO, data: QueryDict | None
    ) -> list[_CandidateRow]:
        submitted: QueryDict | dict[str, str] = data or {}
        rows: list[_CandidateRow] = []
        for candidate in detail.candidates:
            prefix = _candidate_prefix(candidate.index)
            form = personal_fields_form(
                prefix=prefix,
                fields=detail.personal_fields,
                data=data,
                values=candidate.values,
            )
            # An exact name match is a suggestion the organizer confirms; two
            # people can share a name, so nothing is linked until they say so.
            # One already decided is somebody else's finished work, so the row
            # defaults to leaving it alone rather than deciding it twice.
            matched_target = "existing" if candidate.match else "new"
            default_target = "skip" if candidate.resolved else matched_target
            target = submitted.get(f"{prefix}_target", default_target)
            rows.append(
                {
                    "candidate": candidate,
                    "prefix": prefix,
                    "target": target,
                    "checked": {name: name == target for name in _TARGETS},
                    "name": submitted.get(f"{prefix}_name", candidate.name),
                    "existing_id": submitted.get(
                        f"{prefix}_existing",
                        str(candidate.match.pk) if candidate.match else "",
                    ),
                    "descriptors": personal_descriptors(
                        detail.personal_fields, form, prefix=prefix
                    ),
                    "form": form,
                    "error": "",
                }
            )
        return rows

    @staticmethod
    def _context(
        *, loaded: _Loaded, slug: str, rows: list[_CandidateRow]
    ) -> PanelContext:
        context = loaded.context
        context["active_nav"] = "facilitators"
        context["active_tab"] = "cofacilitators"
        context["tab_urls"] = facilitator_tab_urls(slug)
        context["session"] = loaded.detail
        context["chosen_field"] = loaded.field
        context["rows"] = rows
        # ponytail: the whole roster in one select; swap for the searching
        # picker the merge screen uses if an event outgrows a plain dropdown.
        context["existing_facilitators"] = loaded.detail.roster
        return context

    def get(
        self, _request: EventPanelRequest, slug: str, session_id: int
    ) -> HttpResponse:
        loaded = self._load(slug=slug, session_id=session_id)
        if isinstance(loaded, HttpResponse):
            return loaded

        return TemplateResponse(
            self.request,
            _RESOLVE_TEMPLATE,
            self._context(
                loaded=loaded,
                slug=slug,
                rows=self._rows(detail=loaded.detail, data=None),
            ),
        )

    def post(
        self, _request: EventPanelRequest, slug: str, session_id: int
    ) -> HttpResponse:
        loaded = self._load(slug=slug, session_id=session_id)
        if isinstance(loaded, HttpResponse):
            return loaded

        rows = self._rows(detail=loaded.detail, data=self.request.POST)
        entries = _entries(rows=rows, fields=loaded.detail.personal_fields)
        if any(row["error"] for row in rows):
            return TemplateResponse(
                self.request,
                _RESOLVE_TEMPLATE,
                self._context(loaded=loaded, slug=slug, rows=rows),
            )

        try:
            added = self.request.services.cofacilitator_panel.add_facilitators(
                event_id=loaded.event_id,
                session_id=session_id,
                field_id=loaded.field.pk,
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
            + f"?field={loaded.field.pk}"
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

        service = self.request.services.cofacilitator_panel
        # Clearing destroys an answer, so the field it names is never guessed:
        # a missing pick is a mistake, not "the first field".
        field = None
        if raw := self.request.POST.get("field", ""):
            with suppress(NotFoundError):
                field = service.resolve_field(event_id=current_event.pk, raw=raw)
        if field is None:
            messages.error(self.request, _("Field not found."))
            return redirect("panel:cofacilitators", slug=slug)

        try:
            service.clear_field(
                event_id=current_event.pk, session_id=session_id, field_id=field.pk
            )
        except NotFoundError:
            messages.error(self.request, _("Session not found."))
            return redirect("panel:cofacilitators", slug=slug)

        messages.success(self.request, _("Answer cleared."))
        return redirect(
            f"{reverse('panel:cofacilitators', kwargs={'slug': slug})}"
            f"?field={field.pk}"
        )
