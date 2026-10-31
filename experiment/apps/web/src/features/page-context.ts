import type { ShellModel } from "../client/shell/model.js";
import { translator } from "../ui/i18n.js";
import type { Translator } from "../ui/i18n.js";

export type PageContext = Readonly<{
  shell: ShellModel;
  translator: Translator;
}>;

export type PageInputs = Readonly<{ shell: ShellModel }>;

export const pageContextOf = (shell: ShellModel): PageContext => ({
  shell,
  translator: translator(shell.locale),
});
