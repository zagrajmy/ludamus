import type { HtmlBuilder } from "foldkit/html";

import type { Child } from "./html.js";

const anchor = /^<a href="(?<href>[^"]*)">(?<label>[^<]*)<\/a>$/u;

export const linkedText = <Message>(
  translated: string,
  h: HtmlBuilder<Message>
): readonly Child[] =>
  translated.split(/(?<anchor><a href="[^"]*">[^<]*<\/a>)/u).map((piece) => {
    const link = anchor.exec(piece);

    return link === null
      ? piece.replaceAll("&nbsp;", "\u00A0")
      : h.a([h.Href(link.groups?.href ?? "")], [link.groups?.label ?? ""]);
  });
