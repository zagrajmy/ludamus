import json
import logging
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum, auto
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urlencode, urlparse

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout as django_logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
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
    SessionData,
    SessionUserParticipationData,
    build_display_field_row,
)
from ludamus.adapters.web.django.safety_presentation import fake_full_card
from ludamus.gates.web.django.entities import (
    AuthenticatedRootRequest,
    RootRequest,
    UserInfo,
)
from ludamus.mills import (
    AcceptProposalService,
    AnonymousEnrollmentService,
    get_user_enrollment_config,
)
from ludamus.pacts import (
    OCCUPYING_PARTICIPATION_STATUSES,
    AgendaItemDTO,
    AreaDTO,
    EventDTO,
    EventListItemDTO,
    LocationData,
    NotFoundError,
    RedirectError,
    SessionDTO,
    SessionFieldValueDTO,
    SessionRepositoryProtocol,
    SessionStatus,
    SpaceDTO,
    SpherePage,
    UserData,
    UserDTO,
    VenueDTO,
)
from ludamus.pacts.crowd import ClaimOutcome

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
        token = self.request.session.pop("pending_claim_token", "")
        if not token:
            return None
        result = self.request.services.claims.redeem(
            token=token,
            username=userinfo.username,
            email=userinfo.email or "",
            avatar_url=userinfo.picture or "",
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
            if "email" in update_data and self.request.di.uow.active_users.email_exists(
                update_data["email"], exclude_slug=user.slug
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


EVENT_PLACEHOLDER_IMAGES = [
    "placeholder-images/01.jpg",  # meeples
    "placeholder-images/02.jpg",  # chess
    "placeholder-images/03.jpg",  # cards
    "placeholder-images/04.jpg",  # dice
    "placeholder-images/05.jpg",  # tabletop
    "placeholder-images/06.jpg",  # chess pieces
    "placeholder-images/07.jpg",  # board game
    "placeholder-images/08.jpg",  # retro arcade
    "placeholder-images/09.jpg",  # controller
    "placeholder-images/10.png",  # arcade
]


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
                item,
                cover_image_url=item.cover_image_url
                or staticfiles_storage.url(
                    EVENT_PLACEHOLDER_IMAGES[i % len(EVENT_PLACEHOLDER_IMAGES)]
                ),
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
    success_url = reverse_lazy("web:crowd:profile-connected-users")
    template_name = "crowd/user/connected.html"
    template_name_suffix = "_form"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        connected_users = [
            {
                "user": connected,
                "form": ConnectedUserForm(initial=connected.model_dump()),
            }
            for connected in self.request.di.uow.connected_users.read_all(
                self.request.context.current_user_slug
            )
        ]
        context["connected_users"] = connected_users
        context["max_connected_users"] = MAX_CONNECTED_USERS
        return context

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
    success_url = reverse_lazy("web:crowd:profile-connected-users")
    template_name = "crowd/user/connected.html"
    template_name_suffix = "_form"

    def get_object(self) -> UserDTO:
        return self.request.di.uow.connected_users.read(
            self.request.context.current_user_slug, self.kwargs["slug"]
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = {
            "user": self.get_object(),
            "object": self.get_object(),
            "max_connected_users": MAX_CONNECTED_USERS,
            "connected_users": [
                {
                    "user": connected,
                    "form": ConnectedUserForm(initial=connected.model_dump()),
                }
                for connected in self.request.di.uow.connected_users.read_all(
                    self.request.context.current_user_slug
                )
            ],
        }
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
    success_url = reverse_lazy("web:crowd:profile-connected-users")
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
            claim_url = request.build_absolute_uri(
                reverse("web:crowd:claim", kwargs={"token": token})
            )
            messages.success(
                request,
                _(
                    "Claim link ready. Share it with this person so they can take "
                    "over their profile: %(url)s"
                )
                % {"url": claim_url},
            )
        return redirect("web:crowd:profile-connected-users")


class ClaimPageView(View):
    # Landing page for a claim link. The recipient signs in via Auth0 and the
    # managed row becomes their own account.
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
        claimable = request.services.claims.read_claimable(token)
        if claimable is None:
            messages.error(
                request, _("This claim link is invalid or has already been used.")
            )
            return redirect("web:index")
        return TemplateResponse(
            request, "crowd/claim.html", {"claimable": claimable, "token": token}
        )

    @staticmethod
    def post(request: RootRequest, token: str) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect("web:index")
        if request.services.claims.read_claimable(token) is None:
            messages.error(
                request, _("This claim link is invalid or has already been used.")
            )
            return redirect("web:index")
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


class UserDiscordUsernameComponentView(View):
    """Return Discord username HTML fragment via htmx."""

    request: RootRequest

    @staticmethod
    def get(request: RootRequest, user_slug: str) -> HttpResponse:
        try:
            user = request.di.uow.active_users.read(user_slug)
        except NotFoundError:
            return HttpResponse(status=404)
        if user.discord_username:
            return TemplateResponse(
                request,
                "crowd/user/parts/discord_username.html",
                {"discord_username": user.discord_username},
            )
        return HttpResponse("")


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


class EventPageView(DetailView):  # type: ignore [type-arg]
    template_name = "chronology/event.html"
    model = Event
    context_object_name = "event"
    request: RootRequest

    def get_queryset(self) -> QuerySet[Event]:
        return (
            Event.objects
            .filter(sphere_id=self.request.context.current_sphere_id)
            .select_related("sphere")
            .prefetch_related(
                "venues__areas__spaces__agenda_items__session__field_values__field",
                "venues__areas__spaces__agenda_items__session__session_participations__user",
                "enrollment_configs",
            )
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        if not self.object.is_published and not _is_manager(self.request):
            raise Http404

        # Get all sessions for this event that are published
        event_sessions = (
            Session.objects
            .filter(agenda_item__space__area__venue__event=self.object)
            .select_related("presenter", "agenda_item__space", "sphere")
            .prefetch_related(
                "tags__category",
                "session_participations__user__manager",
                "session_participations__user__connected",
                "field_values__field",
                "agenda_item__space__area__venue__event__enrollment_configs",
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

        current_time = datetime.now(tz=UTC)
        ended_hour_data: dict[datetime, list[SessionData]] = defaultdict(list)
        current_hour_data: dict[datetime, list[SessionData]] = defaultdict(list)
        future_unavailable_hour_data: dict[datetime, list[SessionData]] = defaultdict(
            list
        )

        for session_data in sessions_data.values():
            session_end_time = session_data.agenda_item.end_time
            session_start_time = session_data.agenda_item.start_time
            hour_key = session_start_time
            # Check if session has ended
            if session_end_time <= current_time:
                ended_hour_data[hour_key].append(session_data)
            elif (
                not session_data.is_enrollment_available
                and session_start_time > current_time
            ):
                future_unavailable_hour_data[hour_key].append(session_data)
            else:
                # Current sessions (available for enrollment or in progress)
                current_hour_data[hour_key].append(session_data)

        context.update({
            "hour_data": hour_data,  # Keep original for backward compatibility
            "sessions": list(sessions_data.values()),
            "ended_hour_data": dict(ended_hour_data),
            "current_hour_data": dict(current_hour_data),
            "future_unavailable_hour_data": dict(future_unavailable_hour_data),
            "total_enrolled": sum(s.enrolled_count for s in sessions_data.values()),
            "user_enrolled_sessions": [
                s for s in sessions_data.values() if s.user_enrolled
            ],
            "user_enrolled_session_titles": [
                s.session.title for s in sessions_data.values() if s.user_enrolled
            ],
            "event_banned": event_banned,
        })

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
        anonymous_service = AnonymousEnrollmentService(
            self.request.di.uow.anonymous_users
        )

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
            user_id=anonymous_user.pk,
            session__agenda_item__space__area__venue__event=self.object,
        ).select_related("session")
        ctx["anonymous_user_enrollments"] = list(anonymous_enrollments)
        return ctx

    def _clear_anonymous_session(self) -> None:
        self.request.session.pop("anonymous_user_code", None)
        self.request.session.pop("anonymous_enrollment_active", None)
        self.request.session.pop("anonymous_event_id", None)
        self.request.session.pop("anonymous_site_id", None)

    def _get_pending_sessions_context(self) -> dict[str, Any]:
        if (
            not self.request.context.current_user_slug
            or self.request.context.current_user_id is None
        ):
            return {}

        is_sphere_manager = self.object.sphere.managers.filter(
            id=self.request.context.current_user_id
        ).exists()

        if (
            self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ).is_superuser
            or is_sphere_manager
        ):
            return {
                "pending_sessions": self.request.di.uow.sessions.read_pending_by_event(
                    self.object.pk
                )
            }

        return {
            "pending_sessions": (
                self.request.di.uow.sessions.read_pending_by_event_for_user(
                    self.object.pk, self.request.context.current_user_id
                )
            )
        }

    def _set_user_participations(
        self, sessions: dict[int, SessionData], event_sessions: QuerySet[Session]
    ) -> None:
        anonymous_service = AnonymousEnrollmentService(
            self.request.di.uow.anonymous_users
        )
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

                    sessions[session.id].has_any_enrollments |= bool(statuses)
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

                        sessions[session.id].has_any_enrollments = bool(statuses)
                        sessions[session.id].user_enrolled = (
                            SessionParticipationStatus.CONFIRMED in statuses
                        )
                        sessions[session.id].user_waiting = (
                            SessionParticipationStatus.WAITING in statuses
                        )

    def _get_hour_data(
        self,
        event_sessions: QuerySet[Session],
        shadowbanned_ids: frozenset[int] = frozenset(),
    ) -> dict[datetime, list[SessionData]]:
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
            area = getattr(
                session.agenda_item.space, "area", None
            )  # TODO(fancysnake): Fix after merging venues
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
                agenda_item=AgendaItemDTO.model_validate(session.agenda_item),
                session=SessionDTO.model_validate(session),
                presenter=presenter,
                field_values=_field_value_dtos_from_models(session.field_values.all()),
                is_enrollment_available=session.is_enrollment_available,
                is_full=session.is_full,
                loc=LocationData(
                    space=SpaceDTO.model_validate(session.agenda_item.space),
                    area=(  # TODO(fancysnake): Fix after merging venues
                        AreaDTO.model_validate(area) if area else None
                    ),
                    venue=(  # TODO(fancysnake): Fix after merging venues
                        VenueDTO.model_validate(area.venue) if area else None
                    ),
                ),
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

            session_start = session_data.agenda_item.start_time

            # Calculate if session is ongoing (has already started)
            session_data.is_ongoing = session_start <= current_time

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
        super().__init__()


def _get_session_or_redirect(
    request: AuthenticatedRootRequest, session_id: int
) -> Session:
    try:
        session = Session.objects.get(
            sphere_id=request.context.current_sphere_id, id=session_id
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
    event = session.agenda_item.space.area.venue.event
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

    def get(self, request: AuthenticatedRootRequest, session_id: int) -> HttpResponse:
        session = _get_session_or_redirect(request, session_id)

        context = {
            "session": session,
            "event": session.agenda_item.space.area.venue.event,
            "connected_users": self.request.di.uow.connected_users.read_all(
                self.request.context.current_user_slug
            ),
            "user_data": self._get_user_participation_data(session),
            # Frontload the decision: warn the viewer up top if players they
            # shadowbanned are already signed up to this session.
            "shadowban_warnings": request.services.shadowban.list_session_warnings(
                viewer_id=request.context.current_user_id, session_id=session.pk
            ),
            "form": create_enrollment_form(
                session=session,
                current_user=self.request.di.uow.active_users.read(
                    self.request.context.current_user_slug
                ),
                connected_users=self.request.di.uow.connected_users.read_all(
                    self.request.context.current_user_slug
                ),
                enrollment_config_repo=request.di.uow.enrollment_configs,
                ticket_api=request.di.ticket_api,
            )(),
        }

        return TemplateResponse(request, "chronology/enroll_select.html", context)

    @staticmethod
    def _validate_request(
        session: Session, enrollment_requests: list[EnrollmentRequest] | None = None
    ) -> EnrollmentConfig:
        event = session.agenda_item.space.area.venue.event
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
                reverse(
                    "web:chronology:event",
                    kwargs={"slug": session.agenda_item.space.area.venue.event.slug},
                ),
                error=_("No enrollment configuration is available for this session."),
            )

        # Note: UserDTO slot limits (max number of unique users that can be enrolled)
        # are handled in _process_enrollments(). Users can enroll in multiple sessions
        # without consuming additional slots. No need to block access here.

        return enrollment_config

    def _get_user_participation_data(
        self, session: Session
    ) -> list[SessionUserParticipationData]:
        user_data: list[SessionUserParticipationData] = []

        # Get all connected users with proper prefetching
        all_users = [
            self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ),
            *self.request.di.uow.connected_users.read_all(
                self.request.context.current_user_slug
            ),
        ]

        # Bulk fetch all participations for the event and users
        user_participations = SessionParticipation.objects.filter(
            user_id__in=[u.pk for u in all_users],
            session__agenda_item__space__area__venue__event=session.agenda_item.space.area.venue.event,
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
                has_time_conflict=any(
                    session.agenda_item.overlaps_with(p.session.agenda_item)
                    for p in user_parts
                    if p.session != session
                ),
            )
            user_data.append(data)

        return user_data

    def post(self, request: AuthenticatedRootRequest, session_id: int) -> HttpResponse:
        session = _get_session_or_redirect(request, session_id)

        # Initialize form with POST data
        form_class = create_enrollment_form(
            session=session,
            current_user=self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ),
            connected_users=self.request.di.uow.connected_users.read_all(
                self.request.context.current_user_slug
            ),
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
            enrollment_config = (
                session.agenda_item.space.area.venue.event.get_most_liberal_config(
                    session
                )
            )
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
                    event = session.agenda_item.space.area.venue.event
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
                {
                    "session": session,
                    "event": session.agenda_item.space.area.venue.event,
                    "connected_users": self.request.di.uow.connected_users.read_all(
                        self.request.context.current_user_slug
                    ),
                    "user_data": self._get_user_participation_data(session),
                    "shadowban_warnings": (
                        request.services.shadowban.list_session_warnings(
                            viewer_id=request.context.current_user_id,
                            session_id=session.pk,
                        )
                    ),
                    "form": form,
                },
            )

        # Only validate enrollment requirements when form is valid
        enrollment_requests = self._get_enrollment_requests(form)
        enrollment_config = self._validate_request(session, enrollment_requests)

        self._manage_enrollments(form, session, enrollment_config)

        return redirect(
            "web:chronology:event", slug=session.agenda_item.space.area.venue.event.slug
        )

    def _get_enrollment_requests(self, form: forms.Form) -> list[EnrollmentRequest]:
        enrollment_requests = []
        for user in (
            self.request.di.uow.active_users.read(
                self.request.context.current_user_slug
            ),
            *self.request.di.uow.connected_users.read_all(
                self.request.context.current_user_slug
            ),
        ):
            # Skip inactive users
            if not user.is_active:
                continue
            user_field = f"user_{user.pk}"
            if form.cleaned_data.get(user_field):
                choice = form.cleaned_data[user_field]
                enrollment_requests.append(
                    EnrollmentRequest(
                        user=user, choice=EnrollmentChoice(choice), name=user.full_name
                    )
                )
        return enrollment_requests

    def _process_enrollments(
        self,
        enrollment_requests: list[EnrollmentRequest],
        session: Session,
        enrollment_config: EnrollmentConfig,
    ) -> Enrollments:
        enrollments = Enrollments()

        session = Session.objects.select_for_update().get(id=session.id)
        if self._is_capacity_invalid(enrollment_requests, session, enrollment_config):
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"session_id": session.id},
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
                    req, session, enrollments, shadowbanned_ids
                )
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
                f"{req.name} ({_('no enrollment to cancel')!s})"
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
        req: EnrollmentRequest,
        session: Session,
        enrollments: Enrollments,
        shadowbanned_ids: set[int],
    ) -> None:
        # Check if user is the session presenter
        if session.presenter_id and req.user.pk == session.presenter_id:
            enrollments.skipped_users.append(f"{req.name} ({_('session host')!s})")
            return

        # Shadowban: skip without revealing the ban (neutral reason).
        if req.user.pk in shadowbanned_ids:
            enrollments.skipped_users.append(f"{req.name} ({_('not available')!s})")
            return

        # Check for time conflicts for confirmed enrollment
        if req.choice == "enroll" and Session.objects.has_conflicts(session, req.user):
            enrollments.skipped_users.append(f"{req.name} ({_('time conflict')!s})")
            return

        # Use get_or_create to prevent duplicate enrollments in race conditions
        participation = SessionParticipation.objects.filter(
            session=session, user_id=req.user.pk
        ).first()
        is_fresh_signup = participation is None

        if not participation:
            participation = SessionParticipation(session=session, user_id=req.user.pk)

        participation.status = _status_by_choice[req.choice]
        participation.save()

        enrollments.users_by_status[_status_by_choice[req.choice]].append(req.name)
        # Only a brand-new participation is a "signup" worth warning a banner
        # about — re-confirming or status changes must not re-alert.
        if is_fresh_signup:
            enrollments.signed_up_users.append((req.user.pk, req.name))

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
            (enrollments.cancelled_users, _("Cancelled: {}")),
            (
                enrollments.skipped_users,
                _("Skipped (already enrolled or conflicts): {}"),
            ),
        ):
            if users:
                messages.success(self.request, message.format(", ".join(users)))

    def _is_capacity_invalid(
        self,
        enrollment_requests: list[EnrollmentRequest],
        session: Session,
        enrollment_config: EnrollmentConfig,
    ) -> bool:
        enroll_count = sum(1 for req in enrollment_requests if req.choice == "enroll")
        if enroll_count == 0:
            return False

        # A cancellation in the same batch frees its held seat (CONFIRMED or
        # OFFERED) — exactly the statuses get_available_slots already counts as
        # occupied — so credit it back before checking capacity.
        cancelling_user_ids = {
            req.user.pk for req in enrollment_requests if req.choice == "cancel"
        }
        freed_spots = 0
        if cancelling_user_ids:
            freed_spots = SessionParticipation.objects.filter(
                session=session,
                user_id__in=cancelling_user_ids,
                status__in=OCCUPYING_PARTICIPATION_STATUSES,
            ).count()

        available_spots = enrollment_config.get_available_slots(session) + freed_spots

        if enroll_count > available_spots:
            messages.error(
                self.request,
                str(
                    _(
                        "Not enough spots available. {} spots requested, {} available. "
                        "Please use waiting list for some users."
                    )
                ).format(enroll_count, available_spots),
            )
            return True

        return False

    def _manage_enrollments(
        self, form: forms.Form, session: Session, enrollment_config: EnrollmentConfig
    ) -> None:
        if enrollment_requests := self._get_enrollment_requests(form):
            with transaction.atomic():
                enrollments = self._process_enrollments(
                    enrollment_requests, session, enrollment_config
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

            # Send message outside transaction
            self._send_message(enrollments)
        else:
            raise RedirectError(
                reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"session_id": session.id},
                ),
                warning=_("Please select at least one user to enroll."),
            )


