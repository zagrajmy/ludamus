import { Schema } from "effect";

export class InvalidStoreInput extends Schema.TaggedError<InvalidStoreInput>()(
  "InvalidStoreInput",
  {
    operation: Schema.String,
    reason: Schema.String,
  }
) {
  override get message(): string {
    return `${this.operation} rejected its input: ${this.reason}`;
  }
}
