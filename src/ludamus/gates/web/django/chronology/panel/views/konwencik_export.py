"""Konwencik agenda export: the run action, the settings page and its forms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.generic.base import View

from ludamus.gates.web.django.chronology.panel.views.base import (
    EventContextMixin,
    PanelAccessMixin,
    PanelRequest,
)
from ludamus.pacts import NotFoundError
from ludamus.pacts.konwencik import KonwencikExportSettings
from ludamus.pacts.sheets import SheetExportError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.forms.formsets import BaseFormSet
    from django.http import HttpResponse, QueryDict

    from ludamus.pacts.konwencik import KonwencikNamedItemDTO, KonwencikSettingsContext

ICON_MAX_LENGTH = 64
_HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class _SettingsRow(TypedDict):
    item: KonwencikNamedItemDTO | None
    form: forms.Form


class _PageContext(TypedDict):
    active_nav: str
    integration_pk: int
    integration_display_name: str
    icon_formset: BaseFormSet[KonwencikIconForm]
    color_formset: BaseFormSet[KonwencikColorForm]
    overrides_form: KonwencikOverridesForm
    category_rows: list[_SettingsRow]
    track_rows: list[_SettingsRow]


class _ScopedRowForm(forms.Form):
    """One row of a per-object formset, keyed on a pk the event must own."""

    pk = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(
        self, *args: Any, allowed_pks: Iterable[int] = (), **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._allowed_pks = set(allowed_pks)

    def clean_pk(self) -> int:
        if (pk := self.cleaned_data["pk"]) not in self._allowed_pks:
            raise forms.ValidationError(_("This does not belong to the event."))
        return int(pk)


class KonwencikIconForm(_ScopedRowForm):
    icon = forms.CharField(
        label=gettext_lazy("Icon"),
        required=False,
        max_length=ICON_MAX_LENGTH,
        strip=True,
        help_text=gettext_lazy("Konwencik's own notation, for example fa.gamepad."),
    )


class KonwencikColorForm(_ScopedRowForm):
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
    # Paired on pk, not position: a re-rendered POST carries whatever rows the
    # client sent, and a pk the event does not own has no name to show.
    by_pk = {item.pk: item for item in items}
    return [{"item": by_pk.get(_row_pk(form)), "form": form} for form in forms_]


def _row_pk(form: forms.Form) -> int:
    raw = form["pk"].value()
    try:
        return int(raw)
    except TypeError, ValueError:
        return 0


def _icon_formset(
    context: KonwencikSettingsContext, data: QueryDict | None = None
) -> BaseFormSet[KonwencikIconForm]:
    return KonwencikIconFormSet(
        data,
        prefix="icons",
        form_kwargs={"allowed_pks": [item.pk for item in context.categories]},
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
        form_kwargs={"allowed_pks": [item.pk for item in context.tracks]},
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
        },
    )


def _settings_from(
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
    )


class KonwencikExportSettingsPageView(PanelAccessMixin, EventContextMixin, View):
    """Per-category icons, per-track colours and the two override fields."""

    request: PanelRequest

    def get(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        try:
            settings_context = (
                self.request.services.konwencik_export.get_settings_context(
                    sphere_id=self.request.context.current_sphere_id,
                    event_pk=current_event.pk,
                    pk=pk,
                )
            )
        except NotFoundError:
            messages.error(self.request, _("Integration not found."))
            return redirect("panel:event-integration-settings", slug=slug)

        context.update(
            _page_context(
                settings_context=settings_context,
                pk=pk,
                icons=_icon_formset(settings_context),
                colors=_color_formset(settings_context),
                overrides=_overrides_form(settings_context),
            )
        )
        return TemplateResponse(
            self.request, "chronology/panel/konwencik/settings.html", context
        )

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        service = self.request.services.konwencik_export
        try:
            settings_context = service.get_settings_context(
                sphere_id=self.request.context.current_sphere_id,
                event_pk=current_event.pk,
                pk=pk,
            )
        except NotFoundError:
            messages.error(self.request, _("Integration not found."))
            return redirect("panel:event-integration-settings", slug=slug)

        icons = _icon_formset(settings_context, self.request.POST)
        colors = _color_formset(settings_context, self.request.POST)
        overrides = _overrides_form(settings_context, self.request.POST)
        if not (icons.is_valid() and colors.is_valid() and overrides.is_valid()):
            context.update(
                _page_context(
                    settings_context=settings_context,
                    pk=pk,
                    icons=icons,
                    colors=colors,
                    overrides=overrides,
                )
            )
            return TemplateResponse(
                self.request, "chronology/panel/konwencik/settings.html", context
            )

        service.save_settings(
            sphere_id=self.request.context.current_sphere_id,
            event_pk=current_event.pk,
            pk=pk,
            settings=_settings_from(icons, colors, overrides),
        )
        messages.success(self.request, _("Export settings saved."))
        return redirect("panel:konwencik-export-settings", slug=slug, pk=pk)


def _page_context(
    *,
    settings_context: KonwencikSettingsContext,
    pk: int,
    icons: BaseFormSet[KonwencikIconForm],
    colors: BaseFormSet[KonwencikColorForm],
    overrides: KonwencikOverridesForm,
) -> _PageContext:
    return {
        "active_nav": "settings",
        "integration_pk": pk,
        "integration_display_name": settings_context.display_name,
        "icon_formset": icons,
        "color_formset": colors,
        "overrides_form": overrides,
        "category_rows": _rows(settings_context.categories, icons.forms),
        "track_rows": _rows(settings_context.tracks, colors.forms),
    }


class KonwencikExportActionView(PanelAccessMixin, EventContextMixin, View):
    """POST-only: rebuild the Konwencik tab from the current schedule."""

    request: PanelRequest

    def post(self, _request: PanelRequest, slug: str, pk: int) -> HttpResponse:
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
            return redirect("panel:event-integration-settings", slug=slug)
        except SheetExportError as error:
            messages.error(
                self.request, _("Export failed: %(error)s") % {"error": error}
            )
            return redirect("panel:event-integration-settings", slug=slug)

        messages.success(
            self.request,
            ngettext(
                "Exported %(count)d session.",
                "Exported %(count)d sessions.",
                outcome.rows_written,
            )
            % {"count": outcome.rows_written},
        )
        if outcome.sessions_skipped:
            messages.warning(
                self.request,
                ngettext(
                    "%(count)d session skipped: longer than a day.",
                    "%(count)d sessions skipped: longer than a day.",
                    outcome.sessions_skipped,
                )
                % {"count": outcome.sessions_skipped},
            )
        return redirect("panel:event-integration-settings", slug=slug)
