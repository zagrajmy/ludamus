import json
import logging
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email import message_from_bytes, policy
from enum import StrEnum, auto
from pathlib import Path
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import quote_plus, urlencode, urlparse

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout as django_logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.generic.base import ContextMixin, RedirectView, TemplateView, View
from django.views.generic.detail import DetailView, SingleObjectTemplateResponseMixin
from django.views.generic.edit import FormMixin, ProcessFormView
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from ludamus.adapters.db.django.models import (
    MAX_CONNECTED_USERS,
    SPACE_MAX_DEPTH,
    AgendaItem,
    EnrollmentConfig,
    Event,
    EventSettings,
    Session,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.adapters.oauth import oauth
from ludamus.adapters.web.django.entities import (
    EventInfo,
    ParticipationInfo,
    PartyMemberFlags,
    SessionData,
    SessionUserParticipationData,
    build_display_field_row,
    build_room_lanes,
    build_schedule_days,
    group_sessions_by_state,
)
from ludamus.adapters.web.django.forms import EnrollmentRoster, RosterMember
from ludamus.adapters.web.django.safety_presentation import fake_full_card
from ludamus.gates.web.django.crowd.helpers import (
    COMPANION_CREATE_AUTO_ID,
    build_parties_context,
    companion_edit_auto_id,
)
from ludamus.gates.web.django.entities import (
    AuthenticatedRootRequest,
    RootRequest,
    UserInfo,
)
from ludamus.gates.web.django.helpers import placeholder_cover_url
from ludamus.mills import AcceptProposalService
from ludamus.mills.enrollment import build_anonymous_user, get_user_enrollment_config
from ludamus.pacts import (
    OCCUPYING_PARTICIPATION_STATUSES,
    AgendaItemDTO,
    EventDTO,
    EventListItemDTO,
    LocationData,
    NotFoundError,
    RedirectError,
    SessionDTO,
    SessionFieldValueDTO,
    SessionRepositoryProtocol,
    SessionStatus,
    SpherePage,
)
from ludamus.pacts.crowd import (
    ClaimOutcome,
    ConnectedUserDTO,
    UserData,
    UserDTO,
    UserType,
)
from ludamus.pacts.enrollment import SeatHoldRequest
from ludamus.pacts.party import (
    PartyConsentMode,
    PartyEnrolledNotification,
    PartyMembershipStatus,
)

from .design_fixtures import (
    mock_event_info,
    mock_form,
    mock_session_data,
    mock_session_data_ended,
    mock_user,
)
from .forms import (
    ConnectedUserForm,
    UserForm,
    create_enrollment_form,
    create_proposal_acceptance_form,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.party import EnrollmentPartiesDTO, SelectedEnrollmentPartyDTO

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.db.models.query import QuerySet

MINIMUM_ALLOWED_USER_AGE = 16
CACHE_TIMEOUT = 600  # 10 minutes


def _is_safe_login_redirect(url: str, root_domain: str, *, require_https: bool) -> bool:
    host = urlparse(url).netloc
    allowed = {root_domain}
    if host and (host == root_domain or host.endswith(f".{root_domain}")):
        allowed.add(host)
    return url_has_allowed_host_and_scheme(
        url, allowed_hosts=allowed, require_https=require_https
    )


class LoginRequiredPageView(TemplateView):
    template_name = "crowd/login_required.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["next"] = self.request.GET.get("next", "")
        # Variables for login_button.html component
        context["show_icon"] = True
        context["text"] = ""
        context["extra_class"] = ""
        return context


class Auth0LoginActionView(View):
    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        """Redirect to Auth0 for authentication.

        Returns:
            HttpResponse: Redirect to Auth0 authorization endpoint.

        Raises:
            RedirectError: If the request is not from the root domain.
        """
        root_domain = request.services.sites.read_site(
            request.context.root_sphere_id
        ).domain
        next_path = request.GET.get("next")
        if next_path and not _is_safe_login_redirect(
            next_path, root_domain, require_https=request.is_secure()
        ):
            next_path = None
        if request.get_host() != root_domain:
            if next_path:
                next_path = request.build_absolute_uri(next_path)
            login_url = (
                f"{request.scheme}://{root_domain}{reverse('web:crowd:auth0:login')}"
            )
            url = (
                f"{login_url}?{urlencode({'next': next_path})}"
                if next_path
                else login_url
            )
            raise RedirectError(url)

        # Generate a secure state token
        state_token = token_urlsafe(32)

        # Store state data in cache with 10 minute timeout
        state_data = {
            "redirect_to": next_path,
            "created_at": datetime.now(UTC).isoformat(),
            "csrf_token": request.META.get("CSRF_COOKIE", ""),
        }
        cache_key = f"oauth_state:{state_token}"
        cache.set(cache_key, json.dumps(state_data), timeout=CACHE_TIMEOUT)

        return oauth.auth0.authorize_redirect(  # type: ignore [no-any-return]
            request,
            request.build_absolute_uri(reverse("web:crowd:auth0:login-callback")),
            state=state_token,
        )


class Auth0UserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str = ""
    family_name: str = ""
    given_name: str = ""
    name: str = ""
    nickname: str = ""
    picture: str = ""
    preferred_username: str = ""
    sub: str

    @property
    def display_name(self) -> str | None:
        if self.name.strip():
            return self.name.strip()
        parts = [p.strip() for p in (self.given_name, self.family_name) if p.strip()]
        if parts:
            return " ".join(parts)
        if self.nickname.strip():
            return self.nickname.strip()
        if self.preferred_username.strip():
            return self.preferred_username.strip()
        return None

    @property
    def username(self) -> str:
        return f"auth0|{self.sub}"

    def to_create_data(self, *, slug: str, password: str) -> UserData:
        return UserData(
            slug=slug,
            username=self.username,
            password=password,
            email=self.email or "",
            avatar_url=self.picture or "",
            name=self.display_name or "",
        )

    def to_update_data(self, user: UserDTO) -> UserData:
        data: UserData = {}
        if self.email and user.email != self.email:
            data["email"] = self.email
        if self.picture and user.avatar_url != self.picture:
            data["avatar_url"] = self.picture
        display_name = self.display_name
        if display_name and not (user.name or "").strip():
            data["name"] = display_name
        return data


class Auth0LoginCallbackActionView(RedirectView):
    request: RootRequest

    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        default_redirect = super().get_redirect_url(*args, **kwargs)
        index_url = self.request.build_absolute_uri(reverse("web:index"))

        if (redirect_to := self._resolve_oauth_state(default_redirect)) is None:
            return index_url

        root_domain = self.request.services.sites.read_site(
            self.request.context.root_sphere_id
        ).domain
        if redirect_to and not _is_safe_login_redirect(
            redirect_to, root_domain, require_https=self.request.is_secure()
        ):
            redirect_to = ""

        if self.request.context.current_user_slug:
            return redirect_to or index_url

        userinfo = self._get_userinfo()
        user = self._get_or_create_user(userinfo)

        self.request.di.uow.login_user(self.request, user.slug)
        if self.request.session.get("anonymous_enrollment_active"):
            self.request.session.pop("anonymous_user_code", None)
            self.request.session.pop("anonymous_enrollment_active", None)
            self.request.session.pop("anonymous_event_id", None)
        user = self._apply_user_updates(userinfo, user)

        if not (user.name or "").strip():
            messages.success(self.request, _("Please complete your profile."))
            if redirect_to:
                parsed = urlparse(redirect_to)
                return (
                    f"{parsed.scheme}://{parsed.netloc}{reverse('web:crowd:profile')}"
                )
            return self.request.build_absolute_uri(reverse("web:crowd:profile"))

        return redirect_to or index_url

    def _resolve_oauth_state(self, default_redirect: str | None) -> str | None:
        if not (state_token := self.request.GET.get("state")):
            messages.error(
                self.request,
                _("Invalid authentication request: missing state parameter"),
            )
            return None

        cache_key = f"oauth_state:{state_token}"
        if not (state_data_json := cache.get(cache_key)):
            messages.error(
                self.request, _("Authentication session expired. Please try again.")
            )
            return None

        cache.delete(cache_key)

        try:
            state_data = json.loads(state_data_json)
            redirect_to = state_data.get("redirect_to") or default_redirect or ""

            created_at = datetime.fromisoformat(state_data["created_at"])
            if datetime.now(UTC) - created_at > timedelta(minutes=10):
                messages.error(
                    self.request, _("Authentication session expired. Please try again.")
                )
                return None

        except KeyError, ValueError:
            messages.error(self.request, _("Invalid authentication state"))
            return None

        return redirect_to

    def _get_or_create_user(self, userinfo: Auth0UserInfo) -> UserDTO:
        if claimed := self._redeem_pending_claim(userinfo):
            return claimed
        try:
            return self.request.di.uow.active_users.read_by_username(userinfo.username)
        except NotFoundError:
            create_data = userinfo.to_create_data(
                slug=slugify(userinfo.username), password=make_password(None)
            )
            if self.request.di.uow.active_users.email_exists(
                create_data.get("email", "")
            ):
                create_data["email"] = ""
            self.request.di.uow.active_users.create(create_data)
            return self.request.di.uow.active_users.read_by_username(userinfo.username)

    def _redeem_pending_claim(self, userinfo: Auth0UserInfo) -> UserDTO | None:
        if not (token := self.request.session.pop("pending_claim_token", "")):
            return None
        result = self.request.services.claims.redeem(
            token=token, username=userinfo.username
        )
        if result.outcome == ClaimOutcome.CONVERTED:
            messages.success(
                self.request, _("Profile claimed — it is now your own account.")
            )
            return self.request.di.uow.active_users.read(result.user_slug)
        if result.outcome == ClaimOutcome.ALREADY_AUTHENTICATED:
            messages.info(
                self.request,
                _(
                    "You already have an account, so this profile can't be moved "
                    "into it. Ask the person who invited you to enroll you directly."
                ),
            )
        return None

    def _apply_user_updates(self, userinfo: Auth0UserInfo, user: UserDTO) -> UserDTO:
        if update_data := userinfo.to_update_data(user):
            if (
                "email" in update_data
                and self.request.di.uow.active_users.email_exists(
                    update_data["email"], exclude_slug=user.slug
                )
            ):
                del update_data["email"]
            if update_data:
                self.request.di.uow.active_users.update(user.slug, update_data)
            if "name" in update_data:
                user = self.request.di.uow.active_users.read(user.slug)
        return user

    def _get_userinfo(self) -> Auth0UserInfo:
        token = oauth.auth0.authorize_access_token(self.request)
        raw: dict[str, Any] = {}
        source = "token"
        if isinstance(token, dict):
            raw = token.get("userinfo") or {}
        if not raw:
            source = "/userinfo"
            try:
                result = oauth.auth0.userinfo(token=token)
            except Exception as exc:
                raise RedirectError(
                    reverse("web:index"), error=_("Authentication failed")
                ) from exc
            raw = result if isinstance(result, dict) else {}
        try:
            userinfo = Auth0UserInfo.model_validate(raw)
        except PydanticValidationError as exc:
            raise RedirectError(
                reverse("web:index"), error=_("Authentication failed")
            ) from exc
        logger.info(
            "Auth0 userinfo from %s: sub=%s has_name=%s",
            source,
            userinfo.sub,
            bool(userinfo.name),
        )
        return userinfo


class Auth0LogoutActionView(RedirectView):
    request: RootRequest

    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        redirect_to = super().get_redirect_url(*args, **kwargs)

        django_logout(self.request)

        last_domain = self.request.di.uow.spheres.read_site(
            self.request.context.current_sphere_id
        ).domain
        messages.success(self.request, _("You have been successfully logged out."))

        return _auth0_logout_url(
            self.request, last_domain=last_domain, redirect_to=redirect_to
        )


def _auth0_logout_url(
    request: RootRequest,
    *,
    last_domain: str | None = None,
    redirect_to: str | None = None,
) -> str:
    root_domain = request.di.uow.spheres.read_site(
        request.context.root_sphere_id
    ).domain
    last_domain = last_domain or root_domain
    redirect_to = redirect_to or reverse("web:index")
    return f"https://{settings.AUTH0_DOMAIN}/v2/logout?" + urlencode(
        {
            "returnTo": (
                f"{request.scheme}://{root_domain}{reverse('web:crowd:auth0:logout-redirect')}?last_domain={last_domain}&redirect_to={redirect_to}"
            ),
            "client_id": settings.AUTH0_CLIENT_ID,
        },
        quote_via=quote_plus,
    )


class Auth0LogoutRedirectActionView(RedirectView):
    request: RootRequest
    pattern_name = "web:index"

    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        redirect_url = super().get_redirect_url(*args, **kwargs)

        # Get the redirect_to parameter
        if redirect_to := self.request.GET.get("redirect_to"):
            # Only allow relative URLs (starting with /)
            if redirect_to.startswith("/") and not redirect_to.startswith("//"):
                redirect_url = redirect_to
            else:
                messages.warning(self.request, _("Invalid redirect URL."))

        # Handle last_domain parameter for multi-site redirects
        if last_domain := self.request.GET.get("last_domain"):
            # Also allow subdomains of ROOT_DOMAIN if configured
            if (
                last_domain.endswith(f".{settings.ROOT_DOMAIN}")
                or last_domain == settings.ROOT_DOMAIN
            ):
                return f"{self.request.scheme}://{last_domain}{redirect_url}"

            # Check against explicitly allowed domains
            try:
                last_sphere = self.request.di.uow.spheres.read_by_domain(last_domain)
            except NotFoundError:
                last_sphere = None

            if last_sphere:
                return f"{self.request.scheme}://{last_domain}{redirect_url}"

            messages.warning(self.request, _("Invalid domain for redirect."))

        return redirect_url


class DesignPageView(TemplateView):
    request: RootRequest
    template_name = "design.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["design_event"] = mock_event_info()
        context["design_session_data"] = mock_session_data()
        context["design_session_data_ended"] = mock_session_data_ended()
        context["design_user"] = mock_user()
        context["design_form"] = mock_form()
        context["design_radio_options"] = [
            ("a", "Radio A", True, "design-radio-a"),
            ("b", "Radio B", False, "design-radio-b"),
        ]
        return context


class CapturedEmail(NamedTuple):
    subject: str
    to: str
    date: str
    body: str


def _read_captured_emails(directory: Path) -> list[CapturedEmail]:
    if not directory.exists():
        return []
    emails: list[CapturedEmail] = []
    for log_file in sorted(directory.glob("*.log"), reverse=True):
        for chunk in reversed(log_file.read_bytes().split(b"-" * 79)):
            if not (raw := chunk.strip()):
                continue
            message = message_from_bytes(raw, policy=policy.default)
            body = message.get_body(preferencelist=("plain", "html"))
            emails.append(
                CapturedEmail(
                    subject=str(message["Subject"] or ""),
                    to=str(message["To"] or ""),
                    date=str(message["Date"] or ""),
                    body=body.get_content() if body else "",
                )
            )
    return emails


class StagingEmailInboxView(View):
    request: RootRequest

    def get(self, _request: RootRequest) -> HttpResponse:
        if not settings.EMAIL_FILE_PATH or not self.request.user.is_staff:
            raise Http404
        return TemplateResponse(
            self.request,
            "staging_email_inbox.html",
            {"emails": _read_captured_emails(Path(settings.EMAIL_FILE_PATH))},
        )


class IndexRedirectView(View):
    request: RootRequest

    def get(self, _request: RootRequest) -> HttpResponse:
        sphere = self.request.di.uow.spheres.read(
            self.request.context.current_sphere_id
        )
        if sphere.default_page == SpherePage.ENCOUNTERS:
            return redirect("web:notice-board:index")
        return redirect("web:events")


def _is_manager(request: RootRequest) -> bool:
    return (
        request.user.is_authenticated
        and request.context.current_user_slug is not None
        and request.di.uow.spheres.is_manager(
            request.context.current_sphere_id, request.context.current_user_slug
        )
    )


class EventsPageView(TemplateView):
    request: RootRequest
    template_name = "index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sphere_id = self.request.context.current_sphere_id
        context["announcements"] = self.request.services.announcements.list_published(
            sphere_id
        )
        items = self.request.services.events.list_for_sphere(
            sphere_id, include_unpublished=_is_manager(self.request)
        )
        context["upcoming_events"] = self._with_covers(
            sorted(
                (item for item in items if not item.is_ended),
                key=lambda item: item.start_time,
            )
        )
        context["past_events"] = self._with_covers(
            sorted(
                (item for item in items if item.is_ended),
                key=lambda item: item.start_time,
                reverse=True,
            )
        )
        return context

    @staticmethod
    def _with_covers(items: list[EventListItemDTO]) -> list[EventInfo]:
        # Uploaded cover when present, otherwise a placeholder cycled by position.
        return [
            EventInfo.from_list_item(
                item, cover_image_url=item.cover_image_url or placeholder_cover_url(i)
            )
            for i, item in enumerate(items)
        ]


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
        kwargs["user"] = self.request.di.uow.active_users.read(
            self.request.context.current_user_slug
        )
        kwargs["object"] = self.request.di.uow.active_users.read(
            self.request.context.current_user_slug
        )
        kwargs["confirmed_participations_count"] = SessionParticipation.objects.filter(
            user_id=self.request.context.current_user_id,
            status=SessionParticipationStatus.CONFIRMED,
        ).count()
        return super().get_context_data(**kwargs)

    def form_valid(self, form: UserForm) -> HttpResponse:
        # Check if email is being changed and if it already exists
        email = form.user_data.get("email", "").strip()
        if email and self.request.di.uow.active_users.email_exists(
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

        self.request.di.uow.active_users.update(
            self.request.context.current_user_slug, form.user_data
        )
        messages.success(self.request, _("Profile updated successfully!"))
        return super().form_valid(form)

    def form_invalid(self, form: forms.Form) -> HttpResponse:
        messages.warning(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)

    def get_initial(self) -> dict[str, Any]:
        return self.request.di.uow.active_users.read(
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
        # The page moved to the parties tab; this endpoint keeps handling the
        # add-companion POST.
        _ = (request, args, kwargs)  # Django View dispatch
        return redirect(self.get_success_url())

    def get_form_kwargs(self) -> dict[str, Any]:
        return super().get_form_kwargs() | {"auto_id": COMPANION_CREATE_AUTO_ID}

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = build_parties_context(self.request, create_form=kwargs.get("form"))
        context.update(kwargs)
        return super().get_context_data(**context)

    def form_valid(self, form: ConnectedUserForm) -> HttpResponse:
        # Check if user has reached the maximum number of connected users

        connected_count = len(
            self.request.di.uow.connected_users.read_all(
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
        self.request.di.uow.connected_users.create(
            self.request.context.current_user_slug, user_data=user_data
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
        return self.request.di.uow.connected_users.read(
            self.request.context.current_user_slug, self.kwargs["slug"]
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
        self.request.di.uow.connected_users.update(
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
        self.request.di.uow.connected_users.delete(
            self.request.context.current_user_slug, self.kwargs["slug"]
        )
        messages.success(self.request, _("Connected user deleted successfully."))
        return HttpResponseRedirect(success_url)


class ProfileConnectedUserClaimLinkActionView(LoginRequiredMixin, View):
    # POST: mint a share link that lets a connected person take over their
    # profile as their own self-login account.
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
    # Landing page for a claim link. The recipient signs in via Auth0 and the
    # managed row becomes their own account.
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
        user = request.di.uow.active_users.read(request.context.current_user_slug)
        return TemplateResponse(
            request,
            "crowd/user/avatar.html",
            {
                "user": user,
                "gravatar_url": request.di.gravatar_url(user.email),
                "has_auth0_avatar": bool(user.avatar_url),
            },
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        use_gravatar = request.POST.get("use_gravatar") == "true"
        request.di.uow.active_users.update(
            request.context.current_user_slug, UserData(use_gravatar=use_gravatar)
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
            request, "crowd/user/shadowbans.html", {"candidates": candidates}
        )

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        if identifier := request.POST.get("identifier", "").strip():
            # Neutral message either way: never confirm whether an account with
            # this username/email exists (no enumeration of the user base).
            request.services.shadowban.add_by_identifier(
                owner_id=request.context.current_user_id, identifier=identifier
            )
            messages.success(
                request, _("If a matching player exists, they have been shadowbanned.")
            )
            return redirect("web:crowd:profile-shadowbans")

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
        return redirect("web:crowd:profile-shadowbans")


def _get_displayed_field_ids(event: Event) -> set[int]:
    with suppress(EventSettings.DoesNotExist):
        return set(event.settings.displayed_session_fields.values_list("id", flat=True))
    return set()


def _get_public_select_fields(event: Event) -> list[Any]:
    return list(
        event.session_fields.filter(field_type="select", is_public=True).order_by(
            "order", "name"
        )
    )


def _field_value_dtos_from_models(
    field_values: Iterable[SessionFieldValue],
) -> list[SessionFieldValueDTO]:
    return sorted(
        (
            SessionFieldValueDTO(
                allow_custom=fv.field.allow_custom,
                field_icon=fv.field.icon,
                field_id=fv.field_id,
                field_name=fv.field.name,
                field_question=fv.field.question,
                field_slug=fv.field.slug,
                field_type=fv.field.field_type,
                is_public=fv.field.is_public,
                value=fv.value,
                field_order=fv.field.order,
            )
            for fv in field_values
            if fv.field.is_public
        ),
        key=lambda fv: (fv.field_order, fv.field_name),
    )


# Above this many scheduled sessions, the card grid becomes unwieldy and the
# event page switches to the compact schedule (a dense chronological list with
# an hour scrubber). Tunable; not a business invariant, so it lives here rather
# than in specs.
COMPACT_SCHEDULE_MIN_SESSIONS = 60


class EventPageView(DetailView):  # type: ignore [type-arg]
    template_name = "chronology/event.html"
    model = Event
    context_object_name = "event"
    request: RootRequest

    def get_queryset(self) -> QuerySet[Event]:
        return (
            Event.objects.filter(sphere_id=self.request.context.current_sphere_id)
            .select_related("sphere")
            .prefetch_related(
                "spaces__agenda_items__session__field_values__field",
                "spaces__agenda_items__session__session_participations__user",
                "enrollment_configs",
            )
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        if not self.object.is_published and not _is_manager(self.request):
            raise Http404

        # Get all sessions for this event that are published
        event_sessions = (
            Session.objects.filter(event=self.object, agenda_item__isnull=False)
            .select_related(
                # str(space) walks the whole ancestor chain, so eager-load every
                # level up to the max nesting depth to avoid per-row parent queries.
                "presenter",
                "agenda_item__space" + "__parent" * (SPACE_MAX_DEPTH - 1),
                "event",
                "event__sphere",
            )
            .prefetch_related(
                "tags__category",
                "session_participations__user",
                "field_values__field",
                "event__enrollment_configs",
            )
            .annotate(
                enrolled_count_cached=Count(
                    "session_participations",
                    filter=Q(
                        session_participations__status=SessionParticipationStatus.CONFIRMED
                    ),
                ),
                waiting_count_cached=Count(
                    "session_participations",
                    filter=Q(
                        session_participations__status=SessionParticipationStatus.WAITING
                    ),
                ),
            )
            .order_by("agenda_item__start_time")
        )

        # Shadowban: hide a presenter's sessions from players they shadowbanned,
        # and collect the viewer's shadowbans to red-ring their avatars (the
        # ring is carried per-participation on the DTO, not via template logic).
        shadowbanned_ids: frozenset[int] = frozenset()
        if current_user_id := self.request.context.current_user_id:
            if hidden := self.request.services.shadowban.banning_owner_ids(
                current_user_id
            ):
                event_sessions = event_sessions.exclude(presenter_id__in=hidden)
            shadowbanned_ids = frozenset(
                self.request.services.shadowban.banned_user_ids(current_user_id)
            )

        hour_data = dict(self._get_hour_data(event_sessions, shadowbanned_ids))
        # Get session data objects that include enrollment status
        sessions_data = self._get_session_data(event_sessions, shadowbanned_ids)

        # Hard event ban: a banned viewer sees every session as full (with
        # simulacra participants) and gets no Enroll action, so the event looks
        # full and they are never told they are banned.
        event_banned = current_user_id is not None and (
            self.request.services.event_bans.is_banned(
                event_id=self.object.pk, user_id=current_user_id
            )
        )
        if event_banned:
            sessions_data = {
                sid: fake_full_card(data) for sid, data in sessions_data.items()
            }

        compact_schedule = len(sessions_data) >= COMPACT_SCHEDULE_MIN_SESSIONS

        if compact_schedule and current_user_id:
            self._set_user_bookmarks(sessions_data, current_user_id)

        # The ended/current/future grouping only feeds the card-grid layout;
        # the compact schedule renders from schedule_days instead, so skip the
        # pass there but keep the context keys (tests enumerate them exactly).
        ended_hour_data: dict[datetime, list[SessionData]] = {}
        current_hour_data: dict[datetime, list[SessionData]] = {}
        future_unavailable_hour_data: dict[datetime, list[SessionData]] = {}
        if not compact_schedule:
            ended_hour_data, current_hour_data, future_unavailable_hour_data = (
                group_sessions_by_state(sessions_data)
            )

        schedule_days = build_schedule_days(sessions_data) if compact_schedule else []
        # The compact schedule offers two layouts: the chronological ledger
        # (default) and a rooms grid (?view=rooms) with a column per room.
        rooms_view = compact_schedule and self.request.GET.get("view") == "rooms"
        event_url = reverse("web:chronology:event", kwargs={"slug": self.object.slug})

        context.update(
            {
                "hour_data": hour_data,  # Keep original for backward compatibility
                "sessions": list(sessions_data.values()),
                "compact_schedule": compact_schedule,
                "schedule_days": schedule_days,
                "schedule_view_is_list": not rooms_view,
                "schedule_view_is_rooms": rooms_view,
                "room_lane_days": build_room_lanes(schedule_days) if rooms_view else [],
                "schedule_list_url": event_url,
                "schedule_rooms_url": f"{event_url}?view=rooms",
                "ended_hour_data": ended_hour_data,
                "current_hour_data": current_hour_data,
                "future_unavailable_hour_data": future_unavailable_hour_data,
                "total_enrolled": sum(s.enrolled_count for s in sessions_data.values()),
                "user_enrolled_sessions": [
                    s for s in sessions_data.values() if s.user_enrolled
                ],
                "user_enrolled_session_titles": [
                    s.session.title for s in sessions_data.values() if s.user_enrolled
                ],
                "event_banned": event_banned,
            }
        )

        # Add user enrollment config for authenticated users
        user_enrollment_config = None
        if (
            self.request.context.current_user_slug
            and self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ).email
        ):
            user_enrollment_config = get_user_enrollment_config(
                event=EventDTO.model_validate(self.object),
                user_email=self.request.di.uow.active_users.read(
                    self.request.context.current_user_slug
                ).email,
                enrollment_config_repo=self.request.di.uow.enrollment_configs,
                ticket_api=self.request.di.ticket_api,
                check_interval_minutes=settings.MEMBERSHIP_API_CHECK_INTERVAL,
            )
        context["user_enrollment_config"] = user_enrollment_config

        # Check if any active enrollment config requires slots
        active_configs = self.object.get_active_enrollment_configs()
        requires_slots = any(
            config.restrict_to_configured_users for config in active_configs
        )
        context["enrollment_requires_slots"] = requires_slots
        context.update(self._get_anonymous_context())

        context["filterable_tag_categories"] = _get_public_select_fields(self.object)
        context.update(self._get_pending_sessions_context())

        return context

    def _get_anonymous_context(self) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        anonymous_service = self.request.services.anonymous_enrollment

        if self.request.context.current_user_id and self.request.session.get(
            "anonymous_enrollment_active"
        ):
            self._clear_anonymous_session()
            return ctx

        if (
            not self.request.session.get("anonymous_enrollment_active")
            or self.request.context.current_user_id
        ):
            return ctx

        anonymous_user_code = self.request.session.get("anonymous_user_code")
        current_site_id = self.request.context.current_site_id
        session_site_id = self.request.session.get("anonymous_site_id")

        if not (anonymous_user_code and session_site_id == current_site_id):
            self._clear_anonymous_session()
            return ctx

        anonymous_user = None
        with suppress(NotFoundError):
            anonymous_user = anonymous_service.get_user_by_code(
                code=anonymous_user_code
            )

        if not anonymous_user:
            self._clear_anonymous_session()
            return ctx

        ctx["anonymous_code"] = anonymous_user.slug.removeprefix("code_")
        anonymous_enrollments = SessionParticipation.objects.filter(
            user_id=anonymous_user.pk, session__event=self.object
        ).select_related("session")
        ctx["anonymous_user_enrollments"] = list(anonymous_enrollments)
        return ctx

    def _clear_anonymous_session(self) -> None:
        self.request.session.pop("anonymous_user_code", None)
        self.request.session.pop("anonymous_enrollment_active", None)
        self.request.session.pop("anonymous_event_id", None)
        self.request.session.pop("anonymous_site_id", None)

    def _get_pending_sessions_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {
            "pending_sessions": [],
            "pending_review_visible": False,
            "pending_wizard_view": False,
            "own_pending_proposals": [],
        }
        if (
            not self.request.context.current_user_slug
            or self.request.context.current_user_id is None
        ):
            return context

        is_sphere_manager = self.object.sphere.managers.filter(
            id=self.request.context.current_user_id
        ).exists()
        is_superuser = self.request.di.uow.active_users.read(
            self.request.context.current_user_slug
        ).is_superuser

        if is_superuser or is_sphere_manager:
            return context | {
                "pending_sessions": self.request.di.uow.sessions.read_pending_by_event(
                    self.object.pk
                ),
                "pending_review_visible": True,
                "pending_wizard_view": is_superuser and not is_sphere_manager,
            }

        return context | {
            "own_pending_proposals": list(
                self._get_session_data(self._get_own_pending_sessions()).values()
            )
        }

    def _get_own_pending_sessions(self) -> QuerySet[Session]:
        # The author's unscheduled proposals, rendered as schedule-style cards.
        # Same eager-loading shape as event_sessions, minus the agenda item.
        return (
            Session.objects.filter(
                category__event_id=self.object.pk,
                status=SessionStatus.PENDING,
                presenter_id=self.request.context.current_user_id,
            )
            .select_related("presenter", "agenda_item", "event", "event__sphere")
            .prefetch_related(
                "tags__category",
                "session_participations__user",
                "field_values__field",
                "event__enrollment_configs",
            )
            .order_by("-creation_time")
        )

    def _set_user_participations(
        self, sessions: dict[int, SessionData], event_sessions: QuerySet[Session]
    ) -> None:
        anonymous_service = self.request.services.anonymous_enrollment
        # Handle authenticated users
        if self.request.context.current_user_slug:
            # Get all connected users in a single query
            all_users = [
                self.request.di.uow.active_users.read(
                    self.request.context.current_user_slug
                ),
                *self.request.di.uow.connected_users.read_all(
                    self.request.context.current_user_slug
                ),
            ]

            # Pre-fetch all participations for relevant users and sessions
            participations = SessionParticipation.objects.filter(
                session__in=event_sessions, user_id__in=[u.pk for u in all_users]
            ).select_related("user", "session")

            # Create lookup dictionaries for efficient access
            participation_by_user_session: dict[tuple[int, int], list[str]] = (
                defaultdict(list)
            )
            for p in participations:
                key = (p.user_id, p.session_id)
                participation_by_user_session[key].append(p.status)

            # Add user participation info for each session
            for user in all_users:
                for session in event_sessions:
                    statuses = set(
                        participation_by_user_session.get((user.pk, session.id), [])
                    )

                    sessions[session.id].user_enrolled |= (
                        SessionParticipationStatus.CONFIRMED in statuses
                    )
                    sessions[session.id].user_waiting |= (
                        SessionParticipationStatus.WAITING in statuses
                    )

        # Handle anonymous users
        elif self.request.session.get(
            "anonymous_enrollment_active"
        ) and self.request.session.get("anonymous_user_code"):
            # Validate anonymous user is for the current site
            current_site_id = self.request.context.current_site_id
            session_site_id = self.request.session.get("anonymous_site_id")
            anonymous_user_code = self.request.session.get("anonymous_user_code")
            if session_site_id == current_site_id and anonymous_user_code is not None:
                anonymous_user = None
                with suppress(NotFoundError):
                    anonymous_user = anonymous_service.get_user_by_code(
                        code=anonymous_user_code
                    )

                if anonymous_user:
                    # Pre-fetch anonymous user participations for event sessions
                    anonymous_participations = SessionParticipation.objects.filter(
                        session__in=event_sessions, user_id=anonymous_user.pk
                    ).select_related("session")

                    # Create lookup dictionary for anonymous user
                    anonymous_participation_by_session: dict[int, list[str]] = (
                        defaultdict(list)
                    )
                    for p in anonymous_participations:
                        anonymous_participation_by_session[p.session_id].append(
                            p.status
                        )

                    # Add anonymous user participation info for each session
                    for session in event_sessions:
                        statuses = set(
                            anonymous_participation_by_session.get(session.id, [])
                        )

                        sessions[session.id].user_enrolled = (
                            SessionParticipationStatus.CONFIRMED in statuses
                        )
                        sessions[session.id].user_waiting = (
                            SessionParticipationStatus.WAITING in statuses
                        )

    def _set_user_bookmarks(
        self, sessions_data: dict[int, SessionData], current_user_id: int
    ) -> None:
        # Bookmarks are only surfaced on the compact schedule (the lightweight
        # "I want to attend" gesture for big events). One query for the whole set.
        bookmarked_ids = self.request.services.bookmarks.bookmarked_session_ids(
            user_id=current_user_id, event_id=self.object.pk
        )
        for sid, data in sessions_data.items():
            data.user_bookmarked = sid in bookmarked_ids

    def _get_hour_data(
        self,
        event_sessions: QuerySet[Session],
        shadowbanned_ids: frozenset[int] = frozenset(),
    ) -> dict[datetime, list[SessionData]]:
        # Expects a scheduled-only queryset (agenda_item__isnull=False): the
        # grouping below dereferences each session's agenda item.
        sessions_data = self._get_session_data(event_sessions, shadowbanned_ids)

        sessions_by_hour: dict[datetime, list[SessionData]] = defaultdict(list)
        for session in event_sessions:
            sessions_by_hour[session.agenda_item.start_time].append(
                sessions_data[session.id]
            )

        return sessions_by_hour

    def _get_session_data(
        self,
        event_sessions: QuerySet[Session],
        shadowbanned_ids: frozenset[int] = frozenset(),
    ) -> dict[int, SessionData]:
        event_override = self.object.allow_facilitator_session_edit
        sphere_default = self.object.sphere.allow_facilitator_session_edit
        edit_allowed = sphere_default if event_override is None else event_override
        current_user_id = self.request.context.current_user_id

        sessions_data = {}
        for session in event_sessions:
            try:
                agenda_item = session.agenda_item
            except AgendaItem.DoesNotExist:
                # Pending proposal: not scheduled yet, so no time or space.
                agenda_item = None
            if agenda_item is not None:
                space = agenda_item.space
                loc = LocationData(
                    space_name=space.name,
                    parent_slug=space.parent.slug if space.parent else "",
                    parent_name=space.parent.name if space.parent else "",
                    path=str(space),
                )
            else:
                loc = LocationData(
                    space_name="", parent_slug="", parent_name="", path=""
                )
            if session.presenter_id:
                presenter_dto = UserDTO.model_validate(session.presenter)
                presenter = UserInfo.from_user_dto(
                    presenter_dto, gravatar_url=self.request.di.gravatar_url
                )
            else:
                presenter_name = session.display_name or ""
                presenter = UserInfo(
                    avatar_url=None,
                    discord_username="",
                    full_name=presenter_name,
                    name=presenter_name,
                    pk=0,
                    slug="",
                    username=presenter_name,
                )
            sessions_data[session.id] = SessionData(
                can_edit=(
                    edit_allowed
                    and current_user_id is not None
                    and session.presenter_id == current_user_id
                ),
                effective_participants_limit=session.effective_participants_limit,
                full_participant_info=session.full_participant_info,
                agenda_item=(
                    AgendaItemDTO.model_validate(agenda_item)
                    if agenda_item is not None
                    else None
                ),
                session=SessionDTO.model_validate(session),
                presenter=presenter,
                field_values=_field_value_dtos_from_models(session.field_values.all()),
                # is_session_eligible dereferences agenda_item, and an
                # unscheduled proposal can't be enrolled in anyway.
                is_enrollment_available=(
                    agenda_item is not None and session.is_enrollment_available
                ),
                is_full=session.is_full,
                loc=loc,
                enrolled_count=session.enrolled_count,
                waiting_count=session.waiting_count,
                session_participations=[
                    ParticipationInfo(
                        user=UserInfo.from_user_dto(
                            UserDTO.model_validate(sp.user),
                            gravatar_url=self.request.di.gravatar_url,
                        ),
                        status=sp.status,
                        creation_time=sp.creation_time,
                        is_shadowbanned=sp.user_id in shadowbanned_ids,
                    )
                    for sp in session.session_participations.all()
                ],
            )

        # Check if any active enrollment config has limit_to_end_time enabled
        active_configs = self.object.get_active_enrollment_configs()
        limit_configs = [c for c in active_configs if c.limit_to_end_time]
        current_time = datetime.now(tz=UTC)

        # Get the earliest end_time from configs with limit_to_end_time
        earliest_limit_end_time = None
        if limit_configs:
            earliest_limit_end_time = min(config.end_time for config in limit_configs)

        # Set displayed field values and display status for each session
        displayed_field_ids = _get_displayed_field_ids(self.object)
        for session_data in sessions_data.values():
            session_data.displayed_field_rows = [
                build_display_field_row(fv)
                for fv in session_data.field_values
                if fv.field_id in displayed_field_ids
            ]

            if session_data.agenda_item is None:
                continue
            session_start = session_data.agenda_item.start_time

            # Calculate if session is ongoing (has already started) or fully over
            session_data.is_ongoing = session_start <= current_time
            session_data.is_ended = session_data.agenda_item.end_time <= current_time

            # Mark sessions as inactive for display based on limit_to_end_time rules
            if limit_configs and earliest_limit_end_time and session_data.is_ongoing:
                session_data.should_show_as_inactive = True

        # Set user participation data for authenticated users and anonymous users
        self._set_user_participations(sessions_data, event_sessions)

        return sessions_data


class EnrollmentChoice(StrEnum):
    CANCEL = auto()
    ENROLL = auto()
    WAITLIST = auto()
    BLOCK = auto()


@dataclass
class EnrollmentRequest:
    user: UserDTO
    choice: EnrollmentChoice
    name: str = _("yourself")
    # A real co-member of the selected party (not the viewer, not a
    # companion): they are notified about seats taken on their behalf.
    is_party_member: bool = False
    # ACCEPT_INVITES member: "enroll" holds an OFFERED seat they must claim.
    needs_accept: bool = False


@dataclass
class Enrollments:
    cancelled_users: list[str]
    skipped_users: list[str]
    users_by_status: dict[SessionParticipationStatus, list[str]]

    def __init__(self) -> None:
        self.cancelled_users = []
        self.skipped_users = []
        self.users_by_status = defaultdict(list)
        # Set when a cancellation frees a held (confirmed) seat, so the caller
        # can run waiting-list promotion after the transaction commits.
        self.freed_seat = False
        # (user_id, name) of fresh enrol/waitlist sign-ups, so the caller can
        # warn the presenter about shadowbanned players after commit.
        self.signed_up_users: list[tuple[int, str]] = []
        # Seats taken for real party members, announced to them after commit.
        self.party_notices = PartyNotices()
        # Final +N guest headcount after this submit; None when untouched.
        self.guest_total: int | None = None
        super().__init__()


@dataclass
class PartyNotices:
    # ACCEPT_INVITES members to hold seats for (created via the promotion
    # service at the end of the batch).
    held_seats: list[UserDTO] = field(default_factory=list)
    # Real members seated directly (ACCEPT_BY_DEFAULT).
    enrolled_members: list[UserDTO] = field(default_factory=list)


def _guest_participations(
    session: Session, viewer_pk: int
) -> QuerySet[SessionParticipation]:
    return SessionParticipation.objects.filter(
        session=session, enrolled_by_id=viewer_pk, user__user_type=UserType.ANONYMOUS
    ).order_by("pk")


def _event_allows_anonymous_enrollment(event: Event, session: Session) -> bool:
    # Unscheduled sessions have no enrollment to join — and eligibility below
    # reads agenda times, which they don't have.
    if not hasattr(session, "agenda_item"):
        return False
    return any(
        config.allow_anonymous_enrollment and config.is_session_eligible(session)
        for config in event.get_active_enrollment_configs()
    )


def _get_session_or_redirect(
    request: AuthenticatedRootRequest, event_slug: str, session_id: int
) -> Session:
    try:
        session = Session.objects.get(
            event__slug=event_slug,
            event__sphere_id=request.context.current_sphere_id,
            id=session_id,
        )
    except Session.DoesNotExist:
        raise RedirectError(
            reverse("web:index"), error=_("Session not found.")
        ) from None
    viewer_id = request.context.current_user_id
    # Shadowban: a player the presenter shadowbanned cannot reach the session.
    if session.presenter_id in request.services.shadowban.banning_owner_ids(viewer_id):
        raise RedirectError(
            reverse("web:index"), error=_("Session not found.")
        ) from None
    if not AgendaItem.objects.filter(session_id=session.pk).exists():
        raise RedirectError(
            reverse("web:index"),
            error=_("No enrollment configuration is available for this session."),
        )
    # Hard event ban: a banned user cannot enrol; bounce them back to the
    # (fake-full) event page without revealing the ban.
    event = session.event
    if request.services.event_bans.is_banned(event_id=event.pk, user_id=viewer_id):
        raise RedirectError(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        ) from None
    return session


_status_by_choice = {
    "enroll": SessionParticipationStatus.CONFIRMED,
    "waitlist": SessionParticipationStatus.WAITING,
}


class SessionOfferClaimView(View):
    """Login-free claim of an offered waiting-list spot via its token link.

    Works for anonymous waiters (the token is the credential). GET shows the
    offer; POST claims the whole party.
    """

    @staticmethod
    def get(request: RootRequest, token: str) -> HttpResponse:
        offer = request.services.waitlist_promotion.peek_offer(token=token)
        if offer is None:
            messages.error(
                request, _("This offer is no longer available or has expired.")
            )
            return redirect("web:events")
        return TemplateResponse(
            request, "chronology/offer_claim.html", {"offer": offer, "token": token}
        )

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        result = request.services.waitlist_promotion.claim_offer(token=token)
        if result.success and result.event_slug:
            messages.success(
                request, _("Spot claimed — you are now confirmed for this session.")
            )
            return redirect("web:chronology:event", slug=result.event_slug)
        messages.error(request, _("This offer has expired or was already claimed."))
        return redirect("web:events")


class SessionOfferDeclineView(View):
    """Login-free decline of an offered spot via its token link.

    The way out of a seat held by a party leader (or an unwanted waitlist
    offer): drops the offered rows and rolls the freed seats on.
    """

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        result = request.services.waitlist_promotion.decline_offer(token=token)
        if result.success and result.event_slug:
            messages.success(request, _("Offer declined — the seat was released."))
            return redirect("web:chronology:event", slug=result.event_slug)
        messages.error(request, _("This offer is no longer available or has expired."))
        return redirect("web:events")


class NotificationsMarkReadView(LoginRequiredMixin, View):
    """POST: mark all of the current user's notifications as read."""

    request: AuthenticatedRootRequest

    @staticmethod
    def post(request: AuthenticatedRootRequest) -> HttpResponse:
        request.services.notifications.mark_all_read(request.context.current_user_id)
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ):
            return redirect(next_url)
        return redirect("web:index")


class SessionEnrollPageView(LoginRequiredMixin, View):
    request: AuthenticatedRootRequest

    def get(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        session = _get_session_or_redirect(request, event_slug, session_id)
        selection = self._party_selection(session, request.GET.get("party"))
        members = self._party_members(session, selection.selected)
        form = create_enrollment_form(
            session=session,
            current_user=self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ),
            roster=EnrollmentRoster(
                companions=tuple(selection.companions),
                members=tuple(members),
                guest_count=self._guest_count(session),
            ),
            enrollment_config_repo=request.di.uow.enrollment_configs,
            ticket_api=request.di.ticket_api,
        )()

        return TemplateResponse(
            request,
            "chronology/enroll_select.html",
            self._page_context(
                session=session, selection=selection, form=form, members=members
            ),
        )

    def _party_selection(
        self, session: Session, requested: str | None
    ) -> EnrollmentPartiesDTO:
        selection = self.request.services.parties.enrollment_selection(
            viewer_pk=self.request.context.current_user_id, requested_party=requested
        )
        if selection.requested_invalid:
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"event_slug": session.event.slug, "session_id": session.pk},
                ),
                error=_("Choose one of your parties or enroll by yourself."),
            )
        return selection

    def _page_context(
        self,
        *,
        session: Session,
        selection: EnrollmentPartiesDTO,
        form: forms.Form,
        members: list[RosterMember],
    ) -> dict[str, Any]:
        return {
            "session": session,
            "event": session.event,
            "party_choices": selection.choices,
            "selected_party": selection.selected,
            "connected_users": selection.companions,
            "user_data": self._get_user_participation_data(
                session, selection.companions, members
            ),
            # Frontload the decision: warn the viewer up top if players they
            # shadowbanned are already signed up to this session.
            "shadowban_warnings": self.request.services.shadowban.list_session_warnings(
                viewer_id=self.request.context.current_user_id, session_id=session.pk
            ),
            "form": form,
        }

    def _guest_count(self, session: Session) -> int | None:
        # None when the organizer has not opened anonymous enrollment for this
        # session — the stepper then never renders.
        if not _event_allows_anonymous_enrollment(session.event, session):
            return None
        return _guest_participations(
            session, self.request.context.current_user_id
        ).count()

    def _party_members(
        self, session: Session, selected: SelectedEnrollmentPartyDTO | None
    ) -> list[RosterMember]:
        # Real ACTIVE co-members of the viewer's selected led party. Whether a
        # member can be seated directly follows their consent (O-9): only
        # ACCEPT_INVITES members require the held-seat accept round-trip.
        if selected is None or not selected.is_own_led:
            return []
        eligible = [
            member
            for member in selected.members
            if not member.is_leader
            and not member.is_login_less
            and member.status == PartyMembershipStatus.ACTIVE
        ]
        if not eligible:
            return []
        users = {
            user.pk: user
            for user in self.request.di.uow.active_users.read_by_ids(
                [member.user_pk for member in eligible]
            )
        }
        enrollment_config = session.event.get_most_liberal_config(session)
        restricted = bool(
            enrollment_config and enrollment_config.restrict_to_configured_users
        )
        return [
            RosterMember(
                user=users[member.user_pk],
                needs_accept=member.consent_mode == PartyConsentMode.ACCEPT_INVITES,
                can_enroll=(
                    not restricted
                    or self._member_has_access(session, users[member.user_pk])
                ),
            )
            for member in eligible
            if member.user_pk in users
        ]

    def _member_has_access(self, session: Session, user: UserDTO) -> bool:
        # On a restricted event a member's seat spends that member's own
        # allowance, so a member without slots cannot be seated by the leader.
        if not user.email:
            return False
        config = get_user_enrollment_config(
            event=EventDTO.model_validate(session.event),
            user_email=user.email,
            enrollment_config_repo=self.request.di.uow.enrollment_configs,
            ticket_api=self.request.di.ticket_api,
            check_interval_minutes=settings.MEMBERSHIP_API_CHECK_INTERVAL,
        )
        return bool(config and config.allowed_slots)

    @staticmethod
    def _validate_request(
        session: Session, enrollment_requests: list[EnrollmentRequest] | None = None
    ) -> EnrollmentConfig:
        event = session.event
        if enrollment_requests and all(
            req.choice == EnrollmentChoice.CANCEL for req in enrollment_requests
        ):
            if not (config := event.enrollment_configs.order_by("pk").first()):
                raise RedirectError(
                    reverse("web:chronology:event", kwargs={"slug": event.slug}),
                    error=_(
                        "No enrollment configuration is available for this session."
                    ),
                )
            return config

        if not (enrollment_config := event.get_most_liberal_config(session)):
            raise RedirectError(
                reverse("web:chronology:event", kwargs={"slug": session.event.slug}),
                error=_("No enrollment configuration is available for this session."),
            )

        # Note: UserDTO slot limits (max number of unique users that can be enrolled)
        # are handled in _process_enrollments(). Users can enroll in multiple sessions
        # without consuming additional slots. No need to block access here.

        return enrollment_config

    def _get_user_participation_data(
        self,
        session: Session,
        companions: list[ConnectedUserDTO],
        members: list[RosterMember],
    ) -> list[SessionUserParticipationData]:
        user_data: list[SessionUserParticipationData] = []

        all_users = [
            self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ),
            *companions,
            *(member.user for member in members),
        ]
        flags_by_pk = {
            member.user.pk: PartyMemberFlags(
                is_member=True,
                needs_accept=member.needs_accept,
                blocked=not member.can_enroll,
            )
            for member in members
        }

        # Bulk fetch all participations for the event and users
        user_participations = SessionParticipation.objects.filter(
            user_id__in=[u.pk for u in all_users], session__event=session.event
        ).select_related("session__agenda_item")

        # Group participations by user for efficient lookup
        participations_by_user: dict[int, list[SessionParticipation]] = defaultdict(
            list
        )
        for participation in user_participations:
            user_id = participation.user_id
            participations_by_user[user_id].append(participation)

        # Add enrollment status and time conflict info for each connected user
        for user in all_users:
            user_parts = participations_by_user.get(user.pk, [])
            membership = flags_by_pk.get(user.pk, PartyMemberFlags())
            offered = any(
                p.status == SessionParticipationStatus.OFFERED and p.session == session
                for p in user_parts
            )

            data = SessionUserParticipationData(
                user=user,
                user_enrolled=any(
                    p.status == SessionParticipationStatus.CONFIRMED
                    and p.session == session
                    for p in user_parts
                ),
                user_waiting=any(
                    p.status == SessionParticipationStatus.WAITING
                    and p.session == session
                    for p in user_parts
                ),
                # An OFFERED row on a needs-accept member of the viewer's own
                # party is a seat held for them; any other OFFERED row keeps
                # the generic pending-offer treatment.
                seat_held=offered and membership.needs_accept,
                offer_pending=offered and not membership.needs_accept,
                membership=membership,
                has_time_conflict=any(
                    session.agenda_item.overlaps_with(p.session.agenda_item)
                    for p in user_parts
                    if p.session != session
                ),
            )
            user_data.append(data)

        return user_data

    def post(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        session = _get_session_or_redirect(request, event_slug, session_id)
        selection = self._party_selection(session, request.POST.get("party"))
        members = self._party_members(session, selection.selected)
        roster = EnrollmentRoster(
            companions=tuple(selection.companions),
            members=tuple(members),
            guest_count=self._guest_count(session),
        )

        # Initialize form with POST data
        form_class = create_enrollment_form(
            session=session,
            current_user=self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ),
            roster=roster,
            enrollment_config_repo=request.di.uow.enrollment_configs,
            ticket_api=request.di.ticket_api,
        )
        form = form_class(data=request.POST)
        if not form.is_valid():
            # Add detailed form validation error messages without field name prefixes
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(self.request, str(error))

            # Check for specific enrollment restrictions and provide helpful messages
            enrollment_config = session.event.get_most_liberal_config(session)
            if enrollment_config and enrollment_config.restrict_to_configured_users:
                if not request.di.uow.active_users.read(
                    request.context.current_user_slug
                ).email:
                    messages.error(
                        self.request,
                        _("Email address is required for enrollment in this session."),
                    )
                else:
                    user_email = request.di.uow.active_users.read(
                        request.context.current_user_slug
                    ).email
                    event = session.event
                    if not get_user_enrollment_config(
                        event=EventDTO.model_validate(event),
                        user_email=user_email,
                        enrollment_config_repo=request.di.uow.enrollment_configs,
                        ticket_api=request.di.ticket_api,
                        check_interval_minutes=settings.MEMBERSHIP_API_CHECK_INTERVAL,
                    ):
                        messages.error(
                            self.request,
                            _(
                                "Enrollment access permission is required for this "
                                "session. Please contact the organizers to obtain "
                                "access."
                            ),
                        )
                    else:
                        messages.warning(
                            self.request,
                            _("Please review the enrollment options below."),
                        )
            else:
                messages.warning(
                    self.request, _("Please review the enrollment options below.")
                )

            # Re-render with form errors
            return TemplateResponse(
                request,
                "chronology/enroll_select.html",
                self._page_context(
                    session=session, selection=selection, form=form, members=members
                ),
            )

        # Only validate enrollment requirements when form is valid
        enrollment_requests = self._get_enrollment_requests(form, roster)
        enrollment_config = self._validate_request(session, enrollment_requests)

        self._manage_enrollments(
            form=form,
            session=session,
            enrollment_config=enrollment_config,
            roster=roster,
            party_pk=selection.selected.pk if selection.selected else None,
        )

        return redirect("web:chronology:event", slug=session.event.slug)

    def _get_enrollment_requests(
        self, form: forms.Form, roster: EnrollmentRoster
    ) -> list[EnrollmentRequest]:
        enrollment_requests = []
        household = [
            *(
                RosterMember(user=user)
                for user in (
                    self.request.di.uow.active_users.read(
                        self.request.context.current_user_slug
                    ),
                    *roster.companions,
                )
            ),
            *roster.members,
        ]
        member_pks = {member.user.pk for member in roster.members}
        for member in household:
            user = member.user
            # Skip inactive users
            if not user.is_active:
                continue
            user_field = f"user_{user.pk}"
            if form.cleaned_data.get(user_field):
                choice = form.cleaned_data[user_field]
                enrollment_requests.append(
                    EnrollmentRequest(
                        user=user,
                        choice=EnrollmentChoice(choice),
                        name=user.full_name,
                        is_party_member=user.pk in member_pks,
                        needs_accept=member.needs_accept,
                    )
                )
        return enrollment_requests

    def _process_enrollments(
        self,
        *,
        enrollment_requests: list[EnrollmentRequest],
        session: Session,
        enrollment_config: EnrollmentConfig,
        party_pk: int | None,
        guests_target: int | None = None,
    ) -> Enrollments:
        enrollments = Enrollments()

        session = Session.objects.select_for_update().get(id=session.id)
        # The guest delta is derived from the absolute target under the session
        # lock, so a replayed submit (double-click, refresh) is a no-op instead
        # of duplicating guests.
        guests_delta = 0
        if guests_target is not None:
            guests_delta = (
                guests_target
                - _guest_participations(
                    session, self.request.context.current_user_id
                ).count()
            )
        guest_seats_needed = max(guests_delta, 0)
        guest_seats_freed = max(-guests_delta, 0)
        if self._is_capacity_invalid(
            enrollment_requests,
            session,
            enrollment_config,
            guest_seats_needed=guest_seats_needed,
            guest_seats_freed=guest_seats_freed,
        ):
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"event_slug": session.event.slug, "session_id": session.id},
                )
            )

        participations = SessionParticipation.objects.filter(session=session).order_by(
            "creation_time"
        )

        # Players the presenter shadowbanned must not be seated — even when an
        # unbanned manager tries to enroll a banned connected sub-user.
        shadowbanned_ids = (
            self.request.services.shadowban.banned_user_ids(session.presenter_id)
            if session.presenter_id
            else set()
        )

        # Cancellations first: a seat freed in this batch must be available to a
        # connected user enrolling in the same submit (e.g. swapping a seat on a
        # full session).
        ordered_requests = sorted(
            enrollment_requests, key=lambda req: 0 if req.choice == "cancel" else 1
        )

        for req in ordered_requests:
            if req.choice == "cancel":
                self._handle_cancellation(req, participations, enrollments)
            else:
                self._check_and_create_enrollment(
                    req=req,
                    session=session,
                    enrollments=enrollments,
                    shadowbanned_ids=shadowbanned_ids,
                    party_pk=party_pk,
                )
        if guest_seats_needed or guest_seats_freed:
            self._adjust_guests(
                session=session,
                add=guest_seats_needed,
                remove=guest_seats_freed,
                party_pk=party_pk,
                enrollments=enrollments,
            )

        self._hold_member_seats(session, enrollments, party_pk)
        return enrollments

    @staticmethod
    def _handle_cancellation(
        req: EnrollmentRequest,
        participations: Iterable[SessionParticipation],
        enrollments: Enrollments,
    ) -> None:
        # A racing request may have already deleted the row (the form would
        # otherwise reject "cancel"); skip gracefully instead of raising.
        existing_participation = next(
            (p for p in participations if p.user.id == req.user.pk), None
        )
        if existing_participation is None:
            enrollments.skipped_users.append(
                _("%(name)s (no enrollment to cancel)") % {"name": req.name}
            )
            return

        # A freed confirmed (or held offered) seat triggers waiting-list
        # promotion after the transaction commits, via the service.
        if existing_participation.status in OCCUPYING_PARTICIPATION_STATUSES:
            enrollments.freed_seat = True
        existing_participation.delete()
        enrollments.cancelled_users.append(req.name)

    @staticmethod
    def _check_and_create_enrollment(
        *,
        req: EnrollmentRequest,
        session: Session,
        enrollments: Enrollments,
        shadowbanned_ids: set[int],
        party_pk: int | None,
    ) -> None:
        # Check if user is the session presenter
        if session.presenter_id and req.user.pk == session.presenter_id:
            enrollments.skipped_users.append(
                _("%(name)s (session host)") % {"name": req.name}
            )
            return

        # Shadowban: skip without revealing the ban (neutral reason).
        if req.user.pk in shadowbanned_ids:
            enrollments.skipped_users.append(
                _("%(name)s (not available)") % {"name": req.name}
            )
            return

        # Check for time conflicts for confirmed enrollment
        if req.choice == "enroll" and Session.objects.has_conflicts(session, req.user):
            enrollments.skipped_users.append(
                _("%(name)s (time conflict)") % {"name": req.name}
            )
            return

        # Use get_or_create to prevent duplicate enrollments in race conditions
        participation = SessionParticipation.objects.filter(
            session=session, user_id=req.user.pk
        ).first()
        is_fresh_signup = participation is None

        if req.needs_accept:
            # An ACCEPT_INVITES member is never seated directly: their seat is
            # held by the promotion service at the end of this batch, still
            # inside its transaction (see _hold_member_seats).
            if participation is not None:
                enrollments.skipped_users.append(
                    _("%(name)s (manages their own enrollment)") % {"name": req.name}
                )
                return
            enrollments.party_notices.held_seats.append(req.user)
            enrollments.signed_up_users.append((req.user.pk, req.name))
            return

        if not participation:
            participation = SessionParticipation(session=session, user_id=req.user.pk)

        participation.status = _status_by_choice[req.choice]
        # The latest submit's grouping intent wins: this seat promotes with the
        # party it was (re-)enrolled through.
        participation.party_id = party_pk
        participation.save()

        if req.is_party_member and is_fresh_signup:
            enrollments.party_notices.enrolled_members.append(req.user)

        enrollments.users_by_status[_status_by_choice[req.choice]].append(req.name)
        # Only a brand-new participation is a "signup" worth warning a banner
        # about — re-confirming or status changes must not re-alert.
        if is_fresh_signup:
            enrollments.signed_up_users.append((req.user.pk, req.name))

    def _hold_member_seats(
        self, session: Session, enrollments: Enrollments, party_pk: int | None
    ) -> None:
        # The promotion service owns the hold (OFFERED row + claim token +
        # expiry timer + notification); the batch transaction wraps it so the
        # seats stay consistent with the capacity check above.
        if not enrollments.party_notices.held_seats:
            return
        actor_name = self._actor_name()
        for member in enrollments.party_notices.held_seats:
            self.request.services.waitlist_promotion.hold_seat(
                hold=SeatHoldRequest(
                    session_id=session.pk,
                    session_title=session.title,
                    user_id=member.pk,
                    user_email=member.email,
                    party_id=party_pk,
                    actor_name=actor_name,
                )
            )

    def _actor_name(self) -> str:
        return self.request.di.uow.active_users.read(
            self.request.context.current_user_slug
        ).full_name

    def _notify_party_members(self, session: Session, enrollments: Enrollments) -> None:
        if not enrollments.party_notices.enrolled_members:
            return
        actor_name = self._actor_name()
        for member in enrollments.party_notices.enrolled_members:
            self.request.services.parties.announce_member_enrolled(
                PartyEnrolledNotification(
                    recipient_user_id=member.pk,
                    recipient_email=member.email,
                    actor_name=actor_name,
                    session_id=session.pk,
                    session_title=session.title,
                    event_slug=session.event.slug,
                )
            )

    def _send_message(self, enrollments: Enrollments) -> None:
        for users, message in (
            (
                enrollments.users_by_status[SessionParticipationStatus.CONFIRMED],
                _("Enrolled: {}"),
            ),
            (
                enrollments.users_by_status[SessionParticipationStatus.WAITING],
                _("Added to waiting list: {}"),
            ),
            (
                [held.full_name for held in enrollments.party_notices.held_seats],
                _("Seat held (awaiting their approval): {}"),
            ),
            (enrollments.cancelled_users, _("Cancelled: {}")),
            (
                enrollments.skipped_users,
                _("Skipped (already enrolled or conflicts): {}"),
            ),
        ):
            if users:
                messages.success(self.request, message.format(", ".join(users)))
        if enrollments.guest_total is not None:
            messages.success(
                self.request, _("Guests you bring: {}").format(enrollments.guest_total)
            )

    def _is_capacity_invalid(
        self,
        enrollment_requests: list[EnrollmentRequest],
        session: Session,
        enrollment_config: EnrollmentConfig,
        *,
        guest_seats_needed: int = 0,
        guest_seats_freed: int = 0,
    ) -> bool:
        enroll_count = sum(1 for req in enrollment_requests if req.choice == "enroll")
        enroll_count += guest_seats_needed
        if enroll_count == 0:
            return False

        # A cancellation in the same batch frees its held seat (CONFIRMED or
        # OFFERED) — exactly the statuses get_available_slots already counts as
        # occupied — so credit it back before checking capacity.
        cancelling_user_ids = {
            req.user.pk for req in enrollment_requests if req.choice == "cancel"
        }
        freed_spots = guest_seats_freed
        if cancelling_user_ids:
            freed_spots += SessionParticipation.objects.filter(
                session=session,
                user_id__in=cancelling_user_ids,
                status__in=OCCUPYING_PARTICIPATION_STATUSES,
            ).count()

        available_spots = enrollment_config.get_available_slots(session) + freed_spots

        if enroll_count > available_spots:
            # Guests cannot wait on the list, so the generic "use the waiting
            # list" advice would be a dead end when guests caused the overflow.
            message = (
                _(
                    "Not enough spots available. {} spots requested, {} available. "
                    "Bring fewer guests or use the waiting list for account "
                    "holders."
                )
                if guest_seats_needed
                else _(
                    "Not enough spots available. {} spots requested, {} available. "
                    "Please use waiting list for some users."
                )
            )
            messages.error(
                self.request, str(message).format(enroll_count, available_spots)
            )
            return True

        return False

    def _manage_enrollments(
        self,
        *,
        form: forms.Form,
        session: Session,
        enrollment_config: EnrollmentConfig,
        roster: EnrollmentRoster,
        party_pk: int | None,
    ) -> None:
        enrollment_requests = self._get_enrollment_requests(form, roster)
        # An empty guests box means "leave unchanged" (the field is prefilled
        # with the current count, so this only happens when cleared on purpose).
        guests_target: int | None = (
            form.cleaned_data.get("guests") if roster.guest_count is not None else None
        )
        guests_changed = (
            guests_target is not None and guests_target != roster.guest_count
        )
        if enrollment_requests or guests_changed:
            with transaction.atomic():
                enrollments = self._process_enrollments(
                    enrollment_requests=enrollment_requests,
                    session=session,
                    enrollment_config=enrollment_config,
                    party_pk=party_pk,
                    guests_target=guests_target,
                )

            # T1: a freed seat promotes/offers the next waiter (who is notified
            # directly), instead of the canceller stealing the message.
            if enrollments.freed_seat:
                self.request.services.waitlist_promotion.fill_freed_seats(
                    session_id=session.id
                )

            # Warn the presenter (by email) if a shadowbanned player signed up.
            self.request.services.shadowban.notify_signups(
                session_id=session.id, signed_up=enrollments.signed_up_users
            )

            self._notify_party_members(session, enrollments)

            # Send message outside transaction
            self._send_message(enrollments)
        else:
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"event_slug": session.event.slug, "session_id": session.id},
                ),
                warning=(
                    # A submit whose only touched control is the (unchanged)
                    # guests field is not a selection mistake.
                    _("No changes.")
                    if guests_target is not None
                    else _("Please select at least one user to enroll.")
                ),
            )

    def _adjust_guests(
        self,
        *,
        session: Session,
        add: int,
        remove: int,
        party_pk: int | None,
        enrollments: Enrollments,
    ) -> None:
        # Runs inside the enrollment transaction, after the per-user requests,
        # with the session row locked.
        viewer_pk = self.request.context.current_user_id
        if add:
            self._create_guests(session=session, count=add, party_pk=party_pk)
        if remove:
            # Trim the most recent guests; their throwaway rows go with them.
            doomed = list(_guest_participations(session, viewer_pk))[-remove:]
            for participation in doomed:
                participation.user.delete()
            enrollments.freed_seat = True
        enrollments.guest_total = _guest_participations(session, viewer_pk).count()

    def _create_guests(
        self, *, session: Session, count: int, party_pk: int | None
    ) -> None:
        users = self.request.di.uow.anonymous_users
        viewer_name = self.request.di.uow.active_users.read(
            self.request.context.current_user_slug
        ).full_name
        for _i in range(count):
            user_data = build_anonymous_user(
                f"guest-{token_urlsafe(8).lower()}", name=f"{viewer_name} +1"
            )
            users.create(user_data)
            guest = users.read(user_data["slug"])
            SessionParticipation.objects.create(
                session=session,
                user_id=guest.pk,
                status=SessionParticipationStatus.CONFIRMED,
                party_id=party_pk,
                enrolled_by_id=self.request.context.current_user_id,
            )


