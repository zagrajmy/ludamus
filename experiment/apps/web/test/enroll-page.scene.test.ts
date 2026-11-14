import { describe, it } from "@effect/vitest";
import type { EnrollmentForm, EnrollmentRow } from "@zagrajmy/core/contracts";
import { Option } from "effect";
import {
  click,
  Command,
  expect,
  given,
  role,
  scene,
  selector,
} from "foldkit/scene";

import { SubmitEnrollPage } from "../src/client/enroll-page/command.js";
import { EnrollPageMessage } from "../src/client/enroll-page/message.js";
import { PageFlags } from "../src/client/model.js";
import { update } from "../src/client/update.js";
import { view } from "../src/features/app.js";
import { modelFor, shellFlags } from "./fixtures.js";

const config = { update, view };

const row = (
  overrides: Partial<EnrollmentRow> & Pick<EnrollmentRow, "userId">
): EnrollmentRow => ({
  badge: { label: "Available", variant: "muted" },
  boxChecked: false,
  checked: false,
  disabled: false,
  isViewer: false,
  needsApproval: false,
  occupiesSeat: false,
  person: {
    avatarUrl: "",
    email: "",
    name: `Person ${overrides.userId}`,
    useGravatar: false,
  },
  reason: "",
  ...overrides,
});

const form = (overrides: Partial<EnrollmentForm>): EnrollmentForm => ({
  agenda: null,
  ctaLabel: "Confirm",
  description: "",
  eventCoverImage: "",
  eventName: "Spring Meet",
  eventSlug: "spring-meet",
  facilitatorName: "Alex Morgan",
  guests: null,
  minAge: 0,
  partyChoices: [],
  presenter: null,
  rows: [],
  seats: {
    effectiveParticipantsLimit: 1,
    eligibleWindowIds: [1],
    enrolledCount: 1,
    isFull: true,
    seatsLeft: 0,
    waitingCount: 1,
  },
  selectedPartyId: null,
  sessionCoverImage: "",
  sessionId: 1,
  shadowbanWarnings: [],
  title: "Waitlist Promotion Demo",
  ...overrides,
});

const page = (enrollment: EnrollmentForm) =>
  modelFor({
    page: PageFlags.EnrollPage({
      flags: {
        avatars: [],
        coverUrl: Option.none(),
        descriptionHtml: "",
        eventUrl: "/event/spring-meet/",
        form: enrollment,
        locale: "en",
        partiesUrl: "/crowd/profile/parties/",
        partyParam: null,
        presenterAvatar: Option.none(),
        shadowbanDates: [],
        whenLabel: "",
      },
    }),
    shell: shellFlags(),
  });

const seated = row({
  badge: { label: "Already enrolled", variant: "success" },
  boxChecked: true,
  checked: true,
  isViewer: true,
  occupiesSeat: true,
  person: { avatarUrl: "", email: "", name: "Ola", useGravatar: false },
  userId: 7,
});

const include = role("checkbox", { name: /Include/u });

describe("the enroll page", () => {
  it("unticking a viewer who holds the seat says they will leave and still reads Confirm", () => {
    scene(
      config,
      given(page(form({ rows: [seated] }))),
      expect(include).toBeChecked(),
      click(include),
      expect(selector("[data-seat-hint]")).toHaveText("Will leave the session"),
      expect(role("button", { name: "Confirm" })).toExist()
    );
  });

  it("confirming posts the desired state, leaving the unticked viewer out", () => {
    scene(
      config,
      given(page(form({ rows: [seated] }))),
      click(include),
      click(role("button", { name: "Confirm" })),
      Command.expectExact(
        SubmitEnrollPage({
          eventSlug: "spring-meet",
          input: {
            choices: [{ userId: 7, value: "" }],
            guests: null,
            mode: "desired",
            party: null,
            sessionId: 1,
          },
          locale: "en",
        })
      ),
      Command.resolve(SubmitEnrollPage, EnrollPageMessage.LeftEnrollPage())
    );
  });

  it("a newcomer on a full session is told they join the waiting list", () => {
    scene(
      config,
      given(
        page(
          form({ rows: [row({ boxChecked: true, isViewer: true, userId: 7 })] })
        )
      ),
      expect(selector("[data-seat-hint]")).toHaveText("Joins the waiting list"),
      expect(role("button", { name: "Join the waiting list" })).toExist()
    );
  });
});
