import {
  EventId,
  FacilitatorId,
  FieldStore,
  FieldValue,
  PersonalDataField,
  PersonalDataFieldId,
  PersonalDataValueWrite,
} from "@zagrajmy/core";
import { DateTime, Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import {
  SESSION_FIELD_COLUMNS,
  SessionFieldRow,
} from "./proposal-category-store.js";
import {
  decodeInput,
  decodeOne,
  decodeRows,
  pythonJson,
  SqlBool,
  SqlJson,
  storeFailure,
  toSqlDateTime,
} from "./rows.js";
import { FieldOptionsJson } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const PersonalFieldRow = Schema.Struct({
  ...PersonalDataField.fields,
  allowCustom: SqlBool,
  isMultiple: SqlBool,
  isPublic: SqlBool,
  isRequired: SqlBool,
  options: FieldOptionsJson,
});

const PERSONAL_FIELD_COLUMNS = `
  f.id AS id, f.event_id AS eventId, f.name AS name, f.question AS question,
  f.slug AS slug, f.field_type AS fieldType, f.is_multiple AS isMultiple,
  f.allow_custom AS allowCustom, f.max_length AS maxLength, f."order" AS "order",
  f.help_text AS helpText, f.is_public AS isPublic, f.is_required AS isRequired,
  (SELECT json_group_array(json_object('id', o.id, 'label', o.label, 'value', o.value, 'order', o."order")
     ORDER BY o."order", o.label)
   FROM personal_data_field_option o WHERE o.field_id = f.id) AS options`;

const AnswerRow = Schema.Struct({
  fieldId: PersonalDataFieldId,
  fieldSlug: Schema.String,
  value: SqlJson(FieldValue),
});

const SlugInput = Schema.Struct({ eventId: EventId, slug: Schema.String });

const OwnerInput = Schema.Struct({
  eventId: EventId,
  facilitatorId: FacilitatorId,
});

const SaveInput = Schema.Struct({
  eventId: EventId,
  facilitatorId: FacilitatorId,
  values: Schema.Array(PersonalDataValueWrite),
});

export const makeFieldStore = Effect.gen(function* makeFieldStore() {
  const sql = yield* SqlClient;
  const sessionColumns = sql.literal(SESSION_FIELD_COLUMNS);
  const personalColumns = sql.literal(PERSONAL_FIELD_COLUMNS);

  const listSessionFields = Effect.fn("FieldStore.listSessionFields")(
    function* listSessionFields(eventId: EventId) {
      const valid = yield* decodeInput(
        "FieldStore.listSessionFields",
        EventId
      )(eventId);

      return yield* sql`
      SELECT ${sessionColumns} FROM session_field f WHERE f.event_id = ${valid}
      ORDER BY f."order", f.name, f.id LIMIT ${ROW_BUDGET.eventFields}
    `.pipe(decodeRows("FieldStore.listSessionFields", SessionFieldRow));
    }
  );

  const readSessionFieldBySlug = Effect.fn("FieldStore.readSessionFieldBySlug")(
    function* readSessionFieldBySlug(options: typeof SlugInput.Type) {
      const input = yield* decodeInput(
        "FieldStore.readSessionFieldBySlug",
        SlugInput
      )(options);

      return yield* sql`
      SELECT ${sessionColumns} FROM session_field f WHERE f.event_id = ${input.eventId} AND f.slug = ${input.slug}
    `.pipe(
        decodeOne({
          entity: "SessionField",
          key: input.slug,
          operation: "FieldStore.readSessionFieldBySlug",
          row: SessionFieldRow,
        })
      );
    }
  );

  const listPersonalDataFields = Effect.fn("FieldStore.listPersonalDataFields")(
    function* listPersonalDataFields(eventId: EventId) {
      const valid = yield* decodeInput(
        "FieldStore.listPersonalDataFields",
        EventId
      )(eventId);

      return yield* sql`
      SELECT ${personalColumns} FROM personal_data_field f WHERE f.event_id = ${valid}
      ORDER BY f."order", f.name, f.id LIMIT ${ROW_BUDGET.eventFields}
    `.pipe(decodeRows("FieldStore.listPersonalDataFields", PersonalFieldRow));
    }
  );

  const readPersonalDataFieldBySlug = Effect.fn(
    "FieldStore.readPersonalDataFieldBySlug"
  )(function* readPersonalDataFieldBySlug(options: typeof SlugInput.Type) {
    const input = yield* decodeInput(
      "FieldStore.readPersonalDataFieldBySlug",
      SlugInput
    )(options);

    return yield* sql`
        SELECT ${personalColumns} FROM personal_data_field f WHERE f.event_id = ${input.eventId} AND f.slug = ${input.slug}
      `.pipe(
      decodeOne({
        entity: "PersonalDataField",
        key: input.slug,
        operation: "FieldStore.readPersonalDataFieldBySlug",
        row: PersonalFieldRow,
      })
    );
  });

  const readPersonalData = Effect.fn("FieldStore.readPersonalData")(
    function* readPersonalData(options: typeof OwnerInput.Type) {
      const input = yield* decodeInput(
        "FieldStore.readPersonalData",
        OwnerInput
      )(options);

      return yield* sql`
      SELECT v.field_id AS fieldId, f.slug AS fieldSlug, v.value AS value
      FROM personal_data_field_value v JOIN personal_data_field f ON f.id = v.field_id
      WHERE v.facilitator_id = ${input.facilitatorId} AND v.event_id = ${input.eventId}
      ORDER BY f."order", f.name, v.id LIMIT ${ROW_BUDGET.eventFields}
    `.pipe(decodeRows("FieldStore.readPersonalData", AnswerRow));
    }
  );

  const savePersonalData = Effect.fn("FieldStore.savePersonalData")(
    function* savePersonalData(options: typeof SaveInput.Type) {
      const input = yield* decodeInput(
        "FieldStore.savePersonalData",
        SaveInput
      )(options);

      if (input.values.length === 0) {
        return;
      }

      const now = toSqlDateTime(yield* DateTime.now);
      yield* sql`
      INSERT INTO personal_data_field_value ${sql.insert(
        input.values.map((value) => ({
          creation_time: now,
          event_id: input.eventId,
          facilitator_id: input.facilitatorId,
          field_id: value.fieldId,
          modification_time: now,
          value: pythonJson(value.value),
        }))
      )}
      ON CONFLICT (facilitator_id, event_id, field_id) WHERE facilitator_id IS NOT NULL
      DO UPDATE SET value = excluded.value, modification_time = excluded.modification_time
    `.pipe(storeFailure("FieldStore.savePersonalData"));
    }
  );

  return FieldStore.of({
    listPersonalDataFields,
    listSessionFields,
    readPersonalData,
    readPersonalDataFieldBySlug,
    readSessionFieldBySlug,
    savePersonalData,
  });
});

export const FieldStoreLive = Layer.effect(FieldStore, makeFieldStore);
