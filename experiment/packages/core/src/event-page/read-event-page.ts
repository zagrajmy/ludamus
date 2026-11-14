import { implement } from "@zagrajmy/capability/implement";
import { DateTime, Effect, Option } from "effect";

import {
  readEventPageContract,
  readEventSessionContract,
} from "../contracts.js";
import { isOpen } from "../event.js";
import { SessionId } from "../ids.js";
import { BookmarkStore } from "../ports/bookmark-store.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import { EnrollmentConfigStore } from "../ports/enrollment-config-store.js";
import { EventStore } from "../ports/event-store.js";
import { FieldStore } from "../ports/field-store.js";
import { SessionStore } from "../ports/session-store.js";
import { NotFound } from "../ports/store-error.js";
import { COMPACT_SCHEDULE_MIN_SESSIONS } from "./event-page.js";
import type { EventPage } from "./event-page.js";

const openEvent = Effect.fn("EventPage.openEvent")(function* openEvent(
  slug: string
) {
  const sphere = yield* CurrentSphere;
  const events = yield* EventStore;
  const now = yield* DateTime.now;
  const event = yield* events.readBySlug({ slug, sphereId: sphere.id });

  if (!isOpen(event, now)) {
    return yield* new NotFound({ entity: "Event", key: slug });
  }

  return { event, now };
});

export const readEventPage = implement(readEventPageContract, ({ slug }) =>
  Effect.gen(function* readEventPageHandler() {
    const { event, now } = yield* openEvent(slug);
    const sessions = yield* SessionStore;
    const fields = yield* FieldStore;
    const windows = yield* EnrollmentConfigStore;
    const bookmarks = yield* BookmarkStore;

    const cards = yield* sessions.listScheduledCards({
      eventId: event.id,
      now,
      rosterUpTo: COMPACT_SCHEDULE_MIN_SESSIONS,
    });

    const isCompact = cards.length >= COMPACT_SCHEDULE_MIN_SESSIONS;

    const sessionFields = yield* fields.listSessionFields(event.id);
    const enrollmentWindows = yield* windows.listByEvent(event.id);

    const bookmarkCounts = isCompact ? yield* bookmarks.counts(event.id) : [];

    const page: EventPage = {
      bookmarkCounts,
      enrollmentWindows,
      event,
      filterFields: sessionFields.filter(
        (field) => field.fieldType === "select" && field.isPublic
      ),
      isCompact,
      sessions: cards,
    };

    return page;
  })
);

export const readEventSession = implement(
  readEventSessionContract,
  ({ sessionId, slug }) =>
    Effect.gen(function* readEventSessionHandler() {
      const { event, now } = yield* openEvent(slug);
      const sessions = yield* SessionStore;

      const card = yield* sessions.readScheduledCard({
        eventId: event.id,
        now,
        sessionId: SessionId.make(sessionId),
      });

      return yield* Option.match(card, {
        onNone: () =>
          Effect.fail(
            new NotFound({ entity: "Session", key: String(sessionId) })
          ),
        onSome: Effect.succeed,
      });
    })
);
