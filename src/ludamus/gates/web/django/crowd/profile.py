from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse, reverse_lazy
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.generic.base import ContextMixin, View
from django.views.generic.detail import SingleObjectTemplateResponseMixin
from django.views.generic.edit import FormMixin, ProcessFormView

from ludamus.adapters.db.django.models import MAX_CONNECTED_USERS
from ludamus.gates.web.django.crowd.forms import ConnectedUserForm, UserForm
from ludamus.gates.web.django.crowd.helpers import (
    COMPANION_CREATE_AUTO_ID,
    build_parties_context,
    companion_edit_auto_id,
)
from ludamus.pacts.crowd import UserDTO

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

    from ludamus.gates.web.django.entities import AuthenticatedRootRequest, RootRequest


class ProfilePageView(
    LoginRequiredMixin,
    SingleObjectTemplateResponseMixin,
    FormMixin,  # type: ignore [type-arg]
    ContextMixin,
    ProcessFormView,
):
    form_class = UserForm
    request: AuthenticatedRootRequest
    success_url = reverse_lazy("web:index")
    template_name = "crowd/user/edit.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        profile = self.request.services.profile
        kwargs["user"] = profile.read(self.request.context.current_user_slug)
        kwargs["object"] = profile.read(self.request.context.current_user_slug)
        kwargs["confirmed_participations_count"] = (
            profile.confirmed_participations_count(self.request.context.current_user_id)
        )
        kwargs["profile_active_tab"] = "profile"
        return super().get_context_data(**kwargs)

    def form_valid(self, form: UserForm) -> HttpResponse:
        email = form.user_data.get("email", "").strip()
        if email and self.request.services.profile.email_in_use(
            email, exclude_slug=self.request.context.current_user_slug
        ):
            form.add_error(
                "email",
                _(
                    "This email address is already in use. "
                    "Please use a different email address."
                ),
            )
            return self.form_invalid(form)

        self.request.services.profile.update(
            self.request.context.current_user_slug, form.user_data
        )
        messages.success(self.request, _("Profile updated successfully!"))
        return super().form_valid(form)

    def form_invalid(self, form: forms.Form) -> HttpResponse:
        messages.warning(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)

    def get_initial(self) -> dict[str, Any]:
        return self.request.services.profile.read(
            self.request.context.current_user_slug
        ).model_dump()


class ProfileConnectedUsersPageView(
    LoginRequiredMixin,
    SingleObjectTemplateResponseMixin,
    FormMixin,  # type: ignore [type-arg]
    ContextMixin,
    ProcessFormView,
):
    form_class = ConnectedUserForm
    object: UserDTO
    request: AuthenticatedRootRequest
    success_url = reverse_lazy("web:crowd:profile-parties")
    template_name = "crowd/user/parties.html"
    template_name_suffix = "_form"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        _ = (request, args, kwargs)
        return redirect(self.get_success_url())

    def get_form_kwargs(self) -> dict[str, Any]:
        return super().get_form_kwargs() | {"auto_id": COMPANION_CREATE_AUTO_ID}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = build_parties_context(self.request, create_form=kwargs.get("form"))
        context.update(kwargs)
        return super().get_context_data(**context)

    def form_valid(self, form: ConnectedUserForm) -> HttpResponse:

        connected_count = len(
            self.request.services.companions.list_companions(
                self.request.context.current_user_slug
            )
        )
        if connected_count >= MAX_CONNECTED_USERS:
            messages.error(
                self.request,
                _("You can only have up to %(max)s connected users.")
                % {"max": MAX_CONNECTED_USERS},
            )
            return self.form_invalid(form)

        user_data = form.user_data
        user_data["username"] = f"connected|{token_urlsafe(50)}"
        user_data["slug"] = slugify(user_data["username"][:50])
        result = super().form_valid(form)
        self.request.services.companions.create(
            manager_slug=self.request.context.current_user_slug, user_data=user_data
        )
        messages.success(self.request, _("Connected user added successfully!"))
        return result

    def form_invalid(self, form: ConnectedUserForm) -> HttpResponse:
        messages.warning(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)


class ProfileConnectedUserUpdateActionView(
    LoginRequiredMixin,
    SingleObjectTemplateResponseMixin,
    FormMixin,  # type: ignore [type-arg]
    ContextMixin,
    ProcessFormView,
):
    form_class = ConnectedUserForm
    request: AuthenticatedRootRequest
    success_url = reverse_lazy("web:crowd:profile-parties")
    template_name = "crowd/user/parties.html"
    template_name_suffix = "_form"

    def get_object(self) -> UserDTO:
        return self.request.services.companions.read(
            manager_slug=self.request.context.current_user_slug,
            user_slug=self.kwargs["slug"],
        )

    def get_form_kwargs(self) -> dict[str, Any]:
        return super().get_form_kwargs() | {
            "auto_id": companion_edit_auto_id(self.kwargs["slug"])
        }

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = build_parties_context(
            self.request, edit_slug=self.kwargs["slug"], edit_form=kwargs.get("form")
        )
        context.update(kwargs)
        return super().get_context_data(**context)

    def form_valid(self, form: ConnectedUserForm) -> HttpResponse:
        self.request.services.companions.update(
            manager_slug=self.request.context.current_user_slug,
            user_slug=self.kwargs["slug"],
            user_data=form.user_data,
        )
        messages.success(self.request, _("Connected user updated successfully!"))
        return super().form_valid(form)

    def form_invalid(self, form: ConnectedUserForm) -> HttpResponse:
        messages.warning(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)


