import { describe, it } from "@effect/vitest";
import { PersonalAccepted } from "@zagrajmy/core/contracts";
import {
  Command,
  Mount,
  click,
  expect,
  given,
  inside,
  role,
  scene,
  selector,
  text,
} from "foldkit/scene";

import { EnhanceWriteIn, PostStep } from "../src/client/propose/command.js";
import { ProposeMessage } from "../src/client/propose/message.js";
import { update } from "../src/client/update.js";
import { view } from "../src/features/app.js";
import { proposeModel } from "./propose-fixtures.js";

const config = { update, view };

const onDetails = ProposeMessage.AcceptedStep({
  accepted: PersonalAccepted.make({
    formValues: { contact_email: "anon@example.com" },
    personal: { answers: {}, contactEmail: "anon@example.com" },
  }),
  data: { contact_email: ["anon@example.com"] },
  descriptionHtml: "",
  step: "personal",
});

describe("proposal wizard", () => {
  it("an anonymous visitor starts on their information with a required contact email and a login nudge", () => {
    scene(
      config,
      given(proposeModel()),
      inside(
        role("navigation", { name: "Proposal progress" }),
        expect(text("Your info")).toExist(),
        expect(text("Category")).toBeAbsent()
      ),
      expect(role("heading", { name: "Your Information" })).toExist(),
      expect(role("textbox", { name: /Contact Email/u })).toHaveAttr(
        "required",
        "true"
      ),
      inside(
        selector("#wizard-content"),
        expect(role("link", { name: "Log in" })).toHaveAttr(
          "href",
          "/crowd/login-required/?next=/event/open-mic/session/propose/"
        )
      ),
      expect(role("button", { name: /Back/u })).toBeAbsent()
    );
  });

  it("the session step names a multi-select by its legend and labels the write-in after its question", () => {
    scene(
      config,
      given(proposeModel()),
      click(role("button", { name: /Continue/u })),
      Command.resolve(PostStep, onDetails),
      expect(text("semicolon separated")).toExist(),
      Mount.resolve(
        EnhanceWriteIn,
        ProposeMessage.EnhancedWriteIn({ name: "session_triggers" })
      ),
      expect(text("Type a value and press Enter to add it.")).toExist(),
      expect(role("heading", { name: "Session Details" })).toExist(),
      expect(role("group", { name: /^Trigger warnings/u })).toExist(),
      expect(
        role("textbox", { name: "Custom value for: Any trigger warnings?" })
      ).toHaveAttr("maxlength", "50"),
      expect(role("combobox", { name: /Duration/u })).toBeAbsent(),
      expect(text("1h")).toExist(),
      expect(role("heading", { name: "Visible to organizers only" })).toExist(),
      expect(role("button", { name: /Back/u })).toExist()
    );
  });

  it("a server rejection puts Django's message beside the write-in it belongs to", () => {
    scene(
      config,
      given(proposeModel()),
      click(role("button", { name: /Continue/u })),
      Command.resolve(PostStep, onDetails),
      Mount.resolve(
        EnhanceWriteIn,
        ProposeMessage.FailedEnhanceWriteIn({ name: "session_triggers" })
      ),
      click(role("button", { name: /Continue/u })),
      Command.resolve(
        PostStep,
        ProposeMessage.RejectedStep({
          errors: {
            session_triggers_custom: [
              {
                code: "max_length",
                msgid:
                  "Ensure this value has at most %(limit_value)d character (it has %(show_value)d).",
                plural: {
                  count: 50,
                  msgid:
                    "Ensure this value has at most %(limit_value)d characters (it has %(show_value)d).",
                },
                vars: { limit_value: 50, show_value: 51 },
              },
            ],
          },
        })
      ),
      expect(
        role("textbox", { name: "Custom value for: Any trigger warnings?" })
      ).toHaveAttr("aria-invalid", "true"),
      expect(
        role("textbox", { name: "Custom value for: Any trigger warnings?" })
      ).toHaveAttr("aria-describedby", "id_session_triggers_custom_error"),
      expect(
        text("Ensure this value has at most 50 characters (it has 51).")
      ).toExist()
    );
  });
});
