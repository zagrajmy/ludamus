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
  GotStoredConsent: { isAnswered: Schema.Boolean },
  GotStoredTheme: { theme: ThemeChoice },
  StoredConsent: {},
  ToggledAccountMenu: { isOpen: Schema.Boolean },
});

export type ShellMessage = typeof ShellMessage.Type;
