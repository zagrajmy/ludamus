import type { SessionStatusValue } from "../../client/panel/schemas.js";
import type { Translator } from "../../ui/i18n.js";
import type { PanelH } from "./page.js";

const pill =
  "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium";

export const statusBadge = (
  options: Readonly<{
    isScheduled: boolean;
    status: SessionStatusValue;
    translator: Translator;
  }>,
  h: PanelH
) => {
  const { t } = options.translator;

  if (options.status === "pending") {
    return h.span(
      [h.Class(`${pill} bg-warning-bg text-warning-text`)],
      [t("Pending")]
    );
  }

  if (options.status === "accepted") {
    return options.isScheduled
      ? h.span([h.Class(`${pill} bg-info-bg text-info-text`)], [t("Scheduled")])
      : h.span(
          [h.Class(`${pill} bg-success-bg text-success-text`)],
          [t("Accepted")]
        );
  }

  return options.status === "on_hold"
    ? h.span(
        [h.Class(`${pill} bg-bg-tertiary text-foreground-muted`)],
        [t("On hold")]
      )
    : h.span(
        [h.Class(`${pill} bg-danger-bg text-danger-text`)],
        [t("Rejected")]
      );
};
