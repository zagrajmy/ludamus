import { formatDate } from "@zagrajmy/i18n";
import type { Locale } from "@zagrajmy/i18n";
import { DateTime, Effect, Option, Schema } from "effect";
import { Command, Dom } from "foldkit";
import { load, pushUrl, replaceUrl } from "foldkit/navigation";

import { Backend } from "../rpc.js";
import type { RosterEntry } from "./flags.js";
import { EventPageMessage } from "./message.js";

export const QueryUpdate = Schema.Tuple([
  Schema.String,
  Schema.NullOr(Schema.String),
]);

export type QueryUpdate = typeof QueryUpdate.Type;

const withUpdates = (options: {
  readonly hash: string;
  readonly updates: readonly QueryUpdate[];
}) => {
  const params = new URLSearchParams(window.location.search);

  for (const [name, value] of options.updates) {
    if (value === null || value === "") {
      params.delete(name);
    } else {
      params.set(name, value);
    }
  }

  const search = params.toString();

  return `${window.location.pathname}${search === "" ? "" : `?${search}`}${options.hash}`;
};

const currentLocation = () =>
  `${window.location.pathname}${window.location.search}${window.location.hash}`;

export const ReplaceQuery = Command.define("ReplaceQuery", {
  args: { updates: Schema.Array(QueryUpdate) },
  execute: ({ updates }) =>
    Effect.suspend(() => {
      const target = withUpdates({ hash: window.location.hash, updates });

      return target === currentLocation() ? Effect.void : replaceUrl(target);
    }).pipe(Effect.as(EventPageMessage.CompletedUrlUpdate())),
  messages: [EventPageMessage.CompletedUrlUpdate],
});

export const PushQuery = Command.define("PushQuery", {
  args: { updates: Schema.Array(QueryUpdate) },
  execute: ({ updates }) =>
    Effect.suspend(() => {
      const target = withUpdates({ hash: "", updates });

      return target === currentLocation() ? Effect.void : pushUrl(target);
    }).pipe(Effect.as(EventPageMessage.CompletedUrlUpdate())),
  messages: [EventPageMessage.CompletedUrlUpdate],
});

export const LoadHref = Command.define("LoadHref", {
  args: { href: Schema.String },
  execute: ({ href }) =>
    load(href).pipe(Effect.as(EventPageMessage.CompletedUrlUpdate())),
  messages: [EventPageMessage.CompletedUrlUpdate],
});

export const SESSION_DIALOG_SELECTOR = "#session-dialog";

const MORPH_CONTAINER = "session-morph";

const PAGE_LIVE = "vt-page-live";

const SUPPRESSED = "session-suppressed";

const sessionSurface = (sessionId: number) => {
  const surface = document.querySelector(
    `.session[data-session-id="${String(sessionId)}"]`
  );

  return surface instanceof HTMLElement ? surface : null;
};

const prefersReducedMotion = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const canMorph = (surface: HTMLElement | null): surface is HTMLElement =>
  surface !== null &&
  surface.dataset.noMorph === undefined &&
  typeof document.startViewTransition === "function" &&
  !prefersReducedMotion();

const setSubMorph = (root: HTMLElement, active: boolean) => {
  for (const element of root.querySelectorAll<HTMLElement>("[data-morph]")) {
    element.style.viewTransitionName = active
      ? `morph-${element.dataset.morph ?? ""}`
      : "";
  }
};

const setContainerMorph = (root: HTMLElement, active: boolean) => {
  root.style.viewTransitionName = active ? MORPH_CONTAINER : "";
};

const setMorph = (root: HTMLElement, active: boolean) => {
  setContainerMorph(root, active);
  setSubMorph(root, active);
};

const resetScroll = (dialog: Element) => {
  for (const element of dialog.querySelectorAll("*")) {
    if (element.scrollTop !== 0) {
      element.scrollTop = 0;
    }
  }
};

const runTransition = (options: {
  readonly settle: () => void;
  readonly swap: () => void;
}) =>
  Effect.promise(async () => {
    document.documentElement.classList.add(PAGE_LIVE);
    const transition = document.startViewTransition(options.swap);
    transition.ready.catch(() => null);

    try {
      await transition.finished;
    } catch {
      return;
    } finally {
      options.settle();
      document.documentElement.classList.remove(PAGE_LIVE);
    }
  });

const presentDialog = Dom.showDialog(SESSION_DIALOG_SELECTOR, {
  isModal: false,
}).pipe(
  Effect.tap((acquired) => (acquired ? Dom.lockScroll : Effect.void)),
  Effect.tap(() =>
    Effect.sync(() => {
      const dialog = document.querySelector(SESSION_DIALOG_SELECTOR);

      if (dialog !== null) {
        resetScroll(dialog);
      }
    })
  ),
  Effect.ignore
);

export const ShowSessionDialog = Command.define("ShowSessionDialog", {
  args: { animate: Schema.Boolean, sessionId: Schema.Int },
  execute: ({ animate, sessionId }) =>
    Effect.gen(function* showSessionDialog() {
      const surface = sessionSurface(sessionId);
      const dialog = document.querySelector(SESSION_DIALOG_SELECTOR);

      if (!animate || !canMorph(surface) || !(dialog instanceof HTMLElement)) {
        surface?.classList.add(SUPPRESSED);

        return yield* presentDialog;
      }

      setMorph(surface, true);

      yield* runTransition({
        settle: () => {
          setMorph(dialog, false);
          surface.style.transition = "";
        },
        swap: () => {
          setMorph(surface, false);
          surface.classList.add(SUPPRESSED);
          surface.style.transition = "none";

          if (dialog instanceof HTMLDialogElement) {
            dialog.show();
          }

          resetScroll(dialog);
          setMorph(dialog, true);
        },
      });

      return yield* presentDialog;
    }).pipe(Effect.as(EventPageMessage.CompletedFocus())),
  messages: [EventPageMessage.CompletedFocus],
});

