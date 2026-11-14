import {
  DomainEnrollmentConfig,
  EnrollmentConfig,
  EnrollmentConfigId,
  EnrollmentConfigStore,
  EventId,
  NewUserEnrollmentConfig,
  SlotAllowance,
  StoreError,
  UserEnrollmentConfig,
} from "@zagrajmy/core";
import { Effect, Layer, Option, Schema } from "effect";
import { SqlClient } from "effect/sql/SqlClient";

import {
  decodeFirst,
  decodeInput,
  decodeRows,
  IdRow,
  SqlBool,
  SqlDateTime,
  toSqlDateTime,
} from "./rows.js";
import { ROW_BUDGET } from "./sql-fragments.js";

const ConfigRow = Schema.Struct({
  ...EnrollmentConfig.fields,
  allowAnonymousEnrollment: SqlBool,
  endTime: SqlDateTime,
  limitToEndTime: SqlBool,
  restrictToConfiguredUsers: SqlBool,
  startTime: SqlDateTime,
});

const UserConfigRow = Schema.Struct({
  ...UserEnrollmentConfig.fields,
  fetchedFromApi: SqlBool,
  lastCheck: Schema.NullOr(SqlDateTime),
});

const USER_CONFIG_COLUMNS = `
  id, enrollment_config_id AS enrollmentConfigId, user_email AS userEmail,
  allowed_slots AS allowedSlots, fetched_from_api AS fetchedFromApi, last_check AS lastCheck`;

const UserKeyInput = Schema.Struct({
  enrollmentConfigId: EnrollmentConfigId,
  userEmail: Schema.String,
});

const DomainKeyInput = Schema.Struct({
  domain: Schema.String,
  enrollmentConfigId: EnrollmentConfigId,
});

const UserAllowanceInput = Schema.Struct({
  emails: Schema.Array(Schema.String),
  enrollmentConfigIds: Schema.Array(EnrollmentConfigId),
});

const DomainAllowanceInput = Schema.Struct({
  domains: Schema.Array(Schema.String),
  enrollmentConfigIds: Schema.Array(EnrollmentConfigId),
});

