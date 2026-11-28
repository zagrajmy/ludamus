import type { EnrollActions } from "@zagrajmy/core/contracts";
import { formatDate, shortDate } from "@zagrajmy/i18n";
import { DateTime, Predicate } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";

import { EnrollmentSlotMessage } from "../../client/event-page/enrollment-slot.js";
import { enrollmentPath } from "../../client/event-page/enrollment/model.js";
import type { FooterState } from "../../client/event-page/enrollment/model.js";
import type { SessionView } from "../../client/event-page/flags.js";
import { EventPageMessage } from "../../client/event-page/message.js";
import type { EventPageModel } from "../../client/event-page/model.js";
import { cx } from "../../ui/cx.js";
import type { Translator } from "../../ui/i18n.js";
import { icon } from "../../ui/icon.js";
import type { IconData } from "../../ui/icon.js";
import {
  checkCircleMini,
  clockMini,
  exclamationCircleMini,
  userGroupMini,
  userPlusMini,
  xMarkMini,
} from "../../ui/icons.js";
import type { PageContext } from "../page-context.js";

type H = HtmlBuilder<EventPageMessage>;

const ICONS: Readonly<
  Record<EnrollActions["submitIcon"] | "check-circle", IconData>
> = {
  "check-circle": checkCircleMini,
  clock: clockMini,
  "user-plus": userPlusMini,
  "x-mark": xMarkMini,
};

const BADGE_TONE: Readonly<Record<"success" | "warning", string>> = {
  success: "text-success-text",
  warning: "text-warning-text",
};

const clicked = (sessionId: number) =>
  EventPageMessage.GotEnrollmentMessage({
    message: EnrollmentSlotMessage.ClickedFooterChoice({ sessionId }),
  });

const submit = (
  options: Readonly<{
    state: FooterState;
    actions: EnrollActions;
    extraClass: string;
    t: Translator["t"];
  }>,
  h: H
) =>
  h.button(
    [
      h.Type("button"),
      h.Class(cx("btn text-sm", options.extraClass)),
      h.OnClick(clicked(options.state.sessionId)),
      ...(options.state.busy ? [h.AriaDisabled(true)] : []),
    ],
    [
      icon(ICONS[options.actions.submitIcon], { class: "w-4 h-4" }, h),
      ` ${options.t(options.actions.submitLabel)}`,
    ]
  );

const actionsView = (
  state: FooterState,
  actions: EnrollActions,
  t: Translator["t"],
  h: H
): Html => {
  const href = enrollmentPath(state);
  const groupLabel = t(actions.groupLabel);
  const isPrimary = actions.submitValue === "enroll";
  const buttonClass = isPrimary ? "btn-primary" : "btn-secondary";

  return h.div(
    [h.Class("flex items-center gap-2.5")],
    [
      ...(actions.badge === null
        ? []
        : [
            h.span(
              [
                h.Class(
                  cx(
                    "inline-flex items-center gap-1 text-sm font-medium",
                    BADGE_TONE[actions.badge.tone]
                  )
                ),
              ],
              [
                icon(ICONS[actions.badge.icon], { class: "w-4 h-4" }, h),
                ` ${t(actions.badge.label)}`,
              ]
            ),
          ]),
      h.div(
        [h.Class("flex items-center gap-1")],
        actions.badge === null
          ? [
              h.span(
                [h.Class("inline-flex items-stretch")],
                [
                  submit(
                    {
                      actions,
                      extraClass: cx(
                        "rounded-r-none",
                        buttonClass,
                        !isPrimary && "border-r-0"
                      ),
                      state,
                      t,
                    },
                    h
                  ),
                  isPrimary
                    ? h.span(
                        [
                          h.Class(
                            "w-px before:block before:top-0 before:-bottom-0.5 relative before:absolute before:inset-0 after:block after:absolute after:inset-0 after:top-0 after:z-10 after:bg-[hsl(9,90%,69%)] before:bg-[#C54B2F]"
                          ),
                        ],
                        []
                      )
                    : h.span(
                        [
                          h.Class(
                            "after:content-[''] after:block after:w-px after:h-[calc(100%+2px)] after:bg-border/80"
                          ),
                        ],
                        []
                      ),
                  h.a(
                    [
                      h.Href(href),
                      h.Class(
                        cx("btn text-sm rounded-l-none border-l-0", buttonClass)
                      ),
                      h.Title(groupLabel),
                    ],
                    [t("with others")]
                  ),
                ]
              ),
            ]
          : [
              submit({ actions, extraClass: "btn-secondary", state, t }, h),
              h.a(
                [
                  h.Href(href),
                  h.Class("btn btn-secondary text-sm px-2.5"),
                  h.Title(groupLabel),
                ],
                [
                  icon(userGroupMini, { class: "w-4 h-4" }, h),
                  h.span([h.Class("sr-only")], [groupLabel]),
                ]
              ),
            ]
      ),
    ]
  );
};

