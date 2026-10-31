import { DateTime, Effect } from "effect";

import { windowsHoldingPasses } from "./allowance.js";
import type { SessionContext } from "./api.js";
import { enrollFooter } from "./footer.js";
import type { EnrollFooter } from "./footer.js";
import { EnrollmentStore } from "./ports.js";
import { accessSeats, viewerAccess } from "./windows.js";

export const shadowbannedSeats = (
  seats: SessionContext["seats"]
): SessionContext["seats"] => ({
  ...seats,
  enrolledCount: seats.effectiveParticipantsLimit,
  isFull: true,
  seatsLeft: 0,
  waitingCount: 0,
});

export const viewerFooter = Effect.fn("Enrollment.viewerFooter")(
  function* viewerFooter(options: {
    readonly session: SessionContext;
    readonly viewerId: number;
    readonly viewerEmail: string;
  }) {
    const store = yield* EnrollmentStore;
    const { session } = options;
    const now = yield* DateTime.now;

    const statuses = new Set(
      (yield* store.householdSeats({
        eventId: session.eventId,
        userIds: [options.viewerId],
      }))
        .filter((seat) => seat.sessionId === session.sessionId)
        .map((seat) => seat.status)
    );

    const access = viewerAccess({
      configuredWindowIds: yield* windowsHoldingPasses({
        email: options.viewerEmail,
        eventId: session.eventId,
        now,
        windows: session.windows,
      }),
      now,
      windows: session.windows,
    });

    const seats = session.viewerShadowbanned
      ? shadowbannedSeats(session.seats)
      : session.seats;

    const footer: EnrollFooter = enrollFooter({
      isEnded:
        session.agenda !== null &&
        DateTime.isLessThanOrEqualTo(session.agenda.endTime, now),
      isEnrollmentAvailable: accessSeats({
        access,
        windowIds: session.seats.eligibleWindowIds,
      }),
      isFull: seats.isFull,
      isScheduled: session.agenda !== null,
      opensAt: access.opensAt,
      participantsLimit: session.participantsLimit,
      userEnrolled: statuses.has("confirmed"),
      userWaiting: statuses.has("waiting"),
    });

    return footer;
  }
);
