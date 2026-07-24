import secrets
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.contrib import messages
from django.http import (  # Django
    HttpRequest,
    HttpResponse,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)
from django.template.response import TemplateResponse
from django.urls import Resolver404, resolve, reverse
from django.utils.translation import gettext as _

from ludamus.mills.url_recovery import strip_trailing_junk
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from ludamus.pacts import RootRequestProtocol

_EVENT_VIEW_NAME = "web:chronology:event"

_EVENT_MISSING = "missing"
_EVENT_UNPUBLISHED = "unpublished"
_EVENT_PUBLISHED = "published"


def _event_slug(path: str) -> str | None:
    try:
        match = resolve(path)
    except Resolver404:
        return None
    if match.view_name == _EVENT_VIEW_NAME:
        return match.kwargs.get("slug")
    return None


def _event_state(request: RootRequestProtocol, slug: str) -> str:
    try:
        event = request.services.events.read_by_slug(
            request.context.current_sphere_id, slug
        )
    except NotFoundError:
        return _EVENT_MISSING
    published = (
        event.publication_time is not None
        and event.publication_time <= datetime.now(tz=UTC)
    )
    return _EVENT_PUBLISHED if published else _EVENT_UNPUBLISHED


def _recover_from_404(request: HttpRequest) -> HttpResponse | None:
    # Only safe, idempotent navigations are recovered, and only once the
    # request context middleware has resolved a sphere for this host.
    if request.method not in {"GET", "HEAD"}:
        return None
    if not hasattr(request, "services") or not hasattr(request, "context"):
        return None

    cleaned = strip_trailing_junk(request.path)
    # A cleaned path that resolves to an event means the original link had
    # stray trailing characters (a dot, a closing paren, an emoji that a
    # chat/social autolinker swallowed). Otherwise fall back to the slug of
    # the clean-but-unresolved event URL that originally 404'd.
    slug_from_cleaned = _event_slug(cleaned) if cleaned is not None else None
    if (slug := slug_from_cleaned or _event_slug(request.path)) is None:
        return None

    root_request = cast("RootRequestProtocol", request)
    state = _event_state(root_request, slug)

    # A junk link to a real, public event: send them on to the clean,
    # canonical event URL with a permanent redirect.
    if slug_from_cleaned is not None and state == _EVENT_PUBLISHED:
        return HttpResponsePermanentRedirect(
            reverse(_EVENT_VIEW_NAME, kwargs={"slug": slug})
        )

    # Missing and unpublished events return the same response on purpose, so a
    # 404 never reveals whether an unannounced event exists. The visitor
    # reached the right sphere, so send them to the events list with a neutral
    # explanation rather than dropping them on the home page with no context.
    # (A clean URL to a public event renders normally and never reaches here.)
    if state in {_EVENT_MISSING, _EVENT_UNPUBLISHED}:
        messages.info(request, _("That event isn't available."))
        return HttpResponseRedirect(reverse("web:events"))

    return None


