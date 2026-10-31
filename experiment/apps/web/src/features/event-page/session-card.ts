import { Option } from "effect";
import type { Attribute, Html, HtmlBuilder } from "foldkit/html";

import {
  availabilityAt,
  isEnded,
  statusAt,
} from "../../client/event-page/filters.js";
import type { FieldPill, SessionView } from "../../client/event-page/flags.js";
import { EventPageMessage } from "../../client/event-page/message.js";
import type { EventPageModel } from "../../client/event-page/model.js";
import { avatar } from "../../ui/avatar.js";
import { coverStrip } from "../../ui/cover.js";
import { cx } from "../../ui/cx.js";
import { icon } from "../../ui/icon.js";
import { clockMini, mapPinMini } from "../../ui/icons.js";
import type { PageContext } from "../page-context.js";

type H = HtmlBuilder<EventPageMessage>;

export type TileTiming = Readonly<{ endIso: string; startIso: string }>;

const flag = (on: boolean) => (on ? "true" : "false");

export const sessionAttributes = (
  options: Readonly<{
    now: number;
    session: SessionView;
    tile?: TileTiming;
  }>,
  h: H
): readonly Attribute<EventPageMessage>[] => {
  const { now, session } = options;
  const data = (key: string, value: string) => h.DataAttribute(key, value);

  const base = [
    data("title", session.title.toLowerCase()),
    data("session-id", String(session.id)),
    data("host", session.host),
    data("tags", session.tags),
    data("tag-categories", session.tagCategories),
    data("status", statusAt(session, now)),
    data("takes-enrollment", flag(session.takesEnrollment)),
    data("user-enrolled", flag(session.userEnrolled)),
    data("user-waiting", flag(session.userWaiting)),
    data("bookmarked", flag(session.userBookmarked)),
    data("min-age", String(session.minAge)),
    data("venue", session.venueId),
    data("venue-name", session.venueName),
    data("space", session.spaceId),
    data("space-name", session.spaceName),
    data("space-order", session.spaceOrder),
  ];

  return Option.match(session.timing, {
    onNone: () => base,
    onSome: (timing) => [
      ...base,
      data("session-end", timing.sessionEndIso),
      ...(isEnded(session, now) ? [data("ended", "")] : []),
      data("start", options.tile?.startIso ?? timing.startIso),
      data("end", options.tile?.endIso ?? timing.endIso),
      data("day", timing.day),
      data("day-label", timing.dayLabel),
      data("hour", timing.hour),
    ],
  });
};

export const openDetailsLabel = (session: SessionView, context: PageContext) =>
  context.translator.t("Open details for %(title)s", { title: session.title });

export const fieldPill = (pill: FieldPill, h: H) =>
  h.span(
    [
      h.Class(
        "inline-flex min-w-0 items-center gap-1 rounded-2xl font-medium max-w-full bg-warm-200/80 dark:bg-neutral-700 text-warm-700 dark:text-neutral-300 text-sm px-2.5 py-0.5"
      ),
      h.Title(pill.value),
    ],
    [
      Option.match(pill.icon, {
        onNone: () => h.empty,
        onSome: (glyph) =>
          icon(glyph, { class: "size-3.5 shrink-0 opacity-80" }, h),
      }),
      h.span([h.Class("truncate")], [pill.value]),
    ]
  );

export const agePill = (age: number, context: PageContext, h: H) =>
  h.span(
    [
      h.Class(
        cx(
          "px-2.5 py-0.5 rounded-2xl text-sm font-medium max-w-full truncate",
          age >= 18
            ? "bg-coral-100 dark:bg-coral-900/50 text-coral-700 dark:text-coral-300"
            : "bg-warm-200/80 dark:bg-neutral-700 text-warm-700 dark:text-neutral-300"
        )
      ),
      h.Title(
        `${context.translator.t("Minimum age")}: ${age} ${context.translator.t("years")}`
      ),
    ],
    [
      h.span([h.Class("sr-only")], [`${context.translator.t("Minimum age")}:`]),
      h.span([], [`${age}+`]),
    ]
  );

export const tagsCloud = (session: SessionView, context: PageContext, h: H) =>
  session.pills.length === 0 && session.minAge <= 0
    ? h.empty
    : h.div(
        [h.Class("flex flex-wrap gap-1 mt-2 session-tags-cloud items-center")],
        [
          ...session.pills.map((pill) => fieldPill(pill, h)),
          session.minAge > 0 ? agePill(session.minAge, context, h) : h.empty,
          session.overflowPills.length === 0
            ? h.empty
            : h.div(
                [
                  h.Class(
                    "session-tags-more relative inline-flex items-center justify-center pointer-events-auto"
                  ),
                ],
                [
                  h.div(
                    [
                      h.Class("session-tags-popover pointer-events-none"),
                      h.Role("tooltip"),
                    ],
                    [
                      h.div(
                        [
                          h.Class(
                            "session-tags-bubble rounded-xl border border-border bg-bg-secondary p-2 shadow-(--shadow-elevated) flex flex-wrap gap-1"
                          ),
                        ],
                        session.overflowPills.map((pill) => fieldPill(pill, h))
                      ),
                    ]
                  ),
                  h.span(
                    [
                      h.Class(
                        "text-sm font-medium text-foreground-muted hover:text-foreground-secondary cursor-help border-b border-dotted border-foreground-muted hover:border-foreground-secondary"
                      ),
                    ],
                    [`+${session.overflowPills.length}`]
                  ),
                ]
              ),
        ]
      );

