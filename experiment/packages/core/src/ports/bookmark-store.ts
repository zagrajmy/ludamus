import { Context } from "effect";
import type { Effect, Option } from "effect";

import type { BookmarkCount, BookmarkState } from "../bookmark.js";
import type { EventId, SessionId, UserId } from "../ids.js";
import type { SphereId } from "../sphere.js";
import type { StoreFailure } from "./store-error.js";

export class BookmarkStore extends Context.Service<
  BookmarkStore,
  {
    readonly toggle: (options: {
      readonly userId: UserId;
      readonly sessionId: SessionId;
      readonly sphereId: SphereId;
    }) => Effect.Effect<Option.Option<BookmarkState>, StoreFailure>;
    readonly bookmarkedSessionIds: (options: {
      readonly userId: UserId;
      readonly eventId: EventId;
    }) => Effect.Effect<readonly SessionId[], StoreFailure>;
    readonly counts: (
      eventId: EventId
    ) => Effect.Effect<readonly BookmarkCount[], StoreFailure>;
    readonly sessionState: (options: {
      readonly userId: UserId | null;
      readonly sessionId: SessionId;
      readonly eventId: EventId;
    }) => Effect.Effect<BookmarkState, StoreFailure>;
  }
>()("@zagrajmy/core/BookmarkStore") {}