class ProposalAcceptPageView(LoginRequiredMixin, View):
    @staticmethod
    def _get_session_and_event(
        request: AuthenticatedRootRequest, session_id: int
    ) -> tuple[SessionDTO, EventDTO]:
        session_repository = request.di.uow.sessions
        try:
            session = session_repository.read(session_id)
        except NotFoundError as exception:
            raise RedirectError(
                reverse("web:index"), error=_("Session not found.")
            ) from exception

        event = session_repository.read_event(session.pk)

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
            "spaces": session_repository.read_spaces(session.pk),
            "time_slots": session_repository.read_time_slots(session.pk),
            "preferred_time_slot_ids": session_repository.read_preferred_time_slot_ids(
                session.pk
            ),
            "form": form,
            "field_values": field_values,
        }

    def get(self, request: AuthenticatedRootRequest, session_id: int) -> HttpResponse:
        session, event = self._get_session_and_event(request, session_id)
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

    def post(self, request: AuthenticatedRootRequest, session_id: int) -> HttpResponse:
        session, event = self._get_session_and_event(request, session_id)

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
            slugifier=slugify,
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


class EventAnonymousActivateActionView(View):
    @staticmethod
    def get(request: RootRequest, event_slug: str) -> HttpResponse:
        # Redirect to event page if user is authenticated (not anonymous)
        if request.context.current_user_slug:
            return redirect("web:chronology:event", slug=event_slug)

        # Check if event exists and has anonymous enrollment enabled
        try:
            event = Event.objects.get(slug=event_slug)
        except Event.DoesNotExist:
            messages.error(request, _("Event not found."))
            return redirect("web:index")

        active_configs = event.get_active_enrollment_configs()

        if not any(
            config for config in active_configs if config.allow_anonymous_enrollment
        ):
            messages.error(
                request, _("Anonymous enrollment is not available for this event.")
            )
            return redirect("web:chronology:event", slug=event.slug)

        code = token_urlsafe(4).lower()
        # Create new anonymous UserDTO immediately
        user_repository = request.di.uow.anonymous_users
        service = AnonymousEnrollmentService(user_repository=user_repository)
        user = service.build_user(code)
        user_repository.create(user)

        # Set session flags - include site ID to prevent cross-site confusion
        request.session["anonymous_user_code"] = code
        request.session["anonymous_enrollment_active"] = True
        request.session["anonymous_event_id"] = event.id
        request.session["anonymous_site_id"] = request.context.current_site_id

        return redirect("web:chronology:event", slug=event.slug)


