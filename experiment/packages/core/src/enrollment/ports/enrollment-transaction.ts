import { Context } from "effect";
import type { Effect } from "effect";
import type { EnrollmentStoreError } from "../errors.js";

export class EnrollmentTransaction extends Context.Service<
  EnrollmentTransaction,
  {
    readonly atomic: <A, E, R>(
      effect: Effect.Effect<A, E, R>
    ) => Effect.Effect<A, E | EnrollmentStoreError, R>;
  }
>()("@zagrajmy/core/enrollment/EnrollmentTransaction") {}
