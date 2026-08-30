"""Integration tests for the discount-rule settings tab."""

from decimal import Decimal
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import DiscountRule
from ludamus.pacts.discounts import DiscountMethod, DiscountRuleDTO
from tests.integration.conftest import EventFactory, SphereFactory
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_login_required,
    assert_response,
)
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
    settings_tab_urls,
)

HALF_OFF = Decimal("50.00")
FULL_OFF = Decimal("100.00")


def _list_url(event):
    return reverse("panel:event-discount-settings", kwargs={"slug": event.slug})


def _create_url(event):
    return reverse("panel:discount-rule-create", kwargs={"slug": event.slug})


def _edit_url(event, rule):
    return reverse(
        "panel:discount-rule-edit", kwargs={"slug": event.slug, "pk": rule.pk}
    )


def _delete_url(event, rule):
    return reverse(
        "panel:discount-rule-delete", kwargs={"slug": event.slug, "pk": rule.pk}
    )


def _post_data(**overrides):
    data = {
        "method": DiscountMethod.STARTED_HOURS.value,
        "quantity": "4",
        "percent": "50",
        "order": "0",
    }
    data.update(overrides)
    return data


def _rule(event, **overrides):
    data = {
        "event": event,
        "method": DiscountMethod.STARTED_HOURS.value,
        "quantity": 4,
        "percent": HALF_OFF,
        "order": 0,
    }
    data.update(overrides)
    return DiscountRule.objects.create(**data)


def _row(rule, *, method_label):
    return {"rule": DiscountRuleDTO.model_validate(rule), "method_label": method_label}


def _tab_context(event, **extra):
    return {
        **panel_context(event, active_nav="settings"),
        "active_tab": "discounts",
        "tab_urls": settings_tab_urls(event),
        **extra,
    }


class TestDiscountRulesList:
    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = _list_url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(_list_url(event))

        assert_not_a_manager(response)

    def test_get_redirects_when_event_not_found(self, panel_client):
        response = panel_client.get(
            reverse("panel:event-discount-settings", kwargs={"slug": "nonexistent"})
        )

        assert_event_not_found(response)

    def test_shows_empty_state_for_manager(self, panel_client, event):
        response = panel_client.get(_list_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discount-rules.html",
            context_data=_tab_context(event, rows=[]),
        )

    def test_lists_event_rules_in_matching_order(self, panel_client, event):
        second = _rule(event, quantity=2, percent=Decimal("25.00"), order=1)
        first = _rule(event, quantity=8, percent=FULL_OFF, order=0)
        # Another sphere, so the sidebar's event list stays a single event.
        _rule(EventFactory(sphere=SphereFactory(name="Other"), slug="other-event"))

        response = panel_client.get(_list_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discount-rules.html",
            context_data=_tab_context(
                event,
                rows=[
                    _row(first, method_label="Started hours"),
                    _row(second, method_label="Started hours"),
                ],
            ),
        )


class TestDiscountRuleCreate:
    def test_get_shows_an_empty_form(self, panel_client, event):
        response = panel_client.get(_create_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discount-rule-form.html",
            context_data=_tab_context(event, form=ANY, rule=None),
        )

    def test_post_creates_the_rule_and_redirects(self, panel_client, event):
        quantity = 4

        response = panel_client.post(_create_url(event), data=_post_data())

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Discount rule created.")],
            url=_list_url(event),
        )
        rule = DiscountRule.objects.get(event=event)
        assert (rule.method, rule.quantity, rule.percent) == (
            DiscountMethod.STARTED_HOURS.value,
            quantity,
            HALF_OFF,
        )

    def test_post_re_renders_a_percentage_over_one_hundred(self, panel_client, event):
        response = panel_client.post(_create_url(event), data=_post_data(percent="120"))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discount-rule-form.html",
            context_data=_tab_context(
                event,
                form=FormErrorsMatcher(
                    percent=["Ensure this value is less than or equal to 100."]
                ),
                rule=None,
            ),
        )
        assert not DiscountRule.objects.exists()


class TestDiscountRuleEdit:
    def test_get_shows_the_stored_rule(self, panel_client, event):
        rule = _rule(event)

        response = panel_client.get(_edit_url(event, rule))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discount-rule-form.html",
            context_data=_tab_context(
                event, form=ANY, rule=DiscountRuleDTO.model_validate(rule)
            ),
        )

    def test_post_saves_the_changed_rule(self, panel_client, event):
        rule = _rule(event)
        new_quantity = 6

        response = panel_client.post(
            _edit_url(event, rule),
            data=_post_data(quantity=str(new_quantity), percent="100"),
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Discount rule saved.")],
            url=_list_url(event),
        )
        rule.refresh_from_db()
        assert (rule.quantity, rule.percent) == (new_quantity, FULL_OFF)

    def test_post_re_renders_the_rule_beside_the_invalid_form(
        self, panel_client, event
    ):
        rule = _rule(event)

        response = panel_client.post(
            _edit_url(event, rule), data=_post_data(percent="120")
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/discount-rule-form.html",
            context_data=_tab_context(
                event,
                form=FormErrorsMatcher(
                    percent=["Ensure this value is less than or equal to 100."]
                ),
                rule=DiscountRuleDTO.model_validate(rule),
            ),
        )
        stored = DiscountRule.objects.get(pk=rule.pk)
        assert (stored.quantity, stored.percent) == (rule.quantity, rule.percent)

    def test_get_rejects_a_rule_from_another_event(self, panel_client, sphere, event):
        foreign = _rule(EventFactory(sphere=sphere, slug="other-event"))

        response = panel_client.get(_edit_url(event, foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount rule not found.")],
            url=_list_url(event),
        )

    def test_post_rejects_a_rule_from_another_sphere(self, panel_client, event):
        other_sphere = SphereFactory(name="Other")
        foreign = _rule(EventFactory(sphere=other_sphere, slug="foreign-event"))

        response = panel_client.post(_edit_url(event, foreign), data=_post_data())

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount rule not found.")],
            url=_list_url(event),
        )
        foreign.refresh_from_db()
        assert foreign.percent == HALF_OFF


class TestDiscountRuleDelete:
    def test_post_deletes_the_rule(self, panel_client, event):
        rule = _rule(event)

        response = panel_client.post(_delete_url(event, rule))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Discount rule deleted.")],
            url=_list_url(event),
        )
        assert not DiscountRule.objects.exists()

    def test_post_rejects_a_rule_from_another_event(self, panel_client, sphere, event):
        foreign = _rule(EventFactory(sphere=sphere, slug="other-event"))

        response = panel_client.post(_delete_url(event, foreign))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Discount rule not found.")],
            url=_list_url(event),
        )
        assert DiscountRule.objects.filter(pk=foreign.pk).exists()
