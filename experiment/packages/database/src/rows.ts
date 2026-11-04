import { InvalidStoreInput, NotFound, StoreError } from "@zagrajmy/core";
import {
  DateTime,
  Duration,
  Effect,
  Option,
  Predicate,
  Schema,
  SchemaIssue,
  SchemaTransformation,
} from "effect";
import type { SqlClient } from "effect/sql/SqlClient";
import type { Row } from "effect/sql/SqlConnection";
import type { Statement } from "effect/sql/Statement";

const twoDigits = (value: number) => String(value).padStart(2, "0");

export const toSqlDateTime = (value: DateTime.Utc): string => {
  const parts = DateTime.toPartsUtc(value);
  const date = `${parts.year}-${twoDigits(parts.month)}-${twoDigits(parts.day)}`;
  const time = `${twoDigits(parts.hour)}:${twoDigits(parts.minute)}:${twoDigits(parts.second)}`;

  const fraction =
    parts.millisecond === 0
      ? ""
      : `.${String(parts.millisecond).padStart(3, "0")}000`;

  return `${date} ${time}${fraction}`;
};

const fromSqlDateTime = (value: string) =>
  DateTime.make(`${value.replace(" ", "T")}Z`).pipe(Option.map(DateTime.toUtc));

export const SqlDateTime = Schema.String.pipe(
  Schema.decodeTo(
    Schema.DateTimeUtc,
    SchemaTransformation.transformEffect({
      decode: (value: string, options) =>
        Option.match(fromSqlDateTime(value), {
          onNone: () =>
            Effect.fail(
              new SchemaIssue.InvalidValue(
                { expected: "a Django datetime string" },
                Option.some(value),
                options
              )
            ),
          onSome: Effect.succeed,
        }),
      encode: (value: DateTime.Utc) => Effect.succeed(toSqlDateTime(value)),
    })
  )
);

export const SqlBool = Schema.BooleanFromBit;

export const SqlDuration = Schema.Number.pipe(
  Schema.decodeTo(
    Schema.Duration,
    SchemaTransformation.transform({
      decode: (micros: number) => Duration.micros(BigInt(micros)),
      encode: (duration: Duration.Duration) =>
        Number(
          Duration.toNanos(duration).pipe(Option.getOrElse(() => 0n)) / 1000n
        ),
    })
  )
);

export const SqlJson = <S extends Schema.Top>(schema: S) =>
  Schema.fromJsonString(schema);

export type PythonJson =
  | string
  | number
  | boolean
  | null
  | readonly PythonJson[]
  | { readonly [key: string]: PythonJson };

const hex = (unit: number) => `\\u${unit.toString(16).padStart(4, "0")}`;

const escapeCodePoint = (char: string) => {
  const point = char.codePointAt(0) ?? 0;

  if (point <= 0xff_ff) {
    return hex(point);
  }

  const offset = point - 0x1_00_00;

  return (
    hex(0xd8_00 + Math.floor(offset / 0x4_00)) +
    hex(0xdc_00 + (offset % 0x4_00))
  );
};

const asciiEscape = (text: string) =>
  text.replaceAll(/[\u0080-\u{10FFFF}]/gu, escapeCodePoint);

export const pythonJson = (value: PythonJson): string => {
  if (value === null) {
    return "null";
  }

  if (Predicate.isString(value)) {
    return asciiEscape(JSON.stringify(value));
  }

  if (Predicate.isNumber(value) || Predicate.isBoolean(value)) {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map(pythonJson).join(", ")}]`;
  }

  return `{${Object.entries(value)
    .map(
      ([key, item]) =>
        `${asciiEscape(JSON.stringify(key))}: ${pythonJson(item)}`
    )
    .join(", ")}}`;
};

export const likeContains = (term: string) =>
  `%${term.replaceAll(/[\\%_]/gu, (char) => `\\${char}`)}%`;

const tagOf = (cause: Error): string => {
  if (
    Predicate.hasProperty(cause, "reason") &&
    Predicate.hasProperty(cause.reason, "_tag")
  ) {
    return String(cause.reason._tag);
  }

  return Predicate.hasProperty(cause, "_tag") ? String(cause._tag) : cause.name;
};

export const storeFailure =
  (operation: string) =>
  <A, E extends Error, R>(effect: Effect.Effect<A, E, R>) =>
    effect.pipe(
      Effect.mapError(
        (cause) => new StoreError({ operation, reason: tagOf(cause) })
      )
    );

export const decodeInput =
  <A, I>(operation: string, schema: Schema.Codec<A, I>) =>
  (input: I | A) =>
    Schema.decodeUnknownEffect(schema)(input).pipe(
      Effect.mapError(
        (issue) => new InvalidStoreInput({ operation, reason: issue.message })
      )
    );

export const decodeRows =
  <A, I>(operation: string, row: Schema.Codec<A, I>) =>
  <E extends Error>(
    statement: Effect.Effect<readonly Row[], E>
  ): Effect.Effect<readonly A[], StoreError> =>
    statement.pipe(
      Effect.flatMap(Schema.decodeUnknownEffect(Schema.Array(row))),
      storeFailure(operation)
    );

export const decodeFirst =
  <A, I>(operation: string, row: Schema.Codec<A, I>) =>
  <E extends Error>(statement: Effect.Effect<readonly Row[], E>) =>
    statement.pipe(
      decodeRows(operation, row),
      Effect.map((rows) => Option.fromNullishOr(rows[0]))
    );

export const decodeOne =
  <A, I>(options: {
    readonly operation: string;
    readonly row: Schema.Codec<A, I>;
    readonly entity: string;
    readonly key: string;
  }) =>
  <E extends Error>(statement: Effect.Effect<readonly Row[], E>) =>
    statement.pipe(
      decodeFirst(options.operation, options.row),
      Effect.flatMap(
        Option.match({
          onNone: () =>
            Effect.fail(
              new NotFound({ entity: options.entity, key: options.key })
            ),
          onSome: (row) => Effect.succeed(row),
        })
      )
    );

export const IdRow = Schema.Struct({ id: Schema.Int });

export const requireRow =
  (options: { readonly entity: string; readonly key: string }) =>
  (rows: readonly { readonly id: number }[]) =>
    rows.length === 0
      ? Effect.fail(new NotFound({ entity: options.entity, key: options.key }))
      : Effect.void;

export type Sql = SqlClient;

export type SqlStatement<A> = Statement<A>;
