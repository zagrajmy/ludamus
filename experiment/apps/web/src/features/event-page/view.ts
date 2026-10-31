import { Option } from "effect";
import type { HtmlBuilder } from "foldkit/html";
import { defineView } from "foldkit/submodel";

import { isFiltering } from "../../client/event-page/filters.js";
import type { EventPageMessage } from "../../client/event-page/message.js";
import type { EventPageModel } from "../../client/event-page/model.js";
import { icon } from "../../ui/icon.js";
import {
  arrowLeftMini,
  checkCircleMini,
  plusMini,
  plusOutline,
} from "../../ui/icons.js";
import { pageContextOf } from "../page-context.js";
import type { PageContext, PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";
import { filterToolbar, noResults } from "./filters.js";
import { enrollmentNotices, eventHero } from "./hero.js";
import { sessionModal } from "./modal.js";
import {
  cardSchedule,
  compactSchedule,
  viewTabs,
  visibleSessions,
} from "./schedule.js";

type H = HtmlBuilder<EventPageMessage>;

export const eventPageTitle = (model: EventPageModel): PageTitle => ({
  name: model.hero.name,
  sphereSuffix: true,
});

const enrolledBanner = (model: EventPageModel, context: PageContext, h: H) =>
  !model.signedIn || model.enrolledSessions.length === 0
    ? h.empty
    : h.div(
        [
          h.Class(
            "mb-6 bg-gradient-to-r from-coral-400 to-coral-500 rounded-2xl p-[2px] print:hidden"
          ),
        ],
        [
          h.div(
            [h.Class("rounded-2xl p-5 bg-bg-secondary")],
            [
              h.div(
                [h.Class("flex flex-col sm:flex-row sm:items-center gap-4")],
                [
                  h.div(
                    [
                      h.Class(
                        "w-12 h-12 bg-coral-100 dark:bg-coral-900/30 rounded-xl flex items-center justify-center shrink-0"
                      ),
                    ],
                    [
                      icon(
                        checkCircleMini,
                        { class: "w-6 h-6 text-coral-600 dark:text-coral-400" },
                        h
                      ),
                    ]
                  ),
                  h.div(
                    [h.Class("flex-1")],
                    [
                      h.h3(
                        [h.Class("font-semibold text-foreground")],
                        [
                          context.translator.n(
                            "You're signed up for %(counter)s session!",
                            "You're signed up for %(counter)s sessions!",
                            model.enrolledSessions.length,
                            { counter: model.enrolledSessions.length }
                          ),
                        ]
                      ),
                      h.ul(
                        [h.Class("text-sm text-foreground-muted")],
                        model.enrolledSessions.map((enrolled) =>
                          h.li(
                            [h.Key(String(enrolled.id))],
                            [
                              h.a(
                                [
                                  h.Href(`?session=${enrolled.id}`),
                                  h.Class(
                                    "font-medium text-foreground underline decoration-dashed decoration-foreground-muted underline-offset-2 hover:decoration-solid"
                                  ),
                                  h.AriaHasPopup("dialog"),
                                  h.AriaControls(`session-${enrolled.id}`),
                                ],
                                [enrolled.title]
                              ),
                              ` · ${enrolled.when}`,
                            ]
                          )
                        )
                      ),
                    ]
                  ),
                ]
              ),
            ]
          ),
        ]
      );

const proposeCta = (model: EventPageModel, context: PageContext, h: H) =>
  model.hero.isProposalActive
    ? h.div(
        [h.Class("mt-12 text-center print:hidden")],
        [
          h.div(
            [
              h.Class(
                "inline-flex flex-col items-center p-8 rounded-3xl border border-border bg-linear-135 from-bg-tertiary to-bg-secondary xl:w-[512px] xl:px-16"
              ),
            ],
            [
              h.div(
                [
                  h.Class(
                    "w-16 h-16 bg-coral-100 dark:bg-coral-900/30 rounded-2xl flex items-center justify-center mb-4 rotate-3"
                  ),
                ],
                [icon(plusOutline, { class: "w-8 h-8 text-coral-500" }, h)]
              ),
              h.h3(
                [h.Class("text-xl font-bold mb-2 text-foreground")],
                [context.translator.t("Want to host a session?")]
              ),
              h.p(
                [h.Class("mb-4 max-w-md text-foreground-muted")],
                context.translator
                  .t(
                    'Got a game you\'re dying to play? <br class="max-xl:hidden" /> Propose your own session and find players!'
                  )
                  .split('<br class="max-xl:hidden" />')
                  .flatMap((part, index) =>
                    index === 0
                      ? [part.trim()]
                      : [h.br([h.Class("max-xl:hidden")]), part.trim()]
                  )
              ),
              h.a(
                [
                  h.Href(model.hero.proposeUrl),
                  h.Class("btn btn-primary text-base"),
                ],
                [context.translator.t("Propose a session")]
              ),
            ]
          ),
        ]
      )
    : h.empty;

const scheduleRegion = (model: EventPageModel, context: PageContext, h: H) => {
  const visible = visibleSessions(model);
  const hasSessions = model.sessions.length > 0;

  const isEmpty =
    isFiltering(model.filters) && visible.size === 0 && hasSessions;

  const schedule =
    model.layout._tag === "Cards"
      ? cardSchedule(
          {
            context,
            days: model.layout.days,
            model,
            slotCount: model.layout.slotCount,
            visible,
          },
          h
        )
      : compactSchedule(
          {
            context,
            days: model.layout.days,
            grid: model.layout.rooms,
            model,
            visible,
          },
          h
        );

  return h.div(
    [h.Id("schedule-region"), h.Class("scroll-mt-24")],
    [
      h.div(
        [h.Class("flex items-center justify-between mb-3")],
        [
          h.div(
            [h.Class("flex items-center gap-3")],
            [
              h.h2(
                [h.Class("text-xl font-bold text-foreground")],
                [context.translator.t("Sessions")]
              ),
              h.span(
                [
                  h.Class(
                    "inline-flex items-center px-2.5 py-0.5 rounded-full text-base translate-y-[.5px] font-semibold bg-coral-100 dark:bg-coral-900/30 text-coral-700 dark:text-coral-400"
                  ),
                ],
                [String(model.sessions.length)]
              ),
            ]
          ),
          model.hero.isProposalActive
            ? h.a(
                [
                  h.Href(model.hero.proposeUrl),
                  h.Class("btn btn-primary text-sm print:hidden"),
                ],
                [
                  icon(plusMini, { class: "w-4 h-4" }, h),
                  ` ${context.translator.t("Propose Session")}`,
                ]
              )
            : h.empty,
        ]
      ),
      ...(hasSessions
        ? [
            filterToolbar(
              { context, model, viewTabs: viewTabs(model, context, h) },
              h
            ),
            noResults({ context, isShown: isEmpty }, h),
            schedule,
          ]
        : []),
    ]
  );
};

export const eventPageView = defineView<
  EventPageModel,
  EventPageMessage,
  PageInputs
>((model, inputs, h) => {
  const context = pageContextOf(inputs.shell);

  const openSession = Option.flatMap(model.shownSession, (id) =>
    Option.fromNullishOr(model.sessions.find((session) => session.id === id))
  );

  return h.div(
    [],
    [
      eventHero(model, context, h),
      ...enrollmentNotices(model, h),
      enrolledBanner(model, context, h),
      scheduleRegion(model, context, h),
      proposeCta(model, context, h),
      sessionModal({ context, model, session: openSession }, h),
      model.hero.isUnlisted
        ? h.empty
        : h.div(
            [h.Class("mt-8 print:hidden")],
            [
              h.a(
                [h.Href("/"), h.Class("btn btn-secondary")],
                [
                  icon(arrowLeftMini, { class: "w-4 h-4" }, h),
                  ` ${context.translator.t("Back to Events")}`,
                ]
              ),
            ]
          ),
      h.a(
        [
          h.Id("event-print-link"),
          h.DataAttribute("event-print", ""),
          h.Href(model.hero.printUrl),
          h.Hidden(true),
        ],
        [context.translator.t("Print-ready schedule")]
      ),
    ]
  );
});