def _anonymous_event_redirect(request: RootRequest) -> HttpResponse:
    if (event_id := request.session.get("anonymous_event_id")) is not None:
        try:
            event = Event.objects.get(pk=event_id)
            return redirect("web:chronology:event", slug=event.slug)
        except Event.DoesNotExist:
            pass
    return redirect("web:index")


def _event_allows_anonymous_enrollment(event: Event, session: Session) -> bool:
    return any(
        config.allow_anonymous_enrollment and config.is_session_eligible(session)
        for config in event.get_active_enrollment_configs()
    )


def _validate_anonymous_session_event(
    request: RootRequest, session: Session, *, require_active_enrollment: bool = True
) -> Event | HttpResponse:
    try:
        event = session.agenda_item.space.area.venue.event
    except ObjectDoesNotExist:
        messages.error(
            request, _("No enrollment configuration is available for this session.")
        )
        return _anonymous_event_redirect(request)

    anonymous_event_id = request.session.get("anonymous_event_id")
    if anonymous_event_id is None or event.id != anonymous_event_id:
        messages.error(
            request, _("Anonymous enrollment is not available for this session.")
        )
        return _anonymous_event_redirect(request)

    if require_active_enrollment and not _event_allows_anonymous_enrollment(
        event, session
    ):
        messages.error(
            request, _("No enrollment configuration is available for this session.")
        )
        return redirect("web:chronology:event", slug=event.slug)

    return event


