from datetime import UTC, datetime
from http import HTTPStatus

from django.test import override_settings
from django.urls import reverse

from ludamus.pacts.event import LandingConventionDTO, LandingStatsDTO
from tests.integration.conftest import EventFactory, SessionFactory
from tests.integration.utils import assert_response
from tests.integration.web.landing_context import CONTACT_EMAIL


class TestAboutPage:
    URL = reverse("about")

    def test_renders_with_no_events_yet(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["about.html"],
            context_data={
                "stats": LandingStatsDTO(events=0, sessions=0),
                "conventions": [],
                "contact_email": CONTACT_EMAIL,
            },
        )

    def test_cites_live_counts_and_conventions(self, client, non_root_sphere):
        event = EventFactory(
            sphere=non_root_sphere,
            start_time=datetime.now(UTC),
            cover_image="events/cover.png",
        )
        SessionFactory(category__event=event)

        with override_settings(
            LANDING_CONVENTION_DOMAINS=(non_root_sphere.site.domain,)
        ):
            response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=["about.html"],
            context_data={
                "stats": LandingStatsDTO(events=1, sessions=1),
                "conventions": [
                    LandingConventionDTO(
                        name=non_root_sphere.name,
                        domain=non_root_sphere.site.domain,
                        event_slug=event.slug,
                        cover_image_url=event.cover_image.url,
                    )
                ],
                "contact_email": CONTACT_EMAIL,
            },
        )

    def test_convention_domain_redirects_to_the_root_copy(
        self, client, non_root_sphere, settings
    ):
        # One indexed copy: on a sphere's domain the page would render the
        # same text under the convention's name and chrome.
        response = client.get(self.URL, HTTP_HOST=non_root_sphere.site.domain)

        assert_response(
            response,
            HTTPStatus.MOVED_PERMANENTLY,
            url=f"http://{settings.ROOT_DOMAIN}/about/",
        )
