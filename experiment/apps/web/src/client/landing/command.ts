import { Effect } from "effect";
import { Command } from "foldkit";
import { replaceUrl } from "foldkit/navigation";

import { LandingMessage } from "./message.js";
import { Audience, playersHash } from "./model.js";

export const ReadLocationHash = Command.define("ReadLocationHash", {
  execute: Effect.sync(() =>
    LandingMessage.GotLocationHash({
      hash: window.location.hash.replace(/^#/u, ""),
    })
  ),
  messages: [LandingMessage.GotLocationHash],
});

export const ReplaceAudienceHash = Command.define("ReplaceAudienceHash", {
  args: { audience: Audience },
  execute: ({ audience }) =>
    Effect.suspend(() =>
      replaceUrl(
        audience === "players"
          ? `#${playersHash}`
          : `${window.location.pathname}${window.location.search}`
      )
    ).pipe(Effect.as(LandingMessage.ReplacedAudienceHash())),
  messages: [LandingMessage.ReplacedAudienceHash],
});

export const WaitForChoreography = Command.define("WaitForChoreography", {
  execute: Effect.sleep("1600 millis").pipe(
    Effect.as(LandingMessage.CompletedChoreography())
  ),
  messages: [LandingMessage.CompletedChoreography],
});
