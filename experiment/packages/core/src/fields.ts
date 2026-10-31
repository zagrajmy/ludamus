import { Schema } from "effect";

import { EventId, PersonalDataFieldId, SessionFieldId } from "./ids.js";

export const SessionFieldType = Schema.Literals(["text", "select", "checkbox"]);

export type SessionFieldType = typeof SessionFieldType.Type;

export const PersonalFieldType = Schema.Literals([
  "text",
  "select",
  "checkbox",
  "discord",
]);

export type PersonalFieldType = typeof PersonalFieldType.Type;

export const FieldValue = Schema.Union([
  Schema.String,
  Schema.Array(Schema.String),
  Schema.Boolean,
]);

export type FieldValue = typeof FieldValue.Type;

export const FieldOption = Schema.Struct({
  id: Schema.Int,
  label: Schema.String,
  order: Schema.Int,
  value: Schema.String,
});

export type FieldOption = typeof FieldOption.Type;

const FieldColumns = {
  allowCustom: Schema.Boolean,
  eventId: EventId,
  helpText: Schema.String,
  isMultiple: Schema.Boolean,
  isPublic: Schema.Boolean,
  maxLength: Schema.Int,
  name: Schema.String,
  options: Schema.Array(FieldOption),
  order: Schema.Int,
  question: Schema.String,
  slug: Schema.String,
};

export const SessionField = Schema.Struct({
  ...FieldColumns,
  fieldType: SessionFieldType,
  icon: Schema.String,
  id: SessionFieldId,
  showOnCards: Schema.Boolean,
});

export type SessionField = typeof SessionField.Type;

export const PersonalDataField = Schema.Struct({
  ...FieldColumns,
  fieldType: PersonalFieldType,
  id: PersonalDataFieldId,
  isRequired: Schema.Boolean,
});

export type PersonalDataField = typeof PersonalDataField.Type;

export const SessionFieldRequirement = Schema.Struct({
  field: SessionField,
  isRequired: Schema.Boolean,
});

export type SessionFieldRequirement = typeof SessionFieldRequirement.Type;

export const SessionFieldAnswer = Schema.Struct({
  allowCustom: Schema.Boolean,
  fieldIcon: Schema.String,
  fieldId: SessionFieldId,
  fieldName: Schema.String,
  fieldOrder: Schema.Int,
  fieldQuestion: Schema.String,
  fieldSlug: Schema.String,
  fieldType: SessionFieldType,
  isPublic: Schema.Boolean,
  showOnCards: Schema.Boolean,
  value: FieldValue,
});

export type SessionFieldAnswer = typeof SessionFieldAnswer.Type;

export const SessionFieldValueWrite = Schema.Struct({
  fieldId: SessionFieldId,
  value: FieldValue,
});

export type SessionFieldValueWrite = typeof SessionFieldValueWrite.Type;

export const PersonalDataAnswer = Schema.Struct({
  fieldId: PersonalDataFieldId,
  fieldSlug: Schema.String,
  value: FieldValue,
});

export type PersonalDataAnswer = typeof PersonalDataAnswer.Type;

export const PersonalDataValueWrite = Schema.Struct({
  fieldId: PersonalDataFieldId,
  value: FieldValue,
});

export type PersonalDataValueWrite = typeof PersonalDataValueWrite.Type;