def _validate_anonymous_enrollment_request(
    request: RootRequest, session_id: int, *, require_active_enrollment: bool = True
) -> tuple[Session, UserDTO] | HttpResponse:
    if not request.session.get("anonymous_enrollment_active"):
        messages.error(request, _("Anonymous enrollment is not active."))
        return redirect("web:index")

    if request.session.get("anonymous_site_id") != request.context.current_site_id:
        messages.error(
            request, _("Anonymous enrollment session is not valid for this site.")
        )
        return redirect("web:index")

    try:
        session = Session.objects.get(
            id=session_id, sphere__site_id=request.context.current_site_id
        )
    except Session.DoesNotExist:
        messages.error(request, _("Session not found."))
        return redirect("web:index")

    event_or_redirect = _validate_anonymous_session_event(
        request, session, require_active_enrollment=require_active_enrollment
    )
    if isinstance(event_or_redirect, HttpResponse):
        return event_or_redirect

    if not (anonymous_user_code := request.session.get("anonymous_user_code")):
        messages.error(request, _("Anonymous session expired."))
        return redirect("web:index")

    service = AnonymousEnrollmentService(user_repository=request.di.uow.anonymous_users)
    try:
        anonymous_user = service.get_user_by_code(code=anonymous_user_code)
    except NotFoundError:
        messages.error(request, _("Anonymous user not found."))
        return redirect("web:index")

    return session, anonymous_user


