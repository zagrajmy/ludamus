import { EnrollmentStoreError } from "@zagrajmy/core/enrollment/errors";
import { Effect, Predicate } from "effect";

export const asEnrollmentFailure =
  (operation: string) =>
  <A, E extends { readonly _tag: string }, R>(effect: Effect.Effect<A, E, R>) =>
    effect.pipe(
      Effect.mapError(
        (failure) =>
          new EnrollmentStoreError({
            operation,
            reason:
              Predicate.hasProperty(failure, "reason") &&
              Predicate.isString(failure.reason)
                ? `${failure._tag}: ${failure.reason}`
                : failure._tag,
          })
      )
    );
