import { Context } from "effect";
import type { DateTime, Effect } from "effect";
import type { EnrollmentStoreError } from "../errors.js";

export class OfferExpiryScheduler extends Context.Service<
  OfferExpiryScheduler,
  {
    readonly scheduleExpiry: (expiry: {
      readonly participationId: number;
      readonly runAt: DateTime.Utc;
    }) => Effect.Effect<void, EnrollmentStoreError>;
  }
>()("@zagrajmy/core/enrollment/OfferExpiryScheduler") {}
