from importlib import import_module

from django.apps import AppConfig


class WebGatesConfig(AppConfig):
    """Django app config for web gates."""

    name = "ludamus.gates.web.django"
    label = "web_gates"

    def ready(self) -> None:
        # The URLconf is fully loaded by now, so the analytics redaction rules
        # can be derived from it once instead of per request.
        from ludamus.gates.web.django.analytics_routes import (  # ruff: ignore[import-outside-top-level]
            register_redaction_rules,
        )

        register_redaction_rules()
        # `{% load vite_tags %}` imports the module lazily, mid-request, which is
        # too late for that request's `request_started` to have reset the
        # per-request set. Import it here so the receiver is connected first.
        import_module(f"{self.name}.templatetags.vite_tags")
