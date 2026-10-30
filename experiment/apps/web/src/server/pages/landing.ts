import { LandingStore } from "@zagrajmy/core/ports/landing-store";
import { Effect } from "effect";

import type { LandingFlags } from "../../client/landing/flags.js";
import { storedTimestamp } from "../format/instant.js";
import { mediaUrl } from "../request-context.js";
import type { RequestContext } from "../request-context.js";

export const contactEmail = "kontakt@zagrajmy.net";
export const showcaseUrl = "https://kapitularz.zagrajmy.net/";

const conventionSubdomains: ReadonlyArray<string> = [
  "kapitularz",
  "bachanalia",
  "o2f",
];

export const conventionDomains = (context: RequestContext) =>
  conventionSubdomains.map(
    (subdomain) => `${subdomain}.${context.rootSphere.domain}`
  );

export const loadConventions = Effect.fn("Landing.conventions")(
  function* loadConventions(context: RequestContext) {
    const store = yield* LandingStore;
    const domains = conventionDomains(context);
    const rows = yield* store.conventions({
      domains,
      now: storedTimestamp(context.now),
    });

    return rows.toSorted(
      (left, right) =>
        domains.indexOf(left.domain) - domains.indexOf(right.domain)
    );
  }
);

export const loadLanding = Effect.fn("LandingPage.load")(function* loadLanding(
  context: RequestContext
) {
  const conventions = yield* loadConventions(context);
  const flags: LandingFlags = {
    contactEmail,
    conventions: conventions.map((convention) => ({
      coverUrl:
        convention.coverImage === ""
          ? "/static/placeholder-images/03.webp"
          : mediaUrl(convention.coverImage),
      domain: convention.domain,
      eventSlug: convention.eventSlug,
      name: convention.name,
    })),
    encountersEnabled: context.sphere.encountersPolicy !== "none",
    showcaseUrl,
  };

  return flags;
});
