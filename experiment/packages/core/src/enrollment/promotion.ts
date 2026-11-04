import type { Duration } from "effect";
import { DateTime, Match, Schema } from "effect";

import {
  distinctRecipients,
  selectPromotableParties,
  MEMBERSHIP_CHECK_INTERVAL_MINUTES,
} from "./rules.js";
import {
  ClaimResult,
  HeldSeatData,
  HeldSeatNotification,
  OfferNotification,
  PromotionNotification,
  PromotionResult,
} from "./schemas.js";
import type {
  Offer,
  PromotionState,
  SeatHoldRequest,
  UserEnrollmentConfig,
  WaitingParticipant,
} from "./schemas.js";

export const PlannedParty = Schema.Struct({
  participationIds: Schema.Array(Schema.Int),
  recipients: Schema.Array(Schema.Int),
});

export type PlannedParty = typeof PlannedParty.Type;

export const PromotionSession = Schema.Struct({
  eventSlug: Schema.String,
  sessionId: Schema.Int,
  sessionTitle: Schema.String,
});

export type PromotionSession = typeof PromotionSession.Type;

export const PromotionPlan = Schema.TaggedUnion({
  ConfirmParties: {
    parties: Schema.Array(PlannedParty),
    session: PromotionSession,
  },
  NoPromotion: {
    reason: Schema.Literals(["gone", "started", "nobody_fits"]),
  },
  OfferParties: {
    offerExpiresAt: Schema.DateTimeUtcFromString,
    offeredAt: Schema.DateTimeUtcFromString,
    parties: Schema.Array(PlannedParty),
    session: PromotionSession,
  },
});

export type PromotionPlan = typeof PromotionPlan.Type;

export const PromotionWrite = Schema.TaggedUnion({
  Confirm: { participationIds: Schema.Array(Schema.Int) },
  Offer: {
    claimToken: Schema.String,
    offerExpiresAt: Schema.DateTimeUtcFromString,
    offeredAt: Schema.DateTimeUtcFromString,
    participationIds: Schema.Array(Schema.Int),
  },
});

export type PromotionWrite = typeof PromotionWrite.Type;

export const OfferExpiry = Schema.Struct({
  participationId: Schema.Int,
  runAt: Schema.DateTimeUtcFromString,
});

export type OfferExpiry = typeof OfferExpiry.Type;

export const PromotionEffects = Schema.Struct({
  expiries: Schema.Array(OfferExpiry),
  offers: Schema.Array(OfferNotification),
  promotions: Schema.Array(PromotionNotification),
  result: PromotionResult,
  writes: Schema.Array(PromotionWrite),
});

export type PromotionEffects = typeof PromotionEffects.Type;

const plannedParty = (party: readonly WaitingParticipant[]): PlannedParty => ({
  participationIds: party.map((member) => member.participationId),
  recipients: distinctRecipients(party.map((member) => member.recipientUserId)),
});

export const planFillFreedSeats = (options: {
  readonly state: PromotionState | null;
  readonly now: DateTime.Utc;
}): PromotionPlan => {
  const { state, now } = options;

  if (state === null) {
    return PromotionPlan.cases.NoPromotion.make({ reason: "gone" });
  }

  if (DateTime.isGreaterThanOrEqualTo(now, state.startTime)) {
    return PromotionPlan.cases.NoPromotion.make({ reason: "started" });
  }

  const parties = selectPromotableParties(state).map(plannedParty);

  if (parties.length === 0) {
    return PromotionPlan.cases.NoPromotion.make({ reason: "nobody_fits" });
  }

  const session = {
    eventSlug: state.eventSlug,
    sessionId: state.sessionId,
    sessionTitle: state.sessionTitle,
  };

  const expiresAt = DateTime.addDuration(now, state.offerClaimWindow);

  if (
    state.promotionMode === "auto" ||
    DateTime.isGreaterThan(expiresAt, state.startTime)
  ) {
    return PromotionPlan.cases.ConfirmParties.make({ parties, session });
  }

  return PromotionPlan.cases.OfferParties.make({
    offerExpiresAt: expiresAt,
    offeredAt: now,
    parties,
    session,
  });
};

const notification = (
  session: PromotionSession,
  recipientUserId: number
): PromotionNotification => ({ ...session, recipientUserId });

