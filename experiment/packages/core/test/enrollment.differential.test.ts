import { describe, expect, it } from "@effect/vitest";
import { Schema } from "effect";

import {
  EnrollmentRequest,
  EnrollmentWindowPolicy,
  EnrollmentWindowRules,
  ExistingParticipation,
  HouseholdMember,
  Offer,
  PromotionState,
  activeWindows,
  allowanceWindows,
  canEnroll,
  canEnrollNow,
  canSeat,
  decideClaim,
  decideDecline,
  decideExpiry,
  decideMembershipLookup,
  desiredStateRequests,
  distinctRecipients,
  eligibleWindows,
  isValidWindowPeriod,
  membershipOutcome,
  planFillFreedSeats,
  policyAvailableSlots,
  policyEffectiveParticipantsLimit,
  policyForActor,
  policyForAnonymous,
  policyForGuest,
  policyIsFull,
  policyMaxWaitlistSessions,
  policyPercentageSlots,
  processEnrollments,
  promotionEffects,
  requiresSlotAllowance,
  restrictsEveryone,
  seatingWindow,
  selectPromotableParties,
  sessionEffectiveParticipantsLimit,
  sessionIsFull,
  sessionSeatsLeft,
  viewerAccess,
} from "../src/enrollment/index.js";
import type {
  EnrollmentPolicy,
  EnrollmentWrite,
  PromotionEffects,
  PromotionWrite,
  UserEnrollmentConfig,
} from "../src/enrollment/index.js";
import desiredStateCases from "./fixtures/differential/desired_state_requests.json" with { type: "json" };
import distinctRecipientsCases from "./fixtures/differential/distinct_recipients.json" with { type: "json" };
import policyCases from "./fixtures/differential/enrollment_policy.json" with { type: "json" };
import fillFreedSeatsCases from "./fixtures/differential/fill_freed_seats.json" with { type: "json" };
import windowPeriodCases from "./fixtures/differential/is_valid_window_period.json" with { type: "json" };
import membershipCases from "./fixtures/differential/membership_lookup.json" with { type: "json" };
import offerCases from "./fixtures/differential/offer_resolution.json" with { type: "json" };
import processCases from "./fixtures/differential/process_enrollments.json" with { type: "json" };
import selectCases from "./fixtures/differential/select_promotable_parties.json" with { type: "json" };
import viewerAccessCases from "./fixtures/differential/viewer_access.json" with { type: "json" };
import eligibilityCases from "./fixtures/differential/window_eligibility.json" with { type: "json" };
import { iso, isoOrNull, replay } from "./support/differential.js";
import type { Json } from "./support/differential.js";

const Instant = Schema.DateTimeUtcFromString;

const promotionWriteJson = (write: PromotionWrite): Json =>
  write._tag === "Confirm"
    ? { op: "confirm", participationIds: write.participationIds }
    : {
        claimToken: write.claimToken,
        offerExpiresAt: iso(write.offerExpiresAt),
        offeredAt: iso(write.offeredAt),
        op: "offer",
        participationIds: write.participationIds,
      };

const effectsJson = (effects: PromotionEffects): Json => ({
  expiries: effects.expiries.map((expiry) => ({
    participationId: expiry.participationId,
    runAt: iso(expiry.runAt),
  })),
  notifications: [
    ...effects.promotions.map((n) => ({ kind: "promoted", ...n })),
    ...effects.offers.map((n) => ({
      ...n,
      kind: "offered",
      offerExpiresAt: iso(n.offerExpiresAt),
    })),
  ],
  offered: effects.result.offered,
  promoted: effects.result.promoted,
  writes: effects.writes.map(promotionWriteJson),
});

