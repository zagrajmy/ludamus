import { Schema } from "effect";

export class MissingRootSphere extends Schema.TaggedError<MissingRootSphere>()(
  "MissingRootSphere",
  {
    siteId: Schema.Int,
  }
) {
  override get message(): string {
    return `No sphere belongs to the root site ${this.siteId}`;
  }
}
