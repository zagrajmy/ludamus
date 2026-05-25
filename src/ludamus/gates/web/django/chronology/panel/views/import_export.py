"""Import / Export panel section.

An import integration is a dumb connection + capability owned by Chronology;
this section is where the (hardcoded) Google Docs import is configured
(per-question mapping) and run. Integrations settings never reference import.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypedDict

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.submissions import ImportSettings, QuestionTarget

if TYPE_CHECKING:
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts.chronology import EventIntegrationDTO

SESSION_COLUMNS = ("title", "description")


class RecipeRow(TypedDict):
    index: int
    question: str
    selected: str
    field_name: str


def _active_integration(
    integrations: list[EventIntegrationDTO], pk: int | None
) -> EventIntegrationDTO | None:
    if pk is None:
        return integrations[0] if integrations else None
    return next((i for i in integrations if i.pk == pk), None)


def _row(index: int, question: str, target: QuestionTarget | None) -> RecipeRow:
    selected = "ignore"
    field_name = ""
    if target is not None and target.to:
        if target.to.startswith("session."):
            selected = target.to
        elif target.to.startswith("field."):
            selected = "field"
            field_name = target.to.removeprefix("field.")
    return {
        "index": index,
        "question": question,
        "selected": selected,
        "field_name": field_name,
    }


def _target_from_post(post: QueryDict, index: int) -> QuestionTarget:
    choice = (post.get(f"target_{index}") or "ignore").strip()
    if choice.startswith("session."):
        return QuestionTarget(to=choice)
    if choice == "field" and (name := (post.get(f"newname_{index}") or "").strip()):
        return QuestionTarget(to=f"field.{name}")
    return QuestionTarget(ignore=True)


def _settings_from_post(post: QueryDict) -> ImportSettings:
    questions: dict[str, QuestionTarget] = {}
    for key in post:
        match = re.fullmatch(r"question_(\d+)", key)
        question = post.get(key)
        if match is None or question is None:
            continue
        questions[question] = _target_from_post(post, int(match.group(1)))
    return ImportSettings(questions=questions)


class EventImportSectionView(PanelAccessMixin, EventContextMixin, View):
    """Import/Export section: the hardcoded Google Docs import recipe editor."""

    request: PanelRequest

    def get(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        context["active_nav"] = "import"

        integrations_service = self.request.services.event_integrations
        all_integrations = integrations_service.list_for_event(
            current_event.pk, IntegrationKind.IMPORT
        )
        integrations = [
            i
            for i in all_integrations
            if i.implementation == IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
        ]
        active = _active_integration(integrations, pk)
        if integrations and active is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)

        context["active_integration"] = active
        if active is not None:
            sphere_id = self.request.context.current_sphere_id
            questions = integrations_service.fetch_questions(
                sphere_id, current_event.pk, active.pk
            )
            settings = ImportSettings.model_validate_json(active.settings_json or "{}")
            context["session_columns"] = SESSION_COLUMNS
            context["rows"] = [
                _row(index, question, settings.questions.get(question))
                for index, question in enumerate(questions)
            ]
        return TemplateResponse(self.request, "panel/import.html", context)

    def post(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        all_integrations = self.request.services.event_integrations.list_for_event(
            current_event.pk, IntegrationKind.IMPORT
        )
        integrations = [
            i
            for i in all_integrations
            if i.implementation == IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
        ]
        if (active := _active_integration(integrations, pk)) is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        settings = _settings_from_post(self.request.POST)
        self.request.services.event_integrations.save_settings(
            current_event.pk, active.pk, settings.model_dump_json()
        )
        messages.success(self.request, _("Import recipe saved."))
        return redirect("panel:import-integration", slug=slug, pk=active.pk)


class EventImportRunActionView(PanelAccessMixin, EventContextMixin, View):
    """Run the saved import recipe: create a proposal per source response."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        all_integrations = self.request.services.event_integrations.list_for_event(
            current_event.pk, IntegrationKind.IMPORT
        )
        integrations = [
            i
            for i in all_integrations
            if i.implementation == IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
        ]
        if (active := _active_integration(integrations, pk)) is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        sphere_id = self.request.context.current_sphere_id
        result = self.request.services.proposals_import.run(
            sphere_id, current_event.pk, active.pk
        )
        messages.success(
            self.request, _("Created %(count)d proposals.") % {"count": result.created}
        )
        return redirect("panel:import-integration", slug=slug, pk=active.pk)