const policyJson = (
  policy: EnrollmentPolicy<EnrollmentWindowRules>,
  seats: { readonly participantsLimit: number; readonly enrolledCount: number }
): Json => {
  const seating = seatingWindow(policy);

  return {
    availableSlots: policyAvailableSlots({ policy, ...seats }),
    canEnroll: canEnroll(policy),
    effectiveParticipantsLimit: policyEffectiveParticipantsLimit({
      participantsLimit: seats.participantsLimit,
      policy,
    }),
    isFull: policyIsFull({ policy, ...seats }),
    maxWaitlistSessions: policyMaxWaitlistSessions(policy),
    percentageSlots: policyPercentageSlots(policy),
    requiresSlotAllowance: requiresSlotAllowance(policy),
    seatingWindowId: seating._tag === "Some" ? seating.value.pk : null,
    windowIds: policy.windows.map((window) => window.pk),
  };
};

const enrollmentWriteJson = (write: EnrollmentWrite): Json => {
  switch (write._tag) {
    case "Delete": {
      return { op: "delete", userId: write.userId };
    }

    case "Save": {
      return {
        created: write.created,
        op: "save",
        partyId: write.partyId,
        status: write.status,
        userId: write.userId,
      };
    }

    case "AddGuests": {
      return { count: write.count, op: "addGuests", partyId: write.partyId };
    }

    case "RemoveGuest": {
      return { op: "removeGuest", participationId: write.participationId };
    }

    case "HoldSeat": {
      return { op: "holdSeat", partyId: write.partyId, userId: write.userId };
    }
  }
};

const SeatingInput = Schema.Struct({
  enrolledCount: Schema.Int,
  participantsLimit: Schema.Int,
  viewerIsConfigured: Schema.Boolean,
  windows: Schema.Array(EnrollmentWindowPolicy),
});

