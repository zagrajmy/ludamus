from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Notification, User
from ludamus.links.email_tokens import DjangoEmailTokenCodec
from ludamus.pacts.crowd import EmailTokenPayload, EmailVerificationAction
from tests.integration.utils import assert_response

THROTTLE_INFO = (
    "A verification email was sent a moment ago — try again in a few minutes."
)


def _link_url(token):
    return reverse("web:crowd:email-link", kwargs={"token": token})


def _token(*, act, uid, addr):
    return DjangoEmailTokenCodec.dumps(EmailTokenPayload(act=act, uid=uid, addr=addr))


def _confirm_token(user, addr=None):
    return _token(
        act=EmailVerificationAction.CONFIRM, uid=user.pk, addr=addr or user.email
    )


def _unverify(user):
    user.email_verified = False
    user.save()
    return user


class TestConfirmLink:
    def test_get_ok(self, client, active_user):
        _unverify(active_user)
        token = _confirm_token(active_user)

        response = client.get(_link_url(token))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"address": active_user.email, "token": token},
            template_name="crowd/email/confirm.html",
        )

    def test_get_garbled_token_renders_invalid_page(self, client, active_user):
        _ = active_user
        response = client.get(_link_url("garbage"))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"address_taken": False},
            template_name="crowd/email/link_invalid.html",
        )

    def test_post_verifies_current_address(self, client, active_user):
        _unverify(active_user)
        token = _confirm_token(active_user)

        response = client.post(_link_url(token))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.SUCCESS, "Your email address is verified.")],
        )
        user = User.objects.get(id=active_user.id)
        assert user.email_verified is True

    def test_post_promotes_pending_change(self, client, active_user):
        active_user.pending_email = "new@example.com"
        active_user.save()
        token = _confirm_token(active_user, addr="new@example.com")

        response = client.post(_link_url(token))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.SUCCESS, "Your new email address is now active.")],
        )
        user = User.objects.get(id=active_user.id)
        assert user.email == "new@example.com"
        assert user.email_verified is True
        assert not user.pending_email
        assert Notification.objects.filter(
            recipient_id=active_user.id, kind="email_change_completed"
        ).exists()

    def test_post_replayed_link_renders_invalid_page(self, client, active_user):
        active_user.email_verified = True
        active_user.save()
        token = _confirm_token(active_user)

        response = client.post(_link_url(token))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"address_taken": False},
            template_name="crowd/email/link_invalid.html",
        )

    def test_post_lost_race_renders_address_taken(
        self, client, active_user, complete_user_factory
    ):
        active_user.pending_email = "new@example.com"
        active_user.save()
        token = _confirm_token(active_user, addr="new@example.com")
        complete_user_factory(email="new@example.com")

        response = client.post(_link_url(token))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"address_taken": True},
            template_name="crowd/email/link_invalid.html",
        )
        user = User.objects.get(id=active_user.id)
        assert user.email != "new@example.com"
        assert not user.pending_email


class TestCancelLink:
    def test_get_ok(self, client, active_user):
        active_user.pending_email = "new@example.com"
        active_user.save()
        token = _token(
            act=EmailVerificationAction.CANCEL,
            uid=active_user.pk,
            addr="new@example.com",
        )

        response = client.get(_link_url(token))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"address": "new@example.com", "token": token},
            template_name="crowd/email/cancel.html",
        )

    def test_post_drops_pending_change(self, client, active_user):
        active_user.pending_email = "new@example.com"
        active_user.save()
        token = _token(
            act=EmailVerificationAction.CANCEL,
            uid=active_user.pk,
            addr="new@example.com",
        )

        response = client.post(_link_url(token))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.SUCCESS, "The email change has been cancelled.")],
        )
        user = User.objects.get(id=active_user.id)
        assert not user.pending_email

    def test_post_after_cancel_renders_invalid_page(self, client, active_user):
        token = _token(
            act=EmailVerificationAction.CANCEL,
            uid=active_user.pk,
            addr="new@example.com",
        )

        response = client.post(_link_url(token))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"address_taken": False},
            template_name="crowd/email/link_invalid.html",
        )


class TestEmailResendActionView:
    URL = reverse("web:crowd:email-resend")

    def test_post_sends_verification_mail(self, authenticated_client, active_user):
        _unverify(active_user)
        response = authenticated_client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:crowd:profile"),
            messages=[(messages.SUCCESS, "Verification email sent.")],
        )
        user = User.objects.get(id=active_user.id)
        assert user.email_verification_sent_at is not None
        assert Notification.objects.filter(
            recipient_id=active_user.id, kind="email_verification"
        ).exists()

    def test_post_throttles_repeat(self, authenticated_client, active_user):
        _unverify(active_user)
        # The first redirect is never rendered, so its flash is still queued
        # when the throttled response's messages are read.
        authenticated_client.post(self.URL)

        response = authenticated_client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:crowd:profile"),
            messages=[
                (messages.SUCCESS, "Verification email sent."),
                (messages.INFO, THROTTLE_INFO),
            ],
        )
        assert (
            Notification.objects.filter(
                recipient_id=active_user.id, kind="email_verification"
            ).count()
            == 1
        )

    def test_post_verified_address_needs_nothing(
        self, authenticated_client, active_user
    ):
        active_user.email_verified = True
        active_user.save()

        response = authenticated_client.post(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:crowd:profile"),
            messages=[(messages.INFO, "Your email address needs no verification.")],
        )

    def test_post_requires_login(self, client):
        response = client.post(self.URL)

        assert response.status_code == HTTPStatus.FOUND
