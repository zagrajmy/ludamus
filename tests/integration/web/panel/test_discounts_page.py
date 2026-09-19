"""Integration tests for the panel creator-discount pages."""

from datetime import timedelta
from decimal import Decimal
from http import HTTPStatus
from io import BytesIO
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import localdate
from odf import teletype
from odf.opendocument import load
from odf.table import Table, TableCell, TableRow

from ludamus.gates.web.django.chronology.panel.views.export import ODS_CONTENT_TYPE
from ludamus.gates.web.django.forms import ACCREDITATION_TYPE_LABELS
from ludamus.links.db.django.models import (
    AgendaItem,
    Discount,
    DiscountRule,
    Facilitator,
)
from ludamus.pacts import FacilitatorDTO, FacilitatorListItemDTO
from ludamus.pacts.discounts import DiscountDTO
from ludamus.pacts.submissions import AccreditationType
from tests.integration.conftest import EventFactory, SessionFactory, SpaceFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


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


_FILTER_CONTEXT = {
    "filter_accreditation": "",
    "accreditation_types": [
        (t.value, ACCREDITATION_TYPE_LABELS[t]) for t in AccreditationType
    ],
}


def _facilitator_dto(facilitator):
    return FacilitatorDTO(
        accreditation_type=facilitator.accreditation_type,
        display_name=facilitator.display_name,
        event_id=facilitator.event_id,
        pk=facilitator.pk,
        slug=facilitator.slug,
        user_id=None,
    )


class TestDiscountsPageView:
    @staticmethod
    def get_url(event):
        return reverse("panel:discounts", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:discounts", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_ok_for_sphere_manager(self, panel_client, event):
        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [],
                "rows": [],
            },
        )

    def test_list_shows_discount_and_accreditation(self, panel_client, event):
        facilitator = _make_facilitator(event, accreditation_type="guest")
        discount = _make_discount(
            event, facilitator, value=Decimal("15.00"), note="VIP"
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [],
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

    def test_list_filters_by_accreditation(self, panel_client, event):
        guest = _make_facilitator(event, accreditation_type="guest")
        _make_facilitator(event, display_name="Nobody", slug="nobody")

        response = panel_client.get(self.get_url(event), {"accreditation": "guest"})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [
                    {"facilitator": _facilitator_list_dto(guest), "form": ANY}
                ],
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(guest),
                        "accreditation_type_display": "Guest",
                        "discount": None,
                    }
                ],
                "filter_accreditation": "guest",
            },
        )

    def test_list_shows_assign_for_facilitator_without_discount(
        self, panel_client, event
    ):
        facilitator = _make_facilitator(event)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [
                    {"facilitator": _facilitator_list_dto(facilitator), "form": ANY}
                ],
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "None",
                        "discount": None,
                    }
                ],
            },
            contains=[
                "Assign",
                f'aria-controls="discount-assign-modal-{facilitator.pk}"',
                f'<dialog id="discount-assign-modal-{facilitator.pk}"',
                "Assign discount",
            ],
            not_contains="Remove",
        )

    def test_list_shows_amount_discount(self, panel_client, event):
        facilitator = _make_facilitator(event)
        discount = _make_discount(
            event, facilitator, kind="amount", value=Decimal("20.00")
        )

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [],
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

    def test_list_marks_a_discount_the_rules_assigned(self, panel_client, event):
        facilitator = _make_facilitator(event, accreditation_type="creator")
        discount = _make_discount(event, facilitator, from_rules=True)

        response = panel_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [],
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "Program creator",
                        "discount": DiscountDTO.model_validate(discount),
                    }
                ],
            },
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

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        facilitator = _make_facilitator(event)

        response = authenticated_client.get(self.get_url(event, facilitator))

        assert_not_a_manager(response)

    def test_get_redirects_to_table_modal_for_sphere_manager(self, panel_client, event):
        facilitator = _make_facilitator(event)

        response = panel_client.get(self.get_url(event, facilitator))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=(
                reverse("panel:discounts", kwargs={"slug": event.slug})
                + f"?assign={facilitator.pk}"
            ),
        )

    def test_get_redirects_when_facilitator_not_in_event(self, panel_client, event):
        missing_id = 999999
        url = reverse(
            "panel:discount-assign",
            kwargs={"slug": event.slug, "facilitator_id": missing_id},
        )

        response = panel_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_post_creates_discount_and_redirects(self, panel_client, event):
        facilitator = _make_facilitator(event)

        response = panel_client.post(
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

    def test_post_shows_errors_on_invalid_data(self, panel_client, event):
        facilitator = _make_facilitator(event)

        response = panel_client.post(
            self.get_url(event, facilitator), data={"kind": "percent", "value": "-5"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [
                    {"facilitator": _facilitator_list_dto(facilitator), "form": ANY}
                ],
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "None",
                        "discount": None,
                    }
                ],
            },
            contains=[
                f'<dialog id="discount-assign-modal-{facilitator.pk}"',
                "Value must be greater than zero.",
            ],
        )

    def test_post_rejects_zero_value(self, panel_client, event):
        facilitator = _make_facilitator(event)

        response = panel_client.post(
            self.get_url(event, facilitator), data={"kind": "percent", "value": "0"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [
                    {"facilitator": _facilitator_list_dto(facilitator), "form": ANY}
                ],
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "None",
                        "discount": None,
                    }
                ],
            },
        )
        assert not Discount.objects.filter(facilitator=facilitator).exists()

    def test_post_shows_error_on_invalid_kind(self, panel_client, event):
        facilitator = _make_facilitator(event)

        response = panel_client.post(
            self.get_url(event, facilitator), data={"kind": "bogus", "value": "5"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [
                    {"facilitator": _facilitator_list_dto(facilitator), "form": ANY}
                ],
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "None",
                        "discount": None,
                    }
                ],
            },
        )

    def test_post_shows_error_on_too_long_note(self, panel_client, event):
        facilitator = _make_facilitator(event)

        response = panel_client.post(
            self.get_url(event, facilitator),
            data={"kind": "percent", "value": "5", "note": "x" * 256},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/list.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                **_FILTER_CONTEXT,
                "assignments": [
                    {"facilitator": _facilitator_list_dto(facilitator), "form": ANY}
                ],
                "rows": [
                    {
                        "facilitator": _facilitator_list_dto(facilitator),
                        "accreditation_type_display": "None",
                        "discount": None,
                    }
                ],
            },
        )

    def test_post_redirects_when_facilitator_not_in_event(self, panel_client, event):
        url = reverse(
            "panel:discount-assign",
            kwargs={"slug": event.slug, "facilitator_id": 999999},
        )

        response = panel_client.post(url, data={"kind": "percent", "value": "5"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Facilitator not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:discount-assign", kwargs={"slug": "nonexistent", "facilitator_id": 1}
        )

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:discount-assign", kwargs={"slug": "nonexistent", "facilitator_id": 1}
        )

        response = panel_client.post(url, data={"kind": "percent", "value": "5"})

        assert_event_not_found(response)


