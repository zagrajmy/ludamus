import { describe, expect, it } from "@effect/vitest";
import { Option, Schema } from "effect";
import * as Arbitrary from "effect/Arbitrary";

import {
  PROPOSAL_SLUG_MAX_LENGTH,
  STEP_ORDER,
  codePoints,
  parseClientIp,
  proposalSlugify,
  slugCandidates,
  stepAfter,
  stepAtOrBefore,
  wizardSteps,
} from "../src/proposal/index.js";
import { between } from "./support/arbitraries.js";

const wizardInputs = {
  accountAnswersEverything: Arbitrary.schema(Schema.Boolean),
  categoryCount: Arbitrary.schema(between(0, 4)),
  hasCategory: Arbitrary.schema(Schema.Boolean),
  timeSlotCount: Arbitrary.schema(between(0, 4)),
};

describe("proposal wizard steps", () => {
  it.prop(
    "always ends at the session and the review, in submission order",
    wizardInputs,
    (options) => {
      const steps = wizardSteps(options);

      expect(steps.slice(-2)).toStrictEqual(["details", "review"]);
      expect(steps).toStrictEqual(
        STEP_ORDER.filter((step) => steps.includes(step))
      );
    }
  );

  it.prop(
    "asks for a category only when there is a choice, and for personal details only when the account leaves a question open",
    wizardInputs,
    (options) => {
      const steps = wizardSteps(options);

      expect(steps.includes("category")).toBe(options.categoryCount > 1);
      expect(steps.includes("personal")).toBe(
        !options.accountAnswersEverything
      );
    }
  );

  it.prop(
    "never asks for time slots once a category with at most one slot is chosen",
    wizardInputs,
    (options) => {
      const steps = wizardSteps({ ...options, hasCategory: true });

      expect(steps.includes("timeslots")).toBe(options.timeSlotCount > 1);
    }
  );

  it.prop(
    "Continue moves to the next shown step and Back lands on a shown step no later than asked",
    {
      ...wizardInputs,
      at: Arbitrary.schema(between(0, STEP_ORDER.length - 1)),
    },
    ({ at, ...options }) => {
      const steps = wizardSteps(options);
      const step = STEP_ORDER[at] ?? "review";
      const back = stepAtOrBefore(steps, step);

      expect(steps).toContain(back);
      expect(
        STEP_ORDER.indexOf(back) <= STEP_ORDER.indexOf(step) ||
          back === steps[0]
      ).toBe(true);

      if (steps.includes(step) && step !== "review") {
        expect(stepAfter(steps, step)).toBe(steps[steps.indexOf(step) + 1]);
      }
    }
  );
});

describe("proposal slugs", () => {
  it.prop(
    "every candidate fits the column and is lowercase ASCII",
    { title: Arbitrary.schema(Schema.String) },
    ({ title }) => {
      for (const slug of slugCandidates({
        fallback: "",
        suffixes: ["AAAA", "b-_9"],
        title,
      })) {
        expect(slug.length).toBeLessThanOrEqual(PROPOSAL_SLUG_MAX_LENGTH);
        expect(codePoints(slug).every((point) => point < 128)).toBe(true);
      }

      expect(proposalSlugify(title)).toBe(proposalSlugify(title).toLowerCase());
    }
  );

  it.prop(
    "slugifying a slug changes nothing",
    { title: Arbitrary.schema(Schema.String) },
    ({ title }) => {
      const slug = proposalSlugify(title);

      expect(proposalSlugify(slug)).toBe(slug);
    }
  );
});

describe("client IP", () => {
  it.prop(
    "a dotted quad normalises to itself and survives a second pass",
    {
      octets: Arbitrary.schema(
        Schema.Tuple([
          between(0, 255),
          between(0, 255),
          between(0, 255),
          between(0, 255),
        ])
      ),
    },
    ({ octets }) => {
      const text = octets.join(".");

      expect(parseClientIp(` ${text} `)).toStrictEqual(Option.some(text));
    }
  );

  it.prop(
    "a parsed address parses to itself again",
    { raw: Arbitrary.schema(Schema.String) },
    ({ raw }) => {
      const parsed = parseClientIp(raw);

      if (Option.isSome(parsed)) {
        expect(parseClientIp(parsed.value)).toStrictEqual(parsed);
      }
    }
  );
});
