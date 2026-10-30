import type { Html, HtmlBuilder } from "foldkit/html";

import type { Child } from "./html.js";

const anchor = /^<a href="([^"]*)">([^<]*)<\/a>$/u;

export const linkedText = <Message>(
  translated: string,
  h: HtmlBuilder<Message>
): ReadonlyArray<Child> =>
  translated.split(/(<a href="[^"]*">[^<]*<\/a>)/u).map((piece) => {
    const link = anchor.exec(piece);

    return link === null
      ? piece.replaceAll("&nbsp;", "\u00a0")
      : h.a([h.Href(link[1] ?? "")], [link[2] ?? ""]);
  });
