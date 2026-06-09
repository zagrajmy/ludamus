"""Google Docs Import panel section.

An import integration is a dumb connection + capability owned by Chronology;
this section is where the (hardcoded) Google Docs import is configured
(per-question mapping) and run. Integrations settings never reference import.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.timezone import get_current_timezone, localtime, make_aware
from django.utils.translation import gettext as _
from django.views.generic.base import View
from pydantic import ValidationError

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
    import_tab_urls,
)
from ludamus.mills.submissions import slugify
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.submissions import (
    DurationSpec,
    EntityRef,
    FieldDefinition,
    FieldDefinitions,
    ImportLogStatus,
    ImportSettings,
    QuestionTarget,
    QuestionValue,
    TimeSlotSpec,
)

if TYPE_CHECKING:
    from django.http import QueryDict

    from ludamus.pacts import EventDTO
    from ludamus.pacts.chronology import EventIntegrationDTO, SourceQuestion

SESSION_COLUMNS = ("title", "description", "duration", "participants_limit")
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


class OptionDuration(TypedDict):
    option: str
    iso: str


class RecipeRow(TypedDict):
    index: int
    question: str
    selected: str
    confirmed: bool
    field_name: str
    field_slug: str
    field_type: str
    is_multiple: bool
    allow_custom: bool
    options: str
    option_windows: list[OptionWindows]
    option_entities: list[OptionEntity]
    option_durations: list[OptionDuration]
    catchall_name: str
    catchall_slug: str


class SummaryRow(TypedDict):
    index: int
    status: Literal["confirmed", "ignored", "unconfirmed"]
    question: str
    mapping: str
    details: str


class EditNavOption(TypedDict):
    index: int
    question: str


class EditNav(TypedDict):
    index: int
    total: int
    position: int
    prev_index: int | None
    next_index: int | None
    options: list[EditNavOption]


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
        "confirmed": bool(target and target.confirmed),
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
        "option_durations": _option_durations(question, target),
        "catchall_name": target.catchall.name if target and target.catchall else "",
        "catchall_slug": target.catchall.slug if target and target.catchall else "",
    }


def _edit_nav(rows: list[RecipeRow], current: int) -> EditNav:
    total = len(rows)
    return {
        "index": current,
        "total": total,
        "position": current + 1,
        "prev_index": current - 1 if current > 0 else None,
        "next_index": current + 1 if current + 1 < total else None,
        "options": [{"index": r["index"], "question": r["question"]} for r in rows],
    }


def _edit_row(raw: str | None, rows: list[RecipeRow]) -> RecipeRow | None:
    # The summary linked to ?edit=<index>; ignore anything non-numeric or out of
    # range and fall back to the full list view.
    if raw is None or not raw.isdigit():
        return None
    index = int(raw)
    if 0 <= index < len(rows):
        return rows[index]
    return None


def _summary_row(
    index: int,
    question: SourceQuestion,
    target: QuestionTarget | None,
    definitions: FieldDefinitions,
) -> SummaryRow:
    if target is not None and target.confirmed:
        status: Literal["confirmed", "ignored", "unconfirmed"] = "confirmed"
    elif target is not None and target.ignore:
        status = "ignored"
    else:
        status = "unconfirmed"
    return {
        "index": index,
        "status": status,
        "question": question.title,
        "mapping": _mapping_label(target, definitions),
        "details": _details_label(target, definitions),
    }


_FIXED_MAPPING_LABELS = {
    "session.time_slots": lambda: _("Time slots"),
    "track": lambda: _("Track"),
    "category": lambda: _("Category"),
    "facilitator.display_name": lambda: _("Facilitator — Display name"),
}


def _mapping_label(target: QuestionTarget | None, definitions: FieldDefinitions) -> str:
    if target is None or (not target.to and not target.ignore):
        return ""
    if target.ignore and not target.to:
        return _("Don't import")
    to = target.to or ""
    if (fixed := _FIXED_MAPPING_LABELS.get(to)) is not None:
        return fixed()
    if to.startswith("session."):
        col = to.removeprefix("session.").replace("_", " ")
        return _("Proposal — %(col)s") % {"col": col.capitalize()}
    if to.startswith("facilitator."):
        part = to.removeprefix("facilitator.").replace("_", " ")
        return _("Facilitator — %(part)s") % {"part": part.capitalize()}
    return _field_mapping_label(to, definitions)


def _field_mapping_label(to: str, definitions: FieldDefinitions) -> str:
    if to.startswith("personal."):
        slug = to.removeprefix("personal.")
        name = _definition_name(definitions.personal_fields.get(slug), slug)
        return _("Personal field — %(name)s") % {"name": name}
    if to.startswith("field."):
        slug = to.removeprefix("field.")
        name = _definition_name(definitions.session_fields.get(slug), slug)
        return _("Session field — %(name)s") % {"name": name}
    return ""


def _details_label(target: QuestionTarget | None, definitions: FieldDefinitions) -> str:
    if target is None or target.ignore or not target.to:
        return ""
    to = target.to
    if to == "session.time_slots":
        return _("%(count)d windows") % {"count": len(target.values)}
    if to == "session.duration":
        return _("%(count)d mappings") % {"count": len(target.values)}
    if to in ENTITY_TARGETS:
        return _("%(count)d mappings") % {"count": len(target.values)}
    if to.startswith(("personal.", "field.")):
        slug = to.split(".", 1)[1]
        store = (
            definitions.personal_fields
            if to.startswith("personal.")
            else definitions.session_fields
        )
        if (definition := store.get(slug)) is None:
            return ""
        if definition.type == "select":
            return _("Select — %(count)d options") % {"count": len(definition.options)}
        if definition.type == "checkbox":
            return _("Checkbox")
        return _("Text")
    return ""


def _definition_name(definition: FieldDefinition | None, slug: str) -> str:
    if definition is None or not definition.name:
        return slug
    return definition.name


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


def _option_durations(
    question: SourceQuestion, target: QuestionTarget | None
) -> list[OptionDuration]:
    # One row per source option, pre-filled with the operator-typed ISO 8601
    # duration so the (hidden) editor is ready the moment the row becomes a
    # session-duration target. A blank ISO leaves that option unmapped: the
    # importer then skips rows whose answer hits this option.
    configured = target.values if target else {}
    rows: list[OptionDuration] = []
    for option in question.options:
        spec = configured.get(option)
        iso = spec.iso if isinstance(spec, DurationSpec) else ""
        rows.append({"option": option, "iso": iso})
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


def _duration_values_from_post(post: QueryDict, index: int) -> dict[str, QuestionValue]:
    # Per-option ISO duration rows submit parallel arrays; a blank ISO drops
    # that option (its answers will be skipped at import time).
    values: dict[str, QuestionValue] = {}
    rows = zip(
        post.getlist(f"droption_{index}"), post.getlist(f"driso_{index}"), strict=False
    )
    for option, iso in rows:
        clean_iso = iso.strip()
        if not (option and clean_iso):
            continue
        values[option] = DurationSpec(iso=clean_iso)
    return values


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
    if choice == "session.duration":
        return QuestionTarget(to=choice, values=_duration_values_from_post(post, index))
    if choice.startswith("session.") or choice == "facilitator.display_name":
        return QuestionTarget(to=choice)
    name = (post.get(f"newname_{index}") or "").strip()
    slug = (post.get(f"newslug_{index}") or "").strip() or slugify(name)
    if choice == "personal-field" and slug:
        return QuestionTarget(to=f"personal.{slug}")
    if choice == "session-field" and slug:
        return QuestionTarget(to=f"field.{slug}")
    return QuestionTarget(ignore=True)


def _pretty_json(raw: str | None) -> str:
    text = raw or "{}"
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        return text


def _load_questions(
    request: PanelRequest, event_pk: int, active: EventIntegrationDTO
) -> list[SourceQuestion]:
    # Cached snapshot keeps the Proposal / Review tabs off the Google Forms
    # API on every request; the operator triggers an explicit reset via the
    # "Refetch form" action. A cold integration (no snapshot yet) gets one
    # transparent live-fetch that fills the snapshot without touching
    # confirmed flags — only the explicit refetch resets those.
    cached = request.services.event_integrations.get_cached_questions(
        event_pk, active.pk
    )
    if cached or (
        active.questions_snapshot_json and active.questions_snapshot_json != "[]"
    ):
        return cached
    sphere_id = request.context.current_sphere_id
    return request.services.event_integrations.populate_questions_snapshot(
        sphere_id, event_pk, active.pk
    )


class _ImportTabView(PanelAccessMixin, EventContextMixin, View):
    """Shared loading for the Google Docs import tabs (proposal / json / run)."""

    request: PanelRequest
    active_tab = ""

    def _load(
        self, slug: str, pk: int | None
    ) -> tuple[dict[str, Any], EventDTO, EventIntegrationDTO | None] | HttpResponse:
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
            context["active_tab"] = self.active_tab
            context["tab_urls"] = import_tab_urls(slug, active.pk)
        return context, current_event, active


class EventImportProposalView(_ImportTabView):
    """Proposal tab: the read-only summary of every question's mapping."""

    active_tab = "proposal"

    def get(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, tuple):
            return loaded
        context, current_event, active = loaded
        if active is not None:
            questions = _load_questions(self.request, current_event.pk, active)
            settings = ImportSettings.model_validate_json(active.settings_json or "{}")
            context["summary_rows"] = [
                _summary_row(
                    index, q, settings.questions.get(q.title), settings.definitions
                )
                for index, q in enumerate(questions)
            ]
        return TemplateResponse(self.request, "panel/import.html", context)


