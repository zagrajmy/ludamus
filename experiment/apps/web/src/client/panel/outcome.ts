import type { Translator } from "../../ui/i18n.js";
import { PanelAction } from "./action.js";
import { BROKEN_SAVE, PanelFailure, refusalText } from "./failure.js";
import type { FlashNote } from "./failure.js";
import type { SessionStatusValue } from "./schemas.js";

export type Outcome = Readonly<{ href: string; notes: readonly FlashNote[] }>;

const tracksHref = (eventSlug: string) => `/panel/event/${eventSlug}/tracks/`;

const facilitatorsHref = (eventSlug: string) =>
  `/panel/event/${eventSlug}/facilitators/`;

const proposalsHref = (eventSlug: string) =>
  `/panel/event/${eventSlug}/proposals/`;

const statusMessages: Readonly<Record<SessionStatusValue, string>> = {
  accepted: "Proposal accepted.",
  on_hold: "Proposal put on hold.",
  pending: "Proposal moved back to pending.",
  rejected: "Proposal rejected.",
};

const success = (text: string): readonly FlashNote[] => [
  { level: "success", text },
];

const failed = (text: string): readonly FlashNote[] => [
  { level: "error", text },
];

export const successOutcome = (
  action: PanelAction,
  translator: Translator
): Outcome =>
  PanelAction.match<Outcome>(action, {
    ChangeProposalStatus: ({ next, status }) => ({
      href: next,
      notes: success(translator.t(statusMessages[status])),
    }),
    DeleteFacilitator: ({ next }) => ({
      href: next,
      notes: success(translator.t("Facilitator deleted.")),
    }),
    DeleteProposal: ({ eventSlug }) => ({
      href: proposalsHref(eventSlug),
      notes: success(translator.t("Proposal deleted.")),
    }),
    DeleteTrack: ({ eventSlug }) => ({
      href: tracksHref(eventSlug),
      notes: success(translator.t("Track deleted.")),
    }),
    RestoreFacilitator: ({ next }) => ({
      href: next,
      notes: success(translator.t("Facilitator restored.")),
    }),
    RestoreProposal: ({ eventSlug }) => ({
      href: proposalsHref(eventSlug),
      notes: success(translator.t("Proposal restored.")),
    }),
  });

const missingOutcome = (action: PanelAction, translator: Translator): Outcome =>
  PanelAction.match<Outcome>(action, {
    ChangeProposalStatus: ({ eventSlug }) => ({
      href: proposalsHref(eventSlug),
      notes: failed(translator.t("Proposal not found.")),
    }),
    DeleteFacilitator: ({ eventSlug }) => ({
      href: facilitatorsHref(eventSlug),
      notes: failed(translator.t("Facilitator not found.")),
    }),
    DeleteProposal: ({ eventSlug }) => ({
      href: proposalsHref(eventSlug),
      notes: failed(translator.t("Proposal not found.")),
    }),
    DeleteTrack: ({ eventSlug }) => ({
      href: tracksHref(eventSlug),
      notes: failed(translator.t("Track not found.")),
    }),
    RestoreFacilitator: ({ eventSlug }) => ({
      href: facilitatorsHref(eventSlug),
      notes: failed(translator.t("Facilitator not found.")),
    }),
    RestoreProposal: ({ eventSlug }) => ({
      href: proposalsHref(eventSlug),
      notes: failed(translator.t("Proposal not found.")),
    }),
  });

const backOf = (action: PanelAction) =>
  PanelAction.match<string>(action, {
    ChangeProposalStatus: ({ next }) => next,
    DeleteFacilitator: ({ next }) => next,
    DeleteProposal: ({ eventSlug }) => proposalsHref(eventSlug),
    DeleteTrack: ({ eventSlug }) => tracksHref(eventSlug),
    RestoreFacilitator: ({ next }) => next,
    RestoreProposal: ({ eventSlug }) => proposalsHref(eventSlug),
  });

const sessionsConflict = (
  counts: Readonly<{ deleted: number; live: number }>,
  translator: Translator
) => {
  const total = counts.live + counts.deleted;

  return counts.deleted === 0
    ? translator.n(
        "This facilitator is named on {count} session. Remove them from it before deleting.",
        "This facilitator is named on {count} sessions. Remove them from those before deleting.",
        total,
        { count: total }
      )
    : translator.n(
        "This facilitator is named on {count} session, {deleted} of them deleted. Remove them from all of these first — the deleted ones are in the {bin_link}.",
        "This facilitator is named on {count} sessions, {deleted} of them deleted. Remove them from all of these first — the deleted ones are in the {bin_link}.",
        total,
        {
          bin_link: translator.t("proposal bin"),
          count: total,
          deleted: counts.deleted,
        }
      );
};

export const failureOutcome = (
  action: PanelAction,
  failure: PanelFailure,
  translator: Translator
): Outcome =>
  PanelFailure.match<Outcome>(failure, {
    Broken: () => ({
      href: backOf(action),
      notes: failed(translator.t(BROKEN_SAVE)),
    }),
    Conflict: (counts) => ({
      href: backOf(action),
      notes: failed(sessionsConflict(counts, translator)),
    }),
    Invalid: ({ errors }) => ({
      href: backOf(action),
      notes: errors.map((error) => ({
        level: "error",
        text: translator.t(error.msgid, error.vars),
      })),
    }),
    Missing: () => missingOutcome(action, translator),
    Refused: ({ reason }) => ({
      href: backOf(action),
      notes: failed(refusalText(reason, translator)),
    }),
    Scheduled: () => ({
      href: backOf(action),
      notes: failed(
        translator.t(
          "This session is scheduled and can only be accepted. Remove it from the timetable to change its status."
        )
      ),
    }),
  });
