import { Schema } from "effect";

import { EventBanId, EventId, UserId } from "./ids.js";
import { UserSummary } from "./user.js";

export const EventBan = Schema.Struct({
  createdAt: Schema.DateTimeUtc,
  eventId: EventId,
  id: EventBanId,
  reason: Schema.String,
  user: UserSummary,
});

export type EventBan = typeof EventBan.Type;

export const EVENT_BAN_REASON_MAX_LENGTH = 255;

export const ShadowbanPair = Schema.Struct({
  ownerId: UserId,
  targetId: UserId,
});

export type ShadowbanPair = typeof ShadowbanPair.Type;

export const ShadowbanWarning = Schema.Struct({
  shadowbannedAt: Schema.DateTimeUtc,
  user: UserSummary,
});

export type ShadowbanWarning = typeof ShadowbanWarning.Type;
