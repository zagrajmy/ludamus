import { Effect, Predicate, Schema, Stream } from "effect";
import { Subscription } from "foldkit";

import type { EventPageMessage } from "./event-page/message.js";
import {
  clockTicks,
  escapePresses,
  filterPanelSizing,
  narrowViewportChanges,
  outsideFilterClicks,
  scrollerWidthSync,
} from "./event-page/subscriptions.js";
import { Message } from "./message.js";
import type { Model } from "./model.js";
import { colorSchemeChanges } from "./shell/subscriptions.js";

const toEventPage = (message: EventPageMessage) =>
  Message.GotEventPageMessage({ message });

const whileOnEventPage =
  (stream: Stream.Stream<EventPageMessage>) =>
  ({ isEventPage }: { readonly isEventPage: boolean }) =>
    Stream.when(
      stream.pipe(Stream.map(toEventPage)),
      Effect.sync(() => isEventPage)
    );

const eventPageDependencies = (model: Model) => ({
  isEventPage: Predicate.isTagged(model.page, "EventPage"),
});

export const subscriptions = Subscription.make<Model, Message>()((entry) => ({
  colorScheme: Subscription.persistentEntry(
    colorSchemeChanges.pipe(
      Stream.map((message) => Message.GotShellMessage({ message }))
    )
  ),
  eventPageClock: entry(
    { isEventPage: Schema.Boolean },
    {
      dependenciesToStream: whileOnEventPage(clockTicks),
      modelToDependencies: eventPageDependencies,
    }
  ),
  eventPageEscape: entry(
    { isEventPage: Schema.Boolean },
    {
      dependenciesToStream: whileOnEventPage(escapePresses),
      modelToDependencies: eventPageDependencies,
    }
  ),
  eventPageOutsideClicks: entry(
    { isEventPage: Schema.Boolean },
    {
      dependenciesToStream: whileOnEventPage(outsideFilterClicks),
      modelToDependencies: eventPageDependencies,
    }
  ),
  eventPagePanelSize: entry(
    { isPanelOpen: Schema.Boolean },
    {
      dependenciesToStream: ({ isPanelOpen }) =>
        Stream.when(
          filterPanelSizing.pipe(Stream.map(toEventPage)),
          Effect.sync(() => isPanelOpen)
        ),
      modelToDependencies: (model: Model) => ({
        isPanelOpen:
          Predicate.isTagged(model.page, "EventPage") &&
          model.page.model.isPanelOpen &&
          !model.page.model.isNarrow,
      }),
    }
  ),
  eventPageScroller: entry(
    { isEventPage: Schema.Boolean },
    {
      dependenciesToStream: whileOnEventPage(scrollerWidthSync),
      modelToDependencies: eventPageDependencies,
    }
  ),
  eventPageViewport: entry(
    { isEventPage: Schema.Boolean },
    {
      dependenciesToStream: whileOnEventPage(narrowViewportChanges),
      modelToDependencies: eventPageDependencies,
    }
  ),
}));
