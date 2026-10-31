import { DateTime, Effect, Option, Predicate } from "effect";

import type { EnrollmentStoreError } from "./errors.js";
import {
  ClaimTokens,
  EnrollmentNotifier,
  EnrollmentTransaction,
  OfferExpiryScheduler,
  PromotionStore,
} from "./ports.js";
import {
  decideClaimRechecked,
  decideDecline,
  decideExpiry,
  planFillFreedSeats,
  planSeatHold,
  promotionEffects,
} from "./promotion.js";
import type { OfferExpiry } from "./promotion.js";
import type {
  ClaimResult,
  Offer,
  PromotionResult,
  SeatHoldRequest,
} from "./schemas.js";

const NO_PROMOTION: PromotionResult = { offered: [], promoted: [] };

export const fillFreedSeats = Effect.fn("Promotion.fillFreedSeats")(
  function* fillFreedSeats(sessionId: number) {
    const transaction = yield* EnrollmentTransaction;
    const store = yield* PromotionStore;
    const tokens = yield* ClaimTokens;
    const notifier = yield* EnrollmentNotifier;
    const scheduler = yield* OfferExpiryScheduler;

    const effects = yield* transaction.atomic(
      Effect.gen(function* decideUnderLock() {
        const state = yield* store.lockAndReadState(sessionId);
        const now = yield* DateTime.now;

        const plan = planFillFreedSeats({
          now,
          state: Option.getOrNull(state),
        });

        const claimTokens = Predicate.isTagged(plan, "OfferParties")
          ? yield* Effect.all(plan.parties.map(() => tokens.next))
          : [];

        const decided = promotionEffects({
          claimToken: (index) => claimTokens[index] ?? "",
          plan,
        });

        if (Predicate.isTagged(plan, "NoPromotion")) {
          yield* Effect.logInfo("session promotes nobody").pipe(
            Effect.annotateLogs({ reason: plan.reason, sessionId })
          );
        }

        yield* store.apply(decided.writes);

        return decided;
      })
    );

    yield* Effect.all(
      effects.promotions.map((item) => notifier.notifyPromoted(item)),
      { discard: true }
    );
    yield* Effect.all(
      effects.offers.map((item) => notifier.notifyOffered(item)),
      { discard: true }
    );
    yield* Effect.all(
      effects.expiries.map((item) => scheduler.scheduleExpiry(item)),
      { discard: true }
    );

    if (
      effects.result.promoted.length > 0 ||
      effects.result.offered.length > 0
    ) {
      yield* Effect.logInfo("waiting list moved").pipe(
        Effect.annotateLogs({
          offered: effects.result.offered.length,
          promoted: effects.result.promoted.length,
          sessionId,
        })
      );
    }

    return effects.result;
  }
);

export const holdSeat = Effect.fn("Promotion.holdSeat")(function* holdSeat(
  hold: SeatHoldRequest
) {
  const store = yield* PromotionStore;
  const tokens = yield* ClaimTokens;
  const notifier = yield* EnrollmentNotifier;
  const now = yield* DateTime.now;
  const offerClaimWindow = yield* store.readOfferClaimWindow(hold.sessionId);
  const claimToken = yield* tokens.next;
  const plan = planSeatHold({ claimToken, hold, now, offerClaimWindow });
  const participationId = yield* store.createOffered(plan.seat);
  yield* notifier.notifySeatHeld(plan.notification);

  const expiry: OfferExpiry = { participationId, runAt: plan.expiryAt };

  return expiry;
});

const offerByToken = (query: {
  readonly token: string;
  readonly sphereId: number;
}) =>
  Effect.gen(function* readOfferByToken() {
    const store = yield* PromotionStore;

    return query.token === ""
      ? Option.none<Offer>()
      : yield* store.readOfferByToken(query);
  });

const lockedOffer = (
  read: Effect.Effect<
    Option.Option<Offer>,
    EnrollmentStoreError,
    PromotionStore
  >
) =>
  Effect.gen(function* readLockedOffer() {
    const store = yield* PromotionStore;
    const identified = yield* read;

    if (Option.isNone(identified)) {
      return identified;
    }

    yield* store.lockSessionRow(identified.value.sessionId);
    const offer = yield* read;

    if (Option.isSome(offer)) {
      yield* store.lockOfferHolders(offer.value.participantIds);
    }

    return offer;
  });

export const claimOffer = Effect.fn("Promotion.claimOffer")(
  function* claimOffer(query: {
    readonly token: string;
    readonly sphereId: number;
  }) {
    const transaction = yield* EnrollmentTransaction;
    const store = yield* PromotionStore;

    const decision = yield* transaction.atomic(
      Effect.gen(function* claimUnderLock() {
        const offer = Option.getOrNull(yield* lockedOffer(offerByToken(query)));
        const now = yield* DateTime.now;

        const conflictedParticipationIds =
          offer === null
            ? []
            : yield* store.conflictedOfferIds({
                participationIds: offer.participantIds,
                sessionId: offer.sessionId,
              });

        const decided = decideClaimRechecked({
          conflictedParticipationIds,
          now,
          offer,
        });

        if (decided.markClaimed !== null) {
          yield* store.markClaimed(decided.markClaimed);
        }

        yield* store.drop(decided.drop);

        return decided;
      })
    );

    if (decision.refillSessionId !== null) {
      yield* fillFreedSeats(decision.refillSessionId);
    }

    const result: ClaimResult = decision.result;

    return result;
  }
);

export const declineOffer = Effect.fn("Promotion.declineOffer")(
  function* declineOffer(query: {
    readonly token: string;
    readonly sphereId: number;
  }) {
    const transaction = yield* EnrollmentTransaction;
    const store = yield* PromotionStore;

    const decision = yield* transaction.atomic(
      Effect.gen(function* declineUnderLock() {
        const offer = yield* lockedOffer(offerByToken(query));
        const decided = decideDecline(Option.getOrNull(offer));
        yield* store.drop(decided.drop);

        return decided;
      })
    );

    if (decision.refillSessionId !== null) {
      yield* fillFreedSeats(decision.refillSessionId);
    }

    return decision.result;
  }
);

export const expireOffer = Effect.fn("Promotion.expireOffer")(
  function* expireOffer(participationId: number) {
    const transaction = yield* EnrollmentTransaction;
    const store = yield* PromotionStore;
    const notifier = yield* EnrollmentNotifier;

    const decision = yield* transaction.atomic(
      Effect.gen(function* expireUnderLock() {
        const offer = yield* lockedOffer(
          store.readOfferByParticipation(participationId)
        );

        const now = yield* DateTime.now;
        const decided = decideExpiry({ now, offer: Option.getOrNull(offer) });

        if (Predicate.isTagged(decided, "Lapsed")) {
          yield* store.drop(decided.drop);
        }

        return decided;
      })
    );

    if (!Predicate.isTagged(decision, "Lapsed")) {
      return NO_PROMOTION;
    }

    yield* Effect.all(
      decision.notifications.map((item) => notifier.notifyOfferExpired(item)),
      { discard: true }
    );

    return yield* fillFreedSeats(decision.refillSessionId);
  }
);
