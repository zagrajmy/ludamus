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
from django.core import signing
from django.core.cache import cache
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.generic.base import RedirectView, View
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic import ValidationError as PydanticValidationError

from ludamus.adapters.oauth import oauth
from ludamus.gates.web.django.crowd.forms import SignupAgeForm
from ludamus.pacts import RedirectError
from ludamus.pacts.crowd import (
    MAX_AVATAR_URL_LENGTH,
    MIN_ACCOUNT_AGE,
    AgeBand,
    ClaimOutcome,
    UserData,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.crowd import UserDTO

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 600  # 10 minutes
PENDING_SIGNUP_SESSION_KEY = "pending_signup"
PENDING_SIGNUP_MAX_AGE = timedelta(hours=1)
AGE_CONFIRMATION_SALT = "crowd.age-confirmation"

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


class Auth0LoginActionView(View):
    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        root_domain = request.services.sites.read(
            request.context.root_sphere_id
        ).site.domain
        next_path = request.GET.get("next")
        if next_path and not _is_safe_login_redirect(
            next_path, root_domain, require_https=request.is_secure()
        ):
            next_path = None
        # Auth0 opens the signup screen instead of login when asked to.
        wants_signup = request.GET.get("screen_hint") == "signup"
        hint = {"screen_hint": "signup"} if wants_signup else {}
        if request.get_host() != root_domain:
            if next_path:
                next_path = request.build_absolute_uri(next_path)
            login_url = (
                f"{request.scheme}://{root_domain}{reverse('web:crowd:auth0:login')}"
            )
            params = {"next": next_path, **hint} if next_path else hint
            url = f"{login_url}?{urlencode(params)}" if params else login_url
            raise RedirectError(url)

        # Generate a secure state token
        state_token = token_urlsafe(32)

        # Store state data in cache with 10 minute timeout
        state_data = {
            "redirect_to": next_path,
            "created_at": datetime.now(UTC).isoformat(),
        }
        cache_key = f"oauth_state:{state_token}"
        cache.set(cache_key, json.dumps(state_data), timeout=CACHE_TIMEOUT)

        return oauth.auth0.authorize_redirect(  # type: ignore [no-any-return]
            request,
            request.build_absolute_uri(reverse("web:crowd:auth0:login-callback")),
            state=state_token,
            **hint,
        )


class Auth0UserInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str = ""
    email_verified: bool = False
    family_name: str = ""
    given_name: str = ""
    name: str = ""
    nickname: str = ""
    picture: str = ""
    preferred_username: str = ""
    sub: str

    @field_validator("picture")
    @classmethod
    def _drop_overlong_picture(cls, value: str) -> str:
        # A URL truncated to the column width would be broken; better no avatar.
        if len(value) > MAX_AVATAR_URL_LENGTH:
            logger.warning(
                "Auth0 picture dropped: %s chars exceeds %s",
                len(value),
                MAX_AVATAR_URL_LENGTH,
            )
            return ""
        return value

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

    def to_create_data(
        self, *, slug: str, password: str, age_band: AgeBand
    ) -> UserData:
        return UserData(
            age_band=age_band,
            slug=slug,
            username=self.username,
            password=password,
            email=self.email or "",
            email_verified=bool(self.email and self.email_verified),
            avatar_url=self.picture or "",
            name=self.display_name or "",
        )

    def to_update_data(self) -> UserData:
        # A dumb projection of the claim; whether each value may be written
        # is decided by CrowdAuthService.sync_identity against stored state.
        data: UserData = {}
        if self.email:
            data["email"] = self.email
            data["email_verified"] = self.email_verified
        if self.picture:
            data["avatar_url"] = self.picture
        if display_name := self.display_name:
            data["name"] = display_name
        return data


def _provision_user(
    request: RootRequest,
    *,
    userinfo: Auth0UserInfo,
    age_band: AgeBand,
    claim_token: str,
) -> UserDTO:
    result = request.services.crowd_auth.provision_user(
        username=userinfo.username,
        create_data=userinfo.to_create_data(
            slug=slugify(userinfo.username),
            password=make_password(None),
            age_band=age_band,
        ),
        claim_token=claim_token,
    )
    if result.claim_outcome == ClaimOutcome.CONVERTED:
        messages.success(request, _("Profile claimed — it is now your own account."))
    elif result.claim_outcome == ClaimOutcome.ALREADY_AUTHENTICATED:
        messages.info(
            request,
            _(
                "You already have an account, so this profile can't be moved "
                "into it. Ask the person who invited you to enroll you directly."
            ),
        )
    if result.email_conflict:
        messages.warning(
            request,
            _(
                "That email address already belongs to another account, "
                "so it was not set. Set a different one in your profile."
            ),
        )
    return result.user


def _finish_login(
    request: RootRequest,
    *,
    userinfo: Auth0UserInfo,
    redirect_to: str,
    age_band: AgeBand,
    claim_token: str,
) -> str:
    """Provision and log in. `age_band` only reaches an account created here."""
    index_url = request.build_absolute_uri(reverse("web:index"))
    request.session.pop(PENDING_SIGNUP_SESSION_KEY, None)
    user = _provision_user(
        request, userinfo=userinfo, age_band=age_band, claim_token=claim_token
    )
    if not user.is_active:
        messages.error(
            request, _("This account is inactive. Contact support for help.")
        )
        return index_url

    _login_user(request, user.slug)
    if request.session.get("anonymous_enrollment_active"):
        request.session.pop("anonymous_user_code", None)
        request.session.pop("anonymous_enrollment_active", None)
        request.session.pop("anonymous_event_id", None)
    if update_data := userinfo.to_update_data():
        user = request.services.crowd_auth.sync_identity(
            user_slug=user.slug, data=update_data
        )

    if not (user.name or "").strip():
        messages.success(request, _("Please complete your profile."))
        profile_path = reverse("web:crowd:profile")
        onboarding = f"{profile_path}?{urlencode({'next': reverse('web:index')})}"
        if redirect_to:
            parsed = urlparse(redirect_to)
            return f"{parsed.scheme}://{parsed.netloc}{onboarding}"
        return request.build_absolute_uri(onboarding)

    return redirect_to or index_url


class Auth0LoginCallbackActionView(RedirectView):
    request: RootRequest

    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        default_redirect = super().get_redirect_url(*args, **kwargs)
        index_url = self.request.build_absolute_uri(reverse("web:index"))

        if (redirect_to := self._resolve_oauth_state(default_redirect)) is None:
            return index_url

        root_domain = self.request.services.sites.read(
            self.request.context.root_sphere_id
        ).site.domain
        if redirect_to and not _is_safe_login_redirect(
            redirect_to, root_domain, require_https=self.request.is_secure()
        ):
            redirect_to = ""

        if self.request.context.current_user_slug:
            return redirect_to or index_url

        userinfo = self._get_userinfo()
        claim_token = self.request.session.pop("pending_claim_token", "")
        if not self.request.services.crowd_auth.has_account(userinfo.username):
            self.request.session[PENDING_SIGNUP_SESSION_KEY] = _PendingSignup(
                userinfo=userinfo,
                claim_token=claim_token,
                redirect_to=redirect_to,
                started_at=datetime.now(UTC),
            ).model_dump(mode="json")
            return self.request.build_absolute_uri(
                reverse("web:crowd:auth0:signup-age")
            )
        return _finish_login(
            self.request,
            userinfo=userinfo,
            redirect_to=redirect_to,
            age_band=AgeBand.UNKNOWN,
            claim_token=claim_token,
        )

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

        # HACK: the parens are load-bearing. black's preview mode strips them
        # from a bare `except (A, B):` here and emits Python 2 syntax that
        # breaks the import, so the tuple must be bound with `as`.
        except (KeyError, ValueError) as exc:
            logger.warning("Invalid Auth0 state payload: %s", exc)
            messages.error(self.request, _("Invalid authentication state"))
            return None

        return redirect_to

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


def _valid_signup_confirmation(request: RootRequest, expected: str) -> bool:
    token = request.POST.get("confirmation_token", "")
    try:
        signing.loads(token, salt=AGE_CONFIRMATION_SALT, max_age=CACHE_TIMEOUT)
    except signing.BadSignature:
        return False
    return constant_time_compare(token, expected)


def sign_out_to_guardian_page(request: RootRequest) -> TemplateResponse:
    """Sign out and point an under-13 to the guardian-managed route."""
    # NOTE: logout flushes the session, pending signup and claim token included.
    django_logout(request)
    return TemplateResponse(
        request,
        "crowd/signup_guardian.html",
        {
            "min_age": MIN_ACCOUNT_AGE,
            "guardian_login_url": _auth0_logout_url(
                request, redirect_to=reverse("web:crowd:auth0:login")
            ),
        },
    )


class _PendingSignup(BaseModel):
    userinfo: Auth0UserInfo
    claim_token: str = ""
    redirect_to: str = ""
    confirmation_token: str = ""
    started_at: datetime


def _read_pending_signup(request: RootRequest) -> _PendingSignup | None:
    if request.context.current_user_slug:
        return None
    try:
        pending = _PendingSignup.model_validate(
            request.session.get(PENDING_SIGNUP_SESSION_KEY)
        )
    except PydanticValidationError:
        return None
    # The session outlives the sign-in by weeks; without a bound, anyone at
    # this browser later could finish the abandoned signup as its owner.
    if datetime.now(UTC) - pending.started_at > PENDING_SIGNUP_MAX_AGE:
        request.session.pop(PENDING_SIGNUP_SESSION_KEY, None)
        messages.info(request, _("Your sign-in timed out. Sign in again."))
        return None
    return pending


class Auth0SignupAgePageView(View):
    """A first Auth0 sign-in stops here before its account exists."""

    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        if (pending := _read_pending_signup(request)) is None:
            return redirect("web:index")
        token = signing.dumps({"nonce": token_urlsafe(16)}, salt=AGE_CONFIRMATION_SALT)
        request.session[PENDING_SIGNUP_SESSION_KEY] = pending.model_copy(
            update={"confirmation_token": token}
        ).model_dump(mode="json")
        return TemplateResponse(
            request,
            "crowd/signup_age.html",
            {"form": SignupAgeForm(initial={"confirmation_token": token})},
        )

    @staticmethod
    def post(request: RootRequest) -> HttpResponse:
        if (pending := _read_pending_signup(request)) is None:
            return redirect("web:index")
        if not _valid_signup_confirmation(request, pending.confirmation_token):
            messages.error(
                request,
                _("This age confirmation has expired. Choose your age range again."),
            )
            return redirect("web:crowd:auth0:signup-age")
        form = SignupAgeForm(request.POST)
        if not form.is_valid():
            return TemplateResponse(request, "crowd/signup_age.html", {"form": form})
        if (age_band := form.cleaned_data["age_band"]) is None:
            request.services.crowd_auth.reject_signup(
                username=pending.userinfo.username,
                slug=slugify(pending.userinfo.username),
                password=make_password(None),
            )
            logger.info("Independent signup declined: below minimum age")
            return sign_out_to_guardian_page(request)
        logger.info("Signup age range confirmed")
        destination = _finish_login(
            request,
            userinfo=pending.userinfo,
            redirect_to=pending.redirect_to,
            age_band=age_band,
            claim_token=pending.claim_token,
        )
        # NOTE: CSP form-action stops a form POST from redirecting to another
        # sphere's host, so a cross-host destination is reached from a page.
        if (host := urlparse(destination).netloc) and host != request.get_host():
            return TemplateResponse(
                request, "crowd/signup_continue.html", {"redirect_to": destination}
            )
        return redirect(destination)


class Auth0LogoutActionView(RedirectView):
    request: RootRequest

    def get_redirect_url(self, *args: Any, **kwargs: Any) -> str | None:
        redirect_to = super().get_redirect_url(*args, **kwargs)

        django_logout(self.request)

        last_domain = self.request.services.sites.read(
            self.request.context.current_sphere_id
        ).site.domain

        return _auth0_logout_url(
            self.request, last_domain=last_domain, redirect_to=redirect_to
        )


def _auth0_logout_url(
    request: RootRequest,
    *,
    last_domain: str | None = None,
    redirect_to: str | None = None,
) -> str:
    root_domain = request.services.sites.read(
        request.context.root_sphere_id
    ).site.domain
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
