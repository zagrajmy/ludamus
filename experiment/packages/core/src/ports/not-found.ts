import { Schema } from "effect";

export class NotFound extends Schema.TaggedError<NotFound>()("NotFound", {
  entity: Schema.String,
  key: Schema.String,
}) {
  override get message(): string {
    return `${this.entity} ${this.key} not found`;
  }
}
