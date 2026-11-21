import { Schema } from "effect";

export class DuplicateName extends Schema.TaggedError<DuplicateName>()(
  "DuplicateName",
  {
    entity: Schema.String,
    name: Schema.String,
  }
) {
  override get message(): string {
    return `${this.entity} named ${this.name} already exists`;
  }
}
