import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { ThemeChoice } from "../../ui/theme-switcher.js";

export const ConsentChoice = Schema.Literals(["accepted", "declined"]);

export const ShellMessage = defineMessageUnion({
  AppliedTheme: { theme: ThemeChoice },
  ChangedSystemColorScheme: {},
  ChangedTheme: { theme: ThemeChoice },
  ChoseConsent: { choice: ConsentChoice },
  DismissedFlash: { id: Schema.String },
  StoredConsent: {},
  SucceededReadStoredConsent: { isAnswered: Schema.Boolean },
  SucceededReadStoredTheme: { theme: ThemeChoice },
  ToggledAccountMenu: { isOpen: Schema.Boolean },
  ToggledNotificationsMenu: { isOpen: Schema.Boolean },
});

export type ShellMessage = typeof ShellMessage.Type;

export { ShellMessage as Message };
