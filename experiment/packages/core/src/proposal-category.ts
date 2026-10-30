import { Schema } from "effect";

import { SessionFieldRequirement } from "./fields.js";
import { EventId, ProposalCategoryId, TimeSlotId } from "./ids.js";
import { TimeSlot } from "./time-slot.js";

export const PromotionMode = Schema.Literals(["auto", "offer_claim"]);

export type PromotionMode = typeof PromotionMode.Type;

export const ProposalCategory = Schema.Struct({
  description: Schema.String,
  durations: Schema.Array(Schema.String),
  endTime: Schema.NullOr(Schema.DateTimeUtc),
  eventId: EventId,
  id: ProposalCategoryId,
  maxParticipantsLimit: Schema.Int,
  minParticipantsLimit: Schema.Int,
  name: Schema.String,
  offerClaimWindow: Schema.Duration,
  promotionMode: PromotionMode,
  slug: Schema.String,
  startTime: Schema.NullOr(Schema.DateTimeUtc),
});

export type ProposalCategory = typeof ProposalCategory.Type;

export const TimeSlotRequirement = Schema.Struct({
  isRequired: Schema.Boolean,
  timeSlot: TimeSlot,
  timeSlotId: TimeSlotId,
});

export type TimeSlotRequirement = typeof TimeSlotRequirement.Type;

export const CategoryStats = Schema.Struct({
  acceptedCount: Schema.Int,
  categoryId: ProposalCategoryId,
  proposalsCount: Schema.Int,
});

export type CategoryStats = typeof CategoryStats.Type;

export const CategoryRequirements = Schema.Struct({
  sessionFields: Schema.Array(SessionFieldRequirement),
  timeSlots: Schema.Array(TimeSlotRequirement),
});

export type CategoryRequirements = typeof CategoryRequirements.Type;
