import { describe, expect, it } from "@effect/vitest";
import { Predicate } from "effect";
import { Command, given, message, model, story } from "foldkit/story";

import {
  PushQuery,
  ShowSessionDialog,
} from "../src/client/event-page/command.js";
import { EnrollmentSlotMessage } from "../src/client/event-page/enrollment-slot.js";
import {
  ReadEnrollFooter,
  SubmitFooterChoice,
} from "../src/client/event-page/enrollment/command.js";
import { EventPageMessage } from "../src/client/event-page/message.js";
import { initEventPage } from "../src/client/event-page/model.js";
import type { EventPageModel } from "../src/client/event-page/model.js";
import { updateEventPage } from "../src/client/event-page/update.js";
import { enrollFooter, enrolledFooter, seats } from "./enrollment.fixtures.js";
import { eventPageFlags } from "./event-page.fixtures.js";

const signedIn = initEventPage(eventPageFlags({ signedIn: true }));

const enrollment = (inner: EnrollmentSlotMessage) =>
  EventPageMessage.GotEnrollmentMessage({ message: inner });

const opened = (start: EventPageModel) =>
  updateEventPage(
    start,
    EventPageMessage.ClickedSamePageLink({ hash: "", search: "?session=1" })
  ).model;

const loaded = updateEventPage(
  opened(signedIn),
  enrollment(
    EnrollmentSlotMessage.GotEnrollFooter({
      eventSlug: "spring-meet",
      footer: enrollFooter,
      seats: seats({ seatsLeft: 6 }),
      sessionId: 1,
      viewerId: 7,
    })
  )
).model;

describe("the session dialog's seat control", () => {
  it("a signed-in reader's dialog asks the server for their seat before it shows a way in", () => {
    story(
      updateEventPage,
      given(signedIn),
      message(
        EventPageMessage.ClickedSamePageLink({ hash: "", search: "?session=1" })
      ),
      model((next: EventPageModel) => {
        expect(next.enrollment._tag).toBe("Loading");
      }),
      Command.expectHas(ReadEnrollFooter({ sessionId: 1 })),
      Command.resolve(PushQuery, EventPageMessage.CompletedUrlUpdate()),
      Command.resolve(ShowSessionDialog, EventPageMessage.CompletedFocus()),
      Command.resolve(
        ReadEnrollFooter,
        EnrollmentSlotMessage.GotEnrollFooter({
          eventSlug: "spring-meet",
          footer: enrollFooter,
          seats: seats({}),
          sessionId: 1,
          viewerId: 7,
        })
      ),
      model((next: EventPageModel) => {
        expect(next.enrollment._tag).toBe("Seat");
      })
    );
  });

  it("an answer for a dialog the reader already closed and reopened elsewhere is ignored", () => {
    story(
      updateEventPage,
      given(loaded),
      message(
        enrollment(
          EnrollmentSlotMessage.GotEnrollFooter({
            eventSlug: "spring-meet",
            footer: enrolledFooter,
            seats: seats({ seatsLeft: 5 }),
            sessionId: 2,
            viewerId: 7,
          })
        )
      ),
      model((next: EventPageModel) => {
        expect(next.enrollment).toEqual(loaded.enrollment);
      })
    );
  });

  it("enrolling posts the viewer's own explicit choice and marks the control busy until it lands", () => {
    story(
      updateEventPage,
      given(loaded),
      message(
        enrollment(EnrollmentSlotMessage.ClickedFooterChoice({ sessionId: 1 }))
      ),
      model((next: EventPageModel) => {
        expect(
          Predicate.isTagged(next.enrollment, "Seat") &&
            next.enrollment.state.busy
        ).toBe(true);
      }),
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
      model((next: EventPageModel) => {
        const session = next.sessions.find((candidate) => candidate.id === 1);

        expect(session).toMatchObject({
          enrolledCount: 1,
          spotsLeft: 5,
          userEnrolled: true,
        });
      })
    );
  });
});
