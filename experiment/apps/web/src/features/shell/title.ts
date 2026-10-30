import type { Translator } from "../../ui/i18n.js";

export type PageTitle = Readonly<{ name: string; sphereSuffix: boolean }>;

export const bullet = " • ";

export const documentTitle = (options: {
  readonly isRootSphere: boolean;
  readonly page: PageTitle;
  readonly sphereName: string;
}) =>
  [
    options.page.name,
    ...(options.page.sphereSuffix ? [options.sphereName] : []),
    ...(options.isRootSphere ? [] : ["Zagrajmy"]),
  ]
    .filter((part) => part !== "")
    .join(bullet);

export const defaultDescription = (options: {
  readonly isRootSphere: boolean;
  readonly sphereName: string;
  readonly translator: Translator;
}) =>
  options.isRootSphere
    ? options.translator.t(
        "A convention without spreadsheet chaos. Programme proposals, a schedule of rooms and tracks, sign-ups with seat limits and a waitlist."
      )
    : options.translator.t("Programme and sign-ups for %(sphere)s.", {
        sphere: options.sphereName,
      });
