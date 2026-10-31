import type { EnrollmentRow } from "@zagrajmy/core/contracts";
import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";
import { defineView } from "foldkit/submodel";

import { EnrollPageMessage } from "../../client/enroll-page/message.js";
import { enrollPreview } from "../../client/enroll-page/model.js";
import type {
  EnrollPageModel,
  SeatHint,
} from "../../client/enroll-page/model.js";
import { avatar } from "../../ui/avatar.js";
import { coverStrip } from "../../ui/cover.js";
import { cx } from "../../ui/cx.js";
import { checkboxInput } from "../../ui/form.js";
import type { Translator } from "../../ui/i18n.js";
import { icon } from "../../ui/icon.js";
import {
  arrowLeftMini,
  clockMini,
  mapPinMini,
  usersMini,
} from "../../ui/icons.js";
import { pageContextOf } from "../page-context.js";
import type { PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

type Message = EnrollPageMessage;

export const enrollPageTitle = (
  model: EnrollPageModel,
  translator: Translator
): PageTitle => ({
  name: `${translator.t("Enrollment")} • ${model.form.title}`,
  sphereSuffix: true,
});

const DOT: Readonly<Record<EnrollmentRow["badge"]["variant"], string>> = {
  danger: "bg-danger",
  muted: "bg-foreground-muted",
  success: "bg-success",
  warning: "bg-warning",
};

const HINT: Readonly<
  Record<Exclude<SeatHint, null>, { tone: string; msgid: string }>
> = {
  leave: { msgid: "Will leave the session", tone: "text-foreground-muted" },
  seat: { msgid: "Gets a seat", tone: "text-success-text" },
  wait: { msgid: "Joins the waiting list", tone: "text-warning-text" },
};

const sessionCard = (
  model: EnrollPageModel,
  translator: Translator,
  h: HtmlBuilder<Message>
) => {
  const { form } = model;
  const { t } = translator;
  const { seatsLeft } = form.seats;

  return h.div(
    [h.Class("card overflow-hidden")],
    [
      ...Option.match(model.coverUrl, {
        onNone: () => [],
        onSome: (url) => [coverStrip({ extraClass: "", url }, h)],
      }),
      h.div(
        [h.Class("card-body")],
        [
          h.p(
            [
              h.Class(
                "text-xs font-medium uppercase tracking-wide text-foreground-muted mb-1.5"
              ),
            ],
            [t("Enrollment")]
          ),
          h.h1(
            [
              h.Class(
                "text-2xl sm:text-3xl font-bold text-foreground text-balance"
              ),
            ],
            [form.title]
          ),
          h.div(
            [
              h.Class(
                "flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-3 mb-6 text-sm text-foreground-secondary"
              ),
            ],
            [
              h.span(
                [h.Class("inline-flex items-center gap-1.5")],
                [
                  icon(clockMini, { class: "size-4 shrink-0 opacity-80" }, h),
                  model.whenLabel,
                ]
              ),
              ...(form.seats.effectiveParticipantsLimit > 0
                ? [
                    h.span(
                      [h.Class("inline-flex items-center gap-1.5")],
                      [
                        h.span(
                          [
                            h.Class(
                              cx(
                                "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums",
                                seatsLeft === 0
                                  ? "bg-coral-100 dark:bg-coral-900 text-coral-700 dark:text-coral-400"
                                  : "bg-teal-100 dark:bg-teal-900 text-teal-700 dark:text-teal-400"
                              )
                            ),
                          ],
                          [
                            `${form.seats.enrolledCount}/${form.seats.effectiveParticipantsLimit}`,
                          ]
                        ),
                        ...(form.seats.waitingCount > 0
                          ? [
                              h.span(
                                [
                                  h.Class(
                                    "px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums bg-warning-light text-warning-text"
                                  ),
                                ],
                                [`+${form.seats.waitingCount}`]
                              ),
                            ]
                          : []),
                      ]
                    ),
                  ]
                : []),
            ]
          ),
          h.div(
            [h.Class("flex items-center gap-3 mb-6")],
            [
              ...Option.match(model.presenterAvatar, {
                onNone: () => [],
                onSome: (person) => [
                  h.span(
                    [h.Class("shrink-0")],
                    [avatar({ person, size: "size-10", translator }, h)]
                  ),
                ],
              }),
              h.div(
                [
                  h.Class(
                    "flex items-center gap-x-3 gap-y-0.5 flex-wrap min-w-0"
                  ),
                ],
                [
                  h.div(
                    [h.Class("font-medium text-foreground")],
                    [form.facilitatorName]
                  ),
                  ...(form.agenda?.spaceName === null ||
                  form.agenda?.spaceName === undefined
                    ? []
                    : [
                        h.span(
                          [
                            h.Class(
                              "flex items-center gap-1.5 text-sm min-w-0 text-foreground-muted"
                            ),
                          ],
                          [
                            icon(
                              mapPinMini,
                              { class: "size-4 shrink-0 opacity-80" },
                              h
                            ),
                            h.span(
                              [
                                h.Class("truncate"),
                                h.Title(form.agenda.spaceName),
                              ],
                              [form.agenda.spaceName]
                            ),
                          ]
                        ),
                      ]),
                ]
              ),
            ]
          ),
          ...(model.descriptionHtml === ""
            ? []
            : [
                h.div(form.minAge > 0 ? [h.Class("mb-6")] : [], [
                  h.h3(
                    [h.Class("font-semibold mb-2 text-foreground-secondary")],
                    [t("About this session")]
                  ),
                  h.div([
                    h.Class(
                      "prose prose-sm dark:prose-invert max-w-none text-foreground prose-p:text-foreground"
                    ),
                    h.InnerHTML(model.descriptionHtml),
                  ]),
                ]),
              ]),
          ...(form.minAge > 0
            ? [
                h.div(
                  [h.Class("grid grid-cols-2 gap-3")],
                  [
                    h.div(
                      [
                        h.Class(
                          "bg-warm-100 dark:bg-neutral-800 rounded-xl p-4"
                        ),
                      ],
                      [
                        h.div(
                          [h.Class("text-sm mb-1 text-foreground-muted")],
                          [t("Minimum Age")]
                        ),
                        h.div(
                          [h.Class("font-medium text-foreground")],
                          [`${form.minAge}+ ${t("years")}`]
                        ),
                      ]
                    ),
                  ]
                ),
              ]
            : []),
        ]
      ),
    ]
  );
};

const rowName = (row: EnrollmentRow, t: Translator["t"]) => {
  if (!row.isViewer) {
    return row.person.name;
  }

  return row.person.name === "" ? t("You") : `${t("You")} · ${row.person.name}`;
};

const personRow = (
  options: Readonly<{
    model: EnrollPageModel;
    row: EnrollmentRow;
    hint: SeatHint;
    t: Translator["t"];
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
): Html => {
  const { row, t } = options;
  const checked = options.model.included.includes(row.userId);
  const nameId = `enroll-name-${row.userId}`;
  const includeId = `enroll-include-${row.userId}`;

  const face = options.model.avatars.find(
    (entry) => entry.userId === row.userId
  );

  const hint = options.hint === null ? null : HINT[options.hint];

  return h.li(
    [
      h.DataAttribute("enroll-row", ""),
      h.DataAttribute("current-in", row.checked ? "1" : "0"),
      h.DataAttribute("occupies-seat", row.occupiesSeat ? "1" : "0"),
    ],
    [
      h.label(
        [
          h.Class(
            cx(
              "flex items-center gap-3 px-4 py-3 transition-colors",
              row.disabled
                ? "opacity-60 cursor-not-allowed"
                : "cursor-pointer hover:bg-bg-tertiary"
            )
          ),
        ],
        [
          ...(face === undefined
            ? []
            : [
                avatar(
                  {
                    person: face.avatar,
                    size: "size-10",
                    translator: options.translator,
                  },
                  h
                ),
              ]),
          h.span(
            [h.Class("min-w-0 flex-1")],
            [
              h.span(
                [
                  h.Class("block font-medium truncate"),
                  h.Id(nameId),
                  h.DataAttribute("ph-mask", ""),
                ],
                [rowName(row, t)]
              ),
              h.span(
                [
                  h.Class(
                    "flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-0.5 text-xs text-foreground-secondary"
                  ),
                ],
                [
                  h.span(
                    [h.Class("inline-flex items-center gap-1.5")],
                    [
                      h.span([
                        h.Class(
                          cx(
                            "w-1.5 h-1.5 rounded-full shrink-0",
                            DOT[row.badge.variant]
                          )
                        ),
                      ]),
                      t(row.badge.label),
                    ]
                  ),
                  ...(row.needsApproval && !checked
                    ? [
                        h.span(
                          [h.Class("text-foreground-muted")],
                          [t("needs their approval")]
                        ),
                      ]
                    : []),
                  ...(row.disabled &&
                  row.reason !== "" &&
                  row.reason !== row.badge.label
                    ? [
                        h.span(
                          [h.Class("text-foreground-muted")],
                          [t(row.reason)]
                        ),
                      ]
                    : []),
                  h.span(
                    [
                      h.DataAttribute("seat-hint", ""),
                      h.Class(cx("font-medium", hint?.tone)),
                      h.AriaLive("polite"),
                      ...(hint === null ? [h.Hidden(true)] : []),
                    ],
                    hint === null ? [] : [t(hint.msgid)]
                  ),
                ]
              ),
            ]
          ),
          h.span([h.Id(includeId), h.Class("sr-only")], [t("Include")]),
          checkboxInput(
            {
              attributes: [
                h.AriaLabelledBy(`${includeId} ${nameId}`),
                h.OnClick(EnrollPageMessage.ToggledPerson({ userId: row.userId })),
              ],
              checked,
              disabled: row.disabled,
              name: `user_${row.userId}`,
              size: "w-5 h-5",
              value: "include",
            },
            h
          ),
        ]
      ),
    ]
  );
};

export const enrollPageView = defineView<EnrollPageModel, Message, PageInputs>(
  (model, inputs, h) => {
    const context = pageContextOf(inputs.shell);
    const { translator } = context;
    const { t } = translator;
    const { form } = model;
    const preview = enrollPreview(model);

    const warnings =
      form.shadowbanWarnings.length === 0
        ? []
        : [
            h.div(
              [h.Class("mb-6")],
              [
                h.h2(
                  [h.Class("font-semibold mb-3")],
                  [t("Players you shadowbanned are already signed up here")]
                ),
                h.ul(
                  [h.Class("flex flex-col gap-2")],
                  form.shadowbanWarnings.map((warning, index) =>
                    h.li(
                      [h.Class("flex flex-wrap items-center gap-2")],
                      [
                        h.span(
                          [
                            h.Class("font-medium"),
                            h.DataAttribute("ph-mask", ""),
                          ],
                          [warning.person.name]
                        ),
                        h.span(
                          [h.Class("text-sm text-foreground-muted")],
                          [
                            t("shadowbanned on %(date)s", {
                              date: model.shadowbanDates[index] ?? "",
                            }),
                          ]
                        ),
                      ]
                    )
                  )
                ),
              ]
            ),
          ];

    const guestsBlock =
      form.guests === null
        ? []
        : [
            h.div(
              [
                h.Class(
                  "border-t border-border px-4 py-3 flex items-center justify-between gap-3"
                ),
              ],
              [
                h.label(
                  [h.For("id_guests"), h.Class("min-w-0")],
                  [
                    h.span(
                      [h.Class("block text-sm font-medium")],
                      [t("Guests without an account")]
                    ),
                  ]
                ),
                h.span(
                  [h.Class("shrink-0")],
                  [
                    h.input([
                      h.Type("number"),
                      h.Id("id_guests"),
                      h.Name("guests"),
                      h.Min("0"),
                      h.Max(String(form.guests.max)),
                      h.Value(model.guests),
                      h.Class(
                        "w-20 px-3 py-2 text-sm rounded-lg border border-border bg-bg-secondary text-foreground tabular-nums"
                      ),
                      h.OnInput((value) =>
                        EnrollPageMessage.ChangedGuests({ value })
                      ),
                    ]),
                  ]
                ),
              ]
            ),
          ];

    return h.div(
      [h.Class("max-w-5xl mx-auto w-full")],
      [
        h.div(
          [
            h.Class(
              "grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-10 items-start"
            ),
          ],
          [
            sessionCard(model, translator, h),
            h.div(
              [h.Id("enrollment")],
              [
                ...warnings,
                h.form(
                  [
                    h.Method("post"),
                    h.OnSubmit(EnrollPageMessage.SubmittedEnrollments()),
                  ],
                  [
                    h.div(
                      [
                        h.Class(
                          "rounded-2xl border border-border bg-bg-secondary overflow-hidden shadow-xl"
                        ),
                        h.DataAttribute("enroll-preview", ""),
                        h.DataAttribute(
                          "seats-left",
                          String(form.seats.seatsLeft)
                        ),
                      ],
                      [
                        h.div(
                          [h.Class("px-4 pt-4 pb-3")],
                          [
                            h.h2(
                              [h.Class("text-lg font-semibold")],
                              [t("Who should be in this session?")]
                            ),
                          ]
                        ),
                        h.ul(
                          [
                            h.Class(
                              "divide-y divide-border border-t border-border"
                            ),
                          ],
                          form.rows.map((row) =>
                            personRow(
                              {
                                hint: preview.hints.get(row.userId) ?? null,
                                model,
                                row,
                                t,
                                translator,
                              },
                              h
                            )
                          )
                        ),
                        ...guestsBlock,
                        h.div(
                          [
                            h.Class(
                              "border-t border-border px-4 py-3 flex items-center justify-between gap-3"
                            ),
                          ],
                          [
                            h.a(
                              [
                                h.Href(model.eventUrl),
                                h.Class(
                                  "inline-flex items-center gap-1.5 text-sm text-foreground-muted hover:text-foreground"
                                ),
                              ],
                              [
                                icon(arrowLeftMini, { class: "w-4 h-4" }, h),
                                t("Back to event"),
                              ]
                            ),
                            h.span(
                              [
                                h.DataAttribute("enroll-tally", ""),
                                h.AriaHidden(true),
                                h.Class(
                                  "inline-flex items-center gap-x-2.5 text-xs text-foreground-muted tabular-nums"
                                ),
                                ...(preview.seated + preview.waiting === 0
                                  ? [h.Hidden(true)]
                                  : []),
                              ],
                              [
                                h.span(
                                  [h.Class("inline-flex items-center gap-1")],
                                  [
                                    icon(
                                      usersMini,
                                      { class: "w-3.5 h-3.5" },
                                      h
                                    ),
                                    h.span(
                                      [h.Class("font-medium")],
                                      [String(preview.seated)]
                                    ),
                                  ]
                                ),
                                h.span(
                                  [h.Class("inline-flex items-center gap-1")],
                                  [
                                    icon(
                                      clockMini,
                                      { class: "w-3.5 h-3.5" },
                                      h
                                    ),
                                    h.span(
                                      [h.Class("font-medium")],
                                      [String(preview.waiting)]
                                    ),
                                  ]
                                ),
                              ]
                            ),
                            h.button(
                              [
                                h.Type("submit"),
                                h.Class("btn btn-primary"),
                                h.DataAttribute("enroll-cta", ""),
                                ...(model.submitting
                                  ? [h.AriaDisabled(true)]
                                  : []),
                              ],
                              [t(preview.ctaLabel)]
                            ),
                          ]
                        ),
                      ]
                    ),
                  ]
                ),
                h.p(
                  [h.Class("mt-3 text-center text-xs text-foreground-muted")],
                  [
                    h.a(
                      [
                        h.Href(model.partiesUrl),
                        h.Class(
                          "underline underline-offset-2 hover:text-foreground"
                        ),
                      ],
                      [t("Manage companions in your profile settings")]
                    ),
                  ]
                ),
              ]
            ),
          ]
        ),
      ]
    );
  }
);
