import { describe, it } from "@effect/vitest";
import { Predicate } from "effect";
import {
  click,
  Command,
  expect,
  given,
  inside,
  role,
  scene,
  selector,
} from "foldkit/scene";

import {
  EnrollmentActions,
  EnrollmentSlotMessage,
} from "../src/client/event-page/enrollment-slot.js";
import { SubmitFooterChoice } from "../src/client/event-page/enrollment/command.js";
import type { FooterState } from "../src/client/event-page/enrollment/model.js";
import { PageFlags, PageModel } from "../src/client/model.js";
import type { Model } from "../src/client/model.js";
import { update } from "../src/client/update.js";
import { view } from "../src/features/app.js";
import {
  enrolledFooter,
  enrollFooter,
  seats,
  shutFooter,
} from "./enrollment.fixtures.js";
import { eventPageFlags } from "./event-page.fixtures.js";
import { modelFor, shellFlags } from "./fixtures.js";

const config = { update, view };

const withSeat = (state: Partial<FooterState>): Model => {
  const base = modelFor({
    page: PageFlags.EventPage({
      flags: eventPageFlags({ query: "?session=1", signedIn: true }),
    }),
    shell: shellFlags(),
  });

  if (!Predicate.isTagged(base.page, "EventPage")) {
    return base;
  }

  return {
    ...base,
    page: PageModel.EventPage({
      model: {
        ...base.page.model,
        enrollment: EnrollmentActions.Seat({
          state: {
            busy: false,
            error: "",
            eventSlug: "spring-meet",
            footer: enrollFooter,
            notice: "",
            sessionId: 1,
            viewerId: 7,
            ...state,
          },
        }),
      },
    }),
  };
};

const footer = selector("[data-session-footer]");

describe("the session dialog's seat control", () => {
  it("a session with room offers Enroll, with the group flow as its own link", () => {
    scene(
      config,
      given(withSeat({})),
      inside(
        footer,
        expect(role("button", { name: /^\s*Enroll$/u })).toExist(),
        expect(role("link", { name: "with others" })).toHaveAttr(
          "href",
          "/event/spring-meet/session/1/enrollment/"
        ),
        expect(role("status")).toBeAbsent()
      )
    );
  });

  it("clicking Enroll posts the viewer's choice", () => {
    scene(
      config,
      given(withSeat({})),
      click(role("button", { name: /^\s*Enroll$/u })),
      Command.expectExact(
        SubmitFooterChoice({
          confirm: "",
          locale: "en",
          sessionId: 1,
          value: "enroll",
          viewerId: 7,
        })
      ),
      Command.resolve(
        SubmitFooterChoice,
        EnrollmentSlotMessage.SucceededSubmitEnrollments({
          footer: enrolledFooter,
          notice: "Enrolled: Ola",
          seats: seats({ enrolledCount: 1, seatsLeft: 5 }),
          sessionId: 1,
        })
      ),
      inside(
        footer,
        expect(role("button", { name: /^\s*Cancel$/u })).toExist(),
        expect(role("status")).toBeAbsent()
      )
    );
  });

  it("giving up the last seat on a shut window says so instead of going blank", () => {
    scene(
      config,
      given(withSeat({ footer: shutFooter, notice: "Cancelled: Ola" })),
      inside(footer, expect(role("status")).toContainText("Cancelled: Ola"))
    );
  });

  it("a refused enroll is read out as an alert next to the control", () => {
    scene(
      config,
      given(withSeat({ error: "Not enough spots available." })),
      inside(
        footer,
        expect(role("alert")).toContainText("Not enough spots available.")
      )
    );
  });
});
