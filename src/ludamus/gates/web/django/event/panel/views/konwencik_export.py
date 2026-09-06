"""Konwencik agenda export: the run action, the settings page and its forms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, TypedDict

from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext, ngettext_lazy
from django.views.generic.base import View

from ludamus.gates.web.django.event.panel.views.base import (
    EventContextMixin,
    EventPanelAccessMixin,
    EventPanelRequest,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.konwencik import (
    ExportInProgressError,
    KonwencikExportSettings,
    KonwencikSkipReason,
)
from ludamus.pacts.sheets import SheetExportError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.forms.formsets import BaseFormSet
    from django.http import HttpResponse, QueryDict

    from ludamus.gates.web.django.event.panel.views.base import EventPageContext
    from ludamus.pacts.chronology import EventIntegrationDTO
    from ludamus.pacts.konwencik import (
        KonwencikLastRun,
        KonwencikNamedItemDTO,
        KonwencikSettingsContext,
    )

ICON_MAX_LENGTH = 64
_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"

# One sentence per reason the export drops a session, so the panel says which
# rule bit rather than reporting every skip as an over-long session.
SKIP_MESSAGES = {
    KonwencikSkipReason.TOO_LONG: ngettext_lazy(
        "%(count)d session skipped: longer than a day.",
        "%(count)d sessions skipped: longer than a day.",
        "count",
    ),
    KonwencikSkipReason.INTERNAL_TRACKS: ngettext_lazy(
        "%(count)d session skipped: every block it is in is internal.",
        "%(count)d sessions skipped: every block they are in is internal.",
        "count",
    ),
}


class _SettingsRow(TypedDict):
    # `item` is None only for a surplus row: a hand-crafted POST can raise
    # TOTAL_FORMS above the number of things the event has, and those rows have
    # no name to show.
    item: KonwencikNamedItemDTO | None
    form: forms.Form


class _PageContext(TypedDict):
    active_nav: str
    active_integration: EventIntegrationDTO
    last_run: KonwencikLastRun | None
    icon_formset: BaseFormSet[KonwencikIconForm]
    color_formset: BaseFormSet[KonwencikColorForm]
    overrides_form: KonwencikOverridesForm
    category_rows: list[_SettingsRow]
    track_rows: list[_SettingsRow]


class _RowForm(forms.Form):
    """One formset row, carrying the pk of the thing it configures.

    Ownership of that pk is not checked here. `save_settings` scopes every id
    against the event before it writes, which is where the rule belongs, and a
    second copy in the gate only makes the two disagree about what a foreign pk
    does.
    """

    pk = forms.IntegerField(widget=forms.HiddenInput)


class KonwencikIconForm(_RowForm):
    icon = forms.CharField(
        label=gettext_lazy("Icon"),
        required=False,
        max_length=ICON_MAX_LENGTH,
        strip=True,
        help_text=gettext_lazy("Konwencik's own notation, for example fa.gamepad."),
    )


class KonwencikColorForm(_RowForm):
    color = forms.RegexField(
        label=gettext_lazy("Background"),
        regex=_HEX_COLOR,
        required=False,
        strip=True,
        error_messages={"invalid": gettext_lazy("Use a hex colour, e.g. #1e88e5.")},
        help_text=gettext_lazy("Leave empty for no background."),
    )


class KonwencikOverridesForm(forms.Form):
    photo_url_field = forms.ChoiceField(
        label=gettext_lazy("Photo link field"), required=False
    )
    icon_field = forms.ChoiceField(label=gettext_lazy("Icon field"), required=False)
    sync_enabled = forms.BooleanField(
        label=gettext_lazy("Keep the Konwencik tab in sync"),
        required=False,
        help_text=gettext_lazy(
            "Re-exports the schedule periodically until the event is over."
        ),
    )

    def __init__(
        self, *args: Any, session_fields: Iterable[KonwencikNamedItemDTO], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        choices = [("", _("No override"))] + [
            (str(field.pk), field.name) for field in session_fields
        ]
        for name in ("photo_url_field", "icon_field"):
            field = self.fields[name]
            if isinstance(field, forms.ChoiceField):
                field.choices = choices


KonwencikIconFormSet = forms.formset_factory(KonwencikIconForm, extra=0)
KonwencikColorFormSet = forms.formset_factory(KonwencikColorForm, extra=0)


def _rows(
    items: Iterable[KonwencikNamedItemDTO], forms_: Iterable[forms.Form]
) -> list[_SettingsRow]:
    # Positional: the formset is built from `items` in this order, so row N
    # configures item N.
    named = list(items)
    return [
        {"item": named[index] if index < len(named) else None, "form": form}
        for index, form in enumerate(forms_)
    ]


def _icon_formset(
    context: KonwencikSettingsContext, data: QueryDict | None = None
) -> BaseFormSet[KonwencikIconForm]:
    return KonwencikIconFormSet(
        data,
        prefix="icons",
        initial=[
            {"pk": item.pk, "icon": context.settings.category_icons.get(item.pk, "")}
            for item in context.categories
        ],
    )


def _color_formset(
    context: KonwencikSettingsContext, data: QueryDict | None = None
) -> BaseFormSet[KonwencikColorForm]:
    return KonwencikColorFormSet(
        data,
        prefix="colors",
        initial=[
            {"pk": item.pk, "color": context.settings.track_colors.get(item.pk, "")}
            for item in context.tracks
        ],
    )


def _overrides_form(
    context: KonwencikSettingsContext, data: QueryDict | None = None
) -> KonwencikOverridesForm:
    settings = context.settings
    return KonwencikOverridesForm(
        data,
        session_fields=context.session_fields,
        initial={
            "photo_url_field": (
                str(settings.photo_url_field_pk) if settings.photo_url_field_pk else ""
            ),
            "icon_field": str(settings.icon_field_pk) if settings.icon_field_pk else "",
            "sync_enabled": settings.sync_enabled,
        },
    )


def _settings_from(
    *,
    icons: BaseFormSet[KonwencikIconForm],
    colors: BaseFormSet[KonwencikColorForm],
    overrides: KonwencikOverridesForm,
) -> KonwencikExportSettings:
    photo_raw = overrides.cleaned_data["photo_url_field"]
    icon_raw = overrides.cleaned_data["icon_field"]
    return KonwencikExportSettings(
        category_icons={
            row["pk"]: row["icon"] for row in icons.cleaned_data if row.get("icon")
        },
        track_colors={
            row["pk"]: row["color"] for row in colors.cleaned_data if row.get("color")
        },
        photo_url_field_pk=int(photo_raw) if photo_raw else None,
        icon_field_pk=int(icon_raw) if icon_raw else None,
        sync_enabled=bool(overrides.cleaned_data["sync_enabled"]),
    )


class _Loaded(NamedTuple):
    page: EventPageContext
    event_pk: int
    integration: EventIntegrationDTO
    settings: KonwencikSettingsContext


def _konwencik_integrations(
    request: EventPanelRequest, event_pk: int
) -> list[EventIntegrationDTO]:
    return [
        i
        for i in request.services.event_integrations.list_for_event(
            event_pk, IntegrationKind.EXPORT
        )
        if i.implementation == IntegrationImplementationId.KONWENCIK_SHEET_PUSHER
    ]


class KonwencikExportSettingsPageView(EventPanelAccessMixin, EventContextMixin, View):
    """Per-category icons, per-track colours and the two override fields."""

    request: EventPanelRequest

    def get(
        self, _request: EventPanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, _Loaded):
            return loaded
        return self._render(
            loaded,
            icons=_icon_formset(loaded.settings),
            colors=_color_formset(loaded.settings),
            overrides=_overrides_form(loaded.settings),
        )

    def post(
        self, _request: EventPanelRequest, slug: str, pk: int | None = None
    ) -> HttpResponse:
        loaded = self._load(slug, pk)
        if not isinstance(loaded, _Loaded):
            return loaded

        icons = _icon_formset(loaded.settings, self.request.POST)
        colors = _color_formset(loaded.settings, self.request.POST)
        overrides = _overrides_form(loaded.settings, self.request.POST)
        if not (icons.is_valid() and colors.is_valid() and overrides.is_valid()):
            return self._render(loaded, icons=icons, colors=colors, overrides=overrides)

        self.request.services.konwencik_export.save_settings(
            sphere_id=self.request.context.current_sphere_id,
            event_pk=loaded.event_pk,
            pk=loaded.integration.pk,
            settings=_settings_from(icons=icons, colors=colors, overrides=overrides),
        )
        messages.success(self.request, _("Export settings saved."))
        return redirect(
            "panel:konwencik-export-settings", slug=slug, pk=loaded.integration.pk
        )

    def _load(self, slug: str, pk: int | None) -> _Loaded | HttpResponse:
        # A response is a return value rather than an exception because both
        # verbs answer the same three ways: no such event, no such export, or
        # the empty state.
        if (context := self.get_typed_event_context(slug)) is None:
            return redirect("panel:index")
        current_event = context["current_event"]
        integrations = _konwencik_integrations(self.request, current_event.pk)
        active = (
            next((i for i in integrations if i.pk == pk), None)
            if pk is not None
            else next(iter(integrations), None)
        )
        if active is None:
            # A named pk that is not one of this event's Konwencik exports is a
            # wrong link; the bare page with none configured is the empty state.
            if pk is not None:
                messages.error(self.request, _("Integration not found."))
                return redirect("panel:konwencik-export", slug=slug)
            return TemplateResponse(
                self.request,
                "panel/konwencik-export-settings.html",
                {
                    **context,
                    "active_nav": "konwencik-export",
                    "active_integration": None,
                },
            )
        settings_context = self.request.services.konwencik_export.get_settings_context(
            sphere_id=self.request.context.current_sphere_id,
            event_pk=current_event.pk,
            pk=active.pk,
        )
        return _Loaded(
            page=context,
            event_pk=current_event.pk,
            integration=active,
            settings=settings_context,
        )

    def _render(
        self,
        loaded: _Loaded,
        *,
        icons: BaseFormSet[KonwencikIconForm],
        colors: BaseFormSet[KonwencikColorForm],
        overrides: KonwencikOverridesForm,
    ) -> HttpResponse:
        context = {
            **loaded.page,
            **_page_context(
                settings_context=loaded.settings,
                integration=loaded.integration,
                icons=icons,
                colors=colors,
                overrides=overrides,
            ),
        }
        return TemplateResponse(
            self.request, "panel/konwencik-export-settings.html", context
        )


def _page_context(
    *,
    settings_context: KonwencikSettingsContext,
    integration: EventIntegrationDTO,
    icons: BaseFormSet[KonwencikIconForm],
    colors: BaseFormSet[KonwencikColorForm],
    overrides: KonwencikOverridesForm,
) -> _PageContext:
    return {
        "active_nav": "konwencik-export",
        "active_integration": integration,
        "last_run": settings_context.last_run,
        "icon_formset": icons,
        "color_formset": colors,
        "overrides_form": overrides,
        "category_rows": _rows(settings_context.categories, icons.forms),
        "track_rows": _rows(settings_context.tracks, colors.forms),
    }


class KonwencikExportActionView(EventPanelAccessMixin, EventContextMixin, View):
    """POST-only: rebuild the Konwencik tab from the current schedule."""

    request: EventPanelRequest

    def post(self, _request: EventPanelRequest, slug: str, pk: int) -> HttpResponse:
        _context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")

        try:
            outcome = self.request.services.konwencik_export.export_now(
                sphere_id=self.request.context.current_sphere_id,
                event_pk=current_event.pk,
                pk=pk,
            )
        except NotFoundError:
            messages.error(self.request, _("Integration not found."))
            return redirect("panel:konwencik-export", slug=slug)
        except ExportInProgressError:
            messages.error(
                self.request, _("An export is already running, try again shortly.")
            )
            return redirect("panel:konwencik-export-settings", slug=slug, pk=pk)
        except SheetExportError as error:
            messages.error(
                self.request, _("Export failed: %(error)s") % {"error": error}
            )
            return redirect("panel:konwencik-export-settings", slug=slug, pk=pk)

        messages.success(
            self.request,
            ngettext(
                "Exported %(count)d session.",
                "Exported %(count)d sessions.",
                outcome.rows_written,
            )
            % {"count": outcome.rows_written},
        )
        for reason, count in outcome.skipped.items():
            if count:
                messages.warning(self.request, SKIP_MESSAGES[reason] % {"count": count})
        return redirect("panel:konwencik-export-settings", slug=slug, pk=pk)