class TestDiscountEditPageView:
    @staticmethod
    def get_url(event, discount):
        return reverse(
            "panel:discount-edit", kwargs={"slug": event.slug, "pk": discount.pk}
        )

    def test_get_ok_for_sphere_manager(self, panel_client, event):
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = panel_client.get(self.get_url(event, discount))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/edit.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
                "discount": DiscountDTO.model_validate(discount),
                "form": ANY,
            },
        )

    def test_post_updates_discount_and_redirects(self, panel_client, event):
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = panel_client.post(
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

    def test_post_404_for_discount_in_other_event(self, panel_client, sphere, event):
        other_event = EventFactory(sphere=sphere, slug="other-event")
        facilitator = _make_facilitator(other_event, slug="bob")
        discount = _make_discount(other_event, facilitator)

        url = reverse(
            "panel:discount-edit", kwargs={"slug": event.slug, "pk": discount.pk}
        )
        response = panel_client.post(url, data={"kind": "percent", "value": "30"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:discount-edit", kwargs={"slug": "nonexistent", "pk": 1})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:discount-edit", kwargs={"slug": "nonexistent", "pk": 1})

        response = panel_client.post(url, data={"kind": "percent", "value": "5"})

        assert_event_not_found(response)

    def test_get_404_for_discount_in_other_event(self, panel_client, sphere, event):
        other_event = EventFactory(sphere=sphere, slug="other-event")
        facilitator = _make_facilitator(other_event, slug="bob")
        discount = _make_discount(other_event, facilitator)

        url = reverse(
            "panel:discount-edit", kwargs={"slug": event.slug, "pk": discount.pk}
        )
        response = panel_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_post_shows_errors_on_invalid_data(self, panel_client, event):
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = panel_client.post(
            self.get_url(event, discount), data={"kind": "percent", "value": "-5"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discounts/edit.html",
            context_data={
                **panel_context(event, active_nav="discounts"),
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

        assert_not_a_manager(response)

    def test_post_soft_deletes_discount(self, panel_client, event):
        facilitator = _make_facilitator(event)
        discount = _make_discount(event, facilitator)

        response = panel_client.post(self.get_url(event, discount))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Discount removed successfully.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )
        assert not Discount.objects.filter(pk=discount.pk).exists()
        assert Discount.all_objects.filter(pk=discount.pk).exists()

    def test_post_404_for_missing_discount(self, panel_client, event):
        missing_pk = 999999
        url = reverse(
            "panel:discount-delete", kwargs={"slug": event.slug, "pk": missing_pk}
        )

        response = panel_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount not found.")],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:discount-delete", kwargs={"slug": "nonexistent", "pk": 1})

        response = panel_client.post(url)

        assert_event_not_found(response)


class TestDiscountSyncActionView:
    @staticmethod
    def get_url(event):
        return reverse("panel:discount-sync", kwargs={"slug": event.slug})

    @staticmethod
    def _schedule(event, facilitator, *, minutes=120):
        session = SessionFactory(event=event, category=None, status="accepted")
        session.facilitators.add(facilitator)
        AgendaItem.objects.create(
            session=session,
            space=SpaceFactory(event=event, capacity=10),
            start_time=event.start_time,
            end_time=event.start_time + timedelta(minutes=minutes),
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url)

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event))

        assert_not_a_manager(response)

    def test_post_redirects_when_event_not_found(self, panel_client):
        response = panel_client.post(
            reverse("panel:discount-sync", kwargs={"slug": "nonexistent"})
        )

        assert_event_not_found(response)

    def test_post_marks_scheduled_facilitator_and_assigns_the_rule_discount(
        self, panel_client, event
    ):
        facilitator = _make_facilitator(event)
        self._schedule(event, facilitator, minutes=110)
        DiscountRule.objects.create(
            event=event, method="started_hours", quantity=2, percent=Decimal("50.00")
        )

        response = panel_client.post(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Agenda applied — marked as creators: 1, unmarked: 0,"
                        " discounts assigned: 1, discounts withdrawn: 0."
                    ),
                )
            ],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )
        facilitator.refresh_from_db()
        assert facilitator.accreditation_type == "creator"
        discount = Discount.objects.get(facilitator=facilitator)
        assert (discount.value, discount.from_rules) == (Decimal("50.00"), True)

    def test_post_unmarks_creator_without_scheduled_program(self, panel_client, event):
        facilitator = _make_facilitator(event, accreditation_type="creator")
        _make_discount(event, facilitator, from_rules=True)

        response = panel_client.post(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    (
                        "Agenda applied — marked as creators: 0, unmarked: 1,"
                        " discounts assigned: 0, discounts withdrawn: 1."
                    ),
                )
            ],
            url=reverse("panel:discounts", kwargs={"slug": event.slug}),
        )
        facilitator.refresh_from_db()
        assert facilitator.accreditation_type == "none"
        assert not Discount.objects.filter(facilitator=facilitator).exists()

    def test_post_leaves_a_facilitator_of_another_event_alone(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere, slug="other-event")
        foreign = _make_facilitator(
            other_event, display_name="Bob", slug="bob", accreditation_type="creator"
        )

        panel_client.post(self.get_url(event))

        foreign.refresh_from_db()
        assert foreign.accreditation_type == "creator"


