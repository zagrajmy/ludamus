import { Option, Schema } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";
import { defineTaggedUnion } from "foldkit/schema";

import { feedCover } from "./cover.js";
import { cx } from "./cx.js";
import { DateLeaf } from "./date-leaf.js";
import type { Translator } from "./i18n.js";
import { icon } from "./icon.js";
import type { IconData } from "./icon.js";
import {
  clipboardDocumentSolid,
  eyeSlashOutline,
  linkOutline,
  lockClosedOutline,
  mapPinOutline,
  pencilSquareOutline,
  puzzlePieceOutline,
  squares2x2Outline,
  usersOutline,
} from "./icons.js";

export const FeedEventCard = Schema.Struct({
  coverUrl: Schema.String,
  descriptionText: Schema.String,
  isLinkOnly: Schema.Boolean,
  isProposalActive: Schema.Boolean,
  isUnpublished: Schema.Boolean,
  leaf: DateLeaf,
  name: Schema.String,
  sessionCount: Schema.Int,
  slug: Schema.String,
});

export type FeedEventCard = typeof FeedEventCard.Type;

export const EncounterAttendance = defineTaggedUnion({
  Attending: { count: Schema.Int },
  Full: {},
  SignedUp: { count: Schema.Int, max: Schema.Int },
  SpotsLeft: { left: Schema.Int },
});

export type EncounterAttendance = typeof EncounterAttendance.Type;

export const FeedEncounterCard = Schema.Struct({
  attendance: EncounterAttendance,
  coverUrl: Schema.String,
  game: Schema.OptionFromOptional(Schema.String),
  isMine: Schema.Boolean,
  isPublic: Schema.Boolean,
  leaf: DateLeaf,
  organizerName: Schema.OptionFromOptional(Schema.String),
  place: Schema.OptionFromOptional(Schema.String),
  shareCode: Schema.String,
  title: Schema.String,
});

export type FeedEncounterCard = typeof FeedEncounterCard.Type;

export const FeedItem = defineTaggedUnion({
  Encounter: { card: FeedEncounterCard },
  Event: { card: FeedEventCard },
});

export type FeedItem = typeof FeedItem.Type;

export type FeedTagTone = "quiet" | "secondary" | "state";

export const feedTag = <Message>(
  options: Readonly<{
    icon?: IconData;
    label: string;
    tone?: FeedTagTone;
    truncate?: boolean;
  }>,
  h: HtmlBuilder<Message>
) =>
  h.span(
    [
      h.Class(
        cx(
          "inline-flex min-h-3.5 items-center gap-[5px] whitespace-nowrap text-[13px] font-medium",
          options.truncate === true ? "min-w-0 shrink" : "shrink-0",
          options.tone === "state"
            ? "text-coral-700 dark:text-coral-300"
            : options.tone === "quiet"
              ? "text-foreground-muted"
              : "text-foreground-secondary"
        )
      ),
    ],
    [
      options.icon === undefined
        ? h.empty
        : icon(options.icon, { class: "size-3.5 -translate-y-[1.5px]" }, h),
      h.span(
        [
          h.Class(
            cx(
              "text-box-trim-both",
              options.truncate === true &&
                "min-w-0 overflow-x-clip text-ellipsis"
            )
          ),
        ],
        [options.label]
      ),
    ]
  );

const cardFrame =
  "relative flex flex-col rounded-2xl border border-neutral-200/50 bg-bg-secondary ring-offset-[.5px] ring-offset-background duration-100 dark:border-neutral-700/50";

const tagRow = <Message>(tags: readonly Html[], h: HtmlBuilder<Message>) =>
  h.div(
    [h.Class("ml-[70px] flex min-h-7 min-w-0 items-end justify-end gap-x-3.5")],
    tags
  );

const footerRow =
  "border-t border-neutral-200/50 pt-3 text-sm text-foreground-secondary dark:border-neutral-700/50";