export const makeEnrollmentConfigStore = Effect.gen(
  function* makeEnrollmentConfigStore() {
    const sql = yield* SqlClient;
    const userColumns = sql.literal(USER_CONFIG_COLUMNS);

    const listByEvent = Effect.fn("EnrollmentConfigStore.listByEvent")(
      function* listByEvent(eventId: EventId) {
        const valid = yield* decodeInput(
          "EnrollmentConfigStore.listByEvent",
          EventId
        )(eventId);

        return yield* sql`
      SELECT id, event_id AS eventId, start_time AS startTime, end_time AS endTime,
        percentage_slots AS percentageSlots, limit_to_end_time AS limitToEndTime,
        banner_text AS bannerText, max_waitlist_sessions AS maxWaitlistSessions,
        restrict_to_configured_users AS restrictToConfiguredUsers,
        allow_anonymous_enrollment AS allowAnonymousEnrollment
      FROM enrollment_config WHERE event_id = ${valid}
      ORDER BY start_time, id LIMIT ${ROW_BUDGET.eventCategories}
    `.pipe(decodeRows("EnrollmentConfigStore.listByEvent", ConfigRow));
      }
    );

    const readUserConfig = Effect.fn("EnrollmentConfigStore.readUserConfig")(
      function* readUserConfig(options: typeof UserKeyInput.Type) {
        const input = yield* decodeInput(
          "EnrollmentConfigStore.readUserConfig",
          UserKeyInput
        )(options);

        return yield* sql`
      SELECT ${userColumns} FROM user_enrollment_config
      WHERE enrollment_config_id = ${input.enrollmentConfigId} AND user_email = ${input.userEmail}
      ORDER BY id LIMIT 1
    `.pipe(decodeFirst("EnrollmentConfigStore.readUserConfig", UserConfigRow));
      }
    );

    const readDomainConfig = Effect.fn(
      "EnrollmentConfigStore.readDomainConfig"
    )(function* readDomainConfig(options: typeof DomainKeyInput.Type) {
      const input = yield* decodeInput(
        "EnrollmentConfigStore.readDomainConfig",
        DomainKeyInput
      )(options);

      return yield* sql`
      SELECT id, enrollment_config_id AS enrollmentConfigId, domain,
        allowed_slots_per_user AS allowedSlotsPerUser
      FROM domain_enrollment_config
      WHERE enrollment_config_id = ${input.enrollmentConfigId} AND domain = ${input.domain}
      ORDER BY id LIMIT 1
    `.pipe(
        decodeFirst(
          "EnrollmentConfigStore.readDomainConfig",
          DomainEnrollmentConfig
        )
      );
    });

    const createUserConfig = Effect.fn(
      "EnrollmentConfigStore.createUserConfig"
    )(function* createUserConfig(config: typeof NewUserEnrollmentConfig.Type) {
      const input = yield* decodeInput(
        "EnrollmentConfigStore.createUserConfig",
        NewUserEnrollmentConfig
      )(config);

      const rows = yield* sql`
      INSERT INTO user_enrollment_config ${sql.insert({
        allowed_slots: input.allowedSlots,
        enrollment_config_id: input.enrollmentConfigId,
        fetched_from_api: input.fetchedFromApi ? 1 : 0,
        last_check:
          input.lastCheck === null ? null : toSqlDateTime(input.lastCheck),
        user_email: input.userEmail,
      })} RETURNING ${userColumns}
    `.pipe(decodeRows("EnrollmentConfigStore.createUserConfig", UserConfigRow));

      return yield* Option.match(Option.fromNullishOr(rows[0]), {
        onNone: () =>
          Effect.fail(
            new StoreError({
              operation: "EnrollmentConfigStore.createUserConfig",
              reason: "insert returned no row",
            })
          ),
        onSome: Effect.succeed,
      });
    });

    const updateUserConfig = Effect.fn(
      "EnrollmentConfigStore.updateUserConfig"
    )(function* updateUserConfig(config: typeof UserEnrollmentConfig.Type) {
      const input = yield* decodeInput(
        "EnrollmentConfigStore.updateUserConfig",
        UserEnrollmentConfig
      )(config);

      yield* sql`
      UPDATE user_enrollment_config SET ${sql.update({
        allowed_slots: input.allowedSlots,
        enrollment_config_id: input.enrollmentConfigId,
        fetched_from_api: input.fetchedFromApi ? 1 : 0,
        last_check:
          input.lastCheck === null ? null : toSqlDateTime(input.lastCheck),
        user_email: input.userEmail,
      })} WHERE id = ${input.id} RETURNING id
    `.pipe(decodeRows("EnrollmentConfigStore.updateUserConfig", IdRow));
    });

    const userAllowances = Effect.fn("EnrollmentConfigStore.userAllowances")(
      function* userAllowances(options: typeof UserAllowanceInput.Type) {
        const input = yield* decodeInput(
          "EnrollmentConfigStore.userAllowances",
          UserAllowanceInput
        )(options);

        if (
          input.emails.length === 0 ||
          input.enrollmentConfigIds.length === 0
        ) {
          return [];
        }

        return yield* sql`
      SELECT user_email AS key, SUM(allowed_slots) AS allowedSlots FROM user_enrollment_config
      WHERE ${sql.in("enrollment_config_id", input.enrollmentConfigIds)} AND ${sql.in("user_email", input.emails)}
      GROUP BY user_email ORDER BY user_email LIMIT ${input.emails.length}
    `.pipe(decodeRows("EnrollmentConfigStore.userAllowances", SlotAllowance));
      }
    );

    const domainAllowances = Effect.fn(
      "EnrollmentConfigStore.domainAllowances"
    )(function* domainAllowances(options: typeof DomainAllowanceInput.Type) {
      const input = yield* decodeInput(
        "EnrollmentConfigStore.domainAllowances",
        DomainAllowanceInput
      )(options);

      if (
        input.domains.length === 0 ||
        input.enrollmentConfigIds.length === 0
      ) {
        return [];
      }

      return yield* sql`
      SELECT domain AS key, SUM(allowed_slots_per_user) AS allowedSlots FROM domain_enrollment_config
      WHERE ${sql.in("enrollment_config_id", input.enrollmentConfigIds)} AND ${sql.in("domain", input.domains)}
      GROUP BY domain ORDER BY domain LIMIT ${input.domains.length}
    `.pipe(decodeRows("EnrollmentConfigStore.domainAllowances", SlotAllowance));
    });

    return EnrollmentConfigStore.of({
      createUserConfig,
      domainAllowances,
      listByEvent,
      readDomainConfig,
      readUserConfig,
      updateUserConfig,
      userAllowances,
    });
  }
);

export const EnrollmentConfigStoreLive = Layer.effect(
  EnrollmentConfigStore,
  makeEnrollmentConfigStore
);