def _cancel_anonymous_enrollment(
    request: RootRequest, session: Session, anonymous_user: UserDTO
) -> None:
    freed_seat = False
    with transaction.atomic():
        session = Session.objects.select_for_update().get(id=session.id)
        try:
            enrollment = SessionParticipation.objects.get(
                session=session, user_id=anonymous_user.pk
            )
        except SessionParticipation.DoesNotExist:
            messages.warning(request, _("No enrollment found to cancel."))
            return

        freed_seat = enrollment.status in OCCUPYING_PARTICIPATION_STATUSES
        enrollment.delete()
        messages.success(
            request,
            _("Successfully cancelled enrollment in session: %(title)s")
            % {"title": session.title},
        )

    # A freed confirmed (or held offered) seat promotes/offers the next waiter,
    # who is notified directly by the service after the mutation commits.
    if freed_seat:
        request.services.waitlist_promotion.fill_freed_seats(session_id=session.id)


def _enroll_anonymous_user(
    request: RootRequest, session: Session, anonymous_user: UserDTO, session_id: int
) -> HttpResponse | None:
    if Session.objects.has_conflicts(session, anonymous_user):
        messages.error(
            request,
            _(
                "Cannot enroll: You are already enrolled in another session "
                "that conflicts with this time slot."
            ),
        )
        return redirect(
            "web:chronology:session-enrollment-anonymous", session_id=session_id
        )

    with transaction.atomic():
        session = Session.objects.select_for_update().get(id=session.id)
        if session.is_full:
            SessionParticipation.objects.get_or_create(
                session=session,
                user_id=anonymous_user.pk,
                defaults={"status": SessionParticipationStatus.WAITING.value},
            )
            messages.success(
                request,
                _(
                    "Session is full. You have been added to the waiting list "
                    "for: %(title)s"
                )
                % {"title": session.title},
            )
        else:
            enrollment, created = SessionParticipation.objects.get_or_create(
                session=session,
                user_id=anonymous_user.pk,
                defaults={"status": SessionParticipationStatus.CONFIRMED.value},
            )
            if (
                not created
                and enrollment.status != SessionParticipationStatus.CONFIRMED.value
            ):
                enrollment.status = SessionParticipationStatus.CONFIRMED.value
                enrollment.save()
            messages.success(
                request,
                _("Successfully enrolled in session: %(title)s")
                % {"title": session.title},
            )

    return None


