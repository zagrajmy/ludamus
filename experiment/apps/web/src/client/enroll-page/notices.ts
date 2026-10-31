import type { EnrollmentNotice } from "@zagrajmy/core/contracts";

import type { Translator } from "../../ui/i18n.js";

export const noticeText = (
  notice: EnrollmentNotice,
  translator: Translator
): string => {
  const fills = [
    ...(notice.items.length === 0
      ? []
      : [
          notice.items
            .map((item) => translator.t(item.msgid, { name: item.name }))
            .join(", "),
        ]),
    ...notice.args,
  ];

  let index = 0;

  return translator.t(notice.msgid, notice.vars).replaceAll("{}", () => {
    const fill = fills[index] ?? "";
    index += 1;

    return fill;
  });
};

export const noticesText = (
  notices: readonly EnrollmentNotice[],
  translator: Translator
): string => notices.map((notice) => noticeText(notice, translator)).join(" ");
