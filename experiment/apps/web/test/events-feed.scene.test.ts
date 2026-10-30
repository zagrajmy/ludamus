import { describe, it } from "@effect/vitest";
import { Option } from "effect";
import {
  Command,
  click,
  expect,
  given,
  inside,
  role,
  scene,
  text,
} from "foldkit/scene";

import {
  CopyShareLink,
  WaitBeforeCopyReset,
} from "../src/client/events-feed/command.js";
import { EventsFeedMessage } from "../src/client/events-feed/message.js";
import { update } from "../src/client/update.js";
import { view } from "../src/features/app.js";
import { EncounterAttendance } from "../src/ui/feed-card.js";
import {
  encounterCard,
  eventCard,
  feedItem,
  feedModel,
  player,
} from "./fixtures.js";

const config = { update, view };

describe("events feed", () => {
  it("an empty sphere says nothing is scheduled instead of drawing empty Upcoming and Past sections", () => {
    scene(
      config,
      given(feedModel()),
      expect(text("Nothing scheduled yet")).toExist(),
      expect(role("heading", { name: "Upcoming" })).toBeAbsent(),
      expect(role("heading", { name: "Past" })).toBeAbsent(),
      expect(role("link", { name: "Create Encounter" })).toBeAbsent()
    );
  });

  it("only past items still head the grid with Upcoming and say nothing is coming up", () => {
    scene(
      config,
      given(feedModel({ feed: { past: [feedItem.event(eventCard())] } })),
      expect(role("heading", { name: "Upcoming" })).toExist(),
      expect(text("Nothing coming up.")).toExist(),
      expect(role("heading", { name: "Past" })).toExist()
    );
  });

  it("an event card links to its page and counts its sessions", () => {
    scene(
      config,
      given(
        feedModel({
          feed: { upcoming: [feedItem.event(eventCard({ sessionCount: 1 }))] },
        })
      ),
      inside(
        role("link", { name: /Harvest Convention/ }),
        expect(role("heading", { name: "Harvest Convention" })).toExist(),
        expect(text("1 session")).toExist(),
        expect(text("Nov 9, 2031, 1 p.m. – 6 p.m.")).toExist()
      ),
      expect(role("link", { name: /Harvest Convention/ })).toHaveAttr(
        "href",
        "/event/harvest-convention/"
      )
    );
  });

  it("an encounter card links to its share page and counts spots, not sessions", () => {
    scene(
      config,
      given(
        feedModel({ feed: { upcoming: [feedItem.encounter(encounterCard())] } })
      ),
      expect(role("link", { name: /Late Night Tactics/ })).toHaveAttr(
        "href",
        "/e/FEED01/"
      ),
      inside(
        role("link", { name: /Late Night Tactics/ }),
        expect(text("4 spots left")).toExist(),
        expect(text("Hosted by Tester")).toExist(),
        expect(text(/session/)).toBeAbsent(),
        expect(text("Link only")).toBeAbsent()
      )
    );
  });

  it("a past encounter counts who came", () => {
    scene(
      config,
      given(
        feedModel({
          feed: {
            past: [
              feedItem.encounter(
                encounterCard({
                  attendance: EncounterAttendance.Attending({ count: 0 }),
                })
              ),
            ],
          },
        })
      ),
      expect(text("0 attending")).toExist(),
      expect(text(/spots? left/)).toBeAbsent()
    );
  });

  it("marks a link-only event for managers and hides the mark from everyone else", () => {
    const unlisted = feedItem.event(
      eventCard({
        isLinkOnly: true,
        name: "Crew Sneak Peek",
        slug: "crew-sneak-peek",
      })
    );

    scene(
      config,
      given(feedModel({ feed: { showHidden: true, upcoming: [unlisted] } })),
      expect(text("Link only")).toExist()
    );
    scene(
      config,
      given(feedModel({ feed: { showHidden: false, upcoming: [unlisted] } })),
      expect(text("Link only")).toBeAbsent()
    );
  });

  it("the organizer copies the share link and sees it confirmed until the reset", () => {
    scene(
      config,
      given(
        feedModel({
          feed: {
            upcoming: [
              feedItem.encounter(
                encounterCard({ isMine: true, organizerName: Option.none() })
              ),
            ],
          },
          shell: { viewer: Option.some(player) },
        })
      ),
      expect(text("You organize")).toExist(),
      click(role("button", { name: /\/e\/FEED01\// })),
      Command.resolve(
        CopyShareLink,
        EventsFeedMessage.SucceededCopyShareLink({ shareCode: "FEED01" })
      ),
      expect(role("status")).toHaveText("Copied!"),
      Command.resolve(
        WaitBeforeCopyReset,
        EventsFeedMessage.CompletedWaitBeforeCopyReset({ shareCode: "FEED01" })
      ),
      expect(text("Copied!")).toBeAbsent()
    );
  });
});
