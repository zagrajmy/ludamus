"""Integration tests for the panel creator-discount pages."""

from decimal import Decimal
from http import HTTPStatus
from unittest.mock import ANY, MagicMock, patch

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Connection, Discount, Facilitator
from ludamus.links.db.django.repositories import ConnectionsRepository
from ludamus.pacts import (
    EventDTO,
    FacilitatorDTO,
    FacilitatorListItemDTO,
    NotFoundError,
)
from ludamus.pacts.discounts import DiscountDTO
from tests.integration.conftest import EventFactory, SphereFactory
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


SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/target-sheet/edit#gid=0"


def _google_write_session(*, write_ok=True, write_status=200, write_text=""):
    meta = MagicMock(
        ok=True, json=lambda: {"sheets": [{"properties": {"title": "Sheet1"}}]}
    )
    old_values = MagicMock(ok=True, json=lambda: {"values": []})

    def get(url: str, **_kwargs: object) -> MagicMock:
        if "/values/" in url:
            return old_values
        return meta

    session = MagicMock()
    session.get.side_effect = get
    session.put.return_value = MagicMock(
        ok=write_ok, status_code=write_status, text=write_text
    )
    return session


class TestDiscountExportPageView:
    @staticmethod
    def get_url(event):
        return reverse("panel:discount-export", kwargs={"slug": event.slug})

    def _post(self, client, event, connection, session):
        with (
            patch("ludamus.links.google_docs.Credentials.from_service_account_info"),
            patch("ludamus.links.google_docs.AuthorizedSession") as session_cls,
        ):
            session_cls.return_value = session
            return client.post(
                self.get_url(event),
                data={"connection": str(connection.pk), "spreadsheet": SPREADSHEET_URL},
            )

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
        url = reverse("panel:discount-export", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )

    def test_get_shows_form_when_a_connection_exists(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/export.html",
            context_data={**_base_context(event), "form": ANY, "has_connections": True},
            contains=[connection.display_name, "Export"],
        )

    def test_get_shows_empty_state_without_connections(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/export.html",
            context_data={
                **_base_context(event),
                "form": ANY,
                "has_connections": False,
            },
            contains="No connections yet.",
        )

    def test_post_exports_scoped_rows_and_redirects(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        facilitator = _make_facilitator(event, accreditation_type="guest")
        _make_discount(event, facilitator, value=Decimal("15.00"), note="VIP")
        other_event = EventFactory(sphere=sphere, slug="other-event")
        other_facilitator = _make_facilitator(
            other_event, display_name="Bob", slug="bob"
        )
        _make_discount(other_event, other_facilitator, value=Decimal("99.00"))
        session = _google_write_session()

        response = self._post(
            authenticated_client, event, connection_with_secret, session
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Accreditation sheet exported (1 creator).")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )
        session.post.assert_not_called()
        session.put.assert_called_once_with(
            "https://sheets.googleapis.com/v4/spreadsheets/target-sheet"
            "/values/%27Sheet1%27%21A1?valueInputOption=RAW",
            json={
                "values": [
                    [
                        "Creator",
                        "Accreditation type",
                        "Discount kind",
                        "Discount value",
                        "Note",
                    ],
                    ["Alice", "Guest", "Percent", "15.00", "VIP"],
                ]
            },
            timeout=30,
        )

    def test_post_shows_error_when_google_rejects_the_write(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event)
        session = _google_write_session(
            write_ok=False, write_status=403, write_text="no edit"
        )

        response = self._post(
            authenticated_client, event, connection_with_secret, session
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/export.html",
            messages=[
                (
                    messages.ERROR,
                    (
                        "Export failed: Spreadsheet write request failed "
                        "with 403: no edit"
                    ),
                )
            ],
            context_data={**_base_context(event), "form": ANY, "has_connections": True},
        )
        session.post.assert_not_called()

    def test_post_shows_error_when_connection_vanishes_mid_export(
        self, authenticated_client, active_user, sphere, event, connection_with_secret
    ):
        sphere.managers.add(active_user)
        _make_facilitator(event)
        session = _google_write_session()

        with patch.object(
            ConnectionsRepository, "read_secret", side_effect=NotFoundError
        ):
            response = self._post(
                authenticated_client, event, connection_with_secret, session
            )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/export.html",
            messages=[(messages.ERROR, "Connection not found.")],
            context_data={**_base_context(event), "form": ANY, "has_connections": True},
        )
        session.put.assert_not_called()

    def test_post_rejects_connection_from_another_sphere(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_sphere = SphereFactory(name="Other")
        foreign_connection = Connection.objects.create(
            sphere=other_sphere, display_name="Foreign"
        )
        session = _google_write_session()

        response = self._post(authenticated_client, event, foreign_connection, session)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/export.html",
            context_data={
                **_base_context(event),
                "form": ANY,
                "has_connections": False,
            },
        )
        assert response.context["form"].errors
        session.get.assert_not_called()

    def test_post_rejects_garbage_spreadsheet_value(
        self, authenticated_client, active_user, sphere, event, connection
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event),
            data={"connection": str(connection.pk), "spreadsheet": "not a sheet"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/export.html",
            context_data={**_base_context(event), "form": ANY, "has_connections": True},
        )
        assert response.context["form"].errors == {
            "spreadsheet": ["Enter a Google Sheets link or a spreadsheet ID."]
        }

    def test_post_redirects_when_event_not_found(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:discount-export", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url=reverse("panel:index"),
        )
