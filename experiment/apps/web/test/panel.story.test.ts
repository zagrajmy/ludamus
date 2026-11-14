import { describe, expect, it } from "@effect/vitest";
import { Option } from "effect";
import {
  Command,
  expectOutMessage,
  given,
  message,
  model,
  story,
} from "foldkit/story";

import { PanelFailure } from "../src/client/panel/failure.js";
import { PanelOut } from "../src/client/panel/out.js";
import {
  FocusFirstMenuItem,
  FocusMenuButton,
} from "../src/client/panel/proposals/command.js";
import { ProposalDetailMessage } from "../src/client/panel/proposals/message.js";
import type { ProposalDetailModel } from "../src/client/panel/proposals/model.js";
import { updateProposalDetail } from "../src/client/panel/proposals/update.js";
import { SaveTrack } from "../src/client/panel/tracks/command.js";
import { updateTrackForm } from "../src/client/panel/tracks/form-update.js";
import { TrackFormMessage } from "../src/client/panel/tracks/message.js";
import { initTrackForm } from "../src/client/panel/tracks/model.js";
import type { TrackFormModel } from "../src/client/panel/tracks/model.js";
import { translator } from "../src/ui/i18n.js";

const english = translator("en");

const updateForm = (form: TrackFormModel, formMessage: TrackFormMessage) =>
  updateTrackForm(form, formMessage, english);

const newTrack = initTrackForm({
  eventSlug: "thornwood-days",
  managers: [{ id: 15, name: "E2E Manager" }],
  spaces: [{ id: 36, name: "Oak Room" }],
  trackSlug: Option.none(),
  values: { isPublic: true, managerIds: [], name: "", spaceIds: [] },
});

describe("track form", () => {
  it("a submit while a save is in flight sends nothing", () => {
    story(
      updateForm,
      given({ ...newTrack, isSaving: true }),
      message(TrackFormMessage.SubmittedTrackForm()),
      Command.expectNone()
    );
  });

  it("a saved track leaves for the list with the created flash", () => {
    story(
      updateForm,
      given(newTrack),
      message(TrackFormMessage.ChangedName({ value: "Lantern Stories" })),
      message(TrackFormMessage.SubmittedTrackForm()),
      Command.expectExact(SaveTrack),
      model((form) => {
        expect(form.isSaving).toBe(true);
      }),
      Command.resolve(
        SaveTrack,
        TrackFormMessage.SucceededSaveTrack({ slug: "lantern-stories" })
      ),
      expectOutMessage(
        PanelOut.RequestedNavigation({
          href: "/panel/event/thornwood-days/tracks/",
          notes: [{ level: "success", text: "Track created successfully." }],
        })
      )
    );
  });

  it("a refused name stays on the form with its error and lets the organizer resubmit", () => {
    story(
      updateForm,
      given(newTrack),
      message(TrackFormMessage.ToggledSpace({ checked: true, id: 36 })),
      message(TrackFormMessage.SubmittedTrackForm()),
      Command.resolve(
        SaveTrack,
        TrackFormMessage.FailedSaveTrack({
          failure: PanelFailure.Invalid({
            errors: [
              { field: "name", msgid: "Track name is required.", vars: {} },
            ],
          }),
        })
      ),
      model((form) => {
        expect(form.isSaving).toBe(false);
        expect(form.errors.map((error) => error.field)).toEqual(["name"]);
        expect(form.values.spaceIds).toEqual([36]);
      })
    );
  });

  it("a track deleted meanwhile sends the organizer back to the list with the reason", () => {
    story(
      updateForm,
      given({ ...newTrack, trackSlug: Option.some("gone") }),
      message(TrackFormMessage.SubmittedTrackForm()),
      Command.resolve(
        SaveTrack,
        TrackFormMessage.FailedSaveTrack({ failure: PanelFailure.Missing() })
      ),
      expectOutMessage(
        PanelOut.RequestedNavigation({
          href: "/panel/event/thornwood-days/tracks/",
          notes: [{ level: "error", text: "Track not found." }],
        })
      )
    );
  });
});

const detail: ProposalDetailModel = {
  backUrl: "/panel/event/autumn-open/proposals/",
  categoryName: "",
  contactEmail: "",
  coverUrl: "",
  createdLabel: "",
  description: "",
  durationLabel: "",
  eventSlug: "autumn-open",
  facilitatorName: "Host",
  facilitators: [],
  fieldValues: [],
  id: 20,
  isMenuOpen: false,
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
};

describe("proposal actions menu", () => {
  it("opening from the keyboard moves focus into the menu; a click does not steal it", () => {
    story(
      updateProposalDetail,
      given(detail),
      message(ProposalDetailMessage.OpenedMenu({ focusFirst: true })),
      Command.expectExact(FocusFirstMenuItem),
      Command.resolve(
        FocusFirstMenuItem,
        ProposalDetailMessage.CompletedFocus()
      ),
      message(ProposalDetailMessage.ClosedMenu({ refocus: false })),
      message(ProposalDetailMessage.OpenedMenu({ focusFirst: false })),
      Command.expectNone(),
      model((current) => {
        expect(current.isMenuOpen).toBe(true);
      })
    );
  });

  it("Escape closes the menu and hands focus back to its button", () => {
    story(
      updateProposalDetail,
      given({ ...detail, isMenuOpen: true }),
      message(ProposalDetailMessage.ClosedMenu({ refocus: true })),
      Command.expectExact(FocusMenuButton),
      Command.resolve(FocusMenuButton, ProposalDetailMessage.CompletedFocus()),
      model((current) => {
        expect(current.isMenuOpen).toBe(false);
      })
    );
  });
});
