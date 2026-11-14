import { Schema } from "effect";

import { BookmarkCount } from "../bookmark.js";
import { EnrollmentConfig } from "../enrollment-config.js";
import { Event } from "../event.js";
import { SessionField } from "../fields.js";
import { SessionCard } from "../session.js";

export const COMPACT_SCHEDULE_MIN_SESSIONS = 20;

export const ReadEventPageInput = Schema.Struct({
  slug: Schema.String.check(Schema.isMinLength(1), Schema.isMaxLength(255)),
});

export type ReadEventPageInput = typeof ReadEventPageInput.Type;

export const EventPage = Schema.Struct({
  bookmarkCounts: Schema.Array(BookmarkCount),
  enrollmentWindows: Schema.Array(EnrollmentConfig),
  event: Event,
  filterFields: Schema.Array(SessionField),
  isCompact: Schema.Boolean,
  sessions: Schema.Array(SessionCard),
});

export type EventPage = typeof EventPage.Type;

export const ReadEventSessionInput = Schema.Struct({
  sessionId: Schema.Int.check(Schema.isGreaterThan(0)),
  slug: ReadEventPageInput.fields.slug,
});

export type ReadEventSessionInput = typeof ReadEventSessionInput.Type;
