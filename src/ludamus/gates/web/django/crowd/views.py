from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.views.generic.base import View

from ludamus.gates.web.django.crowd.forms import (
    PartyCompanionForm,
    PartyInviteForm,
    PartyNameForm,
)
from ludamus.gates.web.django.crowd.helpers import (
    build_parties_context,
    build_party_detail_context,
)
from ludamus.pacts.party import (
    CompanionAddOutcome,
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


class PartyDetailPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        if (context := build_party_detail_context(request, pk=pk)) is None:
            raise Http404
        return TemplateResponse(request, "crowd/user/party_detail.html", context)


class PartyCreateActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        form = PartyNameForm(request.POST)
        if form.is_valid():
            party_pk = request.services.parties.create(
                leader_pk=request.context.current_user_id,
                name=form.cleaned_data["name"],
            )
            messages.success(request, _("Party created."))
            return redirect("web:crowd:party-detail", pk=party_pk)
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
        return redirect("web:crowd:party-detail", pk=pk)


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
            messages.error(request, _("Enter an email or Discord username."))
            return redirect("web:crowd:party-detail", pk=pk)
        outcome = request.services.parties.invite(
            member_pk=request.context.current_user_id,
            party_pk=pk,
            identifier=form.cleaned_data["identifier"],
        )
        if outcome == InviteOutcome.INVITED:
            messages.success(request, _("Invitation sent."))
        elif outcome == InviteOutcome.ALREADY_MEMBER:
            messages.info(request, _("This person is already in the party."))
        elif outcome == InviteOutcome.AMBIGUOUS_HANDLE:
            messages.error(
                request,
                _(
                    "More than one account uses that Discord username. "
                    "Invite them by email instead."
                ),
            )
        else:
            messages.error(
                request,
                _(
                    "No account matches that email or Discord username. Ask them "
                    "to sign up first, share your invite link, or add them as a "
                    "companion you enroll yourself."
                ),
            )
        return redirect("web:crowd:party-detail", pk=pk)


class PartyInviteLinkActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        token = request.services.parties.reset_invite_link(
            leader_pk=request.context.current_user_id, party_pk=pk
        )
        if token is None:
            messages.error(request, _("Could not regenerate the invite link."))
        else:
            messages.success(request, _("Invite link regenerated."))
        return redirect("web:crowd:party-detail", pk=pk)


def _reopen_companion_modal(
    request: AuthenticatedRootRequest, *, pk: int, companion_form: PartyCompanionForm
) -> HttpResponse:
    context = build_party_detail_context(request, pk=pk, companion_form=companion_form)
    if context is None:
        raise Http404
    return TemplateResponse(request, "crowd/user/party_detail.html", context)


class PartyCompanionAddActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, pk: int) -> HttpResponse:
        form = PartyCompanionForm(request.POST, auto_id=f"companion_{pk}_%s")
        if not form.is_valid():
            messages.error(request, _("Enter a companion display name."))
            return _reopen_companion_modal(request, pk=pk, companion_form=form)
        outcome = request.services.parties.add_companion(
            member_pk=request.context.current_user_id,
            party_pk=pk,
            display_name=form.cleaned_data["display_name"],
        )
        if outcome == CompanionAddOutcome.ADDED:
            messages.success(request, _("Companion added to the party."))
        elif outcome == CompanionAddOutcome.ALREADY_MEMBER:
            messages.info(request, _("This companion is already in the party."))
        elif outcome == CompanionAddOutcome.AMBIGUOUS_NAME:
            messages.error(
                request,
                _("More than one companion has that display name. Rename one first."),
            )
            return _reopen_companion_modal(request, pk=pk, companion_form=form)
        else:
            messages.error(request, _("No companion matches that display name."))
            return _reopen_companion_modal(request, pk=pk, companion_form=form)
        return redirect("web:crowd:party-detail", pk=pk)


class PartyJoinPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest, token: str) -> HttpResponse:
        party = request.services.parties.read_invitable_party(
            token=token, viewer_pk=request.context.current_user_id
        )
        if party is None:
            messages.error(request, _("This invite link is invalid."))
            return redirect("web:crowd:profile-parties")
        if party.already_member:
            return redirect("web:crowd:party-detail", pk=party.pk)
        return TemplateResponse(
            request, "crowd/user/party_join.html", {"party": party, "token": token}
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest, token: str) -> HttpResponse:
        result = request.services.parties.join_via_link(
            token=token, user_pk=request.context.current_user_id
        )
        if result is None:
            messages.error(request, _("This invite link is invalid."))
            return redirect("web:crowd:profile-parties")
        if result.joined:
            messages.success(request, _("You joined the party."))
        else:
            messages.info(request, _("You're already in this party."))
        return redirect("web:crowd:party-detail", pk=result.party_pk)


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
        return redirect("web:crowd:party-detail", pk=pk)


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
            return redirect("web:crowd:party-detail", pk=pk)
        if request.services.parties.set_my_consent(
            user_pk=request.context.current_user_id, party_pk=pk, mode=mode
        ):
            if mode == PartyConsentMode.ACCEPT_BY_DEFAULT:
                messages.success(request, _("The leader can now enroll you directly."))
            else:
                messages.success(request, _("Enrollments now wait for your approval."))
        else:
            messages.error(request, _("Could not change this setting."))
        return redirect("web:crowd:party-detail", pk=pk)


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
