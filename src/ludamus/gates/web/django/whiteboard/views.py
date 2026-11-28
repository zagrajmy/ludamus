"""Boards: Little Table rooms in a frame, the chat beside them, and one's list."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.helpers import respond_with_policy
from ludamus.gates.web.django.whiteboard.forms import BoardForm
from ludamus.pacts.board import BoardRoomLinkInvalidError, BoardTitleInvalidError
from ludamus.pacts.errors import NotFoundError

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest
    from ludamus.pacts.board import BoardDTO


class _BoardGate(View):
    """404 every board route while no Little Table is configured.

    Leftmost in the MRO, so the 404 wins over a login redirect that would
    leak the route.
    """

    request: RootRequest

    def dispatch(
        self, request: HttpRequest, *args: str, **kwargs: str | int
    ) -> HttpResponseBase:
        if not self.request.services.boards.available():
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _form_page(
    request: AuthenticatedRootRequest, *, form: BoardForm, board: BoardDTO | None
) -> HttpResponse:
    little_table_url: str = settings.LITTLE_TABLE_URL
    return TemplateResponse(
        request,
        "whiteboard/form.html",
        {"form": form, "board": board, "little_table_url": little_table_url},
    )


def _refuse(form: BoardForm, error: Exception) -> None:
    if isinstance(error, BoardRoomLinkInvalidError):
        form.add_error(
            "room_link",
            _("Paste a Little Table board link, like %(example)s.") % {
                "example": f"{settings.LITTLE_TABLE_URL}/b/…"
            },
        )
    else:
        form.add_error("title", _("Give the board a name."))


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


class BoardCreatePageView(_BoardGate, LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        return _form_page(request, form=BoardForm(), board=None)

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        form = BoardForm(request.POST)
        if not form.is_valid():
            return _form_page(request, form=form, board=None)
        try:
            board = request.services.boards.create(
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                title=form.cleaned_data["title"],
                room_link=form.cleaned_data["room_link"],
            )
        except (BoardRoomLinkInvalidError, BoardTitleInvalidError) as error:
            _refuse(form, error)
            return _form_page(request, form=form, board=None)
        return redirect("web:boards:board", share_code=board.share_code)


class BoardPageView(_BoardGate):
    """The Little Table room in a frame, with the board's chat for the signed in."""

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, share_code: str) -> HttpResponse:
        try:
            board = request.services.boards.open(
                share_code=share_code,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                now=datetime.now(UTC),
            )
        except NotFoundError as exception:
            raise Http404 from exception
        response = TemplateResponse(request, "whiteboard/board.html", {"board": board})
        # Absent or disabled, the policy restricts no frame: leave it that way.
        if not (policy := settings.SECURE_CSP):
            return response
        return respond_with_policy(
            request, response, {**policy, "frame-src": [board.room_origin]}
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
        form = BoardForm(
            initial={
                "title": board.title,
                "room_link": request.services.boards.room_url(board.room_code),
            }
        )
        return _form_page(request, form=form, board=board)

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        board = _read_owned(request, pk)
        form = BoardForm(request.POST)
        if not form.is_valid():
            return _form_page(request, form=form, board=board)
        try:
            request.services.boards.update(
                pk=pk,
                sphere_id=request.context.current_sphere_id,
                user_id=request.context.current_user_id,
                title=form.cleaned_data["title"],
                room_link=form.cleaned_data["room_link"],
            )
        except NotFoundError as exception:
            raise Http404 from exception
        except (BoardRoomLinkInvalidError, BoardTitleInvalidError) as error:
            _refuse(form, error)
            return _form_page(request, form=form, board=board)
        messages.success(request, _("Board saved."))
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
