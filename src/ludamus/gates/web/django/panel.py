from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal, TypedDict, get_args

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from ludamus.pacts.submissions import RequirementSelectionDTO

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponseRedirect, QueryDict

# Every value `active_nav` can take — one per entry in the panel sidebar
# (`panel/base.html`). A value outside this set highlights nothing, silently.
# Most producers assign into loosely typed context mappings no type checker
# sees, so `{% sidebar_link %}` checks both ends at render time.
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
    "errata",
    "settings",
    "bans",
    "guilds",
    "sphere-settings",
]
PANEL_NAV_KEYS: Final = frozenset(get_args(PanelNav))


# Every panel context carries one, so the name is declared once here rather than
# repeated as a bare `str` in each view module's TypedDict.
class PanelNavContext(TypedDict):
    active_nav: PanelNav


# Every sidebar category. A category with no collapse rules in `panel/base.html`
# renders a fully wired toggle that visibly does nothing, so `TestSidebarCoverage`
# checks this set against the rules there.
PanelCat = Literal["program", "schedule", "live", "settings", "sphere"]
PANEL_CAT_KEYS: Final = frozenset(get_args(PanelCat))


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
        "discounts": reverse("panel:event-discount-settings", kwargs={"slug": slug}),
        "display": reverse("panel:event-display-settings", kwargs={"slug": slug}),
        "integrations": reverse(
            "panel:event-integration-settings", kwargs={"slug": slug}
        ),
        "mcp": reverse("panel:event-mcp-token", kwargs={"slug": slug}),
    }


def safe_url(request: HttpRequest, url: str | None) -> str:
    # The one host check behind every "back where you came from" redirect,
    # whether the URL arrived as a `next` param or as the referer.
    return (
        url
        if url
        and url_has_allowed_host_and_scheme(
            url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        else ""
    )


def safe_next_url(request: HttpRequest, fallback: str) -> str:
    # Actions post it, links carry it in the query — both spellings mean "the
    # list the organizer came from", filters and all.
    return (
        safe_url(request, request.POST.get("next") or request.GET.get("next"))
        or fallback
    )


# The whole refusal policy for panel views, in one place. A role that reads the
# panel but may not change it was denied the write, not the panel: saying
# otherwise is untrue, and dropping the user on the site index loses the page
# they were reading. Callers pass the access answer they already resolved and
# the wording for the panel they guard.
def refuse_panel_access(
    *, request: HttpRequest, reads_panel: bool, message: str
) -> HttpResponseRedirect:
    if not reads_panel:
        messages.error(request, message)
        return redirect("web:index")
    messages.error(
        request, _("Your role can read the panel, but not make changes here.")
    )
    back = safe_url(request, request.META.get("HTTP_REFERER"))
    return redirect(back) if back else redirect("web:index")
