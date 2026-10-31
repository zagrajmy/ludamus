import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { ConfirmPrompt, PanelAction } from "./action.js";
import { FlashNote } from "./failure.js";

export const PanelOut = defineMessageUnion({
  RequestedAction: { action: PanelAction },
  RequestedConfirm: { action: PanelAction, prompt: ConfirmPrompt },
  RequestedNavigation: { href: Schema.String, notes: Schema.Array(FlashNote) },
});

export type PanelOut = typeof PanelOut.Type;
