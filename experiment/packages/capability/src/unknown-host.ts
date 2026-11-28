import { Schema } from "effect";

export class UnknownHost extends Schema.TaggedError<
  UnknownHost,
  { readonly brand: unique symbol }
>()(
  "UnknownHost",
  { host: Schema.String },
  { description: "UnknownHost", httpApiStatus: 404 }
) {
  override get message(): string {
    return `Nothing is served at ${this.host}`;
  }
}
