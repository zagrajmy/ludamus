import { Schema } from "effect";

export const PanelRefusalReason = Schema.Literals([
  "sign_in",
  "no_panel_access",
  "read_only",
]);

export type PanelRefusalReason = typeof PanelRefusalReason.Type;