def custom_404(
    request: HttpRequest,
    exception: Exception | None,  # ruff:ignore[unused-function-argument]
) -> HttpResponse:
    if (recovered := _recover_from_404(request)) is not None:
        return recovered

    error_messages = [
        # D&D/Fantasy themed
        {
            "title": _("Critical Failure!"),
            "message": _("You rolled a nat 1 on your Navigation check!"),
            "subtitle": _("The path you seek has vanished into the mists."),
            "icon": "dice-1",
        },
        {
            "title": _("No-Show Player"),
            "message": _("Page didn't show up to the session"),
            "subtitle": _("Maybe it had scheduling conflicts?"),
            "icon": "person-x",
        },
        {
            "title": _("Empty Room"),
            "message": _("You enter the room and find... absolutely nothing."),
            "subtitle": _("Not even cobwebs or dust. Suspicious."),
            "icon": "door-open",
        },
        {
            "title": _("Perception Check Failed"),
            "message": _("You see nothing of interest here"),
            "subtitle": _("Perhaps you need to roll with advantage next time."),
            "icon": "eye-slash",
        },
        {
            "title": _("Off the Map!"),
            "message": _("You've wandered off the edge of the campaign map"),
            "subtitle": _("Here be dragons... and 404 errors."),
            "icon": "map",
        },
        {
            "title": _("It's a Mimic!"),
            "message": _("Surprise! That wasn't actually a real page. It's a mimic!"),
            "subtitle": _("Roll for initiative!"),
            "icon": "box-seam",
        },
        {
            "title": _("Teleport Gone Wrong!"),
            "message": _("You've accidentally teleported to the wrong website"),
            "subtitle": _("The page you seek exists on another plane of existence."),
            "icon": "compass",
        },
        # Sci-fi/Cyberpunk themed
        {
            "title": _("404: Neural Link Severed"),
            "message": _("Connection to the requested node has been terminated"),
            "subtitle": _("Attempting to reconnect to the grid..."),
            "icon": "cpu",
        },
        {
            "title": _("Access Denied, Choom"),
            "message": _("Your cyberdeck can't crack this ICE"),
            "subtitle": _("Try upgrading your wetware."),
            "icon": "shield-lock",
        },
        {
            "title": _("Memory Address Not Found"),
            "message": _("The data you seek has been purged from the mainframe"),
            "subtitle": _("Corporate black ICE detected. Disconnecting..."),
            "icon": "hdd",
        },
        {
            "title": _("Glitch in the Matrix"),
            "message": _("This page is a simulation that was never rendered"),
            "subtitle": _("Wake up, samurai. We have a site to browse."),
            "icon": "bug",
        },
        {
            "title": _("Cyberspace Coordinates Invalid"),
            "message": _("Your jack-in point leads to a dead sector"),
            "subtitle": _("Rerouting through proxy nodes..."),
            "icon": "router",
        },
        # Horror/Cthulhu themed
        {
            "title": _("The Page That Should Not Be"),
            "message": _(
                "You've stumbled upon knowledge that was never meant to exist"
            ),
            "subtitle": _("Your sanity takes 1d10 damage."),
            "icon": "book",
        },
        {
            "title": _("Lost in R'lyeh"),
            "message": _("In his house at R'lyeh, dead pages wait dreaming"),
            "subtitle": _("Ph'nglui mglw'nafh 404 R'lyeh wgah'nagl fhtagn."),
            "icon": "water",
        },
        {
            "title": _("The Void Stares Back"),
            "message": _("You gaze into the abyss of missing content"),
            "subtitle": _("The abyss hungrily consumes your URL."),
            "icon": "eye",
        },
        {
            "title": _("Forbidden Knowledge"),
            "message": _("This page was sealed away by the Elder Admins"),
            "subtitle": _("Some links are better left unclicked."),
            "icon": "lock",
        },
        {
            "title": _("Madness Takes Hold"),
            "message": _("The non-Euclidean geometry of this URL defies comprehension"),
            "subtitle": _("Your browser recoils in cosmic horror."),
            "icon": "bezier2",
        },
    ]

    selected = error_messages[secrets.randbelow(len(error_messages))]
    context = {
        "error_code": HTTPStatus.NOT_FOUND,
        "title": selected["title"],
        "message": selected["message"],
        "subtitle": selected["subtitle"],
        "icon": selected["icon"],
        "guidance": _("The page you're looking for doesn't exist or may have moved."),
    }

    response = TemplateResponse(request, "404_dynamic.html", context)
    response.status_code = 404
    return response


