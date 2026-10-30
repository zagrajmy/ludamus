import { describe, expect, it } from "@effect/vitest";
import { Duration, Effect, Result, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import {
  UNLIMITED_SLOTS,
  canEnrollUsers,
  conflictedUserIds,
  ownerSlotsRemaining,
  processEnrollments,
  selectPromotableParties,
} from "../src/enrollment/index.js";
import type {
  EnrollSessionState,
  EnrollmentRequest,
  PromotionState,
} from "../src/enrollment/index.js";
import { durationFromParts } from "../src/proposal/index.js";
import { at, between } from "./support/arbitraries.js";

const OPEN_WINDOW = {
  allowAnonymousEnrollment: false,
  maxWaitlistSessions: 10,
  percentageSlots: 100,
  restrictToConfiguredUsers: false,
};

const waitingOwner = (slots: number): PromotionState => ({
  availableSeats: 1,
  eventSlug: "ev",
  offerClaimWindow: Duration.zero,
  presenterId: null,
  promotionMode: "auto",
  sessionId: 1,
  sessionTitle: "S",
  shadowbannedUserIds: [],
  startTime: at(10_000),
  waiting: [
    {
      creationTime: at(0),
      email: "owner@example.com",
      fullName: "owner",
      hasConflict: false,
      ownerSlotsRemaining: slots,
      participationId: 1,
      partyId: null,
      recipientUserId: 1,
      sponsorId: null,
      userId: 1,
    },
  ],
});

const Household = Schema.Struct({
  allowed: between(1, 3),
  companions: between(0, 2),
  seated: Schema.Array(between(0, 2)).check(Schema.isMaxLength(3)),
  waiter: between(0, 2),
});

const promotionAgreesWithGate = (household: typeof Household.Type): boolean => {
  const members = Array.from(
    { length: household.companions + 1 },
    (_, index) => index + 1
  );

  const occupying = [...new Set(household.seated)]
    .filter((index) => index < members.length)
    .map((index) => index + 1);

  const waiter = Math.min(household.waiter, members.length - 1) + 1;

  const gateAdmits = canEnrollUsers({
    allowedSlots: household.allowed,
    occupyingUserIds: occupying,
    userIdsToEnroll: [waiter],
  });

  const slots = ownerSlotsRemaining({
    domainAllowed: new Map(),
    occupyingHouseholdUserIds: occupying,
    ownerEmail: "owner@example.com",
    userAllowed: new Map([["owner@example.com", household.allowed]]),
  });

  const promoted = selectPromotableParties(waitingOwner(slots)).length === 1;

  return promoted === gateAdmits;
};

describe("documented findings (VERIFICATION.md), reproduced by the port", () => {
  it.effect.fails(
    "finding: promotion charges a pass for a waiter already seated in the event, so it refuses whom the gate admits",
    () =>
      Effect.gen(function* checkPromotionAgainstGate() {
        const result = yield* Arbitrary.checkEffect(
          Arbitrary.schema(Household),
          promotionAgreesWithGate,
          { runs: 200, seed: 1 }
        );

        expect(result._tag).toBe("Passed");
      })
  );

  it("finding, shrunk: one pass, owner seated elsewhere, owner waiting is never promoted", () => {
    expect(
      promotionAgreesWithGate({
        allowed: 1,
        companions: 0,
        seated: [0],
        waiter: 0,
      })
    ).toBe(false);
    expect(
      ownerSlotsRemaining({
        domainAllowed: new Map(),
        occupyingHouseholdUserIds: [],
        ownerEmail: "",
        userAllowed: new Map(),
      })
    ).toBe(UNLIMITED_SLOTS);
  });

  it.fails("finding: an offered seat in an overlapping session does not block enrolling (finding_offered_seat.bend)", () => {
    const conflicts = conflictedUserIds({
      seats: [
        {
          endTime: at(120),
          sessionId: 2,
          startTime: at(0),
          status: "offered",
          userId: 7,
        },
      ],
      sessionId: 1,
      span: { endTime: at(120), startTime: at(0) },
      userIds: [7],
    });

    expect(conflicts).toEqual([7]);
  });

  it.fails("finding: two enrolls decided on one snapshot double-book a person (finding_two_requests.bend)", () => {
    const snapshot = (sessionId: number): EnrollSessionState => ({
      conflictedUserIds: conflictedUserIds({
        seats: [],
        sessionId,
        span: { endTime: at(120), startTime: at(0) },
        userIds: [7],
      }),
      eligibleWindows: [OPEN_WINDOW],
      enrolledCount: 0,
      guestParticipationIds: [],
      participantsLimit: 4,
      participations: [],
      presenterId: null,
      shadowbannedUserIds: [],
      viewerIsConfigured: true,
    });

    const enroll: readonly EnrollmentRequest[] = [
      {
        choice: "enroll",
        isPartyMember: false,
        name: "p",
        needsAccept: false,
        userId: 7,
      },
    ];

    const confirmedIn = [1, 2].filter((sessionId) => {
      const outcome = processEnrollments({
        guestsTarget: null,
        partyId: null,
        requests: enroll,
        session: snapshot(sessionId),
      });

      return (
        Result.isSuccess(outcome) &&
        outcome.success.writes.some(
          (w) => w._tag === "Save" && w.status === "confirmed"
        )
      );
    });

    expect(confirmedIn.length).toBeLessThanOrEqual(1);
  });

  it.fails("finding: two enrolls checked on one snapshot seat more people than the owner holds passes (finding_allowance_race.bend)", () => {
    const occupying = [1];

    const first = canEnrollUsers({
      allowedSlots: 2,
      occupyingUserIds: occupying,
      userIdsToEnroll: [2],
    });

    const second = canEnrollUsers({
      allowedSlots: 2,
      occupyingUserIds: occupying,
      userIdsToEnroll: [3],
    });

    const seated = new Set([
      ...occupying,
      ...(first ? [2] : []),
      ...(second ? [3] : []),
    ]);

    expect(seated.size).toBeLessThanOrEqual(2);
  });
});

describe("new findings from the port (not yet in VERIFICATION.md)", () => {
  it.fails("finding: a confirmed seat in a session that wholly contains this one is not a conflict (conflicted_user_ids range test)", () => {
    const conflicts = conflictedUserIds({
      seats: [
        {
          endTime: at(240),
          sessionId: 2,
          startTime: at(-60),
          status: "confirmed",
          userId: 7,
        },
      ],
      sessionId: 1,
      span: { endTime: at(120), startTime: at(0) },
      userIds: [7],
    });

    expect(conflicts).toEqual([7]);
  });

  it.fails("finding: a superscript digit in an import duration is a bare ValueError the import view does not catch", () => {
    const outcome = durationFromParts({ hours: "²", minutes: "" });
    expect(Result.isFailure(outcome) && outcome.failure._tag).toBe(
      "InvalidDurationError"
    );
  });

  it("guarded only by the form: a needs-accept member posting waitlist is held a seat with no capacity check", () => {
    const outcome = processEnrollments({
      guestsTarget: null,
      partyId: 7,
      requests: [
        {
          choice: "waitlist",
          isPartyMember: true,
          name: "m",
          needsAccept: true,
          userId: 2,
        },
      ],
      session: {
        conflictedUserIds: [],
        eligibleWindows: [OPEN_WINDOW],
        enrolledCount: 1,
        guestParticipationIds: [],
        participantsLimit: 1,
        participations: [],
        presenterId: null,
        shadowbannedUserIds: [],
        viewerIsConfigured: true,
      },
    });

    expect(Result.isSuccess(outcome) && outcome.success.writes).toEqual([
      { _tag: "HoldSeat", partyId: 7, userId: 2 },
    ]);
  });
});
