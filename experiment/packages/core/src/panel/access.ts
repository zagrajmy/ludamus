import { DateTime, Effect, Option } from "effect";

import { isProposalActive } from "../event.js";
import type { Event } from "../event.js";
import { CurrentSphere } from "../ports/current-sphere.js";
import { CurrentViewer } from "../ports/current-viewer.js";
import type { Viewer } from "../ports/current-viewer.js";
import { EventStore } from "../ports/event-store.js";
import { PanelStore } from "../ports/panel-store.js";
import { PanelAccessDenied } from "./schemas.js";
import type { PanelRole } from "./schemas.js";

export type PanelMode = "read" | "write";

export interface PanelAccess {
  readonly role: Option.Option<PanelRole>;
  readonly viewer: Viewer;
}

export const grantsRead = (access: PanelAccess) =>
  access.viewer.isSuperuser || Option.isSome(access.role);

export const grantsWrite = (access: PanelAccess) =>
  access.viewer.isSuperuser || Option.contains(access.role, "manager");

export const refusalFor = (
  access: Option.Option<PanelAccess>,
  mode: PanelMode
): Option.Option<PanelAccessDenied> => {
  if (Option.isNone(access)) {
    return Option.some(new PanelAccessDenied({ reason: "sign_in" }));
  }

  if (!grantsRead(access.value)) {
    return Option.some(new PanelAccessDenied({ reason: "no_panel_access" }));
  }

  return mode === "write" && !grantsWrite(access.value)
    ? Option.some(new PanelAccessDenied({ reason: "read_only" }))
    : Option.none();
};

export const currentPanelAccess = Effect.fn("Panel.currentAccess")(
  function* currentPanelAccess() {
    const viewer = yield* CurrentViewer;

    if (Option.isNone(viewer)) {
      return Option.none<PanelAccess>();
    }

    const sphere = yield* CurrentSphere;
    const panel = yield* PanelStore;

    const role = yield* panel.roleOf({
      sphereId: sphere.id,
      userId: viewer.value.id,
    });

    return Option.some<PanelAccess>({ role, viewer: viewer.value });
  }
);

export const requirePanelAccess = Effect.fn("Panel.requireAccess")(
  function* requirePanelAccess(mode: PanelMode) {
    const access = yield* currentPanelAccess();
    const refusal = refusalFor(access, mode);

    if (Option.isSome(refusal)) {
      return yield* refusal.value;
    }

    return yield* Option.match(access, {
      onNone: () => new PanelAccessDenied({ reason: "sign_in" }),
      onSome: Effect.succeed,
    });
  }
);

export interface PanelEvent {
  readonly access: PanelAccess;
  readonly event: Event;
}

export const requirePanelEvent = Effect.fn("Panel.requireEvent")(
  function* requirePanelEvent(options: {
    readonly mode: PanelMode;
    readonly slug: string;
  }) {
    const access = yield* requirePanelAccess(options.mode);
    const sphere = yield* CurrentSphere;
    const events = yield* EventStore;

    const event = yield* events.readBySlug({
      slug: options.slug,
      sphereId: sphere.id,
    });

    const scoped: PanelEvent = { access, event };

    return scoped;
  }
);

export const proposalsOpen = Effect.fn("Panel.proposalsOpen")(
  function* proposalsOpen(event: Event) {
    const now = yield* DateTime.now;

    return isProposalActive(event, now);
  }
);
