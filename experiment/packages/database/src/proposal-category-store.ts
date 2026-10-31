import {
  CategoryStats,
  EventId,
  ProposalCategory,
  ProposalCategoryId,
  ProposalCategoryStore,
  SessionField,
} from "@zagrajmy/core";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";
import type { Fragment } from "effect/sql/Statement";

import {
  decodeInput,
  decodeOne,
  decodeRows,
  SqlBool,
  SqlDateTime,
  SqlDuration,
  SqlJson,
} from "./rows.js";
import { FieldOptionsJson, TimeSlotRow } from "./shared-rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const CategoryRow = Schema.Struct({
  ...ProposalCategory.fields,
  durations: SqlJson(ProposalCategory.fields.durations),
  endTime: Schema.NullOr(SqlDateTime),
  offerClaimWindow: SqlDuration,
  startTime: Schema.NullOr(SqlDateTime),
});

export const SessionFieldRow = Schema.Struct({
  ...SessionField.fields,
  allowCustom: SqlBool,
  isMultiple: SqlBool,
  isPublic: SqlBool,
  options: FieldOptionsJson,
  showOnCards: SqlBool,
});

const FieldRequirementRow = Schema.Struct({
  ...SessionFieldRow.fields,
  isRequired: SqlBool,
});

const SlotRequirementRow = Schema.Struct({
  ...TimeSlotRow.fields,
  isRequired: SqlBool,
});

export const SESSION_FIELD_COLUMNS = `
  f.id AS id, f.event_id AS eventId, f.name AS name, f.question AS question,
  f.slug AS slug, f.field_type AS fieldType, f.is_multiple AS isMultiple,
  f.allow_custom AS allowCustom, f.max_length AS maxLength, f."order" AS "order",
  f.help_text AS helpText, f.icon AS icon, f.is_public AS isPublic,
  f.show_on_cards AS showOnCards,
  (SELECT json_group_array(json_object('id', o.id, 'label', o.label, 'value', o.value, 'order', o."order")
     ORDER BY o."order", o.label)
   FROM session_field_option o WHERE o.field_id = f.id) AS options`;

const CATEGORY_COLUMNS = `
  c.id AS id, c.event_id AS eventId, c.name AS name, c.slug AS slug,
  c.description AS description, c.start_time AS startTime, c.end_time AS endTime,
  c.max_participants_limit AS maxParticipantsLimit,
  c.min_participants_limit AS minParticipantsLimit, c.durations AS durations,
  c.promotion_mode AS promotionMode, c.offer_claim_window AS offerClaimWindow`;

const ScopeInput = Schema.Struct({ eventId: EventId, id: ProposalCategoryId });

const SlugInput = Schema.Struct({ eventId: EventId, slug: Schema.String });

export const makeProposalCategoryStore = Effect.gen(
  function* makeProposalCategoryStore() {
    const sql = yield* SqlClient;
    const columns = sql.literal(CATEGORY_COLUMNS);

    const readWhere = (operation: string, key: string, where: Fragment) =>
      sql`SELECT ${columns} FROM proposal_category c WHERE ${where}`.pipe(
        decodeOne({
          entity: "ProposalCategory",
          key,
          operation,
          row: CategoryRow,
        })
      );

    const listByEvent = Effect.fn("ProposalCategoryStore.listByEvent")(
      function* listByEvent(eventId: EventId) {
        const valid = yield* decodeInput(
          "ProposalCategoryStore.listByEvent",
          EventId
        )(eventId);

        return yield* sql`
      SELECT ${columns} FROM proposal_category c WHERE c.event_id = ${valid}
      ORDER BY c.name, c.id LIMIT ${ROW_BUDGET.eventCategories}
    `.pipe(decodeRows("ProposalCategoryStore.listByEvent", CategoryRow));
      }
    );

    const readInEvent = Effect.fn("ProposalCategoryStore.readInEvent")(
      function* readInEvent(scope: typeof ScopeInput.Type) {
        const input = yield* decodeInput(
          "ProposalCategoryStore.readInEvent",
          ScopeInput
        )(scope);

        return yield* readWhere(
          "ProposalCategoryStore.readInEvent",
          String(input.id),
          sql`c.id = ${input.id} AND c.event_id = ${input.eventId}`
        );
      }
    );

    const readBySlug = Effect.fn("ProposalCategoryStore.readBySlug")(
      function* readBySlug(options: typeof SlugInput.Type) {
        const input = yield* decodeInput(
          "ProposalCategoryStore.readBySlug",
          SlugInput
        )(options);

        return yield* readWhere(
          "ProposalCategoryStore.readBySlug",
          input.slug,
          sql`c.slug = ${input.slug} AND c.event_id = ${input.eventId}`
        );
      }
    );

    const readRequirements = Effect.fn(
      "ProposalCategoryStore.readRequirements"
    )(function* readRequirements(categoryId: ProposalCategoryId) {
      const valid = yield* decodeInput(
        "ProposalCategoryStore.readRequirements",
        ProposalCategoryId
      )(categoryId);

      const fields = yield* sql`
      SELECT ${sql.literal(SESSION_FIELD_COLUMNS)}, r.is_required AS isRequired
      FROM session_field_requirement r JOIN session_field f ON f.id = r.field_id
      WHERE r.category_id = ${valid}
      ORDER BY r."order", f.name, r.id
      LIMIT ${ROW_BUDGET.eventFields}
    `.pipe(
        decodeRows(
          "ProposalCategoryStore.readRequirements",
          FieldRequirementRow
        )
      );

      const slots = yield* sql`
      SELECT ts.id AS id, ts.event_id AS eventId, ts.start_time AS startTime,
        ts.end_time AS endTime, r.is_required AS isRequired
      FROM time_slot_requirement r JOIN time_slot ts ON ts.id = r.time_slot_id
      WHERE r.category_id = ${valid}
      ORDER BY r."order", ts.start_time, r.id
      LIMIT ${ROW_BUDGET.eventTimeSlots}
    `.pipe(
        decodeRows("ProposalCategoryStore.readRequirements", SlotRequirementRow)
      );

      return {
        sessionFields: fields.map(({ isRequired, ...field }) => ({
          field,
          isRequired,
        })),
        timeSlots: slots.map(({ isRequired, ...timeSlot }) => ({
          isRequired,
          timeSlot,
          timeSlotId: timeSlot.id,
        })),
      };
    });

    const stats = Effect.fn("ProposalCategoryStore.stats")(function* stats(
      eventId: EventId
    ) {
      const valid = yield* decodeInput(
        "ProposalCategoryStore.stats",
        EventId
      )(eventId);

      return yield* sql`
      SELECT c.id AS categoryId,
        COUNT(s.id) AS proposalsCount,
        COUNT(CASE WHEN s.status <> 'pending' THEN s.id END) AS acceptedCount
      FROM proposal_category c
      LEFT JOIN session s ON s.category_id = c.id
      WHERE c.event_id = ${valid}
      GROUP BY c.id ORDER BY c.id LIMIT ${ROW_BUDGET.eventCategories}
    `.pipe(decodeRows("ProposalCategoryStore.stats", CategoryStats));
    });

    return ProposalCategoryStore.of({
      listByEvent,
      readBySlug,
      readInEvent,
      readRequirements,
      stats,
    });
  }
);

export const ProposalCategoryStoreLive = Layer.effect(
  ProposalCategoryStore,
  makeProposalCategoryStore
);
