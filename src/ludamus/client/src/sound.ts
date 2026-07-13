import { bind, play, setEnabled as setEngineEnabled, type SoundName, sounds } from "cuelume";

const STORAGE_KEY = "sound.enabled";
const TAP_SELECTOR = 'a[href], button, [role="button"], summary';
const OWN_SOUND_SELECTOR =
  "[data-sound-play], [data-sound-toggle], [data-cuelume-hover]," +
  " [data-cuelume-press], [data-cuelume-release], [data-cuelume-toggle]";

const isSoundName = (value: string): value is SoundName =>
  (sounds as readonly string[]).includes(value);

const isEnabled = (): boolean => {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored !== null) return stored === "1";
  return !matchMedia("(prefers-reduced-motion: reduce)").matches;
};

const applyPreference = (): void => {
  const on = isEnabled();
  setEngineEnabled(on);
  for (const el of document.querySelectorAll<HTMLInputElement>("[data-sound-toggle]")) {
    el.checked = on;
    const title = on ? el.dataset.titleChecked : el.dataset.titleUnchecked;
    const label = el.closest("label");
    if (title && label) label.title = title;
  }
};

const setEnabled = (on: boolean): void => {
  localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  applyPreference();
};

const preview = (name: SoundName): void => {
  setEngineEnabled(true);
  play(name);
  setEngineEnabled(isEnabled());
};

const announceFlash = (): void => {
  const alert = document.querySelector("[data-flash]");
  if (!alert) return;
  if (alert.classList.contains("alert-danger")) play("droplet");
  else if (alert.classList.contains("alert-success")) play("success");
  else play("bloom");
};

const init = (): void => {
  applyPreference();
  bind();

  document.addEventListener(
    "pointerdown",
    ({ target }) => {
      if (!(target instanceof Element) || target.closest(OWN_SOUND_SELECTOR)) return;
      if (target.closest(TAP_SELECTOR)) play("press");
    },
    true,
  );

  document.addEventListener(
    "submit",
    ({ target }) => {
      if (target instanceof HTMLFormElement) play("release");
    },
    true,
  );

  document.addEventListener("change", ({ target }) => {
    if (!(target instanceof HTMLInputElement) || target.type !== "checkbox") return;
    if (target.matches("[data-sound-toggle]")) setEnabled(target.checked);
    play("toggle");
  });

  document.addEventListener("click", ({ target }) => {
    if (!(target instanceof Element)) return;
    const name = target.closest<HTMLElement>("[data-sound-play]")?.dataset.soundPlay;
    if (name !== undefined && isSoundName(name)) preview(name);
  });

  globalThis.addEventListener("storage", ({ key }) => {
    if (key === STORAGE_KEY) applyPreference();
  });

  announceFlash();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
