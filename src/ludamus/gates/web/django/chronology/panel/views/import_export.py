"""Import / Export panel section.

An import integration is a dumb connection + capability owned by Chronology;
this section is where the (hardcoded) Google Docs import is configured
(per-question mapping) and run. Integrations settings never reference import.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, TypedDict

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
from ludamus.pacts.submissions import (
    FieldDefinition,
    FieldDefinitions,
    ImportSettings,
    QuestionTarget,
)

if TYPE_CHECKING:
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts.chronology import EventIntegrationDTO, SourceQuestion

SESSION_COLUMNS = ("title", "description")
FieldType = Literal["text", "select", "checkbox"]


class RecipeRow(TypedDict):
    index: int
    question: str
    selected: str
    field_name: str
    field_type: str
    is_multiple: bool
    allow_custom: bool
    options: str


def _active_integration(
    integrations: list[EventIntegrationDTO], pk: int | None
) -> EventIntegrationDTO | None:
    if pk is None:
        return integrations[0] if integrations else None
    return next((i for i in integrations if i.pk == pk), None)


def _row(
    index: int,
    question: SourceQuestion,
    target: QuestionTarget | None,
    definitions: FieldDefinitions,
) -> RecipeRow:
    field_name = ""
    # Pre-fill the new-field setup from the source question; a saved definition
    # (the operator's edits) overrides it.
    setup: FieldDefinition | SourceQuestion = question
    if target is None:
        # Never decided: default to a new session field that mirrors the source
        # question, so its form setup is visible and ready to save. The operator
        # re-points anything that should be a built-in field, personal field, or
        # deliberately unmapped.
        selected = "session-field"
        field_name = question.title
    elif target.to and target.to.startswith("session."):
        selected = target.to
    elif target.to and target.to.startswith("personal."):
        selected = "personal-field"
        field_name = target.to.removeprefix("personal.")
        setup = definitions.personal_fields.get(field_name, question)
    elif target.to and target.to.startswith("field."):
        selected = "session-field"
        field_name = target.to.removeprefix("field.")
        setup = definitions.session_fields.get(field_name, question)
    else:
        selected = "ignore"
    field_type, multiple = _setup_type(setup)
    return {
        "index": index,
        "question": question.title,
        "selected": selected,
        "field_name": field_name,
        "field_type": field_type,
        "is_multiple": multiple,
        "allow_custom": setup.allow_custom,
        "options": "\n".join(setup.options),
    }


def _setup_type(setup: FieldDefinition | SourceQuestion) -> tuple[str, bool]:
    # FieldDefinition exposes `type`; SourceQuestion exposes `field_type`.
    if isinstance(setup, FieldDefinition):
        return setup.type, setup.multiple
    return setup.field_type, setup.is_multiple


def _field_type_from_post(post: QueryDict, index: int) -> FieldType:
    match (post.get(f"fieldtype_{index}") or "text").strip():
        case "select":
            return "select"
        case "checkbox":
            return "checkbox"
        case _:
            return "text"


def _definition_from_post(post: QueryDict, index: int) -> FieldDefinition:
    return FieldDefinition(
        type=_field_type_from_post(post, index),
        multiple=bool(post.get(f"multiple_{index}")),
        allow_custom=bool(post.get(f"allowcustom_{index}")),
        options=[
            line.strip()
            for line in (post.get(f"options_{index}") or "").splitlines()
            if line.strip()
        ],
    )


def _target_from_post(post: QueryDict, index: int) -> QuestionTarget:
    choice = (post.get(f"target_{index}") or "ignore").strip()
    if choice.startswith("session."):
        return QuestionTarget(to=choice)
    name = (post.get(f"newname_{index}") or "").strip()
    if choice == "personal-field" and name:
        return QuestionTarget(to=f"personal.{name}")
    if choice == "session-field" and name:
        return QuestionTarget(to=f"field.{name}")
    return QuestionTarget(ignore=True)


def _settings_from_post(post: QueryDict) -> ImportSettings:
    questions: dict[str, QuestionTarget] = {}
    definitions = FieldDefinitions()
    for key in post:
        match = re.fullmatch(r"question_(\d+)", key)
        question = post.get(key)
        if match is None or question is None:
            continue
        index = int(match.group(1))
        target = _target_from_post(post, index)
        questions[question] = target
        if not target.to:
            continue
        if target.to.startswith("personal."):
            definitions.personal_fields[target.to.removeprefix("personal.")] = (
                _definition_from_post(post, index)
            )
        elif target.to.startswith("field."):
            definitions.session_fields[target.to.removeprefix("field.")] = (
                _definition_from_post(post, index)
            )
    return ImportSettings(questions=questions, definitions=definitions)


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
                _row(index, q, settings.questions.get(q.title), settings.definitions)
                for index, q in enumerate(questions)
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
