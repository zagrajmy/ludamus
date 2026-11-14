import { Schema } from "effect";

export class SignInRequired extends Schema.TaggedError<
  SignInRequired,
  { readonly brand: unique symbol }
>()(
  "SignInRequired",
  { capabilityName: Schema.String },
  { description: "SignInRequired", httpApiStatus: 401 }
) {
  override get message(): string {
    return `${this.capabilityName} needs a signed-in user`;
  }
}
