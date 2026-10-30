import { describe, expect, it } from "@effect/vitest";
import { DateTime, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import {
  canEnroll,
  planFillFreedSeats,
  policyAvailableSlots,
  policyEffectiveParticipantsLimit,
  policyForActor,
  policyForGuest,
  policyIsFull,
  promotionEffects,
  promotionGroupKey,
  selectPromotableParties,
  viewerAccess,
} from "../src/enrollment/index.js";
import type {
  PromotionState,
  WaitingParticipant,
} from "../src/enrollment/index.js";
import {
  BASE,
  EPOCH,
  between,
  promotionStates,
  windowLists,
} from "./support/arbitraries.js";

const ineligible = (
  state: PromotionState,
  member: WaitingParticipant
): boolean =>
  member.userId === state.presenterId ||
  member.hasConflict ||
  state.shadowbannedUserIds.includes(member.userId);

const firstSlots = (state: PromotionState): Map<number, number> => {
  const slots = new Map<number, number>();

  for (const member of state.waiting) {
    if (!slots.has(member.recipientUserId)) {
      slots.set(member.recipientUserId, member.ownerSlotsRemaining);
    }
  }

  return slots;
};

const eligibleParties = (
  state: PromotionState
): readonly (readonly WaitingParticipant[])[] => {
  const keys = [...new Set(state.waiting.map(promotionGroupKey))];

  return keys
    .map((key) =>
      state.waiting.filter(
        (member) =>
          promotionGroupKey(member) === key && !ineligible(state, member)
      )
    )
    .filter((party) => party.length > 0);
};

const ids = (party: readonly WaitingParticipant[]): string =>
  party.map((member) => member.participationId).join(",");

const states = { state: promotionStates };

describe("selectPromotableParties", () => {
  it.prop(
    "never seats more people than the seats left",
    states,
    ({ state }) => {
      const seated = selectPromotableParties(state).flat().length;
      expect(seated).toBeLessThanOrEqual(state.availableSeats);
    }
  );

  it.prop(
    "seats only waiting participations, each at most once",
    states,
    ({ state }) => {
      const seated = selectPromotableParties(state)
        .flat()
        .map((m) => m.participationId);

      const waiting = new Set(state.waiting.map((m) => m.participationId));
      expect(seated.every((id) => waiting.has(id))).toBe(true);
      expect(new Set(seated).size).toBe(seated.length);
    }
  );

  it.prop(
    "never seats a presenter, a conflicted or a shadowbanned waiter",
    states,
    ({ state }) => {
      expect(
        selectPromotableParties(state)
          .flat()
          .some((m) => ineligible(state, m))
      ).toBe(false);
    }
  );

  it.prop(
    "never splits a party: all of its eligible members move together",
    states,
    ({ state }) => {
      const whole = new Set(eligibleParties(state).map(ids));

      for (const party of selectPromotableParties(state)) {
        expect(whole.has(ids(party))).toBe(true);
      }
    }
  );

  it.prop(
    "keeps parties in the order their party first joined the queue",
    states,
    ({ state }) => {
      const position = (member: WaitingParticipant): number =>
        state.waiting.indexOf(member);

      const joined = (member: WaitingParticipant): number =>
        state.waiting.findIndex(
          (other) => promotionGroupKey(other) === promotionGroupKey(member)
        );

      const parties = selectPromotableParties(state);

      for (const party of parties) {
        const members = party.map(position);
        expect(members).toEqual(members.toSorted((a, b) => a - b));
      }

      const order = parties.map((party) =>
        party[0] === undefined ? -1 : joined(party[0])
      );

      expect(order).toEqual(order.toSorted((a, b) => a - b));
    }
  );

  it.prop(
    "never spends more of an owner's allowance than they hold",
    states,
    ({ state }) => {
      const slots = firstSlots(state);
      const spent = new Map<number, number>();

      for (const member of selectPromotableParties(state).flat()) {
        spent.set(
          member.recipientUserId,
          (spent.get(member.recipientUserId) ?? 0) + 1
        );
      }

      for (const [owner, count] of spent) {
        expect(count).toBeLessThanOrEqual(slots.get(owner) ?? 0);
      }
    },
    { arbitrary: { runs: 4000 } }
  );

  it.prop(
    "passes over a party ahead only when one of its owners is out of slots",
    states,
    ({ state }) => {
      const selected = selectPromotableParties(state).map(ids);
      const last = selected.at(-1);

      if (last === undefined) {
        return;
      }

      const remaining = firstSlots(state);

      for (const party of eligibleParties(state)) {
        if (ids(party) === last) {
          break;
        }

        if (selected.includes(ids(party))) {
          for (const member of party) {
            remaining.set(
              member.recipientUserId,
              (remaining.get(member.recipientUserId) ?? 0) - 1
            );
          }

          continue;
        }

        expect(
          party.some(
            (member) => (remaining.get(member.recipientUserId) ?? 0) <= 0
          )
        ).toBe(true);
      }
    }
  );

  it.prop(
    "promotes the head of the line whenever it fits",
    states,
    ({ state }) => {
      const [head] = eligibleParties(state);

      if (head === undefined) {
        return;
      }

      const slots = firstSlots(state);
      const needed = new Map<number, number>();

      for (const member of head) {
        needed.set(
          member.recipientUserId,
          (needed.get(member.recipientUserId) ?? 0) + 1
        );
      }

      const fits =
        head.length <= state.availableSeats &&
        [...needed].every(([owner, count]) => count <= (slots.get(owner) ?? 0));

      const [first] = selectPromotableParties(state);
      expect(first !== undefined && ids(first) === ids(head)).toBe(fits);
    }
  );

  it.prop(
    "one more free seat only ever extends the promoted line",
    states,
    ({ state }) => {
      const before = selectPromotableParties(state).map(ids);

      const after = selectPromotableParties({
        ...state,
        availableSeats: state.availableSeats + 1,
      }).map(ids);

      expect(after.slice(0, before.length)).toEqual(before);
    }
  );
});

describe("planFillFreedSeats", () => {
  const plans = {
    minutes: Arbitrary.schema(between(-3000, 4500)),
    state: promotionStates,
  };

  it.prop("a started session promotes nobody", plans, ({ state, minutes }) => {
    const now = DateTime.add(BASE, { minutes });

    if (DateTime.isLessThan(now, state.startTime)) {
      return;
    }

    expect(planFillFreedSeats({ now, state })._tag).toBe("NoPromotion");
  });

  it.prop(
    "an offer never outlives the session start",
    plans,
    ({ state, minutes }) => {
      const plan = planFillFreedSeats({
        now: DateTime.add(BASE, { minutes }),
        state,
      });

      if (plan._tag === "OfferParties") {
        expect(
          DateTime.isLessThanOrEqualTo(plan.offerExpiresAt, state.startTime)
        ).toBe(true);
      }
    }
  );

  it.prop(
    "tells each recipient of a moved party once, and nobody else",
    plans,
    ({ state, minutes }) => {
      const effects = promotionEffects({
        claimToken: (index) => `t${index}`,
        plan: planFillFreedSeats({
          now: DateTime.add(BASE, { minutes }),
          state,
        }),
      });

      const moved = new Set([
        ...effects.result.promoted,
        ...effects.result.offered,
      ]);

      const owners = new Set(
        state.waiting
          .filter((m) => moved.has(m.participationId))
          .map((m) => m.recipientUserId)
      );

      const told = [...effects.promotions, ...effects.offers].map(
        (n) => n.recipientUserId
      );

      expect(new Set(told)).toEqual(owners);
      expect(told.length).toBeLessThanOrEqual(moved.size);
    }
  );
});

describe("enrollment windows", () => {
  const limits = Arbitrary.schema(between(0, 500));

  it.prop(
    "a pass never lowers the seats on offer",
    { limit: limits, windows: windowLists },
    ({ windows, limit }) => {
      const holder = policyForActor({ isConfiguredUser: true, windows });
      expect(
        policyEffectiveParticipantsLimit({
          participantsLimit: limit,
          policy: holder,
        })
      ).toBeGreaterThanOrEqual(
        policyEffectiveParticipantsLimit({
          participantsLimit: limit,
          policy: policyForGuest(windows),
        })
      );
    }
  );

  it.prop(
    "never offers more seats than the room has",
    { limit: limits, windows: windowLists },
    ({ windows, limit }) => {
      const seats = policyEffectiveParticipantsLimit({
        participantsLimit: limit,
        policy: policyForActor({ isConfiguredUser: true, windows }),
      });

      expect(seats).toBeGreaterThanOrEqual(0);
      expect(seats).toBeLessThanOrEqual(limit);
    }
  );

  it.prop(
    "an open window always offers a seat in a room that has one",
    { limit: Arbitrary.schema(between(1, 500)), windows: windowLists },
    ({ windows, limit }) => {
      const policy = policyForGuest(windows);

      if (canEnroll(policy)) {
        expect(
          policyEffectiveParticipantsLimit({ participantsLimit: limit, policy })
        ).toBeGreaterThanOrEqual(1);
      }
    }
  );

  it.prop(
    "full exactly when no seat is left",
    {
      enrolled: Arbitrary.schema(between(0, 600)),
      limit: limits,
      windows: windowLists,
    },
    ({ windows, limit, enrolled }) => {
      const policy = policyForActor({ isConfiguredUser: true, windows });

      if (canEnroll(policy)) {
        const seats = {
          enrolledCount: enrolled,
          participantsLimit: limit,
          policy,
        };

        expect(policyIsFull(seats)).toBe(policyAvailableSlots(seats) === 0);
      }
    }
  );

  it.prop(
    "a pass never hides a window or delays the next one",
    {
      hour: Arbitrary.schema(between(0, 96)),
      passes: Arbitrary.schema(Schema.Array(between(1, 4))),
      windows: windowLists,
    },
    ({ windows, passes, hour }) => {
      const now = DateTime.add(EPOCH, { hours: hour });

      const withPasses = viewerAccess({
        configuredWindowIds: passes,
        now,
        windows,
      });

      const without = viewerAccess({ configuredWindowIds: [], now, windows });
      expect(
        without.openWindowIds.every((id) =>
          withPasses.openWindowIds.includes(id)
        )
      ).toBe(true);

      if (without.opensAt !== null) {
        expect(withPasses.opensAt).not.toBeNull();
        expect(
          withPasses.opensAt !== null &&
            DateTime.isLessThanOrEqualTo(withPasses.opensAt, without.opensAt)
        ).toBe(true);
      }
    }
  );
});
