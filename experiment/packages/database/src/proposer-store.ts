import {
  EventId,
  FieldValue,
  ProposerStore,
  SessionId,
  SphereId,
  UserId,
} from "@zagrajmy/core";
import { Effect, Layer, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import { IdRow, SqlBool, SqlJson, decodeInput, decodeRows } from "./rows.js";

const REUSABLE_SESSIONS_BUDGET = 50;

const ReusableInput = Schema.Struct({
  excludeEventId: EventId,
  limit: Schema.Int.check(
    Schema.isBetween({ maximum: REUSABLE_SESSIONS_BUDGET, minimum: 0 })
  ),
  sphereId: SphereId,
  userId: UserId,
});

const FillInput = Schema.Struct({ handle: Schema.String, userId: UserId });

const EarlierSessionRow = Schema.Struct({
  description: Schema.String,
  duration: Schema.String,
  eventName: Schema.String,
  id: SessionId,
  minAge: Schema.Int,
  participantsLimit: Schema.Int,
  presented: SqlBool,
  title: Schema.String,
});

const AnswerRow = Schema.Struct({
  isPublic: SqlBool,
  sessionId: SessionId,
  slug: Schema.String,
  value: SqlJson(FieldValue),
});

export const makeProposerStore = Effect.gen(function* makeProposerStore() {
  const sql = yield* SqlClient;

  const listReusableSessions = Effect.fn("ProposerStore.listReusableSessions")(
    function* listReusableSessions(options: typeof ReusableInput.Type) {
      const operation = "ProposerStore.listReusableSessions";
      const input = yield* decodeInput(operation, ReusableInput)(options);

      const sessions = yield* sql`
        WITH runs AS (
          SELECT s.id AS id, s.title AS title, s.description AS description,
                 s.participants_limit AS participantsLimit, s.min_age AS minAge,
                 s.duration AS duration, e.name AS eventName,
                 COALESCE(s.presenter_id = ${input.userId}, 0) AS presented,
                 e.start_time AS eventStart, s.creation_time AS created,
                 ROW_NUMBER() OVER (
                   PARTITION BY LOWER(TRIM(s.title))
                   ORDER BY e.start_time DESC, s.creation_time DESC
                 ) AS titleRank
          FROM session s JOIN event e ON e.id = s.event_id
          WHERE s.deleted_at IS NULL
            AND e.sphere_id = ${input.sphereId}
            AND s.event_id <> ${input.excludeEventId}
            AND (
              s.presenter_id = ${input.userId}
              OR s.id IN (
                SELECT sf.session_id FROM session_facilitators sf
                JOIN facilitator f ON f.id = sf.facilitator_id
                WHERE f.user_id = ${input.userId} AND f.deleted_at IS NULL
              )
            )
        )
        SELECT id, title, description, participantsLimit, minAge, duration,
               eventName, presented
        FROM runs WHERE titleRank = 1
        ORDER BY eventStart DESC, created DESC
        LIMIT ${input.limit}
      `.pipe(decodeRows(operation, EarlierSessionRow));

      if (sessions.length === 0) {
        return [];
      }

      const answers = yield* sql`
        SELECT v.session_id AS sessionId, v.value AS value, f.slug AS slug,
               f.is_public AS isPublic
        FROM session_field_value v JOIN session_field f ON f.id = v.field_id
        WHERE ${sql.in(
          "v.session_id",
          sessions.map((session) => session.id)
        )}
        ORDER BY v.id
        LIMIT ${REUSABLE_SESSIONS_BUDGET * 100}
      `.pipe(decodeRows(operation, AnswerRow));

      return sessions.map((session) => {
        const own = answers.filter((answer) => answer.sessionId === session.id);

        const bySlug = (isPublic: boolean) =>
          Object.fromEntries(
            own
              .filter((answer) => answer.isPublic === isPublic)
              .map((answer) => [answer.slug, answer.value])
          );

        return {
          description: session.description,
          duration: session.duration,
          eventName: session.eventName,
          minAge: session.minAge,
          participantsLimit: session.participantsLimit,
          presented: session.presented,
          privateAnswers: bySlug(false),
          publicAnswers: bySlug(true),
          sessionId: session.id,
          title: session.title,
        };
      });
    }
  );

  const fillDiscordUsername = Effect.fn("ProposerStore.fillDiscordUsername")(
    function* fillDiscordUsername(options: typeof FillInput.Type) {
      const operation = "ProposerStore.fillDiscordUsername";
      const input = yield* decodeInput(operation, FillInput)(options);

      const updated = yield* sql`
        UPDATE user SET discord_username = ${input.handle}
        WHERE id = ${input.userId} AND discord_username = ''
        RETURNING id
      `.pipe(decodeRows(operation, IdRow));

      return updated.length > 0;
    }
  );

  return ProposerStore.of({ fillDiscordUsername, listReusableSessions });
});

export const ProposerStoreLive = Layer.effect(ProposerStore, makeProposerStore);
