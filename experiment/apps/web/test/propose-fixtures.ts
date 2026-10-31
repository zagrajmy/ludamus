import { ProposalCategoryId, SessionId } from "@zagrajmy/core/contracts";
import { Option } from "effect";

import { PageFlags } from "../src/client/model.js";
import type { FieldView, ProposeFlags } from "../src/client/propose/flags.js";
import { modelFor, shellFlags } from "./fixtures.js";

export const triggersField: FieldView = {
  controlRequired: false,
  fieldType: "select",
  helpHtml: "",
  icon: null,
  isMultiple: true,
  isPublic: true,
  isRequired: false,
  maxLength: 50,
  name: "Trigger warnings",
  offersCustom: true,
  options: [
    { label: "Violence", value: "violence" },
    { label: "Horror", value: "horror" },
  ],
  question: "Any trigger warnings?",
  slug: "triggers",
};

export const systemField: FieldView = {
  controlRequired: false,
  fieldType: "text",
  helpHtml: "<p>Any edition is fine.</p>",
  icon: null,
  isMultiple: false,
  isPublic: false,
  isRequired: true,
  maxLength: 40,
  name: "System",
  offersCustom: true,
  options: [],
  question: "Which system?",
  slug: "system",
};

export const proposeFlags = (
  overrides: Partial<ProposeFlags> = {}
): ProposeFlags => ({
  account: {
    answers: {},
    email: "",
    name: "",
    person: { avatarUrl: Option.none(), name: "" },
    signedIn: false,
  },
  categories: [
    {
      description: "",
      durations: [{ label: "1h", value: "PT1H" }],
      id: 8,
      maxParticipantsLimit: 6,
      minParticipantsLimit: 1,
      name: "Open Mic",
      sessionFields: [triggersField, systemField],
      slotDays: [],
      steps: ["personal", "details", "review"],
    },
  ],
  descriptionHtml: "",
  eventName: "Open Mic Proposals",
  eventSlug: "open-mic",
  locale: "en",
  loginUrl: "/crowd/login-required/?next=/event/open-mic/session/propose/",
  personalFields: [],
  personalFormValues: {},
  reusableSessions: [
    {
      eventName: "Mothership Nights I",
      formValues: [
        {
          categoryId: ProposalCategoryId.make(8),
          values: {
            description: "Prospero's station went quiet.",
            session_triggers: ["horror"],
            session_triggers_custom: "krew",
            title: "Play Mothership",
          },
        },
      ],
      sessionId: SessionId.make(5),
      title: "Play Mothership",
    },
  ],
  tracks: [],
  uncategorizedSteps: ["personal", "details", "review"],
  ...overrides,
});

export const proposeModel = (overrides: Partial<ProposeFlags> = {}) =>
  modelFor({
    page: PageFlags.Propose({ flags: proposeFlags(overrides) }),
    shell: shellFlags(),
  });
