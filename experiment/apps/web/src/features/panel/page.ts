import { Option } from "effect";
import type { Html, HtmlBuilder } from "foldkit/html";

import type { PanelMessage } from "../../client/panel/message.js";
import type { Child } from "../../ui/html.js";
import type { PanelHeader } from "./chrome.js";

export type PanelPageView = Readonly<{
  content: readonly Child[];
  header: PanelHeader;
  title: string;
}>;

export const header = (
  options: Readonly<{
    actions?: Html;
    adornment?: Html;
    subtitle: readonly Child[];
    title: string;
  }>
): PanelHeader => ({
  actions: Option.fromNullishOr(options.actions),
  adornment: Option.fromNullishOr(options.adornment),
  subtitle: options.subtitle,
  title: options.title,
});

export type PanelH = HtmlBuilder<PanelMessage>;

export const tableHead = (
  columns: readonly Readonly<{ align?: "right"; label: string }>[],
  h: PanelH
) =>
  h.thead(
    [h.Class("bg-bg-tertiary")],
    [
      h.tr(
        [],
        columns.map((column) =>
          h.th(
            [
              h.Scope("col"),
              h.Class(
                `px-6 py-3 ${column.align === "right" ? "text-right" : "text-left"} text-xs font-medium text-foreground-muted uppercase tracking-wider`
              ),
            ],
            [column.label]
          )
        )
      ),
    ]
  );

export const tesseraTable = (
  options: Readonly<{
    body: readonly Html[];
    flush?: boolean;
    tableClass?: string;
  }>,
  h: PanelH
) =>
  h.div(
    [
      h.Class(
        options.flush === true
          ? "border-b border-border bg-bg-secondary"
          : "card overflow-hidden"
      ),
    ],
    [
      h.div(
        [h.Class("overflow-x-auto")],
        [
          h.table(
            [
              h.Class(
                `min-w-full divide-y divide-border${options.tableClass === undefined ? "" : ` ${options.tableClass}`}`
              ),
            ],
            options.body
          ),
        ]
      ),
    ]
  );

export const emptyCard = (children: readonly Child[], h: PanelH) =>
  h.div(
    [h.Class("panel-bleed")],
    [h.div([h.Class("card p-8 text-center")], children)]
  );
