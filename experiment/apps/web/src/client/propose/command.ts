import { Effect, Predicate, Schema } from "effect";
import { Command, Mount } from "foldkit";
import { load } from "foldkit/navigation";

import { Backend } from "../rpc.js";
import { PROPOSE_CATEGORY_HEADER, StepResponse, stepPath } from "./flags.js";
import { ProposeMessage, SnapshotIntent } from "./message.js";
import type { SubmitRefusal } from "./message.js";
import { PostedForm } from "./model.js";

export const DETAILS_FORM_ID = "propose-details-form";

export const STEP_FORM_ID = "propose-step-form";

const FLASH_COOKIE = "flash";

const readForm = (formId: string): PostedForm => {
  const form = document.querySelector(`#${formId}`);

  if (!(form instanceof HTMLFormElement)) {
    return {};
  }

  const posted: Record<string, string[]> = {};

  for (const [name, value] of new FormData(form)) {
    if (Predicate.isString(value)) {
      posted[name] = [...(posted[name] ?? []), value];
    }
  }

  return posted;
};

const toFormData = (posted: PostedForm) => {
  const body = new FormData();

  for (const [name, values] of Object.entries(posted)) {
    for (const value of values) {
      body.append(name, value);
    }
  }

  return body;
};

const decodeResponse = Schema.decodeUnknownEffect(StepResponse);

export const PostStep = Command.define("PostStep", {
  args: {
    categoryId: Schema.NullOr(Schema.Int),
    eventSlug: Schema.String,
    formId: Schema.String,
    step: Schema.Literals(["personal", "category", "timeslots", "details"]),
  },
  execute: ({ categoryId, eventSlug, formId, step }) =>
    Effect.gen(function* postStep() {
      const data = readForm(formId);

      const response = yield* Effect.tryPromise(
        async () =>
          await fetch(stepPath({ eventSlug, step }), {
            body: toFormData(data),
            credentials: "same-origin",
            headers:
              categoryId === null
                ? {}
                : { [PROPOSE_CATEGORY_HEADER]: String(categoryId) },
            method: "POST",
          })
      );

      const payload = yield* Effect.tryPromise(async () => {
        const body: unknown = await response.json();

        return body;
      });

      const outcome = yield* decodeResponse(payload);

      return yield* StepResponse.match(outcome, {
        Accepted: (accepted) =>
          Effect.succeed(
            ProposeMessage.AcceptedStep({
              accepted: accepted.step,
              data,
              descriptionHtml: accepted.descriptionHtml,
              step,
            })
          ),
        Redirected: (redirected) =>
          load(redirected.location).pipe(
            Effect.as(ProposeMessage.CompletedNavigation())
          ),
        Rejected: (rejected) =>
          Effect.succeed(
            ProposeMessage.RejectedStep({ errors: rejected.errors })
          ),
      });
    }).pipe(
      Effect.catchCause(() => Effect.succeed(ProposeMessage.FailedRequest()))
    ),
  messages: [
    ProposeMessage.AcceptedStep,
    ProposeMessage.RejectedStep,
    ProposeMessage.CompletedNavigation,
    ProposeMessage.FailedRequest,
  ],
});

export const ReadFormSnapshot = Command.define("ReadFormSnapshot", {
  args: { formId: Schema.String, intent: SnapshotIntent },
  execute: ({ formId, intent }) =>
    Effect.sync(() =>
      ProposeMessage.ReadForm({ data: readForm(formId), intent })
    ),
  messages: [ProposeMessage.ReadForm],
});

const setFlashCookie = (note: Readonly<{ level: string; text: string }>) =>
  Effect.sync(() => {
    // oxlint-disable-next-line unicorn/no-document-cookie -- server/flash.ts reads this cookie on the next page load; the Cookie Store API is missing in the Firefox ESR the suite runs.
    document.cookie = `${FLASH_COOKIE}=${encodeURIComponent(JSON.stringify([note]))}; Path=/; SameSite=Lax`;
  });

export const LoadWithFlash = Command.define("LoadWithFlash", {
  args: {
    href: Schema.String,
    level: Schema.Literals(["error", "success"]),
    text: Schema.String,
  },
  execute: ({ href, level, text }) =>
    setFlashCookie({ level, text }).pipe(
      Effect.andThen(load(href)),
      Effect.as(ProposeMessage.CompletedNavigation())
    ),
  messages: [ProposeMessage.CompletedNavigation],
});

export const LoadHref = Command.define("LoadHref", {
  args: { href: Schema.String },
  execute: ({ href }) =>
    load(href).pipe(Effect.as(ProposeMessage.CompletedNavigation())),
  messages: [ProposeMessage.CompletedNavigation],
});

const PostedFormSchema = PostedForm;

const refused = (reason: SubmitRefusal) =>
  Effect.succeed(
    ProposeMessage.FailedSubmitProposal({ errors: {}, reason, step: null })
  );

export const SubmitProposal = Command.define("SubmitProposal", {
  args: {
    categoryId: Schema.NullOr(Schema.Int),
    details: PostedFormSchema,
    eventSlug: Schema.String,
    personal: Schema.NullOr(PostedFormSchema),
    successText: Schema.String,
    timeSlotIds: Schema.Array(Schema.Int),
  },
  execute: (input) =>
    Effect.gen(function* submitProposal() {
      const backend = yield* Backend;

      const submitted = yield* backend.submitProposal({
        categoryId: input.categoryId,
        details: input.details,
        eventSlug: input.eventSlug,
        personal: input.personal,
        timeSlotIds: input.timeSlotIds,
      });

      yield* setFlashCookie({
        level: "success",
        text: input.successText.replace("{}", submitted.title),
      });

      return yield* load(`/event/${encodeURIComponent(input.eventSlug)}/`).pipe(
        Effect.as(ProposeMessage.CompletedNavigation())
      );
    }).pipe(
      Effect.provide(Backend.layer),
      Effect.catchTags({
        AnonymousProposalsDisabled: () => refused("SignIn"),
        CategoryRequired: () => refused("CategoryRequired"),
        NotFound: () => refused("NotFound"),
        ProposalInvalid: (invalid) =>
          Effect.succeed(
            ProposeMessage.FailedSubmitProposal({
              errors: invalid.errors,
              reason: "Invalid",
              step: invalid.step,
            })
          ),
        ProposalsClosed: (closed) =>
          refused(closed.eventIsOpen ? "ClosedOpenEvent" : "ClosedHiddenEvent"),
        SubmissionThrottled: () => refused("Throttled"),
      }),
      Effect.catchCause((cause) =>
        Effect.logWarning("submitProposal failed", cause).pipe(
          Effect.andThen(refused("Unknown"))
        )
      )
    ),
  messages: [
    ProposeMessage.CompletedNavigation,
    ProposeMessage.FailedSubmitProposal,
  ],
});

export const EnhanceWriteIn = Mount.define("EnhanceWriteIn", {
  args: { name: Schema.String },
  execute: ({ element, name }) =>
    Effect.tryPromise(async () => await import("./write-in-chips.js")).pipe(
      Effect.flatMap((module) =>
        Effect.sync(() => {
          const input = element.querySelector("input[data-write-in-chips]");

          if (input instanceof HTMLInputElement) {
            module.enhanceWriteIn(input);
          }
        })
      ),
      Effect.as(ProposeMessage.EnhancedWriteIn({ name })),
      Effect.orElseSucceed(() => ProposeMessage.FailedEnhanceWriteIn({ name }))
    ),
  messages: [
    ProposeMessage.EnhancedWriteIn,
    ProposeMessage.FailedEnhanceWriteIn,
  ],
});