class EventImportReviewView(_ImportTabView):
    """Review tab: walk through each question's mapping one at a time."""

    active_tab = "review"

    def get(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, tuple):
            return loaded
        context, current_event, active = loaded
        if active is not None:
            questions = _load_questions(self.request, current_event.pk, active)
            settings = ImportSettings.model_validate_json(active.settings_json or "{}")
            context["session_columns"] = SESSION_COLUMNS
            context["rows"] = [
                _row(index, q, settings.questions.get(q.title), settings.definitions)
                for index, q in enumerate(questions)
            ]
            # Default to the first question when no ?edit is supplied or the
            # value is invalid (non-numeric, out of range); the Review tab is
            # never empty so the operator always lands on something actionable.
            edit = _edit_row(self.request.GET.get("edit"), context["rows"])
            if edit is None and context["rows"]:
                edit = context["rows"][0]
            context["edit_row"] = edit
            context["edit_nav"] = (
                _edit_nav(context["rows"], context["edit_row"]["index"])
                if context["edit_row"]
                else None
            )
        template = (
            "panel/parts/import-review-region.html"
            if self.request.headers.get("HX-Request")
            else "panel/import-review.html"
        )
        return TemplateResponse(self.request, template, context)


class EventImportRowSaveView(PanelAccessMixin, EventContextMixin, View):
    """Persist a single question's mapping and mark it confirmed."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        integrations = _import_integrations(self.request, current_event.pk)
        if (active := _active_integration(integrations, pk)) is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        raw_index = (self.request.POST.get("index") or "").strip()
        question = self.request.POST.get(f"question_{raw_index}") if raw_index else None
        if not raw_index.isdigit() or not question:
            messages.error(self.request, _("Invalid row submission."))
            return redirect("panel:import-review", slug=slug, pk=active.pk)
        index = int(raw_index)
        settings = ImportSettings.model_validate_json(active.settings_json or "{}")
        target = _target_from_post(self.request.POST, index)
        target.confirmed = True
        settings.questions[question] = target
        if target.to and target.to.startswith("personal."):
            slug_part = target.to.removeprefix("personal.")
            settings.definitions.personal_fields[slug_part] = _definition_from_post(
                self.request.POST, index
            )
        elif target.to and target.to.startswith("field."):
            slug_part = target.to.removeprefix("field.")
            settings.definitions.session_fields[slug_part] = _definition_from_post(
                self.request.POST, index
            )
        self.request.services.event_integrations.save_settings(
            current_event.pk, active.pk, settings.model_dump_json()
        )
        messages.success(self.request, _("Question saved."))
        cached = self.request.services.event_integrations.get_cached_questions(
            current_event.pk, active.pk
        )
        if (next_index := index + 1) < len(cached):
            review_url = reverse(
                "panel:import-review", kwargs={"slug": slug, "pk": active.pk}
            )
            target_url = f"{review_url}?edit={next_index}"
        else:
            target_url = reverse(
                "panel:import-integration", kwargs={"slug": slug, "pk": active.pk}
            )
        if self.request.headers.get("HX-Request"):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = target_url
            return response
        return redirect(target_url)


class EventImportJsonView(_ImportTabView):
    """JSON tab: edit the raw import settings blob directly."""

    active_tab = "json"

    def get(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, tuple):
            return loaded
        context, _current_event, active = loaded
        if active is not None:
            context["settings_json"] = _pretty_json(active.settings_json)
        return TemplateResponse(self.request, "panel/import-json.html", context)

    def post(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, tuple):
            return loaded
        context, current_event, active = loaded
        if active is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        raw = (self.request.POST.get("settings_json") or "").strip() or "{}"
        try:
            ImportSettings.model_validate_json(raw)
        except ValidationError:
            messages.error(self.request, _("Invalid import settings JSON."))
            context["settings_json"] = raw
            return TemplateResponse(self.request, "panel/import-json.html", context)
        self.request.services.event_integrations.save_settings(
            current_event.pk, active.pk, raw
        )
        messages.success(self.request, _("Import settings saved."))
        return redirect("panel:import-json", slug=slug, pk=active.pk)


class EventImportRunPageView(_ImportTabView):
    """Import run tab: sheet settings + the import actions, with inferred status."""

    active_tab = "run"

    def get(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, tuple):
            return loaded
        context, current_event, active = loaded
        if active is not None:
            settings = ImportSettings.model_validate_json(active.settings_json or "{}")
            cached = self.request.services.event_integrations.get_cached_questions(
                current_event.pk, active.pk
            )
            # Form-linked sheets always carry these two metadata columns ahead of
            # the form's own question columns; surface them as unique-key
            # candidates without a live sheet fetch. Operators uncheck them if
            # the form doesn't collect email.
            forms_metadata = ("Timestamp", "Email Address")
            seen: set[str] = set()
            available: list[str] = []
            for col in (*forms_metadata, *settings.questions.keys()):
                if col and col not in seen:
                    seen.add(col)
                    available.append(col)
            context["header_row"] = settings.header_row
            context["unique_key_columns"] = settings.unique_key_columns
            context["available_columns"] = available
            context["fields_imported"] = bool(cached)
            context["fields_count"] = len(cached)
            mappings = [t for t in settings.questions.values() if t.to or t.ignore]
            context["mapping_total"] = len(mappings)
            context["mapping_confirmed"] = sum(1 for t in mappings if t.confirmed)
            context["no_unique_keys_label"] = _("No columns selected.")
        return TemplateResponse(self.request, "panel/import-run.html", context)


_LOG_STATUS_FILTERS = {
    "all": None,
    "skipped": ImportLogStatus.SKIPPED,
    "success": ImportLogStatus.SUCCESS,
}


def _log_pill_urls(slug: str, pk: int, *, search: str) -> dict[str, str]:
    base = reverse("panel:import-log", kwargs={"slug": slug, "pk": pk})
    suffix = f"&search={search}" if search else ""
    return {key: f"{base}?status={key}{suffix}" for key in _LOG_STATUS_FILTERS}


class EventImportLogPageView(_ImportTabView):
    """Log tab: every attempt with its status, grouped errors and successes."""

    active_tab = "log"

    def get(
        self, _request: PanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, tuple):
            return loaded
        context, current_event, active = loaded
        if active is None:
            return TemplateResponse(self.request, "panel/import-log.html", context)
        raw_status = (self.request.GET.get("status") or "all").strip()
        status_key = raw_status if raw_status in _LOG_STATUS_FILTERS else "all"
        status_filter = _LOG_STATUS_FILTERS[status_key]
        search = (self.request.GET.get("search") or "").strip()
        raw_focus = (self.request.GET.get("focus") or "").strip()
        focus_pk = int(raw_focus) if raw_focus.isdigit() else None
        # The repo filter already narrows by status when set; for grouping we
        # always read both buckets so the counts stay accurate even when only
        # one section renders.
        entries = self.request.services.proposals_import.list_log_entries(
            current_event.pk, active.pk, search=search
        )
        # Each (integration, row_index) is unique now, so a simple split by
        # status covers it — no per-row dedupe needed.
        errors = [e for e in entries if e.status == ImportLogStatus.SKIPPED]
        successes = [e for e in entries if e.status == ImportLogStatus.SUCCESS]
        successes_open = status_filter == ImportLogStatus.SUCCESS
        if focus_pk is not None:
            focused = next((e for e in entries if e.pk == focus_pk), None)
            if focused is not None and focused.status == ImportLogStatus.SUCCESS:
                successes_open = True
        context["log_status"] = status_key
        context["log_search"] = search
        context["log_focus_pk"] = focus_pk
        context["log_filter_urls"] = _log_pill_urls(
            current_event.slug, active.pk, search=search
        )
        context["log_show_errors"] = status_filter != ImportLogStatus.SUCCESS
        context["log_show_successes"] = status_filter != ImportLogStatus.SKIPPED
        context["log_successes_open"] = successes_open
        context["log_errors"] = errors if context["log_show_errors"] else []
        context["log_successes"] = successes if context["log_show_successes"] else []
        context["log_total_attempts"] = len(entries)
        context["log_success_count"] = len(successes)
        context["log_error_count"] = len(errors)
        return TemplateResponse(self.request, "panel/import-log.html", context)


class EventImportSettingsSaveView(PanelAccessMixin, EventContextMixin, View):
    """Persist the sheet-level config (header row, unique-key cols).

    Rendered inline on the Run tab; this endpoint is POST-only.
    """

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        integrations = _import_integrations(self.request, current_event.pk)
        if (active := _active_integration(integrations, pk)) is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        settings = ImportSettings.model_validate_json(active.settings_json or "{}")
        raw_row = (self.request.POST.get("header_row") or "").strip()
        if not raw_row.isdigit() or int(raw_row) < 1:
            messages.error(self.request, _("Header row must be 1 or greater."))
            return redirect("panel:import-run", slug=slug, pk=active.pk)
        settings.header_row = int(raw_row)
        # Trust the operator: any non-empty column name is a valid unique-key
        # candidate. Sheet metadata columns (Timestamp, Email Address) aren't
        # in settings.questions, so we can't filter against the recipe.
        settings.unique_key_columns = [
            stripped
            for col in self.request.POST.getlist("unique_key_columns")
            if (stripped := col.strip())
        ]
        self.request.services.event_integrations.save_settings(
            current_event.pk, active.pk, settings.model_dump_json()
        )
        messages.success(self.request, _("Sheet settings saved."))
        return redirect("panel:import-run", slug=slug, pk=active.pk)


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
        return redirect("panel:import-run", slug=slug, pk=active.pk)

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
        if result.duplicates:
            messages.info(
                self.request,
                _("Skipped %(count)d responses already imported.")
                % {"count": result.duplicates},
            )
        if result.skipped:
            messages.warning(
                self.request,
                _("Skipped %(count)d responses with an invalid or unmapped answer.")
                % {"count": result.skipped},
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
        elif result.skipped:
            messages.warning(
                self.request,
                _(
                    "Test row was skipped because one of its mapped answers "
                    "is invalid or has no mapping."
                ),
            )
        else:
            messages.info(self.request, _("No responses found to test."))


class _EventImportLogActionView(PanelAccessMixin, EventContextMixin, View):
    """Base for actions that take an `entry_id` from the Log tab."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        integrations = _import_integrations(self.request, current_event.pk)
        if (active := _active_integration(integrations, pk)) is None:
            messages.error(self.request, _("Import integration not found."))
            return redirect("panel:import", slug=slug)
        raw = (self.request.POST.get("entry_id") or "").strip()
        if not raw.isdigit():
            messages.error(self.request, _("Invalid log entry."))
            return redirect("panel:import-log", slug=slug, pk=active.pk)
        entry_pk = int(raw)
        sphere_id = self.request.context.current_sphere_id
        self._act(sphere_id, current_event.pk, entry_pk)
        return redirect("panel:import-log", slug=slug, pk=active.pk)

    def _act(self, sphere_id: int, event_pk: int, entry_pk: int) -> None:
        raise NotImplementedError


