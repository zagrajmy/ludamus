// Prologue — consent-gated PostHog analytics.
//
// The `module.full.no-external` bundle ships the recorder and exception
// autocapture inline, so nothing is ever fetched from a third-party host
// (keeps the strict CSP: only connect-src needs the PostHog ingestion host).
//
// Consent states (stored under STORAGE_KEY in localStorage):
// - unset:      PostHog is not initialized at all — no events leave the
//               browser — and the banner shows.
// - "accepted": initialized with durable persistence, capturing opted in,
//               session recording with every input masked.
// - "declined": PostHog is never initialized; withdrawing consent on a
//               pageload where it already runs opts out and stops recording.
import posthog from "posthog-js/dist/module.full.no-external";

const STORAGE_KEY = "prologue.consent";

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

const syncIdentity = (userId: string | null): void => {
  // PostHog persists distinct_id across pageloads, so a logout leaves the
  // previous user identified until we reset. Asking posthog rather than
  // tracking it ourselves keeps one source of truth: a mirror desyncs when
  // site data is cleared, and then nobody is ever identified again.
  if (posthog.get_distinct_id() === userId) return;
  // identify() on an already-identified instance silently re-registers the id
  // without emitting $identify or linking the anonymous history, so a switch
  // between accounts has to reset first.
  if (posthog._isIdentified()) posthog.reset();
  if (userId !== null) posthog.identify(userId);
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
    // reset() before opt_out_capturing(), never after: reset() calls
    // consent.reset(), which is what clear_opt_in_out_capturing() does, so the
    // reverse order withdraws consent and then immediately clears the
    // withdrawal. Dropping the identity matters too, or re-accepting later
    // resumes capture under the person who declined.
    posthog.stopSessionRecording();
    syncIdentity(null);
    posthog.opt_out_capturing();
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
