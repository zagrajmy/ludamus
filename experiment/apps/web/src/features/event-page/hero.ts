import type { Html, HtmlBuilder } from "foldkit/html";

import type { StatusPill } from "../../client/event-page/flags.js";
import { EventPageMessage } from "../../client/event-page/message.js";
import type { EventPageModel } from "../../client/event-page/model.js";
import { linkButton } from "../../ui/button.js";
import { cx } from "../../ui/cx.js";
import { icon } from "../../ui/icon.js";
import type { IconData } from "../../ui/icon.js";
import {
  arrowDownTrayMini,
  calendarDaysMini,
  checkCircleMini,
  clockMini,
  informationCircleMini,
  lightBulbMini,
  mapMini,
  mapPinMini,
  printerMini,
  queueListMini,
  userPlusMini,
} from "../../ui/icons.js";
import { actionDropdown, menuLink } from "../../ui/menu.js";
import type { PageContext } from "../page-context.js";

type H = HtmlBuilder<EventPageMessage>;

const pillIcons: Readonly<Record<string, IconData>> = {
  "check-circle": checkCircleMini,
  clock: clockMini,
  "light-bulb": lightBulbMini,
  "user-plus": userPlusMini,
};

const statusPill = (pill: StatusPill, h: H) =>
  h.div(
    [
      h.Key(pill.label),
      h.Class(
        cx(
          "inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium",
          pill.classes
        )
      ),
    ],
    [
      pill.icon === "live"
        ? h.span([h.Class("w-2 h-2 bg-teal-500 rounded-full live-dot")], [])
        : icon(pillIcons[pill.icon] ?? clockMini, { class: "w-4 h-4" }, h),
      pill.label,
    ]
  );

const heroTools = (
  options: Readonly<{ mapsUrl: string; printUrl: string }>,
  context: PageContext,
  h: H
) => {
  const tool = (href: string, label: string, glyph: IconData) =>
    h.a(
      [
        h.Href(href),
        h.Class(
          "icon-btn shrink-0 justify-center overflow-hidden size-12 rounded-2xl"
        ),
        h.Title(label),
      ],
      [
        icon(glyph, { class: "size-5" }, h),
        h.span([h.Class("sr-only")], [label]),
      ]
    );

  return h.div(
    [h.Class("flex gap-1 flex-col max-sm:basis-full sm:flex-row")],
    [
      tool(
        options.printUrl,
        context.translator.t("Print the program"),
        printerMini
      ),
      options.mapsUrl === ""
        ? h.empty
        : tool(options.mapsUrl, context.translator.t("Venue maps"), mapMini),
    ]
  );
};