class EventImportLogRetryActionView(_EventImportLogActionView):
    """Retry a single skipped log entry against the current recipe."""

    def _act(self, sphere_id: int, event_pk: int, entry_pk: int) -> None:
        succeeded = self.request.services.proposals_import.retry_entry(
            sphere_id, event_pk, entry_pk
        )
        if succeeded:
            messages.success(self.request, _("Row imported."))
        else:
            messages.warning(self.request, _("Row still cannot be imported."))


class EventImportLogReimportActionView(_EventImportLogActionView):
    """Reapply the source row to the existing session for a success entry."""

    def _act(self, sphere_id: int, event_pk: int, entry_pk: int) -> None:
        succeeded = self.request.services.proposals_import.reimport_entry(
            sphere_id, event_pk, entry_pk
        )
        if succeeded:
            messages.success(self.request, _("Proposal reimported from source."))
        else:
            messages.warning(self.request, _("Reimport failed."))


class EventImportRefetchView(PanelAccessMixin, EventContextMixin, View):
    """Pull a fresh question snapshot from the source form and drop confirmed."""

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
        questions = self.request.services.event_integrations.refetch_questions(
            sphere_id, current_event.pk, active.pk
        )
        messages.success(
            self.request,
            _("Form refetched: %(count)d questions.") % {"count": len(questions)},
        )
        return redirect("panel:import-run", slug=slug, pk=active.pk)
