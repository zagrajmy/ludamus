import { DateTime, Schema } from "effect";

import { SessionParticipationStatus } from "./schemas.js";

export const AgendaSpan = Schema.Struct({
  endTime: Schema.DateTimeUtcFromString,
  startTime: Schema.DateTimeUtcFromString,
});

export type AgendaSpan = typeof AgendaSpan.Type;

export const EventSeat = Schema.Struct({
  endTime: Schema.DateTimeUtcFromString,
  sessionId: Schema.Int,
  startTime: Schema.DateTimeUtcFromString,
  status: SessionParticipationStatus,
  userId: Schema.Int,
});

export type EventSeat = typeof EventSeat.Type;

export const overlapsWith = (options: {
  readonly item: AgendaSpan;
  readonly other: AgendaSpan;
}): boolean => {
  const { item, other } = options;

  return (
    (DateTime.isLessThanOrEqualTo(other.startTime, item.startTime) &&
      DateTime.isLessThan(item.startTime, other.endTime)) ||
    (DateTime.isLessThan(other.startTime, item.endTime) &&
      DateTime.isLessThanOrEqualTo(item.endTime, other.endTime))
  );
};

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
        seat.status === "confirmed" &&
        ((DateTime.isGreaterThanOrEqualTo(seat.startTime, span.startTime) &&
          DateTime.isLessThan(seat.startTime, span.endTime)) ||
          (DateTime.isGreaterThan(seat.endTime, span.startTime) &&
            DateTime.isLessThanOrEqualTo(seat.endTime, span.endTime)))
    )
    .map((seat) => seat.userId);

  return [...new Set(ids)].toSorted((a, b) => a - b);
};
