import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";

import {
  availabilityAt,
  isFiltering,
  isEnded,
  sessionMatches,
} from "../../client/event-page/filters.js";
import type {
  CardDay,
  LedgerDay,
  LedgerTile,
  RoomGrid,
  RoomTile,
  ScheduleDay,
  SessionView,
} from "../../client/event-page/flags.js";
import { RoomRow } from "../../client/event-page/flags.js";
import { EventPageMessage } from "../../client/event-page/message.js";
import type { EventPageModel } from "../../client/event-page/model.js";
import { avatar } from "../../ui/avatar.js";
import { cx } from "../../ui/cx.js";
import { icon } from "../../ui/icon.js";
import {
  chevronDownMini,
  listBulletMini,
  plusMini,
  tableCellsMini,
} from "../../ui/icons.js";
import type { PageContext } from "../page-context.js";
import { bookmarkToggle } from "./bookmark-toggle.js";
import {
  openDetailsLabel,
  sessionAttributes,
  sessionCard,
} from "./session-card.js";

type H = HtmlBuilder<EventPageMessage>;

export type Visibility = ReadonlySet<number>;

export const visibleSessions = (model: EventPageModel): Visibility =>
  new Set(
    model.sessions
      .filter((session) =>
        sessionMatches({ filters: model.filters, now: model.now, session })
      )
      .map((session) => session.id)
  );

const sessionById = (model: EventPageModel) =>
  new Map(model.sessions.map((session) => [session.id, session]));

export const dayFoldToggle = (
  options: Readonly<{
    controls?: string;
    day: ScheduleDay;
    extraClass: string;
    isFolded: boolean;
  }>,
  h: H
) =>
  h.button(
    [
      h.Type("button"),
      h.Class(
        cx(
          "items-center gap-2 rounded-md px-2 py-1 text-left text-sm font-bold uppercase tracking-wide text-foreground-secondary transition-colors hover:bg-foreground/5 hover:text-foreground active:scale-100!",
          options.extraClass
        )
      ),
      h.DataAttribute("day-fold", ""),
      ...(options.controls === undefined
        ? []
        : [h.AriaControls(options.controls)]),
      h.AriaExpanded(!options.isFolded),
      h.OnClick(EventPageMessage.ClickedDayFold({ date: options.day.date })),
    ],
    [
      h.span(
        [h.Class("flex items-baseline gap-2")],
        [
          h.span([h.DataAttribute("day-name", "")], [options.day.name]),
          " ",
          h.span(
            [
              h.Class(
                "text-xs font-medium normal-case tracking-normal text-foreground-muted"
              ),
              h.DataAttribute("day-date", ""),
            ],
            [options.day.dateLabel]
          ),
        ]
      ),
      h.span(
        [
          h.Class(
            "day-fold-chevron ms-auto text-foreground-muted print:hidden"
          ),
        ],
        [icon(chevronDownMini, { class: "w-4 h-4" }, h)]
      ),
    ]
  );

const dayHeader = (
  options: Readonly<{ day: ScheduleDay; dayCount: number; isFolded: boolean }>,
  h: H
) =>
  h.h3(
    [
      h.Class(
        "mb-2 border-b border-border pb-1 text-sm font-bold uppercase tracking-wide text-foreground-secondary print:break-after-avoid"
      ),
    ],
    [
      options.dayCount > 1
        ? dayFoldToggle(
            {
              controls: options.day.panelId,
              day: options.day,
              extraClass: "flex w-full",
              isFolded: options.isFolded,
            },
            h
          )
        : h.span(
            [h.Class("flex items-baseline gap-2 px-2 pb-1")],
            [
              options.day.name,
              " ",
              h.span(
                [
                  h.Class(
                    "text-xs font-medium normal-case tracking-normal text-foreground-muted"
                  ),
                ],
                [options.day.dateLabel]
              ),
            ]
          ),
    ]
  );

export const viewTabs = (model: EventPageModel, context: PageContext, h: H) => {
  if (model.layout._tag !== "Compact") {
    return h.empty;
  }

  const base = `/event/${model.hero.slug}/`;

  const tab = (
    view: EventPageModel["view"],
    label: string,
    glyph: typeof listBulletMini
  ) =>
    h.a(
      [
        h.Key(view),
        h.Class(
          "flex items-center gap-1.5 rounded-xl px-3 py-1.5 sm:py-2 text-sm font-semibold whitespace-nowrap text-foreground-muted transition-colors hover:text-foreground aria-selected:bg-bg-secondary aria-selected:text-foreground aria-selected:shadow-sm"
        ),
        h.Role("tab"),
        h.Href(view === "rooms" ? `${base}?view=rooms` : base),
        h.AriaSelected(model.view === view),
        h.DataAttribute("tab", view),
      ],
      [
        icon(glyph, { class: "w-4 h-4" }, h),
        h.span([h.Class("sr-only sm:not-sr-only")], [label]),
      ]
    );

  return h.div(
    [h.Class("flex")],
    [
      h.nav(
        [
          h.Class(
            "inline-flex items-stretch gap-0.5 rounded-2xl border border-border bg-bg-tertiary p-1"
          ),
          h.Role("tablist"),
          h.AriaLabel(context.translator.t("Schedule view")),
        ],
        [
          tab("list", context.translator.t("List"), listBulletMini),
          tab("rooms", context.translator.t("Rooms"), tableCellsMini),
        ]
      ),
    ]
  );
};

