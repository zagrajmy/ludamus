from importlib import import_module

from django.apps import AppConfig

from ludamus.gates.web.django.analytics_routes import register_redaction_rules


class WebGatesConfig(AppConfig):
    """Django app config for web gates."""

    name = "ludamus.gates.web.django"
    label = "web_gates"

    def ready(self) -> None:
        register_redaction_rules()
        # `{% load vite_tags %}` imports the module lazily, mid-request, which is
        # too late for that request's `request_started` to have reset the
        # per-request set. Import it here so the receiver is connected first.
        import_module(f"{self.name}.templatetags.vite_tags")