class SessionEnrollmentAnonymousPageView(View):
    @staticmethod
    def get(request: RootRequest, session_id: int) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect("web:chronology:session-enrollment", session_id=session_id)

        result = _validate_anonymous_enrollment_request(
            request, session_id, require_active_enrollment=False
        )
        if isinstance(result, HttpResponse):
            return result
        session, anonymous_user = result

        existing_enrollment = SessionParticipation.objects.filter(
            session=session, user_id=anonymous_user.pk
        ).first()
        event = session.agenda_item.space.area.venue.event
        if existing_enrollment is None and not _event_allows_anonymous_enrollment(
            event, session
        ):
            messages.error(
                request, _("No enrollment configuration is available for this session.")
            )
            return redirect("web:chronology:event", slug=event.slug)

        context = {
            "session": session,
            "event": event,
            "anonymous_user": anonymous_user,
            "anonymous_code": anonymous_user.slug.removeprefix("code_"),
            "needs_user_data": not anonymous_user.name,
            "existing_enrollment": existing_enrollment,
            "is_enrolled": existing_enrollment is not None,
        }

        return TemplateResponse(request, "chronology/anonymous_enroll.html", context)

    @staticmethod
    def post(request: RootRequest, session_id: int) -> HttpResponse:
        if request.context.current_user_slug:
            return redirect("web:chronology:session-enrollment", session_id=session_id)

        result = _validate_anonymous_enrollment_request(
            request,
            session_id,
            require_active_enrollment=request.POST.get("action", "enroll") != "cancel",
        )
        if isinstance(result, HttpResponse):
            return result
        session, anonymous_user = result

        if name := request.POST.get("name", "").strip():
            anonymous_user.name = name

        if not anonymous_user.name:
            messages.error(request, _("Name is required."))
            return redirect(
                "web:chronology:session-enrollment-anonymous", session_id=session_id
            )

        request.di.uow.anonymous_users.update(anonymous_user.slug, UserData(name=name))

        if request.POST.get("action", "enroll") == "cancel":
            _cancel_anonymous_enrollment(request, session, anonymous_user)
        elif early_redirect := _enroll_anonymous_user(
            request, session, anonymous_user, session_id
        ):
            return early_redirect

        return redirect(
            "web:chronology:event", slug=session.agenda_item.space.area.venue.event.slug
        )


