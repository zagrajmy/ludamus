"""Import / Export panel section.

An import integration is a dumb connection + capability owned by Chronology;
this section is where the (hardcoded) Google Docs import is configured
(per-question mapping) and run. Integrations settings never reference import.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Literal, TypedDict

from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.timezone import get_current_timezone, localtime, make_aware
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.mills.submissions import slugify
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.submissions import (
    EntityRef,
    FieldDefinition,
    FieldDefinitions,
    ImportSettings,
    QuestionTarget,
    QuestionValue,
    TimeSlotSpec,
)

if TYPE_CHECKING:
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts.chronology import EventIntegrationDTO, SourceQuestion

SESSION_COLUMNS = ("title", "description")
TIME_SLOTS_TARGET = "session.time_slots"
ENTITY_TARGETS = ("track", "category")
FieldType = Literal["text", "select", "checkbox"]
LOCAL_DT_FORMAT = "%Y-%m-%dT%H:%M"


class Window(TypedDict):
    start: str
    end: str


class OptionWindows(TypedDict):
    option: str
    windows: list[Window]


class OptionEntity(TypedDict):
    option: str
    name: str
    slug: str


class RecipeRow(TypedDict):
    index: int
    question: str
    selected: str
    field_name: str
    field_slug: str
    field_type: str
    is_multiple: bool
    allow_custom: bool
    options: str
    option_windows: list[OptionWindows]
    option_entities: list[OptionEntity]
    catchall_name: str
    catchall_slug: str


def _active_integration(
    integrations: list[EventIntegrationDTO], pk: int | None
) -> EventIntegrationDTO | None:
    if pk is None:
        return integrations[0] if integrations else None
    return next((i for i in integrations if i.pk == pk), None)


def _import_integrations(
    request: PanelRequest, event_pk: int
) -> list[EventIntegrationDTO]:
    return [
        i
        for i in request.services.event_integrations.list_for_event(
            event_pk, IntegrationKind.IMPORT
        )
        if i.implementation == IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
    ]


def _row(
    index: int,
    question: SourceQuestion,
    target: QuestionTarget | None,
    definitions: FieldDefinitions,
) -> RecipeRow:
    field_name = ""
    field_slug = ""
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
        field_slug = slugify(question.title)
    elif target.to and (
        target.to.startswith("session.")
        or target.to == "facilitator.display_name"
        or target.to in ENTITY_TARGETS
    ):
        selected = target.to
    elif target.to and target.to.startswith("personal."):
        selected = "personal-field"
        field_slug = target.to.removeprefix("personal.")
        setup, field_name = _field_row_setup(
            definitions.personal_fields.get(field_slug), field_slug, question
        )
    elif target.to and target.to.startswith("field."):
        selected = "session-field"
        field_slug = target.to.removeprefix("field.")
        setup, field_name = _field_row_setup(
            definitions.session_fields.get(field_slug), field_slug, question
        )
    else:
        selected = "ignore"
    field_type, multiple = _setup_type(setup)
    return {
        "index": index,
        "question": question.title,
        "selected": selected,
        "field_name": field_name,
        "field_slug": field_slug,
        "field_type": field_type,
        "is_multiple": multiple,
        "allow_custom": setup.allow_custom,
        "options": "\n".join(setup.options),
        # Always built from the source options so the (hidden) editors are ready
        # the moment the operator switches this row to "Time slots" or a
        # track/category target.
        "option_windows": _option_windows(question, target),
        "option_entities": _option_entities(question, target),
        "catchall_name": target.catchall.name if target and target.catchall else "",
        "catchall_slug": target.catchall.slug if target and target.catchall else "",
    }


def _field_row_setup(
    definition: FieldDefinition | None, slug: str, question: SourceQuestion
) -> tuple[FieldDefinition | SourceQuestion, str]:
    # A saved definition supplies both the form setup and the display name; with
    # none, mirror the source question and fall back to the slug for the name.
    if definition is None:
        return question, slug
    return definition, definition.name or slug


def _setup_type(setup: FieldDefinition | SourceQuestion) -> tuple[str, bool]:
    # FieldDefinition exposes `type`; SourceQuestion exposes `field_type`.
    if isinstance(setup, FieldDefinition):
        return setup.type, setup.multiple
    return setup.field_type, setup.is_multiple


def _option_windows(
    question: SourceQuestion, target: QuestionTarget | None
) -> list[OptionWindows]:
    # One editable group per source option, pre-filled with its configured
    # windows (local datetime-local strings) or a single blank window to fill.
    configured = target.values if target else {}
    rows: list[OptionWindows] = []
    for option in question.options:
        spec = configured.get(option)
        specs = spec if isinstance(spec, list) else [spec] if spec else []
        windows: list[Window] = [
            {
                "start": localtime(s.start_time).strftime(LOCAL_DT_FORMAT),
                "end": localtime(s.end_time).strftime(LOCAL_DT_FORMAT),
            }
            for s in specs
            if isinstance(s, TimeSlotSpec)
        ] or [{"start": "", "end": ""}]
        rows.append({"option": option, "windows": windows})
    return rows


def _option_entities(
    question: SourceQuestion, target: QuestionTarget | None
) -> list[OptionEntity]:
    # One row per source option, pre-filled with its configured track/category
    # (name + slug) or defaulting to the option text and the slug derived from
    # it, so the (hidden) editor is ready the moment the row becomes a track or
    # category target.
    configured = target.values if target else {}
    rows: list[OptionEntity] = []
    for option in question.options:
        ref = configured.get(option)
        if isinstance(ref, EntityRef):
            rows.append({"option": option, "name": ref.name, "slug": ref.slug})
        else:
            rows.append({"option": option, "name": option, "slug": slugify(option)})
    return rows


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
        name=(post.get(f"newname_{index}") or "").strip(),
        type=_field_type_from_post(post, index),
        multiple=bool(post.get(f"multiple_{index}")),
        allow_custom=bool(post.get(f"allowcustom_{index}")),
        options=[
            line.strip()
            for line in (post.get(f"options_{index}") or "").splitlines()
            if line.strip()
        ],
    )


def _time_slot_values_from_post(
    post: QueryDict, index: int
) -> dict[str, QuestionValue]:
    # The window rows submit parallel arrays (one entry per row); regroup them
    # by option, dropping rows missing a start or end.
    grouped: dict[str, list[TimeSlotSpec]] = {}
    rows = zip(
        post.getlist(f"tsoption_{index}"),
        post.getlist(f"tsstart_{index}"),
        post.getlist(f"tsend_{index}"),
        strict=False,
    )
    tz = get_current_timezone()
    for option, start, end in rows:
        if not (option and start and end):
            continue
        grouped.setdefault(option, []).append(
            TimeSlotSpec(
                start_time=make_aware(datetime.fromisoformat(start), tz),
                end_time=make_aware(datetime.fromisoformat(end), tz),
            )
        )
    result: dict[str, QuestionValue] = {
        option: windows[0] if len(windows) == 1 else windows
        for option, windows in grouped.items()
    }
    return result


def _entity_map_from_post(
    post: QueryDict, index: int
) -> tuple[dict[str, QuestionValue], EntityRef | None]:
    # Per-option track/category rows submit parallel arrays; a blank name drops
    # that option. The catchall is one name/slug pair for custom answers. Each
    # slug falls back to the slug of its name when left blank.
    values: dict[str, QuestionValue] = {}
    rows = zip(
        post.getlist(f"entoption_{index}"),
        post.getlist(f"entname_{index}"),
        post.getlist(f"entslug_{index}"),
        strict=False,
    )
    for option, name, slug in rows:
        clean_name = name.strip()
        if not (option and clean_name):
            continue
        values[option] = EntityRef(
            name=clean_name, slug=slug.strip() or slugify(clean_name)
        )
    catch_name = (post.get(f"entcatchname_{index}") or "").strip()
    catch_slug = (post.get(f"entcatchslug_{index}") or "").strip()
    catchall = (
        EntityRef(name=catch_name, slug=catch_slug or slugify(catch_name))
        if catch_name
        else None
    )
    return values, catchall


def _target_from_post(post: QueryDict, index: int) -> QuestionTarget:
    choice = (post.get(f"target_{index}") or "ignore").strip()
    if choice == TIME_SLOTS_TARGET:
        return QuestionTarget(
            to=choice, values=_time_slot_values_from_post(post, index)
        )
    if choice in ENTITY_TARGETS:
        values, catchall = _entity_map_from_post(post, index)
        return QuestionTarget(to=choice, values=values, catchall=catchall)
    if choice.startswith("session.") or choice == "facilitator.display_name":
        return QuestionTarget(to=choice)
    name = (post.get(f"newname_{index}") or "").strip()
    slug = (post.get(f"newslug_{index}") or "").strip() or slugify(name)
    if choice == "personal-field" and slug:
        return QuestionTarget(to=f"personal.{slug}")
    if choice == "session-field" and slug:
        return QuestionTarget(to=f"field.{slug}")
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

        integrations = _import_integrations(self.request, current_event.pk)
        active = _active_integration(integrations, pk)
        if integrations and active is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)

        context["active_integration"] = active
        if active is not None:
            sphere_id = self.request.context.current_sphere_id
            questions = self.request.services.event_integrations.fetch_questions(
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
        integrations = _import_integrations(self.request, current_event.pk)
        if (active := _active_integration(integrations, pk)) is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        settings = _settings_from_post(self.request.POST)
        self.request.services.event_integrations.save_settings(
            current_event.pk, active.pk, settings.model_dump_json()
        )
        messages.success(self.request, _("Import recipe saved."))
        return redirect("panel:import-integration", slug=slug, pk=active.pk)


class _ImportActionView(PanelAccessMixin, EventContextMixin, View):
    """Shared lookup for the import action buttons (run / test a row)."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        integrations = _import_integrations(self.request, current_event.pk)
        if (active := _active_integration(integrations, pk)) is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        sphere_id = self.request.context.current_sphere_id
        self._act(sphere_id, current_event.pk, active.pk)
        return redirect("panel:import-integration", slug=slug, pk=active.pk)

    def _act(self, sphere_id: int, event_pk: int, integration_pk: int) -> None:
        raise NotImplementedError


class EventImportRunActionView(_ImportActionView):
    """Run the saved import recipe: create a proposal per source response."""

    def _act(self, sphere_id: int, event_pk: int, integration_pk: int) -> None:
        result = self.request.services.proposals_import.run(
            sphere_id, event_pk, integration_pk
        )
        messages.success(
            self.request, _("Created %(count)d proposals.") % {"count": result.created}
        )


class EventImportTestRowActionView(_ImportActionView):
    """Import one random response so the recipe can be eyeballed before a run."""

    def _act(self, sphere_id: int, event_pk: int, integration_pk: int) -> None:
        result = self.request.services.proposals_import.run_sample(
            sphere_id, event_pk, integration_pk
        )
        if result.created:
            messages.success(
                self.request,
                _(
                    "Test import created one proposal from a random row. Review "
                    "it, then delete it before running the full import."
                ),
            )
        else:
            messages.info(self.request, _("No responses found to test."))
