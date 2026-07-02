"""Integration tests for the panel creator-discount pages."""

from decimal import Decimal
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Discount, Facilitator
from ludamus.pacts import EventDTO, FacilitatorDTO, FacilitatorListItemDTO
from ludamus.pacts.discounts import DiscountDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_facilitator(event, **kwargs):
    defaults = {"display_name": "Alice", "slug": "alice", "user": None}
    defaults.update(kwargs)
    return Facilitator.objects.create(event=event, **defaults)


def _make_discount(event, facilitator, **kwargs):
    defaults = {"kind": "percent", "value": Decimal("10.00"), "note": ""}
    defaults.update(kwargs)
    return Discount.objects.create(event=event, facilitator=facilitator, **defaults)


def _facilitator_list_dto(facilitator):
    return FacilitatorListItemDTO(
        accreditation_type=facilitator.accreditation_type,
        display_name=facilitator.display_name,
        pk=facilitator.pk,
        session_count=0,
        slug=facilitator.slug,
        user_id=None,
    )


def _facilitator_dto(facilitator):
    return FacilitatorDTO(
        accreditation_type=facilitator.accreditation_type,
        display_name=facilitator.display_name,
        event_id=facilitator.event_id,
        pk=facilitator.pk,
        slug=facilitator.slug,
        user_id=None,
    )


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "discounts",
    }


class TestDiscountsPageView:
    @staticmethod
    def get_url(event):
        return reverse("panel:discounts", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:discounts", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={**_base_context(event), "rows": []},
        )

    def test_list_shows_discount_and_accreditation(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event, accreditation_type="guest")
        discount = _make_discount(
            event, facilitator, value=Decimal("15.00"), note="VIP"
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **_base_context(event),
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "Guest",
                        "discount": DiscountDTO.model_validate(discount),
                    }
                ],
            },
            contains=["Alice", "Guest", "15.00", "VIP", "Edit", "Remove"],
        )

    def test_list_shows_assign_for_facilitator_without_discount(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **_base_context(event),
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "None",
                        "discount": None,
                    }
                ],
            },
            contains="Assign",
            not_contains="Remove",
        )

    def test_list_shows_amount_discount(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        discount = _make_discount(
            event, facilitator, kind="amount", value=Decimal("20.00")
        )

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **_base_context(event),
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "None",
                        "discount": DiscountDTO.model_validate(discount),
                    }
                ],
            },
            contains="20.00",
        )