export const locationCrumbs = (
  options: Readonly<{ eventSlug: string; session: SessionView }>,
  h: H
) =>
  options.session.crumbs.length === 0
    ? h.empty
    : h.span(
        [
          h.Class("flex min-w-0 items-baseline"),
          h.Title(options.session.locationLabel),
        ],
        options.session.crumbs.flatMap((crumb, index) => {
          const isLast = index === options.session.crumbs.length - 1;
          const width = isLast ? "min-w-0" : "min-w-[3ch] shrink-[100000]";

          const separator =
            index === 0
              ? []
              : [
                  h.span(
                    [h.AriaHidden(true), h.Class("shrink-0 whitespace-pre")],
                    [" > "]
                  ),
                ];

          return [
            ...separator,
            crumb.spaceFilter === ""
              ? h.span([h.Class(cx("truncate", width))], [crumb.name])
              : h.a(
                  [
                    h.Href(
                      `/event/${options.eventSlug}/?space=${crumb.spaceFilter}#schedule-region`
                    ),
                    h.Class(
                      cx(
                        "pointer-events-auto truncate underline decoration-dotted underline-offset-4 hover:text-primary",
                        width
                      )
                    ),
                  ],
                  [crumb.name]
                ),
          ];
        })
      );

const seatCount = (session: SessionView, extraClass: string, h: H) =>
  h.span(
    [
      h.Class(
        cx(extraClass, "font-semibold tabular-nums text-foreground-muted")
      ),
    ],
    [session.seatsLabel]
  );

const availabilityLabel = (
  session: SessionView,
  now: number,
  context: PageContext,
  h: H
) => {
  const { translator } = context;
  const availability = availabilityAt(session, now);

  if (availability === "proposal") {
    return session.effectiveLimit === 0
      ? h.empty
      : seatCount(session, "text-sm", h);
  }

  if (availability === "full") {
    return session.waitingCount > 0
      ? h.span(
          [h.Class("text-sm font-medium text-foreground-muted")],
          [`${session.waitingCount} ${translator.t("waiting")}`]
        )
      : h.empty;
  }

  if (availability === "available") {
    return h.span(
      [
        h.Class(
          cx(
            "text-sm font-semibold",
            session.spotsScarce
              ? "text-coral-600 dark:text-coral-400"
              : "text-teal-700 dark:text-teal-400"
          )
        ),
      ],
      [
        translator.n(
          "%(counter)s spot left",
          "%(counter)s spots left",
          session.spotsLeft,
          { counter: session.spotsLeft }
        ),
      ]
    );
  }

  if (availability === "ended") {
    return h.span(
      [h.Class("text-xs font-medium text-foreground-muted")],
      [translator.t("Ended")]
    );
  }

  if (availability === "in-progress") {
    return h.span(
      [h.Class("text-xs font-medium text-foreground-muted")],
      [translator.t("In Progress")]
    );
  }

  return availability === "unavailable"
    ? seatCount(session, "text-sm", h)
    : h.empty;
};

const presenterRow = (session: SessionView, context: PageContext, h: H) =>
  session.host === "" && session.enrolledCount === 0
    ? h.empty
    : h.div(
        [h.Class("flex items-center gap-2.5 my-3.5 min-w-0 flex-nowrap")],
        [
          session.host === ""
            ? h.empty
            : h.span(
                [
                  h.Class("shrink-0 relative"),
                  h.DataAttribute("morph", "avatar"),
                ],
                [
                  avatar(
                    {
                      person: session.presenter,
                      size: "size-8",
                      translator: context.translator,
                    },
                    h
                  ),
                ]
              ),
          session.host === ""
            ? h.empty
            : h.span(
                [
                  h.Class(
                    "shrink-0 max-w-[12rem] truncate text-base font-medium text-foreground-secondary"
                  ),
                  h.DataAttribute("morph", "host"),
                  h.Title(session.host),
                ],
                [session.host]
              ),
          session.enrolledCount > 0
            ? h.span(
                [
                  h.Class("shrink-0 flex justify-end grow -space-x-2"),
                  h.Role("img"),
                  h.AriaLabel(
                    context.translator.n(
                      "%(counter)s participant enrolled",
                      "%(counter)s participants enrolled",
                      session.enrolledCount,
                      { counter: session.enrolledCount }
                    )
                  ),
                ],
                session.participants.map((person) =>
                  avatar(
                    { person, size: "w-7 h-7", translator: context.translator },
                    h
                  )
                )
              )
            : h.empty,
        ]
      );

