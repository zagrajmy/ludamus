import {
  CurrentSphere,
  EventStore,
  SessionId,
  SessionStore,
  TimeSlotStore,
} from "@zagrajmy/core";
import { currentPanelAccess, grantsWrite } from "@zagrajmy/core/panel/access";
import { formatDate } from "@zagrajmy/i18n";
import { DateTime, Effect, Option } from "effect";

import type {
  ProposalAcceptFlags,
  ScheduleBlocker,
} from "../../client/accept/flags.js";
import { PageFlags } from "../../client/model.js";
import { durationLabel } from "../../client/panel/proposals/duration.js";
import { renderSafeMarkdown } from "../markdown.js";
import type { RequestContext } from "../request-context.js";
import { Routed } from "../routed.js";
import { providePanelServices } from "./panel/context.js";

export const ACCEPT_PAGE_PATH =
  /^\/event\/(?<eventSlug>[^/]+)\/session\/(?<sessionId>\d+)\/accept\/$/u;

const LOGIN_URL = "/crowd/login-required/";

const redirectWith = (
  location: string,
  level: "error" | "warning",
  text: string
) => Routed.Redirect({ flashes: [{ level, text }], location, status: 302 });

const blockerOf = (spaces: number, slots: number): ScheduleBlocker => {
  if (spaces === 0) {
    return "spaces";
  }

  return slots === 0 ? "time_slots" : "none";
};

const loadAccept = Effect.fn("ProposalAccept.load")(function* loadAccept(
  context: RequestContext,
  options: Readonly<{ eventSlug: string; sessionId: number }>
) {
  const { t } = context.translator;
  const { locale } = context.translator;
  const sphere = yield* CurrentSphere;
  const sessions = yield* SessionStore;
  const missing = redirectWith("/", "error", t("Session not found."));

  const session = yield* sessions.read(SessionId.make(options.sessionId)).pipe(
    Effect.map(Option.some),
    Effect.catchTag("NotFound", () => Effect.succeed(Option.none()))
  );

  if (Option.isNone(session)) {
    return missing;
  }

  const event = yield* (yield* EventStore)
    .readInSphere({ id: session.value.eventId, sphereId: sphere.id })
    .pipe(
      Effect.map(Option.some),
      Effect.catchTag("NotFound", () => Effect.succeed(Option.none()))
    );

  if (Option.isNone(event) || event.value.slug !== options.eventSlug) {
    return missing;
  }

  const eventHref = `/event/${event.value.slug}/`;

  if (session.value.status !== "pending") {
    return redirectWith(
      eventHref,
      "warning",
      t("This proposal has already been accepted.")
    );
  }

  const access = yield* currentPanelAccess();

  if (!Option.exists(access, grantsWrite)) {
    return redirectWith(
      eventHref,
      "error",
      t("You don't have permission to accept proposals for this event.")
    );
  }

  const proposal = session.value;
  const spaces = yield* sessions.readSpaceOptions(proposal.id);
  const slots = yield* (yield* TimeSlotStore).listByEvent(event.value.id);
  const preferred = yield* sessions.readPreferredTimeSlots(proposal.id);
  const preferredIds = new Set<number>(preferred.map((slot) => slot.id));
  const fieldValues = yield* sessions.readFieldValues(proposal.id);

  const format = (at: DateTime.Utc, pattern: string) =>
    formatDate({ format: pattern, locale, value: DateTime.formatIso(at) });

  const slotLabel = (slot: (typeof slots)[number]) =>
    `${format(slot.startTime, "l, M j · G:i")}–${format(slot.endTime, "G:i")}`;

  const hasPreferred = slots.some((slot) => preferredIds.has(slot.id));
  const length = durationLabel(proposal.duration);

  const slotGroup = (id: number) => {
    if (!hasPreferred) {
      return "";
    }

    return preferredIds.has(id)
      ? t("Preferred by the facilitator")
      : t("Other times");
  };

  const flags: ProposalAcceptFlags = {
    blocker: blockerOf(spaces.length, slots.length),
    contactEmail: proposal.contactEmail,
    descriptionHtml:
      proposal.description === ""
        ? ""
        : renderSafeMarkdown(proposal.description),
    eventName: event.value.name,
    eventSlug: event.value.slug,
    facilitatorName: proposal.facilitatorName,
    facts: [
      ...(proposal.participantsLimit > 0
        ? [{ label: t("Seats"), value: String(proposal.participantsLimit) }]
        : []),
      ...(length === "" ? [] : [{ label: t("Length"), value: length }]),
      ...(proposal.minAge > 0
        ? [
            {
              label: t("Minimum Age"),
              value: t("%(age)s+ years", { age: proposal.minAge }),
            },
          ]
        : []),
      { label: t("Submitted"), value: format(proposal.creationTime, "M j, Y") },
    ],
    fieldValues: fieldValues.map((answer) => ({
      label: answer.fieldName,
      value: Array.isArray(answer.value)
        ? answer.value.join(", ")
        : String(answer.value),
    })),
    locale,
    preferredSlots: preferred.map(
      (slot) =>
        `${format(slot.startTime, "M j, G:i")}–${format(slot.endTime, "G:i")}`
    ),
    sessionId: proposal.id,
    slots: slots.map((slot) => ({
      group: slotGroup(slot.id),
      id: slot.id,
      label: slotLabel(slot),
    })),
    spaces: spaces.map((space) => ({
      group: space.group === "" ? t("Ungrouped") : space.group,
      id: space.id,
      label: space.name,
    })),
    title: proposal.title,
  };

  return Routed.Page({
    flags: PageFlags.ProposalAccept({ flags }),
    status: 200,
  });
});

export const routeProposalAccept = (
  context: RequestContext,
  options: Readonly<{ eventSlug: string; sessionId: number }>
) =>
  Option.isNone(context.viewer)
    ? Effect.succeed(
        Routed.Redirect({
          location: `${LOGIN_URL}?next=${encodeURIComponent(context.url.pathname).replaceAll("%2F", "/")}`,
          status: 302,
        })
      )
    : loadAccept(context, options).pipe(providePanelServices(context));
