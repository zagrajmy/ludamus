import { Context } from "effect";
import type { Effect } from "effect";
import type { EnrollmentStoreError } from "../errors.js";
import type { HeldSeatNotification, OfferNotification, PartyEnrolledNotification, PromotionNotification } from "../schemas.js";

export class EnrollmentNotifier extends Context.Service<
  EnrollmentNotifier,
  {
    readonly notifyPromoted: (
      notification: PromotionNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifyOffered: (
      notification: OfferNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifyOfferExpired: (
      notification: PromotionNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifySeatHeld: (
      notification: HeldSeatNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
    readonly notifyPartyEnrolled: (
      notification: PartyEnrolledNotification
    ) => Effect.Effect<void, EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/EnrollmentNotifier") {}
