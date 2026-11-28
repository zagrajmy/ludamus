import { Context } from "effect";
import type { Effect } from "effect";

export class ClaimTokens extends Context.Service<
  ClaimTokens,
  { readonly next: Effect.Effect<string> }
>()("@zagrajmy/core/enrollment/ClaimTokens") {}