class ProfileConnectedUserDeleteActionView(
    LoginRequiredMixin,
    SingleObjectTemplateResponseMixin,
    FormMixin,  # type: ignore [type-arg]
    ContextMixin,
    ProcessFormView,
):
    context_object_name = None
    form_class = forms.Form
    model = UserDTO
    pk_url_kwarg = "pk"
    query_pk_and_slug = False
    queryset = None
    request: AuthenticatedRootRequest
    slug_field = "slug"
    slug_url_kwarg = "slug"
    success_url = reverse_lazy("web:crowd:profile-parties")
    template_name_suffix = "_confirm_delete"

    def form_valid(self, form: forms.Form) -> HttpResponseRedirect:  # noqa: ARG002
        success_url = self.get_success_url()
        self.request.services.companions.delete(
            manager_slug=self.request.context.current_user_slug,
            user_slug=self.kwargs["slug"],
        )
        messages.success(self.request, _("Connected user deleted successfully."))
        return HttpResponseRedirect(success_url)


class ProfileConnectedUserClaimLinkActionView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest, slug: str) -> HttpResponse:
        token = request.services.claims.issue(
            manager_slug=request.context.current_user_slug, user_slug=slug
        )
        if token is None:
            messages.error(request, _("Could not create a claim link for this person."))
        else:
            messages.success(request, _("Claim link created."))
        return redirect("web:crowd:profile-parties")


class ClaimPageView(View):
    @staticmethod
    def _reject_invalid_link(request: RootRequest) -> HttpResponse:
        messages.error(
            request, _("This claim link is invalid or has already been used.")
        )
        return redirect("web:index")

    @staticmethod
    def get(request: RootRequest, token: str) -> HttpResponse:
        if request.context.current_user_slug:
            messages.info(
                request,
                _(
                    "You're already signed in. Log out first to claim this "
                    "profile into a new account."
                ),
            )
            return redirect("web:index")
        if (claimable := request.services.claims.read_claimable(token)) is None:
            return ClaimPageView._reject_invalid_link(request)
        return TemplateResponse(
            request, "crowd/claim.html", {"claimable": claimable, "token": token}
        )

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect("web:index")
        if request.services.claims.read_claimable(token) is None:
            return ClaimPageView._reject_invalid_link(request)
        request.session["pending_claim_token"] = token
        login_url = reverse("web:crowd:auth0:login")
        next_url = reverse("web:crowd:profile")
        return redirect(f"{login_url}?{urlencode({'next': next_url})}")


class ProfileAvatarPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> TemplateResponse:
        avatar = request.services.profile.read_avatar(request.context.current_user_slug)
        return TemplateResponse(
            request,
            "crowd/user/avatar.html",
            {
                "user": avatar.user,
                "gravatar_url": avatar.gravatar_url,
                "has_auth0_avatar": avatar.has_auth0_avatar,
                "profile_active_tab": "avatar",
            },
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        use_gravatar = request.POST.get("use_gravatar") == "true"
        request.services.profile.set_avatar_preference(
            request.context.current_user_slug, use_gravatar=use_gravatar
        )
        messages.success(request, _("Avatar preference updated successfully!"))
        return redirect("web:crowd:profile-avatar")


class ProfileShadowbanPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    @staticmethod
    def get(request: AuthenticatedRootRequest) -> TemplateResponse:
        candidates = request.services.shadowban.list_candidates(
            request.context.current_user_id
        )
        return TemplateResponse(
            request,
            "crowd/user/safety.html",
            {"candidates": candidates, "profile_active_tab": "safety"},
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        if identifier := request.POST.get("identifier", "").strip():
            request.services.shadowban.add_by_identifier(
                owner_id=request.context.current_user_id, identifier=identifier
            )
            messages.success(
                request, _("If a matching player exists, they have been shadowbanned.")
            )
            return redirect("web:crowd:profile-safety")

        if slug := request.POST.get("slug", ""):
            banned = request.POST.get("banned") == "true"
            request.services.shadowban.set_shadowban(
                owner_id=request.context.current_user_id,
                target_slug=slug,
                banned=banned,
            )
            messages.success(
                request,
                _("Player shadowbanned.") if banned else _("Shadowban removed."),
            )
        return redirect("web:crowd:profile-safety")
