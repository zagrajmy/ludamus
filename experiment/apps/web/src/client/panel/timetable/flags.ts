import { Schema } from "effect";

export const TimetableSession = Schema.Struct({
  facilitators: Schema.Array(Schema.String),
  id: Schema.Int,
  room: Schema.String,
  timeLabel: Schema.String,
  title: Schema.String,
});

export type TimetableSession = typeof TimetableSession.Type;

export const TimetableFlags = Schema.Struct({
  days: Schema.Array(
    Schema.Struct({
      label: Schema.String,
      sessions: Schema.Array(TimetableSession),
    })
  ),
  eventSlug: Schema.String,
});

export type TimetableFlags = typeof TimetableFlags.Type;

export const TimetableModel = Schema.Struct({
  ...TimetableFlags.fields,
  selected: Schema.Option(Schema.Int),
});

export type TimetableModel = typeof TimetableModel.Type;
