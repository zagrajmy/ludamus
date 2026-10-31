import {
  CurrentSphere,
  CurrentViewer,
  SphereId,
  UserId,
  checkProposalStep,
  readProposalForm,
} from "@zagrajmy/core";
import type {
  CheckableStep,
  FieldAnswer,
  FieldRequirement,
  ProposeWizard,
  ProposeWizardCategory,
} from "@zagrajmy/core/contracts";
import { durationChoices } from "@zagrajmy/core/proposal/durations";
import {
  controlRequired,
  lengthLimit,
  offersCustomInput,
  sortedOptions,
} from "@zagrajmy/core/proposal/fields";
import { formatDate } from "@zagrajmy/i18n";
import { Data, DateTime, Effect, Option, Predicate, Schema } from "effect";

import {
  PROPOSE_CATEGORY_HEADER,
  StepAccepted,
  StepRedirected,
  StepRejected,
  StepResponse,
  proposePath,
} from "../../client/propose/flags.js";
import type {
  CategoryView,
  FieldView,
  ProposeFlags,
  ProposeIcon,
  SlotDay,
} from "../../client/propose/flags.js";
import type { IconData } from "../../ui/icon.js";
import * as icons from "../../ui/icons.js";
import { flashCookieHeader } from "../flash.js";
import type { FlashNote } from "../flash.js";
import { renderSafeMarkdown } from "../markdown.js";
import type { RequestContext } from "../request-context.js";

const LOGIN_URL = "/crowd/login-required/";

const PROPOSE_PATH = /^\/event\/(?<slug>[^/]+)\/session\/propose\/$/u;

const STEP_PATH =
  /^\/event\/(?<slug>[^/]+)\/session\/propose\/parts\/(?<step>personal|category|timeslots|details)$/u;

const iconIndex: Readonly<Record<string, IconData>> = icons;

const camel = (name: string) =>
  name
    .split("-")
    .map((part, index) =>
      index === 0 ? part : `${part.charAt(0).toUpperCase()}${part.slice(1)}`
    )
    .join("");

const iconNamed = (name: string): ProposeIcon | null =>
  name === "" ? null : (iconIndex[`${camel(name)}Mini`] ?? null);

export const proposeSlugOf = (pathname: string): Option.Option<string> =>
  Option.map(
    Option.fromNullishOr(PROPOSE_PATH.exec(pathname)?.groups?.slug),
    decodeURIComponent
  );

export const isProposeStepPath = (pathname: string) => STEP_PATH.test(pathname);

const provideRequest =
  (context: RequestContext) =>
  <A, E, R>(effect: Effect.Effect<A, E, R>) =>
    effect.pipe(
      Effect.provideService(CurrentSphere, {
        domain: context.sphere.domain,
        id: SphereId.make(context.sphere.id),
        name: context.sphere.name,
      }),
      Effect.provideService(
        CurrentViewer,
        context.viewer.pipe(
          Option.map((viewer) => ({
            id: UserId.make(viewer.id),
            isSuperuser: viewer.isSuperuser === 1,
          }))
        )
      )
    );

const fieldView = (requirement: FieldRequirement): FieldView => {
  const { field } = requirement;

  return {
    controlRequired: controlRequired(requirement),
    fieldType: field.fieldType,
    helpHtml: renderSafeMarkdown(field.helpText),
    icon: iconNamed(field.icon),
    isMultiple: field.isMultiple,
    isPublic: field.isPublic,
    isRequired: requirement.isRequired,
    maxLength: lengthLimit(field),
    name: field.name,
    offersCustom: offersCustomInput(field),
    options: sortedOptions(field).map((option) => ({
      label: option.label,
      value: option.value,
    })),
    question: field.question,
    slug: field.slug,
  };
};

const local = (context: RequestContext, value: DateTime.Utc, format: string) =>
  formatDate({
    format,
    locale: context.translator.locale,
    value: DateTime.formatIso(value),
  });

const slotDays = (
  context: RequestContext,
  category: ProposeWizardCategory
): readonly SlotDay[] => {
  const days = new Map<string, SlotDay>();

  for (const slot of category.timeSlots) {
    const key = local(context, slot.startTime, "Y-m-d");

    const day = days.get(key) ?? {
      label: local(context, slot.startTime, "l, d M"),
      slots: [],
    };

    days.set(key, {
      ...day,
      slots: [
        ...day.slots,
        {
          id: slot.id,
          isRequired: slot.isRequired,
          label: `${local(context, slot.startTime, "H:i")}–${local(context, slot.endTime, "H:i")}`,
        },
      ],
    });
  }

  return [...days.entries()]
    .toSorted(([a], [b]) => (a < b ? -1 : 1))
    .map(([, day]) => day);
};

const categoryView = (
  context: RequestContext,
  category: ProposeWizardCategory
): CategoryView => ({
  description: category.description,
  durations: durationChoices(category.durations).map(([value, label]) => ({
    label,
    value,
  })),
  id: category.id,
  maxParticipantsLimit: category.maxParticipantsLimit,
  minParticipantsLimit: category.minParticipantsLimit,
  name: category.name,
  sessionFields: category.sessionFields.map(fieldView),
  slotDays: slotDays(context, category),
  steps: category.steps,
});

const posted = (answers: Readonly<Record<string, FieldAnswer>>) =>
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

