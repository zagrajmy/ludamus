import { DateTime, Schema } from "effect";

import {
  OCCUPYING_PARTICIPATION_STATUSES,
  ParticipationStatus,
} from "../participation.js";

export const AgendaSpan = Schema.Struct({
  endTime: Schema.DateTimeUtcFromString,
  startTime: Schema.DateTimeUtcFromString,
});

export type AgendaSpan = typeof AgendaSpan.Type;

export const EventSeat = Schema.Struct({
  endTime: Schema.DateTimeUtcFromString,
  sessionId: Schema.Int,
  startTime: Schema.DateTimeUtcFromString,
  status: ParticipationStatus,
  userId: Schema.Int,
});

export type EventSeat = typeof EventSeat.Type;

export const overlapsWith = (options: {
  readonly item: AgendaSpan;
  readonly other: AgendaSpan;
}): boolean =>
  DateTime.isLessThan(options.other.startTime, options.item.endTime) &&
  DateTime.isGreaterThan(options.other.endTime, options.item.startTime);

export const conflictedUserIds = (options: {
  readonly sessionId: number;
  readonly span: AgendaSpan | null;
  readonly userIds: readonly number[];
  readonly seats: readonly EventSeat[];
}): readonly number[] => {
  const { span } = options;

  if (options.userIds.length === 0 || span === null) {
    return [];
  }

  const ids = options.seats
    .filter(
      (seat) =>
        seat.sessionId !== options.sessionId &&
        options.userIds.includes(seat.userId) &&
        OCCUPYING_PARTICIPATION_STATUSES.includes(seat.status) &&
        overlapsWith({ item: span, other: seat })
    )
    .map((seat) => seat.userId);

  return [...new Set(ids)].toSorted((a, b) => a - b);
};
