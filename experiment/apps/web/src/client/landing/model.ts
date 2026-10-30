import { Schema } from "effect";

import { LandingFlags } from "./flags.js";

export const Audience = Schema.Literals(["organizers", "players"]);
export type Audience = typeof Audience.Type;

export const playersHash = "gracze";
export const playersConventionsHash = "g-conventions-heading";

export const audienceForHash = (hash: string): Audience =>
  hash === playersHash || hash === playersConventionsHash
    ? "players"
    : "organizers";

export const LandingModel = Schema.Struct({
  ...LandingFlags.fields,
  audience: Audience,
  isChoreographyDone: Schema.Boolean,
});
export type LandingModel = typeof LandingModel.Type;

export const initLanding = (flags: LandingFlags): LandingModel => ({
  ...flags,
  audience: "organizers",
  isChoreographyDone: false,
});
