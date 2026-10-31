import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";

import { EnrollmentActions } from "../../client/event-page/enrollment-slot.js";
import type {
  RosterEntry,
  SessionView,
} from "../../client/event-page/flags.js";
import { EventPageMessage } from "../../client/event-page/message.js";
import type { EventPageModel } from "../../client/event-page/model.js";
import { avatar } from "../../ui/avatar.js";
import { cx } from "../../ui/cx.js";
import { icon } from "../../ui/icon.js";
import {
  arrowRightOnRectangleMini,
  calendarDaysMini,
  clockMini,
  informationCircleMini,
  mapPinMini,
  usersMini,
  xMarkMini,
} from "../../ui/icons.js";
import type { PageContext } from "../page-context.js";
import {
  enrollmentFooterActions,
  hasEnrollmentFooter,
  seatNote,
} from "./enrollment-footer.js";
import { locationCrumbs } from "./session-card.js";

type H = HtmlBuilder<EventPageMessage>;

const fact = (
  glyph: typeof clockMini,
  children: readonly (Html | string)[],
  h: H
) =>
  h.span(
    [h.Class("inline-flex items-center gap-1.5 min-w-0")],
    [
      icon(glyph, { class: "size-4 shrink-0 text-foreground-muted/80" }, h),
      ...children,
    ]
  );

const facts = (
  model: EventPageModel,
  session: SessionView,
  context: PageContext,
  h: H
) => {
  const { translator } = context;

  return h.div(
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
        [
          Option.match(session.timing, {
            onNone: () => h.empty,
            onSome: (timing) =>
              fact(calendarDaysMini, [h.span([], [timing.when])], h),
          }),
          session.crumbs.length === 0
            ? h.empty
            : h.span(
                [
                  h.Class("flex items-center gap-1.5 min-w-0"),
                  h.DataAttribute("morph", "venue"),
                ],
                [
                  icon(
                    mapPinMini,
                    {
                      class:
                        "size-4 shrink-0 text-foreground-muted/80 max-[400px]:hidden",
                    },
                    h
                  ),
                  locationCrumbs({ eventSlug: model.hero.slug, session }, h),
                ]
              ),
          session.durationLabel === ""
            ? h.empty
            : fact(
                clockMini,
                [
                  h.span(
                    [h.Class("sr-only")],
                    [`${translator.t("Duration")}:`]
                  ),
                  session.durationLabel,
                ],
                h
              ),
          session.takesEnrollment
            ? fact(
                usersMini,
                [
                  h.span(
                    [h.Class("sr-only")],
                    [`${translator.t("Capacity")}:`]
                  ),
                  h.span(
                    [
                      h.Class(
                        cx(
                          "font-medium tabular-nums",
                          session.isFull
                            ? "text-coral-700 dark:text-coral-400"
                            : "text-teal-700 dark:text-teal-400"
                        )
                      ),
                    ],
                    [`${session.enrolledCount}/${session.effectiveLimit}`]
                  ),
                  ...(session.waitingCount > 0
                    ? [
                        h.span(
                          [
                            h.Class("text-foreground-muted/70"),
                            h.AriaHidden(true),
                          ],
                          ["·"]
                        ),
                        h.span(
                          [h.Class("text-warning-text")],
                          [
                            translator.n(
                              "%(counter)s waiting",
                              "%(counter)s waiting",
                              session.waitingCount,
                              { counter: session.waitingCount }
                            ),
                          ]
                        ),
                      ]
                    : []),
                ],
                h
              )
            : h.empty,
          session.minAge > 0
            ? h.span(
                [
                  h.Class(
                    cx(
                      "tabular-nums",
                      session.minAge >= 18 &&
                        "font-medium text-coral-700 dark:text-coral-400"
                    )
                  ),
                  h.Title(
                    `${translator.t("Minimum age")}: ${session.minAge} ${translator.t("years")}`
                  ),
                ],
                [
                  h.span(
                    [h.Class("sr-only")],
                    [`${translator.t("Minimum age")}:`]
                  ),
                  `${session.minAge}+`,
                ]
              )
            : h.empty,
        ]
      ),
    ]
  );
};

