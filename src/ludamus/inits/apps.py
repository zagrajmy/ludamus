"""Startup wiring for the hooks that gates and links leave open.

Some entry points are found by the framework rather than built by a composition
root: Django dispatches a management command by name, builds the admin and its
actions itself, and the analytics link needs rules only the URLconf can derive.
Each exposes a registry, and this is where the registries are filled.
"""

from typing import override

from django.apps import AppConfig

from ludamus.gates.cli.django import wiring
from ludamus.gates.web.django.analytics_routes import build_redaction_rules
from ludamus.inits.config import scheduler_mode
from ludamus.links.analytics import redaction


class InitsConfig(AppConfig):
    name = "ludamus.inits"
    label = "inits"

    @override
    def ready(self) -> None:
        # NOTE: imported here because the services and the sweeps import the
        # models, which Django only lets load once every app is registered.
        from ludamus.inits.dbos_scheduler import register_sweeps
        from ludamus.inits.services import Services
        from ludamus.inits.sweeps import SWEEPS
        from ludamus.links.db.django import admin

        # Fail on a mistyped SCHEDULER_MODE while the process starts, not on
        # the first request that schedules something.
        scheduler_mode()
        # Hands over the builder, not the rules: nothing walks the URLconf
        # until the first event needs redacting.
        redaction.register_builder(build_redaction_rules)
        register_sweeps(SWEEPS)
        wiring.register(make_services=Services, sweeps=SWEEPS)
        admin.register(make_services=Services)
