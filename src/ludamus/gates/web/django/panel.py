from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal, get_args

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from ludamus.pacts.submissions import RequirementSelectionDTO

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponseRedirect, QueryDict

# Every value `active_nav` can take — one per entry in the panel sidebar
# (`panel/base.html`). Both ends of the comparison are closed against it: views
# are typed, and `{% sidebar_link %}` checks its `key` at render time, since the
# call sites are template literals no type checker reads. A key that matches
# nothing highlights nothing, silently, which is the whole failure mode.
PanelNav = Literal[
    "index",
    "cfp",
    "proposals",
    "facilitators",
    "discounts",
    "import",
    "venues",
    "tracks",
    "timetable",
    "settings",
    "bans",
    "guilds",
    "sphere-settings",
]
PANEL_NAV_KEYS: Final = frozenset(get_args(PanelNav))


def parse_requirement_selection(
    post_data: QueryDict, *, prefix: str, order_key: str
) -> RequirementSelectionDTO:
    requirements: dict[int, bool] = {}
    for key, value in post_data.items():
        raw_pk = key.removeprefix(prefix) if key.startswith(prefix) else ""
        if raw_pk.isdigit() and value in {"required", "optional"}:
            requirements[int(raw_pk)] = value == "required"
    order = [
        int(raw_pk)
        for raw_pk in post_data.get(order_key, "").split(",")
        if raw_pk.isdigit()
    ]
    return RequirementSelectionDTO(requirements=requirements, order=order)


def settings_tab_urls(slug: str) -> dict[str, str]:
    return {
        "general": reverse("panel:event-settings", kwargs={"slug": slug}),
        "proposals": reverse("panel:event-proposal-settings", kwargs={"slug": slug}),
        "enrollment": reverse("panel:event-enrollment-settings", kwargs={"slug": slug}),
        "display": reverse("panel:event-display-settings", kwargs={"slug": slug}),
        "integrations": reverse(
            "panel:event-integration-settings", kwargs={"slug": slug}
        ),
    }


class PanelPermissionResponseMixin(LoginRequiredMixin):
    request: HttpRequest

    def handle_no_permission(self) -> HttpResponseRedirect:
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()

        messages.error(
            self.request, _("You don't have permission to access the backoffice panel.")
        )
        return redirect("web:index")
