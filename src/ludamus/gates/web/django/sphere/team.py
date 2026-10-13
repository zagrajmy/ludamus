"""Sphere team page and the invitation links that add people to it."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
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
from ludamus.pacts.team import AcceptInvitationOutcome

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest

logger = logging.getLogger(__name__)


class TeamPageView(SphereAccessMixin, View):
    request: MultiverseRequest

    def get(self, _request: MultiverseRequest) -> HttpResponse:
        sphere_id = self.request.context.current_sphere_id
        # Comms people read the team too; only managers may grow it.
        can_invite = panel_access(self.request).allows(Capability.PANEL_WRITE)
        return TemplateResponse(
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
            },
        )


class TeamInviteActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(self, _request: MultiverseRequest) -> HttpResponse:
        form = SphereInvitationForm(self.request.POST)
        if not form.is_valid():
            messages.error(self.request, _("Pick a role for the invitation."))
            return redirect("multiverse:panel:team")
        invitation = self.request.services.sphere_team.invite(
            sphere_id=self.request.context.current_sphere_id,
            role=SphereRole(form.cleaned_data["role"]),
            invited_by_id=self.request.context.current_user_id,
        )
        logger.info(
            "Sphere invitation created: sphere=%s invitation=%s role=%s by=%s",
            self.request.context.current_sphere_id,
            invitation.pk,
            invitation.role,
            self.request.context.current_user_id,
        )
        messages.success(
            self.request,
            _("Invitation link created. Copy it and send it to the person."),
        )
        return redirect("multiverse:panel:team")


class TeamInviteRevokeActionView(SphereAccessMixin, View):
    request: MultiverseRequest

    def post(self, _request: MultiverseRequest, pk: int) -> HttpResponse:
        revoked = self.request.services.sphere_team.revoke(
            sphere_id=self.request.context.current_sphere_id, pk=pk
        )
        logger.info(
            "Sphere invitation revoke: sphere=%s invitation=%s revoked=%s by=%s",
            self.request.context.current_sphere_id,
            pk,
            revoked,
            self.request.context.current_user_id,
        )
        if revoked:
            messages.success(self.request, _("Invitation revoked."))
        else:
            messages.error(
                self.request, _("That invitation was already used or has expired.")
            )
        return redirect("multiverse:panel:team")


def _invalid_link(request: AuthenticatedRootRequest) -> HttpResponse:
    messages.error(
        request,
        _(
            "This invitation link is no longer valid. Ask the person who sent "
            "it for a new one."
        ),
    )
    return redirect("web:index")


class JoinSpherePageView(LoginRequiredMixin, View):
    """Where an invitation link lands: say what it grants, then accept it.

    Accepting is a POST, never the GET: link previews in chat apps open the
    URL, and a GET that spent the link would hand the role to a bot.
    """

    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest, token: str) -> HttpResponse:
        preview = request.services.sphere_team.preview(
            sphere_id=request.context.current_sphere_id, token=token
        )
        if preview is None:
            return _invalid_link(request)
        return TemplateResponse(
            request, "multiverse/join.html", {"invitation": preview}
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest, token: str) -> HttpResponse:
        outcome = request.services.sphere_team.accept(
            sphere_id=request.context.current_sphere_id,
            token=token,
            user_id=request.context.current_user_id,
        )
        logger.info(
            "Sphere invitation accept: sphere=%s user=%s outcome=%s",
            request.context.current_sphere_id,
            request.context.current_user_id,
            outcome,
        )
        match outcome:
            case AcceptInvitationOutcome.JOINED:
                messages.success(request, _("You joined the sphere's team."))
            case AcceptInvitationOutcome.ALREADY_MEMBER:
                messages.info(
                    request,
                    _(
                        "You're already on this sphere's team, so the link is "
                        "still unused."
                    ),
                )
            case AcceptInvitationOutcome.INVALID:
                return _invalid_link(request)
        return redirect(reverse("multiverse:panel:team"))
