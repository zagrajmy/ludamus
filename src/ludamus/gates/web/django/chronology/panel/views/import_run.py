"""Proposal import recipe editor (event panel).

Maps each fetched source question to a target. The recipe is stored as the
integration's opaque settings blob; running it is a separate action.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, TypedDict

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
from ludamus.gates.web.django.chronology.panel.views.integrations import (
    PanelViewLike,
    load_integration,
)
from ludamus.pacts.chronology import IntegrationKind
from ludamus.pacts.submissions import ImportSettings, QuestionTarget

if TYPE_CHECKING:
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts import EventDTO
    from ludamus.pacts.chronology import EventIntegrationDTO

SESSION_COLUMNS = ("title", "description")


class RecipeRow(TypedDict):
    index: int
    question: str
    selected: str
    field_name: str


def _load_import_integration(
    view: PanelViewLike, slug: str, pk: int
) -> tuple[dict[str, Any], EventDTO, EventIntegrationDTO] | HttpResponse:
    # Load the integration and enforce that it can import; on any miss return
    # the redirect for the caller to hand back, otherwise the unpacked triple.
    loaded = load_integration(view, slug, pk)
    if loaded[1] is None:
        return loaded[2]
    context, current_event, integration = loaded
    if integration.kind != IntegrationKind.IMPORT:
        messages.error(view.request, _("This integration does not import proposals."))
        return redirect("panel:event-integration-settings", slug=slug)
    return context, current_event, integration


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


class EventImportPageView(PanelAccessMixin, EventContextMixin, View):
    """Edit the import recipe for one IMPORT-kind integration."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        result = _load_import_integration(self, slug, pk)
        if not isinstance(result, tuple):
            return result
        context, current_event, integration = result

        sphere_id = self.request.context.current_sphere_id
        questions = self.request.services.event_integrations.fetch_questions(
            sphere_id, current_event.pk, pk
        )
        settings = ImportSettings.model_validate_json(integration.settings_json or "{}")
        context["active_nav"] = "settings"
        context["integration"] = integration
        context["session_columns"] = SESSION_COLUMNS
        context["rows"] = [
            _row(index, question, settings.questions.get(question))
            for index, question in enumerate(questions)
        ]
        return TemplateResponse(
            self.request, "chronology/panel/integrations/import.html", context
        )

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        result = _load_import_integration(self, slug, pk)
        if not isinstance(result, tuple):
            return result
        _context, current_event, _integration = result

        settings = _settings_from_post(self.request.POST)
        self.request.services.event_integrations.save_settings(
            current_event.pk, pk, settings.model_dump_json()
        )
        messages.success(self.request, _("Import recipe saved."))
        return redirect("panel:integration-import", slug=slug, pk=pk)


class EventImportRunActionView(PanelAccessMixin, EventContextMixin, View):
    """Run the saved import recipe: create a proposal per source response."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        loaded = _load_import_integration(self, slug, pk)
        if not isinstance(loaded, tuple):
            return loaded
        _context, current_event, _integration = loaded

        sphere_id = self.request.context.current_sphere_id
        result = self.request.services.proposals_import.run(
            sphere_id, current_event.pk, pk
        )
        messages.success(
            self.request, _("Created %(count)d proposals.") % {"count": result.created}
        )
        return redirect("panel:integration-import", slug=slug, pk=pk)
