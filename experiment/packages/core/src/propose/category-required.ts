import { Schema } from "effect";

export class CategoryRequired extends Schema.TaggedError<CategoryRequired>()(
  "CategoryRequired",
  { eventSlug: Schema.String },
  { httpApiStatus: 422 }
) {
  override get message(): string {
    return `Pick a category of ${this.eventSlug} first.`;
  }
}
