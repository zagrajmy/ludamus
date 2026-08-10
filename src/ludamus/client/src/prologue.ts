// Prologue — consent-gated PostHog analytics.
//
// The `module.full.no-external` bundle ships the recorder and exception
// autocapture inline, so nothing is ever fetched from a third-party host
// (keeps the strict CSP: only connect-src needs the PostHog ingestion host).
//
// Consent states (stored under STORAGE_KEY in localStorage):
// - unset:      PostHog runs with in-memory persistence only — no cookies,
//               no localStorage, no session recording — and the banner shows.
// - "accepted": durable persistence, capturing opted in, session recording
//               with every input masked.
// - "declined": PostHog is not initialized at all on later page loads; if it
//               was already running in memory mode this pageload, it opts out.
import posthog from "posthog-js/dist/module.full.no-external";

const STORAGE_KEY = "prologue.consent";

type Consent = "accepted" | "declined" | null;

type PosthogServerConfig = { api_key: string; host: string };

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

const initPosthog = (config: PosthogServerConfig, consented: boolean): void => {
  posthog.init(config.api_key, {
    api_host: config.host,
    capture_exceptions: true,
    defaults: "2025-05-24",
    disable_external_dependency_loading: true,
    disable_session_recording: !consented,
    disable_surveys: true,
    persistence: consented ? "localStorage+cookie" : "memory",
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: "[data-ph-mask]",
    },
  });
};

const applyChoice = (config: PosthogServerConfig, choice: "accepted" | "declined"): void => {
  localStorage.setItem(STORAGE_KEY, choice);
  if (choice === "accepted") {
    if (posthog.__loaded) {
      posthog.set_config({ persistence: "localStorage+cookie" });
      posthog.opt_in_capturing();
      posthog.startSessionRecording();
    } else {
      initPosthog(config, true);
    }
  } else if (posthog.__loaded) {
    posthog.stopSessionRecording();
    posthog.opt_out_capturing();
  }
};

const init = (): void => {
  const config = readServerConfig();
  if (!config) return;

  const consent = readConsent();
  if (consent !== "declined") initPosthog(config, consent === "accepted");

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
