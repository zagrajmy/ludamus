import {
  AgendaItem,
  Facilitator,
  FieldOption,
  Location,
  Session,
  SessionFieldAnswer,
  SessionSeats,
  TimeSlot,
  UserSummary,
} from "@zagrajmy/core";
import { Schema } from "effect";

import { SqlBool, SqlDateTime, SqlJson } from "./rows.js";

export const USER_SUMMARY_COLUMNS = (alias: string) => `
  ${alias}.id AS id, ${alias}.name AS name, ${alias}.slug AS slug,
  ${alias}.username AS username, ${alias}.email AS email,
  ${alias}.avatar_url AS avatarUrl, ${alias}.use_gravatar AS useGravatar,
  ${alias}.user_type AS userType, ${alias}.manager_id AS managerId`;

export const UserSummaryRow = Schema.Struct({
  ...UserSummary.fields,
  useGravatar: SqlBool,
});

export const SESSION_COLUMNS = `
  s.id AS id, s.event_id AS eventId, s.category_id AS categoryId,
  s.presenter_id AS presenterId, s.facilitator_name AS facilitatorName,
  s.title AS title, s.slug AS slug, s.ident AS ident,
  s.description AS description, s.contact_email AS contactEmail,
  s.duration AS duration, s.cover_image AS coverImage,
  s.cover_image_original_name AS coverImageOriginalName, s.status AS status,
  s.schedule_confirmed AS scheduleConfirmed,
  s.participants_limit AS participantsLimit, s.min_age AS minAge,
  s.creation_time AS creationTime, s.modification_time AS modificationTime,
  s.deleted_at AS deletedAt`;

export const SessionRow = Schema.Struct({
  ...Session.fields,
  creationTime: SqlDateTime,
  deletedAt: Schema.NullOr(SqlDateTime),
  modificationTime: SqlDateTime,
  scheduleConfirmed: SqlBool,
});

export const AgendaItemRow = Schema.Struct({
  ...AgendaItem.fields,
  endTime: SqlDateTime,
  scheduleConfirmed: SqlBool,
  startTime: SqlDateTime,
});

export const TimeSlotRow = Schema.Struct({
  ...TimeSlot.fields,
  endTime: SqlDateTime,
  startTime: SqlDateTime,
});

export const FieldOptionsJson = SqlJson(Schema.Array(FieldOption));

export const FIELD_ANSWER_COLUMNS = `
  v.session_id AS sessionId, v.value AS value, f.id AS fieldId,
  f.allow_custom AS allowCustom, f.icon AS fieldIcon, f.name AS fieldName,
  f."order" AS fieldOrder, f.question AS fieldQuestion, f.slug AS fieldSlug,
  f.field_type AS fieldType, f.is_public AS isPublic,
  f.show_on_cards AS showOnCards`;

export const FieldAnswerRow = Schema.Struct({
  ...SessionFieldAnswer.fields,
  allowCustom: SqlBool,
  isPublic: SqlBool,
  sessionId: Session.fields.id,
  showOnCards: SqlBool,
  value: SqlJson(SessionFieldAnswer.fields.value),
});

export const LocationRow = Schema.Struct({
  ...Location.fields,
  sortPath: SqlJson(Location.fields.sortPath),
});

export const SeatsRow = Schema.Struct({
  ...SessionSeats.fields,
  eligibleWindowIds: SqlJson(SessionSeats.fields.eligibleWindowIds),
  isFull: SqlBool,
});

export const FACILITATOR_COLUMNS = `
  f.id AS id, f.event_id AS eventId, f.user_id AS userId, f.guild_id AS guildId,
  f.display_name AS displayName, f.slug AS slug, f.ident AS ident,
  f.accreditation_type AS accreditationType, f.organizer_id AS organizerId,
  o.name AS organizerName, f.is_collective AS isCollective,
  f.internal_comment AS internalComment, f.deleted_at AS deletedAt`;

export const FacilitatorRow = Schema.Struct({
  ...Facilitator.fields,
  deletedAt: Schema.NullOr(SqlDateTime),
  isCollective: SqlBool,
});
