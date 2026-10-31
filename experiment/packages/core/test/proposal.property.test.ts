import { describe, expect, it } from "@effect/vitest";
import { Result, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import {
  FieldRequirement,
  MAX_DURATION_HOURS,
  MAX_DURATION_MINUTES,
  OrganizerField,
  buildDuration,
  controlRequired,
  durationFromParts,
  formatDuration,
  normalizeDuration,
  offersCustomInput,
  parseDuration,
  resolveFieldControls,
  stepperParts,
  uniqueSlug,
  validateFieldAnswers,
} from "../src/proposal/index.js";
import { between } from "./support/arbitraries.js";

const hours = Arbitrary.schema(between(0, 200));

const minutes = Arbitrary.schema(between(0, 2000));

describe("durations", () => {
  it.prop(
    "a built duration parses back to the same total minutes",
    { hours, minutes },
    (parts) => {
      const [h, m] = parseDuration(buildDuration(parts));
      expect(h * 60 + m).toBe(parts.hours * 60 + parts.minutes);
      expect(m).toBeLessThan(60);
    }
  );

  it.prop(
    "normalizing is idempotent",
    { text: Arbitrary.schema(Schema.String) },
    ({ text }) => {
      const once = normalizeDuration(text);
      expect(normalizeDuration(once)).toBe(once);
    }
  );

  it.prop(
    "a canonical duration is its own normal form",
    { hours, minutes },
    (parts) => {
      const built = buildDuration(parts);
      expect(normalizeDuration(built)).toBe(built);
    }
  );

  it.prop(
    "the stepper round-trips every length it can show",
    {
      hours: Arbitrary.schema(between(0, MAX_DURATION_HOURS)),
      minutes: Arbitrary.schema(between(0, MAX_DURATION_MINUTES)),
    },
    (parts) => {
      const built = buildDuration(parts);
      const [h, m] = stepperParts(built);
      expect(
        Result.getOrNull(durationFromParts({ hours: h, minutes: m }))
      ).toBe(built);
    }
  );

  it.prop(
    "a label is empty exactly when the duration is",
    { hours, minutes },
    (parts) => {
      const built = buildDuration(parts);
      expect(formatDuration(built) === "").toBe(built === "");
    }
  );
});

const Pairs = Arbitrary.map(
  Arbitrary.schema(Schema.Array(FieldRequirement).check(Schema.isMaxLength(4))),
  (pairs) =>
    pairs.map((pair, index) => ({
      ...pair,
      field: { ...pair.field, slug: `f${index}` },
    }))
);

describe("field requirements", () => {
  it.prop(
    "a write-in field is never enforced by its control alone, but always as a pair",
    { pairs: Pairs },
    ({ pairs }) => {
      const resolved = resolveFieldControls({ pairs, prefix: "session" });

      for (const pair of pairs) {
        if (offersCustomInput(pair.field)) {
          expect(controlRequired(pair)).toBe(false);
          expect(
            resolved.pairCheckedKeys.includes(`session_${pair.field.slug}`)
          ).toBe(pair.isRequired);
        }
      }
    }
  );

  it.prop(
    "an empty submission is valid exactly when nothing is required",
    { field: Arbitrary.schema(OrganizerField), isRequired: Schema.Boolean },
    ({ field, isRequired }) => {
      const pair = { field: { ...field, slug: "a" }, isRequired };

      const validation = validateFieldAnswers({
        data: {},
        pairs: [pair],
        prefix: "session",
      });

      const binds = isRequired && field.fieldType !== "checkbox";
      expect(validation.valid).toBe(!binds);
    }
  );

  it.prop(
    "never reports an error for a key it does not render",
    {
      data: Arbitrary.schema(
        Schema.Record(Schema.String, Schema.Array(Schema.String))
      ),
      pairs: Pairs,
    },
    ({ pairs, data }) => {
      const keys = new Set(
        resolveFieldControls({ pairs, prefix: "p" }).controls.map((c) => c.key)
      );

      const validation = validateFieldAnswers({ data, pairs, prefix: "p" });
      expect(Object.keys(validation.errors).every((key) => keys.has(key))).toBe(
        true
      );
      expect(
        Object.keys(validation.cleaned).every((key) => keys.has(key))
      ).toBe(true);
    }
  );
});

describe("unique slugs", () => {
  const SlugCase = Schema.Struct({
    base: Schema.String,
    fallback: Schema.String,
    taken: Schema.Array(Schema.String),
  });

  it.prop(
    "a slug starts with the capped base and fits the column",
    { input: Arbitrary.schema(SlugCase) },
    ({ input }) => {
      const slug = uniqueSlug({
        ...input,
        exists: (s) => input.taken.includes(s),
        nextSuffix: () => "AbC_",
      });

      const base = [...(input.base === "" ? input.fallback : input.base)]
        .slice(0, 45)
        .join("");

      expect(slug.startsWith(base)).toBe(true);
      expect([...slug].length).toBeLessThanOrEqual(50);
    }
  );

  it.prop(
    "a free base is used as it is",
    {
      base: Arbitrary.schema(
        Schema.String.check(Schema.isMaxLength(45), Schema.isMinLength(1))
      ),
    },
    ({ base }) => {
      expect(
        uniqueSlug({
          base,
          exists: () => false,
          fallback: "x",
          nextSuffix: () => "zzzz",
        })
      ).toBe(base);
    }
  );
});
