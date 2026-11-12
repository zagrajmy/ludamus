"""The board: a whiteboard with dice, its pass, and the list of one's boards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import formats
from django.utils.decorators import method_decorator
from django.utils.timezone import localdate
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.generic.base import View
from pydantic import BaseModel, ConfigDict, ValidationError

from ludamus.gates.web.django.helpers import get_client_ip
from ludamus.gates.web.django.whiteboard.copy import board_copy
from ludamus.gates.web.django.whiteboard.forms import BoardRenameForm
from ludamus.pacts.board import (
    BoardGuestDTO,
    BoardNameInvalidError,
    BoardNameRequiredError,
    BoardThrottledError,
)
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.board import BoardDTO

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


class BoardsPageView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        return TemplateResponse(
            request,
            "whiteboard/index.html",
            {
                "boards": request.services.boards.list_mine(
                    sphere_id=request.context.current_sphere_id,
                    user_id=request.context.current_user_id,
                )
            },
        )


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
        return redirect("web:boards:board", share_code=board.share_code)


class BoardPageView(_BoardGate):
    request: RootRequest

    @staticmethod
    def get(request: RootRequest, share_code: str) -> HttpResponse:
        try:
            board = request.services.boards.open(
                share_code=share_code,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                now=_now(),
            )
        except NotFoundError as exception:
            raise Http404 from exception
        license_key: str = settings.TLDRAW_LICENSE_KEY
        return TemplateResponse(
            request,
            "whiteboard/board.html",
            {
                "board": board,
                "is_owner": board.creator_id == request.context.current_user_id,
                "license_key": license_key,
            },
        )


class _BootstrapBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    name: str | None = None


def _requested_name(request: HttpRequest) -> str | None:
    """Read the name a guest typed, if the body carries one.

    Raises:
        ValidationError: the body is not a JSON object with a string name.

    Returns:
        The name as typed, or None when the body names nobody.
    """
    if not request.body:
        return None
    return _BootstrapBody.model_validate_json(request.body).name


@method_decorator(never_cache, name="dispatch")
class BoardBootstrapEndpointView(_BoardGate):
    request: RootRequest

    @staticmethod
    def post(request: RootRequest, share_code: str) -> HttpResponse:
        user_id = request.context.current_user_id
        try:
            requested_name = None if user_id is not None else _requested_name(request)
        except ValidationError:
            return JsonResponse({"error": "invalid-request"}, status=400)
        try:
            payload = request.services.boards.bootstrap(
                share_code=share_code,
                sphere_id=request.context.current_sphere_id,
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
        return JsonResponse(
            payload.model_dump(mode="json", by_alias=True) | {"copy": board_copy()}
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
            request.services.boards.delete(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
            )
        except NotFoundError as exception:
            raise Http404 from exception
        messages.success(request, _("Board deleted."))
        return redirect("web:boards:index")
