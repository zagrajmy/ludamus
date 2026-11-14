"""Export Hypothesis-generated cases of the Django app's pure rules for the TS port.

Each fixture under packages/core/test/fixtures/differential holds the inputs
Hypothesis drew (fixed seed) and what the real Python returned for them, in
the camelCase shape the TypeScript schemas decode. The vitest replay runs
every case through the port and asserts the same answer.

Run from the repository root:

    .venv/bin/python experiment/evals/differential/export_cases.py

Rules that live inside IO-bearing classes (the promotion service, the enroll
view) are driven through their real methods with in-memory fakes standing in
for the ORM, the clock and the token source; nothing touches a database.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "experiment" / "packages" / "core" / "test" / "fixtures" / "differential"
SEED = 20261030
EXAMPLES = 300


def _load_env() -> None:
    for raw in (ROOT / ".env.e2e").read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env()
sys.path.insert(0, str(ROOT / "src"))

import logging

import django

django.setup()
logging.disable(logging.CRITICAL)

from django.http import QueryDict
from django.utils import translation
from hypothesis import HealthCheck, Phase, given, seed, settings
from hypothesis import strategies as st

from ludamus.adapters.web.django import views
from ludamus.adapters.web.django.forms import INCLUDE_VALUE, RosterMember
from ludamus.gates.web.django.dynamic_fields import (
    answered_value,
    build_dynamic_fields,
    dynamic_fields_form,
    fold_custom_answers,
    unfold_custom_answers,
)
from ludamus.links.db.django import models
from ludamus.mills import enrollment as enrollment_mills
from ludamus.mills import slugs
from ludamus.mills.enrollment_windows import (
    EnrollmentPolicy,
    restricts_everyone,
    viewer_access,
)
from ludamus.mills.field_values import merge_custom, split_stored
from ludamus.mills.timeslots import (
    MIDNIGHT,
    PROGRAMME_DAYS,
    DayTurnover,
    slot_windows_by_local_date,
)
from ludamus.pacts import durations
from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    OfferDTO,
    PromotionStateDTO,
    WaitingParticipantDTO,
    distinct_recipients,
)
from ludamus.pacts.fields import OrganizerFieldDTO, OrganizerFieldOptionDTO
from ludamus.pacts.legacy import (
    MembershipAPIError,
    PromotionMode,
    SessionParticipationStatus,
)
from ludamus.specs.enrollment import (
    is_valid_window_period,
    select_promotable_parties,
)
from ludamus.specs.proposal import carried_answers

translation.activate("en")

BASE = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
USERS = range(1, 7)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    utc = value.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def millis(value: timedelta) -> int:
    return int(value.total_seconds() * 1000)


def write(name: str, *, python: str, cases: list[dict[str, Any]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    body = ",\n".join(json.dumps(case, sort_keys=True) for case in cases)
    header = json.dumps({"function": name, "python": python, "seed": SEED})
    (OUT / f"{name}.json").write_text(
        header[:-1] + ', "cases": [\n' + body + "\n]}\n"
    )
    print(f"{name}: {len(cases)} cases")


def collect(
    name: str,
    *,
    python: str,
    strategy: st.SearchStrategy[Any],
    run: Any,
    examples: int = EXAMPLES,
) -> None:
    cases: dict[str, dict[str, Any]] = {}

    @seed(SEED)
    @settings(
        max_examples=examples,
        database=None,
        deadline=None,
        phases=[Phase.generate],
        suppress_health_check=list(HealthCheck),
    )
    @given(strategy)
    def gather(value: Any) -> None:
        case = run(value)
        cases.setdefault(json.dumps(case["input"], sort_keys=True), case)

    gather()
    write(name, python=python, cases=list(cases.values()))


def frozen_datetime(now: datetime) -> type[datetime]:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return now if tz is None else now.astimezone(tz)

    return Frozen


class FakeTransaction:
    @contextmanager
    def atomic(self):
        yield


# ---------------------------------------------------------------- promotion


@st.composite
def promotion_states(draw: st.DrawFn) -> PromotionStateDTO:
    user_ids = draw(st.lists(st.sampled_from(USERS), unique=True, max_size=6))
    values = [0, 1, 2, 3, UNLIMITED_SLOTS]
    slots = {user: draw(st.sampled_from(values)) for user in USERS}
    waiting = []
    for order, user_id in enumerate(user_ids):
        sponsor_id = draw(
            st.none() | st.sampled_from([u for u in USERS if u != user_id])
        )
        recipient = sponsor_id if sponsor_id is not None else user_id
        consistent = draw(st.sampled_from([True, True, True, False]))
        waiting.append(
            WaitingParticipantDTO(
                participation_id=order + 1,
                user_id=user_id,
                party_id=draw(st.none() | st.sampled_from([1, 2])),
                sponsor_id=sponsor_id,
                full_name=f"user-{user_id}",
                email=f"u{user_id}@example.com",
                creation_time=BASE + timedelta(minutes=order),
                has_conflict=draw(st.sampled_from([False, False, False, True])),
                owner_slots_remaining=(
                    slots[recipient] if consistent else draw(st.sampled_from(values))
                ),
                recipient_user_id=recipient,
            )
        )
    return PromotionStateDTO(
        session_id=1,
        session_title="S",
        event_slug="ev",
        start_time=BASE + timedelta(hours=draw(st.integers(0, 72))),
        promotion_mode=draw(st.sampled_from(list(PromotionMode))),
        offer_claim_window=timedelta(hours=draw(st.sampled_from([0, 1, 24, 48]))),
        presenter_id=draw(st.none() | st.sampled_from(USERS)),
        available_seats=draw(st.integers(0, 6) | st.integers(1, 6)),
        waiting=waiting,
        shadowbanned_user_ids=frozenset(
            draw(st.sets(st.sampled_from(USERS), max_size=2))
        ),
    )


def participant_json(p: WaitingParticipantDTO) -> dict[str, Any]:
    return {
        "participationId": p.participation_id,
        "userId": p.user_id,
        "partyId": p.party_id,
        "sponsorId": p.sponsor_id,
        "fullName": p.full_name,
        "email": p.email,
        "creationTime": iso(p.creation_time),
        "hasConflict": p.has_conflict,
        "ownerSlotsRemaining": p.owner_slots_remaining,
        "recipientUserId": p.recipient_user_id,
    }


def state_json(state: PromotionStateDTO) -> dict[str, Any]:
    return {
        "sessionId": state.session_id,
        "sessionTitle": state.session_title,
        "eventSlug": state.event_slug,
        "startTime": iso(state.start_time),
        "promotionMode": state.promotion_mode.value,
        "offerClaimWindow": millis(state.offer_claim_window),
        "presenterId": state.presenter_id,
        "availableSeats": state.available_seats,
        "waiting": [participant_json(p) for p in state.waiting],
        "shadowbannedUserIds": sorted(state.shadowbanned_user_ids),
    }


def export_select_promotable_parties() -> None:
    def run(state: PromotionStateDTO) -> dict[str, Any]:
        parties = select_promotable_parties(state)
        return {
            "input": state_json(state),
            "output": [[p.participation_id for p in party] for party in parties],
        }

    collect(
        "select_promotable_parties",
        python="ludamus.specs.enrollment.select_promotable_parties",
        strategy=promotion_states(),
        run=run,
        examples=500,
    )


class RecordingPromotions:
    def __init__(self, state: PromotionStateDTO | None, offer: OfferDTO | None):
        self.state = state
        self.offer_dto = offer
        self.writes: list[dict[str, Any]] = []

    def lock_and_read_state(self, session_id: int) -> PromotionStateDTO | None:
        return self.state

    def confirm(self, participation_ids: list[int]) -> None:
        self.writes.append({"op": "confirm", "participationIds": list(participation_ids)})

    def offer(
        self,
        participation_ids: list[int],
        *,
        offered_at: datetime,
        offer_expires_at: datetime,
        claim_token: str,
    ) -> None:
        self.writes.append(
            {
                "op": "offer",
                "participationIds": list(participation_ids),
                "offeredAt": iso(offered_at),
                "offerExpiresAt": iso(offer_expires_at),
                "claimToken": claim_token,
            }
        )

    def read_offer_by_token(self, token: str) -> OfferDTO | None:
        return self.offer_dto

    def read_offer_by_participation(self, participation_id: int) -> OfferDTO | None:
        return self.offer_dto

    def mark_claimed(self, participation_ids: list[int], *, claimed_at: datetime) -> None:
        self.writes.append(
            {
                "op": "markClaimed",
                "participationIds": list(participation_ids),
                "claimedAt": iso(claimed_at),
            }
        )

    def drop(self, participation_ids: list[int]) -> None:
        self.writes.append({"op": "drop", "participationIds": list(participation_ids)})


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def notify_promoted(self, n: Any) -> None:
        self.sent.append({"kind": "promoted", **_notification(n)})

    def notify_offered(self, n: Any) -> None:
        self.sent.append(
            {
                "kind": "offered",
                **_notification(n),
                "claimToken": n.claim_token,
                "offerExpiresAt": iso(n.offer_expires_at),
            }
        )

    def notify_offer_expired(self, n: Any) -> None:
        self.sent.append({"kind": "offerExpired", **_notification(n)})


def _notification(n: Any) -> dict[str, Any]:
    return {
        "recipientUserId": n.recipient_user_id,
        "sessionId": n.session_id,
        "sessionTitle": n.session_title,
        "eventSlug": n.event_slug,
    }


class RecordingScheduler:
    def __init__(self) -> None:
        self.expiries: list[dict[str, Any]] = []

    def schedule_expiry(self, *, participation_id: int, run_at: datetime) -> None:
        self.expiries.append({"participationId": participation_id, "runAt": iso(run_at)})


def _service(repo: RecordingPromotions) -> tuple[Any, RecordingNotifier, RecordingScheduler]:
    notifier = RecordingNotifier()
    scheduler = RecordingScheduler()
    service = enrollment_mills.WaitlistPromotionService(
        FakeTransaction(), repo, notifier, scheduler
    )
    return service, notifier, scheduler


@contextmanager
def _clock_and_tokens(now: datetime):
    counter = iter(range(1, 1000))
    with (
        patch.object(enrollment_mills, "_now", lambda: now),
        patch.object(enrollment_mills, "_token", lambda: f"token-{next(counter)}"),
    ):
        yield


def export_fill_freed_seats() -> None:
    @st.composite
    def cases(draw: st.DrawFn) -> tuple[PromotionStateDTO | None, datetime]:
        state = draw(st.sampled_from([True, False, False, False]).flatmap(
            lambda gone: st.none() if gone else promotion_states()
        ))
        now = BASE + timedelta(hours=draw(st.integers(-48, 72)))
        return state, now

    def run(value: tuple[PromotionStateDTO | None, datetime]) -> dict[str, Any]:
        state, now = value
        repo = RecordingPromotions(state, None)
        service, notifier, scheduler = _service(repo)
        with _clock_and_tokens(now):
            result = service.fill_freed_seats(session_id=1)
        return {
            "input": {"state": None if state is None else state_json(state), "now": iso(now)},
            "output": {
                "promoted": result.promoted,
                "offered": result.offered,
                "writes": repo.writes,
                "notifications": notifier.sent,
                "expiries": scheduler.expiries,
            },
        }

    collect(
        "fill_freed_seats",
        python="ludamus.mills.enrollment.WaitlistPromotionService.fill_freed_seats",
        strategy=cases(),
        run=run,
        examples=500,
    )


def export_offer_resolution() -> None:
    @st.composite
    def cases(draw: st.DrawFn) -> tuple[str, OfferDTO | None, datetime]:
        offer = draw(
            st.none()
            | st.builds(
                lambda ids, recipients, minutes: OfferDTO(
                    session_id=1,
                    session_title="S",
                    event_slug="ev",
                    participant_ids=ids,
                    recipients=recipients,
                    offer_expires_at=BASE + timedelta(minutes=minutes),
                ),
                st.lists(st.integers(1, 6), unique=True, min_size=1, max_size=3),
                st.lists(st.integers(1, 6), unique=True, max_size=3),
                st.integers(-3, 3),
            )
        )
        op = draw(st.sampled_from(["claim", "expire", "decline"]))
        now = BASE + timedelta(minutes=draw(st.integers(-3, 3)))
        return op, offer, now

    def run(value: tuple[str, OfferDTO | None, datetime]) -> dict[str, Any]:
        op, offer, now = value
        repo = RecordingPromotions(None, offer)
        service, notifier, _scheduler = _service(repo)
        with _clock_and_tokens(now):
            if op == "claim":
                claim = service.claim_offer(token="t")
                result: dict[str, Any] = {
                    "claim": {
                        "success": claim.success,
                        "sessionId": claim.session_id,
                        "eventSlug": claim.event_slug,
                        "reason": claim.reason,
                    }
                }
            elif op == "decline":
                claim = service.decline_offer(token="t")
                result = {
                    "claim": {
                        "success": claim.success,
                        "sessionId": claim.session_id,
                        "eventSlug": claim.event_slug,
                        "reason": claim.reason,
                    }
                }
            else:
                expired = service.expire_offer(participation_id=1)
                result = {"promoted": expired.promoted, "offered": expired.offered}
        return {
            "input": {
                "op": op,
                "now": iso(now),
                "offer": None
                if offer is None
                else {
                    "sessionId": offer.session_id,
                    "sessionTitle": offer.session_title,
                    "eventSlug": offer.event_slug,
                    "participantIds": offer.participant_ids,
                    "recipients": offer.recipients,
                    "offerExpiresAt": iso(offer.offer_expires_at),
                },
            },
            "output": {**result, "writes": repo.writes, "notifications": notifier.sent},
        }

    collect(
        "offer_resolution",
        python="ludamus.mills.enrollment.WaitlistPromotionService.claim_offer/decline_offer/expire_offer",
        strategy=cases(),
        run=run,
        examples=150,
    )


def export_distinct_recipients() -> None:
    collect(
        "distinct_recipients",
        python="ludamus.pacts.enrollment.distinct_recipients",
        strategy=st.lists(st.integers(1, 6), max_size=8),
        run=lambda ids: {"input": ids, "output": distinct_recipients(ids)},
    )


def export_is_valid_window_period() -> None:
    def run(value: tuple[int, int]) -> dict[str, Any]:
        start = BASE + timedelta(minutes=value[0])
        end = BASE + timedelta(minutes=value[1])
        return {
            "input": {"startTime": iso(start), "endTime": iso(end)},
            "output": is_valid_window_period(start_time=start, end_time=end),
        }

    collect(
        "is_valid_window_period",
        python="ludamus.specs.enrollment.is_valid_window_period",
        strategy=st.tuples(st.integers(-120, 120), st.integers(-120, 120)),
        run=run,
    )


# ------------------------------------------------------------------ windows


@dataclass(frozen=True)
class Window:
    pk: int
    start_time: datetime
    end_time: datetime
    percentage_slots: int
    restrict_to_configured_users: bool
    allow_anonymous_enrollment: bool
    max_waitlist_sessions: int
    limit_to_end_time: bool


EPOCH = datetime(2026, 6, 1, tzinfo=UTC)


@st.composite
def windows(draw: st.DrawFn, max_size: int = 4) -> list[Window]:
    count = draw(st.integers(0, max_size))
    result = []
    for pk in range(1, count + 1):
        start = draw(st.integers(0, 48))
        length = draw(st.integers(1, 48))
        result.append(
            Window(
                pk=pk,
                start_time=EPOCH + timedelta(hours=start),
                end_time=EPOCH + timedelta(hours=start + length),
                percentage_slots=draw(
                    st.sampled_from([1, 33, 50, 99, 100]) | st.integers(1, 100)
                ),
                restrict_to_configured_users=draw(st.booleans()),
                allow_anonymous_enrollment=draw(st.booleans()),
                max_waitlist_sessions=draw(st.integers(0, 10)),
                limit_to_end_time=draw(st.booleans()),
            )
        )
    return result


def window_json(w: Window) -> dict[str, Any]:
    return {
        "pk": w.pk,
        "startTime": iso(w.start_time),
        "endTime": iso(w.end_time),
        "percentageSlots": w.percentage_slots,
        "restrictToConfiguredUsers": w.restrict_to_configured_users,
        "allowAnonymousEnrollment": w.allow_anonymous_enrollment,
        "maxWaitlistSessions": w.max_waitlist_sessions,
        "limitToEndTime": w.limit_to_end_time,
    }


limits = st.integers(0, 10) | st.integers(0, 500)


def policy_json(policy: EnrollmentPolicy, *, limit: int, enrolled: int) -> dict[str, Any]:
    seating = policy.seating_window
    return {
        "windowIds": [w.pk for w in policy.windows],
        "canEnroll": policy.can_enroll,
        "seatingWindowId": None if seating is None else seating.pk,
        "percentageSlots": policy.percentage_slots,
        "maxWaitlistSessions": policy.max_waitlist_sessions,
        "requiresSlotAllowance": policy.requires_slot_allowance,
        "effectiveParticipantsLimit": policy.effective_participants_limit(
            participants_limit=limit
        ),
        "isFull": policy.is_full(participants_limit=limit, enrolled_count=enrolled),
        "availableSlots": policy.available_slots(
            participants_limit=limit, enrolled_count=enrolled
        ),
    }


def export_enrollment_policy() -> None:
    def run(value: tuple[list[Window], bool, int, int]) -> dict[str, Any]:
        listed, configured, limit, enrolled = value
        return {
            "input": {
                "windows": [window_json(w) for w in listed],
                "isConfiguredUser": configured,
                "participantsLimit": limit,
                "enrolledCount": enrolled,
            },
            "output": {
                "forActor": policy_json(
                    EnrollmentPolicy.for_actor(listed, is_configured_user=configured),
                    limit=limit,
                    enrolled=enrolled,
                ),
                "forGuest": policy_json(
                    EnrollmentPolicy.for_guest(listed), limit=limit, enrolled=enrolled
                ),
                "forAnonymous": policy_json(
                    EnrollmentPolicy.for_anonymous(listed), limit=limit, enrolled=enrolled
                ),
                "restrictsEveryone": restricts_everyone(listed),
            },
        }

    collect(
        "enrollment_policy",
        python="ludamus.mills.enrollment_windows.EnrollmentPolicy",
        strategy=st.tuples(
            windows(), st.booleans(), limits, st.integers(0, 12) | st.integers(0, 600)
        ),
        run=run,
    )


def export_viewer_access() -> None:
    def run(value: tuple[list[Window], set[int], int]) -> dict[str, Any]:
        listed, passes, hour = value
        now = EPOCH + timedelta(hours=hour)
        access = viewer_access(
            windows=listed, configured_window_ids=frozenset(passes), now=now
        )
        return {
            "input": {
                "windows": [window_json(w) for w in listed],
                "configuredWindowIds": sorted(passes),
                "now": iso(now),
            },
            "output": {
                "openWindowIds": sorted(access.open_window_ids),
                "opensAt": iso(access.opens_at),
                "canEnrollNow": access.can_enroll_now,
            },
        }

    collect(
        "viewer_access",
        python="ludamus.mills.enrollment_windows.viewer_access",
        strategy=st.tuples(
            windows(), st.sets(st.integers(1, 4)), st.integers(0, 96)
        ),
        run=run,
    )


class FakeEvent:
    get_active_enrollment_configs = models.Event.get_active_enrollment_configs
    get_allowance_enrollment_configs = models.Event.get_allowance_enrollment_configs
    get_eligible_enrollment_configs = models.Event.get_eligible_enrollment_configs

    def __init__(self, configs: list[models.EnrollmentConfig]) -> None:
        self.enrollment_configs = SimpleNamespace(all=lambda: list(configs))


def _config(w: Window) -> models.EnrollmentConfig:
    return models.EnrollmentConfig(
        pk=w.pk,
        start_time=w.start_time,
        end_time=w.end_time,
        percentage_slots=w.percentage_slots,
        limit_to_end_time=w.limit_to_end_time,
        restrict_to_configured_users=w.restrict_to_configured_users,
        allow_anonymous_enrollment=w.allow_anonymous_enrollment,
        max_waitlist_sessions=w.max_waitlist_sessions,
    )


def export_window_eligibility() -> None:
    def run(value: tuple[list[Window], int, int, int | None, int]) -> dict[str, Any]:
        listed, hour, limit, start_hour, enrolled = value
        now = EPOCH + timedelta(hours=hour)
        start = None if start_hour is None else EPOCH + timedelta(hours=start_hour)
        configs = [_config(w) for w in listed]
        event = FakeEvent(configs)
        session = SimpleNamespace(participants_limit=limit)
        if start is not None:
            session.agenda_item = SimpleNamespace(start_time=start)
        with patch.object(models, "datetime", frozen_datetime(now)):
            active = event.get_active_enrollment_configs()
            eligible = event.get_eligible_enrollment_configs(session)
            allowance = event.get_allowance_enrollment_configs()
        effective = models.effective_participants_limit(
            participants_limit=limit, eligible_configs=eligible
        )
        seats = SimpleNamespace(
            participants_limit=limit,
            enrolled_count=enrolled,
            effective_participants_limit=effective,
        )
        return {
            "input": {
                "windows": [window_json(w) for w in listed],
                "now": iso(now),
                "participantsLimit": limit,
                "sessionStartTime": iso(start),
                "enrolledCount": enrolled,
            },
            "output": {
                "activeIds": [c.pk for c in active],
                "canSeatIds": [
                    c.pk
                    for c in configs
                    if c.can_seat(participants_limit=limit, start_time=start)
                ],
                "eligibleIds": [c.pk for c in eligible],
                "allowanceIds": [c.pk for c in allowance],
                "effectiveParticipantsLimit": effective,
                "seatsLeft": models.Session.seats_left.fget(seats),
                "isFull": models.Session.is_full.fget(seats),
            },
        }

    collect(
        "window_eligibility",
        python="ludamus.links.db.django.models.Event/EnrollmentConfig/Session seat rules",
        strategy=st.tuples(
            windows(),
            st.integers(0, 96),
            st.integers(0, 10) | st.integers(0, 200),
            st.none() | st.integers(0, 96),
            st.integers(0, 12),
        ),
        run=run,
    )


def export_membership_lookup() -> None:
    @st.composite
    def cases(draw: st.DrawFn) -> dict[str, Any]:
        existing = draw(
            st.none()
            | st.fixed_dictionaries(
                {
                    "allowedSlots": st.integers(0, 3),
                    "lastCheck": st.none() | st.integers(0, 30),
                }
            )
        )
        return {"existing": existing, "apiAnswer": draw(st.none() | st.integers(0, 3))}

    def run(value: dict[str, Any]) -> dict[str, Any]:
        now = BASE
        existing = value["existing"]
        answer = value["apiAnswer"]
        calls: list[str] = []
        writes: list[dict[str, Any]] = []

        class TicketApi:
            def fetch_membership_count(self, email: str) -> int:
                calls.append(email)
                if answer is None:
                    raise MembershipAPIError
                return answer

        class Repo:
            def update_user_config(self, config: Any) -> None:
                writes.append(
                    {
                        "op": "update",
                        "allowedSlots": config.allowed_slots,
                        "lastCheck": iso(config.last_check),
                    }
                )

            def create_user_config(self, data: Any) -> Any:
                writes.append(
                    {
                        "op": "create",
                        "allowedSlots": data["allowed_slots"],
                        "fetchedFromApi": data["fetched_from_api"],
                        "lastCheck": iso(data["last_check"]),
                    }
                )
                return SimpleNamespace(allowed_slots=data["allowed_slots"])

        config = (
            None
            if existing is None
            else SimpleNamespace(
                user_email="u@example.com",
                allowed_slots=existing["allowedSlots"],
                last_check=None
                if existing["lastCheck"] is None
                else now - timedelta(minutes=existing["lastCheck"]),
            )
        )
        drawn = {
            "now": iso(now),
            "existing": None
            if config is None
            else {
                "allowedSlots": existing["allowedSlots"],
                "lastCheck": iso(config.last_check),
            },
            "apiAnswer": answer,
        }
        with patch.object(enrollment_mills, "datetime", frozen_datetime(now)):
            returned = enrollment_mills.get_or_create_user_enrollment_config(
                enrollment_config=SimpleNamespace(pk=1),
                user_email="u@example.com",
                ticket_api=TicketApi(),
                existing_user_config=config,
                enrollment_config_repo=Repo(),
            )
        return {
            "input": drawn,
            "output": {
                "askedApi": bool(calls),
                "returnedAllowedSlots": None if returned is None else returned.allowed_slots,
                "writes": writes,
            },
        }

    collect(
        "membership_lookup",
        python="ludamus.mills.enrollment.get_or_create_user_enrollment_config",
        strategy=cases(),
        run=run,
        examples=200,
    )


# ------------------------------------------------------------ enroll batch

HOUSEHOLD = (1, 2, 3, 4)
OCCUPYING = (SessionParticipationStatus.CONFIRMED, SessionParticipationStatus.OFFERED)
STATUS_VALUES = [None, *[s.value for s in SessionParticipationStatus]]


class Store:
    def __init__(self, rows: list[tuple[int, str]], guests: list[int]) -> None:
        self.log: list[dict[str, Any]] = []
        self.rows = [FakeRow(self, user_id, SessionParticipationStatus(status), saved=True) for user_id, status in rows]
        self.guests = [FakeGuest(self, pk) for pk in guests]
        self.next_guest = max(guests, default=100) + 1


class FakeRow:
    def __init__(
        self,
        store: Store,
        user_id: int,
        status: SessionParticipationStatus | None = None,
        *,
        saved: bool = False,
    ) -> None:
        self.store = store
        self.user_id = user_id
        self.status = status
        self.party_id: int | None = None
        self.saved = saved
        self.user = SimpleNamespace(id=user_id)

    def save(self) -> None:
        self.store.log.append(
            {
                "op": "save",
                "userId": self.user_id,
                "status": str(self.status),
                "partyId": self.party_id,
                "created": not self.saved,
            }
        )
        if not self.saved:
            self.saved = True
            self.store.rows.append(self)

    def delete(self) -> None:
        self.store.log.append({"op": "delete", "userId": self.user_id})
        self.store.rows.remove(self)


class FakeGuest:
    def __init__(self, store: Store, pk: int) -> None:
        self.pk = pk
        self.user = SimpleNamespace(delete=lambda: self._delete(store))

    def _delete(self, store: Store) -> None:
        store.log.append({"op": "removeGuest", "participationId": self.pk})
        store.guests.remove(self)


class FakeQuerySet:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def count(self) -> int:
        return len(self.rows)

    def order_by(self, *_fields: str) -> FakeQuerySet:
        return self

    def __iter__(self):
        return iter(self.rows)


def participation_model(store: Store) -> Any:
    class Manager:
        def filter(self, **kw: Any) -> FakeQuerySet:
            rows = list(store.rows)
            if "user_id" in kw:
                rows = [r for r in rows if r.user_id == kw["user_id"]]
            if "user_id__in" in kw:
                rows = [r for r in rows if r.user_id in set(kw["user_id__in"])]
            if "status__in" in kw:
                rows = [r for r in rows if r.status in kw["status__in"]]
            return FakeQuerySet(rows)

    class Participation:
        objects = Manager()

        def __new__(cls, *, session: Any, user_id: int) -> FakeRow:
            return FakeRow(store, user_id)

    return Participation


def session_model(session: Any, conflicted: set[int]) -> Any:
    return SimpleNamespace(
        objects=SimpleNamespace(
            select_for_update=lambda: SimpleNamespace(get=lambda **_kw: session),
            has_conflicts=lambda _session, user: user.pk in conflicted,
        )
    )


def window_like(draw: st.DrawFn) -> list[Window]:
    return draw(windows(max_size=2))


@st.composite
def batches(draw: st.DrawFn) -> dict[str, Any]:
    statuses = {u: draw(st.sampled_from(STATUS_VALUES)) for u in HOUSEHOLD}
    guests_now = draw(st.integers(0, 2))
    others = draw(st.integers(0, 2))
    requests = []
    for user_id in HOUSEHOLD:
        choice = draw(st.sampled_from([None, None, "enroll", "waitlist", "cancel"]))
        if choice is None:
            continue
        member = user_id != 1 and draw(st.booleans())
        requests.append(
            {
                "userId": user_id,
                "choice": choice,
                "name": f"user-{user_id}",
                "isPartyMember": member,
                "needsAccept": member and draw(st.booleans()),
            }
        )
    occupying = sum(1 for s in statuses.values() if s in ("confirmed", "offered"))
    return {
        "windows": draw(windows(max_size=2)),
        "viewerIsConfigured": draw(st.booleans()),
        "participantsLimit": draw(st.integers(1, 8)),
        "enrolledCount": others + occupying + guests_now,
        "presenterId": draw(st.none() | st.sampled_from([1, 2, 3, 4, 9])),
        "shadowbannedUserIds": sorted(draw(st.sets(st.sampled_from(HOUSEHOLD), max_size=2))),
        "conflictedUserIds": sorted(draw(st.sets(st.sampled_from(HOUSEHOLD), max_size=2))),
        "participations": [
            {"userId": u, "status": s} for u, s in statuses.items() if s is not None
        ],
        "partyId": draw(st.none() | st.just(7)),
        "guestParticipationIds": list(range(101, 101 + guests_now)),
        "guestsTarget": draw(st.none() | st.integers(0, 3)),
        "requests": requests,
    }


SKIP_REASONS = {
    "session host": "session_host",
    "not available": "not_available",
    "time conflict": "time_conflict",
    "manages their own enrollment": "manages_own_enrollment",
    "no enrollment to cancel": "no_enrollment_to_cancel",
}


def _skip(text: str) -> dict[str, str]:
    match = re.fullmatch(r"(.*) \((.*)\)", text)
    assert match, text
    return {"name": match[1], "reason": SKIP_REASONS[match[2]]}


def _view(case: dict[str, Any], log: list[dict[str, Any]], overflow: list[Any]) -> Any:
    view = views.SessionEnrollPageView()
    view.request = SimpleNamespace(
        context=SimpleNamespace(current_user_id=1),
        services=SimpleNamespace(
            shadowban=SimpleNamespace(
                banned_user_ids=lambda _presenter: set(case["shadowbannedUserIds"])
            ),
            waitlist_promotion=SimpleNamespace(
                hold_seat=lambda *, hold: log.append(
                    {"op": "holdSeat", "userId": hold.user_id, "partyId": hold.party_id}
                )
            ),
        ),
    )
    view._policies = {
        1: EnrollmentPolicy.for_actor(
            case["windows"], is_configured_user=case["viewerIsConfigured"]
        )
    }
    view._report_overflow = lambda requested, available, *, blame_guests: overflow.append(
        {"requested": requested, "available": available, "blameGuests": blame_guests}
    )
    view._actor_name = lambda: "Viewer"
    return view


def _fake_session(case: dict[str, Any]) -> Any:
    return SimpleNamespace(
        id=1,
        pk=1,
        title="S",
        presenter_id=case["presenterId"],
        participants_limit=case["participantsLimit"],
        enrolled_count=case["enrolledCount"],
        event=SimpleNamespace(
            slug="ev", get_eligible_enrollment_configs=lambda _s: case["windows"]
        ),
    )


def batch_input_json(case: dict[str, Any]) -> dict[str, Any]:
    return {**case, "windows": [window_json(w) for w in case["windows"]]}


def export_process_enrollments() -> None:
    def run(case: dict[str, Any]) -> dict[str, Any]:
        store = Store(
            [(p["userId"], p["status"]) for p in case["participations"]],
            case["guestParticipationIds"],
        )
        overflow: list[Any] = []
        view = _view(case, store.log, overflow)
        session = _fake_session(case)

        def create_guests(*, session: Any, count: int, party_pk: int | None) -> None:
            store.log.append({"op": "addGuests", "count": count, "partyId": party_pk})
            for _ in range(count):
                store.guests.append(FakeGuest(store, store.next_guest))
                store.next_guest += 1

        view._create_guests = create_guests
        requests = [
            views.EnrollmentRequest(
                user=SimpleNamespace(pk=r["userId"]),
                choice=views.EnrollmentChoice(r["choice"]),
                name=r["name"],
                is_party_member=r["isPartyMember"],
                needs_accept=r["needsAccept"],
            )
            for r in case["requests"]
        ]
        with ExitStack() as stack:
            stack.enter_context(patch.object(views, "SessionParticipation", participation_model(store)))
            stack.enter_context(
                patch.object(views, "Session", session_model(session, set(case["conflictedUserIds"])))
            )
            stack.enter_context(
                patch.object(views, "_guest_participations", lambda _s, _v: FakeQuerySet(list(store.guests)))
            )
            stack.enter_context(patch.object(views, "reverse", lambda *_a, **_k: "/enroll"))
            try:
                enrollments = view._process_enrollments(
                    enrollment_requests=requests,
                    session=session,
                    party_pk=case["partyId"],
                    guests_target=case["guestsTarget"],
                )
            except views.RedirectError:
                return {
                    "input": batch_input_json(case),
                    "output": {"kind": "capacityExceeded", "overflow": overflow[0], "writes": store.log},
                }
        return {
            "input": batch_input_json(case),
            "output": {
                "kind": "processed",
                "writes": store.log,
                "cancelledUsers": enrollments.cancelled_users,
                "skippedUsers": [_skip(s) for s in enrollments.skipped_users],
                "confirmedUsers": enrollments.users_by_status[SessionParticipationStatus.CONFIRMED],
                "waitingUsers": enrollments.users_by_status[SessionParticipationStatus.WAITING],
                "freedSeat": enrollments.freed_seat,
                "signedUpUsers": [{"userId": u, "name": n} for u, n in enrollments.signed_up_users],
                "heldSeatUserIds": [u.pk for u in enrollments.party_notices.held_seats],
                "enrolledMemberUserIds": [u.pk for u in enrollments.party_notices.enrolled_members],
                "guestTotal": enrollments.guest_total,
            },
        }

    collect(
        "process_enrollments",
        python="ludamus.adapters.web.django.views.SessionEnrollPageView._process_enrollments",
        strategy=batches(),
        run=run,
        examples=400,
    )


@st.composite
def desired_states(draw: st.DrawFn) -> dict[str, Any]:
    companions = draw(st.integers(0, 2))
    members = draw(st.integers(0, 2))
    household = []
    for index in range(1 + companions + members):
        user_id = index + 1
        is_member = index > companions
        household.append(
            {
                "userId": user_id,
                "name": f"user-{user_id}",
                "isActive": draw(st.sampled_from([True, True, True, False])),
                "isMember": is_member,
                "needsAccept": is_member and draw(st.booleans()),
                "status": draw(st.sampled_from(STATUS_VALUES)),
                "desiredIn": draw(st.booleans()),
                "choices": sorted(
                    draw(st.sets(st.sampled_from(["enroll", "waitlist", "cancel"])))
                ),
            }
        )
    occupying = sum(1 for m in household if m["status"] in ("confirmed", "offered"))
    return {
        "windows": draw(windows(max_size=2)),
        "viewerIsConfigured": draw(st.booleans()),
        "participantsLimit": draw(st.integers(1, 6)),
        "enrolledCount": draw(st.integers(0, 3)) + occupying,
        "conflictedUserIds": sorted(
            draw(st.sets(st.sampled_from([m["userId"] for m in household]), max_size=2))
        ),
        "household": household,
    }


def export_desired_state_requests() -> None:
    def run(case: dict[str, Any]) -> dict[str, Any]:
        rows = [(m["userId"], m["status"]) for m in case["household"] if m["status"]]
        store = Store(rows, [])
        view = _view({**case, "shadowbannedUserIds": []}, store.log, [])
        session = _fake_session({**case, "presenterId": None})
        members = [
            RosterMember(
                user=SimpleNamespace(pk=m["userId"], full_name=m["name"], is_active=m["isActive"]),
                needs_accept=m["needsAccept"],
            )
            for m in case["household"]
        ]
        choices = {m["userId"]: set(m["choices"]) for m in case["household"]}
        view._household = lambda _roster: members
        view._choice_values = lambda _form, pk: choices[pk]
        roster = SimpleNamespace(
            members=[r for r, m in zip(members, case["household"], strict=True) if m["isMember"]]
        )
        form = SimpleNamespace(
            cleaned_data={
                f"user_{m['userId']}": INCLUDE_VALUE if m["desiredIn"] else ""
                for m in case["household"]
            }
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(views, "SessionParticipation", participation_model(store)))
            stack.enter_context(
                patch.object(views, "Session", session_model(session, set(case["conflictedUserIds"])))
            )
            requests = view._desired_state_requests(form, roster, session)
        return {
            "input": batch_input_json(case),
            "output": [
                {
                    "userId": r.user.pk,
                    "choice": r.choice.value,
                    "name": r.name,
                    "isPartyMember": r.is_party_member,
                    "needsAccept": r.needs_accept,
                }
                for r in requests
            ],
        }

    collect(
        "desired_state_requests",
        python="ludamus.adapters.web.django.views.SessionEnrollPageView._desired_state_requests",
        strategy=desired_states(),
        run=run,
    )


# ---------------------------------------------------------------- durations

DURATION_TOKENS = [
    "P", "T", "p", "t", "PT", "pt", "H", "M", "h", "m", "hours", "hour", "hrs",
    "hr", "min", "mins", "minutes", "minute", " ", "  ", "\t", "\n", "\x1c",
    "\x85", "　", "﻿", "\xa0", "0", "1", "2", "5", "9", "12", "23",
    "24", "59", "60", "90", "007", "1234", "12345", "١", "٢",
    "²", "５", "\U0001d7d8", "_", "-", "PT1H30M", "x", "S",
]


def _short_digit_runs(text: str) -> bool:
    return all(len(run) <= 12 for run in re.findall(r"\d+", text))


SPACES = st.sampled_from(["", "", " ", "  ", "\t", "\x1c", "\x85", "\u3000", "\ufeff", "\xa0"])
NUMBERS = st.sampled_from(["0", "1", "2", "5", "12", "23", "59", "60", "90", "007", "1234", "12345", "\u0661", "\u0662\u0663", "\uff15", "\U0001d7d8", "\u00b2"])


@st.composite
def loose_durations(draw: st.DrawFn) -> str:
    parts = [draw(SPACES), draw(st.sampled_from(["", "", "p", "t", "pt", "PT", "Pt", "P", "T"])), draw(SPACES)]
    if draw(st.booleans()):
        parts += [draw(NUMBERS), draw(SPACES), draw(st.sampled_from(["h", "H", "hour", "hours", "hrs", "hr", "Hours", "m", "x", ""]))]
    parts.append(draw(SPACES))
    if draw(st.booleans()):
        parts += [draw(NUMBERS), draw(SPACES), draw(st.sampled_from(["m", "M", "min", "mins", "minute", "minutes", "MIN", "h", "s", ""]))]
    parts.append(draw(SPACES))
    return "".join(parts)


canonical_durations = st.builds(
    lambda h, m: "PT" + h + m,
    st.sampled_from(["", "1H", "12H", "0H", "\u0661H", "007H", "H"]),
    st.sampled_from(["", "30M", "0M", "90M", "5M", "M", "\uff15M"]),
)

duration_texts = (
    loose_durations()
    | loose_durations()
    | canonical_durations
    | st.lists(st.sampled_from(DURATION_TOKENS), max_size=6).map("".join)
    | st.text(max_size=6)
).filter(_short_digit_runs)


def _outcome(call: Any) -> Any:
    try:
        return {"ok": call()}
    except durations.InvalidDurationError:
        return {"error": "InvalidDurationError"}
    except ValueError:
        return {"error": "ValueError"}


def export_durations() -> None:
    def run(value: tuple[str | None, str, str, int, int, list[str]]) -> dict[str, Any]:
        text, hours_raw, minutes_raw, hours, minutes, listed = value
        return {
            "input": {
                "text": text,
                "hoursPart": hours_raw,
                "minutesPart": minutes_raw,
                "hours": hours,
                "minutes": minutes,
                "durations": listed,
            },
            "output": {
                "parseDuration": list(durations.parse_duration(text)),
                "normalizeDuration": durations.normalize_duration(text or ""),
                "formatDuration": durations.format_duration(text),
                "stepperParts": list(durations.stepper_parts(text or "")),
                "hoursPart": _outcome(
                    lambda: durations.parse_duration_part(
                        hours_raw, maximum=durations.MAX_DURATION_HOURS
                    )
                ),
                "minutesPart": _outcome(
                    lambda: durations.parse_duration_part(
                        minutes_raw, maximum=durations.MAX_DURATION_MINUTES
                    )
                ),
                "durationFromParts": _outcome(
                    lambda: durations.duration_from_parts(
                        hours=hours_raw, minutes=minutes_raw
                    )
                ),
                "buildDuration": durations.build_duration(hours=hours, minutes=minutes),
                "durationChoices": [list(c) for c in durations.duration_choices(listed)],
            },
        }

    part = st.sampled_from(
        ["", " ", "0", "7", " 7 ", "23", "24", "59", "60", "007", "05", "١",
         "²", "５", "1_0", "-1", "x", "\x1c3", "﻿3"]
    ) | st.text(alphabet="0123456789 ", max_size=3)
    collect(
        "durations",
        python="ludamus.pacts.durations",
        strategy=st.tuples(
            st.none() | duration_texts,
            part,
            part,
            st.integers(-130, 130),
            st.integers(-130, 130),
            st.lists(duration_texts, max_size=3),
        ),
        run=run,
        examples=500,
    )


# ------------------------------------------------------------------- fields

FIELD_SLUGS = ["a", "b", "a_custom", "c"]


@st.composite
def organizer_fields(draw: st.DrawFn) -> list[tuple[OrganizerFieldDTO, bool]]:
    chosen = draw(st.lists(st.sampled_from(FIELD_SLUGS), unique=True, max_size=3))
    pairs = []
    for pk, slug in enumerate(chosen, start=1):
        field_type = draw(st.sampled_from(["text", "select", "checkbox", "discord"]))
        values = (
            draw(st.lists(st.sampled_from(["x", "y", "z"]), unique=True, max_size=3))
            if field_type == "select"
            else []
        )
        field = OrganizerFieldDTO(
            allow_custom=draw(st.booleans()),
            field_type=field_type,
            is_multiple=draw(st.booleans()),
            is_required=draw(st.booleans()),
            max_length=draw(st.sampled_from([0, 3, 10, 50])),
            name=f"F {slug}",
            options=[
                OrganizerFieldOptionDTO(
                    label=value.upper(), order=draw(st.integers(0, 2)), pk=i + 1, value=value
                )
                for i, value in enumerate(values)
            ],
            order=pk,
            pk=pk,
            question=f"Q {slug}",
            slug=slug,
        )
        pairs.append((field, draw(st.booleans())))
    return pairs


def field_json(field: OrganizerFieldDTO) -> dict[str, Any]:
    return {
        "allowCustom": field.allow_custom,
        "fieldType": field.field_type,
        "helpText": field.help_text,
        "icon": field.icon,
        "isMultiple": field.is_multiple,
        "isPublic": field.is_public,
        "isRequired": field.is_required,
        "maxLength": field.max_length,
        "name": field.name,
        "options": [
            {"label": o.label, "order": o.order, "pk": o.pk, "value": o.value}
            for o in field.options
        ],
        "order": field.order,
        "pk": field.pk,
        "question": field.question,
        "showOnCards": field.show_on_cards,
        "slug": field.slug,
    }


def pairs_json(pairs: list[tuple[OrganizerFieldDTO, bool]]) -> list[dict[str, Any]]:
    return [{"field": field_json(f), "isRequired": r} for f, r in pairs]


def _kind(form_field: Any) -> str:
    return {
        "MultipleChoiceField": "multipleChoice",
        "ChoiceField": "choice",
        "BooleanField": "boolean",
        "CharField": "text",
    }[type(form_field).__name__]


def export_field_requirements() -> None:
    def run(value: tuple[str, list[tuple[OrganizerFieldDTO, bool]]]) -> dict[str, Any]:
        prefix, pairs = value
        built: dict[str, Any] = {}
        pair_keys = build_dynamic_fields(fields=built, pairs=pairs, prefix=prefix)
        return {
            "input": {"prefix": prefix, "pairs": pairs_json(pairs)},
            "output": {
                "controls": [
                    {
                        "key": key,
                        "kind": _kind(f),
                        "required": f.required,
                        "maxLength": getattr(f, "max_length", None),
                        "choices": [[v, str(label)] for v, label in f.choices]
                        if hasattr(f, "choices")
                        else None,
                    }
                    for key, f in built.items()
                ],
                "pairCheckedKeys": list(pair_keys),
            },
        }

    collect(
        "field_requirements",
        python="ludamus.gates.web.django.dynamic_fields.build_dynamic_fields",
        strategy=st.tuples(st.sampled_from(["session", "personal"]), organizer_fields()),
        run=run,
    )


ANSWER_TOKENS = ["", " ", "x", "y", "z", "w", "X", "true", "false", "False", "0", "on", "abcdefghijkl", "x\x00", " x ", "x;w", "　"]


def export_field_validation() -> None:
    @st.composite
    def cases(draw: st.DrawFn) -> tuple[str, list[tuple[OrganizerFieldDTO, bool]], dict[str, list[str]]]:
        prefix = draw(st.sampled_from(["session", "personal"]))
        pairs = draw(organizer_fields())
        data: dict[str, list[str]] = {}
        for field, _required in pairs:
            for key in (f"{prefix}_{field.slug}", f"{prefix}_{field.slug}_custom"):
                if draw(st.booleans()):
                    data[key] = draw(st.lists(st.sampled_from(ANSWER_TOKENS), min_size=1, max_size=2))
        return prefix, pairs, data

    def run(value: tuple[str, list[tuple[OrganizerFieldDTO, bool]], dict[str, list[str]]]) -> dict[str, Any]:
        prefix, pairs, data = value
        query = QueryDict(mutable=True)
        for key, values in data.items():
            query.setlist(key, values)
        form = dynamic_fields_form(prefix=prefix, fields=pairs, data=query)
        valid = form.is_valid()
        return {
            "input": {"prefix": prefix, "pairs": pairs_json(pairs), "data": data},
            "output": {
                "valid": valid,
                "errors": {
                    key: [error.code or "custom_answer_required" for error in errors]
                    for key, errors in form.errors.as_data().items()
                },
                "cleaned": form.cleaned_data,
                "answered": {
                    f.slug: answered_value(prefix=prefix, field_def=f, form=form)
                    for f, _r in pairs
                }
                if valid
                else None,
            },
        }

    collect(
        "field_validation",
        python="ludamus.gates.web.django.dynamic_fields.dynamic_fields_form + answered_value",
        strategy=cases(),
        run=run,
        examples=400,
    )


answers = (
    st.none()
    | st.booleans()
    | st.sampled_from(ANSWER_TOKENS)
    | st.lists(st.sampled_from(ANSWER_TOKENS), max_size=3)
)


def export_field_answers() -> None:
    def run(value: tuple[Any, str, bool, list[str], str, list[tuple[OrganizerFieldDTO, bool]], dict[str, Any]]) -> dict[str, Any]:
        chosen, custom, multiple, known, prefix, pairs, stored = value
        fields = [f for f, _r in pairs]
        return {
            "input": {
                "chosen": chosen,
                "custom": custom,
                "isMultiple": multiple,
                "known": known,
                "prefix": prefix,
                "fields": [field_json(f) for f in fields],
                "answers": stored,
            },
            "output": {
                "mergeCustom": merge_custom(chosen=chosen, custom=custom, is_multiple=multiple),
                "splitStored": list(split_stored(stored=chosen, known=known, is_multiple=multiple)),
                "fold": fold_custom_answers(cleaned=dict(stored), fields=fields, prefix=prefix),
                "unfold": unfold_custom_answers(stored=dict(stored), fields=fields, prefix=prefix),
            },
        }

    stored_answers = st.dictionaries(
        st.sampled_from([f"{p}_{s}{c}" for p in ("session",) for s in FIELD_SLUGS for c in ("", "_custom")]),
        answers.filter(lambda a: a is not None),
        max_size=4,
    )
    collect(
        "field_answers",
        python="ludamus.mills.field_values.merge_custom/split_stored + dynamic_fields.fold/unfold_custom_answers",
        strategy=st.tuples(
            answers,
            st.sampled_from(ANSWER_TOKENS),
            st.booleans(),
            st.lists(st.sampled_from(["x", "y", "z", "w"]), unique=True, max_size=3),
            st.just("session"),
            organizer_fields(),
            stored_answers,
        ),
        run=run,
    )


def export_carried_answers() -> None:
    dicts = st.dictionaries(st.sampled_from(["a", "b", "c"]), st.sampled_from(["x", "y"]), max_size=3)
    collect(
        "carried_answers",
        python="ludamus.specs.proposal.carried_answers",
        strategy=st.tuples(dicts, dicts, st.booleans()),
        run=lambda v: {
            "input": {"public": v[0], "private": v[1], "presented": v[2]},
            "output": carried_answers(public=v[0], private=v[1], presented=v[2]),
        },
        examples=60,
    )


def export_unique_slug() -> None:
    @st.composite
    def cases(draw: st.DrawFn) -> dict[str, Any]:
        base = draw(st.text(alphabet="ab-", max_size=50) | st.sampled_from(["", "a" * 45, "b" * 60]))
        default = draw(st.sampled_from(["", "session", "d" * 50]))
        suffixes = draw(st.lists(st.sampled_from(["AAAA", "BBBB", "a-_9", "CCCC"]), min_size=4, max_size=4))
        capped = (default if base == "" else base)[:45]
        candidates = [capped, *(f"{capped}-{s}" for s in suffixes)]
        taken = sorted(draw(st.sets(st.sampled_from(candidates))))
        return {"base": base, "default": default, "taken": taken, "suffixes": suffixes}

    def run(case: dict[str, Any]) -> dict[str, Any]:
        suffixes = iter(case["suffixes"])
        with patch.object(slugs, "token_urlsafe", lambda _n: next(suffixes)):
            slug = slugs.unique_slug(
                base=case["base"], default=case["default"], exists=lambda s: s in case["taken"]
            )
        return {"input": case, "output": slug}

    collect(
        "unique_slug",
        python="ludamus.mills.slugs.unique_slug",
        strategy=cases(),
        run=run,
    )


# ---------------------------------------------------------------- timeslots

ZONES = {
    "UTC": datetime(2026, 3, 29, 1, tzinfo=UTC),
    "Europe/Warsaw": datetime(2026, 3, 29, 1, tzinfo=UTC),
    "Europe/Warsaw#autumn": datetime(2026, 10, 25, 1, tzinfo=UTC),
    "America/New_York": datetime(2026, 11, 1, 6, tzinfo=UTC),
    "Australia/Lord_Howe": datetime(2026, 4, 4, 15, tzinfo=UTC),
    "America/Havana": datetime(2026, 3, 8, 5, tzinfo=UTC),
    "America/Santiago": datetime(2026, 4, 5, 3, tzinfo=UTC),
    "Asia/Kolkata": datetime(2026, 6, 1, 0, 30, tzinfo=UTC),
}


def local_json(value: datetime) -> dict[str, str | None]:
    return {"wall": value.replace(tzinfo=None).isoformat(), "utc": iso(value)}


@st.composite
def intervals(draw: st.DrawFn) -> tuple[str, datetime, datetime]:
    zone_key = draw(st.sampled_from(sorted(ZONES)))
    anchor = ZONES[zone_key]
    start = anchor + timedelta(minutes=30 * draw(st.integers(-96, 96)))
    end = start + timedelta(minutes=30 * draw(st.integers(-4, 160)))
    return zone_key.split("#")[0], start, end


def export_day_turnover() -> None:
    def run(value: tuple[tuple[str, datetime, datetime], int]) -> dict[str, Any]:
        (zone, start, end), hour = value
        tz = ZoneInfo(zone)
        turnover = DayTurnover(hour)
        return {
            "input": {"timeZone": zone, "hour": hour, "start": iso(start), "end": iso(end)},
            "output": {
                "dateOfStart": turnover.date_of(start, tz).isoformat(),
                "opening": local_json(turnover.opening(turnover.date_of(start, tz), tz)),
                "windows": [
                    {"start": local_json(a), "end": local_json(b)}
                    for a, b in turnover.windows(start=start, end=end, tz=tz)
                ],
            },
        }

    collect(
        "day_turnover",
        python="ludamus.mills.timeslots.DayTurnover",
        strategy=st.tuples(
            intervals(), st.sampled_from([MIDNIGHT.hour, PROGRAMME_DAYS.hour, 0, 6, 2])
        ),
        run=run,
    )


def export_slot_windows_by_local_date() -> None:
    @st.composite
    def cases(draw: st.DrawFn) -> tuple[str, list[tuple[datetime, datetime]]]:
        zone_key = draw(st.sampled_from(sorted(ZONES)))
        anchor = ZONES[zone_key]
        slots = []
        for _ in range(draw(st.integers(0, 3))):
            start = anchor + timedelta(minutes=30 * draw(st.integers(-96, 96)))
            slots.append((start, start + timedelta(minutes=30 * draw(st.integers(-2, 100)))))
        return zone_key.split("#")[0], slots

    def run(value: tuple[str, list[tuple[datetime, datetime]]]) -> dict[str, Any]:
        zone, slots = value
        tz = ZoneInfo(zone)
        grouped = slot_windows_by_local_date(
            [SimpleNamespace(start_time=a, end_time=b) for a, b in slots], tz
        )
        return {
            "input": {
                "timeZone": zone,
                "slots": [{"startTime": iso(a), "endTime": iso(b)} for a, b in slots],
            },
            "output": [
                {
                    "date": day.isoformat(),
                    "windows": [{"start": local_json(a), "end": local_json(b)} for a, b in found],
                }
                for day, found in grouped.items()
            ],
        }

    collect(
        "slot_windows_by_local_date",
        python="ludamus.mills.timeslots.slot_windows_by_local_date",
        strategy=cases(),
        run=run,
    )



# ------------------------------------------------------------------- propose

SLUG_ALPHABET = (
    "abcXYZ019 -_.,!?'\"\t\n\x1c/łŁóÓźżćęąśńŚßæÆøœþðđĸŉŋſıħŧŀ×©®™½µ¿ª€¥£§°«»‰·•"
    "αβΓΩάΐЖжЁёЇїҐґЩщ—–…„”“’‘ẞỳḀ  ​😀"
)


def export_proposal_slug() -> None:
    from ludamus.mills.submissions import mapping

    @st.composite
    def cases(draw: st.DrawFn) -> dict[str, Any]:
        title = draw(
            st.text(alphabet=SLUG_ALPHABET, max_size=70)
            | st.sampled_from(["", "Ł" * 60, "a" * 50, "a" * 49 + " b", "--x--", "Ünïcödé Tïtlé"])
        )
        fallback = draw(st.sampled_from(["", "session"]))
        suffixes = draw(
            st.lists(st.sampled_from(["AAAA", "b-_9", "zzzz", "Q1w2"]), min_size=8, max_size=8)
        )
        base = mapping.slugify(title) or fallback
        candidates = [base] + [
            f"{mapping.slugify(base, max_length=50 - len(sfx) - 1)}-{sfx}" for sfx in suffixes[:7]
        ]
        taken = sorted(draw(st.sets(st.sampled_from(candidates))))
        return {"title": title, "fallback": fallback, "suffixes": suffixes, "taken": taken}

    def run(case: dict[str, Any]) -> dict[str, Any]:
        suffixes = iter(case["suffixes"])
        with patch.object(mapping, "token_urlsafe", lambda _n: next(suffixes)):
            try:
                output: Any = mapping.generate_unique_slug(
                    case["title"], lambda s: s in case["taken"], fallback=case["fallback"]
                )
            except mapping.SlugCollisionError:
                output = {"error": "SlugCollisionError"}
        return {
            "input": case,
            "output": {"slug": output, "slugify": mapping.slugify(case["title"])},
        }

    collect(
        "proposal_slug",
        python="ludamus.mills.submissions.mapping.generate_unique_slug + slugify",
        strategy=cases(),
        run=run,
        examples=400,
    )


IP_SAMPLES = [
    "", " ", "1.2.3.4", " 10.0.0.1 ", "01.2.3.4", "256.1.1.1", "1.2.3", "1.2.3.4.5",
    "١.2.3.4", "::", "::1", "1::", "::ffff:1.2.3.4", "::ffff:0102:0304", "::1.2.3.4",
    "1:0:0:2:0:0:0:3", "0:0:1:0:0:1:0:0", "fe80::1%eth0", "fe80::1%", "fe80::1%a%b",
    "1:2:3:4:5:6:7:8", "1:2:3:4:5:6:7:8:9", "1:2:3:4:5:6:7::", "::2:3:4:5:6:7:8",
    "1::2::3", ":1:2:3:4:5:6:7", "1:2:3:4:5:6:7:", "ABCD:EF01::", "12345::", "g::1",
    "1.2.3.4/32", "::/0", "2001:db8::1.2.3.4", "::ffff:1.2.3.04", "　::1　",
    "0000:0000:0000:0000:0000:ffff:7f00:0001",
    "1111:2222:3333:4444:5555:6666:7777:8888:9999:aaaa",
]


def export_client_ip() -> None:
    from ludamus.gates.web.django.helpers import _parse_ip

    collect(
        "client_ip",
        python="ludamus.gates.web.django.helpers._parse_ip",
        strategy=st.sampled_from(IP_SAMPLES)
        | st.ip_addresses().map(lambda a: a.exploded)
        | st.ip_addresses().map(lambda a: str(a).upper())
        | st.ip_addresses(v=6).map(lambda a: f"{a}%{a.version}")
        | st.text(alphabet="0123456789abcdefABCDEF:.%/ ", max_size=24),
        run=lambda value: {"input": {"raw": value}, "output": _parse_ip(value)},
        examples=400,
    )


def _messages(form: Any) -> dict[str, list[str]]:
    return {key: [str(e) for e in errors] for key, errors in form.errors.items()}


BUILTIN_TOKENS = ["", " ", "0", "1", "5", "6", "7", "-1", "80", "81", " 3 ", "3.0", "3.5",
                  "1_0", "x", "٣", "99999999999", "\x00", "a" * 256, "Title", "PT1H", "PT2H", "PT9H"]


def export_details_form() -> None:
    from types import SimpleNamespace

    from ludamus.gates.web.django.event.propose_forms import build_session_details_form
    from ludamus.pacts.legacy import SessionFieldRequirementDTO

    @st.composite
    def cases(draw: st.DrawFn) -> dict[str, Any]:
        category = draw(
            st.none()
            | st.fixed_dictionaries(
                {
                    "minParticipantsLimit": st.sampled_from([0, 1, 3]),
                    "maxParticipantsLimit": st.sampled_from([0, 6]),
                    "durations": st.lists(st.sampled_from(["PT1H", "PT2H", "PT30M", "bogus"]), unique=True, max_size=2),
                }
            )
        )
        pairs = draw(organizer_fields())
        data: dict[str, list[str]] = {}
        plausible = {
            "title": ["Title", " Tytuł "], "description": ["About it"], "participants_limit": ["", "1", "4", "6"],
            "min_age": ["", "0", "16"], "facilitator_name": ["Ola"], "duration": ["PT1H", "PT2H", "PT30M"],
        }
        for key, good in plausible.items():
            roll = draw(st.integers(0, 9))
            if roll >= 3:
                data[key] = [draw(st.sampled_from(good))]
            elif roll >= 1:
                data[key] = [draw(st.sampled_from(BUILTIN_TOKENS))]
        for field, _required in pairs:
            for key in (f"session_{field.slug}", f"session_{field.slug}_custom"):
                if draw(st.booleans()):
                    data[key] = draw(st.lists(st.sampled_from(ANSWER_TOKENS), min_size=1, max_size=2))
        return {"category": category, "pairs": pairs, "data": data}

    def run(case: dict[str, Any]) -> dict[str, Any]:
        category = case["category"]
        dto = None if category is None else SimpleNamespace(
            min_participants_limit=category["minParticipantsLimit"],
            max_participants_limit=category["maxParticipantsLimit"],
            durations=category["durations"],
        )
        requirements = [SessionFieldRequirementDTO(field=f, is_required=r) for f, r in case["pairs"]]
        query = QueryDict(mutable=True)
        for key, values in case["data"].items():
            query.setlist(key, values)
        form = build_session_details_form(requirements, category=dto)(data=query)
        valid = form.is_valid()
        cleaned = None
        if valid:
            folded = fold_custom_answers(
                cleaned=form.cleaned_data, fields=[f for f, _r in case["pairs"]], prefix="session"
            )
            cleaned = {k: v for k, v in folded.items() if v}
        return {
            "input": {"category": category, "pairs": pairs_json(case["pairs"]), "data": case["data"]},
            "output": {"errors": _messages(form), "cleaned": cleaned},
        }

    collect(
        "details_form",
        python="ludamus.gates.web.django.event.propose_forms.build_session_details_form + fold",
        strategy=cases(),
        run=run,
        examples=400,
    )


EMAIL_SAMPLES = [
    "", " ", "a@b.co", " anon@example.com ", "a@localhost", "a@b", "a@b.c", "a@-b.co",
    "a@b-.co", "a.b@c.de", "a..b@c.de", ".a@b.co", '"a b"@c.de', "a@[127.0.0.1]",
    "a@[::1]", "a@[1.2.3.04]", "a@b.xn--p1ai", "ą@b.co", "a@ą.pl", "a@b.co\x00",
    "İ@b.co", "ı@b.co", "K@b.co", "a@@b.co", "a@b.co.", "x" * 310 + "@example.com",
    "e2e-discord@test.local",
]


def export_personal_form() -> None:
    from ludamus.gates.web.django.event.propose_forms import build_personal_data_form

    @st.composite
    def cases(draw: st.DrawFn) -> dict[str, Any]:
        pairs = draw(organizer_fields())
        data: dict[str, list[str]] = {}
        if draw(st.integers(0, 4)):
            data["contact_email"] = [draw(st.sampled_from(EMAIL_SAMPLES) | st.emails())]
        for field, _required in pairs:
            for key in (f"personal_{field.slug}", f"personal_{field.slug}_custom"):
                if draw(st.booleans()):
                    data[key] = draw(st.lists(st.sampled_from(ANSWER_TOKENS), min_size=1, max_size=2))
        return {"pairs": pairs, "data": data}

    def run(case: dict[str, Any]) -> dict[str, Any]:
        query = QueryDict(mutable=True)
        for key, values in case["data"].items():
            query.setlist(key, values)
        form = build_personal_data_form(case["pairs"])(data=query)
        valid = form.is_valid()
        cleaned = None
        if valid:
            folded = fold_custom_answers(
                cleaned=form.cleaned_data, fields=[f for f, _r in case["pairs"]], prefix="personal"
            )
            cleaned = {
                "answers": {k: v for k, v in folded.items() if k != "contact_email" and v},
                "contactEmail": form.cleaned_data["contact_email"],
            }
        return {
            "input": {"pairs": pairs_json(case["pairs"]), "data": case["data"]},
            "output": {"errors": _messages(form), "cleaned": cleaned},
        }

    collect(
        "personal_form",
        python="ludamus.gates.web.django.event.propose_forms.build_personal_data_form + fold",
        strategy=cases(),
        run=run,
        examples=400,
    )


EXPORTS = {
    "select_promotable_parties": export_select_promotable_parties,
    "fill_freed_seats": export_fill_freed_seats,
    "offer_resolution": export_offer_resolution,
    "distinct_recipients": export_distinct_recipients,
    "is_valid_window_period": export_is_valid_window_period,
    "enrollment_policy": export_enrollment_policy,
    "viewer_access": export_viewer_access,
    "window_eligibility": export_window_eligibility,
    "membership_lookup": export_membership_lookup,
    "process_enrollments": export_process_enrollments,
    "desired_state_requests": export_desired_state_requests,
    "durations": export_durations,
    "field_requirements": export_field_requirements,
    "field_validation": export_field_validation,
    "field_answers": export_field_answers,
    "carried_answers": export_carried_answers,
    "unique_slug": export_unique_slug,
    "proposal_slug": export_proposal_slug,
    "client_ip": export_client_ip,
    "details_form": export_details_form,
    "personal_form": export_personal_form,
    "day_turnover": export_day_turnover,
    "slot_windows_by_local_date": export_slot_windows_by_local_date,
}


if __name__ == "__main__":
    for name in sys.argv[1:] or list(EXPORTS):
        EXPORTS[name]()