describe("differential: specs.enrollment", () => {
  it("select_promotable_parties picks the parties Python picks", () => {
    const mismatches = replay({
      cases: selectCases.cases,
      input: PromotionState,
      run: (state) =>
        selectPromotableParties(state).map((party) =>
          party.map((member) => member.participationId)
        ),
    });

    expect(selectCases.cases.length).toBeGreaterThan(300);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("is_valid_window_period agrees on every period", () => {
    const mismatches = replay({
      cases: windowPeriodCases.cases,
      input: Schema.Struct({ endTime: Instant, startTime: Instant }),
      run: isValidWindowPeriod,
    });

    expect(windowPeriodCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("distinct_recipients keeps first mentions in order", () => {
    const mismatches = replay({
      cases: distinctRecipientsCases.cases,
      input: Schema.Array(Schema.Int),
      run: distinctRecipients,
    });

    expect(distinctRecipientsCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});

describe("differential: WaitlistPromotionService", () => {
  it("fill_freed_seats writes, notifies and schedules what Python does", () => {
    const mismatches = replay({
      cases: fillFreedSeatsCases.cases,
      input: Schema.Struct({
        now: Instant,
        state: Schema.NullOr(PromotionState),
      }),
      run: ({ state, now }) =>
        effectsJson(
          promotionEffects({
            claimToken: (index) => `token-${index + 1}`,
            plan: planFillFreedSeats({ now, state }),
          })
        ),
    });

    expect(fillFreedSeatsCases.cases.length).toBeGreaterThan(200);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("claim, decline and expire resolve offers like Python", () => {
    const mismatches = replay({
      cases: offerCases.cases,
      input: Schema.Struct({
        now: Instant,
        offer: Schema.NullOr(Offer),
        op: Schema.Literals(["claim", "decline", "expire"]),
      }),
      run: ({ op, offer, now }): Json => {
        if (op === "claim") {
          const decision = decideClaim({ now, offer });

          return {
            claim: decision.result,
            notifications: [],
            writes:
              decision.markClaimed === null
                ? []
                : [
                    {
                      claimedAt: iso(decision.markClaimed.claimedAt),
                      op: "markClaimed",
                      participationIds: decision.markClaimed.participationIds,
                    },
                  ],
          };
        }

        if (op === "decline") {
          const decision = decideDecline(offer);

          return {
            claim: decision.result,
            notifications: [],
            writes:
              decision.refillSessionId === null
                ? []
                : [{ op: "drop", participationIds: decision.drop }],
          };
        }

        const expiry = decideExpiry({ now, offer });

        const refill = promotionEffects({
          claimToken: (index) => `token-${index + 1}`,
          plan: planFillFreedSeats({ now, state: null }),
        });

        return expiry._tag === "StillOpen"
          ? { notifications: [], offered: [], promoted: [], writes: [] }
          : {
              notifications: expiry.notifications.map((n) => ({
                kind: "offerExpired",
                ...n,
              })),
              offered: refill.result.offered,
              promoted: refill.result.promoted,
              writes: [{ op: "drop", participationIds: expiry.drop }],
            };
      },
    });

    expect(offerCases.cases.length).toBeGreaterThan(100);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("get_or_create_user_enrollment_config asks and writes what Python does", () => {
    const mismatches = replay({
      cases: membershipCases.cases,
      input: Schema.Struct({
        apiAnswer: Schema.NullOr(Schema.Int),
        existing: Schema.NullOr(
          Schema.Struct({
            allowedSlots: Schema.Int,
            lastCheck: Schema.NullOr(Instant),
          })
        ),
        now: Instant,
      }),
      run: ({ apiAnswer, existing, now }): Json => {
        const config: UserEnrollmentConfig | null =
          existing === null
            ? null
            : { ...existing, userEmail: "u@example.com" };

        const lookup = decideMembershipLookup({ existing: config, now });

        const outcome = membershipOutcome({
          existing: config,
          lookup,
          membershipCount: apiAnswer,
          now,
        });

        const { write } = outcome;

        return {
          askedApi: lookup === "refresh" || lookup === "create",
          returnedAllowedSlots: outcome.allowedSlots,
          writes:
            write === null
              ? []
              : [
                  write._tag === "UpdateUserConfig"
                    ? {
                        allowedSlots: write.allowedSlots,
                        lastCheck: iso(write.lastCheck),
                        op: "update",
                      }
                    : {
                        allowedSlots: write.allowedSlots,
                        fetchedFromApi: write.fetchedFromApi,
                        lastCheck: iso(write.lastCheck),
                        op: "create",
                      },
                ],
        };
      },
    });

    expect(membershipCases.cases.length).toBeGreaterThan(100);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});

describe("differential: enrollment windows", () => {
  it("EnrollmentPolicy answers every query like Python", () => {
    const mismatches = replay({
      cases: policyCases.cases,
      input: Schema.Struct({
        enrolledCount: Schema.Int,
        isConfiguredUser: Schema.Boolean,
        participantsLimit: Schema.Int,
        windows: Schema.Array(EnrollmentWindowRules),
      }),
      run: ({ windows, isConfiguredUser, ...seats }) => ({
        forActor: policyJson(
          policyForActor({ isConfiguredUser, windows }),
          seats
        ),
        forAnonymous: policyJson(policyForAnonymous(windows), seats),
        forGuest: policyJson(policyForGuest(windows), seats),
        restrictsEveryone: restrictsEveryone(windows),
      }),
    });

    expect(policyCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("viewer_access opens the windows Python opens", () => {
    const mismatches = replay({
      cases: viewerAccessCases.cases,
      input: Schema.Struct({
        configuredWindowIds: Schema.Array(Schema.Int),
        now: Instant,
        windows: Schema.Array(EnrollmentWindowRules),
      }),
      run: (input) => {
        const access = viewerAccess(input);

        return {
          canEnrollNow: canEnrollNow(access),
          openWindowIds: access.openWindowIds,
          opensAt: isoOrNull(access.opensAt),
        };
      },
    });

    expect(viewerAccessCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("Event/EnrollmentConfig/Session seat rules agree", () => {
    const mismatches = replay({
      cases: eligibilityCases.cases,
      input: Schema.Struct({
        enrolledCount: Schema.Int,
        now: Instant,
        participantsLimit: Schema.Int,
        sessionStartTime: Schema.NullOr(Instant),
        windows: Schema.Array(EnrollmentWindowRules),
      }),
      run: ({
        windows,
        now,
        participantsLimit,
        sessionStartTime,
        enrolledCount,
      }) => {
        const eligible = eligibleWindows({
          now,
          participantsLimit,
          startTime: sessionStartTime,
          windows,
        });

        const effective = sessionEffectiveParticipantsLimit({
          eligibleWindows: eligible,
          participantsLimit,
        });

        return {
          activeIds: activeWindows({ now, windows }).map((w) => w.pk),
          allowanceIds: allowanceWindows({ now, windows }).map((w) => w.pk),
          canSeatIds: windows
            .filter((window) =>
              canSeat({
                participantsLimit,
                startTime: sessionStartTime,
                window,
              })
            )
            .map((w) => w.pk),
          effectiveParticipantsLimit: effective,
          eligibleIds: eligible.map((w) => w.pk),
          isFull: sessionIsFull({
            effectiveParticipantsLimit: effective,
            enrolledCount,
            participantsLimit,
          }),
          seatsLeft: sessionSeatsLeft({
            effectiveParticipantsLimit: effective,
            enrolledCount,
          }),
        };
      },
    });

    expect(eligibilityCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});

describe("differential: SessionEnrollPageView decisions", () => {
  it("_process_enrollments writes and reports what the view does", () => {
    const mismatches = replay({
      cases: processCases.cases,
      input: Schema.Struct({
        ...SeatingInput.fields,
        conflictedUserIds: Schema.Array(Schema.Int),
        guestParticipationIds: Schema.Array(Schema.Int),
        guestsTarget: Schema.NullOr(Schema.Int),
        participations: Schema.Array(ExistingParticipation),
        partyId: Schema.NullOr(Schema.Int),
        presenterId: Schema.NullOr(Schema.Int),
        requests: Schema.Array(EnrollmentRequest),
        shadowbannedUserIds: Schema.Array(Schema.Int),
      }),
      run: ({ windows, requests, partyId, guestsTarget, ...session }): Json => {
        const outcome = processEnrollments({
          guestsTarget,
          partyId,
          requests,
          session: { ...session, eligibleWindows: windows },
        });

        if (outcome._tag === "Failure") {
          return {
            kind: "capacityExceeded",
            overflow: {
              available: outcome.failure.available,
              blameGuests: outcome.failure.blameGuests,
              requested: outcome.failure.requested,
            },
            writes: [],
          };
        }

        const batch = outcome.success;

        return {
          cancelledUsers: batch.cancelledUsers,
          confirmedUsers: batch.confirmedUsers,
          enrolledMemberUserIds: batch.enrolledMemberUserIds,
          freedSeat: batch.freedSeat,
          guestTotal: batch.guestTotal,
          heldSeatUserIds: batch.heldSeats.map((held) => held.userId),
          kind: "processed",
          signedUpUsers: batch.signedUpUsers,
          skippedUsers: batch.skippedUsers,
          waitingUsers: batch.waitingUsers,
          writes: batch.writes.map(enrollmentWriteJson),
        };
      },
    });

    expect(processCases.cases.length).toBeGreaterThan(300);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });

  it("_desired_state_requests routes the household like the view", () => {
    const mismatches = replay({
      cases: desiredStateCases.cases,
      input: Schema.Struct({
        ...SeatingInput.fields,
        conflictedUserIds: Schema.Array(Schema.Int),
        household: Schema.Array(HouseholdMember),
      }),
      run: ({ household, conflictedUserIds, windows, ...seating }) =>
        desiredStateRequests({
          conflictedUserIds,
          household,
          seating: { ...seating, eligibleWindows: windows },
        }),
    });

    expect(desiredStateCases.cases.length).toBeGreaterThan(250);
    expect(mismatches.slice(0, 3)).toEqual([]);
  });
});
