import { DateTime, Schema } from "effect";

import { EventId } from "./ids.js";
import { SphereId } from "./sphere.js";

export const EventVisibility = Schema.Literals(["public", "unlisted"]);

export type EventVisibility = typeof EventVisibility.Type;

export const EventSummary = Schema.Struct({
  endTime: Schema.String,
  id: EventId,
  name: Schema.String,
  slug: Schema.String,
  sphereId: SphereId,
  startTime: Schema.String,
});

export type EventSummary = typeof EventSummary.Type;

const EventTimes = {
  endTime: Schema.DateTimeUtc,
  proposalEndTime: Schema.NullOr(Schema.DateTimeUtc),
  proposalStartTime: Schema.NullOr(Schema.DateTimeUtc),
  publicationTime: Schema.NullOr(Schema.DateTimeUtc),
  startTime: Schema.DateTimeUtc,
};

export const Event = Schema.Struct({
  ...EventTimes,
  address: Schema.String,
  allowFacilitatorSessionEdit: Schema.NullOr(Schema.Boolean),
  autoConfirmSessions: Schema.Boolean,
  coverImage: Schema.String,
  coverImageOriginalName: Schema.String,
  description: Schema.String,
  id: EventId,
  logo: Schema.String,
  logoOriginalName: Schema.String,
  name: Schema.String,
  proposalDescription: Schema.String,
  slug: Schema.String,
  sphereId: SphereId,
  useParticipantsLabel: Schema.Boolean,
  useSessionCoverPlaceholders: Schema.Boolean,
  visibility: EventVisibility,
});

export type Event = typeof Event.Type;

export const EventListItem = Schema.Struct({
  ...EventTimes,
  coverImage: Schema.String,
  description: Schema.String,
  id: EventId,
  name: Schema.String,
  sessionCount: Schema.Int,
  slug: Schema.String,
  visibility: EventVisibility,
});

export type EventListItem = typeof EventListItem.Type;

export const EventProposalSettings = Schema.Struct({
  allowAnonymousProposals: Schema.Boolean,
  description: Schema.String,
  id: Schema.Int,
});

export type EventProposalSettings = typeof EventProposalSettings.Type;

interface EventClock {
  readonly endTime: DateTime.Utc;
  readonly proposalEndTime: DateTime.Utc | null;
  readonly proposalStartTime: DateTime.Utc | null;
  readonly publicationTime: DateTime.Utc | null;
  readonly startTime: DateTime.Utc;
  readonly visibility: EventVisibility;
}

export const isPublished = (event: EventClock, now: DateTime.Utc) =>
  event.publicationTime !== null &&
  DateTime.isLessThanOrEqualTo(event.publicationTime, now);

export const isOpen = (event: EventClock, now: DateTime.Utc) =>
  isPublished(event, now) || event.visibility === "unlisted";

export const isLive = (event: EventClock, now: DateTime.Utc) =>
  DateTime.isLessThan(event.startTime, now) &&
  DateTime.isLessThan(now, event.endTime);

export const isEnded = (event: EventClock, now: DateTime.Utc) =>
  DateTime.isLessThan(event.endTime, now);

export const isProposalActive = (event: EventClock, now: DateTime.Utc) =>
  isOpen(event, now) &&
  event.proposalStartTime !== null &&
  event.proposalEndTime !== null &&
  DateTime.isLessThanOrEqualTo(event.proposalStartTime, now) &&
  DateTime.isLessThanOrEqualTo(now, event.proposalEndTime);

export const isProposalWindowOpen = (event: EventClock, now: DateTime.Utc) =>
  event.proposalStartTime !== null &&
  event.proposalEndTime !== null &&
  DateTime.isLessThan(event.proposalStartTime, now) &&
  DateTime.isLessThan(now, event.proposalEndTime);
