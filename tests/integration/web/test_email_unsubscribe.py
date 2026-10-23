import re
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from django.core.management import call_command
from django.urls import reverse

from ludamus.links.db.django.models import SphereSubscription
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

_UNSUBSCRIBE_LINK = re.compile(r"Unsubscribe: https://testserver(/\S+)")
POSTAL_ADDRESS = "Zagrajmy, ul. Przykładowa 1, 00-001 Warszawa"


def _announce(sphere, mailoutbox, capture):
    start = datetime.now(UTC) + timedelta(days=30)
    EventFactory(
        sphere=sphere,
        start_time=start,
        end_time=start + timedelta(hours=8),
        publication_time=datetime.now(UTC) - timedelta(minutes=5),
        subscribers_announced_at=None,
    )
    with capture(execute=True):
        call_command("announce_published_events")
    return mailoutbox[0]


class TestAnnouncementEmailUnsubscribe:
    def test_email_carries_a_way_out_and_the_postal_address(
        self,
        settings,
        non_root_sphere,
        active_user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        settings.MAIL_POSTAL_ADDRESS = POSTAL_ADDRESS
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)

        mail = _announce(
            non_root_sphere, mailoutbox, django_capture_on_commit_callbacks
        )

        page_path = _UNSUBSCRIBE_LINK.search(mail.body).group(1)
        assert mail.body.rstrip().endswith(POSTAL_ADDRESS)
        assert mail.extra_headers == {
            "List-Unsubscribe": f"<https://testserver{page_path}do/unsubscribe>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

    def test_opening_the_link_keeps_the_subscription(
        self,
        client,
        non_root_sphere,
        active_user,
        mailoutbox,
        django_capture_on_commit_callbacks,
    ):
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        mail = _announce(
            non_root_sphere, mailoutbox, django_capture_on_commit_callbacks
        )
        page_path = _UNSUBSCRIBE_LINK.search(mail.body).group(1)
        token = page_path.split("/")[-2]

        response = client.get(page_path)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="dashboard/unsubscribe.html",
            context_data={
                "sphere_name": non_root_sphere.name,
                "token": token,
                "done": False,
            },
        )
        assert SphereSubscription.objects.filter(user=active_user).exists()

    def test_one_click_post_unsubscribes_without_login_or_csrf(
        self,
        non_root_sphere,
        active_user,
        mailoutbox,
        django_capture_on_commit_callbacks,
        client,
    ):
        client.handler.enforce_csrf_checks = True
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        mail = _announce(
            non_root_sphere, mailoutbox, django_capture_on_commit_callbacks
        )
        one_click = (
            mail.extra_headers["List-Unsubscribe"]
            .strip("<>")
            .removeprefix("https://testserver")
        )

        response = client.post(one_click, {"List-Unsubscribe": "One-Click"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="dashboard/unsubscribe.html",
            context_data={
                "sphere_name": non_root_sphere.name,
                "token": one_click.split("/")[3],
                "done": True,
            },
        )
        assert not SphereSubscription.objects.filter(user=active_user).exists()

    def test_forged_token_is_refused_without_side_effects(
        self, client, non_root_sphere, active_user
    ):
        SphereSubscription.objects.create(sphere=non_root_sphere, user=active_user)
        url = reverse("web:email-unsubscribe-confirm", kwargs={"token": "forged"})

        response = client.post(url)

        assert_response(
            response,
            HTTPStatus.NOT_FOUND,
            template_name="dashboard/unsubscribe.html",
            context_data={"sphere_name": "", "token": "forged", "done": True},
        )
        assert SphereSubscription.objects.filter(user=active_user).exists()
