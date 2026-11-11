"""Access for the sphere-scoped panel: the panel's own check, no event."""

from __future__ import annotations

from django.utils.translation import gettext_lazy

from ludamus.gates.web.django.panel import PanelAccessMixin


class SphereAccessMixin(PanelAccessMixin):
    no_permission_message = gettext_lazy(
        "You don't have permission to access the sphere panel."
    )