const datesBlock = (model: EventPageModel, context: PageContext, h: H) => {
  const { dates } = model.hero;

  if (dates.isSameDay) {
    return h.div(
      [h.Class("text-box-trim-both"), h.DataAttribute("event-dates", "")],
      [
        h.div(
          [h.Class("font-medium leading-none text-foreground")],
          [h.time([h.Datetime(dates.startIso)], [dates.startDay])]
        ),
        h.div(
          [h.Class("text-foreground-muted leading-none mt-0.5 tabular-nums")],
          [
            h.time([h.Datetime(dates.startIso)], [dates.startTime]),
            "–",
            h.time([h.Datetime(dates.endIso)], [dates.endTime]),
          ]
        ),
      ]
    );
  }

  return h.div(
    [h.Class("text-box-trim-both"), h.DataAttribute("event-dates", "")],
    [
      h.div(
        [h.Class("font-medium leading-tight text-foreground")],
        [
          h.time(
            [h.Class("whitespace-nowrap"), h.Datetime(dates.startIso)],
            [
              `${dates.startShort}, `,
              h.span(
                [h.Class("text-foreground-muted tabular-nums")],
                [dates.startTime]
              ),
            ]
          ),
          " ",
          h.span([h.AriaHidden(true)], ["–"]),
          h.span(
            [h.Class("sr-only")],
            [context.translator.tc("date range", "to")]
          ),
          " ",
          h.time(
            [h.Class("whitespace-nowrap"), h.Datetime(dates.endIso)],
            [
              `${dates.endShort}, `,
              h.span(
                [h.Class("text-foreground-muted tabular-nums")],
                [dates.endTime]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const calendarMenu = (model: EventPageModel, context: PageContext, h: H) =>
  actionDropdown(
    {
      align: "left",
      hover: true,
      id: "event-calendar-menu",
      isOpen: model.isCalendarMenuOpen,
      items: [
        h.a(
          [
            h.Key("google"),
            h.Href(model.hero.googleCalendarUrl),
            h.Target("_blank"),
            h.Rel("noopener"),
            h.Class(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-bg-tertiary text-foreground-secondary"
            ),
          ],
          [
            icon(calendarDaysMini, { class: "w-4 h-4 opacity-60" }, h),
            context.translator.t("Google Calendar"),
          ]
        ),
        menuLink(
          {
            href: model.hero.icsUrl,
            icon: arrowDownTrayMini,
            key: "ics",
            label: context.translator.t("Other calendars (.ics)"),
          },
          h
        ),
      ],
      label: context.translator.t("Add to calendar"),
      onToggle: (isOpen) => EventPageMessage.ToggledCalendarMenu({ isOpen }),
      trigger: [
        h.div(
          [
            h.Class(
              "w-8 h-8 bg-coral-100 dark:bg-coral-900/30 rounded-lg flex items-center justify-center shrink-0"
            ),
          ],
          [icon(calendarDaysMini, { class: "w-4 h-4 text-coral-600" }, h)]
        ),
        datesBlock(model, context, h),
      ],
      triggerClass: "flex items-center gap-2 text-left",
    },
    h
  );

const facts = (model: EventPageModel, context: PageContext, h: H) => {
  const { hero } = model;
  const { translator } = context;
  const viewOnMap = translator.t("View on map ↗");

  return h.div(
    [
      h.Class(
        "flex flex-col items-start gap-2 text-sm sm:gap-3 lg:col-start-2 lg:row-start-1 lg:row-span-3"
      ),
    ],
    [
      calendarMenu(model, context, h),
      h.div(
        [h.Class("flex items-center gap-2")],
        [
          h.div(
            [
              h.Class(
                "w-8 h-8 bg-bg-tertiary rounded-lg flex items-center justify-center"
              ),
            ],
            [icon(queueListMini, { class: "w-4 h-4 text-foreground-muted" }, h)]
          ),
          h.div(
            [
              h.Class(
                "font-medium leading-none text-foreground tabular-nums whitespace-nowrap"
              ),
            ],
            [
              `${hero.scheduledCount} `,
              h.span(
                [h.Class("font-normal text-foreground-muted")],
                [
                  translator.n("Session", "Sessions", hero.scheduledCount, {
                    counter: hero.scheduledCount,
                  }),
                ]
              ),
            ]
          ),
        ]
      ),
      hero.addressLines.length === 0
        ? h.empty
        : h.a(
            [
              h.Href(
                `https://www.google.com/maps/search/?api=1&query=${hero.addressQuery}`
              ),
              h.Target("_blank"),
              h.Rel("noopener"),
              h.Title(viewOnMap),
              h.Class("group flex items-start gap-2"),
            ],
            [
              h.div(
                [
                  h.Class(
                    "w-8 h-8 bg-teal-100 dark:bg-teal-900/30 rounded-lg flex items-center justify-center shrink-0"
                  ),
                ],
                [icon(mapPinMini, { class: "w-4 h-4 text-teal-600" }, h)]
              ),
              h.div(
                [
                  h.Class(
                    "font-medium leading-snug pt-1.5 text-foreground group-hover:underline decoration-dotted underline-offset-4"
                  ),
                ],
                [
                  ...hero.addressLines.flatMap((line, index) =>
                    index === 0 ? [line] : [h.br([]), line]
                  ),
                  h.span([h.Class("sr-only")], [viewOnMap]),
                ]
              ),
            ]
          ),
    ]
  );
};

const ctas = (model: EventPageModel, context: PageContext, h: H) =>
  h.div(
    [
      h.Class(
        "flex flex-wrap gap-3 [&>.btn]:whitespace-nowrap max-sm:[&>.btn]:grow max-sm:[&>.btn]:basis-44 lg:row-start-3 print:hidden"
      ),
    ],
    [
      linkButton(
        {
          href: "#schedule-region",
          size: "lg",
          text: context.translator.t("View the program"),
        },
        h
      ),
      model.hasEnrollableSessions && !model.hero.isEnded
        ? linkButton(
            {
              href: "?enrollment=1#schedule-region",
              size: "lg",
              text: context.translator.t("Sign up for sessions"),
              variant: "secondary",
            },
            h
          )
        : h.empty,
      model.hero.coverUrl === ""
        ? heroTools(
            { mapsUrl: model.hero.mapsUrl, printUrl: model.hero.printUrl },
            context,
            h
          )
        : h.empty,
    ]
  );

export const eventHero = (
  model: EventPageModel,
  context: PageContext,
  h: H
): Html =>
  h.div(
    [
      h.Class(
        "relative mb-6 bg-bg-secondary max-sm:breakout sm:mb-8 sm:rounded-3xl sm:shadow-(--shadow-elevated) print:mb-4 print:shadow-none print:bg-transparent"
      ),
      h.DataAttribute("event-hero", ""),
    ],
    [
      model.hero.coverUrl === ""
        ? h.empty
        : h.div(
            [
              h.Class("relative sm:h-72 print:hidden"),
              h.DataAttribute("event-cover", ""),
            ],
            [
              h.img([
                h.Src(model.hero.coverUrl),
                h.Alt(
                  context.translator.t("Cover image for %(event_name)s", {
                    event_name: model.hero.name,
                  })
                ),
                h.Class(
                  "block h-auto w-full sm:h-full sm:rounded-t-3xl sm:object-cover"
                ),
              ]),
              h.div(
                [h.Class("absolute right-4 sm:right-8 top-4 sm:top-8")],
                [
                  heroTools(
                    {
                      mapsUrl: model.hero.mapsUrl,
                      printUrl: model.hero.printUrl,
                    },
                    context,
                    h
                  ),
                ]
              ),
            ]
          ),
      h.div(
        [h.Class("px-4 py-6 sm:p-8 print:p-0")],
        [
          h.div(
            [
              h.Class(
                "flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6"
              ),
            ],
            [
              h.div(
                [
                  h.Class(
                    "flex-1 grid gap-y-5 lg:grid-cols-[1fr_auto] lg:gap-x-8"
                  ),
                ],
                [
                  h.div(
                    [h.Class("flex items-center flex-wrap gap-x-3 gap-y-2")],
                    [
                      h.h1(
                        [
                          h.Class(
                            "text-3xl sm:text-4xl font-bold text-foreground"
                          ),
                        ],
                        [model.hero.name]
                      ),
                      h.div(
                        [
                          h.Class(
                            "flex flex-wrap items-center gap-2 print:hidden"
                          ),
                        ],
                        model.hero.statusPills.map((pill) =>
                          statusPill(pill, h)
                        )
                      ),
                    ]
                  ),
                  model.hero.descriptionHtml === ""
                    ? h.empty
                    : h.div(
                        [
                          h.Class(
                            "prose prose-lg dark:prose-invert max-w-2xl text-foreground-muted prose-p:text-foreground-muted prose-p:leading-normal prose-li:text-foreground-muted prose-headings:text-foreground-muted"
                          ),
                          h.InnerHTML(model.hero.descriptionHtml),
                        ],
                        []
                      ),
                  facts(model, context, h),
                  ctas(model, context, h),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );

export const enrollmentNotices = (
  model: EventPageModel,
  h: H
): readonly Html[] =>
  model.enrollmentNotices.map((notice) =>
    h.p(
      [
        h.Key(notice),
        h.Class("mb-3 flex gap-1.5 text-sm text-info-text print:hidden"),
      ],
      [
        icon(informationCircleMini, { class: "size-4 shrink-0 mt-0.5" }, h),
        h.span(
          [],
          notice
            .split("\n")
            .flatMap((line, index) => (index === 0 ? [line] : [h.br([]), line]))
        ),
      ]
    )
  );
