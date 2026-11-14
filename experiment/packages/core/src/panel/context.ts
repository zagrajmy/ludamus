import { Effect } from "effect";

import { CurrentSphere } from "../ports/current-sphere.js";
import { EventStore } from "../ports/event-store.js";
import { PanelStore } from "../ports/panel-store.js";
import {
  proposalsOpen,
  requirePanelAccess,
  requirePanelEvent,
} from "./access.js";
import type { PanelMode } from "./access.js";

export const loadPanelEventChrome = Effect.fn("Panel.loadEventChrome")(
  function* loadPanelEventChrome(options: {
    readonly mode: PanelMode;
    readonly slug: string;
  }) {
    const scoped = yield* requirePanelEvent(options);
    const sphere = yield* CurrentSphere;
    const events = yield* (yield* EventStore).listBySphere(sphere.id);
    const isProposalActive = yield* proposalsOpen(scoped.event);

    return { ...scoped, events, isProposalActive };
  }
);

export const loadPanelSphereChrome = Effect.fn("Panel.loadSphereChrome")(
  function* loadPanelSphereChrome(mode: PanelMode) {
    const access = yield* requirePanelAccess(mode);
    const sphere = yield* CurrentSphere;
    const events = yield* (yield* EventStore).listBySphere(sphere.id);

    return { access, events };
  }
);

export const loadPanelDashboard = Effect.fn("Panel.loadDashboard")(
  function* loadPanelDashboard(slug: string) {
    const chrome = yield* loadPanelEventChrome({ mode: "read", slug });
    const stats = yield* (yield* PanelStore).eventStats(chrome.event.id);

    return { ...chrome, stats };
  }
);
