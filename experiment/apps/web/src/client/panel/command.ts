import { Effect, Option, Schema } from "effect";
import { Command } from "foldkit";

import { Backend, keepAliveBackend } from "../rpc.js";
import { PanelAction } from "./action.js";
import { PanelCategory, panelCategories } from "./chrome.js";
import type { PanelCategory as Category } from "./chrome.js";
import { FlashNote, catchPanelFailure } from "./failure.js";
import { PanelMessage } from "./message.js";
import { navigateWithFlash, watchForLeaving } from "./navigate.js";

export const FOLD_KEY = "panel-sidebar-folded";

export const categoryKey = (category: Category) => `panel-cat-${category}`;

const safely = <A>(read: () => A, fallback: A) =>
  Effect.sync(() => {
    try {
      return read();
    } catch {
      return fallback;
    }
  });

export const NavigateWithFlash = Command.define("NavigateWithFlash", {
  args: { href: Schema.String, notes: Schema.Array(FlashNote) },
  execute: ({ href, notes }) =>
    navigateWithFlash(href, notes).pipe(Effect.as(PanelMessage.LeftPanel())),
  messages: [PanelMessage.LeftPanel],
});

export const ReadStoredCategories = Command.define("ReadStoredCategories", {
  execute: safely(
    () =>
      panelCategories.filter(
        (category) => window.localStorage.getItem(categoryKey(category)) === "1"
      ),
    []
  ).pipe(
    Effect.map((collapsed) => PanelMessage.LoadedStoredCategories({ collapsed }))
  ),
  messages: [PanelMessage.LoadedStoredCategories],
});

export const StoreCategory = Command.define("StoreCategory", {
  args: { category: PanelCategory, collapsed: Schema.Boolean },
  execute: ({ category, collapsed }) =>
    safely(() => {
      document.documentElement.classList.toggle(`catc-${category}`, collapsed);
      window.localStorage.setItem(categoryKey(category), collapsed ? "1" : "0");

      return true;
    }, false).pipe(Effect.as(PanelMessage.StoredChrome())),
  messages: [PanelMessage.StoredChrome],
});

export const ToggleFold = Command.define("ToggleFold", {
  execute: safely(() => {
    const folded = document.documentElement.toggleAttribute("data-folded");
    window.localStorage.setItem(FOLD_KEY, folded ? "1" : "0");

    return true;
  }, false).pipe(Effect.as(PanelMessage.StoredChrome())),
  messages: [PanelMessage.StoredChrome],
});

const runAction = (action: PanelAction) =>
  Effect.gen(function* runPanelAction() {
    yield* watchForLeaving;
    const backend = yield* Backend;

    yield* PanelAction.match(action, {
      ChangeProposalStatus: ({ eventSlug, proposalId, status }) =>
        backend
          .changeProposalStatus({ eventSlug, proposalId, status })
          .pipe(Effect.asVoid),
      DeleteFacilitator: ({ eventSlug, facilitatorSlug }) =>
        backend
          .deleteFacilitator({ eventSlug, facilitatorSlug })
          .pipe(Effect.asVoid),
      DeleteProposal: ({ eventSlug, proposalId }) =>
        backend.deleteProposal({ eventSlug, proposalId }).pipe(Effect.asVoid),
      DeleteTrack: ({ eventSlug, trackSlug }) =>
        backend.deleteTrack({ eventSlug, trackSlug }).pipe(Effect.asVoid),
      RestoreFacilitator: ({ eventSlug, facilitatorSlug }) =>
        backend
          .restoreFacilitator({ eventSlug, facilitatorSlug })
          .pipe(Effect.asVoid),
      RestoreProposal: ({ eventSlug, proposalId }) =>
        backend.restoreProposal({ eventSlug, proposalId }).pipe(Effect.asVoid),
    });

    return PanelMessage.CompletedAction({ action, failure: Option.none() });
  }).pipe(Effect.provide(keepAliveBackend));

export const RunAction = Command.define("RunAction", {
  args: { action: PanelAction },
  execute: ({ action }) =>
    catchPanelFailure(runAction(action), (failure) =>
      PanelMessage.CompletedAction({ action, failure: Option.some(failure) })
    ),
  messages: [PanelMessage.CompletedAction],
});