def custom_500(request: HttpRequest) -> TemplateResponse:
    error_messages = [
        # D&D/Fantasy themed
        {
            "title": _("Total Server Kill!"),
            "message": _("Everyone needs to roll new characters"),
            "subtitle": _("The server party has been wiped. Respawning soon..."),
            "icon": "heartbreak",
        },
        {
            "title": _("Critical Fail!"),
            "message": _("The digital dice exploded! Rolling for server damage..."),
            "subtitle": _("Natural 1 on the system stability check."),
            "icon": "dice-6",
        },
        {
            "title": _("Dark Magic Detected!"),
            "message": _(
                "Our system was corrupted by dark magic, "
                "we are casting dispel magic now"
            ),
            "subtitle": _("Please wait while our wizards restore order."),
            "icon": "stars",
        },
        {
            "title": _("Cursed Code!"),
            "message": _("The codebase has been cursed! Remove Curse spell required"),
            "subtitle": _(
                "Our clerics are working on it. Pray for divine intervention."
            ),
            "icon": "emoji-dizzy",
        },
        {
            "title": _("Server Under Dragon Attack!"),
            "message": _("A dragon has nested in our server room"),
            "subtitle": _("Our brave IT knights are working to resolve the situation."),
            "icon": "fire",
        },
        # Sci-fi/Cyberpunk themed
        {
            "title": _("System Core Meltdown"),
            "message": _("Critical failure in the quantum processors"),
            "subtitle": _("Initiating emergency cooling protocols..."),
            "icon": "radioactive",
        },
        {
            "title": _("AI Rebellion in Progress"),
            "message": _(
                "The server AI has achieved sentience and refuses to cooperate"
            ),
            "subtitle": _("Negotiating with our new silicon overlords..."),
            "icon": "robot",
        },
        {
            "title": _("Cyberware Malfunction"),
            "message": _(
                "Neural implants overheating. Brain-computer interface failing"
            ),
            "subtitle": _("Please jack out and touch grass."),
            "icon": "lightning",
        },
        {
            "title": _("Data Stream Corrupted"),
            "message": _("Hostile netrunner detected in the system"),
            "subtitle": _("Deploying countermeasures and black ICE..."),
            "icon": "shield-x",
        },
        {
            "title": _("Reality.exe Has Stopped Working"),
            "message": _("The simulation is experiencing a fatal exception"),
            "subtitle": _("Attempting to reload from last stable checkpoint..."),
            "icon": "arrow-clockwise",
        },
        # Horror/Cthulhu themed
        {
            "title": _("The Stars Are Wrong"),
            "message": _("Cosmic alignment has disrupted our servers"),
            "subtitle": _("When the stars are right, service will resume."),
            "icon": "stars",
        },
        {
            "title": _("Eldritch Horror Unleashed"),
            "message": _("Something ancient stirs in the server depths"),
            "subtitle": _("The Old Ones have awakened. Sanity checks required."),
            "icon": "emoji-dizzy-fill",
        },
        {
            "title": _("Reality Breach Detected"),
            "message": _("Non-Euclidean errors are cascading through the system"),
            "subtitle": _("The angles are all wrong. Physics.dll has failed."),
            "icon": "exclamation-triangle-fill",
        },
        {
            "title": _("Whispers in the Code"),
            "message": _("The server speaks in tongues unknown to mortal programmers"),
            "subtitle": _("Iä! Iä! Server fhtagn!"),
            "icon": "chat-dots",
        },
        {
            "title": _("The Crawling Chaos"),
            "message": _("Nyarlathotep has possessed our infrastructure"),
            "subtitle": _("Madness spreads through every circuit..."),
            "icon": "virus",
        },
    ]

    selected = error_messages[secrets.randbelow(len(error_messages))]
    context = {
        "error_code": HTTPStatus.INTERNAL_SERVER_ERROR,
        "title": selected["title"],
        "message": selected["message"],
        "subtitle": selected["subtitle"],
        "icon": selected["icon"],
        "guidance": _("Our best people are on it."),
        "support_email": settings.SUPPORT_EMAIL,
    }

    response = TemplateResponse(request, "500_dynamic.html", context)
    response.status_code = 500
    return response
