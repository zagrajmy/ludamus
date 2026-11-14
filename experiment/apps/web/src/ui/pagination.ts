import type { HtmlBuilder } from "foldkit/html";

import type { Translator } from "./i18n.js";

export type PageLinks = Readonly<{
  next?: string;
  number: number;
  pageSize: number;
  pageSizes: readonly Readonly<{ href: string; size: number }>[];
  previous?: string;
  total: number;
  totalPages: number;
}>;

export const pagination = <Message>(
  options: Readonly<{
    onChangePageSize: (href: string) => Message;
    page: PageLinks;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  const { page, translator } = options;
  const smallest = page.pageSizes[0]?.size ?? 0;

  if (page.total <= smallest) {
    return h.empty;
  }

  return h.div(
    [h.Class("flex items-center justify-between mt-4 text-sm")],
    [
      h.span(
        [h.Class("text-foreground-muted")],
        [
          translator.t("Page %(page)s of %(total)s", {
            page: page.number,
            total: page.totalPages,
          }),
        ]
      ),
      h.div(
        [h.Class("flex items-center gap-3")],
        [
          h.label(
            [h.Class("flex items-center gap-2 text-foreground-muted")],
            [
              translator.t("Per page:"),
              h.select(
                [
                  h.Class(
                    "w-full px-3 py-2 rounded-lg border border-border bg-bg-secondary text-foreground text-sm"
                  ),
                  h.OnChange(options.onChangePageSize),
                ],
                page.pageSizes.map((choice) =>
                  h.option(
                    [
                      h.Value(choice.href),
                      ...(choice.size === page.pageSize
                        ? [h.Selected(true)]
                        : []),
                    ],
                    [String(choice.size)]
                  )
                )
              ),
            ]
          ),
          page.previous === undefined
            ? h.empty
            : h.a(
                [h.Href(page.previous), h.Class("btn btn-secondary text-sm")],
                [translator.t("Previous")]
              ),
          page.next === undefined
            ? h.empty
            : h.a(
                [h.Href(page.next), h.Class("btn btn-secondary text-sm")],
                [translator.t("Next")]
              ),
        ]
      ),
    ]
  );
};
