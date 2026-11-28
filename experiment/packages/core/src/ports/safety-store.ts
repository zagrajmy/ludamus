import { Context } from "effect";
import type { Effect } from "effect";

import type { EventBanId, EventId, SessionId, UserId } from "../ids.js";
import type { EventBan, ShadowbanWarning } from "../safety.js";
import type { StoreFailure } from "./store-error.js";

export class SafetyStore extends Context.Service<
  SafetyStore,
  {
    readonly bannedUserIds: (
      ownerId: UserId
    ) => Effect.Effect<readonly UserId[], StoreFailure>;
    readonly banningOwnerIds: (
      targetId: UserId
    ) => Effect.Effect<readonly UserId[], StoreFailure>;
    readonly setShadowban: (options: {
      readonly ownerId: UserId;
      readonly targetId: UserId;
      readonly banned: boolean;
    }) => Effect.Effect<void, StoreFailure>;
    readonly sessionShadowbanWarnings: (options: {
      readonly viewerId: UserId;
      readonly sessionId: SessionId;
    }) => Effect.Effect<readonly ShadowbanWarning[], StoreFailure>;
    readonly listEventBans: (
      eventId: EventId
    ) => Effect.Effect<readonly EventBan[], StoreFailure>;
    readonly isBanned: (options: {
      readonly eventId: EventId;
      readonly userId: UserId;
    }) => Effect.Effect<boolean, StoreFailure>;
    readonly bannedEventIds: (options: {
      readonly eventIds: readonly EventId[];
      readonly userId: UserId;
    }) => Effect.Effect<readonly EventId[], StoreFailure>;
    readonly ban: (options: {
      readonly eventId: EventId;
      readonly userId: UserId;
      readonly reason: string;
    }) => Effect.Effect<void, StoreFailure>;
    readonly unban: (options: {
      readonly eventId: EventId;
      readonly id: EventBanId;
    }) => Effect.Effect<void, StoreFailure>;
  }
>()("@zagrajmy/core/SafetyStore") {}
