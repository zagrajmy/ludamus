import { AcceptedStep } from "@zagrajmy/core/contracts";
import type { FieldAnswer } from "@zagrajmy/core/contracts";
import { Predicate } from "effect";
import type { Update } from "foldkit";

import { translator } from "../../ui/i18n.js";
import {
  DETAILS_FORM_ID,
  LoadHref,
  LoadWithFlash,
  PostStep,
  ReadFormSnapshot,
  STEP_FORM_ID,
  SubmitProposal,
} from "./command.js";
import { proposePath } from "./flags.js";
import {
  CopyIntent,
  ProposeMessage,
  SnapshotIntent,
  UndoIntent,
} from "./message.js";
import type { SubmitRefusal } from "./message.js";
import { categoryOf, initialDetailsDraft, stepsOf } from "./model.js";
import type { PostedForm, ProposeModel } from "./model.js";

type Return = Update.Return<ProposeModel, ProposeMessage>;

const LOGIN_URL = "/crowd/login-required/";

export const answersToPosted = (
  answers: Readonly<Record<string, FieldAnswer>>
): PostedForm =>
  Object.fromEntries(
    Object.entries(answers).map(([key, value]) => {
      if (Predicate.isString(value)) {
        return [key, [value]];
      }

      if (Predicate.isBoolean(value)) {
        return [key, value ? ["true"] : []];
      }

      return [key, value];
    })
  );

const nextStep = (model: ProposeModel, from: ProposeModel["step"]) => {
  const steps = stepsOf(model);
  const index = steps.indexOf(from);

  return steps[index + 1] ?? "review";
};

const previousStep = (model: ProposeModel, from: ProposeModel["step"]) => {
  const steps = stepsOf(model);
  const index = steps.indexOf(from);

  return index <= 0 ? from : (steps[index - 1] ?? from);
};

const withCategory = (model: ProposeModel, categoryId: number): ProposeModel =>
  model.categoryId === categoryId
    ? model
    : {
        ...model,
        acceptedDetails: null,
        categoryId,
        copiedSnapshot: null,
        descriptionHtml: "",
        details: null,
        detailsDraft: initialDetailsDraft(model.flags),
        formRevision: model.formRevision + 1,
        timeSlotIds: [],
      };

const accept = (options: {
  readonly model: ProposeModel;
  readonly accepted: AcceptedStep;
  readonly data: PostedForm;
  readonly descriptionHtml: string;
  readonly step: ProposeModel["step"];
}): ProposeModel => {
  const { accepted, data, model } = options;
  const settled = { ...model, errors: {}, isBusy: false, requestFailed: false };

  return AcceptedStep.match(accepted, {
    CategoryAccepted: (chosen) => {
      const picked = withCategory(settled, chosen.categoryId);

      return { ...picked, step: nextStep(picked, "category") };
    },
    DetailsAccepted: (shown) => {
      const { details } = shown;

      return {
        ...settled,
        acceptedDetails: { details, trackIds: shown.trackIds },
        descriptionHtml: options.descriptionHtml,
        details: data,
        detailsDraft: {
          ...answersToPosted(shown.formValues),
          description: [details.description],
          duration: details.duration === "" ? [] : [details.duration],
          facilitator_name: [details.facilitatorName],
          min_age: [String(details.minAge)],
          participants_limit:
            details.participantsLimit === 0
              ? []
              : [String(details.participantsLimit)],
          title: [details.title],
          track_pks: shown.trackIds.map(String),
        },
        formRevision: model.formRevision + 1,
        step: nextStep(settled, "details"),
      };
    },
    PersonalAccepted: (personal) => ({
      ...settled,
      acceptedPersonal: personal.personal,
      personal: data,
      personalDraft: answersToPosted(personal.formValues),
      step: nextStep(settled, "personal"),
    }),
    TimeSlotsAccepted: (slots) => ({
      ...settled,
      step: nextStep(settled, "timeslots"),
      timeSlotIds: slots.timeSlotIds,
    }),
  });
};

const snapshot = (options: {
  readonly model: ProposeModel;
  readonly data: PostedForm;
  readonly intent: SnapshotIntent;
}): ProposeModel => {
  const { data, intent, model } = options;

  const undo = (): ProposeModel => ({
    ...model,
    copiedSnapshot: null,
    detailsDraft: { ...data, ...model.copiedSnapshot },
    formRevision: model.formRevision + 1,
  });

  const copy = (sessionId: number): ProposeModel => {
    const reusable = model.flags.reusableSessions.find(
      (session) => session.sessionId === sessionId
    );

    const values = reusable?.formValues.find(
      (entry) => entry.categoryId === model.categoryId
    )?.values;

    if (values === undefined) {
      return { ...model, isCopyMenuOpen: false };
    }

    const copied = answersToPosted(values);

    const before: PostedForm = Object.fromEntries(
      Object.keys(copied).map((name) => [name, data[name] ?? []])
    );

    return {
      ...model,
      copiedSnapshot: model.copiedSnapshot ?? before,
      detailsDraft: { ...data, ...copied },
      formRevision: model.formRevision + 1,
      isCopyMenuOpen: false,
    };
  };

  return SnapshotIntent.match(intent, {
    Copy: (wanted) => copy(wanted.sessionId),
    Undo: undo,
  });
};

