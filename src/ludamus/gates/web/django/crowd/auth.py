from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.generic.base import RedirectView, View

from ludamus.pacts import RedirectError
from ludamus.pacts.crowd import ClaimOutcome, IdentityRejectedError

if TYPE_CHECKING:
    from django.http import HttpResponse

    from ludamus.gates.web.django.entities import RootRequest
    from ludamus.pacts.crowd import LoginDTO

logger = logging.getLogger(__name__)

CACHE_TIMEOUT = 600  # 10 minutes
# The AuthKit session behind this login, needed to end it at logout.
SESSION_ID_KEY = "workos_session_id"
LOGOUT_TARGET_COOKIE = "logout_target"
LOGOUT_TARGET_MAX_AGE = 300

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


class LoginActionView(View):
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
        # AuthKit opens the sign-up screen instead of sign-in when asked to.
        wants_signup = request.GET.get("screen_hint") == "signup"
        hint = {"screen_hint": "signup"} if wants_signup else {}
        if request.get_host() != root_domain:
            if next_path:
                next_path = request.build_absolute_uri(next_path)
            login_url = (
                f"{request.scheme}://{root_domain}{reverse('web:crowd:auth:login')}"
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

        return HttpResponseRedirect(
            request.services.crowd_auth.login_url(
                redirect_uri=request.build_absolute_uri(
                    reverse("web:crowd:auth:login-callback")
                ),
                state=state_token,
                sign_up=wants_signup,
            )
        )


class LoginCallbackActionView(RedirectView):
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

        login = self._complete_login()
        user = login.user

        _login_user(self.request, user.slug)
        self.request.session[SESSION_ID_KEY] = login.session_id
        if self.request.session.get("anonymous_enrollment_active"):
            self.request.session.pop("anonymous_user_code", None)
            self.request.session.pop("anonymous_enrollment_active", None)
            self.request.session.pop("anonymous_event_id", None)

        if not (user.name or "").strip():
            messages.success(self.request, _("Please complete your profile."))
            profile_path = reverse("web:crowd:profile")
            onboarding = f"{profile_path}?{urlencode({'next': reverse('web:index')})}"
            if redirect_to:
                parsed = urlparse(redirect_to)
                return f"{parsed.scheme}://{parsed.netloc}{onboarding}"
            return self.request.build_absolute_uri(onboarding)

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

        # HACK: the parens are load-bearing. black's preview mode strips them
        # from a bare `except (A, B):` here and emits Python 2 syntax that
        # breaks the import, so the tuple must be bound with `as`.
        except (KeyError, ValueError) as exc:
            logger.warning("Invalid login state payload: %s", exc)
            messages.error(self.request, _("Invalid authentication state"))
            return None

        return redirect_to

    def _complete_login(self) -> LoginDTO:
        if error := self.request.GET.get("error"):
            # AuthKit reports a failed or cancelled sign-in on the callback.
            error_page = f"{reverse('web:auth-error')}?{urlencode({'error': error})}"
            raise RedirectError(error_page)
        claim_token = self.request.session.pop("pending_claim_token", "")
        try:
            login = self.request.services.crowd_auth.complete_login(
                code=self.request.GET.get("code", ""), claim_token=claim_token
            )
        except IdentityRejectedError as exc:
            raise RedirectError(
                reverse("web:index"), error=_("Authentication failed")
            ) from exc
        if login.claim_outcome == ClaimOutcome.CONVERTED:
            messages.success(
                self.request, _("Profile claimed — it is now your own account.")
            )
        elif login.claim_outcome == ClaimOutcome.ALREADY_AUTHENTICATED:
            messages.info(
                self.request,
                _(
                    "You already have an account, so this profile can't be moved "
                    "into it. Ask the person who invited you to enroll you directly."
                ),
            )
        logger.info("Login completed: user=%s", login.user.slug)
        return login


class LogoutActionView(View):
    @staticmethod
    def get(request: RootRequest) -> HttpResponse:
        redirect_to = reverse("web:index")
        session_id = request.session.get(SESSION_ID_KEY, "")
        django_logout(request)

        last_domain = request.services.sites.read(
            request.context.current_sphere_id
        ).site.domain
        root_domain = request.services.sites.read(
            request.context.root_sphere_id
        ).site.domain
        return_to = (
            f"{request.scheme}://{root_domain}"
            f"{reverse('web:crowd:auth:logout-redirect')}"
        )
        if not session_id:
            # No AuthKit session to end (it predates WorkOS), so skip the hop.
            query = urlencode({"last_domain": last_domain, "redirect_to": redirect_to})
            return HttpResponseRedirect(f"{return_to}?{query}")
        # NOTE: WorkOS refuses sign-out redirect URIs that carry a query in
        # production, so where to land afterwards rides in a cookie instead.
        response = HttpResponseRedirect(
            request.services.crowd_auth.logout_url(
                session_id=session_id, return_to=return_to
            )
        )
        response.set_cookie(
            LOGOUT_TARGET_COOKIE,
            signing.dumps(
                {"last_domain": last_domain, "redirect_to": redirect_to},
                salt=LOGOUT_TARGET_COOKIE,
            ),
            max_age=LOGOUT_TARGET_MAX_AGE,
            domain=settings.SESSION_COOKIE_DOMAIN,
            secure=request.is_secure(),
            httponly=True,
            samesite="Lax",
        )
        return response


class LogoutRedirectActionView(View):
    request: RootRequest

    def get(self, _request: RootRequest) -> HttpResponse:
        response = HttpResponseRedirect(self._redirect_url())
        response.delete_cookie(
            LOGOUT_TARGET_COOKIE, domain=settings.SESSION_COOKIE_DOMAIN
        )
        return response

    def _target(self) -> dict[str, str]:
        if "redirect_to" in self.request.GET or "last_domain" in self.request.GET:
            return {
                key: self.request.GET.get(key, "")
                for key in ("last_domain", "redirect_to")
            }
        try:
            target = signing.loads(
                self.request.COOKIES.get(LOGOUT_TARGET_COOKIE, ""),
                salt=LOGOUT_TARGET_COOKIE,
                max_age=LOGOUT_TARGET_MAX_AGE,
            )
        except signing.BadSignature:
            return {}
        if not isinstance(target, dict):
            return {}
        return {key: str(target.get(key, "")) for key in ("last_domain", "redirect_to")}

    def _redirect_url(self) -> str:
        redirect_url = reverse("web:index")
        target = self._target()

        # Get the redirect_to parameter. url_has_allowed_host_and_scheme accepts
        # only same-host relative targets, closing the `//evil.com` and
        # backslash (`/\evil.com`) bypasses a hand-rolled prefix check would miss.
        if redirect_to := target.get("redirect_to"):
            if url_has_allowed_host_and_scheme(
                redirect_to, allowed_hosts=None, require_https=self.request.is_secure()
            ):
                redirect_url = redirect_to
            else:
                messages.warning(self.request, _("Invalid redirect URL."))

        # Handle last_domain parameter for multi-site redirects. Reject anything
        # that is not a bare hostname before the suffix/allowlist checks, so a
        # value like `evil.com#x.ROOT_DOMAIN` cannot satisfy the suffix match.
        if last_domain := target.get("last_domain"):
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
