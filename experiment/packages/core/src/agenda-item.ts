import { Schema } from "effect";

import { AgendaItemId, SessionId, SpaceId } from "./ids.js";

export const AgendaItem = Schema.Struct({
  endTime: Schema.DateTimeUtc,
  id: AgendaItemId,
  scheduleConfirmed: Schema.Boolean,
  sessionId: SessionId,
  spaceId: SpaceId,
  startTime: Schema.DateTimeUtc,
});

export type AgendaItem = typeof AgendaItem.Type;

export const NewAgendaItem = Schema.Struct({
  endTime: Schema.DateTimeUtc,
  sessionConfirmed: Schema.Boolean,
  sessionId: SessionId,
  spaceId: SpaceId,
  startTime: Schema.DateTimeUtc,
});

export type NewAgendaItem = typeof NewAgendaItem.Type;
