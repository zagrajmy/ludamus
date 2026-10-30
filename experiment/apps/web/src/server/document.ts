import { Option, Schema } from "effect";
import * as Server from "foldkit/experimental/server";

import type { Flags } from "../client/model.js";
import { aboutDescription } from "../features/about/view.js";
import { landingDescription } from "../features/landing/view.js";
import { defaultDescription } from "../features/shell/title.js";
import { translator } from "../ui/i18n.js";
import type { Translator } from "../ui/i18n.js";
import { themeColors, themeInitScript } from "../ui/theme-switcher.js";

const ShellHead = Schema.Struct({ shellHead: Schema.String });

const escapeAttribute = (value: string) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

const descriptionOf = (flags: Flags, i18n: Translator) => {
  if (flags.page._tag === "About") {
    return aboutDescription(i18n);
  }

  if (flags.page._tag === "Landing") {
    return landingDescription(i18n);
  }

  return defaultDescription({
    isRootSphere: flags.shell.isRootSphere,
    sphereName: flags.shell.sphere.name,
    translator: i18n,
  });
};

export const shellHead = (options: {
  readonly flags: Flags;
  readonly title: string;
}) => {
  const { flags, title } = options;
  const i18n = translator(flags.shell.locale);
  const description = escapeAttribute(descriptionOf(flags, i18n));
  const { origin } = new URL(flags.shell.requestUrl);
  const image = escapeAttribute(`${origin}/static/og-image.jpg`);
  const escapedTitle = escapeAttribute(title);

  return [
    `<meta name="description" content="${description}">`,
    '<meta property="og:type" content="website">',
    `<meta property="og:url" content="${escapeAttribute(flags.shell.requestUrl)}">`,
    `<meta property="og:site_name" content="${escapeAttribute(flags.shell.sphere.name)}">`,
    `<meta property="og:title" content="${escapedTitle}">`,
    `<meta property="og:description" content="${description}">`,
    `<meta property="og:image" content="${image}">`,
    '<meta name="twitter:card" content="summary_large_image">',
    `<meta name="twitter:title" content="${escapedTitle}">`,
    `<meta name="twitter:description" content="${description}">`,
    `<meta name="twitter:image" content="${image}">`,
    '<link rel="icon" type="image/svg+xml" href="/static/favicon-dev.svg">',
    '<link rel="alternate icon" type="image/x-icon" href="/static/favicon.ico">',
    `<meta name="theme-color" content="${themeColors.light}">`,
    `<script>${themeInitScript}</script>`,
  ].join("\n");
};

export const withShellHead = (
  application: Server.RenderedApplication,
  flags: Flags
) => ({
  ...application,
  shellHead: shellHead({ flags, title: application.title }),
});

export const renderDocument: Server.DocumentRenderer = (application, assets) =>
  Server.renderDocument(application, assets, {
    head: Option.match(Schema.decodeUnknownOption(ShellHead)(application), {
      onNone: () => "",
      onSome: (decoded) => decoded.shellHead,
    }),
    lang: application.lang ?? "pl",
  });
