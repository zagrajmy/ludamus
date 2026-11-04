import { Option } from "effect";

import { PanelAction } from "../../../client/panel/action.js";
import type { PanelCurrentEvent } from "../../../client/panel/chrome.js";
import { eventPath } from "../../../client/panel/chrome.js";
import { PanelMessage } from "../../../client/panel/message.js";
import { MENU_ID } from "../../../client/panel/proposals/command.js";
import { ProposalDetailMessage } from "../../../client/panel/proposals/message.js";
import type { ProposalDetailModel } from "../../../client/panel/proposals/model.js";
import type { SessionStatusValue } from "../../../client/panel/schemas.js";
import { linkButton } from "../../../ui/button.js";
import { cx } from "../../../ui/cx.js";
import type { Child } from "../../../ui/html.js";
import type { Translator } from "../../../ui/i18n.js";
import { icon } from "../../../ui/icon.js";
import { ellipsisVerticalOutline } from "../../../ui/icons.js";
import { menuSurfaceClass } from "../../../ui/menu.js";
import { crumbs } from "../chrome.js";
import { header } from "../page.js";
import type { PanelH, PanelPageView } from "../page.js";
import { statusBadge } from "../status.js";
import { panelTabs } from "../tabs.js";

const toDetail = (message: ProposalDetailMessage) =>
  PanelMessage.RelayedProposalDetail({ message });

type Transition = Readonly<{ label: string; status: SessionStatusValue }>;

const transitions = (status: SessionStatusValue, translator: Translator) => {
  const { t } = translator;
  const accept: Transition = { label: t("Accept"), status: "accepted" };

  const pending: Transition = {
    label: t("Move to pending"),
    status: "pending",
  };

  const hold: Transition = { label: t("Hold"), status: "on_hold" };
  const reject: Transition = { label: t("Reject"), status: "rejected" };

  const flows: Readonly<
    Record<
      SessionStatusValue,
      Readonly<{
        menu: readonly Transition[];
        primary: Option.Option<Transition>;
      }>
    >
  > = {
    accepted: { menu: [pending, hold, reject], primary: Option.none() },
    on_hold: { menu: [pending, reject], primary: Option.some(accept) },
    pending: { menu: [hold, reject], primary: Option.some(accept) },
    rejected: { menu: [accept, hold], primary: Option.some(pending) },
  };

  return flows[status];
};

const detailUrl = (model: ProposalDetailModel) => {
  const base = `/panel/event/${model.eventSlug}/proposals/${model.id}/`;
  const defaultBack = `/panel/event/${model.eventSlug}/proposals/`;

  return model.backUrl === defaultBack
    ? base
    : `${base}?${new URLSearchParams({ next: model.backUrl }).toString()}`;
};

const changeStatus = (model: ProposalDetailModel, status: SessionStatusValue) =>
  PanelMessage.RequestedAction({
    action: PanelAction.ChangeProposalStatus({
      eventSlug: model.eventSlug,
      next: detailUrl(model),
      proposalId: model.id,
      status,
    }),
  });

const moreMenu = (
  model: ProposalDetailModel,
  items: readonly Transition[],
  translator: Translator,
  h: PanelH
) =>
  h.div(
    [
      h.Class("relative"),
      h.DataAttribute("menu", ""),
      h.OnKeyDownPreventDefault((key) =>
        key === "Escape" && model.isMenuOpen
          ? Option.some(
              toDetail(ProposalDetailMessage.ClosedMenu({ refocus: true }))
            )
          : Option.none()
      ),
      h.OnFocusLeave(
        toDetail(ProposalDetailMessage.ClosedMenu({ refocus: false }))
      ),
    ],
    [
      h.button(
        [
          h.Type("button"),
          h.DataAttribute("menu-button", ""),
          h.AriaControls(MENU_ID),
          h.AriaExpanded(model.isMenuOpen),
          h.Class(
            "cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary btn btn-secondary px-4 py-2 text-sm"
          ),
          h.OnClick(
            toDetail(
              model.isMenuOpen
                ? ProposalDetailMessage.ClosedMenu({ refocus: false })
                : ProposalDetailMessage.OpenedMenu({ focusFirst: false })
            )
          ),
          h.OnKeyDownPreventDefault((key) =>
            (key === "Enter" || key === " " || key === "ArrowDown") &&
            !model.isMenuOpen
              ? Option.some(
                  toDetail(
                    ProposalDetailMessage.OpenedMenu({ focusFirst: true })
                  )
                )
              : Option.none()
          ),
        ],
        [
          h.span([h.Class("btn-label")], [translator.t("More")]),
          icon(ellipsisVerticalOutline, { class: "w-4 h-4" }, h),
        ]
      ),
      h.div(
        [
          h.Id(MENU_ID),
          h.DataAttribute("menu-panel", ""),
          ...(model.isMenuOpen ? [] : [h.Hidden(true)]),
          h.Class("absolute top-full z-50 pt-2 right-0"),
        ],
        [
          h.div(
            [
              h.Class(
                menuSurfaceClass({
                  extraClass:
                    "min-w-52 p-1 rounded-xl border border-border bg-bg-secondary shadow-(--shadow-elevated)",
                  isOpen: model.isMenuOpen,
                  origin: "origin-top",
                })
              ),
              h.DataAttribute("menu-surface", ""),
              ...(model.isMenuOpen
                ? [h.DataAttribute("menu-visible", "")]
                : []),
            ],
            items.map((item) =>
              h.button(
                [
                  h.Key(item.status),
                  h.Type("button"),
                  h.DataAttribute("menu-item", ""),
                  h.Class(
                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-foreground-secondary transition-colors hover:bg-bg-tertiary focus-visible:bg-bg-tertiary focus-visible:outline-none"
                  ),
                  h.OnClick(changeStatus(model, item.status)),
                ],
                [item.label]
              )
            )
          ),
        ]
      ),
    ]
  );