class ProposalAcceptPageView(LoginRequiredMixin, View):
    @staticmethod
    def _get_session_and_event(
        request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> tuple[SessionDTO, EventDTO]:
        session_repository = request.di.uow.sessions
        try:
            session = session_repository.read(session_id)
        except NotFoundError as exception:
            raise RedirectError(
                reverse("web:index"), error=_("Session not found.")
            ) from exception

        event = session_repository.read_event(session.pk)

        if event.slug != event_slug:
            raise RedirectError(
                reverse("web:index"), error=_("Session not found.")
            ) from None

        if session.status != SessionStatus.PENDING:
            raise RedirectError(
                reverse("web:chronology:event", kwargs={"slug": event.slug}),
                warning=_("This proposal has already been accepted."),
            )

        service = AcceptProposalService(request.di.uow, context=request.context)
        if not service.can_accept_proposals():
            raise RedirectError(
                reverse("web:chronology:event", kwargs={"slug": event.slug}),
                error=_(
                    "You don't have permission to accept proposals for this event."
                ),
            )

        return session, event

    @staticmethod
    def _build_context(
        request: AuthenticatedRootRequest,
        session: SessionDTO,
        event: EventDTO,
        form: forms.Form,
    ) -> dict[str, Any]:
        session_repository = request.di.uow.sessions
        field_values = session_repository.read_field_values(session.pk)
        return {
            "session": session,
            "event": event,
            "presenter": session_repository.read_presenter(session.pk),
            "spaces": session_repository.read_spaces(session.pk),
            "time_slots": session_repository.read_time_slots(session.pk),
            "preferred_time_slot_ids": session_repository.read_preferred_time_slot_ids(
                session.pk
            ),
            "form": form,
            "field_values": field_values,
        }

    def get(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        session, event = self._get_session_and_event(request, event_slug, session_id)
        session_repository = request.di.uow.sessions

        self._check_spaces(session, session_repository)
        self._check_time_slots(session, session_repository)

        form_class = create_proposal_acceptance_form(event)
        form = form_class()

        return TemplateResponse(
            request,
            "chronology/accept_proposal.html",
            self._build_context(request, session, event, form),
        )

    def post(
        self, request: AuthenticatedRootRequest, event_slug: str, session_id: int
    ) -> HttpResponse:
        session, event = self._get_session_and_event(request, event_slug, session_id)

        form_class = create_proposal_acceptance_form(event)
        form = form_class(data=request.POST)
        if not form.is_valid():
            return TemplateResponse(
                request,
                "chronology/accept_proposal.html",
                self._build_context(request, session, event, form),
            )

        service = AcceptProposalService(request.di.uow, context=request.context)
        service.accept_session(
            session=session,
            space_id=form.cleaned_data["space"].id,
            time_slot_id=form.cleaned_data["time_slot"].id,
        )

        messages.success(
            self.request,
            _("Proposal '{}' has been accepted and added to the agenda.").format(
                session.title
            ),
        )
        return redirect("web:chronology:event", slug=event.slug)

    @staticmethod
    def _check_spaces(
        session: SessionDTO, session_repository: SessionRepositoryProtocol
    ) -> None:
        if not session_repository.read_spaces(session.pk):
            raise RedirectError(
                reverse(
                    "web:chronology:event",
                    kwargs={"slug": session_repository.read_event(session.pk).slug},
                ),
                error=_(
                    "No spaces configured for this event. Please create spaces first."
                ),
            )

    @staticmethod
    def _check_time_slots(
        session: SessionDTO, session_repository: SessionRepositoryProtocol
    ) -> None:
        if not session_repository.read_time_slots(session.pk):
            raise RedirectError(
                reverse(
                    "web:chronology:event",
                    kwargs={"slug": session_repository.read_event(session.pk).slug},
                ),
                error=_(
                    "No time slots configured for this event. "
                    "Please create time slots first."
                ),
            )
