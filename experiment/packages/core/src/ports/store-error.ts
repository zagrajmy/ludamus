import { Schema } from "effect";

import type { InvalidStoreInput } from "./invalid-store-input.js";

export class StoreError extends Schema.TaggedError<
  StoreError,
  { readonly brand: unique symbol }
>()("StoreError", {
  operation: Schema.String,
  reason: Schema.String,
}) {
  override get message(): string {
    return `${this.operation} failed: ${this.reason}`;
  }
}

export type StoreFailure = StoreError | InvalidStoreInput;

export { DuplicateName } from "./duplicate-name.js";

export { InvalidStoreInput } from "./invalid-store-input.js";

export { NotFound } from "./not-found.js";
