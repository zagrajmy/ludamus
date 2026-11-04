import { Schema } from "effect";

import { PanelRefusalReason } from "./refusal-reason.js";

export class PanelAccessDenied extends Schema.TaggedError<PanelAccessDenied>()(
  "PanelAccessDenied",
  { reason: PanelRefusalReason },
  { description: "PanelAccessDenied", httpApiStatus: 403 }
) {
  override get message(): string {
    return this.reason === "read_only"
      ? "Your role can read the panel, but not make changes here."
      : "You don't have permission to access the backoffice panel.";
  }
}