export const promotionEffects = (options: {
  readonly plan: PromotionPlan;
  readonly claimToken: (partyIndex: number) => string;
}): PromotionEffects =>
  PromotionPlan.match<PromotionEffects>(options.plan, {
    ConfirmParties: (plan) => ({
      expiries: [],
      offers: [],
      promotions: plan.parties.flatMap((party) =>
        party.recipients.map((recipient) =>
          notification(plan.session, recipient)
        )
      ),
      result: {
        offered: [],
        promoted: plan.parties.flatMap((party) => party.participationIds),
      },
      writes: plan.parties.map((party) =>
        PromotionWrite.cases.Confirm.make({
          participationIds: party.participationIds,
        })
      ),
    }),
    NoPromotion: () => ({
      expiries: [],
      offers: [],
      promotions: [],
      result: { offered: [], promoted: [] },
      writes: [],
    }),
    OfferParties: (plan) => {
      const offered = plan.parties.map((party, index) => ({
        claimToken: options.claimToken(index),
        party,
      }));

      return {
        expiries: plan.parties.flatMap((party) =>
          party.participationIds.slice(0, 1).map((participationId) => ({
            participationId,
            runAt: plan.offerExpiresAt,
          }))
        ),
        offers: offered.flatMap(({ claimToken, party }) =>
          party.recipients.map((recipient) => ({
            ...notification(plan.session, recipient),
            claimToken,
            offerExpiresAt: plan.offerExpiresAt,
          }))
        ),
        promotions: [],
        result: {
          offered: plan.parties.flatMap((party) => party.participationIds),
          promoted: [],
        },
        writes: offered.map(({ claimToken, party }) =>
          PromotionWrite.cases.Offer.make({
            claimToken,
            offerExpiresAt: plan.offerExpiresAt,
            offeredAt: plan.offeredAt,
            participationIds: party.participationIds,
          })
        ),
      };
    },
  });

export const ClaimDecision = Schema.Struct({
  markClaimed: Schema.NullOr(
    Schema.Struct({
      claimedAt: Schema.DateTimeUtcFromString,
      participationIds: Schema.Array(Schema.Int),
    })
  ),
  result: ClaimResult,
});

export type ClaimDecision = typeof ClaimDecision.Type;

export const decideClaim = (options: {
  readonly offer: Offer | null;
  readonly now: DateTime.Utc;
}): ClaimDecision => {
  const { offer, now } = options;

  if (offer === null) {
    return {
      markClaimed: null,
      result: {
        eventSlug: null,
        reason: "not_found",
        sessionId: null,
        success: false,
      },
    };
  }

  if (DateTime.isGreaterThan(now, offer.offerExpiresAt)) {
    return {
      markClaimed: null,
      result: {
        eventSlug: offer.eventSlug,
        reason: "expired",
        sessionId: offer.sessionId,
        success: false,
      },
    };
  }

  return {
    markClaimed: { claimedAt: now, participationIds: offer.participantIds },
    result: {
      eventSlug: offer.eventSlug,
      reason: null,
      sessionId: offer.sessionId,
      success: true,
    },
  };
};

export const DeclineDecision = Schema.Struct({
  drop: Schema.Array(Schema.Int),
  refillSessionId: Schema.NullOr(Schema.Int),
  result: ClaimResult,
});

export type DeclineDecision = typeof DeclineDecision.Type;

export const decideDecline = (offer: Offer | null): DeclineDecision => {
  if (offer === null) {
    return {
      drop: [],
      refillSessionId: null,
      result: {
        eventSlug: null,
        reason: "not_found",
        sessionId: null,
        success: false,
      },
    };
  }

  return {
    drop: offer.participantIds,
    refillSessionId: offer.sessionId,
    result: {
      eventSlug: offer.eventSlug,
      reason: null,
      sessionId: offer.sessionId,
      success: true,
    },
  };
};

export const ExpiryDecision = Schema.TaggedUnion({
  Lapsed: {
    drop: Schema.Array(Schema.Int),
    notifications: Schema.Array(PromotionNotification),
    refillSessionId: Schema.Int,
  },
  StillOpen: {},
});

export type ExpiryDecision = typeof ExpiryDecision.Type;

export const decideExpiry = (options: {
  readonly offer: Offer | null;
  readonly now: DateTime.Utc;
}): ExpiryDecision => {
  const { offer, now } = options;

  if (
    offer === null ||
    DateTime.isLessThanOrEqualTo(now, offer.offerExpiresAt)
  ) {
    return ExpiryDecision.cases.StillOpen.make({});
  }

  const session = {
    eventSlug: offer.eventSlug,
    sessionId: offer.sessionId,
    sessionTitle: offer.sessionTitle,
  };

  return ExpiryDecision.cases.Lapsed.make({
    drop: offer.participantIds,
    notifications: offer.recipients.map((recipient) =>
      notification(session, recipient)
    ),
    refillSessionId: offer.sessionId,
  });
};

export const SeatHoldPlan = Schema.Struct({
  expiryAt: Schema.DateTimeUtcFromString,
  notification: HeldSeatNotification,
  seat: HeldSeatData,
});

export type SeatHoldPlan = typeof SeatHoldPlan.Type;