const opensView = (
  state: FooterState,
  opensAt: DateTime.Utc,
  translator: Translator,
  h: H
) => {
  const iso = DateTime.formatIso(opensAt);
  const describedBy = `enroll-opens-${state.sessionId}`;

  return h.div(
    [h.Class("flex items-center gap-2.5")],
    [
      h.span(
        [
          h.Id(describedBy),
          h.Class("text-xs text-right text-foreground-muted"),
        ],
        [
          translator.t("Your enrollment opens %(day)s at %(time)s", {
            day: shortDate(translator.locale, iso),
            time: formatDate({
              format: "G:i",
              locale: translator.locale,
              value: iso,
            }),
          }),
        ]
      ),
      h.button(
        [
          h.Type("button"),
          h.Class("btn btn-primary text-sm"),
          h.Disabled(true),
          h.AriaDescribedBy(describedBy),
        ],
        [
          icon(userPlusMini, { class: "w-4 h-4" }, h),
          ` ${translator.t("Enroll")}`,
        ]
      ),
    ]
  );
};

export const hasEnrollmentFooter = (state: FooterState) =>
  state.footer.actions !== null ||
  state.footer.opensAt !== null ||
  state.notice !== "" ||
  state.error !== "";

export const enrollmentFooterActions = (
  state: FooterState,
  translator: Translator,
  h: H
): Html => {
  const { t } = translator;
  const { actions, opensAt } = state.footer;

  return h.div(
    [
      h.Id(`enroll-actions-${state.sessionId}`),
      h.Class("flex flex-col items-end gap-1.5"),
    ],
    [
      ...(state.error === ""
        ? []
        : [
            h.p(
              [
                h.Class(
                  "text-xs text-danger-text flex items-center gap-1 text-right"
                ),
                h.Role("alert"),
                h.AriaLive("assertive"),
              ],
              [
                icon(
                  exclamationCircleMini,
                  { class: "w-3.5 h-3.5 shrink-0" },
                  h
                ),
                h.span([], [state.error]),
              ]
            ),
          ]),
      ...(state.notice === ""
        ? []
        : [
            h.p(
              [
                h.Class(
                  "text-xs text-foreground-muted flex items-center gap-1 text-right"
                ),
                h.Role("status"),
                h.AriaLive("polite"),
              ],
              [
                icon(checkCircleMini, { class: "w-3.5 h-3.5 shrink-0" }, h),
                h.span([], [state.notice]),
              ]
            ),
          ]),
      ...(opensAt === null ? [] : [opensView(state, opensAt, translator, h)]),
      ...(actions === null ? [] : [actionsView(state, actions, t, h)]),
    ]
  );
};

export const seatNote = (
  model: EventPageModel,
  session: SessionView,
  context: PageContext,
  h: H
): Html => {
  const settled =
    Predicate.isTagged(model.enrollment, "Seat") &&
    model.enrollment.state.sessionId === session.id &&
    model.enrollment.state.footer.actions === null;

  if (!settled || !(session.userEnrolled || session.userWaiting)) {
    return h.empty;
  }

  return h.p(
    [h.Class("text-sm text-foreground-secondary")],
    [
      context.translator.t(
        session.userEnrolled
          ? "You are enrolled in this session"
          : "You are on the waiting list"
      ),
    ]
  );
};