def _sheet(response):
    (table,) = load(BytesIO(response.content)).spreadsheet.getElementsByType(Table)
    return [
        [teletype.extractText(cell) for cell in row.getElementsByType(TableCell)]
        for row in table.getElementsByType(TableRow)
    ]


_SHEET_HEADERS = ["Display Name", "Discount kind", "Discount value", "Note"]


class TestDiscountExportPageView:
    @staticmethod
    def get_url(event):
        return reverse("panel:discount-export", kwargs={"slug": event.slug})

    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_when_event_not_found(self, panel_client):
        url = reverse("panel:discount-export", kwargs={"slug": "nonexistent"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_get_downloads_the_filtered_roster_with_its_discounts(
        self, panel_client, sphere, event
    ):
        guest = _make_facilitator(event, accreditation_type="guest")
        _make_discount(event, guest, value=Decimal("15.00"), note="VIP")
        _make_facilitator(event, display_name="Nobody", slug="nobody")
        other_event = EventFactory(sphere=sphere, slug="other-event")
        foreign = _make_facilitator(
            other_event, display_name="Bob", slug="bob", accreditation_type="guest"
        )
        _make_discount(other_event, foreign, value=Decimal("99.00"))

        response = panel_client.get(self.get_url(event), {"accreditation": "guest"})

        assert_response(response, HTTPStatus.OK)
        assert response["Content-Type"] == ODS_CONTENT_TYPE
        assert response["Content-Disposition"] == (
            f'attachment; filename="{event.slug}-accreditation-{localdate()}.ods"'
        )
        assert _sheet(response) == [
            _SHEET_HEADERS,
            ["Alice", "Percent", "15.00", "VIP"],
        ]

    def test_get_without_a_filter_lists_everyone(self, panel_client, event):
        _make_facilitator(event, accreditation_type="guest")
        _make_facilitator(event, display_name="Nobody", slug="nobody")

        response = panel_client.get(self.get_url(event))

        assert_response(response, HTTPStatus.OK)
        assert _sheet(response) == [
            _SHEET_HEADERS,
            ["Alice", "", "", ""],
            ["Nobody", "", "", ""],
        ]

    def test_get_with_columns_resolving_to_nothing_falls_back_to_the_sheet(
        self, panel_client, event
    ):
        _make_facilitator(event)

        response = panel_client.get(self.get_url(event), {"columns": ""})

        assert_response(response, HTTPStatus.OK)
        assert _sheet(response) == [_SHEET_HEADERS, ["Alice", "", "", ""]]

    def test_get_narrows_the_rows_by_the_lists_search(self, panel_client, event):
        _make_facilitator(event)
        _make_facilitator(event, display_name="Nobody", slug="nobody")

        response = panel_client.get(self.get_url(event), {"search": "Alice"})

        assert_response(response, HTTPStatus.OK)
        assert _sheet(response) == [_SHEET_HEADERS, ["Alice", "", "", ""]]