const nowMarker = (extraClass: string, context: PageContext, h: H) =>
  h.span(
    [
      h.Class(
        cx(
          "schedule-now-pill rounded-full bg-primary px-1.5 text-[0.625rem] font-bold tabular-nums leading-[1.1rem] text-white",
          extraClass
        )
      ),
    ],
    [
      h.span([h.Class("sr-only")], [context.translator.t("Now")]),
      h.span([h.DataAttribute("now-time", "")], []),
    ]
  );

export const cardSchedule = (
  options: Readonly<{
    context: PageContext;
    days: readonly CardDay[];
    model: EventPageModel;
    slotCount: number;
    visible: Visibility;
  }>,
  h: H
): Html => {
  const { context, model, visible } = options;
  const byId = sessionById(model);
  const dayCount = options.days.length;
  const allSlots = options.days.flatMap((day) => day.slots);

  const nextSlot = allSlots.find((slot) =>
    slot.sessionIds.some((id) => {
      const session = byId.get(id);

      return session !== undefined && !isEnded(session, model.now);
    })
  );

  return h.div(
    [
      h.DataAttribute("event-time-zone", "Europe/Warsaw"),
      h.DataAttribute("day-starts-at", "6"),
    ],
    options.days.map((day) => {
      const isFolded = model.foldedDays.includes(day.day.date);

      const daySlots = day.slots.map((slot, index) => {
        const sessions = slot.sessionIds.flatMap((id) => {
          const session = byId.get(id);

          return session === undefined ? [] : [session];
        });

        const isSlotEnded = sessions.every((session) =>
          isEnded(session, model.now)
        );

        const hasVisible = sessions.some((session) => visible.has(session.id));
        const labelId = `${day.day.panelId}-slot-${index + 1}`;

        return h.div(
          [
            h.Key(labelId),
            h.Class(
              "mb-8 time-slot-section print:mb-4 print:break-inside-avoid"
            ),
            h.Role("group"),
            h.AriaLabelledBy(labelId),
            ...(isSlotEnded ? [h.DataAttribute("ended", "")] : []),
            h.Hidden(!hasVisible),
          ],
          [
            h.div(
              [h.Class("flex min-h-8 items-center gap-4 mb-3 px-2")],
              [
                h.div(
                  [
                    h.Id(labelId),
                    h.Class(
                      cx(
                        "text-sm font-semibold tabular-nums",
                        isSlotEnded
                          ? "text-foreground-muted"
                          : "text-foreground"
                      )
                    ),
                  ],
                  [
                    slot.dateLabel === ""
                      ? slot.hour
                      : `${slot.dateLabel} ${slot.hour}`,
                  ]
                ),
                model.hero.isLive && slot === nextSlot
                  ? h.span(
                      [
                        h.Class(
                          "text-sm text-teal-600 dark:text-teal-400 font-medium flex items-center gap-1.5 print:hidden"
                        ),
                      ],
                      [
                        h.span(
                          [
                            h.Class(
                              "w-2 h-2 bg-teal-500 rounded-full live-dot"
                            ),
                          ],
                          []
                        ),
                        context.translator.t("Now"),
                      ]
                    )
                  : h.empty,
                h.span(
                  [h.Class("ml-auto text-xs text-foreground-muted")],
                  [
                    context.translator.n(
                      "%(counter)s session",
                      "%(counter)s sessions",
                      sessions.length,
                      { counter: sessions.length }
                    ),
                  ]
                ),
                !isSlotEnded &&
                model.hero.isProposalActive &&
                options.slotCount > 1
                  ? h.a(
                      [
                        h.Href(model.hero.proposeUrl),
                        h.Class(
                          "print:hidden text-teal-600 bg-teal-400/20 dark:bg-teal-800/20 dark:text-teal-400 gap-1.5 p-1.5 rounded-lg hover:bg-teal-400/30 dark:hover:bg-teal-800/30 transition-colors hover:duration-0 shrink-0"
                        ),
                      ],
                      [
                        icon(plusMini, { class: "w-4 h-4" }, h),
                        h.span(
                          [h.Class("sr-only")],
                          [context.translator.t("Propose")]
                        ),
                      ]
                    )
                  : h.empty,
              ]
            ),
            h.div(
              [
                h.Class(
                  "session-grid grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4 print:grid-cols-2 print:gap-3"
                ),
              ],
              sessions.map((session) =>
                sessionCard(
                  {
                    context,
                    isHidden: !visible.has(session.id),
                    model,
                    session,
                  },
                  h
                )
              )
            ),
          ]
        );
      });

      const anyVisible = day.slots.some((slot) =>
        slot.sessionIds.some((id) => visible.has(id))
      );

      return h.section(
        [
          h.Key(day.day.date),
          h.DataAttribute("schedule-day", ""),
          h.DataAttribute("day", day.day.date),
          ...(isFolded ? [h.DataAttribute("folded", "")] : []),
          h.Hidden(!anyVisible),
        ],
        [
          dayCount > 1
            ? dayHeader({ day: day.day, dayCount, isFolded }, h)
            : h.empty,
          h.div(
            [h.Id(day.day.panelId), h.DataAttribute("day-panel", "")],
            daySlots
          ),
        ]
      );
    })
  );
};

