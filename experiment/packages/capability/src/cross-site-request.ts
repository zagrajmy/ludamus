import { Schema } from "effect";

export class CrossSiteRequest extends Schema.TaggedError<
  CrossSiteRequest,
  { readonly brand: unique symbol }
>()(
  "CrossSiteRequest",
  { capabilityName: Schema.String },
  { description: "CrossSiteRequest", httpApiStatus: 403 }
) {
  override get message(): string {
    return `${this.capabilityName} changes data and accepts same-origin requests only`;
  }
}
