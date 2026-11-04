import { ProposalCategoryStore } from "@zagrajmy/core";
import type { Event } from "@zagrajmy/core";
import { formatDate } from "@zagrajmy/i18n";
import { DateTime, Effect } from "effect";

import type {
  CategoryWindow,
  CfpFlags,
} from "../../../client/panel/cfp/flags.js";
import type { RequestContext } from "../../request-context.js";

const windowOf = (
  options: Readonly<{
    end: DateTime.Utc | null;
    now: DateTime.Utc;
    start: DateTime.Utc | null;
  }>
): CategoryWindow => {
  const { end, now, start } = options;

  if (start === null && end === null) {
    return "not_set";
  }

  if (end !== null && DateTime.isGreaterThan(now, end)) {
    return "closed";
  }

  if (start !== null && DateTime.isLessThan(now, start)) {
    return "upcoming";
  }

  return start === null ? "not_set" : "active";
};

export const loadCfp = Effect.fn("PanelPages.loadCfp")(function* loadCfp(
  context: RequestContext,
  event: Event
) {
  const store = yield* ProposalCategoryStore;
  const categories = yield* store.listByEvent(event.id);
  const stats = yield* store.stats(event.id);
  const now = yield* DateTime.now;

  const short = (value: DateTime.Utc | null) =>
    value === null
      ? "—"
      : formatDate({
          format: "d M H:i",
          locale: context.translator.locale,
          value: DateTime.formatIso(value),
        });

  const flags: CfpFlags = {
    categories: categories.map((category) => {
      const counts = stats.find((stat) => stat.categoryId === category.id);

      return {
        acceptedCount: counts?.acceptedCount ?? 0,
        hasProposals: (counts?.proposalsCount ?? 0) > 0,
        name: category.name,
        proposalsCount: counts?.proposalsCount ?? 0,
        slug: category.slug,
        window: windowOf({
          end: category.endTime,
          now,
          start: category.startTime,
        }),
        windowLabel:
          category.startTime === null && category.endTime === null
            ? ""
            : `${short(category.startTime)} – ${short(category.endTime)}`,
      };
    }),
    eventSlug: event.slug,
  };

  return flags;
});
