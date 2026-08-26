// Prologue — consent-gated PostHog analytics.
//
// The `module.full.no-external` bundle ships the recorder and exception
// autocapture inline, so nothing is ever fetched from a third-party host
// (keeps the strict CSP: script-src stays nonce-only). connect-src still
// needs two origins — the ingestion host, and the assets host posthog-js
// derives from it to fetch remote config.
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

type PosthogServerConfig = {
  api_key: string;
  environment: string;
  host: string;
  redaction_rules: [string, string][];
  user_id: string | null;
};

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

// Claim links and session offers authenticate by bearing a token in the path —
// that is what lets those flows work without a login — so those paths are
// credentials, not locations. The patterns come from the server, which derives
// them from the URLconf, so this half cannot drift from the routes.
//
// The walk covers the whole event, keys included, because posthog puts URLs in
// more places than a property list can track: $set_once carries
// $initial_current_url into *person* properties, $session_entry_url rides every
// event of the session, autocapture folds a form's action into $elements_chain,
// and $heatmap_data is keyed by URL. It assigns in place rather than rebuilding
// — a rebuilt object flattens anything that is not a plain object, and
// CaptureResult.timestamp is a Date.
type Rule = { pattern: RegExp; replacement: string };

// The floor alone, if the server ever ships a pattern this engine rejects.
// new RegExp throwing here would run before posthog.init and leave the page
// with no analytics at all, silently.
// A token is base64url, so it has upper case or -_ in it; a digest is lower
// hex. Without that distinction a gravatar URL — sha256, also 64 characters —
// reads as a credential on every authenticated page.
const FLOOR: Rule = {
  pattern: /\/(?![0-9a-f]{56,}(?=[/?#]|$))[A-Za-z0-9_-]{56,}(?=[/?#]|$)/g,
  replacement: "/:token",
};

const compileRules = (patterns: [string, string][]): Rule[] => {
  try {
    return patterns.map(([source, replacement]) => ({
      pattern: new RegExp(source, "g"),
      replacement,
    }));
  } catch {
    return [FLOOR];
  }
};

const scrubText = (rules: Rule[], text: string): string => {
  let scrubbed = text;
  for (const { pattern, replacement } of rules) {
    scrubbed = scrubbed.replace(pattern, replacement);
  }
  return scrubbed;
};

const scrubInPlace = (rules: Rule[], node: object, seen: WeakSet<object>): void => {
  if (seen.has(node)) return;
  seen.add(node);
  const record = node as Record<string, unknown>;
  const renames: [string, string][] = [];
  for (const [key, value] of Object.entries(record)) {
    if (typeof value === "string") {
      record[key] = scrubText(rules, value);
    } else if (value !== null && typeof value === "object") {
      scrubInPlace(rules, value, seen);
    }
    const scrubbedKey = scrubText(rules, key);
    if (scrubbedKey !== key) renames.push([key, scrubbedKey]);
  }
  // Applied after the walk rather than during it: merging early can capture a
  // value the walk has not reached yet, leaving a token inside the merged copy.
  for (const [key, scrubbedKey] of renames) {
    const existing = record[scrubbedKey];
    const value = record[key];
    // Two buckets differing only by a token collapse onto one key. Concatenating
    // keeps both; anything else drops one silently. hasOwn rather than `in`, so
    // an inherited name cannot masquerade as a collision.
    record[scrubbedKey] =
      Object.hasOwn(record, scrubbedKey) && Array.isArray(existing) && Array.isArray(value)
        ? [...existing, ...value]
        : value;
    Reflect.deleteProperty(record, key);
  }
};

// rrweb puts the page URL in the Meta event as a plain string, and the network
// plugin records one per request, so the token does reach a recording. Walking
// the whole snapshot would mean walking a DOM; these two carry the URLs.
const scrubSnapshot = (rules: Rule[], properties: Record<string, unknown>): void => {
  const snapshot = properties["$snapshot_data"];
  if (!Array.isArray(snapshot)) return;
  for (const entry of snapshot) {
    if (entry === null || typeof entry !== "object") continue;
    const { data } = entry as { data?: unknown };
    if (data === null || typeof data !== "object") continue;
    const record = data as Record<string, unknown>;
    const { href, payload } = record;
    if (typeof href === "string") {
      record["href"] = scrubText(rules, href);
    }
    if (payload !== null && typeof payload === "object") {
      scrubInPlace(rules, payload, new WeakSet());
    }
  }
};

const initPosthog = (config: PosthogServerConfig): void => {
  const rules = compileRules(config.redaction_rules);
  posthog.init(config.api_key, {
    api_host: config.host,
    // Every event carries the deployment it came from, so staging traffic can
    // be filtered out of production dashboards. This is config rather than a
    // super property because reset() clears super properties, and reset() is
    // exactly what a logout, an account switch or a withdrawn consent does.
    before_send: (event) => {
      if (!event) return event;
      event.properties.environment = config.environment;
      // Not an either/or: $set_once hangs off the event, not off properties,
      // and posthog attaches it to every event name including $snapshot. Walk
      // the event with the recording payload held out, then scrub that payload
      // on its own terms.
      const snapshot = event.properties["$snapshot_data"];
      Reflect.deleteProperty(event.properties, "$snapshot_data");
      try {
        scrubInPlace(rules, event, new WeakSet());
      } catch {
        // posthog calls before_send bare, so a throw here would take capture()
        // down with it. Fall through to the check below rather than dropping
        // the event outright: a throw is deterministic per event shape, so
        // discarding on sight would silently delete a whole class of events
        // forever. Drop on evidence instead.
      }
      // Checked before the recording payload goes back, never after. That DOM
      // is left unscrubbed on purpose, and it carries URLs — a gravatar hash is
      // 64 characters, the same length as a token — so testing it here would
      // throw away the snapshot rather than the credential.
      let carriesToken = false;
      try {
        carriesToken = FLOOR.pattern.test(JSON.stringify(event));
      } catch {
        carriesToken = true;
      }
      if (snapshot !== undefined) {
        event.properties["$snapshot_data"] = snapshot;
        try {
          scrubSnapshot(rules, event.properties);
        } catch {
          /* the payload is back either way; a partial scrub beats no event */
        }
      }
      return carriesToken ? null : event;
    },
    capture_exceptions: true,
    defaults: "2025-05-24",
    disable_external_dependency_loading: true,
    disable_surveys: true,
    persistence: "localStorage+cookie",
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: "[data-ph-mask]",
      // base.html puts the current URL in og:url, and rrweb serialises social
      // meta into the snapshot unless told not to. On a claim or offer page
      // that tag is the credential, and before_send cannot reach the DOM.
      slimDOMOptions: { headMetaSocial: true },
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
