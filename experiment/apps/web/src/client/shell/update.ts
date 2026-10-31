import type { Update } from "foldkit";
import { modifyFields } from "foldkit/struct";

import { ApplyTheme, StoreConsent } from "./command.js";
import { ShellMessage } from "./message.js";
import type { ShellModel } from "./model.js";

type Return = Update.Return<ShellModel, ShellMessage>;

export const updateShell = (model: ShellModel, message: ShellMessage): Return =>
  ShellMessage.match<Return>(message, {
    AppliedTheme: () => ({ model }),
    ChangedSystemColorScheme: () =>
      model.isThemeRead && model.theme === "system"
        ? { commands: [ApplyTheme({ persist: false, theme: "system" })], model }
        : { model },
    ChangedTheme: ({ theme }) => ({
      commands: [ApplyTheme({ persist: true, theme })],
      model: modifyFields(model, {
        isThemeRead: () => true,
        theme: () => theme,
      }),
    }),
    ChoseConsent: ({ choice }) => ({
      commands: [StoreConsent({ choice })],
      model: modifyFields(model, { isConsentAnswered: () => true }),
    }),
    DismissedFlash: ({ id }) => ({
      model: modifyFields(model, {
        flashes: (flashes) => flashes.filter((flash) => flash.id !== id),
      }),
    }),
    GotStoredConsent: ({ isAnswered }) => ({
      model: modifyFields(model, { isConsentAnswered: () => isAnswered }),
    }),
    GotStoredTheme: ({ theme }) => ({
      model: modifyFields(model, {
        isThemeRead: () => true,
        theme: () => theme,
      }),
    }),
    StoredConsent: () => ({ model }),
    ToggledAccountMenu: ({ isOpen }) => ({
      model: modifyFields(model, { isAccountMenuOpen: () => isOpen }),
    }),
    ToggledNotificationsMenu: ({ isOpen }) => ({
      model: modifyFields(model, { isNotificationsOpen: () => isOpen }),
    }),
  });
