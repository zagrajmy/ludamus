import { DateTime, Schema } from "effect";

export type Json =
  | string
  | number
  | boolean
  | null
  | readonly Json[]
  | { readonly [key: string]: Json };

export interface DifferentialCase {
  readonly input: Json;
  readonly output: Json;
}

export interface Mismatch {
  readonly index: number;
  readonly input: Json;
  readonly python: Json;
  readonly port: Json;
}

const isJsonList = (value: Json): value is readonly Json[] =>
  Array.isArray(value);

const canonical = (value: Json): Json => {
  if (value === null || typeof value !== "object") {
    return value;
  }

  if (isJsonList(value)) {
    return value.map(canonical);
  }

  return Object.fromEntries(
    Object.entries(value)
      .toSorted(([a], [b]) => (a < b ? -1 : 1))
      .map(([key, item]) => [key, canonical(item)])
  );
};

export const replay = <S extends Schema.Decoder<unknown>>(options: {
  readonly cases: readonly DifferentialCase[];
  readonly input: S;
  readonly run: (input: S["Type"]) => Json;
}): readonly Mismatch[] => {
  const decode = Schema.decodeUnknownSync(options.input);

  return options.cases.flatMap((testCase, index) => {
    const port = options.run(decode(testCase.input));

    return JSON.stringify(canonical(port)) ===
      JSON.stringify(canonical(testCase.output))
      ? []
      : [{ index, input: testCase.input, port, python: testCase.output }];
  });
};

export const iso = (value: DateTime.DateTime): string =>
  DateTime.formatIso(value);

export const isoOrNull = (value: DateTime.DateTime | null): string | null =>
  value === null ? null : iso(value);
