import type { HtmlBuilder } from "foldkit/html";

import { EnrollmentSlotMessage } from "../../client/event-page/enrollment-slot.js";
import type { SessionView } from "../../client/event-page/flags.js";
import { EventPageMessage } from "../../client/event-page/message.js";
import { bookmarkOutline, bookmarkSolid } from "../../ui/bookmark-icons.js";
import { cx } from "../../ui/cx.js";
import { icon } from "../../ui/icon.js";
import type { PageContext } from "../page-context.js";

const ICON_CLASS = "shrink-0 align-middle size-4";

const CORAL = "text-coral-600 dark:text-coral-400";

export const bookmarkToggle = (
  options: Readonly<{
    context: PageContext;
    session: SessionView;
    wrapper: string;
  }>,
  h: HtmlBuilder<EventPageMessage>
) => {
  const { session } = options;
  const bookmarked = session.userBookmarked;

  return h.span(
    [h.Class(cx("bookmark-affordance print:hidden", options.wrapper))],
    [
      h.button(
        [
          h.Type("button"),
          h.DataAttribute("bookmark-toggle", ""),
          h.DataAttribute("session-id", String(session.id)),
          h.AriaPressed(bookmarked ? "true" : "false"),
          h.Class(
            cx(
              "before:inset-0 before:-inset-y-2.5 before:absolute before:bg-transparent icon-btn icon-btn-clear relative z-20 shrink-0 self-center border border-transparent hover:border-border hover:bg-bg-tertiary gap-0.75 pointer-events-auto",
              bookmarked && CORAL
            )
          ),
          h.OnClick(
            EventPageMessage.GotEnrollmentMessage({
              message: EnrollmentSlotMessage.ClickedBookmark({
                sessionId: session.id,
              }),
            })
          ),
        ],
        [
          icon(
            bookmarked ? bookmarkSolid : bookmarkOutline,
            { class: ICON_CLASS },
            h
          ),
          h.span(
            [h.Class("sr-only")],
            [options.context.translator.t("Bookmark session")]
          ),
          h.span(
            [
              h.DataAttribute("bookmark-count", ""),
              h.Class(
                cx(
                  "text-xs tabular-nums",
                  session.bookmarkCount === 0 && "hidden"
                )
              ),
            ],
            [String(session.bookmarkCount)]
          ),
        ]
      ),
    ]
  );
};
