import { describe, expect, it } from "@effect/vitest";
import { Option } from "effect";
import { Command, given, message, model, story } from "foldkit/story";

import {
  CloseSessionDialog,
  FocusElement,
  PushQuery,
  ReplaceQuery,
  SettleComboboxFocus,
  ShowSessionDialog,
} from "../src/client/event-page/command.js";
import { EventPageMessage } from "../src/client/event-page/message.js";
import { initEventPage } from "../src/client/event-page/model.js";
import type { EventPageModel } from "../src/client/event-page/model.js";
import { updateEventPage } from "../src/client/event-page/update.js";
import { eventPageFlags } from "./event-page.fixtures.js";

const page = initEventPage(eventPageFlags());

const compact = initEventPage(
  eventPageFlags({
    layout: {
      _tag: "Compact",
      days: [],
      rooms: { columns: [], days: [], rows: [] },
    },
  })
);

describe("filters mirror into the address bar", () => {
  it("typing a search replaces the query string instead of pushing history", () => {
    story(
      updateEventPage,
      given(page),
      message(EventPageMessage.ChangedSearch({ value: "lab" })),
      model((next: EventPageModel) => {
        expect(next.filters.q).toBe("lab");
      }),
      Command.expectExact(
        ReplaceQuery({
          updates: [
            ["q", "lab"],
            ["enrollment", null],
            ["hide-ended", null],
            ["status", null],
            ["space", null],
            ["age", null],
            ["age-min", null],
            ["day", null],
            ["hour", null],
            ["track", null],
            ["category", null],
            ["host", null],
          ],
        })
      ),
      Command.resolve(ReplaceQuery, EventPageMessage.CompletedUrlUpdate())
    );
  });

  it("the URL echo of a trailing-space search does not trim the box while typing", () => {
    story(
      updateEventPage,
      given({ ...page, filters: { ...page.filters, q: "lab " } }),
      message(EventPageMessage.ChangedUrl({ search: "?q=lab" })),
      model((next: EventPageModel) => {
        expect(next.filters.q).toBe("lab ");
      }),
      Command.expectNone()
    );
  });

  it("an age outside 0-99 is dropped rather than applied", () => {
    story(
      updateEventPage,
      given(page),
      message(EventPageMessage.ChangedAge({ value: "120" })),
      model((next: EventPageModel) => {
        expect(next.filters.age).toBe("");
      }),
      Command.resolve(ReplaceQuery, EventPageMessage.CompletedUrlUpdate())
    );
  });
});

describe("the host combobox", () => {
  it("Enter commits the only match without arrowing to it, and keeps the list open", () => {
    story(
      updateEventPage,
      given(page),
      message(EventPageMessage.TypedCombobox({ id: "host", value: "chen" })),
      message(
        EventPageMessage.PressedComboboxKey({
          id: "host",
          key: "Enter",
          shiftKey: false,
        })
      ),
      model((next: EventPageModel) => {
        expect(next.filters.host).toEqual(["Priya Chen"]);
        expect(Option.isSome(next.combobox)).toBe(true);
      }),
      Command.resolve(ReplaceQuery, EventPageMessage.CompletedUrlUpdate()),
      Command.resolve(SettleComboboxFocus, EventPageMessage.CompletedFocus())
    );
  });

  it("Escape with the list shut closes the panel, not the pick", () => {
    story(
      updateEventPage,
      given({
        ...page,
        filters: { ...page.filters, host: ["Priya Chen"] },
        isPanelOpen: true,
      }),
      message(
        EventPageMessage.PressedComboboxKey({
          id: "host",
          key: "Escape",
          shiftKey: false,
        })
      ),
      model((next: EventPageModel) => {
        expect(next.isPanelOpen).toBe(false);
        expect(next.filters.host).toEqual(["Priya Chen"]);
      }),
      Command.resolve(FocusElement, EventPageMessage.CompletedFocus())
    );
  });
});

describe("the session dialog", () => {
  it("a ?session= link opens the dialog and pushes the param, keeping the filters", () => {
    story(
      updateEventPage,
      given(page),
      message(
        EventPageMessage.ClickedSamePageLink({ hash: "", search: "?session=1" })
      ),
      model((next: EventPageModel) => {
        expect(next.openSession).toEqual(Option.some(1));
      }),
      Command.expectHas(
        PushQuery({ updates: [["session", "1"]] }),
        ShowSessionDialog({ animate: true, sessionId: 1 })
      ),
      Command.resolve(PushQuery, EventPageMessage.CompletedUrlUpdate()),
      Command.resolve(ShowSessionDialog, EventPageMessage.CompletedFocus())
    );
  });

  it("a ?session= for a session the page does not list opens nothing", () => {
    story(
      updateEventPage,
      given(page),
      message(
        EventPageMessage.ClickedSamePageLink({
          hash: "",
          search: "?session=999",
        })
      ),
      model((next: EventPageModel) => {
        expect(Option.isNone(next.openSession)).toBe(true);
      }),
      Command.expectNone()
    );
  });

  it("closing drops only the session param", () => {
    story(
      updateEventPage,
      given({
        ...page,
        openSession: Option.some(1),
        shownSession: Option.some(1),
      }),
      message(EventPageMessage.ClosedSessionDialog()),
      model((next: EventPageModel) => {
        expect(Option.isNone(next.openSession)).toBe(true);
        expect(next.shownSession).toEqual(Option.some(1));
      }),
      Command.expectExact(
        CloseSessionDialog({ sessionId: 1 }),
        ReplaceQuery({ updates: [["session", null]] })
      ),
      Command.resolve(CloseSessionDialog, EventPageMessage.CompletedFocus()),
      Command.resolve(ReplaceQuery, EventPageMessage.CompletedUrlUpdate())
    );
  });
});

describe("the view switch", () => {
  it("the rooms tab pushes ?view=rooms on a compact schedule", () => {
    story(
      updateEventPage,
      given(compact),
      message(EventPageMessage.SwitchedView({ view: "rooms" })),
      model((next: EventPageModel) => {
        expect(next.view).toBe("rooms");
      }),
      Command.resolve(PushQuery, EventPageMessage.CompletedUrlUpdate())
    );
  });

  it("a card-grid event has one layout and ignores the switch", () => {
    story(
      updateEventPage,
      given(page),
      message(EventPageMessage.SwitchedView({ view: "rooms" })),
      model((next: EventPageModel) => {
        expect(next.view).toBe("list");
      }),
      Command.expectNone()
    );
  });
});