class TestDiscountCreatePageView:
    @staticmethod
    def get_url(event, facilitator):
        return reverse(
            "panel:discount-assign",
            kwargs={"slug": event.slug, "facilitator_id": facilitator.pk},
        )

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        facilitator = _make_facilitator(event)
        url = self.get_url(event, facilitator)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event, facilitator))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event, facilitator))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/create.html",
            context_data={
                **_base_context(event),
                "facilitator": _facilitator_dto(facilitator),
                "form": ANY,
            },
        )

    def test_get_redirects_when_facilitator_not_in_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        missing_id = 999999
        url = reverse(
            "panel:discount-assign",
            kwargs={"slug": event.slug, "facilitator_id": missing_id},
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_post_creates_discount_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.post(
            self.get_url(event, facilitator),
            data={"kind": "amount", "value": "25.50", "note": "VIP"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Discount assigned successfully.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )
        discount = Discount.objects.get(event=event, facilitator=facilitator)
        assert discount.kind == "amount"
        assert discount.value == Decimal("25.50")
        assert discount.note == "VIP"

    def test_post_shows_errors_on_invalid_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.post(
            self.get_url(event, facilitator), data={"kind": "percent", "value": "-5"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/create.html",
            context_data={
                **_base_context(event),
                "facilitator": _facilitator_dto(facilitator),
                "form": ANY,
            },
        )
        assert response.context["form"].errors

    def test_post_rejects_zero_value(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.post(
            self.get_url(event, facilitator), data={"kind": "percent", "value": "0"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/create.html",
            context_data={
                **_base_context(event),
                "facilitator": _facilitator_dto(facilitator),
                "form": ANY,
            },
        )
        assert response.context["form"].errors
        assert not Discount.objects.filter(facilitator=facilitator).exists()

    def test_post_shows_error_on_invalid_kind(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.post(
            self.get_url(event, facilitator), data={"kind": "bogus", "value": "5"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/create.html",
            context_data={
                **_base_context(event),
                "facilitator": _facilitator_dto(facilitator),
                "form": ANY,
            },
        )
        assert response.context["form"].errors

    def test_post_shows_error_on_too_long_note(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)

        response = authenticated_client.post(
            self.get_url(event, facilitator),
            data={"kind": "percent", "value": "5", "note": "x" * 256},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/create.html",
            context_data={
                **_base_context(event),
                "facilitator": _facilitator_dto(facilitator),
                "form": ANY,
            },
        )
        assert response.context["form"].errors

    def test_post_redirects_when_facilitator_not_in_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:discount-assign",
            kwargs={"slug": event.slug, "facilitator_id": 999999},
        )

        response = authenticated_client.post(
            url, data={"kind": "percent", "value": "5"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:discount-assign", kwargs={"slug": "nonexistent", "facilitator_id": 1}
        )

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse(
            "panel:discount-assign", kwargs={"slug": "nonexistent", "facilitator_id": 1}
        )

        response = authenticated_client.post(
            url, data={"kind": "percent", "value": "5"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )


class TestDiscountEditPageView:
    @staticmethod
    def get_url(event, discount):
        return reverse(
            "panel:discount-edit", kwargs={"slug": event.slug, "pk": discount.pk}
        )

    def test_get_ok_for_sphere_manager(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = authenticated_client.get(self.get_url(event, discount))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/edit.html",
            context_data={
                **_base_context(event),
                "discount": DiscountDTO.model_validate(discount),
                "form": ANY,
            },
        )

    def test_post_updates_discount_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = authenticated_client.post(
            self.get_url(event, discount),
            data={"kind": "percent", "value": "30", "note": "updated"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Discount updated successfully.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )
        discount.refresh_from_db()
        assert discount.value == Decimal(30)
        assert discount.note == "updated"

    def test_post_404_for_discount_in_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere, slug="other-event")
        facilitator = _make_facilitator(other_event, slug="bob")
        discount = _make_discount(other_event, facilitator)

        url = reverse(
            "panel:discount-edit", kwargs={"slug": event.slug, "pk": discount.pk}
        )
        response = authenticated_client.post(
            url, data={"kind": "percent", "value": "30"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_get_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:discount-edit", kwargs={"slug": "nonexistent", "pk": 1})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:discount-edit", kwargs={"slug": "nonexistent", "pk": 1})

        response = authenticated_client.post(
            url, data={"kind": "percent", "value": "5"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_404_for_discount_in_other_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere, slug="other-event")
        facilitator = _make_facilitator(other_event, slug="bob")
        discount = _make_discount(other_event, facilitator)

        url = reverse(
            "panel:discount-edit", kwargs={"slug": event.slug, "pk": discount.pk}
        )
        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_post_shows_errors_on_invalid_data(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = authenticated_client.post(
            self.get_url(event, discount), data={"kind": "percent", "value": "-5"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/edit.html",
            context_data={
                **_base_context(event),
                "discount": DiscountDTO.model_validate(discount),
                "form": ANY,
            },
        )
        assert response.context["form"].errors


class TestDiscountDeleteActionView:
    @staticmethod
    def get_url(event, discount):
        return reverse(
            "panel:discount-delete", kwargs={"slug": event.slug, "pk": discount.pk}
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = authenticated_client.post(self.get_url(event, discount))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_soft_deletes_discount(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = authenticated_client.post(self.get_url(event, discount))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Discount removed successfully.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )
        assert not Discount.objects.filter(pk=discount.pk).exists()
        assert Discount.all_objects.filter(pk=discount.pk).exists()

    def test_post_404_for_missing_discount(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        missing_pk = 999999
        url = reverse(
            "panel:discount-delete", kwargs={"slug": event.slug, "pk": missing_pk}
        )

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:discount-delete", kwargs={"slug": "nonexistent", "pk": 1})

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )
