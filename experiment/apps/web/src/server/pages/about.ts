import { LandingStore } from "@zagrajmy/core/ports/landing-store";
import { Effect } from "effect";

import type { AboutFlags } from "../../client/about/flags.js";
import type { RequestContext } from "../request-context.js";
import { contactEmail, loadConventions } from "./landing.js";

export const loadAbout = Effect.fn("AboutPage.load")(function* loadAbout(
  context: RequestContext
) {
  const store = yield* LandingStore;
  const stats = yield* store.stats;
  const conventions = yield* loadConventions(context);
  const flags: AboutFlags = {
    contactEmail,
    conventions: conventions.map((convention) => ({
      domain: convention.domain,
      name: convention.name,
    })),
    eventCount: stats.events,
    sessionCount: stats.sessions,
  };

  return flags;
});
