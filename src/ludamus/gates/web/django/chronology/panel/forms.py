"""Forms for the chronology event panel."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.translation import gettext_lazy as _
from pydantic import ValidationError

from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ludamus.pacts.chronology import IntegrationImplementation
    from ludamus.pacts.multiverse import ConnectionDTO


def integration_signature(connection_id: int, config_json: str) -> str:
    # Canonicalize so cosmetic whitespace changes don't force a re-check.
    canonical = json.dumps(
        json.loads(config_json), sort_keys=True, separators=(",", ":")
    )
    # Keyed with the server SECRET_KEY: only a server-run check can mint a valid
    # token, so a client cannot forge "this passed" without actually checking.
    return salted_hmac(
        "ludamus.chronology.integration-check",
        f"{connection_id}:{canonical}",
        algorithm="sha256",
    ).hexdigest()


@dataclass(frozen=True)
class IntegrationFormContext:
    """Per-event context used by `EventIntegrationForm` on create and edit."""

    taken_display_names_by_kind: dict[IntegrationKind, set[str]] = field(
        default_factory=dict
    )
    locked_kind: IntegrationKind | None = None
    initial_connection_id: int | None = None
    initial_config_json: str | None = None


class EventIntegrationForm(forms.Form):
    """Add / edit form for an event integration of a given kind."""

    display_name = forms.CharField(label=_("Display name"), max_length=255, strip=True)
    implementation = forms.ChoiceField(label=_("Implementation"))
    connection = forms.ChoiceField(label=_("Connection"))
    config_json = forms.CharField(
        label=_("Configuration (JSON)"),
        help_text=_(
            "A JSON object configuring the selected implementation. Run a "
            "successful check before saving."
        ),
        widget=forms.Textarea(attrs={"rows": 12, "spellcheck": "false"}),
        initial="{}",
    )
    last_ok_signature = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        implementations: Mapping[
            IntegrationImplementationId, IntegrationImplementation
        ],
        connections: Iterable[ConnectionDTO],
        context: IntegrationFormContext | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._context = context or IntegrationFormContext()
        self._implementations: dict[
            IntegrationImplementationId, IntegrationImplementation
        ] = dict(implementations)
        impl_field = cast("forms.ChoiceField", self.fields["implementation"])
        impl_field.choices = self._build_implementation_choices()
        conn_field = cast("forms.ChoiceField", self.fields["connection"])
        conn_field.choices = [(str(c.pk), c.display_name) for c in connections]

    def _build_implementation_choices(self) -> list[tuple[str, str]]:
        kind_order = {kind: index for index, kind in enumerate(IntegrationKind)}
        items = sorted(
            self._implementations.items(),
            key=lambda item: (kind_order[item[1].kind], item[0].value),
        )
        return [
            (impl_id.value, f"{impl.kind.value.capitalize()} — {impl_id.value}")
            for impl_id, impl in items
        ]

    @property
    def resolved_kind(self) -> IntegrationKind | None:
        if self._context.locked_kind is not None:
            return self._context.locked_kind
        identifier = self.cleaned_data.get("implementation")
        if isinstance(identifier, IntegrationImplementationId) and (
            impl := self._implementations.get(identifier)
        ):
            return impl.kind
        return None

    def clean_implementation(self) -> IntegrationImplementationId:
        raw = self.cleaned_data.get("implementation") or ""
        try:
            return IntegrationImplementationId(raw)
        except ValueError as exc:
            raise forms.ValidationError(
                _("Unknown implementation for this kind.")
            ) from exc

    def clean_config_json(self) -> str:
        raw = self.cleaned_data.get("config_json") or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(
                _("Not valid JSON: %(error)s") % {"error": str(exc)}
            ) from exc
        if not isinstance(parsed, dict):
            raise forms.ValidationError(_("Configuration must be a JSON object."))
        # Keep the raw text; the implementation's pydantic model parses it.
        return raw

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        identifier = cleaned.get("implementation")
        config_json = cleaned.get("config_json")
        if isinstance(identifier, IntegrationImplementationId) and isinstance(
            config_json, str
        ):
            if (impl := self._implementations.get(identifier)) is None:
                self.add_error(
                    "implementation", _("Unknown implementation for this kind.")
                )
            else:
                try:
                    impl.config_model.model_validate_json(config_json)
                except ValidationError as exc:
                    self._attach_pydantic_errors(exc)

        self._enforce_unique_display_name()

        if not self.errors:
            self._enforce_check_signature()
        return cleaned

    def _enforce_unique_display_name(self) -> None:
        display_name = self.cleaned_data.get("display_name")
        if not isinstance(display_name, str):
            return
        if (kind := self.resolved_kind) is None:
            return
        taken = self._context.taken_display_names_by_kind.get(kind, set())
        if display_name in taken:
            self.add_error(
                "display_name",
                _("An integration with this name already exists for this kind."),
            )

    def _attach_pydantic_errors(self, exc: ValidationError) -> None:
        for err in exc.errors():
            path = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
            self.add_error("config_json", f"{path}: {err.get('msg', '')}")

    def _enforce_check_signature(self) -> None:
        connection_id_raw = self.cleaned_data.get("connection")
        config_json = self.cleaned_data.get("config_json")
        if not isinstance(connection_id_raw, str) or not isinstance(config_json, str):
            return
        connection_id = int(connection_id_raw)

        if (
            self._context.initial_connection_id == connection_id
            and self._context.initial_config_json == config_json
        ):
            return

        expected = integration_signature(connection_id, config_json)
        provided_raw = self.cleaned_data.get("last_ok_signature")
        provided = provided_raw.strip() if isinstance(provided_raw, str) else ""
        if not constant_time_compare(provided, expected):
            self.add_error(
                None,
                _(
                    'Run "Check integration" against the current connection '
                    "and configuration before saving."
                ),
            )
