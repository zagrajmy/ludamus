import type { FieldAnswer, ProposeStep } from "@zagrajmy/core/contracts";
import { Predicate } from "effect";
import type { Html } from "foldkit/html";
import { defineView } from "foldkit/submodel";

import { DETAILS_FORM_ID, STEP_FORM_ID } from "../../client/propose/command.js";
import type { CategoryView, FieldView } from "../../client/propose/flags.js";
import { ProposeMessage } from "../../client/propose/message.js";
import { categoryOf, stepsOf } from "../../client/propose/model.js";
import type { ProposeModel } from "../../client/propose/model.js";
import { avatar } from "../../ui/avatar.js";
import { cx } from "../../ui/cx.js";
import type { Translator } from "../../ui/i18n.js";
import { icon } from "../../ui/icon.js";
import type { IconData } from "../../ui/icon.js";
import {
  checkMini,
  chevronDownMini,
  clockMini,
  documentDuplicateMini,
  lockClosedMini,
  usersMini,
} from "../../ui/icons.js";
import { actionDropdown } from "../../ui/menu.js";
import { pageContextOf } from "../page-context.js";
import type { PageContext, PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";
import {
  choiceList,
  dynamicField,
  errorsOf,
  inplaceLook,
  lastValue,
  optional,
} from "./fields.js";
import type { H } from "./fields.js";

const eyeMini: IconData = {
  paths: [
    { d: "M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" },
    {
      clipRule: "evenodd",
      d: "M.664 10.59a1.651 1.651 0 010-1.186A10.004 10.004 0 0110 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41zM14 10a4 4 0 11-8 0 4 4 0 018 0z",
      fillRule: "evenodd",
    },
  ],
  variant: "mini",
};

export const proposeTitle = (context: PageContext): PageTitle => ({
  name: context.translator.t("Propose Session"),
  sphereSuffix: true,
});

type Ctx = Readonly<{
  model: ProposeModel;
  translator: Translator;
  steps: readonly ProposeStep[];
  category: CategoryView | null;
}>;

const stepLabel = (translator: Translator, step: ProposeStep): string =>
  ({
    category: translator.t("Category"),
    details: translator.tc("wizard step", "Session"),
    personal: translator.t("Your info"),
    review: translator.t("Review"),
    timeslots: translator.t("Time slots"),
  })[step];

const stepper = (ctx: Ctx, h: H) => {
  const current = ctx.steps.indexOf(ctx.model.step);

  return h.nav(
    [h.AriaLabel(ctx.translator.t("Proposal progress")), h.Class("mb-6")],
    [
      h.ol(
        [
          h.Class(
            "grid w-fit max-w-full mx-auto grid-flow-col auto-cols-[minmax(0,1fr)]"
          ),
        ],
        ctx.steps.map((step, index) => {
          const isDone = index < current;
          const isCurrent = index === current;

          return h.li(
            [
              h.Key(step),
              h.Class("flex flex-col items-center relative px-2"),
              ...optional(isCurrent, h.AriaCurrent("step")),
            ],
            [
              index === 0
                ? h.empty
                : h.span(
                    [
                      h.AriaHidden(true),
                      h.Class(
                        cx(
                          "absolute top-4 h-0.5 -translate-y-1/2",
                          isDone || isCurrent ? "bg-primary" : "bg-border"
                        )
                      ),
                      h.Style({
                        left: "calc(-50% + 1.25rem)",
                        right: "calc(50% + 1.25rem)",
                      }),
                    ],
                    []
                  ),
              h.span(
                [
                  h.Class(
                    cx(
                      "relative z-10 flex items-center justify-center w-8 h-8 rounded-full border-2 text-xs font-semibold transition-colors",
                      isDone && "bg-primary border-primary text-white",
                      isCurrent &&
                        "bg-primary border-primary text-white ring-4 ring-primary/20",
                      !isDone &&
                        !isCurrent &&
                        "bg-[--color-bg-secondary] border-border text-foreground-muted"
                    )
                  ),
                ],
                [isDone ? "✓" : String(index + 1)]
              ),
              h.span(
                [
                  h.Class(
                    cx(
                      "mt-2 text-center text-xs sm:text-sm leading-tight",
                      isCurrent && "text-foreground font-medium",
                      isDone && "text-foreground",
                      !isDone && !isCurrent && "text-foreground-muted"
                    )
                  ),
                ],
                [stepLabel(ctx.translator, step)]
              ),
            ]
          );
        })
      ),
    ]
  );
};

const proposalDescription = (ctx: Ctx, h: H) =>
  ctx.model.flags.descriptionHtml === ""
    ? h.empty
    : h.div(
        [
          h.Class("prose prose-sm dark:prose-invert mb-6"),
          h.InnerHTML(ctx.model.flags.descriptionHtml),
        ],
        []
      );

const requestAlert = (ctx: Ctx, h: H) =>
  ctx.model.requestFailed
    ? h.p(
        [h.Class("text-sm text-danger mb-4"), h.Role("alert")],
        [ctx.translator.t("Something went wrong.")]
      )
    : h.empty;

const nav = (ctx: Ctx, h: H) => {
  const isFirst = ctx.steps[0] === ctx.model.step;

  return h.div(
    [
      h.Class(
        isFirst
          ? "flex justify-end pt-6"
          : "flex flex-col-reverse sm:grid sm:grid-cols-2 gap-3 pt-6"
      ),
    ],
    [
      isFirst
        ? h.empty
        : h.button(
            [
              h.Type("button"),
              h.Class("btn btn-secondary"),
              h.OnClick(ProposeMessage.ClickedBack({ from: ctx.model.step })),
            ],
            [`← ${ctx.translator.t("Back")}`]
          ),
      h.button(
        [
          h.Type("submit"),
          h.Class("btn btn-primary"),
          ...optional(ctx.model.isBusy, h.AriaDisabled(true)),
        ],
        [`${ctx.translator.t("Continue")} →`]
      ),
    ]
  );
};

const card = (children: readonly Html[], h: H) =>
  h.div(
    [h.Id("wizard-content"), h.Class("card card-body max-w-2xl mx-auto")],
    children
  );

const loginNudge = (ctx: Ctx, h: H) =>
  ctx.model.flags.account.signedIn
    ? h.empty
    : h.div(
        [h.Class("mb-4")],
        [
          h.h2(
            [h.Class("font-semibold mb-1")],
            [ctx.translator.t("Have an account?")]
          ),
          h.p(
            [h.Class("mb-2 text-sm text-foreground-muted")],
            [
              ctx.translator.t(
                "Log in to save your details across submissions, track your proposals, and skip re-entering personal data next time."
              ),
            ]
          ),
          h.a(
            [h.Href(ctx.model.flags.loginUrl), h.Class("btn btn-primary")],
            [ctx.translator.t("Log in")]
          ),
        ]
      );

const stepForm = (
  ctx: Ctx,
  step: "category" | "personal" | "timeslots",
  children: readonly Html[],
  h: H
) =>
  h.form(
    [
      h.Id(STEP_FORM_ID),
      h.Key(`${step}-${String(ctx.model.formRevision)}`),
      h.Method("post"),
      h.OnSubmit(ProposeMessage.SubmittedStep({ step })),
    ],
    [...children, nav(ctx, h)]
  );

const personalStep = (ctx: Ctx, h: H) => {
  const { model, translator } = ctx;
  const emailErrors = errorsOf(model.errors, translator, "contact_email");

  return card(
    [
      proposalDescription(ctx, h),
      stepper(ctx, h),
      loginNudge(ctx, h),
      h.h2(
        [h.Class("text-lg font-semibold mb-1")],
        [translator.t("Your Information")]
      ),
      h.p(
        [h.Class("text-sm text-foreground-muted mb-5")],
        [
          translator.t(
            "Your details — private by default. An 👁 marks what attendees will see."
          ),
        ]
      ),
      requestAlert(ctx, h),
      stepForm(
        ctx,
        "personal",
        [
          h.div(
            [h.Class("space-y-6")],
            [
              h.div(
                [],
                [
                  h.label(
                    [
                      h.For("id_contact_email"),
                      h.Class(
                        "block text-sm font-medium text-foreground-secondary mb-1"
                      ),
                    ],
                    [
                      translator.t("Contact Email"),
                      " ",
                      h.span(
                        [h.Class("text-danger"), h.AriaHidden(true)],
                        ["*"]
                      ),
                      " ",
                      h.span(
                        [h.Class("sr-only")],
                        [translator.t("(required)")]
                      ),
                    ]
                  ),
                  h.input([
                    h.Type("email"),
                    h.Name("contact_email"),
                    h.Id("id_contact_email"),
                    h.Attribute(
                      "value",
                      lastValue(model.personalDraft, "contact_email")
                    ),
                    h.Class(
                      cx(
                        "w-full px-4 py-2 text-sm rounded-lg border bg-bg-secondary text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-primary",
                        emailErrors.length > 0
                          ? "border-danger"
                          : "border-border"
                      )
                    ),
                    h.Placeholder(
                      translator.t(
                        "Email address for notifications about this proposal"
                      )
                    ),
                    h.Required(true),
                  ]),
                  emailErrors[0] === undefined
                    ? h.empty
                    : h.p(
                        [h.Class("text-sm text-danger mt-1")],
                        [emailErrors[0]]
                      ),
                  h.p(
                    [h.Class("text-xs text-foreground-muted mt-1")],
                    [
                      translator.t(
                        "We'll use this email to notify you about your proposal status."
                      ),
                    ]
                  ),
                ]
              ),
              ...model.flags.personalFields.map((field) =>
                dynamicField(
                  {
                    draft: model.personalDraft,
                    enhancedWriteIns: model.enhancedWriteIns,
                    errors: model.errors,
                    field,
                    prefix: "personal",
                    translator,
                    visibilityBadge: true,
                  },
                  h
                )
              ),
            ]
          ),
        ],
        h
      ),
    ],
    h
  );
};

const stepAlert = (ctx: Ctx, key: string, h: H) => {
  const [message] = errorsOf(ctx.model.errors, ctx.translator, key);

  return message === undefined
    ? h.empty
    : h.p([h.Class("text-sm text-danger mb-4"), h.Role("alert")], [message]);
};

const categoryStep = (ctx: Ctx, h: H) => {
  const { model, translator } = ctx;

  return card(
    [
      proposalDescription(ctx, h),
      stepper(ctx, h),
      h.h2(
        [h.Class("text-lg font-semibold mb-1")],
        [translator.t("What would you like to propose?")]
      ),
      h.p(
        [h.Class("text-sm text-foreground-muted mb-5")],
        [translator.t("Choose the type of session you want to run.")]
      ),
      stepAlert(ctx, "category_id", h),
      requestAlert(ctx, h),
      model.flags.categories.length === 0
        ? h.empty
        : stepForm(
            ctx,
            "category",
            [
              h.div(
                [h.Class("space-y-3")],
                model.flags.categories.map((category) =>
                  h.label(
                    [
                      h.Key(String(category.id)),
                      h.Class("block cursor-pointer"),
                    ],
                    [
                      h.input([
                        h.Type("radio"),
                        h.Name("category_id"),
                        h.Attribute("value", String(category.id)),
                        h.Class("peer sr-only"),
                        ...optional(
                          model.categoryId === category.id,
                          h.Attribute("checked", "")
                        ),
                      ]),
                      h.div(
                        [
                          h.Class(
                            "border-2 border-border rounded-xl p-5 transition-colors peer-checked:border-primary peer-checked:bg-primary/5 hover:border-primary/50"
                          ),
                        ],
                        [
                          h.div(
                            [h.Class("font-medium text-foreground")],
                            [category.name]
                          ),
                          category.description === ""
                            ? h.empty
                            : h.div(
                                [
                                  h.Class(
                                    "text-sm text-foreground-muted mt-0.5"
                                  ),
                                ],
                                [category.description]
                              ),
                        ]
                      ),
                    ]
                  )
                )
              ),
            ],
            h
          ),
    ],
    h
  );
};

const timeSlotsStep = (ctx: Ctx, h: H) => {
  const { model, translator } = ctx;
  const days = ctx.category?.slotDays ?? [];

  return card(
    [
      proposalDescription(ctx, h),
      stepper(ctx, h),
      h.h2(
        [h.Class("text-lg font-semibold mb-1")],
        [translator.t("Preferred Time Slots")]
      ),
      h.p(
        [h.Class("text-sm text-foreground-muted mb-5")],
        [translator.t("Pick every slot you could host.")]
      ),
      stepAlert(ctx, "time_slot_ids", h),
      requestAlert(ctx, h),
      stepForm(
        ctx,
        "timeslots",
        [
          h.div(
            [h.Class("space-y-5")],
            days.map((day) =>
              h.div(
                [h.Key(day.label)],
                [
                  h.h3(
                    [h.Class("text-sm font-medium text-foreground mb-2")],
                    [day.label]
                  ),
                  h.div(
                    [h.Class("flex flex-wrap gap-2")],
                    day.slots.map((slot) =>
                      h.label(
                        [h.Key(String(slot.id)), h.Class("cursor-pointer")],
                        [
                          h.input([
                            h.Type("checkbox"),
                            h.Name("time_slot_ids"),
                            h.Attribute("value", String(slot.id)),
                            h.Class("peer sr-only"),
                            ...optional(
                              model.timeSlotIds.includes(slot.id),
                              h.Attribute("checked", "")
                            ),
                          ]),
                          h.span(
                            [
                              h.Class(
                                "inline-block border-2 border-border rounded-full px-4 py-2 text-sm text-foreground transition-colors peer-checked:border-primary peer-checked:bg-primary/5 hover:border-primary/50 peer-focus-visible:ring-2 peer-focus-visible:ring-primary/50 min-w-[44px] text-center"
                              ),
                            ],
                            [slot.label]
                          ),
                        ]
                      )
                    )
                  ),
                ]
              )
            )
          ),
        ],
        h
      ),
    ],
    h
  );
};

const controlErrors = (ctx: Ctx, key: string, h: H) =>
  errorsOf(ctx.model.errors, ctx.translator, key).map((message) =>
    h.p([h.Class("text-xs mt-1 text-danger")], [message])
  );

const sessionFact = (
  options: Readonly<{
    icon?: Parameters<typeof icon>[0];
    label?: string;
    labelFor?: string;
    value: readonly (Html | string)[];
  }>,
  h: H
) => {
  const glyph =
    options.icon === undefined
      ? h.empty
      : icon(
          options.icon,
          { class: "size-4 shrink-0 text-foreground-muted/80" },
          h
        );

  return options.label === undefined
    ? h.span(
        [h.Class("inline-flex items-center gap-1.5 min-w-0")],
        [glyph, ...options.value]
      )
    : h.div(
        [h.Class("grid gap-0.5 min-w-0")],
        [
          h.label(
            [
              ...optional(
                options.labelFor !== undefined,
                h.For(options.labelFor ?? "")
              ),
              h.Class("text-xs text-foreground-muted"),
            ],
            [options.label]
          ),
          h.span(
            [h.Class("inline-flex items-center gap-3 min-w-0")],
            [glyph, ...options.value]
          ),
        ]
      );
};

const numberInput = (
  ctx: Ctx,
  options: Readonly<{
    name: string;
    min: number;
    max: number | null;
    required: boolean;
    placeholder?: string;
    unit?: string;
  }>,
  h: H
) => {
  const hasErrors = (ctx.model.errors[options.name] ?? []).length > 0;
  const value = lastValue(ctx.model.detailsDraft, options.name);

  const control = h.input([
    h.Type("number"),
    h.Class(inplaceLook("number", options.unit !== undefined)),
    h.Name(options.name),
    h.Id(`id_${options.name}`),
    ...optional(
      options.placeholder !== undefined,
      h.Placeholder(options.placeholder ?? "")
    ),
    ...optional(value !== "", h.Attribute("value", value)),
    h.Attribute("min", String(options.min)),
    ...optional(options.max !== null, h.Attribute("max", String(options.max))),
    h.InputMode("numeric"),
    ...optional(options.required, h.Required(true)),
    ...optional(hasErrors, h.AriaInvalid(true)),
  ]);

  return [
    options.unit === undefined
      ? control
      : h.span(
          [h.Class("relative inline-flex")],
          [
            control,
            h.span(
              [
                h.AriaHidden(true),
                h.Class(
                  "pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2"
                ),
              ],
              [options.unit]
            ),
          ]
        ),
    ...controlErrors(ctx, options.name, h),
  ];
};

const durationFact = (ctx: Ctx, h: H): Html => {
  const choices = ctx.category?.durations ?? [];
  const label = ctx.translator.t("Duration");
  const hasErrors = (ctx.model.errors.duration ?? []).length > 0;
  const [sole] = choices;

  if (choices.length === 0) {
    return h.empty;
  }

  if (choices.length === 1 && sole !== undefined && !hasErrors) {
    return h.span(
      [h.Class("contents")],
      [
        h.input([
          h.Type("hidden"),
          h.Name("duration"),
          h.Attribute("value", sole.value),
        ]),
        sessionFact(
          {
            icon: clockMini,
            value: [h.span([h.Class("sr-only")], [`${label}:`]), sole.label],
          },
          h
        ),
      ]
    );
  }

  const current = lastValue(ctx.model.detailsDraft, "duration");

  return sessionFact(
    {
      icon: clockMini,
      label,
      labelFor: "id_duration",
      value: [
        h.select(
          [
            h.Class(inplaceLook("select")),
            ...optional(hasErrors, h.AriaInvalid(true)),
            h.Id("id_duration"),
            h.Name("duration"),
            h.Required(true),
          ],
          [{ label: "–", value: "" }, ...choices].map((choice) =>
            h.option(
              [
                h.Attribute("value", choice.value),
                ...optional(
                  choice.value === current,
                  h.Attribute("selected", "")
                ),
              ],
              [choice.label]
            )
          )
        ),
        ...controlErrors(ctx, "duration", h),
      ],
    },
    h
  );
};

const seatsPlaceholder = (ctx: Ctx) => {
  const min = ctx.category?.minParticipantsLimit ?? 0;
  const max = ctx.category?.maxParticipantsLimit ?? 0;

  if (max) {
    return `${String(min)}–${String(max)}`;
  }

  return min ? `${String(min)}+` : ctx.translator.t("no sign-up");
};

const facts = (ctx: Ctx, h: H) => {
  const min = ctx.category?.minParticipantsLimit ?? 0;
  const max = ctx.category?.maxParticipantsLimit ?? 0;

  return h.div(
    [
      h.Class(
        "grid grid-flow-col auto-cols-auto items-end justify-between sm:justify-start gap-x-4 sm:gap-x-6 w-full"
      ),
    ],
    [
      durationFact(ctx, h),
      sessionFact(
        {
          icon: usersMini,
          label: ctx.translator.tc("session capacity", "Seats"),
          labelFor: "id_participants_limit",
          value: numberInput(
            ctx,
            {
              max: max || null,
              min,
              name: "participants_limit",
              placeholder: seatsPlaceholder(ctx),
              required: Boolean(min),
            },
            h
          ),
        },
        h
      ),
      sessionFact(
        {
          label: ctx.translator.t("Minimum age"),
          labelFor: "id_min_age",
          value: numberInput(
            ctx,
            { max: 80, min: 0, name: "min_age", required: false, unit: "+" },
            h
          ),
        },
        h
      ),
    ]
  );
};

const fieldsFor = (
  ctx: Ctx,
  fields: readonly FieldView[],
  h: H
): readonly Html[] =>
  fields.map((field) =>
    dynamicField(
      {
        draft: ctx.model.detailsDraft,
        enhancedWriteIns: ctx.model.enhancedWriteIns,
        errors: ctx.model.errors,
        field,
        prefix: "session",
        translator: ctx.translator,
        visibilityBadge: false,
      },
      h
    )
  );

const tracksFieldset = (ctx: Ctx, h: H) => {
  const { tracks } = ctx.model.flags;
  const [trackError] = errorsOf(ctx.model.errors, ctx.translator, "track_pks");
  const chosen = ctx.model.detailsDraft.track_pks ?? [];

  return tracks.length === 0
    ? h.empty
    : h.fieldset(
        [
          h.Class("flex flex-col gap-y-1 mb-4"),
          ...optional(
            trackError !== undefined,
            h.AriaDescribedBy("propose-track-error")
          ),
        ],
        [
          h.legend(
            [h.Class("text-sm font-medium text-foreground-secondary")],
            [
              h.span(
                [],
                [
                  ctx.translator.t("Tracks"),
                  h.span([h.Class("text-danger"), h.AriaHidden(true)], ["*"]),
                  h.span(
                    [h.Class("sr-only")],
                    [`(${ctx.translator.t("required")})`]
                  ),
                ]
              ),
            ]
          ),
          choiceList(
            {
              choices: tracks.map((track) => ({
                checked: chosen.includes(String(track.id)),
                id: `id_track_${String(track.id)}`,
                label: track.name,
                value: String(track.id),
              })),
              hasErrors: trackError !== undefined,
              name: "track_pks",
            },
            h
          ),
          trackError === undefined
            ? h.empty
            : h.p(
                [h.Id("propose-track-error"), h.Class("text-sm text-danger")],
                [trackError]
              ),
        ]
      );
};

const sessionInfo = (ctx: Ctx, h: H) => {
  const { model, translator } = ctx;
  const fields = ctx.category?.sessionFields ?? [];
  const publicFields = fields.filter((field) => field.isPublic);
  const draft = model.detailsDraft;
  const descriptionInvalid = (model.errors.description ?? []).length > 0;
  const nameInvalid = (model.errors.facilitator_name ?? []).length > 0;
  const { account } = model.flags;

  return h.div(
    [h.DataAttribute("session-info", "")],
    [
      h.div(
        [h.Class("flex items-center gap-3 mb-4 flex-wrap text-sm")],
        [
          account.signedIn && account.person.name !== ""
            ? avatar({ person: account.person, size: "size-9", translator }, h)
            : h.empty,
          h.div(
            [h.Class("flex flex-1 min-w-0 font-medium text-foreground")],
            [
              h.label(
                [h.For("id_facilitator_name"), h.Class("sr-only")],
                [translator.t("Presenter name")]
              ),
              h.input([
                h.Type("text"),
                h.Class(inplaceLook("fit")),
                h.Name("facilitator_name"),
                h.Id("id_facilitator_name"),
                h.Placeholder(translator.t("Your name or nickname")),
                ...optional(
                  lastValue(draft, "facilitator_name") !== "",
                  h.Attribute("value", lastValue(draft, "facilitator_name"))
                ),
                h.Attribute("maxlength", "255"),
                h.Required(true),
                ...optional(nameInvalid, h.AriaInvalid(true)),
              ]),
              ...controlErrors(ctx, "facilitator_name", h),
            ]
          ),
        ]
      ),
      h.div(
        [
          h.Class("flex items-end gap-3 mb-6"),
          h.DataAttribute("session-facts", ""),
        ],
        [
          h.div(
            [
              h.Class(
                "flex flex-1 min-w-0 flex-wrap items-end gap-x-5 gap-y-2 text-sm text-foreground-secondary"
              ),
            ],
            [facts(ctx, h)]
          ),
        ]
      ),
      h.div(
        [h.Class("mb-6")],
        [
          h.h3(
            [
              h.Class("text-sm font-semibold mb-2 text-foreground-secondary"),
              h.DataAttribute("morph", "desc-label"),
            ],
            [
              h.label(
                [h.For("id_description")],
                [translator.t("About this session")]
              ),
            ]
          ),
          h.div(
            [h.Class("text-sm leading-5 text-foreground")],
            [
              h.textarea([
                h.Class(inplaceLook("textarea")),
                h.Id("id_description"),
                h.Name("description"),
                h.Rows(4),
                h.Placeholder(
                  translator.t(
                    "What awaits participants: what it is about, how it goes, what to expect."
                  )
                ),
                h.Required(true),
                ...optional(descriptionInvalid, h.AriaInvalid(true)),
                h.DataAttribute("ph-unmask", ""),
                h.Value(lastValue(draft, "description")),
                h.OnInput((value) =>
                  ProposeMessage.ChangedDraftText({
                    name: "description",
                    value,
                  })
                ),
              ]),
              ...controlErrors(ctx, "description", h),
            ]
          ),
        ]
      ),
      publicFields.length === 0 && model.flags.tracks.length === 0
        ? h.empty
        : h.div(
            [h.Class("mb-6"), h.DataAttribute("session-fields", "")],
            [
              h.div(
                [],
                [...fieldsFor(ctx, publicFields, h), tracksFieldset(ctx, h)]
              ),
            ]
          ),
    ]
  );
};

const copyFrom = (ctx: Ctx, h: H) => {
  const { model, translator } = ctx;
  const copied = model.copiedSnapshot !== null;

  return model.flags.reusableSessions.length === 0
    ? h.empty
    : h.div(
        [
          h.Class(
            "flex flex-wrap items-center justify-end gap-x-3 gap-y-1 mb-2 text-sm"
          ),
          h.DataAttribute("propose-copy", DETAILS_FORM_ID),
        ],
        [
          h.span(
            [
              h.Class(
                "inline-flex items-center gap-1 font-medium text-success-text"
              ),
              ...optional(!copied, h.Hidden(true)),
              h.DataAttribute("propose-copied", ""),
            ],
            [
              icon(checkMini, { class: "size-3.5" }, h),
              h.span([h.Class("max-sm:sr-only")], [translator.t("Copied")]),
            ]
          ),
          h.button(
            [
              h.Type("button"),
              h.Class("font-medium text-primary underline underline-offset-3"),
              ...optional(!copied, h.Hidden(true)),
              h.DataAttribute("propose-copy-undo", ""),
              h.OnClick(ProposeMessage.ClickedUndoCopy()),
            ],
            [translator.t("Undo")]
          ),
          actionDropdown(
            {
              align: "right",
              hover: false,
              id: "propose-copy-menu",
              isOpen: model.isCopyMenuOpen,
              items: [
                ...model.flags.reusableSessions.map((reusable) =>
                  h.button(
                    [
                      h.Key(String(reusable.sessionId)),
                      h.Type("button"),
                      h.Class(
                        "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap cursor-pointer text-foreground-secondary transition-colors duration-150 hover:bg-bg-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary w-full text-left"
                      ),
                      h.DataAttribute(
                        "propose-copy-from",
                        String(reusable.sessionId)
                      ),
                      h.OnClick(
                        ProposeMessage.ClickedCopyFrom({
                          sessionId: reusable.sessionId,
                        })
                      ),
                    ],
                    [
                      h.span(
                        [h.Class("grid whitespace-normal")],
                        [
                          h.span([], [reusable.title]),
                          h.span(
                            [
                              h.Class(
                                "text-xs font-normal text-foreground-muted"
                              ),
                            ],
                            [reusable.eventName]
                          ),
                        ]
                      ),
                    ]
                  )
                ),
                h.p(
                  [
                    h.Class(
                      "max-w-72 px-3 pt-2 pb-1 border-t border-border text-xs text-foreground-muted whitespace-normal"
                    ),
                  ],
                  [
                    translator.t(
                      "Copies the title, description and answers. Time slots, tracks and the cover stay as they are."
                    ),
                  ]
                ),
              ],
              onToggle: (isOpen) => ProposeMessage.ToggledCopyMenu({ isOpen }),
              trigger: [
                icon(documentDuplicateMini, { class: "size-4 shrink-0" }, h),
                translator.t("Copy from an earlier session"),
                icon(chevronDownMini, { class: "size-4 shrink-0" }, h),
              ],
              triggerClass:
                "inline-flex items-center gap-1 min-h-11 font-medium text-foreground-muted transition-colors duration-150 hover:duration-0 hover:text-foreground aria-expanded:text-foreground",
            },
            h
          ),
          h.p(
            [
              h.Class("sr-only"),
              h.Role("status"),
              h.DataAttribute("propose-copy-status", ""),
            ],
            [copied ? translator.t("Copied") : ""]
          ),
        ]
      );
};

const detailsStep = (ctx: Ctx, h: H) => {
  const { model, translator } = ctx;
  const fields = ctx.category?.sessionFields ?? [];
  const privateFields = fields.filter((field) => !field.isPublic);
  const titleInvalid = (model.errors.title ?? []).length > 0;

  return h.div(
    [h.Id("wizard-content"), h.Class("flex justify-center")],
    [
      h.div(
        [h.Class("w-full max-w-200 min-w-0")],
        [
          proposalDescription(ctx, h),
          copyFrom(ctx, h),
          h.form(
            [
              h.Id(DETAILS_FORM_ID),
              h.Key(`details-${String(model.formRevision)}`),
              h.Method("post"),
              h.Enctype("multipart/form-data"),
              h.Class(
                "bg-bg-secondary border border-border rounded-2xl shadow-lg text-foreground"
              ),
              h.OnSubmit(ProposeMessage.SubmittedStep({ step: "details" })),
            ],
            [
              h.h2([h.Class("sr-only")], [translator.t("Session Details")]),
              h.div(
                [h.Class("px-6 pt-6")],
                [stepper(ctx, h), requestAlert(ctx, h)]
              ),
              h.div(
                [
                  h.Class(
                    "px-6 py-4 border-b border-border text-lg font-semibold text-foreground"
                  ),
                ],
                [
                  h.label(
                    [h.For("id_title"), h.Class("sr-only")],
                    [translator.t("Title")]
                  ),
                  h.input([
                    h.Type("text"),
                    h.Class(inplaceLook("text")),
                    h.Name("title"),
                    h.Id("id_title"),
                    h.Placeholder(translator.t("Session title")),
                    ...optional(
                      lastValue(model.detailsDraft, "title") !== "",
                      h.Attribute(
                        "value",
                        lastValue(model.detailsDraft, "title")
                      )
                    ),
                    h.Attribute("maxlength", "255"),
                    h.Required(true),
                    ...optional(titleInvalid, h.AriaInvalid(true)),
                  ]),
                  ...controlErrors(ctx, "title", h),
                ]
              ),
              h.div([h.Class("px-6 py-4")], [sessionInfo(ctx, h)]),
              privateFields.length === 0
                ? h.empty
                : h.section(
                    [
                      h.Class(
                        "border-t border-border bg-proposal-surface dark:bg-black/25 px-6 py-4"
                      ),
                      h.AriaLabelledBy("propose-private-heading"),
                    ],
                    [
                      h.h3(
                        [
                          h.Id("propose-private-heading"),
                          h.Class(
                            "flex items-center gap-1.5 text-sm font-semibold text-foreground-secondary"
                          ),
                        ],
                        [
                          icon(lockClosedMini, { class: "w-4 h-4" }, h),
                          translator.t("Visible to organizers only"),
                        ]
                      ),
                      h.p(
                        [h.Class("mb-4 text-sm text-foreground-muted")],
                        [translator.t("Participants won't see this.")]
                      ),
                      ...fieldsFor(ctx, privateFields, h),
                    ]
                  ),
              h.div(
                [h.Class("px-6 pb-6 border-t border-border")],
                [nav(ctx, h)]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const displayValue = (
  translator: Translator,
  field: FieldView,
  value: FieldAnswer
): string => {
  if (Predicate.isBoolean(value)) {
    return value ? translator.t("Yes") : translator.t("No");
  }

  const labels = new Map(
    field.options.map((option) => [option.value, option.label])
  );

  const shown = (raw: string) => labels.get(raw) ?? raw;

  return Predicate.isString(value) ? shown(value) : value.map(shown).join(", ");
};

const answered = (
  fields: readonly FieldView[],
  answers: Readonly<Record<string, FieldAnswer>>,
  prefix: string
) =>
  fields.flatMap((field) => {
    const value = answers[`${prefix}_${field.slug}`];

    if (value === undefined) {
      return [];
    }

    const present =
      Predicate.isBoolean(value) ||
      (Predicate.isString(value) ? value !== "" : value.length > 0);

    return present ? [{ field, value }] : [];
  });

const visibilityHeader = (
  ctx: Ctx,
  options: Readonly<{ isPublic: boolean; isFirst: boolean }>,
  h: H
) =>
  h.div(
    [
      h.Class(
        cx(
          "flex items-center gap-2 text-xs font-medium mb-2",
          !options.isFirst && "mt-4",
          options.isPublic ? "text-success-text" : "text-foreground-muted"
        )
      ),
    ],
    [
      icon(
        options.isPublic ? eyeMini : lockClosedMini,
        { class: "w-3.5 h-3.5" },
        h
      ),
      options.isPublic
        ? ctx.translator.t("Public information")
        : ctx.translator.t("For organizers"),
    ]
  );

const term = (
  label: readonly (Html | string)[],
  value: readonly (Html | string)[],
  h: H
) =>
  h.div(
    [],
    [
      h.dt([h.Class("text-xs text-foreground-muted")], label),
      h.dd([h.Class("text-foreground")], value),
    ]
  );

const fieldTerms = (
  ctx: Ctx,
  rows: readonly Readonly<{ field: FieldView; value: FieldAnswer }>[],
  withIcon: boolean,
  h: H
) =>
  rows.map(({ field, value }) =>
    term(
      [
        withIcon && field.icon !== null
          ? icon(
              field.icon,
              { class: "w-3.5 h-3.5 inline mr-0.5 text-foreground-muted" },
              h
            )
          : h.empty,
        field.question,
      ],
      [displayValue(ctx.translator, field, value)],
      h
    )
  );

const reviewFacts = (ctx: Ctx) => {
  const { model } = ctx;
  const details = model.acceptedDetails?.details;
  const personal = model.acceptedPersonal;

  const sessionRows = answered(
    ctx.category?.sessionFields ?? [],
    details?.answers ?? {},
    "session"
  );

  const personalRows = answered(
    model.flags.personalFields,
    personal?.answers ?? {},
    "personal"
  );

  const durationLabel =
    ctx.category?.durations.find((choice) => choice.value === details?.duration)
      ?.label ?? "";

  const selectedDays = (ctx.category?.slotDays ?? [])
    .map((day) => ({
      ...day,
      slots: day.slots.filter((slot) => model.timeSlotIds.includes(slot.id)),
    }))
    .filter((day) => day.slots.length > 0);

  return {
    contactEmail: personal?.contactEmail ?? "",
    details,
    durationLabel,
    privatePersonal: personalRows.filter((row) => !row.field.isPublic),
    privateSession: sessionRows.filter((row) => !row.field.isPublic),
    publicPersonal: personalRows.filter((row) => row.field.isPublic),
    publicSession: sessionRows.filter((row) => row.field.isPublic),
    selectedDays,
  };
};

const reviewStep = (ctx: Ctx, h: H) => {
  const { model, translator } = ctx;

  const {
    contactEmail,
    details,
    durationLabel,
    privatePersonal,
    privateSession,
    publicPersonal,
    publicSession,
    selectedDays,
  } = reviewFacts(ctx);

  const box = (children: readonly Html[]) =>
    h.div([h.Class("border border-border rounded-2xl p-5")], children);

  return card(
    [
      proposalDescription(ctx, h),
      stepper(ctx, h),
      details === undefined
        ? h.empty
        : h.div(
            [],
            [
              h.h2(
                [h.Class("text-lg font-semibold mb-1")],
                [translator.t("Review & Submit")]
              ),
              h.p(
                [h.Class("text-sm text-foreground-muted mb-5")],
                [translator.t("Please review your proposal before submitting.")]
              ),
              requestAlert(ctx, h),
              h.div(
                [h.Class("space-y-4 break-words")],
                [
                  ctx.category === null
                    ? h.empty
                    : box([
                        h.h3(
                          [
                            h.Class(
                              "text-sm font-medium text-foreground-muted mb-2"
                            ),
                          ],
                          [translator.t("Category")]
                        ),
                        h.p([h.Class("text-foreground")], [ctx.category.name]),
                      ]),
                  box([
                    h.h3(
                      [
                        h.Class(
                          "text-sm font-medium text-foreground-muted mb-2"
                        ),
                      ],
                      [translator.tc("proposal review heading", "Session")]
                    ),
                    visibilityHeader(ctx, { isFirst: true, isPublic: true }, h),
                    h.dl(
                      [h.Class("space-y-2")],
                      [
                        term(
                          [translator.t("Presenter name")],
                          [details.facilitatorName],
                          h
                        ),
                        term([translator.t("Title")], [details.title], h),
                        details.description === ""
                          ? h.empty
                          : h.div(
                              [],
                              [
                                h.dt(
                                  [h.Class("text-xs text-foreground-muted")],
                                  [translator.t("Description")]
                                ),
                                h.dd(
                                  [
                                    h.Class(
                                      "prose prose-sm dark:prose-invert max-w-none text-foreground prose-p:text-foreground"
                                    ),
                                    h.InnerHTML(model.descriptionHtml),
                                  ],
                                  []
                                ),
                              ]
                            ),
                        term(
                          [translator.t("Max participants")],
                          [
                            details.participantsLimit
                              ? String(details.participantsLimit)
                              : translator.t("No limit"),
                          ],
                          h
                        ),
                        term(
                          [translator.t("Minimum age")],
                          [
                            details.minAge
                              ? `${String(details.minAge)}+`
                              : translator.t("All ages"),
                          ],
                          h
                        ),
                        durationLabel === ""
                          ? h.empty
                          : term(
                              [translator.t("Duration")],
                              [durationLabel],
                              h
                            ),
                        ...fieldTerms(ctx, publicSession, true, h),
                      ]
                    ),
                    ...(privateSession.length === 0
                      ? []
                      : [
                          visibilityHeader(
                            ctx,
                            { isFirst: false, isPublic: false },
                            h
                          ),
                          h.dl(
                            [h.Class("space-y-2")],
                            fieldTerms(ctx, privateSession, true, h)
                          ),
                        ]),
                  ]),
                  box([
                    h.h3(
                      [
                        h.Class(
                          "text-sm font-medium text-foreground-muted mb-2"
                        ),
                      ],
                      [translator.t("Your Information")]
                    ),
                    ...(publicPersonal.length === 0
                      ? []
                      : [
                          visibilityHeader(
                            ctx,
                            { isFirst: true, isPublic: true },
                            h
                          ),
                          h.dl(
                            [h.Class("space-y-2")],
                            fieldTerms(ctx, publicPersonal, false, h)
                          ),
                        ]),
                    visibilityHeader(
                      ctx,
                      { isFirst: publicPersonal.length === 0, isPublic: false },
                      h
                    ),
                    h.dl(
                      [h.Class("space-y-2")],
                      [
                        contactEmail === ""
                          ? h.empty
                          : h.div(
                              [],
                              [
                                h.dt(
                                  [h.Class("text-xs text-foreground-muted")],
                                  [translator.t("Contact Email")]
                                ),
                                h.dd(
                                  [
                                    h.Class("text-foreground"),
                                    h.DataAttribute("ph-mask", ""),
                                  ],
                                  [contactEmail]
                                ),
                              ]
                            ),
                        ...fieldTerms(ctx, privatePersonal, false, h),
                      ]
                    ),
                  ]),
                  selectedDays.length === 0
                    ? h.empty
                    : box([
                        h.h3(
                          [
                            h.Class(
                              "text-sm font-medium text-foreground-muted mb-3"
                            ),
                          ],
                          [translator.t("Preferred Time Slots")]
                        ),
                        h.div(
                          [h.Class("space-y-4")],
                          selectedDays.map((day) =>
                            h.div(
                              [h.Key(day.label)],
                              [
                                h.h4(
                                  [
                                    h.Class(
                                      "text-xs font-medium text-foreground mb-2"
                                    ),
                                  ],
                                  [day.label]
                                ),
                                h.div(
                                  [h.Class("flex flex-wrap gap-2")],
                                  day.slots.map((slot) =>
                                    h.span(
                                      [
                                        h.Key(String(slot.id)),
                                        h.Class(
                                          "inline-block border-2 border-primary bg-primary/5 rounded-full px-4 py-2 text-sm text-foreground min-w-[44px] text-center"
                                        ),
                                      ],
                                      [slot.label]
                                    )
                                  )
                                ),
                              ]
                            )
                          )
                        ),
                      ]),
                ]
              ),
              h.form(
                [
                  h.Method("post"),
                  h.OnSubmit(ProposeMessage.ClickedSubmitProposal()),
                ],
                [
                  h.div(
                    [
                      h.Class(
                        "flex flex-col-reverse sm:grid sm:grid-cols-2 gap-3 pt-6"
                      ),
                    ],
                    [
                      h.button(
                        [
                          h.Type("button"),
                          h.Class("btn btn-secondary"),
                          h.OnClick(
                            ProposeMessage.ClickedBack({ from: "review" })
                          ),
                        ],
                        [`← ${translator.t("Back")}`]
                      ),
                      h.button(
                        [
                          h.Type("submit"),
                          h.Class("btn btn-primary"),
                          ...optional(model.isBusy, h.AriaDisabled(true)),
                        ],
                        [translator.t("Submit Proposal")]
                      ),
                    ]
                  ),
                ]
              ),
            ]
          ),
    ],
    h
  );
};

const stepViews: Readonly<Record<ProposeStep, (ctx: Ctx, h: H) => Html>> = {
  category: (ctx, h) => categoryStep(ctx, h),
  details: (ctx, h) => detailsStep(ctx, h),
  personal: (ctx, h) => personalStep(ctx, h),
  review: (ctx, h) => reviewStep(ctx, h),
  timeslots: (ctx, h) => timeSlotsStep(ctx, h),
};

const stepView = (ctx: Ctx, h: H) => stepViews[ctx.model.step](ctx, h);

export const proposeView = defineView<ProposeModel, ProposeMessage, PageInputs>(
  (model, inputs, h) => {
    const context = pageContextOf(inputs.shell);
    const { translator } = context;

    const ctx: Ctx = {
      category: categoryOf(model),
      model,
      steps: stepsOf(model),
      translator,
    };

    return h.div(
      [],
      [
        h.div(
          [h.Class("mb-6 text-center")],
          [
            h.h1(
              [h.Class("text-2xl sm:text-3xl font-bold text-foreground mb-2")],
              [translator.t("Propose Session")]
            ),
            `${translator.t("Submit a session proposal for")} ${model.flags.eventName}`,
          ]
        ),
        stepView(ctx, h),
        h.p(
          [
            h.Class(
              "max-w-2xl mx-auto mt-6 text-sm text-center text-foreground-muted"
            ),
          ],
          [
            translator.t(
              "Proposals are reviewed by organizers. You'll be notified when yours is accepted and added to the agenda."
            ),
          ]
        ),
      ]
    );
  }
);
