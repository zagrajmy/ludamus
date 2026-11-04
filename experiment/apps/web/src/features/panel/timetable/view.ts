import { Option } from "effect";

import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { eventPath } from "../../../client/panel/chrome.js";
import { PanelMessage } from "../../../client/panel/message.js";
import type { TimetableModel } from "../../../client/panel/timetable/flags.js";
import { linkButton } from "../../../ui/button.js";
import type { Translator } from "../../../ui/i18n.js";
import { documentTextOutline } from "../../../ui/icons.js";
import { header } from "../page.js";
import type { PanelH, PanelPageView } from "../page.js";
import { panelTabs } from "../tabs.js";

export const timetableTabs = (slug: string, translator: Translator) => [
  {
    href: eventPath(slug, "timetable/"),
    key: "timetable",
    label: translator.t("Schedule"),
  },
  {
    href: eventPath(slug, "timetable/log/"),
    key: "log",
    label: translator.t("Activity Log"),
  },
  {
    href: eventPath(slug, "timetable/overview/"),
    key: "overview",
    label: translator.t("Organizer Overview"),
  },
  {
    href: eventPath(slug, "timetable/problems/"),
    key: "problems",
    label: translator.t("Problems"),
  },
  {
    href: eventPath(slug, "timetable/confirmations/"),
    key: "confirmations",
    label: translator.t("Confirmations"),
  },
];

export const timetableView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: TimetableModel;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t } = translator;
  const sessions = model.days.flatMap((day) => day.sessions);

  const selected = model.selected.pipe(
    Option.flatMap((id) =>
      Option.fromNullishOr(sessions.find((session) => session.id === id))
    )
  );

  const detail = Option.match(selected, {
    onNone: () =>
      h.p(
        [h.Class("text-sm text-foreground-muted")],
        [t("Select a session to see its details.")]
      ),
    onSome: (session) =>
      h.div(
        [h.Id("left-pane"), h.Class("space-y-3")],
        [
          h.h3(
            [h.Class("text-base font-semibold text-foreground")],
            [session.title]
          ),
          h.div(
            [h.Class("space-y-1")],
            session.facilitators.length === 0
              ? [
                  h.div(
                    [h.Class("text-sm text-foreground-muted")],
                    [t("No facilitator")]
                  ),
                ]
              : session.facilitators.map((name) =>
                  h.div([h.Class("text-sm text-foreground")], [name])
                )
          ),
          h.div(
            [h.Class("mb-3")],
            [
              linkButton(
                {
                  href: eventPath(event.slug, `proposals/${session.id}/`),
                  icon: documentTextOutline,
                  size: "sm",
                  text: t("View proposal"),
                  variant: "secondary",
                },
                h
              ),
            ]
          ),
          h.p(
            [h.Class("text-sm text-foreground-muted")],
            [`${session.room} · ${session.timeLabel}`]
          ),
        ]
      ),
  });

  const body = [
    h.div(
      [h.Class("grid gap-6 lg:grid-cols-[20rem_1fr]")],
      [
        h.div([h.Class("card p-4")], [detail]),
        h.div(
          [h.Class("space-y-6")],
          model.days.length === 0
            ? [
                h.p(
                  [h.Class("text-sm text-foreground-muted")],
                  [t("Nothing is scheduled yet.")]
                ),
              ]
            : model.days.map((day) =>
                h.section(
                  [h.Key(day.label)],
                  [
                    h.h3(
                      [
                        h.Class(
                          "text-sm font-semibold text-foreground-muted uppercase tracking-wider mb-2"
                        ),
                      ],
                      [day.label]
                    ),
                    h.ul(
                      [h.Class("grid gap-2 sm:grid-cols-2 xl:grid-cols-3")],
                      day.sessions.map((session) =>
                        h.li(
                          [h.Key(String(session.id))],
                          [
                            h.button(
                              [
                                h.Type("button"),
                                h.Class(
                                  "timetable-session block w-full text-left rounded-md border border-border bg-bg-secondary px-3 py-2 text-xs hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                                ),
                                h.DataAttribute(
                                  "session-pk",
                                  String(session.id)
                                ),
                                h.Title(session.title),
                                h.OnClick(
                                  PanelMessage.SelectedTimetableSession({
                                    id: session.id,
                                  })
                                ),
                              ],
                              [
                                h.div(
                                  [
                                    h.Class(
                                      "font-medium text-foreground wrap-anywhere"
                                    ),
                                  ],
                                  [session.title]
                                ),
                                h.div(
                                  [h.Class("text-foreground-muted")],
                                  [`${session.timeLabel} · ${session.room}`]
                                ),
                              ]
                            ),
                          ]
                        )
                      )
                    ),
                  ]
                )
              )
        ),
      ]
    ),
  ];

  return {
    content: [
      panelTabs(
        {
          active: "timetable",
          body,
          tabs: timetableTabs(event.slug, translator),
        },
        h
      ),
    ],
    header: header({
      subtitle: [`${event.name} · ${t("Schedule")}`],
      title: t("Schedule"),
    }),
    title: t("Schedule"),
  };
};
