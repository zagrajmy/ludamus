import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";
import { defineView } from "foldkit/submodel";

import { EventsFeedMessage } from "../../client/events-feed/message.js";
import type { EventsFeedModel } from "../../client/events-feed/model.js";
import { linkButton } from "../../ui/button.js";
import {
  encounterCard,
  eventCard,
  FeedItem,
  feedGrid,
} from "../../ui/feed-card.js";
import { calendarDaysOutline, plusOutline } from "../../ui/icons.js";
import { emptyState } from "../../ui/status.js";
import { pageContextOf } from "../page-context.js";
import type { PageContext, PageInputs } from "../page-context.js";
import type { PageTitle } from "../shell/title.js";

export const createEncounterHref = "/encounters/create/";

export const eventsFeedTitle = (context: PageContext): PageTitle => ({
  name: context.translator.t("Events"),
  sphereSuffix: true,
});

const createEncounterButton = (
  context: PageContext,
  h: HtmlBuilder<EventsFeedMessage>
) =>
  linkButton(
    {
      href: createEncounterHref,
      icon: plusOutline,
      text: context.translator.t("Create Encounter"),
    },
    h
  );

const cards = (
  options: Readonly<{
    context: PageContext;
    items: readonly FeedItem[];
    model: EventsFeedModel;
  }>,
  h: HtmlBuilder<EventsFeedMessage>
): readonly Html[] => {
  const { context, model } = options;

  return options.items.map((item) =>
    FeedItem.match(item, {
      Encounter: ({ card }) =>
        encounterCard(
          {
            card,
            copied: Option.contains(model.copiedShareCode, card.shareCode),
            onCopyShareLink: EventsFeedMessage.ClickedCopyShareLink({
              shareCode: card.shareCode,
            }),
            translator: context.translator,
          },
          h
        ),
      Event: ({ card }) =>
        eventCard(
          {
            card,
            showHidden: model.showHidden,
            translator: context.translator,
          },
          h
        ),
    })
  );
};

const announcements = (
  model: EventsFeedModel,
  context: PageContext,
  h: HtmlBuilder<EventsFeedMessage>
) =>
  model.announcements.length === 0
    ? h.empty
    : h.section(
        [
          h.Id("announcements"),
          h.Class("mb-12"),
          h.AriaLabelledBy("announcements-heading"),
        ],
        [
          h.h2(
            [
              h.Id("announcements-heading"),
              h.Class("text-2xl font-bold mb-6 text-foreground"),
            ],
            [context.translator.t("Organization announcements")]
          ),
          h.div(
            [h.Class("space-y-4")],
            model.announcements.map((announcement) =>
              h.article(
                [h.Key(String(announcement.id)), h.Class("card p-6")],
                [
                  h.h3(
                    [h.Class("text-lg font-semibold text-foreground mb-2")],
                    [announcement.title]
                  ),
                  h.p(
                    [h.Class("text-foreground-secondary whitespace-pre-line")],
                    [announcement.content]
                  ),
                ]
              )
            )
          ),
        ]
      );

const programme = (
  model: EventsFeedModel,
  context: PageContext,
  h: HtmlBuilder<EventsFeedMessage>
) => {
  const { translator } = context;

  if (model.upcoming.length === 0 && model.past.length === 0) {
    return [
      emptyState(
        {
          ...(model.canCreateEncounter
            ? { action: createEncounterButton(context, h) }
            : {}),
          icon: calendarDaysOutline,
          lead: translator.t(
            "There are no upcoming events or public encounters. Please check back later!"
          ),
          title: translator.t("Nothing scheduled yet"),
        },
        h
      ),
    ];
  }

  return [
    h.div(
      [h.Class("flex items-center justify-between mb-6")],
      [
        h.h2(
          [h.Class("text-2xl font-bold text-foreground")],
          [translator.t("Upcoming")]
        ),
        model.canCreateEncounter ? createEncounterButton(context, h) : h.empty,
      ]
    ),
    model.upcoming.length === 0
      ? h.p(
          [h.Class("text-sm text-foreground-muted py-4 mb-8")],
          [translator.t("Nothing coming up.")]
        )
      : feedGrid(
          {
            cards: cards({ context, items: model.upcoming, model }, h),
            extraClass: "mb-12",
          },
          h
        ),
    ...(model.past.length === 0
      ? []
      : [
          h.h2(
            [h.Class("text-2xl font-bold mb-6 text-foreground")],
            [translator.t("Past")]
          ),
          feedGrid(
            { cards: cards({ context, items: model.past, model }, h) },
            h
          ),
        ]),
  ];
};

export const eventsFeedView = defineView<
  EventsFeedModel,
  EventsFeedMessage,
  PageInputs
>((model, inputs, h) => {
  const context = pageContextOf(inputs.shell);

  return h.div(
    [],
    [
      announcements(model, context, h),
      h.div([h.Id("events")], programme(model, context, h)),
    ]
  );
});
