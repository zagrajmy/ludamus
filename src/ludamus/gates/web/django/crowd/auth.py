from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus, urlencode, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.generic.base import RedirectView, TemplateView, View
from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from ludamus.adapters.oauth import oauth
from ludamus.pacts import RedirectError
from ludamus.pacts.crowd import ClaimOutcome, UserData

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.crowd import UserDTO

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 600  # 10 minutes

# A bare hostname: dot-separated DNS labels, no scheme, path, port, credentials,
# or fragment. Rejects the `evil.com#x.ROOT_DOMAIN` suffix-match bypass, where a
# browser would parse the host as `evil.com` once embedded in a URL.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)


def _is_safe_login_redirect(url: str, root_domain: str, *, require_https: bool) -> bool:
    host = urlparse(url).netloc
    allowed = {root_domain}
    if host and (host == root_domain or host.endswith(f".{root_domain}")):
        allowed.add(host)
    return url_has_allowed_host_and_scheme(
        url, allowed_hosts=allowed, require_https=require_https
    )


def _login_user(request: RootRequest, user_slug: str) -> None:
    django_login(request, get_user_model().objects.get(slug=user_slug))


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
        user = self._provision_user(userinfo)

        _login_user(self.request, user.slug)
        if self.request.session.get("anonymous_enrollment_active"):
            self.request.session.pop("anonymous_user_code", None)
            self.request.session.pop("anonymous_enrollment_active", None)
            self.request.session.pop("anonymous_event_id", None)
        if update_data := userinfo.to_update_data(user):
            user = self.request.services.crowd_auth.sync_identity(
                user_slug=user.slug, data=update_data
            )

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

    def _provision_user(self, userinfo: Auth0UserInfo) -> UserDTO:
        claim_token = self.request.session.pop("pending_claim_token", "")
        result = self.request.services.crowd_auth.provision_user(
            username=userinfo.username,
            create_data=userinfo.to_create_data(
                slug=slugify(userinfo.username), password=make_password(None)
            ),
            claim_token=claim_token,
        )
        if result.claim_outcome == ClaimOutcome.CONVERTED:
            messages.success(
                self.request, _("Profile claimed — it is now your own account.")
            )
        elif result.claim_outcome == ClaimOutcome.ALREADY_AUTHENTICATED:
            messages.info(
                self.request,
                _(
                    "You already have an account, so this profile can't be moved "
                    "into it. Ask the person who invited you to enroll you directly."
                ),
            )
        return result.user

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

        last_domain = self.request.services.sites.read_site(
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
    root_domain = request.services.sites.read_site(
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

        # Get the redirect_to parameter. url_has_allowed_host_and_scheme accepts
        # only same-host relative targets, closing the `//evil.com` and
        # backslash (`/\evil.com`) bypasses a hand-rolled prefix check would miss.
        if redirect_to := self.request.GET.get("redirect_to"):
            if url_has_allowed_host_and_scheme(
                redirect_to, allowed_hosts=None, require_https=self.request.is_secure()
            ):
                redirect_url = redirect_to
            else:
                messages.warning(self.request, _("Invalid redirect URL."))

        # Handle last_domain parameter for multi-site redirects. Reject anything
        # that is not a bare hostname before the suffix/allowlist checks, so a
        # value like `evil.com#x.ROOT_DOMAIN` cannot satisfy the suffix match.
        if last_domain := self.request.GET.get("last_domain"):
            if not _HOSTNAME_RE.match(last_domain):
                messages.warning(self.request, _("Invalid domain for redirect."))
                return redirect_url

            # Also allow subdomains of ROOT_DOMAIN if configured
            if (
                last_domain.endswith(f".{settings.ROOT_DOMAIN}")
                or last_domain == settings.ROOT_DOMAIN
            ):
                return f"{self.request.scheme}://{last_domain}{redirect_url}"

            # Check against explicitly allowed domains
            if self.request.services.crowd_auth.is_known_sphere_domain(last_domain):
                return f"{self.request.scheme}://{last_domain}{redirect_url}"

            messages.warning(self.request, _("Invalid domain for redirect."))

        return redirect_url
