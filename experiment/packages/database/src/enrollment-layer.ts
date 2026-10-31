import { Layer } from "effect";

import { EnrollmentNotifierLive } from "./enrollment-notifier.js";
import {
  ClaimTokensLive,
  EnrollmentTransactionLive,
  NoTicketApiLive,
  OfferExpirySchedulerLive,
} from "./enrollment-services.js";
import { EnrollmentStoreLive } from "./enrollment-store.js";
import { NotificationStoreLive } from "./notification-store.js";
import { PromotionStoreLive } from "./promotion-store.js";

export const EnrollmentLive = Layer.mergeAll(
  ClaimTokensLive,
  EnrollmentNotifierLive,
  EnrollmentStoreLive,
  EnrollmentTransactionLive,
  NoTicketApiLive,
  NotificationStoreLive,
  OfferExpirySchedulerLive,
  PromotionStoreLive
);
