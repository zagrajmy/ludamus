import { Schema } from "effect";

import { SessionId } from "./ids.js";

export const BookmarkState = Schema.Struct({
  bookmarked: Schema.Boolean,
  count: Schema.Int,
});

export type BookmarkState = typeof BookmarkState.Type;

export const BookmarkCount = Schema.Struct({
  count: Schema.Int,
  sessionId: SessionId,
});

export type BookmarkCount = typeof BookmarkCount.Type;