const dismissDialog = Dom.closeDialog(SESSION_DIALOG_SELECTOR).pipe(
  Effect.tap((released) => (released ? Dom.unlockScroll : Effect.void)),
  Effect.ignore
);

const releaseDialog = Dom.releaseDialogResources(
  SESSION_DIALOG_SELECTOR.slice(1)
).pipe(
  Effect.tap((released) => (released ? Dom.unlockScroll : Effect.void)),
  Effect.ignore
);

const isAppleTouch = () =>
  /iPhone|iPad|iPod/u.test(navigator.userAgent) ||
  (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

export const CloseSessionDialog = Command.define("CloseSessionDialog", {
  args: { sessionId: Schema.Int },
  execute: ({ sessionId }) =>
    Effect.gen(function* closeSessionDialog() {
      const surface = sessionSurface(sessionId);
      const dialog = document.querySelector(SESSION_DIALOG_SELECTOR);

      if (
        isAppleTouch() ||
        !canMorph(surface) ||
        !(dialog instanceof HTMLElement)
      ) {
        surface?.classList.remove(SUPPRESSED);

        return yield* dismissDialog;
      }

      setContainerMorph(dialog, true);

      yield* runTransition({
        settle: () => {
          setContainerMorph(surface, false);
        },
        swap: () => {
          if (dialog instanceof HTMLDialogElement) {
            dialog.close();
          }

          setContainerMorph(dialog, false);
          surface.classList.remove(SUPPRESSED);
          setContainerMorph(surface, true);
        },
      });

      return yield* releaseDialog;
    }).pipe(Effect.as(EventPageMessage.CompletedFocus())),
  messages: [EventPageMessage.CompletedFocus],
});

export const ReadClock = Command.define("ReadClock", {
  execute: Effect.sync(() =>
    EventPageMessage.GotBootClock({ now: Date.now() })
  ),
  messages: [EventPageMessage.GotBootClock],
});

export const ScrollToElement = Command.define("ScrollToElement", {
  args: { selector: Schema.String },
  execute: ({ selector }) =>
    Dom.scrollIntoViewAfterPaint(selector, { block: "start" }).pipe(
      Effect.ignore,
      Effect.as(EventPageMessage.CompletedScroll())
    ),
  messages: [EventPageMessage.CompletedScroll],
});

export const FocusElement = Command.define("FocusElement", {
  args: { selector: Schema.String },
  execute: ({ selector }) =>
    Dom.focus(selector, { preventScroll: true }).pipe(
      Effect.ignore,
      Effect.as(EventPageMessage.CompletedFocus())
    ),
  messages: [EventPageMessage.CompletedFocus],
});

export const BlurActiveElement = Command.define("BlurActiveElement", {
  execute: Effect.sync(() => {
    const active = document.activeElement;

    if (active instanceof HTMLElement) {
      active.blur();
    }

    return EventPageMessage.CompletedFocus();
  }),
  messages: [EventPageMessage.CompletedFocus],
});

export const SettleComboboxFocus = Command.define("SettleComboboxFocus", {
  args: { selector: Schema.String },
  execute: ({ selector }) =>
    Effect.sync(() => {
      const input = document.querySelector(selector);

      if (!(input instanceof HTMLInputElement)) {
        return EventPageMessage.CompletedFocus();
      }

      if (window.matchMedia("(pointer: coarse)").matches) {
        input.blur();
      } else {
        input.focus({ preventScroll: true });
        input.select();
      }

      return EventPageMessage.CompletedFocus();
    }),
  messages: [EventPageMessage.CompletedFocus],
});

export const SelectInputText = Command.define("SelectInputText", {
  args: { selector: Schema.String },
  execute: ({ selector }) =>
    Effect.sync(() => {
      const input = document.querySelector(selector);

      if (input instanceof HTMLInputElement) {
        input.select();
      }

      return EventPageMessage.CompletedFocus();
    }),
  messages: [EventPageMessage.CompletedFocus],
});

const waitingLabel = (locale: Locale, created: DateTime.Utc) =>
  formatDate({
    format: "M j, G:i",
    locale,
    value: DateTime.formatIso(created),
  });

export const ReadRoster = Command.define("ReadRoster", {
  args: {
    locale: Schema.Literals(["en", "pl"]),
    sessionId: Schema.Int,
    slug: Schema.String,
  },
  execute: ({ locale, sessionId, slug }) =>
    Effect.gen(function* readRoster() {
      const backend = yield* Backend;
      const card = yield* backend.readEventSession({ sessionId, slug });

      const entries: readonly RosterEntry[] = card.participations.map(
        (seat) => ({
          createdLabel: waitingLabel(locale, seat.creationTime),
          person: {
            avatarUrl:
              seat.user.avatarUrl === ""
                ? Option.none()
                : Option.some(seat.user.avatarUrl),
            name: seat.user.name === "" ? seat.user.username : seat.user.name,
          },
          status: seat.status,
        })
      );

      return EventPageMessage.SucceededReadRoster({ entries, sessionId });
    }).pipe(
      Effect.provide(Backend.layer),
      Effect.catchCause(() =>
        Effect.succeed(EventPageMessage.FailedReadRoster({ sessionId }))
      )
    ),
  messages: [
    EventPageMessage.SucceededReadRoster,
    EventPageMessage.FailedReadRoster,
  ],
});
