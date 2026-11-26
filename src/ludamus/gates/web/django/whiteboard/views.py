"""The board: a whiteboard with dice, its pass, and the list of one's boards."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import formats
from django.utils.cache import patch_vary_headers
from django.utils.decorators import method_decorator
from django.utils.timezone import localdate
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csp import csp_override
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import View
from pydantic import BaseModel, ConfigDict, ValidationError

from ludamus.gates.web.django.helpers import get_client_ip
from ludamus.gates.web.django.whiteboard.forms import BoardRenameForm
from ludamus.pacts.board import (
    BoardGuestDTO,
    BoardNameInvalidError,
    BoardNameRequiredError,
    BoardThrottledError,
)
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.board import BoardDTO

logger = logging.getLogger(__name__)

# NOTE: the guest's id and name live in the Django session, so a reload or a
# second tab joins as the same person.
_GUEST_ID = "board_guest_id"
_GUEST_NAME = "board_guest_name"


def _now() -> datetime:
    return datetime.now(UTC)


class _BoardGate(View):
    """404 every board route where no board could connect.

    Leftmost in the MRO, so the 404 wins over a login redirect that would
    leak the route.
    """

    request: RootRequest

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        if not self.request.services.boards.available():
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _board_url(request: RootRequest, share_code: str) -> str:
    """Where the board app opens a board, in the language of this request."""
    origin = request.services.boards.origin()
    query = urlencode({"lang": get_language()})
    return f"{origin}/b/{share_code}?{query}"


def _allow_form_redirect(
    request: RootRequest, response: HttpResponse, *, origin: str
) -> HttpResponse:
    """Let the page's "New board" form end in a redirect to the board app.

    Browsers check form-action against every redirect a form submission
    follows, so under 'self' alone the new board would never open.

    Returns:
        The response, carrying the site policy with the board app's origin
        added to form-action; untouched when the policy sets no form-action.
    """
    policy: dict[str, list[str]] = settings.SECURE_CSP
    if not (sources := policy.get("form-action")):
        return response
    config = {**policy, "form-action": [*sources, origin]}
    overridden: HttpResponse = csp_override(config)(lambda _request: response)(request)
    return overridden


class BoardsPageView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        origin = request.services.boards.origin()
        response = TemplateResponse(
            request,
            "whiteboard/index.html",
            {
                "board_origin": origin,
                "boards": request.services.boards.list_mine(
                    sphere_id=request.context.current_sphere_id,
                    user_id=request.context.current_user_id,
                ),
            },
        )
        return _allow_form_redirect(request, response, origin=origin)


class BoardCreateActionView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        board = request.services.boards.create(
            sphere_id=request.context.current_sphere_id,
            user_id=request.context.current_user_id,
            title=_("Board %(date)s") % {
                "date": formats.date_format(localdate(), "MONTH_DAY_FORMAT")
            },
        )
        return HttpResponseRedirect(_board_url(request, board.share_code))


class BoardPageView(_BoardGate):
    """The board's old address on the sphere, which the board app took over."""

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, share_code: str) -> HttpResponse:
        try:
            board = request.services.boards.open(
                share_code=share_code, sphere_id=request.context.current_sphere_id
            )
        except NotFoundError as exception:
            raise Http404 from exception
        return HttpResponseRedirect(_board_url(request, board.share_code))


class _BootstrapBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    name: str | None = None


def _requested_name(request: HttpRequest) -> str | None:
    """Read the name a guest typed, if the body carries one.

    Raises:
        ValidationError: the body is not JSON shaped like {"name": "<text>"}.

    Returns:
        The name as typed, or None when the body names nobody.
    """
    if not request.body:
        return None
    return _BootstrapBody.model_validate_json(request.body).name


def _answer_board_app(response: HttpResponseBase, origin: str) -> HttpResponseBase:
    response["Access-Control-Allow-Origin"] = origin
    response["Access-Control-Allow-Credentials"] = "true"
    patch_vary_headers(response, ("Origin",))
    return response


