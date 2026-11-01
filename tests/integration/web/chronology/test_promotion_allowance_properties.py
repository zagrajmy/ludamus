"""Promotion and the enroll gate must agree on who a pass covers.

A pass covers one distinct person per event, however many sessions they sit
in (the enroll form says so in its own error). Hypothesis builds households
whose members already hold seats elsewhere in the event and checks, on the
real database, that `fill_freed_seats` seats a waiter exactly when the enroll
gate would let that waiter in.
"""

from datetime import timedelta

import pytest
from django.db import transaction
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ludamus.inits.services import Services
from ludamus.links.db.django.models import (
    SessionParticipation,
    SessionParticipationStatus,
    UserEnrollmentConfig,
)
from ludamus.pacts import EventDTO, VirtualEnrollmentConfig
from ludamus.pacts.crowd import UserDTO, UserType
from tests.integration.conftest import AgendaItemFactory, SessionFactory, UserFactory

households = st.fixed_dictionaries(
    {
        "allowed": st.integers(min_value=1, max_value=3),
        "companions": st.integers(min_value=0, max_value=2),
        # Indexes into the household: 0 is the owner, then each companion.
        "seated": st.sets(st.integers(min_value=0, max_value=2)),
        "waiter": st.integers(min_value=0, max_value=2),
    }
)


@pytest.mark.usefixtures("enrollment_config")
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=households)
def test_promotion_admits_exactly_whom_the_gate_admits(
    data, session, agenda_item, enrollment_config, event
):
    with transaction.atomic():
        owner = UserFactory(email="owner@example.com")
        household = [owner] + [
            UserFactory(user_type=UserType.CONNECTED, manager=owner)
            for _ in range(data["companions"])
        ]
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=owner.email,
            allowed_slots=data["allowed"],
        )
        elsewhere = SessionFactory(event=event, participants_limit=10)
        AgendaItemFactory(
            session=elsewhere,
            space=agenda_item.space,
            start_time=agenda_item.end_time + timedelta(hours=1),
            end_time=agenda_item.end_time + timedelta(hours=2),
        )
        for index in data["seated"]:
            if index < len(household):
                SessionParticipation.objects.create(
                    session=elsewhere,
                    user=household[index],
                    status=SessionParticipationStatus.CONFIRMED,
                )
        waiter = household[min(data["waiter"], len(household) - 1)]
        session.participants_limit = 1
        session.save()
        waiting = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        gate_admits = Services().enrollment.can_enroll_users(
            users=[UserDTO.model_validate(u) for u in household],
            event=EventDTO.model_validate(event),
            virtual_config=VirtualEnrollmentConfig(user_slots=data["allowed"]),
            users_to_enroll=[UserDTO.model_validate(waiter)],
        )
        promoted = (
            Services()
            .waitlist_promotion.fill_freed_seats(session_id=session.pk)
            .promoted
        )

        transaction.set_rollback(True)

    assert (promoted == [waiting.pk]) == gate_admits
