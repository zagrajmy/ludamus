"""The seat model that formal/enrollment proves, run against the real enroll view.

`formal/enrollment/seats.bend` proves that a session never seats more than its
limit, assuming each request reserves only what fits and writes all of it or
nothing. Hypothesis drives a household through the real enroll view (batches
of enrolls and cancels) and replays the same steps through the compiled model
(`seats.gen.mjs`, via `replay_seats.mjs` on Node). The seats taken must match
after every step; when the code drifts from the model, this fails and the
proof no longer speaks for the code.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from django.db import transaction
from django.urls import reverse
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ludamus.links.db.django.models import AgendaItem, SessionParticipation
from ludamus.pacts import OCCUPYING_PARTICIPATION_STATUSES
from tests.integration.conftest import SessionFactory, UserFactory, sponsor_user

_REPLAY = Path(__file__).parents[4] / "formal" / "enrollment" / "replay_seats.mjs"
_HOUSEHOLD = 4

steps = st.lists(
    st.one_of(
        st.tuples(
            st.just("enroll"), st.sets(st.integers(0, _HOUSEHOLD - 1), min_size=1)
        ),
        st.tuples(st.just("cancel"), st.integers(0, _HOUSEHOLD - 1)),
    ),
    max_size=6,
)


def _model_taken(limit: int, groups: list[list[dict[str, object]]]) -> list[int]:
    node = shutil.which("node")
    assert node, "the differential test runs the Bend model on Node"
    completed = subprocess.run(
        [node, str(_REPLAY)],
        input=json.dumps({"limit": limit, "groups": groups}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.usefixtures("enrollment_config")
@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(limit=st.integers(1, 4), plan=steps)
def test_real_enrollment_takes_the_seats_the_model_takes(
    limit, plan, active_user, authenticated_client, agenda_item, event
):
    real_taken: list[int] = []
    groups: list[list[dict[str, object]]] = []
    with transaction.atomic():
        household = [active_user] + [
            UserFactory(user_type="connected", manager=active_user)
            for _ in range(_HOUSEHOLD - 1)
        ]
        for member in household[1:]:
            sponsor_user(leader=active_user, member=member)
        target = SessionFactory(event=event, participants_limit=limit, min_age=0)
        AgendaItem.objects.create(
            session=target,
            space=agenda_item.space,
            start_time=agenda_item.start_time,
            end_time=agenda_item.end_time,
        )
        url = reverse(
            "web:chronology:session-enrollment",
            kwargs={"event_slug": event.slug, "session_id": target.pk},
        )

        def seated() -> set[int]:
            return set(
                SessionParticipation.objects.filter(
                    session=target, status__in=OCCUPYING_PARTICIPATION_STATUSES
                ).values_list("user_id", flat=True)
            )

        for kind, who in plan:
            if kind == "enroll":
                new = [
                    household[i] for i in sorted(who) if household[i].pk not in seated()
                ]
                if not new:
                    continue
                choices = {f"user_{m.pk}": "enroll" for m in new}
                ops = [{"$": "Check", "want": len(new)}, {"$": "Commit"}]
            else:
                member = household[who]
                if member.pk not in seated():
                    continue
                choices = {f"user_{member.pk}": "cancel"}
                ops = [{"$": "Free"}]
            authenticated_client.post(url, data=choices)
            groups.append(ops)
            real_taken.append(len(seated()))

        transaction.set_rollback(True)

    assert real_taken == _model_taken(limit, groups)
