import { describe, it } from "@effect/vitest";
import { Option } from "effect";
import { expect, given, inside, role, scene, text } from "foldkit/scene";

import { PageFlags } from "../src/client/model.js";
import type { PanelPageFlags } from "../src/client/panel/flags.js";
import { PanelPageFlags as PanelPage } from "../src/client/panel/flags.js";
import type {
  ProposalDetailFlags,
  ProposalsFlags,
} from "../src/client/panel/proposals/flags.js";
import { update } from "../src/client/update.js";
import { view } from "../src/features/app.js";
import { manager, modelFor, shellFlags } from "./fixtures.js";

const config = { update, view };

const panelModel = (page: PanelPageFlags) =>
  modelFor({
    page: PageFlags.Panel({
      flags: {
        chrome: {
          activeNav: "proposals",
          currentEvent: Option.some({
            dateLabel: "01 Nov 2031",
            isProposalActive: true,
            name: "Autumn Open Playtest",
            slug: "autumn-open",
          }),
          events: [{ name: "Autumn Open Playtest", slug: "autumn-open" }],
          locale: "en",
        },
        page,
      },
    }),
    shell: shellFlags({ viewer: Option.some(manager) }),
  });

const detail = (
  overrides: Partial<ProposalDetailFlags> = {}
): ProposalDetailFlags => ({
  backUrl: "/panel/event/autumn-open/proposals/",
  categoryName: "RPG",
  contactEmail: "",
  coverUrl: "",
  createdLabel: "",
  description: "",
  durationLabel: "",
  eventSlug: "autumn-open",
  facilitatorName: "Game Master Alex",
  facilitators: [],
  fieldValues: [],
  id: 20,
  minAge: 0,
  modifiedLabel: "",
  participantsLimit: 4,
  preferredSlots: [],
  presenter: "",
  scheduled: "",
  slug: "pending-neon-proposal",
  status: "pending",
  title: "Pending Neon Proposal",
  tracks: [],
  ...overrides,
});

const proposals = (
  overrides: Partial<ProposalsFlags> = {}
): ProposalsFlags => ({
  categories: [],
  cells: [],
  columns: [{ key: "title", kind: "text", label: "Title" }],
  deleted: [],
  eventSlug: "autumn-open",
  fields: [],
  filterStatus: "pending",
  filters: { category: "", search: "", sort: "", status: "pending", track: "" },
  fullPath: "/panel/event/autumn-open/proposals/",
  hasProposals: false,
  listPath: "/panel/event/autumn-open/proposals/",
  rows: [],
  tracks: [],
  ...overrides,
});

describe("panel proposal detail", () => {
  it("a pending proposal offers Accept up front and keeps Hold and Reject under More", () => {
    scene(
      config,
      given(panelModel(PanelPage.ProposalDetail({ flags: detail() }))),
      expect(role("heading", { name: "Pending Neon Proposal" })).toExist(),
      expect(role("button", { name: "Accept" })).toExist(),
      expect(role("button", { name: "More" })).toExist(),
      expect(role("button", { name: "Move to pending" })).toBeAbsent()
    );
  });

  it("a scheduled proposal offers no status change, only edit and delete", () => {
    scene(
      config,
      given(
        panelModel(
          PanelPage.ProposalDetail({
            flags: detail({
              scheduled: "Scheduled in Hall, Nov 1 – 12:00",
              status: "accepted",
            }),
          })
        )
      ),
      expect(text("Scheduled")).toExist(),
      expect(role("link", { name: "Edit" })).toExist(),
      expect(role("button", { name: "Delete proposal" })).toExist(),
      expect(role("button", { name: "More" })).toBeAbsent(),
      expect(role("button", { name: "Accept" })).toBeAbsent()
    );
  });
});

describe("panel proposals list", () => {
  it("an event with no proposals says so instead of blaming the pending filter", () => {
    scene(
      config,
      given(panelModel(PanelPage.Proposals({ flags: proposals() }))),
      expect(text("No proposals submitted yet.")).toExist(),
      expect(text("No proposals match the current filters.")).toBeAbsent()
    );
  });

  it("a filtered-out list offers the way back to every status", () => {
    scene(
      config,
      given(
        panelModel(
          PanelPage.Proposals({
            flags: proposals({ filterStatus: "on_hold", hasProposals: true }),
          })
        )
      ),
      expect(text("No proposals match the current filters.")).toExist(),
      expect(role("link", { name: "Show all statuses" })).toHaveAttr(
        "href",
        "/panel/event/autumn-open/proposals/?status=all"
      )
    );
  });

  it("the deleted section appears only with something to restore, each row with its own Restore", () => {
    const row = {
      categoryName: "",
      createdLabel: "",
      facilitatorName: "Host",
      id: 20,
      isScheduled: false,
      status: "pending" as const,
      title: "Pending Neon Proposal",
    };

    scene(
      config,
      given(
        panelModel(
          PanelPage.Proposals({
            flags: proposals({ deleted: [row], hasProposals: true }),
          })
        )
      ),
      expect(role("heading", { name: "Recently deleted" })).toExist(),
      inside(
        role("row", { name: /Pending Neon Proposal/u }),
        expect(role("button", { name: "Restore" })).toExist()
      )
    );
  });
});

describe("panel tracks", () => {
  it("a private track reads Private and lists its rooms as list items", () => {
    scene(
      config,
      given(
        panelModel(
          PanelPage.Tracks({
            flags: {
              eventSlug: "autumn-open",
              tracks: [
                {
                  isPublic: false,
                  managerNames: ["Local Manager"],
                  name: "Lantern Stories",
                  slug: "lantern-stories",
                  spaceNames: ["Birch Room", "Cedar Room"],
                },
              ],
            },
          })
        )
      ),
      inside(
        role("row", { name: /Lantern Stories/u }),
        expect(text("Private")).toExist(),
        expect(role("listitem", { name: "Birch Room" })).toExist(),
        expect(role("button", { name: "Delete" })).toExist()
      )
    );
  });
});
