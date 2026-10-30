import { describe, expect, it } from "@effect/vitest";
import { Command, given, message, model, story } from "foldkit/story";

import { ReplaceAudienceHash } from "../src/client/landing/command.js";
import { LandingMessage } from "../src/client/landing/message.js";
import { initLanding } from "../src/client/landing/model.js";
import { updateLanding } from "../src/client/landing/update.js";
import { ApplyTheme } from "../src/client/shell/command.js";
import { ShellMessage } from "../src/client/shell/message.js";
import { initShell } from "../src/client/shell/model.js";
import { updateShell } from "../src/client/shell/update.js";
import { shellFlags } from "./fixtures.js";

const shell = initShell(shellFlags());

describe("theme", () => {
  it("a colour-scheme change before the stored theme is read does not override it", () => {
    story(
      updateShell,
      given(shell),
      message(ShellMessage.ChangedSystemColorScheme()),
      Command.expectNone()
    );
  });

  it("follows the system once the stored theme is known to be system", () => {
    story(
      updateShell,
      given(shell),
      message(ShellMessage.GotStoredTheme({ theme: "system" })),
      message(ShellMessage.ChangedSystemColorScheme()),
      Command.expectExact(ApplyTheme),
      Command.resolve(
        ApplyTheme,
        ShellMessage.AppliedTheme({ theme: "system" })
      )
    );
  });

  it("ignores the system once a manual theme is stored", () => {
    story(
      updateShell,
      given(shell),
      message(ShellMessage.GotStoredTheme({ theme: "dark" })),
      message(ShellMessage.ChangedSystemColorScheme()),
      Command.expectNone()
    );
  });
});

describe("landing audience", () => {
  const landing = initLanding({
    contactEmail: "kontakt@zagrajmy.net",
    conventions: [],
    encountersEnabled: true,
    showcaseUrl: "https://kapitularz.zagrajmy.net/",
  });

  it("a deep link into the player view opens it, an unrelated hash keeps the current view", () => {
    story(
      updateLanding,
      given(landing),
      message(
        LandingMessage.GotLocationHash({ hash: "g-conventions-heading" })
      ),
      model((current) => {
        expect(current.audience).toBe("players");
      }),
      message(LandingMessage.GotLocationHash({ hash: "pricing" })),
      model((current) => {
        expect(current.audience).toBe("players");
      }),
      message(LandingMessage.GotLocationHash({ hash: "" })),
      model((current) => {
        expect(current.audience).toBe("organizers");
      })
    );
  });

  it("switching the audience writes it to the URL", () => {
    story(
      updateLanding,
      given(landing),
      message(LandingMessage.ChangedAudience({ audience: "players" })),
      Command.expectExact(ReplaceAudienceHash),
      Command.resolve(
        ReplaceAudienceHash,
        LandingMessage.ReplacedAudienceHash()
      )
    );
  });
});
