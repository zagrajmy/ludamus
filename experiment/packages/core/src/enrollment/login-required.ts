import { Schema } from "effect";

export class LoginRequired extends Schema.TaggedError<LoginRequired>()(
  "LoginRequired",
  { capability: Schema.String },
  { httpApiStatus: 401 }
) {
  override get message(): string {
    return `Sign in to use ${this.capability}`;
  }
}