const refusalRedirect = (
  model: ProposeModel,
  reason: SubmitRefusal
): Return => {
  const { t } = translator(model.flags.locale);
  const propose = proposePath(model.flags.eventSlug);
  const idle = { ...model, isBusy: false };

  const flash = (href: string, text: string): Return => ({
    commands: [LoadWithFlash({ href, level: "error", text })],
    model: idle,
  });

  const failed: Return = { model: { ...idle, requestFailed: true } };

  const outcomes: Readonly<Record<SubmitRefusal, () => Return>> = {
    CategoryRequired: () =>
      flash(propose, t("Please select a category first.")),
    ClosedHiddenEvent: () =>
      flash(
        "/",
        t("Proposal submission is not currently active for this event.")
      ),
    ClosedOpenEvent: () =>
      flash(
        `/event/${encodeURIComponent(model.flags.eventSlug)}/`,
        t("Proposal submission is not currently active for this event.")
      ),
    Invalid: () => failed,
    NotFound: () => flash(propose, t("Invalid category.")),
    SignIn: () => ({
      commands: [LoadHref({ href: `${LOGIN_URL}?next=${propose}` })],
      model: idle,
    }),
    Throttled: () =>
      flash(propose, t("Please wait before submitting another proposal.")),
    Unknown: () => failed,
  };

  return outcomes[reason]();
};

export const updatePropose = (
  model: ProposeModel,
  message: ProposeMessage
): Return =>
  ProposeMessage.match<Return>(message, {
    AcceptedStep: ({ accepted, data, descriptionHtml, step }) => ({
      model: accept({ accepted, data, descriptionHtml, model, step }),
    }),
    ChangedDraftText: ({ name, value }) => ({
      model: {
        ...model,
        detailsDraft: { ...model.detailsDraft, [name]: [value] },
      },
    }),
    ClickedBack: ({ from }) => ({
      model: {
        ...model,
        copiedSnapshot: null,
        errors: {},
        formRevision: model.formRevision + 1,
        isCopyMenuOpen: false,
        requestFailed: false,
        step: previousStep(model, from),
      },
    }),
    ClickedCopyFrom: ({ sessionId }) => ({
      commands: [
        ReadFormSnapshot({
          formId: DETAILS_FORM_ID,
          intent: CopyIntent.make({ sessionId }),
        }),
      ],
      model,
    }),
    ClickedSubmitProposal: () => ({
      commands: [
        SubmitProposal({
          categoryId: categoryOf(model)?.id ?? null,
          details: model.details ?? {},
          eventSlug: model.flags.eventSlug,
          personal: model.personal,
          successText: translator(model.flags.locale).t(
            "Session proposal '{}' submitted successfully!"
          ),
          timeSlotIds: model.timeSlotIds,
        }),
      ],
      model: { ...model, isBusy: true, requestFailed: false },
    }),
    ClickedUndoCopy: () => ({
      commands: [
        ReadFormSnapshot({
          formId: DETAILS_FORM_ID,
          intent: UndoIntent.make({}),
        }),
      ],
      model,
    }),
    CompletedNavigation: () => ({ model }),
    EnhancedWriteIn: ({ name }) => ({
      model: model.enhancedWriteIns.includes(name)
        ? model
        : { ...model, enhancedWriteIns: [...model.enhancedWriteIns, name] },
    }),
    FailedEnhanceWriteIn: () => ({ model }),
    FailedRequest: () => ({
      model: { ...model, isBusy: false, requestFailed: true },
    }),
    FailedSubmitProposal: ({ errors, reason, step }) =>
      reason === "Invalid" && step !== null
        ? {
            model: {
              ...model,
              errors,
              isBusy: false,
              step: stepsOf(model).includes(step) ? step : model.step,
            },
          }
        : refusalRedirect(model, reason),
    ReadForm: ({ data, intent }) => ({
      model: snapshot({ data, intent, model }),
    }),
    RejectedStep: ({ errors }) => ({
      model: { ...model, errors, isBusy: false },
    }),
    SubmittedStep: ({ step }) => ({
      commands: [
        PostStep({
          categoryId: model.categoryId,
          eventSlug: model.flags.eventSlug,
          formId: step === "details" ? DETAILS_FORM_ID : STEP_FORM_ID,
          step,
        }),
      ],
      model: { ...model, isBusy: true, requestFailed: false },
    }),
    ToggledCopyMenu: ({ isOpen }) => ({
      model: { ...model, isCopyMenuOpen: isOpen },
    }),
  });
