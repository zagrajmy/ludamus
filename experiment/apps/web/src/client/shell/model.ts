import { Schema } from "effect";

import { ThemeChoice } from "../../ui/theme-switcher.js";
import { ShellFlags } from "./flags.js";

export const ShellModel = Schema.Struct({
  ...ShellFlags.fields,
  isAccountMenuOpen: Schema.Boolean,
  isConsentAnswered: Schema.Boolean,
  isNotificationsOpen: Schema.Boolean,
  isThemeRead: Schema.Boolean,
  theme: ThemeChoice,
});

export type ShellModel = typeof ShellModel.Type;

export const initShell = (flags: ShellFlags): ShellModel => ({
  ...flags,
  isAccountMenuOpen: false,
  isConsentAnswered: false,
  isNotificationsOpen: false,
  isThemeRead: false,
  theme: "system",
});
