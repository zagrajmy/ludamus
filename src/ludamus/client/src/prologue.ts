// Prologue — consent-gated PostHog analytics.
//
// The `module.full.no-external` bundle ships the recorder and exception
// autocapture inline, so nothing is ever fetched from a third-party host
// (keeps the strict CSP: only connect-src needs the PostHog ingestion host).
//
// Consent states (stored under STORAGE_KEY in localStorage):
// - unset:      PostHog is not initialized at all — no events leave the
//               browser — and the banner shows. The banner's "nothing is
//               stored before you agree" promise depends on this staying
//               literally true.
// - "accepted": initialized with durable persistence, capturing opted in,
//               session recording with every input masked.
// - "declined": PostHog is never initialized; withdrawing consent on a
//               pageload where it already runs opts out and stops recording.
import posthog from "posthog-js/dist/module.full.no-external";

const STORAGE_KEY = "prologue.consent";
const UID_KEY = "prologue.uid";

type Consent = "accepted" | "declined" | null;

type PosthogServerConfig = { api_key: string; host: string; user_id: string | null };

const readServerConfig = (): PosthogServerConfig | null => {
  const el = document.getElementById("posthog-config");
  if (!el?.textContent) return null;
  try {
    return JSON.parse(el.textContent) as PosthogServerConfig;
  } catch {
    return null;
  }
};

const readConsent = (): Consent => {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === "accepted" || stored === "declined" ? stored : null;
};

// PostHog persists distinct_id across pageloads, so a logout leaves the
// previous user identified until we reset. UID_KEY records who we last
// identified, which is the only way to tell "still anonymous" from "just
// logged out" — posthog exposes no public predicate for it.
const syncIdentity = (userId: string | null): void => {
  const stored = localStorage.getItem(UID_KEY);
  if (stored === userId) return;
  if (stored !== null) posthog.reset();
  if (userId === null) {
    localStorage.removeItem(UID_KEY);
  } else {
    posthog.identify(userId);
    localStorage.setItem(UID_KEY, userId);
  }
};

const initPosthog = (config: PosthogServerConfig): void => {
  posthog.init(config.api_key, {
    api_host: config.host,
    capture_exceptions: true,
    defaults: "2025-05-24",
    disable_external_dependency_loading: true,
    disable_surveys: true,
    persistence: "localStorage+cookie",
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: "[data-ph-mask]",
    },
  });
  syncIdentity(config.user_id);
};

const applyChoice = (config: PosthogServerConfig, choice: "accepted" | "declined"): void => {
  localStorage.setItem(STORAGE_KEY, choice);
  if (choice === "accepted") {
    if (posthog.__loaded) {
      posthog.set_config({ persistence: "localStorage+cookie" });
      posthog.opt_in_capturing();
      posthog.startSessionRecording();
      syncIdentity(config.user_id);
    } else {
      initPosthog(config);
    }
  } else if (posthog.__loaded) {
    posthog.stopSessionRecording();
    posthog.opt_out_capturing();
    localStorage.removeItem(UID_KEY);
  }
};

const init = (): void => {
  const config = readServerConfig();
  if (!config) return;

  const consent = readConsent();
  if (consent === "accepted") initPosthog(config);

  const banner = document.getElementById("consent-banner");
  if (!(banner instanceof HTMLElement)) return;
  if (consent === null) banner.hidden = false;

  for (const button of banner.querySelectorAll<HTMLButtonElement>("[data-consent-choice]")) {
    button.addEventListener("click", () => {
      const { consentChoice } = button.dataset;
      if (consentChoice !== "accepted" && consentChoice !== "declined") return;
      applyChoice(config, consentChoice);
      banner.hidden = true;
    });
  }

  for (const opener of document.querySelectorAll("[data-consent-reopen]")) {
    opener.addEventListener("click", () => {
      banner.hidden = false;
      banner.querySelector<HTMLButtonElement>("[data-consent-choice]")?.focus();
    });
  }
};

init();