const card = (title: string, body: readonly Child[], h: PanelH, extra = "") =>
  h.div(
    [h.Class(cx("card mb-6", extra))],
    [
      h.div(
        [h.Class("card-body")],
        [
          h.h3(
            [h.Class("text-sm font-medium text-foreground-muted mb-2")],
            [title]
          ),
          ...body,
        ]
      ),
    ]
  );

const fact = (term: string, value: string, h: PanelH) =>
  h.div(
    [],
    [
      h.dt([h.Class("text-xs text-foreground-muted")], [term]),
      h.dd([h.Class("text-foreground")], [value]),
    ]
  );

export const proposalDetailView = (
  options: Readonly<{
    event: PanelCurrentEvent;
    model: ProposalDetailModel;
    translator: Translator;
  }>,
  h: PanelH
): PanelPageView => {
  const { event, model, translator } = options;
  const { t } = translator;
  const isScheduled = model.scheduled !== "";
  const flow = transitions(model.status, translator);
  const editHref = `${eventPath(event.slug, `proposals/${model.id}/edit/`)}?${new URLSearchParams({ next: model.backUrl }).toString()}`;

  const actions = h.div(
    [h.Class("flex flex-wrap items-center gap-2")],
    [
      statusBadge({ isScheduled, status: model.status, translator }, h),
      linkButton({ href: editHref, text: t("Edit"), variant: "secondary" }, h),
      ...(isScheduled
        ? []
        : [
            ...Option.match(flow.primary, {
              onNone: () => [],
              onSome: (primary) => [
                h.button(
                  [
                    h.Type("button"),
                    h.Class("btn btn-primary px-4 py-2 text-sm max-md:w-full"),
                    h.OnClick(changeStatus(model, primary.status)),
                  ],
                  [h.span([h.Class("btn-label")], [primary.label])]
                ),
              ],
            }),
            moreMenu(model, flow.menu, translator, h),
          ]),
    ]
  );

  const body = [
    h.div(
      [
        h.Class(
          "mb-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-foreground-muted"
        ),
      ],
      [
        h.span(
          [],
          [
            `${t("Slug")}: `,
            h.span([h.Class("font-mono select-all")], [model.slug]),
          ]
        ),
        h.span([], [`${t("Created")}: ${model.createdLabel}`]),
        h.span([], [`${t("Last modified")}: ${model.modifiedLabel}`]),
      ]
    ),
    isScheduled
      ? h.div(
          [h.Class("card mb-6")],
          [
            h.div(
              [
                h.Class(
                  "card-body flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
                ),
              ],
              [h.p([h.Class("text-sm text-foreground")], [model.scheduled])]
            ),
          ]
        )
      : h.empty,
    h.div(
      [h.Class("card mb-6")],
      [
        h.div(
          [h.Class("card-body")],
          [
            h.h3(
              [h.Class("text-sm font-medium text-foreground-muted mb-2")],
              [t("Presenter")]
            ),
            h.p([h.Class("text-foreground")], [model.facilitatorName]),
            model.presenter === ""
              ? h.empty
              : h.p(
                  [
                    h.Class("text-foreground-muted text-sm mt-1"),
                    h.DataAttribute("ph-mask", ""),
                  ],
                  [model.presenter]
                ),
            model.contactEmail === ""
              ? h.empty
              : h.dl(
                  [h.Class("mt-3")],
                  [
                    h.dt(
                      [h.Class("text-xs text-foreground-muted")],
                      [t("Contact Email")]
                    ),
                    h.dd(
                      [h.Class("text-foreground")],
                      [
                        h.a(
                          [
                            h.Href(`mailto:${model.contactEmail}`),
                            h.Class("text-primary hover:underline"),
                          ],
                          [model.contactEmail]
                        ),
                      ]
                    ),
                  ]
                ),
          ]
        ),
      ]
    ),
    model.coverUrl === ""
      ? h.empty
      : h.div(
          [h.Class("card mb-6 overflow-hidden")],
          [
            h.img([
              h.Src(model.coverUrl),
              h.Alt(model.title),
              h.Width("960"),
              h.Height("540"),
              h.Class("aspect-video w-full object-cover"),
            ]),
          ]
        ),
    model.description === ""
      ? h.empty
      : card(
          t("Description"),
          [
            h.p(
              [h.Class("text-foreground whitespace-pre-wrap")],
              [model.description]
            ),
          ],
          h
        ),
    card(
      t("Details"),
      [
        h.dl(
          [h.Class("grid grid-cols-2 gap-4")],
          [
            model.categoryName === ""
              ? h.empty
              : fact(t("Category"), model.categoryName, h),
            fact(t("Participants Limit"), String(model.participantsLimit), h),
            model.durationLabel === ""
              ? h.empty
              : fact(t("Duration"), model.durationLabel, h),
            model.minAge === 0
              ? h.empty
              : fact(t("Minimum Age"), String(model.minAge), h),
          ]
        ),
      ],
      h
    ),
    model.tracks.length === 0
      ? h.empty
      : card(
          t("Tracks"),
          [
            h.div(
              [h.Class("flex flex-wrap gap-2")],
              model.tracks.map((track) =>
                h.a(
                  [
                    h.Key(track.slug),
                    h.Href(eventPath(event.slug, `tracks/${track.slug}/edit/`)),
                    h.Class(
                      "inline-flex items-center rounded-full border border-border px-3 py-1 text-sm text-foreground hover:border-primary hover:text-primary"
                    ),
                  ],
                  [track.name]
                )
              )
            ),
          ],
          h
        ),
    model.preferredSlots.length === 0
      ? h.empty
      : card(
          t("Preferred time slots"),
          [
            h.ul(
              [h.Class("space-y-1")],
              model.preferredSlots.map((slot) =>
                h.li([h.Class("text-foreground text-sm")], [slot])
              )
            ),
          ],
          h
        ),
    model.fieldValues.length === 0
      ? h.empty
      : card(
          t("Session Fields"),
          [
            h.dl(
              [h.Class("space-y-3")],
              model.fieldValues.map((value) => fact(value.term, value.value, h))
            ),
          ],
          h
        ),
    h.div(
      [h.Class("card mb-6")],
      [
        h.div(
          [h.Class("card-body")],
          [
            h.h3(
              [h.Class("text-sm font-medium text-foreground-muted mb-4")],
              [t("Facilitators")]
            ),
            model.facilitators.length === 0
              ? h.p(
                  [h.Class("text-foreground-muted text-sm")],
                  [t("No facilitators assigned.")]
                )
              : h.ul(
                  [h.Class("space-y-1")],
                  model.facilitators.map((facilitator) =>
                    h.li(
                      [h.Key(facilitator.slug), h.Class("text-sm")],
                      [
                        h.a(
                          [
                            h.Href(
                              eventPath(
                                event.slug,
                                `facilitators/${facilitator.slug}/`
                              )
                            ),
                            h.Class("text-primary hover:underline"),
                          ],
                          [facilitator.name]
                        ),
                      ]
                    )
                  )
                ),
          ]
        ),
      ]
    ),
    h.section(
      [
        h.Class(
          "mt-8 flex flex-col gap-3 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between"
        ),
      ],
      [
        h.div(
          [],
          [
            h.h3(
              [h.Class("text-sm font-medium text-foreground")],
              [t("Delete proposal")]
            ),
            h.p(
              [h.Class("mt-1 text-sm text-foreground-muted")],
              [
                t(
                  "It will disappear from the event and timetable. You can restore it from the proposals list."
                ),
              ]
            ),
          ]
        ),
        h.button(
          [
            h.Type("button"),
            h.Class("btn btn-danger px-3 py-1.5 text-xs gap-1.5 rounded-xl"),
            h.OnClick(
              PanelMessage.RequestedConfirm({
                action: PanelAction.DeleteProposal({
                  eventSlug: event.slug,
                  proposalId: model.id,
                }),
                prompt: {
                  confirmLabel: t("Delete proposal"),
                  icon: "exclamation-triangle",
                  message: t(
                    "Are you sure you want to delete this proposal? It will disappear from the event and timetable."
                  ),
                },
              })
            ),
          ],
          [h.span([h.Class("btn-label")], [t("Delete proposal")])]
        ),
      ]
    ),
  ];

  return {
    content: [
      panelTabs(
        {
          active: "details",
          body,
          tabs: [
            {
              href: eventPath(event.slug, `proposals/${model.id}/`),
              key: "details",
              label: t("Details"),
            },
            {
              href: eventPath(event.slug, `proposals/${model.id}/history/`),
              key: "history",
              label: t("Change history"),
            },
          ],
        },
        h
      ),
    ],
    header: header({
      actions,
      subtitle: crumbs(
        {
          backHref: model.backUrl,
          backLabel: t("Proposals"),
          eventName: event.name,
          eventSlug: event.slug,
        },
        h
      ),
      title: model.title,
    }),
    title: `${model.title} • ${t("Proposals")}`,
  };
};
