from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.crowd.forms import PartyInviteForm, PartyNameForm
from ludamus.gates.web.django.crowd.helpers import build_parties_context
from ludamus.pacts.party import (
    DeletePartyOutcome,
    InviteOutcome,
    PartyConsentMode,
    PartyMembershipStatus,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest


class PartiesPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> HttpResponse:
        return TemplateResponse(
            request, "crowd/user/parties.html", build_parties_context(request)
        )


class PartyCreateActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        form = PartyNameForm(request.POST)
        if form.is_valid():
            request.services.parties.create(
                leader_pk=request.context.current_user_id,
                name=form.cleaned_data["name"],
            )
            messages.success(request, _("Party created."))
        else:
            messages.error(request, _("Give the party a name."))
        return redirect("web:crowd:profile-parties")


class PartyRenameActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        form = PartyNameForm(request.POST)
        if form.is_valid() and request.services.parties.rename(
            leader_pk=request.context.current_user_id,
            party_pk=pk,
            name=form.cleaned_data["name"],
        ):
            messages.success(request, _("Party renamed."))
        else:
            messages.error(request, _("Could not rename this party."))
        return redirect("web:crowd:profile-parties")


class PartyDeleteActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        outcome = request.services.parties.delete(
            leader_pk=request.context.current_user_id, party_pk=pk
        )
        if outcome == DeletePartyOutcome.DELETED:
            messages.success(request, _("Party deleted."))
        elif outcome == DeletePartyOutcome.HAS_COMPANIONS:
            messages.error(
                request,
                _(
                    "This party still has companions. Remove them first — "
                    "their profiles would be left without a caretaker."
                ),
            )
        else:
            messages.error(request, _("Could not delete this party."))
        return redirect("web:crowd:profile-parties")


class PartyInviteActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        form = PartyInviteForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Enter a valid email address."))
            return redirect("web:crowd:profile-parties")
        outcome = request.services.parties.invite(
            leader_pk=request.context.current_user_id,
            party_pk=pk,
            email=form.cleaned_data["email"],
        )
        if outcome == InviteOutcome.INVITED:
            messages.success(request, _("Invitation sent."))
        elif outcome == InviteOutcome.ALREADY_MEMBER:
            messages.info(request, _("This person is already in the party."))
        else:
            messages.error(
                request,
                _(
                    "No account uses this email. Ask them to sign up first, "
                    "or add them as a companion you enroll yourself."
                ),
            )
        return redirect("web:crowd:profile-parties")


class PartyInviteAcceptActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        if request.services.parties.accept_invite(
            user_pk=request.context.current_user_id, membership_pk=pk
        ):
            messages.success(request, _("You joined the party."))
        else:
            messages.error(request, _("This invitation is no longer valid."))
        return redirect("web:crowd:profile-parties")


class PartyInviteDeclineActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        if request.services.parties.decline_invite(
            user_pk=request.context.current_user_id, membership_pk=pk
        ):
            messages.success(request, _("Invitation declined."))
        else:
            messages.error(request, _("This invitation is no longer valid."))
        return redirect("web:crowd:profile-parties")


class PartyMemberRemoveActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(
        request: AuthenticatedRootRequest, pk: int, membership_pk: int
    ) -> HttpResponse:
        removed_status = request.services.parties.remove_member(
            leader_pk=request.context.current_user_id,
            party_pk=pk,
            membership_pk=membership_pk,
        )
        if removed_status == PartyMembershipStatus.INVITED:
            messages.success(request, _("Invitation withdrawn."))
        elif removed_status is not None:
            messages.success(request, _("Member removed."))
        else:
            messages.error(request, _("Could not remove this member."))
        return redirect("web:crowd:profile-parties")


class PartyConsentActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        # Power of attorney (O-9): a member grants or revokes the leader's
        # right to seat them without asking.
        try:
            mode = PartyConsentMode(request.POST.get("mode", ""))
        except ValueError:
            messages.error(request, _("Could not change this setting."))
            return redirect("web:crowd:profile-parties")
        if request.services.parties.set_my_consent(
            user_pk=request.context.current_user_id, party_pk=pk, mode=mode
        ):
            if mode == PartyConsentMode.ACCEPT_BY_DEFAULT:
                messages.success(request, _("The leader can now enroll you directly."))
            else:
                messages.success(request, _("Enrollments now wait for your accept."))
        else:
            messages.error(request, _("Could not change this setting."))
        return redirect("web:crowd:profile-parties")


class PartyLeaveActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        if request.services.parties.leave(
            user_pk=request.context.current_user_id, party_pk=pk
        ):
            messages.success(request, _("You left the party."))
        else:
            messages.error(request, _("Could not leave this party."))
        return redirect("web:crowd:profile-parties")