const info = (
  model: EventPageModel,
  session: SessionView,
  context: PageContext,
  h: H
) =>
  h.div(
    [h.DataAttribute("session-info", "")],
    [
      session.host === ""
        ? h.empty
        : h.div(
            [h.Class("flex items-center gap-3 mb-4 flex-wrap text-sm")],
            [
              h.span(
                [
                  h.Class("shrink-0 relative"),
                  h.DataAttribute("morph", "avatar"),
                ],
                [
                  avatar(
                    {
                      person: session.presenter,
                      size: "size-9",
                      translator: context.translator,
                    },
                    h
                  ),
                ]
              ),
              h.div(
                [
                  h.Class(
                    "flex flex-1 items-center gap-x-3 gap-y-0.5 flex-wrap min-w-0"
                  ),
                ],
                [
                  h.div(
                    [
                      h.Class("font-medium text-foreground"),
                      h.DataAttribute("morph", "host"),
                      h.DataAttribute("ph-mask", ""),
                    ],
                    [session.presenter.name]
                  ),
                ]
              ),
            ]
          ),
      facts(model, session, context, h),
      session.descriptionHtml === ""
        ? h.empty
        : h.div(
            [h.Class("mb-6")],
            [
              h.h3(
                [
                  h.Class(
                    "text-sm font-semibold mb-2 text-foreground-secondary"
                  ),
                  h.DataAttribute("morph", "desc-label"),
                ],
                [context.translator.t("About this session")]
              ),
              h.div(
                [
                  h.Class(
                    "prose prose-sm dark:prose-invert max-w-none text-foreground prose-p:text-foreground prose-p:leading-5 prose-li:leading-5"
                  ),
                  h.DataAttribute("session-description", ""),
                  h.InnerHTML(session.descriptionHtml),
                ],
                []
              ),
            ]
          ),
      session.fieldAnswers.length === 0
        ? h.empty
        : h.div(
            [h.Class("mb-6"), h.DataAttribute("session-fields", "")],
            [
              h.div(
                [h.Class("space-y-4")],
                session.fieldAnswers.map((answer) =>
                  h.div(
                    [h.Key(answer.name)],
                    [
                      h.h4(
                        [
                          h.Class(
                            "text-sm font-semibold mb-1 text-foreground-secondary"
                          ),
                        ],
                        [
                          Option.match(answer.icon, {
                            onNone: () => h.empty,
                            onSome: (shape) =>
                              icon(shape, { class: "w-4 h-4 inline mr-1" }, h),
                          }),
                          answer.name,
                        ]
                      ),
                      h.div(
                        [h.Class("flex flex-wrap gap-1.5")],
                        answer.values.map((value) =>
                          h.span(
                            [
                              h.Key(value),
                              h.Class(
                                "inline-flex items-center gap-1 rounded-2xl font-medium px-2.5 py-1 text-sm bg-warm-200/80 dark:bg-neutral-700 text-warm-700 dark:text-neutral-300"
                              ),
                            ],
                            [value]
                          )
                        )
                      ),
                    ]
                  )
                )
              ),
            ]
          ),
    ]
  );

const rosterRow = (entry: RosterEntry, context: PageContext, h: H) =>
  h.div(
    [
      h.Class(
        "flex items-center justify-between p-3 rounded-xl bg-warm-100 dark:bg-neutral-800"
      ),
      ...(entry.status === "waiting"
        ? [h.DataAttribute("waiting-list-row", "")]
        : []),
    ],
    [
      h.div(
        [h.Class("flex items-center gap-3")],
        [
          entry.status === "waiting"
            ? h.span(
                [
                  h.Class(
                    "w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold bg-warning-light text-warning-text"
                  ),
                  h.DataAttribute("waiting-position", ""),
                ],
                []
              )
            : avatar(
                {
                  person: entry.person,
                  size: "size-8",
                  translator: context.translator,
                },
                h
              ),
          h.span(
            [
              h.Class("font-medium text-foreground"),
              h.DataAttribute("ph-mask", ""),
            ],
            [entry.person.name]
          ),
        ]
      ),
      entry.status === "waiting"
        ? h.span(
            [h.Class("text-xs text-foreground-muted")],
            [entry.createdLabel]
          )
        : h.empty,
    ]
  );

