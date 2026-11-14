import { describe, expect as vitestExpect, it } from "@effect/vitest";
import { Option } from "effect";
import {
  Command,
  change,
  click,
  expect,
  given,
  inside,
  role,
  scene,
  text,
} from "foldkit/scene";

import { ApplyTheme } from "../src/client/shell/command.js";
import { ShellMessage } from "../src/client/shell/message.js";
import { update } from "../src/client/update.js";
import { view } from "../src/features/app.js";
import { documentTitle } from "../src/features/shell/title.js";
import { feedModel, manager, player } from "./fixtures.js";

const config = { update, view };

describe("navbar by viewer", () => {
  it("a signed-out visitor gets a Log in link that returns them here, and no account menu", () => {
    scene(
      config,
      given(feedModel()),
      expect(role("link", { name: "Log in" })).toHaveAttr(
        "href",
        "/crowd/auth0/do/login?next=http%3A%2F%2Fcrew.localhost%3A8000%2F"
      ),
      expect(role("button", { name: "Account menu" })).toBeAbsent()
    );
  });

  it("a signed-in player opens the account menu and sees the dashboard and logout, but no panel", () => {
    scene(
      config,
      given(feedModel({ shell: { viewer: Option.some(player) } })),
      expect(role("link", { name: "Log in" })).toBeAbsent(),
      expect(role("button", { name: "Account menu" })).toHaveAttr(
        "aria-expanded",
        "false"
      ),
      click(role("button", { name: "Account menu" })),
      expect(role("button", { name: "Account menu" })).toHaveAttr(
        "aria-expanded",
        "true"
      ),
      expect(text("player@example.com")).toExist(),
      expect(role("link", { name: "Your dashboard" })).toHaveAttr(
        "href",
        "http://localhost:8000/dashboard/"
      ),
      expect(role("link", { name: "Log out" })).toHaveAttr(
        "href",
        "/crowd/auth0/do/logout"
      ),
      expect(role("link", { name: "Panel" })).toBeAbsent()
    );
  });

  it("a sphere manager also gets the panel link", () => {
    scene(
      config,
      given(
        feedModel({
          shell: {
            links: {
              ...feedModel().shell.links,
              panel: Option.some("/panel/"),
            },
            viewer: Option.some(manager),
          },
        })
      ),
      click(role("button", { name: "Account menu" })),
      expect(role("link", { name: "Panel" })).toHaveAttr("href", "/panel/")
    );
  });

  it("a sphere other than the root links its own name; the root sphere shows only the brand", () => {
    scene(
      config,
      given(feedModel()),
      expect(role("link", { name: "Crew Sphere" })).toHaveAttr(
        "href",
        "http://crew.localhost:8000/"
      )
    );
    scene(
      config,
      given(feedModel({ shell: { isRootSphere: true } })),
      expect(role("link", { name: "Crew Sphere" })).toBeAbsent()
    );
  });
});

describe("footer", () => {
  it("links the documents, the root domain's about page and the AGPL source", () => {
    scene(
      config,
      given(feedModel()),
      inside(
        role("contentinfo"),
        expect(role("link", { name: "Privacy Policy" })).toHaveAttr(
          "href",
          "/privacy-policy/"
        ),
        expect(role("link", { name: "Terms of Service" })).toHaveAttr(
          "href",
          "/terms-of-service/"
        ),
        expect(role("link", { name: "About Zagrajmy" })).toHaveAttr(
          "href",
          "http://localhost:8000/about/"
        ),
        expect(role("link", { name: "Source code" })).toHaveAttr(
          "href",
          "https://github.com/zagrajmy/ludamus"
        ),
        expect(role("link", { name: "AGPL-3.0" })).toHaveAttr(
          "href",
          "https://github.com/zagrajmy/ludamus/blob/main/LICENSE"
        )
      )
    );
  });

  it("choosing a theme checks its radio and applies it", () => {
    scene(
      config,
      given(feedModel()),
      expect(role("radio", { name: "light" })).not.toBeChecked(),
      change(role("radio", { name: "light" }), "light"),
      Command.resolve(
        ApplyTheme,
        ShellMessage.AppliedTheme({ theme: "light" })
      ),
      expect(role("radio", { name: "light" })).toBeChecked(),
      expect(role("radio", { name: "system" })).not.toBeChecked()
    );
  });
});

describe("document title", () => {
  it("names the page, then the sphere, then Zagrajmy off the root, with bullets only", () => {
    vitestExpect(
      documentTitle({
        isRootSphere: false,
        page: { name: "Events", sphereSuffix: true },
        sphereName: "Crew Sphere",
      })
    ).toBe("Events • Crew Sphere • Zagrajmy");
    vitestExpect(
      documentTitle({
        isRootSphere: true,
        page: { name: "Privacy Policy", sphereSuffix: true },
        sphereName: "Root Domain Sphere",
      })
    ).toBe("Privacy Policy • Root Domain Sphere");
    vitestExpect(
      documentTitle({
        isRootSphere: true,
        page: { name: "About Zagrajmy", sphereSuffix: false },
        sphereName: "Root Domain Sphere",
      })
    ).toBe("About Zagrajmy");
  });
});