export const eventCard = <Message>(
  options: Readonly<{
    card: FeedEventCard;
    showHidden: boolean;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  const { card, translator } = options;

  const hiddenTag = options.showHidden
    ? card.isLinkOnly
      ? feedTag(
          {
            icon: linkOutline,
            label: translator.t("Link only"),
            tone: "quiet",
          },
          h
        )
      : card.isUnpublished
        ? feedTag(
            {
              icon: eyeSlashOutline,
              label: translator.t("Unpublished"),
              tone: "quiet",
            },
            h
          )
        : h.empty
    : h.empty;

  return h.a(
    [
      h.Key(`event-${card.slug}`),
      h.Href(`/event/${card.slug}/`),
      h.Class(
        cx(
          cardFrame,
          "hover:ring-1 hover:ring-neutral-200 dark:hover:ring-neutral-600"
        )
      ),
    ],
    [
      feedCover({ leaf: card.leaf, url: card.coverUrl }, h),
      h.div(
        [h.Class("flex flex-1 flex-col px-4 pb-4")],
        [
          tagRow(
            [
              hiddenTag,
              card.isProposalActive
                ? feedTag(
                    {
                      icon: pencilSquareOutline,
                      label: translator.t("Proposals open"),
                      tone: "state",
                    },
                    h
                  )
                : h.empty,
            ],
            h
          ),
          h.h3(
            [
              h.Class(
                "mt-3.5 text-lg font-semibold leading-tight text-foreground"
              ),
            ],
            [card.name]
          ),
          card.descriptionText === ""
            ? h.empty
            : h.p(
                [
                  h.Class(
                    "mt-1.5 line-clamp-2 text-sm text-foreground-secondary"
                  ),
                ],
                [card.descriptionText]
              ),
          h.div(
            [h.Class("mt-auto pt-4")],
            [
              h.div(
                [h.Class(cx("flex items-center gap-1.5", footerRow))],
                [
                  icon(squares2x2Outline, { class: "h-4 w-4" }, h),
                  h.span(
                    [h.Class("text-box-trim-both")],
                    [
                      translator.n(
                        "%(counter)s session",
                        "%(counter)s sessions",
                        card.sessionCount,
                        {
                          counter: card.sessionCount,
                        }
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
};

const attendanceLabel = (
  attendance: EncounterAttendance,
  translator: Translator
) =>
  EncounterAttendance.match(attendance, {
    Attending: ({ count }) => `${count} ${translator.t("attending")}`,
    Full: () => translator.t("Full"),
    SignedUp: ({ count, max }) =>
      translator.t("%(count)s of %(max)s signed up", { count, max }),
    SpotsLeft: ({ left }) =>
      translator.n("%(counter)s spot left", "%(counter)s spots left", left, {
        counter: left,
      }),
  });

export const copyPopoverClass =
  "pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md bg-bg-secondary px-2 py-1 text-xs font-medium tracking-[0.01em] text-foreground shadow-(--shadow-card) ring-1 ring-border origin-bottom opacity-0 scale-90 translate-y-0.5 transition duration-150 ease-out data-[show]:opacity-100 data-[show]:scale-100 data-[show]:translate-y-0 data-[show]:duration-300 data-[show]:ease-spring-a-bit";

export const copyButton = <Message>(
  options: Readonly<{
    children: readonly (Html | string)[];
    copied: boolean;
    onCopy: Message;
    translator: Translator;
    variant?: "button" | "menu-item";
  }>,
  h: HtmlBuilder<Message>
) =>
  h.button(
    [
      h.Type("button"),
      h.Class(
        options.variant === "menu-item"
          ? "relative w-full px-3 py-2 rounded-lg text-sm text-left text-foreground hover:bg-bg-tertiary focus-visible:bg-bg-tertiary"
          : "btn btn-secondary text-sm w-full"
      ),
      h.OnClick(options.onCopy),
    ],
    [
      ...options.children,
      h.span(
        [
          h.Role("status"),
          h.AriaLive("polite"),
          h.DataAttribute("copy-popover", ""),
          ...(options.copied ? [h.DataAttribute("show", "")] : []),
          h.Class(copyPopoverClass),
        ],
        [options.copied ? options.translator.t("Copied!") : ""]
      ),
    ]
  );

export const encounterSharePath = (shareCode: string) => `/e/${shareCode}/`;

export const encounterCard = <Message>(
  options: Readonly<{
    card: FeedEncounterCard;
    copied: boolean;
    onCopyShareLink: Message;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  const { card, translator } = options;
  const sharePath = encounterSharePath(card.shareCode);
  const placeLine = card.isMine ? card.place : Option.none<string>();
  const hostLine = card.isMine ? Option.none<string>() : card.organizerName;

  return h.div(
    [
      h.Key(`encounter-${card.shareCode}`),
      h.Class(
        cx(
          cardFrame,
          "has-[>a:hover]:ring-1 has-[>a:hover]:ring-neutral-200 dark:has-[>a:hover]:ring-neutral-600"
        )
      ),
    ],
    [
      h.a(
        [h.Href(sharePath), h.Class("flex flex-1 flex-col rounded-2xl")],
        [
          feedCover({ leaf: card.leaf, url: card.coverUrl }, h),
          h.div(
            [h.Class("flex flex-1 flex-col px-4 pb-4")],
            [
              tagRow(
                [
                  card.isMine
                    ? feedTag(
                        { label: translator.t("You organize"), tone: "state" },
                        h
                      )
                    : h.empty,
                  Option.match(card.game, {
                    onNone: () => h.empty,
                    onSome: (game) =>
                      feedTag(
                        {
                          icon: puzzlePieceOutline,
                          label: game,
                          truncate: true,
                        },
                        h
                      ),
                  }),
                ],
                h
              ),
              h.h3(
                [
                  h.Class(
                    "mt-3.5 text-lg font-semibold leading-tight text-foreground"
                  ),
                ],
                [card.title]
              ),
              Option.match(hostLine, {
                onNone: () =>
                  Option.match(placeLine, {
                    onNone: () => h.empty,
                    onSome: (place) =>
                      h.p(
                        [h.Class("mt-1.5 text-sm text-foreground-secondary")],
                        [place]
                      ),
                  }),
                onSome: (name) =>
                  h.p(
                    [h.Class("mt-1.5 text-sm text-foreground-secondary")],
                    [translator.t("Hosted by %(name)s", { name })]
                  ),
              }),
              h.div(
                [h.Class("mt-auto pt-4")],
                [
                  h.div(
                    [
                      h.Class(
                        cx(
                          "flex min-w-0 items-center justify-between gap-3",
                          footerRow
                        )
                      ),
                    ],
                    [
                      card.isMine
                        ? h.empty
                        : Option.match(card.place, {
                            onNone: () => h.empty,
                            onSome: (place) =>
                              h.span(
                                [h.Class("flex min-w-0 items-center gap-1.5")],
                                [
                                  icon(mapPinOutline, { class: "h-4 w-4" }, h),
                                  h.span([h.Class("truncate")], [place]),
                                ]
                              ),
                          }),
                      h.span(
                        [h.Class("flex shrink-0 items-center gap-1.5")],
                        [
                          icon(usersOutline, { class: "h-4 w-4" }, h),
                          h.span(
                            [h.Class("text-box-trim-both")],
                            [attendanceLabel(card.attendance, translator)]
                          ),
                        ]
                      ),
                      card.isMine && !card.isPublic
                        ? h.span(
                            [
                              h.Class(
                                "flex shrink-0 items-center gap-1.5 text-foreground-muted"
                              ),
                            ],
                            [
                              icon(lockClosedOutline, { class: "h-4 w-4" }, h),
                              h.span(
                                [h.Class("text-box-trim-both")],
                                [translator.t("Link only")]
                              ),
                            ]
                          )
                        : h.empty,
                    ]
                  ),
                ]
              ),
            ]
          ),
        ]
      ),
      card.isMine
        ? copyButton(
            {
              children: [
                icon(
                  clipboardDocumentSolid,
                  { class: "h-4 w-4 flex-shrink-0" },
                  h
                ),
                h.span([h.Class("truncate")], [sharePath]),
              ],
              copied: options.copied,
              onCopy: options.onCopyShareLink,
              translator,
            },
            h
          )
        : h.empty,
    ]
  );
};

export const feedGrid = <Message>(
  options: Readonly<{ cards: readonly Html[]; extraClass?: string }>,
  h: HtmlBuilder<Message>
) =>
  h.div(
    [
      h.Class(
        cx(
          "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6",
          options.extraClass
        )
      ),
    ],
    options.cards
  );
