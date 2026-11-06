from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, Literal, TypedDict, get_args

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from ludamus.gates.web.django.access import has_panel_access, passes_panel_access
from ludamus.gates.web.django.redirects import safe_url
from ludamus.gates.web.django.request_ids import parse_id, parse_ids
from ludamus.pacts.multiverse import Capability
from ludamus.pacts.submissions import RequirementSelectionDTO

if TYPE_CHECKING:
    from django.http import HttpResponseRedirect, QueryDict
    from django.utils.functional import _StrPromise

    from ludamus.pacts.legacy import AuthenticatedRequestContext
    from ludamus.pacts.services import ServicesProtocol

# Every value `active_nav` can take — one per `{% sidebar_link %}` in the panel
# sidebar (`panel/base.html`), list row or header button. A value outside this
# set highlights nothing, silently.
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
    "konwencik-export",
    "errata",
    "settings",
    "bans",
    "guilds",
    "team",
    "sphere-settings",
    "event-create",
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
        if not key.startswith(prefix) or value not in {"required", "optional"}:
            continue
        if (pk := parse_id(key.removeprefix(prefix))) is not None:
            requirements[pk] = value == "required"
    order = parse_ids(post_data.get(order_key, "").split(","))
    return RequirementSelectionDTO(requirements=requirements, order=order)


class PanelRequest(HttpRequest):
    context: AuthenticatedRequestContext
    services: ServicesProtocol


class PanelAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Any panel page: a sphere role reads it, the page's capability writes it."""

    request: PanelRequest

    # What this page's buttons stand for. A view whose writes a narrower role
    # may perform names that capability instead; it never names the role.
    write_capability: ClassVar[Capability] = Capability.PANEL_WRITE
    no_permission_message: ClassVar[_StrPromise] = gettext_lazy(
        "You don't have permission to access the backoffice panel."
    )

    def test_func(self) -> bool:
        return passes_panel_access(self.request, write_capability=self.write_capability)

    def handle_no_permission(self) -> HttpResponseRedirect:
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return refuse_panel_access(
            request=self.request,
            reads_panel=has_panel_access(self.request),
            message=str(self.no_permission_message),
        )


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


def cfp_tab_urls(slug: str) -> dict[str, str]:
    return {
        "types": reverse("panel:cfp", kwargs={"slug": slug}),
        "host": reverse("panel:personal-data-fields", kwargs={"slug": slug}),
        "session": reverse("panel:session-fields", kwargs={"slug": slug}),
        "time_slots": reverse("panel:time-slots", kwargs={"slug": slug}),
    }


def facilitator_tab_urls(slug: str) -> dict[str, str]:
    return {
        "list": reverse("panel:facilitators", kwargs={"slug": slug}),
        "merge": reverse("panel:facilitator-merge", kwargs={"slug": slug}),
        "columns": reverse("panel:facilitator-columns", kwargs={"slug": slug}),
        "export": reverse("panel:facilitator-export", kwargs={"slug": slug}),
        "bin": reverse("panel:facilitator-bin", kwargs={"slug": slug}),
    }


def proposal_tab_urls(slug: str) -> dict[str, str]:
    return {
        "list": reverse("panel:proposals", kwargs={"slug": slug}),
        "columns": reverse("panel:proposal-columns", kwargs={"slug": slug}),
        "export": reverse("panel:proposal-export", kwargs={"slug": slug}),
    }


def proposal_detail_tab_urls(slug: str, proposal_id: int) -> dict[str, str]:
    kwargs = {"slug": slug, "proposal_id": proposal_id}
    return {
        "details": reverse("panel:proposal-detail", kwargs=kwargs),
        "history": reverse("panel:proposal-history", kwargs=kwargs),
    }


def facilitator_detail_tab_urls(slug: str, facilitator_slug: str) -> dict[str, str]:
    kwargs = {"slug": slug, "facilitator_slug": facilitator_slug}
    return {
        "details": reverse("panel:facilitator-detail", kwargs=kwargs),
        "history": reverse("panel:facilitator-history", kwargs=kwargs),
    }


def import_tab_urls(slug: str, pk: int) -> dict[str, str]:
    kwargs = {"slug": slug, "pk": pk}
    return {
        "proposal": reverse("panel:import-integration", kwargs=kwargs),
        "review": reverse("panel:import-review", kwargs=kwargs),
        "json": reverse("panel:import-json", kwargs=kwargs),
        "run": reverse("panel:import-run", kwargs=kwargs),
        "log": reverse("panel:import-log", kwargs=kwargs),
    }


def timetable_tab_urls(slug: str) -> dict[str, str]:
    return {
        "timetable": reverse("panel:timetable", kwargs={"slug": slug}),
        "log": reverse("panel:timetable-log", kwargs={"slug": slug}),
        "overview": reverse("panel:timetable-overview", kwargs={"slug": slug}),
        "problems": reverse("panel:timetable-problems", kwargs={"slug": slug}),
        "confirmations": reverse(
            "panel:timetable-confirmations", kwargs={"slug": slug}
        ),
    }


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
