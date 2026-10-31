import { describe, expect, it } from "@effect/vitest";
import { PersonalAccepted } from "@zagrajmy/core/contracts";
import { Command, given, message, model, story } from "foldkit/story";

import {
  LoadWithFlash,
  PostStep,
  ReadFormSnapshot,
  SubmitProposal,
} from "../src/client/propose/command.js";
import {
  CopyIntent,
  ProposeMessage,
  UndoIntent,
} from "../src/client/propose/message.js";
import { initPropose } from "../src/client/propose/model.js";
import { updatePropose } from "../src/client/propose/update.js";
import { proposeFlags } from "./propose-fixtures.js";

const wizard = initPropose(proposeFlags());

const personalAccepted = ProposeMessage.AcceptedStep({
  accepted: PersonalAccepted.make({
    formValues: { contact_email: "anon@example.com" },
    personal: { answers: {}, contactEmail: "anon@example.com" },
  }),
  data: { contact_email: ["anon@example.com"] },
  descriptionHtml: "",
  step: "personal",
});

describe("proposal wizard steps", () => {
  it("a single category is picked for the proposer, so the wizard opens on their details", () => {
    expect(wizard.categoryId).toBe(8);
    expect(wizard.step).toBe("personal");
  });

  it("Continue posts the step and moves on only once the server accepts it", () => {
    story(
      updatePropose,
      given(wizard),
      message(ProposeMessage.SubmittedStep({ step: "personal" })),
      model((current) => {
        expect(current.step).toBe("personal");
        expect(current.isBusy).toBe(true);
      }),
      Command.expectExact(PostStep),
      Command.resolve(PostStep, personalAccepted),
      model((current) => {
        expect(current.step).toBe("details");
        expect(current.acceptedPersonal?.contactEmail).toBe("anon@example.com");
      })
    );
  });

  it("a rejected step stays put and carries the field errors", () => {
    story(
      updatePropose,
      given(wizard),
      message(ProposeMessage.SubmittedStep({ step: "personal" })),
      Command.resolve(
        PostStep,
        ProposeMessage.RejectedStep({
          errors: {
            contact_email: [
              {
                code: "invalid",
                msgid: "Enter a valid email address.",
                plural: null,
                vars: {},
              },
            ],
          },
        })
      ),
      model((current) => {
        expect(current.step).toBe("personal");
        expect(current.isBusy).toBe(false);
        expect(Object.keys(current.errors)).toStrictEqual(["contact_email"]);
      })
    );
  });

  it("Back from the session step returns to the personal step with what was accepted there", () => {
    story(
      updatePropose,
      given(wizard),
      message(personalAccepted),
      message(ProposeMessage.ClickedBack({ from: "details" })),
      model((current) => {
        expect(current.step).toBe("personal");
        expect(current.personalDraft.contact_email).toStrictEqual([
          "anon@example.com",
        ]);
      })
    );
  });

  it("copying an earlier session keeps what it does not copy, and Undo restores only what it replaced", () => {
    story(
      updatePropose,
      given({ ...wizard, step: "details" }),
      message(ProposeMessage.ClickedCopyFrom({ sessionId: 5 })),
      Command.resolve(
        ReadFormSnapshot,
        ProposeMessage.ReadForm({
          data: { facilitator_name: ["Ola"], title: ["Typed"] },
          intent: CopyIntent.make({ sessionId: 5 }),
        })
      ),
      model((current) => {
        expect(current.detailsDraft.title).toStrictEqual(["Play Mothership"]);
        expect(current.detailsDraft.facilitator_name).toStrictEqual(["Ola"]);
        expect(current.detailsDraft.session_triggers_custom).toStrictEqual([
          "krew",
        ]);
        expect(current.copiedSnapshot).not.toBeNull();
      }),
      message(ProposeMessage.ClickedUndoCopy()),
      Command.resolve(
        ReadFormSnapshot,
        ProposeMessage.ReadForm({
          data: { facilitator_name: ["Ola Wrzos"], title: ["Play Mothership"] },
          intent: UndoIntent.make({}),
        })
      ),
      model((current) => {
        expect(current.detailsDraft.title).toStrictEqual(["Typed"]);
        expect(current.detailsDraft.facilitator_name).toStrictEqual([
          "Ola Wrzos",
        ]);
        expect(current.detailsDraft.session_triggers_custom).toStrictEqual([]);
        expect(current.copiedSnapshot).toBeNull();
      })
    );
  });

  it("a rate-limited submit goes back to the wizard with Django's warning", () => {
    story(
      updatePropose,
      given({ ...wizard, step: "review" }),
      message(ProposeMessage.ClickedSubmitProposal()),
      Command.resolve(
        SubmitProposal,
        ProposeMessage.FailedSubmitProposal({
          errors: {},
          reason: "Throttled",
          step: null,
        })
      ),
      Command.expectExact(LoadWithFlash),
      Command.resolve(LoadWithFlash, ProposeMessage.CompletedNavigation()),
      model((current) => {
        expect(current.isBusy).toBe(false);
      })
    );
  });
});