const participantsPanel = (
  session: SessionView,
  isActive: boolean,
  context: PageContext,
  h: H
) => {
  const { translator } = context;
  const roster = Option.getOrElse(session.roster, () => []);
  const confirmed = roster.filter((entry) => entry.status === "confirmed");
  const waiting = roster.filter((entry) => entry.status === "waiting");

  return h.div(
    [
      h.Id(`participants-${session.id}`),
      h.Role("tabpanel"),
      h.Class("tab-panel scrollview-fade scrollview-fade-y-16 px-6 py-4"),
      ...(isActive ? [h.DataAttribute("active", "")] : [h.Inert(true)]),
    ],
    [
      session.enrolledCount > 0
        ? h.h3(
            [h.Class("font-semibold mb-3 text-foreground-secondary")],
            [
              `${translator.t("Enrolled")} (${session.enrolledCount}/${session.effectiveLimit})`,
            ]
          )
        : h.empty,
      h.div(
        [h.Class("space-y-2 mb-6")],
        confirmed.map((entry) => rosterRow(entry, context, h))
      ),
      waiting.length > 0
        ? h.h3(
            [h.Class("font-semibold mb-3 text-foreground-secondary")],
            [translator.t("Waiting List")]
          )
        : h.empty,
      h.div(
        [h.Class("space-y-2")],
        waiting.map((entry) => rosterRow(entry, context, h))
      ),
      roster.length === 0 && session.enrolledCount === 0
        ? h.div(
            [
              h.Class(
                "flex items-center justify-center p-4 border-2 border-dashed border-border rounded-xl"
              ),
            ],
            [
              h.span(
                [h.Class("text-sm text-foreground-muted")],
                [translator.t("No participants enrolled yet.")]
              ),
            ]
          )
        : h.empty,
    ]
  );
};

const footer = (
  model: EventPageModel,
  session: SessionView,
  context: PageContext,
  h: H
) =>
  EnrollmentActions.match(model.enrollment, {
    Loading: () => h.empty,
    NotAvailable: () => h.empty,
    Seat: ({ state }) =>
      hasEnrollmentFooter(state)
        ? h.div(
            [
              h.Class(
                "modal-footer-lg px-6 pt-4 flex items-center justify-between gap-2 border-t border-border shrink-0 bg-bg-secondary"
              ),
              h.DataAttribute("morph", "footer"),
              h.DataAttribute("session-footer", String(session.id)),
            ],
            [
              h.div([h.Class("btn-strip-compact")], []),
              h.div(
                [h.Class("flex items-center gap-2")],
                [enrollmentFooterActions(state, context.translator, h)]
              ),
            ]
          )
        : h.empty,
    SignInToEnroll: ({ href }) =>
      h.div(
        [
          h.Class(
            "modal-footer-lg px-6 pt-4 flex items-center justify-between gap-2 border-t border-border shrink-0 bg-bg-secondary"
          ),
          h.DataAttribute("morph", "footer"),
          h.DataAttribute("session-footer", String(session.id)),
        ],
        [
          h.div([h.Class("btn-strip-compact")], []),
          h.div(
            [h.Class("flex items-center gap-2")],
            [
              h.a(
                [h.Href(href), h.Class("btn btn-primary text-sm")],
                [
                  icon(arrowRightOnRectangleMini, { class: "w-4 h-4" }, h),
                  ` ${context.translator.t("Login to Enroll")}`,
                ]
              ),
            ]
          ),
        ]
      ),
  });