const flagsOf = (
  context: RequestContext,
  wizard: ProposeWizard
): ProposeFlags => {
  const viewer = Option.getOrUndefined(context.viewer);

  const avatarUrl =
    viewer === undefined || viewer.useGravatar === 1 || viewer.avatarUrl === ""
      ? Option.none<string>()
      : Option.some(viewer.avatarUrl);

  return {
    account: {
      answers: wizard.account.personalAnswers,
      email: wizard.account.email,
      name: wizard.account.name,
      person: { avatarUrl, name: wizard.account.name },
      signedIn: wizard.account.signedIn,
    },
    categories: wizard.categories.map((category) =>
      categoryView(context, category)
    ),
    descriptionHtml: renderSafeMarkdown(wizard.proposalDescription),
    eventName: wizard.event.name,
    eventSlug: wizard.event.slug,
    locale: context.translator.locale,
    loginUrl: `${LOGIN_URL}?next=${proposePath(wizard.event.slug)}`,
    personalFields: wizard.personalFields.map(fieldView),
    personalFormValues: posted(wizard.personalFormValues),
    reusableSessions: wizard.reusableSessions,
    tracks: wizard.tracks.map((track) => ({ id: track.id, name: track.name })),
    uncategorizedSteps: wizard.uncategorizedSteps,
  };
};

export type ProposeRouted = Data.TaggedEnum<{
  Flags: { readonly flags: ProposeFlags };
  Redirect: {
    readonly location: string;
    readonly flashes: readonly FlashNote[];
  };
}>;

export const ProposeRouted = Data.taggedEnum<ProposeRouted>();

const errorFlash = (error: string | undefined): readonly FlashNote[] =>
  error === undefined ? [] : [{ level: "error", text: error }];

const redirect = (location: string, error?: string): ProposeRouted =>
  ProposeRouted.Redirect({ flashes: errorFlash(error), location });

export const loadPropose = Effect.fn("Propose.load")(function* loadPropose(
  context: RequestContext,
  eventSlug: string
) {
  const { t } = context.translator;

  return yield* readProposalForm.handler({ eventSlug }).pipe(
    provideRequest(context),
    Effect.map((wizard) =>
      ProposeRouted.Flags({ flags: flagsOf(context, wizard) })
    ),
    Effect.catchTags({
      AnonymousProposalsDisabled: () =>
        Effect.succeed(redirect(`${LOGIN_URL}?next=${context.url.pathname}`)),
      NotFound: () => Effect.succeed(redirect("/", t("Event not found."))),
      ProposalsClosed: (closed) =>
        Effect.succeed(
          redirect(
            closed.eventIsOpen
              ? `/event/${encodeURIComponent(eventSlug)}/`
              : "/",
            t("Proposal submission is not currently active for this event.")
          )
        ),
    }),
    Effect.orDie
  );
});

const readPostedForm = Effect.fn("Propose.readPostedForm")(
  function* readPostedForm(request: Request) {
    const body = yield* Effect.tryPromise(
      async () => await request.formData()
    ).pipe(Effect.orElseSucceed(() => new FormData()));

    const data: Record<string, string[]> = {};

    for (const [name, value] of body) {
      if (Predicate.isString(value)) {
        data[name] = [...(data[name] ?? []), value];
      }
    }

    return data;
  }
);

const encodeResponse = Schema.encodeEffect(StepResponse);

const json = (
  options: Readonly<{
    body: unknown;
    status: number;
    flashes?: readonly FlashNote[];
  }>
) => {
  const headers = new Headers({ "cache-control": "no-store" });

  if (options.flashes !== undefined && options.flashes.length > 0) {
    headers.append("set-cookie", flashCookieHeader(options.flashes));
  }

  return Response.json(options.body, { headers, status: options.status });
};

const redirected = (location: string, error?: string) =>
  encodeResponse(StepRedirected.make({ location })).pipe(
    Effect.map((body) =>
      json({ body, flashes: errorFlash(error), status: 200 })
    )
  );

const categoryHeader = (request: Request): number | null => {
  const raw = request.headers.get(PROPOSE_CATEGORY_HEADER) ?? "";

  return /^[0-9]+$/u.test(raw) ? Number(raw) : null;
};

export const respondToProposeStep = Effect.fn("Propose.respondToStep")(
  function* respondToProposeStep(context: RequestContext) {
    const match = STEP_PATH.exec(context.url.pathname);
    const eventSlug = decodeURIComponent(match?.groups?.slug ?? "");

    const step: CheckableStep = Schema.decodeUnknownSync(
      Schema.Literals(["personal", "category", "timeslots", "details"])
    )(match?.groups?.step ?? "details");

    const { t } = context.translator;
    const propose = proposePath(eventSlug);
    const data = yield* readPostedForm(context.request);

    return yield* checkProposalStep
      .handler({
        categoryId: categoryHeader(context.request),
        data,
        eventSlug,
        step,
      })
      .pipe(
        provideRequest(context),
        Effect.flatMap((accepted) =>
          encodeResponse(
            StepAccepted.make({
              descriptionHtml: Predicate.isTagged(accepted, "DetailsAccepted")
                ? renderSafeMarkdown(accepted.details.description)
                : "",
              step: accepted,
            })
          )
        ),
        Effect.map((body) => json({ body, status: 200 })),
        Effect.catchTags({
          AnonymousProposalsDisabled: () =>
            redirected(`${LOGIN_URL}?next=${propose}`),
          CategoryRequired: () =>
            redirected(propose, t("Please select a category first.")),
          NotFound: (missing) =>
            missing.entity === "ProposalCategory"
              ? redirected(propose, t("Invalid category."))
              : redirected("/", t("Event not found.")),
          ProposalInvalid: (invalid) =>
            encodeResponse(StepRejected.make({ errors: invalid.errors })).pipe(
              Effect.map((body) => json({ body, status: 422 }))
            ),
          ProposalsClosed: (closed) =>
            redirected(
              closed.eventIsOpen
                ? `/event/${encodeURIComponent(eventSlug)}/`
                : "/",
              t("Proposal submission is not currently active for this event.")
            ),
        }),
        Effect.orDie
      );
  }
);
