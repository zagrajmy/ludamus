import { FormError, PanelRefusalReason } from "@zagrajmy/core/contracts";
import { Effect, Option, Predicate, Result, Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import { FlashLevel } from "../../ui/flash.js";
import type { Translator } from "../../ui/i18n.js";

export const PanelFailure = defineTaggedUnion({
  Broken: {},
  Conflict: { deleted: Schema.Int, live: Schema.Int },
  Invalid: { errors: Schema.Array(FormError) },
  Missing: {},
  Refused: { reason: PanelRefusalReason },
  Scheduled: {},
});

export type PanelFailure = typeof PanelFailure.Type;

export const FlashNote = Schema.Struct({
  level: FlashLevel,
  text: Schema.String,
});

export type FlashNote = typeof FlashNote.Type;

type Tagged = Readonly<{ _tag: string }>;

const FailureFields = {
  conflict: Schema.Struct({ deleted: Schema.Int, live: Schema.Int }),
  invalid: Schema.Struct({ errors: Schema.Array(FormError) }),
  refused: Schema.Struct({ reason: PanelRefusalReason }),
};

const fieldsOf = <A>(schema: Schema.Decoder<A>, failure: Tagged) =>
  Schema.decodeUnknownOption(schema)(failure);

export const toPanelFailure = (failure: Tagged): PanelFailure => {
  if (Predicate.isTagged(failure, "FormInvalid")) {
    return Option.match(fieldsOf(FailureFields.invalid, failure), {
      onNone: () => PanelFailure.Broken(),
      onSome: ({ errors }) => PanelFailure.Invalid({ errors }),
    });
  }

  if (Predicate.isTagged(failure, "PanelAccessDenied")) {
    return Option.match(fieldsOf(FailureFields.refused, failure), {
      onNone: () => PanelFailure.Broken(),
      onSome: ({ reason }) => PanelFailure.Refused({ reason }),
    });
  }

  if (Predicate.isTagged(failure, "FacilitatorHasSessions")) {
    return Option.match(fieldsOf(FailureFields.conflict, failure), {
      onNone: () => PanelFailure.Broken(),
      onSome: (counts) => PanelFailure.Conflict(counts),
    });
  }

  if (Predicate.isTagged(failure, "ProposalScheduled")) {
    return PanelFailure.Scheduled();
  }

  return Predicate.isTagged(failure, "NotFound")
    ? PanelFailure.Missing()
    : PanelFailure.Broken();
};

export const catchPanelFailure = <A, B, E extends Tagged, R>(
  effect: Effect.Effect<A, E, R>,
  onFailure: (failure: PanelFailure) => B
): Effect.Effect<A | B, never, R> =>
  effect.pipe(
    Effect.result,
    Effect.map(
      Result.match({
        onFailure: (failure: E): A | B => onFailure(toPanelFailure(failure)),
        onSuccess: (value: A): A | B => value,
      })
    ),
    Effect.catchDefect(() => Effect.succeed(onFailure(PanelFailure.Broken())))
  );

export const BROKEN_SAVE =
  "Something went wrong on our side and your change wasn't saved. Please try again.";

export const refusalText = (
  reason: PanelRefusalReason,
  translator: Translator
) =>
  reason === "read_only"
    ? translator.t("Your role can read the panel, but not make changes here.")
    : translator.t("You don't have permission to access the backoffice panel.");

export const errorsFor = (
  errors: readonly FormError[],
  field: string,
  translator: Translator
) =>
  errors.flatMap((error) =>
    error.field === field ? [translator.t(error.msgid, error.vars)] : []
  );
