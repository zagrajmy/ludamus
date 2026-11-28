import { Effect, Option, Schema } from "effect";
import { Command } from "foldkit";

import { consentStorageKey } from "../../ui/consent-banner.js";
import {
  ThemeChoice,
  themeColors,
  themeStorageKey,
} from "../../ui/theme-switcher.js";
import { ConsentChoice, ShellMessage } from "./message.js";

export const darkSchemeQuery = "(prefers-color-scheme: dark)";

const readStorage = (key: string) =>
  Effect.try(() => Option.fromNullishOr(window.localStorage.getItem(key))).pipe(
    Effect.orElseSucceed(() => Option.none<string>())
  );

const writeStorage = (key: string, value: Option.Option<string>) =>
  Effect.try(() => {
    Option.match(value, {
      onNone: () => {
        window.localStorage.removeItem(key);
      },
      onSome: (stored) => {
        window.localStorage.setItem(key, stored);
      },
    });
  }).pipe(Effect.ignore);

const decodeTheme = Schema.decodeUnknownOption(ThemeChoice);

export const ReadStoredTheme = Command.define("ReadStoredTheme", {
  execute: readStorage(themeStorageKey).pipe(
    Effect.map((stored) =>
      ShellMessage.SucceededReadStoredTheme({
        theme: stored.pipe(
          Option.flatMap(decodeTheme),
          Option.getOrElse((): ThemeChoice => "system")
        ),
      })
    )
  ),
  messages: [ShellMessage.SucceededReadStoredTheme],
});

const resolveTheme = (theme: ThemeChoice) => {
  if (theme !== "system") {
    return theme;
  }

  return window.matchMedia(darkSchemeQuery).matches ? "dark" : "light";
};

const paintTheme = (theme: ThemeChoice) =>
  Effect.sync(() => {
    const root = document.documentElement;
    const resolved = resolveTheme(theme);
    const pause = document.createElement("style");
    pause.append(
      document.createTextNode("*,*::before,*::after{transition:none!important}")
    );
    document.head.append(pause);
    root.classList.remove("light", "dark");
    root.classList.add(resolved);
    root.style.colorScheme = resolved;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute(
        "content",
        resolved === "dark" ? themeColors.dark : themeColors.light
      );
    window.getComputedStyle(pause).getPropertyValue("opacity");
    pause.remove();
  });

export const ApplyTheme = Command.define("ApplyTheme", {
  args: { persist: Schema.Boolean, theme: ThemeChoice },
  execute: ({ persist, theme }) =>
    Effect.gen(function* applyTheme() {
      if (persist) {
        yield* writeStorage(
          themeStorageKey,
          theme === "system" ? Option.none() : Option.some(theme)
        );
      }

      yield* paintTheme(theme);

      return ShellMessage.AppliedTheme({ theme });
    }),
  messages: [ShellMessage.AppliedTheme],
});

export const ReadStoredConsent = Command.define("ReadStoredConsent", {
  execute: readStorage(consentStorageKey).pipe(
    Effect.map((stored) =>
      ShellMessage.SucceededReadStoredConsent({
        isAnswered: Option.isSome(stored),
      })
    )
  ),
  messages: [ShellMessage.SucceededReadStoredConsent],
});

export const StoreConsent = Command.define("StoreConsent", {
  args: { choice: ConsentChoice },
  execute: ({ choice }) =>
    writeStorage(consentStorageKey, Option.some(choice)).pipe(
      Effect.as(ShellMessage.StoredConsent())
    ),
  messages: [ShellMessage.StoredConsent],
});
