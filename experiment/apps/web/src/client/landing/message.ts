import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { Audience } from "./model.js";

export const LandingMessage = defineMessageUnion({
  ChangedAudience: { audience: Audience },
  CompletedChoreography: {},
  GotLocationHash: { hash: Schema.String },
  ReplacedAudienceHash: {},
});

export type LandingMessage = typeof LandingMessage.Type;
