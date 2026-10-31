import { implement } from "@zagrajmy/capability/implement";
import { Effect } from "effect";

import { readEnrollFooterContract } from "../contracts.js";
import type { SessionFooter } from "./api.js";
import { loadSession } from "./context.js";
import { EnrollmentStore } from "./ports.js";
import { shadowbannedSeats, viewerFooter } from "./viewer-footer.js";

export const READ_FOOTER_LIMIT = 50;

export const readEnrollFooter = implement(readEnrollFooterContract, (input) =>
  Effect.gen(function* readEnrollFooterHandler() {
    const store = yield* EnrollmentStore;

    return yield* Effect.forEach(
      input.sessionIds.slice(0, READ_FOOTER_LIMIT),
      (sessionId) =>
        Effect.gen(function* footerOf() {
          const { session, viewerId } = yield* loadSession(sessionId);
          const [viewer] = yield* store.readPeople([viewerId]);

          const footer: SessionFooter = {
            eventSlug: session.eventSlug,
            footer: yield* viewerFooter({
              session,
              viewerEmail: viewer?.email ?? "",
              viewerId,
            }),
            seats: session.viewerShadowbanned
              ? shadowbannedSeats(session.seats)
              : session.seats,
            sessionId,
            viewerId,
          };

          return footer;
        })
    );
  })
);
