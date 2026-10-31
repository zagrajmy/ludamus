import { PanelStore, SessionStore } from "@zagrajmy/core";
import type { Event } from "@zagrajmy/core";
import { formatDate } from "@zagrajmy/i18n";
import { DateTime, Effect } from "effect";

import type { TimetableFlags } from "../../../client/panel/timetable/flags.js";
import type { RequestContext } from "../../request-context.js";

export const loadTimetable = Effect.fn("PanelPages.loadTimetable")(
  function* loadTimetable(context: RequestContext, event: Event) {
    const scheduled = yield* (yield* PanelStore).scheduledSessions(event.id);

    const facilitators = yield* (yield* SessionStore).facilitatorsBySession(
      scheduled.map((session) => session.id)
    );

    const format = (value: DateTime.Utc, pattern: string) =>
      formatDate({
        format: pattern,
        locale: context.translator.locale,
        value: DateTime.formatIso(value),
      });

    const days = new Map<
      string,
      TimetableFlags["days"][number]["sessions"][number][]
    >();

    for (const session of scheduled) {
      const day = format(session.startTime, "DATE_FORMAT");
      const list = days.get(day) ?? [];

      list.push({
        facilitators: (facilitators.get(session.id) ?? []).map(
          (facilitator) => facilitator.displayName
        ),
        id: session.id,
        room: session.spaceName,
        timeLabel: `${format(session.startTime, "H:i")}–${format(session.endTime, "H:i")}`,
        title: session.title,
      });
      days.set(day, list);
    }

    const flags: TimetableFlags = {
      days: [...days.entries()].map(([label, sessions]) => ({
        label,
        sessions,
      })),
      eventSlug: event.slug,
    };

    return flags;
  }
);
