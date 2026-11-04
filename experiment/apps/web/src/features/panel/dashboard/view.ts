import type { HtmlBuilder } from "foldkit/html";

import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { eventPath } from "../../../client/panel/chrome.js";
import type { DashboardFlags } from "../../../client/panel/dashboard/flags.js";
import type { PanelMessage } from "../../../client/panel/message.js";
import type { Translator } from "../../../ui/i18n.js";
import { icon } from "../../../ui/icon.js";
import type { IconData } from "../../../ui/icon.js";
import {
  buildingOfficeOutline,
  calendarOutline,
  documentTextOutline,
  usersOutline,
} from "../../../ui/icons.js";
import { header } from "../page.js";
import type { PanelPageView } from "../page.js";

type Tone = "blue" | "green" | "purple" | "yellow";

const tones: Readonly<
  Record<Tone, Readonly<{ frame: string; glyph: string }>>
> = {
  blue: {
    frame: "bg-blue-100 dark:bg-blue-100/20",
    glyph: "text-blue-600 dark:text-blue-400",
  },
  green: {
    frame: "bg-green-100 dark:bg-green-100/20",
    glyph: "text-green-600 dark:text-green-400",
  },
  purple: {
    frame: "bg-purple-100 dark:bg-purple-100/20",
    glyph: "text-purple-600 dark:text-purple-400",
  },
  yellow: {
    frame: "bg-yellow-100 dark:bg-yellow-100/20",
    glyph: "text-yellow-600 dark:text-yellow-400",
  },
};

const card = (
  options: Readonly<{
    count: number;
    href: string;
    iconData: IconData;
    label: string;
    note?: string;
    tone: Tone;
  }>,
  h: HtmlBuilder<PanelMessage>
) =>
  h.a(
    [
      h.Href(options.href),
      h.Class(
        "card p-4 lg:p-6 block ring-offset-[.5px] ring-offset-background hover:ring-1 hover:ring-neutral-200 dark:hover:ring-neutral-600 duration-100"
      ),
    ],
    [
      h.div(
        [h.Class("flex items-center justify-between")],
        [
          h.div(
            [],
            [
              h.p(
                [h.Class("text-xs lg:text-sm text-foreground-muted")],
                [options.label]
              ),
              h.p(
                [h.Class("text-2xl lg:text-3xl font-bold text-foreground")],
                [String(options.count)]
              ),
            ]
          ),
          h.div(
            [
              h.Class(
                `w-10 h-10 lg:w-12 lg:h-12 ${tones[options.tone].frame} rounded-lg flex items-center justify-center`
              ),
            ],
            [
              icon(
                options.iconData,
                { class: `w-5 h-5 lg:w-6 lg:h-6 ${tones[options.tone].glyph}` },
                h
              ),
            ]
          ),
        ]
      ),
      options.note === undefined
        ? h.empty
        : h.p(
            [h.Class("text-xs lg:text-sm text-green-600 mt-2 hidden sm:block")],
            [options.note]
          ),
    ]
  );

export const dashboardView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    stats: DashboardFlags;
    translator: Translator;
  }>,
  h: HtmlBuilder<PanelMessage>
): PanelPageView => {
  const { event, stats, translator } = options;
  const { t } = translator;

  return {
    content: [
      h.div(
        [h.Class("p-4")],
        [
          h.div(
            [
              h.Class(
                "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4"
              ),
            ],
            [
              card(
                {
                  count: stats.totalSessions,
                  href: eventPath(event.slug, "timetable/"),
                  iconData: calendarOutline,
                  label: t("All Sessions"),
                  note: `${stats.scheduledSessions} ${t("scheduled")}, ${stats.pendingProposals} ${t("pending")}`,
                  tone: "blue",
                },
                h
              ),
              card(
                {
                  count: stats.hostsCount,
                  href: eventPath(event.slug, "facilitators/"),
                  iconData: usersOutline,
                  label: t("Facilitators"),
                  tone: "purple",
                },
                h
              ),
              card(
                {
                  count: stats.roomsCount,
                  href: eventPath(event.slug, "venues/"),
                  iconData: buildingOfficeOutline,
                  label: t("Rooms"),
                  tone: "green",
                },
                h
              ),
              card(
                {
                  count: stats.totalProposals,
                  href: eventPath(event.slug, "proposals/"),
                  iconData: documentTextOutline,
                  label: t("Proposals"),
                  tone: "yellow",
                },
                h
              ),
            ]
          ),
        ]
      ),
    ],
    header: header({
      subtitle: [`${event.name} - ${t("Overview")}`],
      title: t("Dashboard"),
    }),
    title: t("Dashboard"),
  };
};
