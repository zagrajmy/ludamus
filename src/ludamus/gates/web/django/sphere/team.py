"""Sphere team page and the invitation links that add people to it."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, NamedTuple

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.access import panel_access
from ludamus.gates.web.django.multiverse.access import (
    MultiverseRequest,
    SphereAccessMixin,
)
from ludamus.gates.web.django.sphere.forms import SphereInvitationForm
from ludamus.gates.web.django.sphere.panel_context import sphere_sidebar_context
from ludamus.pacts.multiverse import Capability, SphereRole
from ludamus.pacts.team import (
    INVITATION_NOTE_MAX_LENGTH,
    AcceptInvitationOutcome,
    JoinPageDTO,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.team import IssuedInvitationDTO

logger = logging.getLogger(__name__)


# The one moment a link exists in full: the invite action hands it to the next
# Team page render in a short-lived signed cookie, never the session table, so
# a redirect that is never followed leaves no usable link at rest.
_ISSUED_LINK_COOKIE = "sphere_invitation_issued"
_ISSUED_LINK_SALT = "ludamus.sphere.team.issued-link"
_ISSUED_LINK_MAX_AGE = 300


class IssuedLink(NamedTuple):
    pk: int
    path: str


def _read_issued_link(request: MultiverseRequest) -> IssuedLink | None:
    signed = request.get_signed_cookie(
        _ISSUED_LINK_COOKIE,
        default=None,
        salt=_ISSUED_LINK_SALT,
        max_age=_ISSUED_LINK_MAX_AGE,
    )
    if signed is None:
        return None
    pk, _sep, token = signed.partition(":")
    if not pk.isdigit() or not token:
        logger.warning("Sphere invitation: malformed issued-link cookie ignored")
        return None
    return IssuedLink(
        pk=int(pk), path=reverse("multiverse:join", kwargs={"token": token})
    )


def _hand_over(request: MultiverseRequest, issued: IssuedInvitationDTO) -> HttpResponse:
    response = redirect("multiverse:panel:team")
    response.set_signed_cookie(
        _ISSUED_LINK_COOKIE,
        f"{issued.invitation.pk}:{issued.token}",
        salt=_ISSUED_LINK_SALT,
        max_age=_ISSUED_LINK_MAX_AGE,
        path=reverse("multiverse:panel:team"),
        secure=request.is_secure(),
        httponly=True,
        samesite="Lax",
    )
    return response


class TeamPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        # Comms people read the team too; only managers may grow it.
        can_invite = panel_access(self.request).allows(Capability.PANEL_WRITE)
        response = TemplateResponse(
            self.request,
            "multiverse/panel/team.html",
            {
                **sphere_sidebar_context(self.request, active_nav="team"),
                "members": self.request.services.sphere_team.list_members(
                    sphere_id=sphere_id
                ),
                "invitations": (
                    self.request.services.sphere_team.list_open_invitations(
                        sphere_id=sphere_id
                    )
                    if can_invite
                    else []
                ),
                "invitation_form": SphereInvitationForm() if can_invite else None,
                "issued_link": _read_issued_link(self.request) if can_invite else None,
            },
        )
        if _ISSUED_LINK_COOKIE in self.request.COOKIES:
            response.delete_cookie(
                _ISSUED_LINK_COOKIE, path=reverse("multiverse:panel:team")
            )
        return response


class TeamInviteActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = SphereInvitationForm(self.request.POST)
        if not form.is_valid():
            messages.error(
                self.request,
                (
                    _("Keep the note to %(limit)d characters.") % {
                        "limit": INVITATION_NOTE_MAX_LENGTH
                    }
                    if "note" in form.errors
                    else _("Pick a role for the invitation.")
                ),
            )
            return redirect("multiverse:panel:team")
        issued = self.request.services.sphere_team.invite(
            sphere_id=self.request.context.current_sphere_id,
            role=SphereRole(form.cleaned_data["role"]),
            note=form.cleaned_data["note"],
            invited_by_id=self.request.context.current_user_id,
        )
        invitation = issued.invitation
        logger.info(
            "Sphere invitation created: sphere=%s invitation=%s role=%s by=%s",
            self.request.context.current_sphere_id,
            invitation.pk,
            invitation.role,
            self.request.context.current_user_id,
        )
        messages.success(
            self.request,
            (
                _("Invitation link ready. Copy it below and send it to %(name)s.") % {
                    "name": invitation.note
                }
                if invitation.note
                else _(
                    "Invitation link ready. Copy it below and send it to the "
                    "person you're inviting."
                )
            ),
        )
        return _hand_over(self.request, issued)


class TeamInviteReissueActionView(SphereAccessMixin, View):
    """Swap a lost link for a new one: same role and note, the old one dies."""

    request: MultiverseRequest

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        issued = self.request.services.sphere_team.reissue(
            sphere_id=self.request.context.current_sphere_id,
            pk=pk,
            reissued_by_id=self.request.context.current_user_id,
        )
        logger.info(
            "Sphere invitation reissue: sphere=%s invitation=%s reissued=%s by=%s",
            self.request.context.current_sphere_id,
            pk,
            issued is not None,
            self.request.context.current_user_id,
        )
        if issued is None:
            messages.error(
                self.request, _("That invitation was already used or has expired.")
            )
            return redirect("multiverse:panel:team")
        messages.success(
            self.request,
            _("New link ready. Copy it below: the old one no longer works."),
        )
        return _hand_over(self.request, issued)


class TeamInviteRevokeActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        revoked = self.request.services.sphere_team.revoke(
            sphere_id=self.request.context.current_sphere_id, pk=pk
        )
        logger.info(
            "Sphere invitation withdraw: sphere=%s invitation=%s withdrawn=%s by=%s",
            self.request.context.current_sphere_id,
            pk,
            revoked,
            self.request.context.current_user_id,
        )
        if revoked:
            messages.success(self.request, _("Invitation withdrawn."))
        else:
            messages.error(
                self.request, _("That invitation was already used or has expired.")
            )
        return redirect("multiverse:panel:team")


def _render_join(request: RootRequest, page: JoinPageDTO) -> HttpResponse:
    # Rendered in place, never redirected: in a private sphere every other
    # page is a 404 to someone who is not on the team yet.
    gone = page.invitation is None and page.member_role is None
    return TemplateResponse(
        request,
        "multiverse/join.html",
        {"page": page},
        status=HTTPStatus.GONE if gone else HTTPStatus.OK,
    )


class JoinSpherePageView(View):
    """Where an invitation link lands: say what it grants, then accept it.

    Anyone holding the link may read it, signed in or not: it names only the
    sphere, the role and who sent it. Accepting is a POST, never the GET:
    link previews in chat apps open the URL, and a GET that spent the link
    would hand the role to a bot.
    """

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, token: str) -> HttpResponse:
        return _render_join(
            request,
            request.services.sphere_team.join_page(
                sphere_id=request.context.current_sphere_id,
                token=token,
                viewer_id=request.context.current_user_id,
            ),
        )

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        if (user_id := request.context.current_user_id) is None:
            return redirect_to_login(request.get_full_path())
        sphere_id = request.context.current_sphere_id
        outcome = request.services.sphere_team.accept(
            sphere_id=sphere_id, token=token, user_id=user_id
        )
        logger.info(
            "Sphere invitation accept: sphere=%s user=%s outcome=%s",
            sphere_id,
            user_id,
            outcome,
        )
        if outcome is AcceptInvitationOutcome.JOINED:
            messages.success(request, _("You joined the sphere's team."))
            return redirect("multiverse:panel:team")
        # Already on the team, or the link stopped working: the page itself
        # says which, the same way it does when the link is opened.
        return _render_join(
            request,
            request.services.sphere_team.join_page(
                sphere_id=sphere_id, token=token, viewer_id=user_id
            ),
        )