export const sessionModal = (
  options: Readonly<{
    context: PageContext;
    model: EventPageModel;
    session: Option.Option<SessionView>;
  }>,
  h: H
): Html => {
  const { context, model } = options;

  const content = Option.match(options.session, {
    onNone: () => [],
    onSome: (session: SessionView) => {
      const showRoster = session.takesEnrollment;

      return [
        h.div(
          [
            h.Class(
              "px-6 py-4 border-b border-border flex items-center justify-between shrink-0"
            ),
          ],
          [
            h.h3(
              [
                h.Id(`session-${session.id}-title`),
                h.Class("text-lg font-semibold text-foreground"),
                h.DataAttribute("morph", "title"),
              ],
              [session.title]
            ),
            h.button(
              [
                h.Type("button"),
                h.DataAttribute("modal-close", `session-${session.id}`),
                h.AriaLabel(context.translator.t("Close")),
                h.Class(
                  "size-11 flex items-center justify-center rounded-lg hover:bg-warm-200 dark:hover:bg-neutral-700 text-foreground-muted"
                ),
                h.OnClick(EventPageMessage.ClosedSessionDialog()),
              ],
              [icon(xMarkMini, { class: "w-5 h-5" }, h)]
            ),
          ]
        ),
        h.div(
          [
            h.Class("flex-auto min-h-0 flex flex-col overflow-hidden"),
            h.DataAttribute("session-tabs", String(session.id)),
          ],
          [
            showRoster
              ? h.div(
                  [
                    h.Class("tab-list shrink-0 bg-bg-secondary"),
                    h.Role("tablist"),
                    h.DataAttribute("morph", "tabs"),
                  ],
                  [
                    h.button(
                      [
                        h.Type("button"),
                        h.Role("tab"),
                        h.AriaSelected(true),
                        h.AriaControls(`info-${session.id}`),
                        h.Class(
                          "tab-trigger px-4 py-3 text-sm font-medium flex items-center gap-1.5 active:scale-100!"
                        ),
                      ],
                      [
                        icon(informationCircleMini, { class: "w-4 h-4" }, h),
                        ` ${context.translator.t("Information")}`,
                      ]
                    ),
                    h.button(
                      [
                        h.Type("button"),
                        h.Tabindex(-1),
                        h.Role("tab"),
                        h.AriaSelected(false),
                        h.AriaControls(`participants-${session.id}`),
                        h.Class(
                          "tab-trigger px-4 py-3 text-sm font-medium flex items-center gap-1.5 active:scale-100!"
                        ),
                      ],
                      [
                        icon(usersMini, { class: "w-4 h-4" }, h),
                        ` ${context.translator.t("Participants")}`,
                        h.span(
                          [
                            h.Class(
                              "px-1.5 py-0.5 rounded-full text-xs font-semibold bg-coral-100 dark:bg-coral-900/30 text-coral-700 dark:text-coral-400"
                            ),
                          ],
                          [String(session.enrolledCount)]
                        ),
                      ]
                    ),
                  ]
                )
              : h.empty,
            h.div(
              [
                h.Class(
                  "tab-content flex-auto min-h-0 overflow-y-auto [-webkit-overflow-scrolling:touch] text-foreground"
                ),
              ],
              [
                h.div(
                  [
                    h.Id(`info-${session.id}`),
                    ...(showRoster ? [h.Role("tabpanel")] : []),
                    h.Class(
                      "tab-panel scrollview-fade scrollview-fade-y-12 px-6 py-4"
                    ),
                    h.DataAttribute("active", ""),
                  ],
                  [
                    info(model, session, context, h),
                    seatNote(model, session, context, h),
                  ]
                ),
                showRoster
                  ? participantsPanel(session, false, context, h)
                  : h.empty,
              ]
            ),
          ]
        ),
        footer(model, session, context, h),
      ];
    },
  });

  return h.dialog(
    [
      h.Id("session-dialog"),
      h.Class("modal modal-capped max-w-200 w-[calc(100%-0.5rem)]"),
      ...Option.match(options.session, {
        onNone: () => [],
        onSome: (session: SessionView) => [
          h.AriaLabelledBy(`session-${session.id}-title`),
        ],
      }),
      h.OnCancelPreventDefault(EventPageMessage.ClosedSessionDialog()),
    ],
    content
  );
};