export const planSeatHold = (options: {
  readonly hold: SeatHoldRequest;
  readonly now: DateTime.Utc;
  readonly offerClaimWindow: Duration.Duration;
  readonly claimToken: string;
}): SeatHoldPlan => {
  const { hold, now, claimToken } = options;
  const expiresAt = DateTime.addDuration(now, options.offerClaimWindow);

  return {
    expiryAt: expiresAt,
    notification: {
      actorName: hold.actorName,
      claimToken,
      offerExpiresAt: expiresAt,
      recipientUserId: hold.userId,
      sessionId: hold.sessionId,
      sessionTitle: hold.sessionTitle,
    },
    seat: {
      claimToken,
      offerExpiresAt: expiresAt,
      offeredAt: now,
      partyId: hold.partyId,
      sessionId: hold.sessionId,
      userId: hold.userId,
    },
  };
};

export const MembershipLookup = Schema.Literals([
  "useExisting",
  "skip",
  "refresh",
  "create",
]);

export type MembershipLookup = typeof MembershipLookup.Type;

export const decideMembershipLookup = (options: {
  readonly existing: UserEnrollmentConfig | null;
  readonly now: DateTime.Utc;
}): MembershipLookup => {
  const { existing } = options;

  if (existing === null) {
    return "create";
  }

  if (existing.allowedSlots > 0) {
    return "useExisting";
  }

  const threshold = DateTime.subtract(options.now, {
    minutes: MEMBERSHIP_CHECK_INTERVAL_MINUTES,
  });

  if (
    existing.lastCheck === null ||
    DateTime.isLessThan(existing.lastCheck, threshold)
  ) {
    return "refresh";
  }

  return "skip";
};

export const MembershipWrite = Schema.TaggedUnion({
  CreateUserConfig: {
    allowedSlots: Schema.Int,
    fetchedFromApi: Schema.Boolean,
    lastCheck: Schema.DateTimeUtcFromString,
  },
  UpdateUserConfig: {
    allowedSlots: Schema.Int,
    lastCheck: Schema.DateTimeUtcFromString,
  },
});

export type MembershipWrite = typeof MembershipWrite.Type;

export const MembershipOutcome = Schema.Struct({
  allowedSlots: Schema.NullOr(Schema.Int),
  write: Schema.NullOr(MembershipWrite),
});

export type MembershipOutcome = typeof MembershipOutcome.Type;

export const membershipOutcome = (options: {
  readonly lookup: MembershipLookup;
  readonly existing: UserEnrollmentConfig | null;
  readonly membershipCount: number | null;
  readonly now: DateTime.Utc;
}): MembershipOutcome => {
  const { existing, membershipCount, now } = options;

  return Match.value(options.lookup).pipe(
    Match.when("useExisting", () => ({
      allowedSlots: existing?.allowedSlots ?? null,
      write: null,
    })),
    Match.when("skip", () => ({ allowedSlots: null, write: null })),
    Match.when("refresh", (): MembershipOutcome => {
      if (membershipCount === null) {
        return { allowedSlots: existing?.allowedSlots ?? null, write: null };
      }

      return {
        allowedSlots: membershipCount === 0 ? null : membershipCount,
        write: MembershipWrite.cases.UpdateUserConfig.make({
          allowedSlots: membershipCount,
          lastCheck: now,
        }),
      };
    }),
    Match.when("create", (): MembershipOutcome => {
      if (membershipCount === null) {
        return { allowedSlots: null, write: null };
      }

      return {
        allowedSlots: membershipCount,
        write: MembershipWrite.cases.CreateUserConfig.make({
          allowedSlots: membershipCount,
          fetchedFromApi: true,
          lastCheck: now,
        }),
      };
    }),
    Match.exhaustive
  );
};

export const RecheckedClaim = Schema.Struct({
  ...ClaimDecision.fields,
  drop: Schema.Array(Schema.Int),
  refillSessionId: Schema.NullOr(Schema.Int),
});

export type RecheckedClaim = typeof RecheckedClaim.Type;

export const decideClaimRechecked = (options: {
  readonly offer: Offer | null;
  readonly now: DateTime.Utc;
  readonly conflictedParticipationIds: readonly number[];
}): RecheckedClaim => {
  const decision = decideClaim(options);
  const { offer } = options;

  const conflicted =
    offer === null
      ? []
      : offer.participantIds.filter((id) =>
          options.conflictedParticipationIds.includes(id)
        );

  if (
    decision.markClaimed === null ||
    offer === null ||
    conflicted.length === 0
  ) {
    return { ...decision, drop: [], refillSessionId: null };
  }

  return {
    drop: conflicted,
    markClaimed: null,
    refillSessionId: offer.sessionId,
    result: {
      eventSlug: offer.eventSlug,
      reason: "conflict",
      sessionId: offer.sessionId,
      success: false,
    },
  };
};