# NOTE: the board app on its own host asks for passes with the session
# cookie, so Django's CSRF token (an HttpOnly cookie on this host) is out of
# its reach. The view stands in for the middleware: it answers only a request
# whose Origin is the board app's, and only with a JSON body, which no form
# on another site can send without a preflight that this view refuses.
@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class BoardBootstrapEndpointView(View):
    request: RootRequest
    http_method_names = ("post", "options")

    def dispatch(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        if not self.request.services.boards.available():
            raise Http404
        origin = self.request.services.boards.origin()
        if request.headers.get("Origin") != origin:
            logger.warning(
                "Board pass refused: the request came from another origin",
                extra={"method": request.method},
            )
            return JsonResponse({"error": "forbidden-origin"}, status=403)
        return _answer_board_app(super().dispatch(request, *args, **kwargs), origin)

    @staticmethod
    def options(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        del request, args, kwargs
        response = HttpResponse(status=204)
        response["Access-Control-Allow-Methods"] = "POST"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        response["Access-Control-Max-Age"] = "600"
        return response

    @staticmethod
    def post(request: RootRequest, share_code: str) -> HttpResponse:
        if request.content_type != "application/json":
            return JsonResponse({"error": "invalid-request"}, status=415)
        user_id = request.context.current_user_id
        try:
            requested_name = None if user_id is not None else _requested_name(request)
        except ValidationError:
            return JsonResponse({"error": "invalid-request"}, status=400)
        try:
            payload = request.services.boards.bootstrap(
                share_code=share_code,
                user_id=user_id,
                guest=BoardGuestDTO(
                    id=request.session.get(_GUEST_ID),
                    name=request.session.get(_GUEST_NAME),
                ),
                requested_name=requested_name,
                client_ip=get_client_ip(request),
                now=_now(),
            )
        except NotFoundError:
            return JsonResponse({"error": "not-found"}, status=404)
        except BoardThrottledError:
            return JsonResponse({"error": "too-many-requests"}, status=429)
        except BoardNameRequiredError:
            return JsonResponse({"error": "name-required"}, status=422)
        except BoardNameInvalidError:
            return JsonResponse({"error": "name-invalid"}, status=422)
        if user_id is None:
            request.session[_GUEST_ID] = payload.person.id
            request.session[_GUEST_NAME] = payload.person.name
        sphere = f"{request.scheme}://{payload.sphere_domain}"
        return JsonResponse(
            {
                "pass": payload.pass_token,
                "board": payload.board_id,
                "person": payload.person.model_dump(mode="json"),
                "title": payload.title,
                "sphere": {"name": payload.sphere_name, "url": f"{sphere}/"},
                # Where a member finds the board again; a guest has no list.
                "boardsUrl": (
                    None
                    if user_id is None
                    else f"{sphere}{reverse('web:boards:index')}"
                ),
            }
        )


def _read_owned(request: AuthenticatedRootRequest, pk: int) -> BoardDTO:
    try:
        return request.services.boards.read_owned(
            pk=pk,
            sphere_id=request.context.current_sphere_id,
            user_id=request.context.current_user_id,
        )
    except NotFoundError as exception:
        raise Http404 from exception


class BoardEditPageView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        board = _read_owned(request, pk)
        return TemplateResponse(
            request,
            "whiteboard/edit.html",
            {"board": board, "form": BoardRenameForm(initial={"title": board.title})},
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        board = _read_owned(request, pk)
        form = BoardRenameForm(request.POST)
        if not form.is_valid():
            return TemplateResponse(
                request, "whiteboard/edit.html", {"board": board, "form": form}
            )
        try:
            request.services.boards.rename(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                title=form.cleaned_data["title"],
            )
        except NotFoundError as exception:
            raise Http404 from exception
        messages.success(request, _("Board renamed."))
        return redirect("web:boards:index")


class BoardResetLinkActionView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        try:
            request.services.boards.reset_link(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
            )
        except NotFoundError as exception:
            raise Http404 from exception
        messages.success(
            request, _("The board has a new link. The old one no longer opens it.")
        )
        return redirect("web:boards:index")


class BoardDeleteActionView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        try:
            wiped = request.services.boards.delete(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                now=_now(),
            )
        except NotFoundError as exception:
            raise Http404 from exception
        if wiped:
            messages.success(request, _("Board deleted."))
        else:
            messages.warning(
                request,
                _(
                    "Board deleted. Anyone still on it can keep drawing "
                    "until they leave."
                ),
            )
        return redirect("web:boards:index")
