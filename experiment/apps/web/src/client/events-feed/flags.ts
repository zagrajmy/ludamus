import { Schema } from "effect";

import { FeedItem } from "../../ui/feed-card.js";

export const Announcement = Schema.Struct({
  content: Schema.String,
  id: Schema.Int,
  title: Schema.String,
});

export type Announcement = typeof Announcement.Type;

export const EventsFeedFlags = Schema.Struct({
  announcements: Schema.Array(Announcement),
  canCreateEncounter: Schema.Boolean,
  past: Schema.Array(FeedItem),
  showHidden: Schema.Boolean,
  upcoming: Schema.Array(FeedItem),
});

export type EventsFeedFlags = typeof EventsFeedFlags.Type;