class AnonymousLoadActionView(View):
    """Handle entering an anonymous code to load a previous session."""

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        # Only accessible to non-authenticated users
        if request.context.current_user_slug:
            return redirect("web:index")

        if not (code := request.POST.get("code", "").strip()):
            messages.error(request, _("Please enter a code."))
            # Try to redirect back to the referring event
            referer = request.META.get("HTTP_REFERER", "")
            if "event" in referer:
                return redirect(referer)
            return redirect("web:index")

        user_repository = request.di.uow.anonymous_users
        service = AnonymousEnrollmentService(user_repository=user_repository)
        # Look up user by code
        try:
            anonymous_user = service.get_user_by_code(code=code)
        except NotFoundError:
            messages.error(request, _("Invalid code. Please check and try again."))
            # Try to redirect back to the referring event
            referer = request.META.get("HTTP_REFERER", "")
            if "event" in referer:
                return redirect(referer)
            return redirect("web:index")

        # Get user's enrollments to find the event and site
        enrollments = SessionParticipation.objects.filter(
            user_id=anonymous_user.pk
        ).select_related(
            "session__agenda_item__space__area__venue__event", "session__sphere"
        )

        if not (first_enrollment := enrollments.first()):
            messages.warning(request, _("No enrollments found for this code."))
            return redirect("web:index")

        # Get the first enrollment to determine the event and site
        event = first_enrollment.session.agenda_item.space.area.venue.event
        site_id = first_enrollment.session.sphere.site_id

        # Load user into session with proper site association
        request.session["anonymous_user_code"] = code
        request.session["anonymous_enrollment_active"] = True
        request.session["anonymous_event_id"] = event.id
        request.session["anonymous_site_id"] = site_id

        messages.success(
            request, _("Code loaded successfully. You can now manage your enrollments.")
        )
        return redirect("web:chronology:event", slug=event.slug)


class AnonymousResetActionView(View):
    @staticmethod
    def get(request: HttpRequest) -> HttpResponse:
        event_id = request.session.get("anonymous_event_id")

        event = None
        if event_id:
            event = Event.objects.filter(id=event_id).first()

        # Clear current anonymous session data
        request.session.pop("anonymous_user_code", None)
        request.session.pop("anonymous_enrollment_active", None)
        request.session.pop("anonymous_event_id", None)
        request.session.pop("anonymous_site_id", None)

        if event:
            # Create new anonymous session (which generates new code)
            return redirect(
                "web:chronology:event-anonymous-activate", event_slug=event.slug
            )
        return redirect("web:index")
