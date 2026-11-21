import { Duration, Effect, Option, Schedule, Stream } from "effect";
import { Dom } from "foldkit";

import { EventPageMessage } from "./message.js";

export const narrowViewportChanges = Dom.streamFromMediaQuery({
  mapMatches: (isNarrow) => EventPageMessage.ChangedViewport({ isNarrow }),
  query: "(max-width: 30rem)",
});

export const escapePresses = Stream.suspend(() =>
  Dom.streamFromEventFilterMap({
    filterMapEvent: (event) =>
      event.key === "Escape" && !event.defaultPrevented
        ? Option.some(EventPageMessage.PressedEscape())
        : Option.none(),
    target: document,
    type: "keydown",
  })
);

const outsideFilters = (target: EventTarget | null) =>
  target instanceof Element &&
  target.closest(".filters-popover-wrapper") === null;

export const outsideFilterClicks = Stream.suspend(() =>
  Stream.merge(
    Dom.streamFromEventFilterMap({
      filterMapEvent: (event) =>
        outsideFilters(event.target)
          ? Option.some(EventPageMessage.ClickedOutsideFilters())
          : Option.none(),
      target: document,
      type: "click",
    }),
    Dom.streamFromEventFilterMap({
      filterMapEvent: (event) =>
        outsideFilters(event.target)
          ? Option.some(EventPageMessage.ClickedOutsideFilters())
          : Option.none(),
      target: document,
      type: "focusin",
    })
  )
);

const TICK = Duration.seconds(30);

export const clockTicks = Stream.fromEffectSchedule(
  Effect.sync(() => EventPageMessage.Ticked({ now: Date.now() })),
  Schedule.spaced(TICK)
);

export const scrollerWidthSync = Stream.callback<EventPageMessage>(() =>
  Effect.acquireRelease(
    Effect.sync(() => {
      const scroller = document.querySelector<HTMLElement>("#app-scroll");

      const observer = new ResizeObserver(() => {
        if (scroller !== null) {
          scroller.style.setProperty(
            "--app-scroll-w",
            `${scroller.clientWidth}px`
          );
        }
      });

      if (scroller !== null) {
        observer.observe(scroller);
      }

      return observer;
    }),
    (observer) =>
      Effect.sync(() => {
        observer.disconnect();
      })
  )
);

const sizeFilterPanel = () => {
  const panel = document.querySelector<HTMLElement>("#filter-panel");
  const toggle = document.querySelector("#filter-toggle");

  if (panel === null || toggle === null) {
    return;
  }

  const viewport = window.visualViewport;

  const bottom =
    viewport === null
      ? window.innerHeight
      : viewport.offsetTop + viewport.height;

  const room = Math.max(0, bottom - toggle.getBoundingClientRect().bottom - 20);

  panel.style.setProperty("--filter-panel-room", `${room}px`);
};

export const filterPanelSizing = Stream.callback<EventPageMessage>(() =>
  Effect.acquireRelease(
    Effect.sync(() => {
      let queued = false;

      const schedule = () => {
        if (queued) {
          return;
        }

        queued = true;
        requestAnimationFrame(() => {
          queued = false;
          sizeFilterPanel();
        });
      };

      sizeFilterPanel();
      window.addEventListener("resize", schedule, {
        capture: true,
        passive: true,
      });
      window.addEventListener("scroll", schedule, {
        capture: true,
        passive: true,
      });

      return schedule;
    }),
    (schedule) =>
      Effect.sync(() => {
        window.removeEventListener("resize", schedule, { capture: true });
        window.removeEventListener("scroll", schedule, { capture: true });
      })
  )
);
