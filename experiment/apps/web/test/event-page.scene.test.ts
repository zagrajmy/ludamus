import { describe, it } from "@effect/vitest";
import {
  Command,
  expect,
  given,
  inside,
  role,
  scene,
  selector,
  type,
} from "foldkit/scene";

import { ReplaceQuery } from "../src/client/event-page/command.js";
import { EventPageMessage } from "../src/client/event-page/message.js";
import { PageFlags } from "../src/client/model.js";
import { update } from "../src/client/update.js";
import { view } from "../src/features/app.js";
import { eventPageFlags } from "./event-page.fixtures.js";
import { modelFor, shellFlags } from "./fixtures.js";

const config = { update, view };

const eventPage = (overrides: Parameters<typeof eventPageFlags>[0] = {}) =>
  modelFor({
    page: PageFlags.EventPage({ flags: eventPageFlags(overrides) }),
    shell: shellFlags(),
  });

describe("event page", () => {
  it("names the event and links every scheduled card to its details", () => {
    scene(
      config,
      given(eventPage()),
      expect(role("heading", { level: 1, name: "Spring Meet" })).toExist(),
      expect(role("link", { name: "Open details for Strategy Lab" })).toHaveAttr(
        "href",
        "?session=1"
      ),
      expect(selector('[data-session-id="2"]')).toHaveAttr("data-takes-enrollment", "false")
    );
  });

  it("a single-layout schedule offers no view switcher", () => {
    scene(
      config,
      given(eventPage()),
      expect(role("tablist", { name: "Schedule view" })).toBeAbsent()
    );
  });

  it("a search that matches nothing shows the empty state, not an empty grid", () => {
    scene(
      config,
      given(eventPage()),
      type(role("textbox", { name: "Search by name or text..." }), "zzzz"),
      Command.resolve(ReplaceQuery, EventPageMessage.CompletedUrlUpdate()),
      expect(selector("#filter-no-results")).toBeVisible()
    );
  });

  it("a session that takes no sign-up opens without the Participants tab", () => {
    scene(
      config,
      given(eventPage({ query: "?session=2" })),
      inside(
        selector("#session-dialog"),
        expect(role("heading", { name: "Story Circle" })).toExist(),
        expect(role("tablist")).toBeAbsent()
      )
    );
  });

  it("a session that takes sign-up offers the roster tab", () => {
    scene(
      config,
      given(eventPage({ query: "?session=1" })),
      inside(
        selector("#session-dialog"),
        expect(role("tab", { name: /Participants/ })).toExist()
      )
    );
  });
});
