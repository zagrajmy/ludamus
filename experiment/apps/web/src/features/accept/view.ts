import type { Html, HtmlBuilder } from "foldkit/html";
import { defineView } from "foldkit/submodel";

import type { AcceptChoice } from "../../client/accept/flags.js";
import { ProposalAcceptMessage } from "../../client/accept/message.js";
import type { ProposalAcceptModel } from "../../client/accept/model.js";
import { errorsFor } from "../../client/panel/failure.js";
import { button, linkButton } from "../../ui/button.js";
import { field, formErrors } from "../../ui/form.js";
import type { Translator } from "../../ui/i18n.js";
import { icon } from "../../ui/icon.js";
import type { IconData } from "../../ui/icon.js";
import {
  arrowLeftOutline,
  calendarDaysOutline,
  clockMini,
  clockOutline,
  mapPinOutline,
} from "../../ui/icons.js";
import { pageContextOf } from "../page-context.js";
import type { PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

type H = HtmlBuilder<ProposalAcceptMessage>;

export const proposalAcceptTitle = (
  model: ProposalAcceptModel,
  translator: Translator
): PageTitle => ({
  name: `${translator.t("Accept Proposal")} • ${model.title}`,
  sphereSuffix: true,
});

const factRow = (
  options: Readonly<{ glyph: IconData; label: string; value: string }>,
  h: H
) =>
  h.div(
    [
      h.Class(
        "flex gap-3 border-t border-border pt-3 mt-3 first:border-t-0 first:mt-0 first:pt-0"
      ),
    ],
    [
      h.span(
        [
          h.Class(
            "shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-lg bg-bg-tertiary text-foreground-secondary"
          ),
        ],
        [icon(options.glyph, { class: "w-4 h-4" }, h)]
      ),
      h.div(
        [h.Class("min-w-0")],
        [
          h.dt(
            [
              h.Class(
                "text-xs font-medium uppercase tracking-wide text-foreground-muted"
              ),
            ],
            [options.label]
          ),
          h.dd(
            [h.Class("mt-0.5 text-sm text-foreground-secondary")],
            [options.value]
          ),
        ]
      ),
    ]
  );

const groupsOf = (choices: readonly AcceptChoice[]) =>
  [...new Set(choices.map((choice) => choice.group))].map((group) => ({
    label: group,
    options: choices.flatMap((choice) =>
      choice.group === group
        ? [{ label: choice.label, value: String(choice.id) }]
        : []
    ),
  }));

const chooser = (
  options: Readonly<{
    blank: string;
    choices: readonly AcceptChoice[];
    help: string;
    id: string;
    label: string;
    model: ProposalAcceptModel;
    name: string;
    onChange: (value: string) => ProposalAcceptMessage;
    selected: string;
    translator: Translator;
  }>,
  h: H
) => {
  const errors = errorsFor(
    options.model.errors,
    options.name,
    options.translator
  );

  const grouped = options.choices.some((choice) => choice.group !== "");

  return field(
    {
      control: h.select(
        [
          h.Id(options.id),
          h.Name(options.name),
          h.Required(true),
          h.Class(
            "w-full px-3 py-2 text-base sm:text-sm rounded-lg border border-border aria-invalid:border-danger bg-bg-secondary text-foreground"
          ),
          ...(errors.length > 0
            ? [h.AriaInvalid(true)]
            : [h.AriaDescribedBy(`${options.id}_help`)]),
          h.OnChange(options.onChange),
        ],
        [
          h.option(
            [
              h.Value(""),
              ...(options.selected === "" ? [h.Selected(true)] : []),
            ],
            [options.blank]
          ),
          ...(grouped
            ? groupsOf(options.choices).map((group) =>
                h.optgroup(
                  [h.LabelAttr(group.label)],
                  group.options.map((choice) =>
                    h.option(
                      [
                        h.Value(choice.value),
                        ...(choice.value === options.selected
                          ? [h.Selected(true)]
                          : []),
                      ],
                      [choice.label]
                    )
                  )
                )
              )
            : options.choices.map((choice) =>
                h.option(
                  [
                    h.Value(String(choice.id)),
                    ...(String(choice.id) === options.selected
                      ? [h.Selected(true)]
                      : []),
                  ],
                  [choice.label]
                )
              )),
        ]
      ),
      described: { errors, help: options.help, id: options.id },
      label: options.label,
      required: true,
      translator: options.translator,
    },
    h
  );
};

const decision = (
  model: ProposalAcceptModel,
  translator: Translator,
  h: H
): readonly Html[] => {
  const { t } = translator;

  if (model.blocker !== "none") {
    return [
      h.p(
        [h.Class("text-sm text-foreground-muted")],
        [
          model.blocker === "time_slots"
            ? t(
                "This event has no time slots yet, so nothing can go on the agenda. Add the time slots, then come back to accept this proposal."
              )
            : t(
                "This event has no spaces yet, so nothing can go on the agenda. Add a space, then come back to accept this proposal."
              ),
        ]
      ),
    ];
  }

  const soleSpace = model.spaces.length === 1 ? model.spaces[0] : undefined;
  const soleSlot = model.slots.length === 1 ? model.slots[0] : undefined;

  return [
    h.form(
      [
        h.Id("accept-proposal-form"),
        h.Method("post"),
        h.Class("space-y-5"),
        h.OnSubmit(ProposalAcceptMessage.SubmittedAccept()),
      ],
      [
        ...formErrors(errorsFor(model.errors, "", translator), h),
        soleSpace === undefined && soleSlot === undefined
          ? h.empty
          : h.dl(
              [],
              [
                soleSpace === undefined
                  ? h.empty
                  : factRow(
                      {
                        glyph: mapPinOutline,
                        label: t("Space"),
                        value: soleSpace.label,
                      },
                      h
                    ),
                soleSlot === undefined
                  ? h.empty
                  : factRow(
                      {
                        glyph: clockOutline,
                        label: t("Time slot"),
                        value: soleSlot.label,
                      },
                      h
                    ),
              ]
            ),
        soleSpace === undefined
          ? chooser(
              {
                blank: t("Select a space..."),
                choices: model.spaces,
                help: t("Select the space where this session will take place"),
                id: "id_space",
                label: t("Space"),
                model,
                name: "space",
                onChange: (value) =>
                  ProposalAcceptMessage.ChangedSpace({ value }),
                selected: model.spaceId,
                translator,
              },
              h
            )
          : h.input([
              h.Type("hidden"),
              h.Name("space"),
              h.Value(model.spaceId),
            ]),
        soleSlot === undefined
          ? chooser(
              {
                blank: t("Choose a time…"),
                choices: model.slots,
                help: t("Pick the start time for this session."),
                id: "id_time_slot",
                label: t("Time slot"),
                model,
                name: "time_slot",
                onChange: (value) =>
                  ProposalAcceptMessage.ChangedSlot({ value }),
                selected: model.slotId,
                translator,
              },
              h
            )
          : h.input([
              h.Type("hidden"),
              h.Name("time_slot"),
              h.Value(model.slotId),
            ]),
      ]
    ),
  ];
};

export const proposalAcceptView = defineView<
  ProposalAcceptModel,
  ProposalAcceptMessage,
  PageInputs
>((model, inputs, h) => {
  const { translator } = pageContextOf(inputs.shell);
  const { t } = translator;
  const eventHref = `/event/${model.eventSlug}/`;

  return h.div(
    [],
    [
      h.div(
        [h.Class("mb-6")],
        [
          h.h1(
            [h.Class("text-2xl sm:text-3xl font-bold text-foreground mb-2")],
            [t("Accept Proposal")]
          ),
          h.p(
            [h.Class("text-foreground-secondary")],
            [t("Review the proposal, then add it to the agenda.")]
          ),
        ]
      ),
      h.div(
        [
          h.Class(
            "max-w-5xl mx-auto grid gap-6 lg:grid-cols-[1fr_22rem] lg:items-start"
          ),
        ],
        [
          h.div(
            [h.Class("card")],
            [
              h.div(
                [h.Class("card-body")],
                [
                  h.h2(
                    [h.Class("text-xl font-semibold text-foreground mb-4")],
                    [model.title]
                  ),
                  h.div(
                    [h.Class("flex items-center gap-3 mb-6 flex-wrap")],
                    [
                      h.span(
                        [
                          h.Class(
                            "size-9 shrink-0 rounded-full bg-warm-200 dark:bg-neutral-700 flex items-center justify-center text-xs font-semibold text-warm-700 dark:text-neutral-300"
                          ),
                          h.Role("img"),
                          h.AriaLabel(model.facilitatorName),
                        ],
                        [model.facilitatorName.slice(0, 2).toUpperCase()]
                      ),
                      h.div(
                        [h.Class("font-medium text-foreground")],
                        [model.facilitatorName]
                      ),
                      model.contactEmail === ""
                        ? h.empty
                        : h.a(
                            [
                              h.Href(`mailto:${model.contactEmail}`),
                              h.Class(
                                "text-sm text-primary hover:underline truncate"
                              ),
                            ],
                            [model.contactEmail]
                          ),
                    ]
                  ),
                  model.descriptionHtml === ""
                    ? h.empty
                    : h.div(
                        [h.Class("mb-6")],
                        [
                          h.h3(
                            [
                              h.Class(
                                "font-semibold mb-2 text-foreground-secondary"
                              ),
                            ],
                            [t("About this session")]
                          ),
                          h.div([
                            h.Class(
                              "prose prose-sm dark:prose-invert max-w-none text-foreground"
                            ),
                            h.InnerHTML(model.descriptionHtml),
                          ]),
                        ]
                      ),
                  model.fieldValues.length === 0
                    ? h.empty
                    : h.dl(
                        [h.Class("mb-6 space-y-2")],
                        model.fieldValues.map((fact) =>
                          h.div(
                            [],
                            [
                              h.dt(
                                [h.Class("text-xs text-foreground-muted")],
                                [fact.label]
                              ),
                              h.dd(
                                [h.Class("text-sm text-foreground")],
                                [fact.value]
                              ),
                            ]
                          )
                        )
                      ),
                  h.div(
                    [h.Class("grid grid-cols-2 gap-3")],
                    model.facts.map((fact) =>
                      h.div(
                        [
                          h.Class(
                            "bg-warm-100 dark:bg-neutral-800 rounded-xl p-4"
                          ),
                        ],
                        [
                          h.div(
                            [h.Class("text-sm mb-1 text-foreground-muted")],
                            [fact.label]
                          ),
                          h.div(
                            [h.Class("font-medium text-foreground")],
                            [fact.value]
                          ),
                        ]
                      )
                    )
                  ),
                  model.preferredSlots.length === 0
                    ? h.empty
                    : h.div(
                        [h.Class("mt-6")],
                        [
                          h.h4(
                            [
                              h.Class(
                                "text-sm font-semibold mb-1 text-foreground-secondary"
                              ),
                            ],
                            [
                              icon(
                                clockMini,
                                { class: "w-4 h-4 inline mr-1" },
                                h
                              ),
                              t("Preferred Time Slots"),
                            ]
                          ),
                          h.div(
                            [h.Class("flex flex-wrap gap-1.5")],
                            model.preferredSlots.map((slot) =>
                              h.span(
                                [
                                  h.Class(
                                    "inline-flex items-center gap-1 rounded-2xl font-medium px-2.5 py-1 text-sm bg-warm-200/80 dark:bg-neutral-700 text-warm-700 dark:text-neutral-300"
                                  ),
                                ],
                                [slot]
                              )
                            )
                          ),
                        ]
                      ),
                ]
              ),
            ]
          ),
          h.div(
            [h.Class("card lg:sticky lg:top-20")],
            [
              h.div(
                [h.Class("card-body")],
                [
                  h.h3(
                    [h.Class("text-base font-semibold text-foreground mb-5")],
                    [t("Schedule it")]
                  ),
                  ...decision(model, translator, h),
                  h.div(
                    [h.Class("[&_.btn]:w-full space-y-3 pt-5")],
                    [
                      model.blocker === "none"
                        ? button(
                            {
                              attributes: [
                                h.Attribute("form", "accept-proposal-form"),
                              ],
                              disabled: model.isSaving,
                              icon: calendarDaysOutline,
                              text: t("Accept and add to agenda"),
                            },
                            h
                          )
                        : linkButton(
                            {
                              href:
                                model.blocker === "time_slots"
                                  ? `/panel/event/${model.eventSlug}/cfp/time-slots/create/`
                                  : `/panel/event/${model.eventSlug}/venues/create/`,
                              icon:
                                model.blocker === "time_slots"
                                  ? clockOutline
                                  : mapPinOutline,
                              text:
                                model.blocker === "time_slots"
                                  ? t("Add time slots")
                                  : t("Add a space"),
                            },
                            h
                          ),
                      h.div(
                        [
                          h.Class(
                            "flex items-center gap-3 text-xs text-foreground-muted"
                          ),
                        ],
                        [
                          h.hr([h.Class("flex-1")]),
                          h.span([], [t("or")]),
                          h.hr([h.Class("flex-1")]),
                        ]
                      ),
                      linkButton(
                        {
                          href: eventHref,
                          icon: arrowLeftOutline,
                          text: t("Back to event"),
                          variant: "secondary",
                        },
                        h
                      ),
                    ]
                  ),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );
});
