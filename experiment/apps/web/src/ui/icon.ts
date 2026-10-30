import type { HtmlBuilder } from "foldkit/html";

import { cx } from "./cx.js";

export type IconPath = Readonly<{
  clipRule?: "evenodd";
  d: string;
  fillRule?: "evenodd";
}>;

export type IconData = Readonly<{
  paths: ReadonlyArray<IconPath>;
  variant: "micro" | "mini" | "outline" | "solid";
}>;

const viewBoxes: Readonly<Record<IconData["variant"], string>> = {
  micro: "0 0 16 16",
  mini: "0 0 20 20",
  outline: "0 0 24 24",
  solid: "0 0 24 24",
};

const sizes: Readonly<Record<IconData["variant"], string>> = {
  micro: "16",
  mini: "20",
  outline: "24",
  solid: "24",
};

export const icon = <Message>(
  data: IconData,
  options: Readonly<{ class?: string }>,
  h: HtmlBuilder<Message>
) =>
  h.svg(
    [
      h.ViewBox(viewBoxes[data.variant]),
      h.Width(sizes[data.variant]),
      h.Height(sizes[data.variant]),
      ...(data.variant === "outline"
        ? [h.Fill("none"), h.StrokeWidth("1.5"), h.Stroke("currentColor")]
        : [h.Fill("currentColor")]),
      h.AriaHidden(true),
      h.Class(cx("shrink-0 align-middle", options.class)),
    ],
    data.paths.map((path) =>
      h.path([
        ...(data.variant === "outline"
          ? [h.StrokeLinecap("round"), h.StrokeLinejoin("round")]
          : []),
        ...(path.fillRule === undefined ? [] : [h.FillRule(path.fillRule)]),
        ...(path.clipRule === undefined ? [] : [h.ClipRule(path.clipRule)]),
        h.D(path.d),
      ])
    )
  );
