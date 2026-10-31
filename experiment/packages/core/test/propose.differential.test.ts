import { describe, expect, it } from "@effect/vitest";
import { Option, Result, Schema } from "effect";

import {
  FieldRequirement,
  PROPOSAL_SLUG_ATTEMPTS,
  parseClientIp,
  proposalSlugify,
  slugCandidates,
  validateDetailsStep,
  validatePersonalStep,
} from "../src/proposal/index.js";
import type { FieldError, FormErrors } from "../src/proposal/index.js";
import ipCases from "./fixtures/differential/client_ip.json" with { type: "json" };
import detailsCases from "./fixtures/differential/details_form.json" with { type: "json" };
import personalCases from "./fixtures/differential/personal_form.json" with { type: "json" };
import slugCases from "./fixtures/differential/proposal_slug.json" with { type: "json" };
import { replay } from "./support/differential.js";
import type { Json } from "./support/differential.js";

const FormData = Schema.Record(Schema.String, Schema.Array(Schema.String));

const PYTHON_FORMAT = /%\((?<name>\w+)\)(?<conversion>[sd])/gu;

const render = (error: FieldError): string => {
  const template =
    error.plural !== null && error.plural.count !== 1
      ? error.plural.msgid
      : error.msgid;

  return template.replaceAll(PYTHON_FORMAT, (...match: unknown[]) => {
    const groups = Schema.decodeUnknownSync(
      Schema.Struct({ name: Schema.String })
    )(match.at(-1));

    return String(error.vars[groups.name] ?? "");
  });
};

const messages = (errors: FormErrors): Json =>
  Object.fromEntries(
    Object.entries(errors).map(([key, list]) => [key, list.map(render)])
  );

describe("differential: proposal slugs (mills.submissions.mapping)", () => {
  it("slugifies and picks the first free candidate like generate_unique_slug", () => {
    const mismatches = replay({
      cases: slugCases.cases,
      input: Schema.Struct({
        fallback: Schema.String,
        suffixes: Schema.Array(Schema.String),
        taken: Schema.Array(Schema.String),
        title: Schema.String,
      }),
      run: (input) => {
        const candidates = slugCandidates({
          fallback: input.fallback,
          suffixes: input.suffixes.slice(0, PROPOSAL_SLUG_ATTEMPTS - 1),
          title: input.title,
        });

        const free = candidates.find((slug) => !input.taken.includes(slug));

        return {
          slug: free ?? { error: "SlugCollisionError" },
          slugify: proposalSlugify(input.title),
        };
      },
    });

    expect(mismatches).toStrictEqual([]);
  });
});

describe("differential: client IP (gates helpers._parse_ip)", () => {
  it("normalises or refuses an address like ipaddress.ip_address", () => {
    const mismatches = replay({
      cases: ipCases.cases,
      input: Schema.Struct({ raw: Schema.String }),
      run: ({ raw }) => Option.getOrNull(parseClientIp(raw)),
    });

    expect(mismatches).toStrictEqual([]);
  });
});

describe("differential: propose forms (event/propose_forms.py)", () => {
  it("validates the session step like build_session_details_form", () => {
    const mismatches = replay({
      cases: detailsCases.cases,
      input: Schema.Struct({
        category: Schema.NullOr(
          Schema.Struct({
            durations: Schema.Array(Schema.String),
            maxParticipantsLimit: Schema.Int,
            minParticipantsLimit: Schema.Int,
          })
        ),
        data: FormData,
        pairs: Schema.Array(FieldRequirement),
      }),
      run: (input) => {
        const outcome = validateDetailsStep({
          category: input.category,
          data: input.data,
          requirements: input.pairs,
        });

        if (Result.isFailure(outcome)) {
          return { cleaned: null, errors: messages(outcome.failure) };
        }

        const cleaned = outcome.success;

        const python = new Map<string, Json>([
          ["description", cleaned.description],
          ["facilitator_name", cleaned.facilitatorName],
          ["title", cleaned.title],
          ["duration", cleaned.duration],
          ["min_age", cleaned.minAge],
          ["participants_limit", cleaned.participantsLimit],
          ...Object.entries(cleaned.answers),
        ]);

        return {
          cleaned: Object.fromEntries(
            [...python].filter(([, value]) => value !== "" && value !== 0)
          ),
          errors: {},
        };
      },
    });

    expect(mismatches).toStrictEqual([]);
  });

  it("validates the personal step like build_personal_data_form", () => {
    const mismatches = replay({
      cases: personalCases.cases,
      input: Schema.Struct({
        data: FormData,
        pairs: Schema.Array(FieldRequirement),
      }),
      run: (input) => {
        const outcome = validatePersonalStep({
          data: input.data,
          fields: input.pairs,
        });

        return Result.isFailure(outcome)
          ? { cleaned: null, errors: messages(outcome.failure) }
          : {
              cleaned: {
                answers: outcome.success.answers,
                contactEmail: outcome.success.contactEmail,
              },
              errors: {},
            };
      },
    });

    expect(mismatches).toStrictEqual([]);
  });
});