const bookmarkBadge = (
  session: SessionView,
  context: PageContext,
  h: H,
  wrapper: string
) =>
  Option.isSome(context.shell.viewer)
    ? bookmarkToggle({ context, session, wrapper }, h)
    : session.bookmarkCount === 0
      ? h.empty
      : h.span(
          [h.Class(cx("bookmark-affordance print:hidden", wrapper))],
          [
            h.span(
              [
                h.Class(
                  "relative z-20 inline-flex shrink-0 items-center self-center gap-0.75 p-1.5 text-xs text-foreground-secondary"
                ),
              ],
              [
                h.span(
                  [h.Class("tabular-nums"), h.AriaHidden(true)],
                  [String(session.bookmarkCount)]
                ),
                h.span(
                  [h.Class("sr-only")],
                  [
                    context.translator.n(
                      "Bookmarked by %(counter)s person",
                      "Bookmarked by %(counter)s people",
                      session.bookmarkCount,
                      { counter: session.bookmarkCount }
                    ),
                  ]
                ),
              ]
            ),
          ]
        );

const compactAvailability = (
  session: SessionView,
  now: number,
  context: PageContext,
  h: H
) => {
  const { translator } = context;
  const availability = availabilityAt(session, now);

  const muted = (text: string) =>
    h.span([h.Class("font-medium text-foreground-muted")], [text]);

  if (availability === "ended") {
    return Option.some(muted(translator.t("Ended")));
  }

  if (availability === "in-progress") {
    return Option.some(muted(translator.t("In Progress")));
  }

  if (availability === "unavailable") {
    return Option.some(
      h.span(
        [h.Class("font-semibold tabular-nums text-foreground-muted")],
        [session.seatsLabel]
      )
    );
  }

  if (availability === "full") {
    const full = h.span(
      [h.Class("font-semibold text-foreground-muted")],
      [translator.t("Full")]
    );

    return Option.some(
      session.waitingCount > 0
        ? h.span(
            [],
            [
              full,
              " ",
              h.span(
                [h.Class("text-foreground-muted")],
                [`· ${session.waitingCount} ${translator.t("waiting")}`]
              ),
            ]
          )
        : full
    );
  }

  if (availability === "available") {
    return Option.some(
      h.span(
        [
          h.Class(
            cx(
              "font-semibold tabular-nums",
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
            {
              counter: session.spotsLeft,
            }
          ),
        ]
      )
    );
  }

  return Option.none();
};

const ledgerRow = (
  options: Readonly<{
    context: PageContext;
    isHidden: boolean;
    model: EventPageModel;
    session: SessionView;
    tile: LedgerTile;
  }>,
  h: H
) => {
  const { context, model, session, tile } = options;
  const availability = compactAvailability(session, model.now, context, h);

  return h.article(
    [
      h.Key(`row-${tile.sessionId}-${tile.startsAt}`),
      h.Class("min-w-0"),
      h.DataAttribute("session-wrapper", ""),
      h.Hidden(options.isHidden),
    ],
    [
      h.div(
        [
          h.Class(
            cx(
              "session group/row relative flex flex-wrap items-center gap-x-2 rounded-lg px-2 py-2 max-sm:pl-12 sm:flex-nowrap sm:gap-x-3 transition-colors has-[a:hover]:duration-0 has-[a:hover]:bg-bg-tertiary dark:has-[a:hover]:bg-bg-tertiary/50 max-sm:has-[.bookmark-affordance]:pr-11 data-ended:opacity-65 data-ended:has-[a:hover]:opacity-100",
              session.userEnrolled && "bg-coral-50/60 dark:bg-coral-950/40"
            )
          ),
          h.DataAttribute("no-morph", ""),
          ...sessionAttributes({ now: model.now, session, tile }, h),
        ],
        [
          h.a(
            [
              h.Href(`?session=${session.id}`),
              h.Class("session-link absolute inset-0 z-10 rounded-lg"),
              h.AriaHasPopup("dialog"),
              h.AriaControls(`session-${session.id}`),
            ],
            [h.span([h.Class("sr-only")], [openDetailsLabel(session, context)])]
          ),
          h.span(
            [
              h.Class(
                "w-8 shrink-0 whitespace-nowrap text-[0.7rem] tabular-nums text-foreground-secondary max-sm:absolute max-sm:left-2 max-sm:top-1/2 max-sm:-translate-y-1/2 sm:w-28 sm:pt-1.5"
              ),
            ],
            [
              tile.startClock,
              h.span([h.Class("hidden sm:inline")], ["–"]),
              h.span([h.Class("block sm:inline")], [tile.endClock]),
            ]
          ),
          h.span(
            [h.Class("flex min-w-0 flex-1 items-baseline gap-x-1.5")],
            [
              h.span(
                [h.Class("truncate text-sm font-semibold text-foreground")],
                [session.title]
              ),
              h.span(
                [h.Class("truncate text-xs text-foreground-muted")],
                [session.host]
              ),
            ]
          ),
          h.span(
            [
              h.Class(
                "shrink-0 text-xs text-foreground-muted max-sm:basis-full sm:whitespace-nowrap sm:text-right"
              ),
              h.Title(session.locationLabel),
            ],
            [
              session.spaceName,
              session.durationLabel === "" ? "" : ` · ${session.durationLabel}`,
              ...(session.minAge > 0
                ? [
                    " · ",
                    h.span(
                      [
                        h.Class(
                          "font-medium text-coral-600 dark:text-coral-400"
                        ),
                      ],
                      [`${session.minAge}+`]
                    ),
                  ]
                : []),
              ...Option.match(availability, {
                onNone: () => [],
                onSome: (label) => [
                  " ",
                  h.span([h.Class("print:hidden")], ["· ", label]),
                ],
              }),
            ]
          ),
          bookmarkBadge(
            session,
            context,
            h,
            "z-20 shrink-0 self-center pointer-events-auto max-sm:absolute max-sm:right-1 max-sm:top-1/2 max-sm:-translate-y-1/2"
          ),
          h.span(
            [h.Class("sr-only"), h.DataAttribute("session-description", "")],
            [session.description]
          ),
        ]
      ),
    ]
  );
};

const scheduleRail = (
  options: Readonly<{
    context: PageContext;
    days: readonly LedgerDay[];
    reachable: Option.Option<ReadonlySet<string>>;
  }>,
  h: H
) =>
  h.nav(
    [
      h.Class(
        "schedule-rail print:hidden sticky top-14.5 max-h-[calc(100dvh-6rem)] shrink-0 touch-none select-none self-start overflow-hidden py-1 text-foreground-muted"
      ),
      h.AriaLabel(options.context.translator.t("Jump to time")),
    ],
    options.days.flatMap((day) => [
      h.span(
        [
          h.Key(`rail-${day.day.date}`),
          h.Class(
            "block px-1.5 pt-2 pb-0.5 text-center text-[0.625rem] font-bold uppercase text-foreground-secondary first:pt-0"
          ),
        ],
        [day.day.shortName]
      ),
      ...day.hours.map((hour) =>
        h.a(
          [
            h.Key(`rail-${hour.slotKey}`),
            h.Hidden(
              Option.exists(
                options.reachable,
                (reachable) => !reachable.has(hour.slotKey)
              )
            ),
            h.DataAttribute("schedule-rail-hour", ""),
            h.Class(
              "block rounded px-1.5 py-px text-center text-xs tabular-nums leading-snug [-webkit-touch-callout:none] hover:text-foreground data-active:bg-white data-active:font-bold data-active:text-coral-600 data-active:ring-1 data-active:ring-inset data-active:ring-coral-300/60 dark:data-active:bg-black dark:data-active:text-coral-400 dark:data-active:ring-coral-700/60"
            ),
            h.Href(`#slot-${hour.slotKey}`),
            h.Draggable(false),
            h.DataAttribute("rail-hour", hour.slotKey),
            h.AriaLabel(
              `${options.context.translator.t("Jump to %(day)s %(time)s", {
                day: day.day.name,
                time: hour.clock,
              })}${hour.repeatedZone === "" ? "" : ` ${hour.repeatedZone}`}`
            ),
            h.OnContextMenu(EventPageMessage.CompletedFocus()),
          ],
          [hour.hourLabel]
        )
      ),
    ])
  );

const ledger = (
  options: Readonly<{
    context: PageContext;
    days: readonly LedgerDay[];
    model: EventPageModel;
    visible: Visibility;
  }>,
  h: H
) => {
  const { context, model, visible } = options;
  const byId = sessionById(model);

  return [
    ...options.days.map((day) => {
      const isFolded = model.foldedDays.includes(day.day.date);

      const anyVisible = day.hours.some((hour) =>
        hour.tiles.some((tile) => visible.has(tile.sessionId))
      );

      return h.section(
        [
          h.Key(day.day.date),
          h.DataAttribute("schedule-day", ""),
          h.DataAttribute("day", day.day.date),
          ...(isFolded ? [h.DataAttribute("folded", "")] : []),
          h.Class(
            "mb-6 border-y border-border bg-bg-secondary px-2 pt-3 pb-2 last:mb-0 sm:rounded-2xl sm:border sm:px-3"
          ),
          h.Hidden(!anyVisible),
        ],
        [
          dayHeader(
            { day: day.day, dayCount: options.days.length, isFolded },
            h
          ),
          h.div(
            [h.Id(day.day.panelId), h.DataAttribute("day-panel", "")],
            day.hours.map((hour) => {
              const hasVisible = hour.tiles.some((tile) =>
                visible.has(tile.sessionId)
              );

              return h.div(
                [
                  h.Key(hour.slotKey),
                  h.Class("time-slot-section scroll-mt-24"),
                  h.Id(`slot-${hour.slotKey}`),
                  h.DataAttribute("slot-hour", hour.slotKey),
                  h.Hidden(!hasVisible),
                ],
                [
                  h.div(
                    [
                      h.Class(
                        "px-2 pt-3 pb-1 text-[0.7rem] font-bold tabular-nums tracking-wide text-foreground-muted"
                      ),
                    ],
                    [
                      hour.clock,
                      hour.repeatedZone === ""
                        ? h.empty
                        : h.span(
                            [h.Class("ml-1 text-[0.6rem]")],
                            [hour.repeatedZone]
                          ),
                    ]
                  ),
                  h.div(
                    [h.Class("session-grid divide-y-visible relative")],
                    hour.tiles.flatMap((tile) => {
                      const session = byId.get(tile.sessionId);

                      return session === undefined
                        ? []
                        : [
                            ledgerRow(
                              {
                                context,
                                isHidden: !visible.has(session.id),
                                model,
                                session,
                                tile,
                              },
                              h
                            ),
                          ];
                    })
                  ),
                ]
              );
            })
          ),
        ]
      );
    }),
    h.div(
      [
        h.Key("now-line"),
        h.Class("schedule-now-line"),
        h.DataAttribute("schedule-now", ""),
        h.Hidden(true),
      ],
      [nowMarker("absolute top-0 start-0.5 -translate-y-1/2", context, h)]
    ),
  ];
};

const roomTile = (
  options: Readonly<{
    context: PageContext;
    model: EventPageModel;
    rowIndex: number;
    session: SessionView;
    tile: RoomTile;
    visible: Visibility;
  }>,
  h: H
) => {
  const { context, model, session, tile } = options;
  const availability = compactAvailability(session, model.now, context, h);

  return h.div(
    [
      h.Key(`tile-${tile.sessionId}`),
      h.Class("justify-self-start p-0.5"),
      h.DataAttribute("room-lanes-cell", ""),
      h.DataAttribute("tile-col", String(tile.column)),
      h.DataAttribute("tile-row", String(options.rowIndex)),
      h.DataAttribute("tile-span", String(tile.span)),
      h.DataAttribute("tile-lane", String(tile.laneIndex)),
      h.DataAttribute("tile-lanes", String(tile.laneCount)),
      h.Style({
        "grid-column": String(tile.column + 1),
        "grid-row": `${options.rowIndex} / span ${tile.span}`,
        transform: `translateX(calc(${tile.laneIndex} * 100%))`,
        width: `calc(100% / ${tile.laneCount})`,
      }),
      h.Hidden(!options.visible.has(session.id)),
    ],
    [
      h.article(
        [
          h.Class("h-full min-w-0"),
          h.DataAttribute("session-wrapper", ""),
          h.DataAttribute("slot-hour", tile.slotKey),
          h.Hidden(!options.visible.has(session.id)),
        ],
        [
          h.div(
            [
              h.Class(
                cx(
                  "session group/tile relative flex h-full flex-col gap-1 rounded-xl border border-border pb-1 bg-bg-secondary p-2 transition-colors hover:border-neutral-300 dark:hover:border-neutral-600 data-ended:opacity-65 data-ended:hover:opacity-100",
                  session.userEnrolled && "bg-coral-50/60 dark:bg-coral-950/40"
                )
              ),
              ...sessionAttributes(
                {
                  now: model.now,
                  session,
                  tile: { endIso: tile.endIso, startIso: tile.startIso },
                },
                h
              ),
            ],
            [
              h.a(
                [
                  h.Href(`?session=${session.id}`),
                  h.Class("session-link absolute inset-0 z-10 rounded-xl"),
                  h.AriaHasPopup("dialog"),
                  h.AriaControls(`session-${session.id}`),
                  h.AriaDescribedBy(`room-lane-room-${tile.column}`),
                ],
                [
                  h.span(
                    [h.Class("sr-only")],
                    [openDetailsLabel(session, context)]
                  ),
                ]
              ),
              h.h4(
                [
                  h.Class(
                    "w-fit text-sm font-semibold leading-snug text-foreground wrap-anywhere text-pretty"
                  ),
                  h.DataAttribute("morph", "title"),
                ],
                [session.title]
              ),
              session.host === ""
                ? h.empty
                : h.div(
                    [
                      h.Class(
                        "flex min-w-0 items-center gap-0.75 text-xs text-foreground-muted"
                      ),
                    ],
                    [
                      h.span(
                        [
                          h.Class("shrink-0"),
                          h.DataAttribute("morph", "avatar"),
                        ],
                        [
                          avatar(
                            {
                              person: session.presenter,
                              size: "size-5",
                              translator: context.translator,
                            },
                            h
                          ),
                        ]
                      ),
                      h.span(
                        [h.Class("truncate"), h.DataAttribute("morph", "host")],
                        [session.host]
                      ),
                    ]
                  ),
              h.span(
                [
                  h.Class(
                    "truncate text-xs tabular-nums text-foreground-muted"
                  ),
                  h.DataAttribute("morph", "time"),
                ],
                [
                  `${tile.startClock}–${tile.endClock}`,
                  ...(session.minAge > 0
                    ? [
                        " · ",
                        h.span(
                          [
                            h.Class(
                              "font-medium text-coral-600 dark:text-coral-400"
                            ),
                          ],
                          [`${session.minAge}+`]
                        ),
                      ]
                    : []),
                ]
              ),
              h.div(
                [
                  h.Class(
                    "mt-auto flex items-center justify-between gap-2 pt-0.5 text-xs"
                  ),
                  h.DataAttribute("morph", "meta"),
                ],
                [
                  h.span(
                    [h.Class("min-w-0 truncate text-foreground-muted")],
                    Option.match(availability, {
                      onNone: () => [],
                      onSome: (label) => [label],
                    })
                  ),
                  bookmarkBadge(session, context, h, "shrink-0"),
                ]
              ),
            ]
          ),
        ]
      ),
    ]
  );
};

const roomsGrid = (
  options: Readonly<{
    context: PageContext;
    grid: RoomGrid;
    model: EventPageModel;
    visible: Visibility;
  }>,
  h: H
) => {
  const { context, grid, model, visible } = options;
  const byId = sessionById(model);
  const columnCount = grid.columns.length;

  const liveColumns = new Set(
    grid.rows.flatMap((row) =>
      row._tag === "Time"
        ? row.tiles
            .filter((tile) => visible.has(tile.sessionId))
            .map((tile) => tile.column)
        : []
    )
  );

  const coveredRows = new Set(
    grid.rows.flatMap((row, index) =>
      row._tag === "Time"
        ? row.tiles
            .filter((tile) => visible.has(tile.sessionId))
            .flatMap((tile) =>
              Array.from(
                { length: tile.span },
                (_unused, offset) => index + 1 + offset
              )
            )
        : []
    )
  );

  const foldedDayIndexes = new Set(
    grid.days.flatMap((day, index) =>
      model.foldedDays.includes(day.date) ? [index] : []
    )
  );

  const filtering = isFiltering(model.filters);

  const isRowCollapsed = (index: number) => {
    const row = grid.rows[index - 1];

    if (row === undefined || row._tag === "DayHeading") {
      return false;
    }

    return (
      foldedDayIndexes.has(row.dayIndex) ||
      (filtering && !coveredRows.has(index))
    );
  };

  const rowTracks = grid.rows
    .map((row, index) => {
      if (isRowCollapsed(index + 1)) {
        return "0px";
      }

      if (row._tag === "DayHeading") {
        return "var(--row-track)";
      }

      return row.isFold
        ? "var(--row-track-fold)"
        : `minmax(calc(var(--row-track-unit) * ${row.minutes} / 60), auto)`;
    })
    .join(" ");

  const columnTracks = `var(--axis-w) ${grid.columns
    .map((_column, index) =>
      !filtering || liveColumns.has(index + 1) ? "var(--col-track)" : "0px"
    )
    .join(" ")}`;

  const firstDay = grid.days[0];

  const gridStyle = {
    "--live-rooms": String(filtering ? liveColumns.size : columnCount),
    "--rooms": String(columnCount),
    "--rows": String(grid.rows.length),
  };

  const headCells = grid.columns.map((column, index) =>
    h.div(
      [
        h.Key(`head-${index}`),
        h.Class(
          cx(
            "room-lanes-head-cell px-2 py-1.5",
            filtering && !liveColumns.has(index + 1) && "room-lanes-collapsed"
          )
        ),
        h.DataAttribute("lane-col", String(index + 1)),
        h.DataAttribute("lane-group", column.groupKey),
        h.Style({ "grid-column": String(index + 2) }),
      ],
      [
        h.div(
          [
            h.Class(
              cx(
                "min-h-[1lh] wrap-anywhere text-pretty text-[0.625rem] font-semibold uppercase tracking-widest text-foreground-muted",
                !column.startsGroup && "invisible"
              )
            ),
            h.DataAttribute("lane-group-label", ""),
          ],
          [column.group]
        ),
        h.div(
          [
            h.Class(
              "wrap-anywhere text-pretty text-xs font-bold uppercase tracking-wide text-foreground-secondary"
            ),
            h.AriaHidden(true),
          ],
          [column.name]
        ),
        h.span(
          [h.Class("sr-only"), h.Id(`room-lane-room-${index + 1}`)],
          [
            column.group === ""
              ? column.name
              : `${column.group}, ${column.name}`,
          ]
        ),
      ]
    )
  );

  const bodyCells = grid.rows.flatMap((row, index) => {
    const rowNumber = index + 1;
    const collapsed = isRowCollapsed(rowNumber);
    const rowStyle = h.Style({ "grid-row": String(rowNumber) });

    if (row._tag === "DayHeading") {
      return [
        h.div(
          [
            h.Key(`day-${row.dayIndex}`),
            h.Class(cx("room-lanes-day", collapsed && "room-lanes-collapsed")),
            h.DataAttribute("day-heading", ""),
            h.DataAttribute("lane-day-heading", String(row.dayIndex)),
            h.DataAttribute("lane-row", String(rowNumber)),
            h.DataAttribute("lane-day", String(row.dayIndex)),
            h.DataAttribute("day", row.day.date),
            ...(model.foldedDays.includes(row.day.date)
              ? [h.DataAttribute("folded", "")]
              : []),
            rowStyle,
          ],
          [
            h.h3(
              [
                h.Class(
                  "sticky left-0 py-1 text-sm font-bold uppercase tracking-wide text-foreground-secondary"
                ),
              ],
              [
                dayFoldToggle(
                  {
                    day: row.day,
                    extraClass: "inline-flex",
                    isFolded: model.foldedDays.includes(row.day.date),
                  },
                  h
                ),
              ]
            ),
          ]
        ),
      ];
    }

    return [
      h.div(
        [
          h.Key(`time-${rowNumber}`),
          h.Class(
            cx(
              "room-lanes-time sticky left-0 z-40 bg-background pr-1 text-right text-[0.7rem] font-bold tabular-nums text-foreground-muted",
              collapsed && "room-lanes-collapsed"
            )
          ),
          h.DataAttribute("lane-row", String(rowNumber)),
          h.DataAttribute("lane-day", String(row.dayIndex)),
          rowStyle,
        ],
        row.isCut
          ? []
          : [
              row.clock,
              row.repeatedZone === ""
                ? h.empty
                : h.span([h.Class("block text-[0.55rem]")], [row.repeatedZone]),
            ]
      ),
      h.div(
        [
          h.Key(`line-${rowNumber}`),
          h.Class(
            cx(
              "room-lanes-line",
              index > 0 && "border-t border-border/60",
              row.isCut && "room-lanes-line-cut",
              collapsed && "room-lanes-collapsed"
            )
          ),
          h.DataAttribute("lane-row", String(rowNumber)),
          h.DataAttribute("lane-day", String(row.dayIndex)),
          h.DataAttribute(
            "row-track",
            row.isFold ? "fold" : String(row.minutes)
          ),
          h.DataAttribute("row-start", row.startIso),
          h.DataAttribute("row-end", row.endIso),
          h.Style({
            "grid-column": `2 / span ${columnCount}`,
            "grid-row": String(rowNumber),
          }),
        ],
        row.isFold
          ? [
              h.span(
                [
                  h.Class(
                    "room-lanes-fold-label px-2 text-[0.6rem] font-semibold uppercase tracking-widest text-foreground-muted"
                  ),
                ],
                [
                  context.translator.t("Nothing new until %(until)s", {
                    until: row.foldUntil,
                  }),
                ]
              ),
            ]
          : row.opensSlot
            ? [
                h.span(
                  [
                    h.Class("time-slot-section block h-full scroll-mt-40"),
                    h.Id(`slot-${row.slotKey}`),
                    h.DataAttribute("slot-hour", row.slotKey),
                    h.AriaHidden(true),
                  ],
                  []
                ),
              ]
            : []
      ),
      ...row.tiles.flatMap((tile) => {
        const session = byId.get(tile.sessionId);

        return session === undefined
          ? []
          : [
              roomTile(
                { context, model, rowIndex: rowNumber, session, tile, visible },
                h
              ),
            ];
      }),
    ];
  });

  return h.div(
    [
      h.Class("room-lanes bg-background"),
      h.Hidden(visible.size === 0),
      h.DataAttribute("rooms", String(columnCount)),
      h.DataAttribute("rows", String(grid.rows.length)),
      h.Style(gridStyle),
    ],
    [
      h.div(
        [h.Class("sticky top-14 z-30 border-b border-border/60 bg-background")],
        [
          firstDay === undefined
            ? h.empty
            : h.div(
                [
                  h.Class(
                    "room-lanes-day-current border-b border-border/60 bg-background"
                  ),
                ],
                [
                  dayFoldToggle(
                    {
                      day: firstDay,
                      extraClass: "inline-flex",
                      isFolded: model.foldedDays.includes(firstDay.date),
                    },
                    h
                  ),
                ]
              ),
          h.div(
            [
              h.Class("room-lanes-head scrollview-fade-x-8"),
              h.DataAttribute("room-lanes-head", ""),
            ],
            [
              h.div(
                [
                  h.Class(
                    "room-lanes-corner z-10 bg-background text-[0.625rem] font-semibold uppercase tracking-widest text-foreground-muted px-1 py-1.5 text-right flex items-end justify-end text-box-trim-both"
                  ),
                ],
                [context.translator.t("Time")]
              ),
              h.div(
                [
                  h.Class("room-lanes-grid"),
                  h.Style({ "grid-template-columns": columnTracks }),
                ],
                headCells
              ),
            ]
          ),
        ]
      ),
      h.div(
        [h.Class("room-lanes-scroll-shell")],
        [
          h.div(
            [
              h.Class(
                "room-lanes-scroll scrollview-fade-x-16 overflow-x-auto overflow-y-clip overscroll-x-contain"
              ),
              h.DataAttribute("room-lanes-scroll", ""),
              h.Tabindex(0),
              h.Role("region"),
              h.AriaLabel(context.translator.t("Rooms schedule")),
            ],
            [
              h.div(
                [
                  h.Class("room-lanes-grid room-lanes-body"),
                  h.Style({
                    "grid-template-columns": columnTracks,
                    "grid-template-rows": rowTracks,
                  }),
                ],
                [
                  firstDay === undefined
                    ? h.empty
                    : h.h3(
                        [
                          h.Class("sr-only"),
                          h.DataAttribute("day-heading", ""),
                          h.DataAttribute("lane-day-heading", "0"),
                          h.DataAttribute("day", firstDay.date),
                        ],
                        [
                          h.span(
                            [h.DataAttribute("day-name", "")],
                            [firstDay.name]
                          ),
                          " ",
                          h.span(
                            [h.DataAttribute("day-date", "")],
                            [firstDay.dateLabel]
                          ),
                        ]
                      ),
                  ...bodyCells,
                  ...grid.columns.map((_column, index) =>
                    h.div(
                      [
                        h.Key(`rule-${index}`),
                        h.Class("room-lanes-rule"),
                        h.DataAttribute("lane-col", String(index + 1)),
                        h.Style({
                          "grid-column": String(index + 2),
                          "grid-row": `1 / span ${grid.rows.length}`,
                        }),
                      ],
                      []
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
};

export const compactSchedule = (
  options: Readonly<{
    context: PageContext;
    days: readonly LedgerDay[];
    grid: RoomGrid;
    model: EventPageModel;
    visible: Visibility;
  }>,
  h: H
): Html => {
  const isRooms = options.model.view === "rooms";

  return h.div(
    [
      h.Class(isRooms ? "breakout" : "-mx-4 sm:mx-0"),
      h.DataAttribute("compact-schedule", ""),
      h.DataAttribute("event-time-zone", "Europe/Warsaw"),
      h.DataAttribute("day-starts-at", "6"),
    ],
    [
      h.div(
        [h.Class("flex items-start sm:gap-1")],
        [
          h.div(
            [h.Class("min-w-0 flex-1")],
            isRooms
              ? [
                  roomsGrid(
                    {
                      context: options.context,
                      grid: options.grid,
                      model: options.model,
                      visible: options.visible,
                    },
                    h
                  ),
                ]
              : ledger(options, h)
          ),
          scheduleRail(
            {
              context: options.context,
              days: options.days,
              reachable: isRooms
                ? Option.some(
                    new Set(
                      options.grid.rows.flatMap((row) =>
                        RoomRow.match(row, {
                          DayHeading: () => [],
                          Time: (time) =>
                            time.opensSlot ? [time.slotKey] : [],
                        })
                      )
                    )
                  )
                : Option.none(),
            },
            h
          ),
        ]
      ),
    ]
  );
};
