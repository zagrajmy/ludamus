import { CurrentSphere, CurrentViewer, SphereId, UserId } from "@zagrajmy/core";
import type { Event } from "@zagrajmy/core";
import { formatDate } from "@zagrajmy/i18n";
import { DateTime, Effect, Option } from "effect";

import type {
  PanelChromeFlags,
  PanelNav,
} from "../../../client/panel/chrome.js";
import type { RequestContext } from "../../request-context.js";

export const providePanelServices =
  (context: RequestContext) =>
  <A, E, R>(effect: Effect.Effect<A, E, R>) =>
    effect.pipe(
      Effect.provideService(CurrentSphere, {
        domain: context.sphere.domain,
        id: SphereId.make(context.sphere.id),
        name: context.sphere.name,
      }),
      Effect.provideService(
        CurrentViewer,
        context.viewer.pipe(
          Option.map((viewer) => ({
            id: UserId.make(viewer.id),
            isSuperuser: viewer.isSuperuser === 1,
          }))
        )
      )
    );

const localDay = (
  context: RequestContext,
  value: DateTime.Utc,
  format: string
) =>
  formatDate({
    format,
    locale: context.translator.locale,
    value: DateTime.formatIso(value),
  });

export const eventDateLabel = (context: RequestContext, event: Event) => {
  const start = localDay(context, event.startTime, "Ymd");
  const end = localDay(context, event.endTime, "Ymd");

  return start === end
    ? localDay(context, event.startTime, "d M Y")
    : `${localDay(context, event.startTime, "d M")} - ${localDay(context, event.endTime, "d M Y")}`;
};

export const eventChrome = (
  context: RequestContext,
  options: Readonly<{
    activeNav: PanelNav;
    event: Event;
    events: readonly Event[];
    isProposalActive: boolean;
  }>
): PanelChromeFlags => ({
  activeNav: options.activeNav,
  currentEvent: Option.some({
    dateLabel: eventDateLabel(context, options.event),
    isProposalActive: options.isProposalActive,
    name: options.event.name,
    slug: options.event.slug,
  }),
  events: options.events.map((event) => ({
    name: event.name,
    slug: event.slug,
  })),
  locale: context.translator.locale,
});