export const sessionCard = (
  options: Readonly<{
    context: PageContext;
    isHidden: boolean;
    model: EventPageModel;
    session: SessionView;
  }>,
  h: H
): Html => {
  const { context, model, session } = options;
  const label = openDetailsLabel(session, context);

  return h.article(
    [
      h.Key(`card-${session.id}`),
      h.Class("h-full min-w-0 print:break-inside-avoid"),
      h.DataAttribute("session-wrapper", ""),
      h.Hidden(options.isHidden),
    ],
    [
      h.div(
        [
          h.Class(
            cx(
              "session relative flex h-full w-full flex-col rounded-2xl border duration-100 ring-offset-background ring-offset-[.5px] bg-(--card-surface) [--card-surface:var(--color-neutral-50)] dark:[--card-surface:var(--color-neutral-800)] border-border hover:ring-1 hover:ring-neutral-200 dark:hover:ring-neutral-600 hover:[--pb-scale:1.01]",
              session.userEnrolled && "ring-2 ring-coral-400"
            )
          ),
          ...sessionAttributes({ now: model.now, session }, h),
        ],
        [
          h.a(
            [
              h.Href(`?session=${session.id}`),
              h.Class("session-link absolute inset-0 z-10 rounded-2xl"),
              h.AriaHasPopup("dialog"),
              h.AriaControls(`session-${session.id}`),
              h.AriaLabel(label),
            ],
            [h.span([h.Class("sr-only")], [label])]
          ),
          session.coverUrl === ""
            ? h.empty
            : coverStrip({ extraClass: "shrink-0", url: session.coverUrl }, h),
          h.div(
            [
              h.Class(
                "relative z-10 flex min-h-0 flex-1 flex-col px-5 pb-5 pointer-events-none pt-4 print:px-3 print:pb-3 print:pt-2"
              ),
            ],
            [
              h.header(
                [],
                [
                  h.h3(
                    [
                      h.Class(
                        "w-fit overflow-hidden wrap-anywhere text-pretty text-3xl font-bold leading-tight tracking-tight text-foreground-primary print:text-lg"
                      ),
                      h.DataAttribute("morph", "title"),
                    ],
                    [session.title]
                  ),
                  presenterRow(session, context, h),
                ]
              ),
              session.description === ""
                ? h.empty
                : h.p(
                    [
                      h.Class(
                        "pointer-events-auto select-text text-sm mb-2 line-clamp-3 text-foreground-primary"
                      ),
                      h.DataAttribute("session-description", ""),
                    ],
                    [session.description]
                  ),
              h.div(
                [h.Class("relative"), h.DataAttribute("morph", "tags")],
                [tagsCloud(session, context, h)]
              ),
              h.div([h.Class("flex-1")], []),
              h.div(
                [
                  h.Class(
                    "mt-auto pt-4 flex items-center justify-between gap-3 min-w-0"
                  ),
                  h.DataAttribute("morph", "meta"),
                ],
                [
                  h.div(
                    [
                      h.Class(
                        "flex items-center gap-1.5 text-sm text-foreground-secondary min-w-0 overflow-hidden"
                      ),
                    ],
                    [
                      session.crumbs.length === 0
                        ? h.empty
                        : icon(
                            mapPinMini,
                            {
                              class: "size-4 shrink-0 text-foreground-muted/80",
                            },
                            h
                          ),
                      locationCrumbs(
                        { eventSlug: model.hero.slug, session },
                        h
                      ),
                      session.durationLabel === ""
                        ? h.empty
                        : icon(
                            clockMini,
                            {
                              class: "size-4 shrink-0 text-foreground-muted/80",
                            },
                            h
                          ),
                      session.durationLabel === ""
                        ? h.empty
                        : h.span(
                            [h.Class("shrink-0")],
                            [session.durationLabel]
                          ),
                    ]
                  ),
                  h.div(
                    [h.Class("shrink-0 flex items-center gap-2 print:hidden")],
                    [availabilityLabel(session, model.now, context, h)]
                  ),
                ]
              ),
            ]
          ),
          h.div(
            [
              h.Class("h-0"),
              h.AriaHidden(true),
              h.DataAttribute("morph", "footer"),
            ],
            []
          ),
        ]
      ),
    ]
  );
};

export const openSessionMessage = (session: SessionView) =>
  EventPageMessage.ClickedSamePageLink({
    hash: "",
    search: `?session=${session.id}`,
  });
