// Prologue — consent-gated PostHog analytics.
//
// The `module.full.no-external` bundle ships the recorder and exception
// autocapture inline, so nothing is ever fetched from a third-party host
// (keeps the strict CSP: script-src stays nonce-only). connect-src still
// needs two origins — the ingestion host, and the assets host posthog-js
// derives from it to fetch remote config.
//
import type posthogClient from "posthog-js/dist/module.full.no-external";

import { PrivacyController, type PrivacyState } from "./privacy-controller";

let posthog: typeof posthogClient | undefined;

type PosthogServerConfig = {
  api_key: string;
  environment: string;
  host: string;
  privacy_revision: string;
  redaction_rules: [string, string][];
  user_id: string;
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

const syncIdentity = (client: typeof posthogClient, userId: string | null): void => {
  // PostHog persists distinct_id across pageloads, so a logout leaves the
  // previous user identified until we reset. Asking posthog rather than
  // tracking it ourselves keeps one source of truth: a mirror desyncs when
  // site data is cleared, and then nobody is ever identified again.
  if (client.get_distinct_id() === userId) return;
  // identify() on an already-identified instance silently re-registers the id
  // without emitting $identify or linking the anonymous history, so a switch
  // between accounts has to reset first.
  if (client._isIdentified()) client.reset();
  if (userId !== null) client.identify(userId);
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
const FLOOR_SOURCE = "/(?![0-9a-f]{56,}(?=[/?#]|$))[A-Za-z0-9_-]{56,}(?=[/?#]|$)";
const FLOOR: Rule = { pattern: new RegExp(FLOOR_SOURCE, "g"), replacement: "/:token" };
// Its own, without the g flag: test() on a global regex advances lastIndex, so
// a shared one answers true, false, true across consecutive events and half the
// tokens it should catch would sail through.
const CARRIES_TOKEN = new RegExp(FLOOR_SOURCE);

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

const initPosthog = async (
  config: PosthogServerConfig,
  canCapture: () => boolean,
): Promise<void> => {
  if (!canCapture()) return;
  if (!posthog) {
    const client = await import("posthog-js/dist/module.full.no-external");
    posthog = client.default;
  }
  if (!canCapture()) return;
  const rules = compileRules(config.redaction_rules);
  posthog.init(config.api_key, {
    api_host: config.host,
    // Every event carries the deployment it came from, so staging traffic can
    // be filtered out of production dashboards. This is config rather than a
    // super property because reset() clears super properties, and reset() is
    // exactly what a logout, an account switch or a withdrawn consent does.
    before_send: (event) => {
      if (!canCapture()) return null;
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
        carriesToken = CARRIES_TOKEN.test(JSON.stringify(event));
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
      // A selector, not posthog's ph-no-capture class: the class is read by
      // autocapture too, which drops the click event entirely, and these are
      // buttons whose use is worth measuring. This blocks the element from the
      // recording and nothing else.
      //
      // maskTextSelector masks TEXT NODES only — rrweb records attribute
      // values verbatim. Any element carrying PII in an attribute (a name in
      // aria-label or data-confirm copy, an email in a data-copy chip or a
      // mailto: href) must therefore be excluded from the recording entirely
      // with data-ph-block; it shows as a same-size placeholder in replay.
      // The pii-attribute-needs-block ast-grep rule enforces the pairing.
      blockSelector: "[data-ph-no-capture], [data-ph-block]",
      // Inputs are masked unless they hold published text (session, encounter
      // and event descriptions), whose bugs are worth seeing in a replay.
      maskAllInputs: true,
      maskInputFn: (text: string, element?: HTMLElement) =>
        element?.closest("[data-ph-unmask]") ? text : "*".repeat(text.length),
      maskTextSelector: "[data-ph-mask]",
      // base.html puts the current URL in og:url, and rrweb serialises social
      // meta into the snapshot unless told not to. On a claim or offer page
      // that tag is the credential, and before_send cannot reach the DOM.
      slimDOMOptions: { headMetaSocial: true },
    },
  });
  syncIdentity(posthog, config.user_id);
};

// The profile Privacy tab shows the stored choice: the server cannot know it
// (localStorage never leaves the browser), so elements carry the translated
// labels in data attributes and this fills the right one in.
const renderConsentState = (state: PrivacyState): void => {
  const consent = state === "ineligible" ? "declined" : state;
  for (const el of document.querySelectorAll<HTMLElement>("[data-consent-state]")) {
    const { labelAccepted = "", labelDeclined = "", labelUnset = "" } = el.dataset;
    el.textContent =
      consent === "accepted" ? labelAccepted : consent === "declined" ? labelDeclined : labelUnset;
  }
};

const startCapture = async (
  config: PosthogServerConfig,
  canCapture: () => boolean,
): Promise<void> => {
  if (!canCapture()) return;
  if (!posthog?.__loaded) {
    await initPosthog(config, canCapture);
    return;
  }
  posthog.set_config({ persistence: "localStorage+cookie" });
  posthog.opt_in_capturing();
  posthog.startSessionRecording();
  syncIdentity(posthog, config.user_id);
};

const stopCapture = (): void => {
  if (!posthog?.__loaded) return;
  // reset() before opt_out_capturing(), never after: reset() calls
  // consent.reset(), which is what clear_opt_in_out_capturing() does, so the
  // reverse order withdraws consent and then immediately clears the
  // withdrawal. Dropping the identity matters too, or re-accepting later
  // resumes capture under the person who declined.
  posthog.stopSessionRecording();
  syncIdentity(posthog, null);
  posthog.opt_out_capturing();
};

const isTrackingKey = (name: string): boolean =>
  name.startsWith("ph_") || name.startsWith("__ph_opt_in_out_");

// posthog sets its cookie on the widest domain it can, so each parent domain
// gets its own delete.
const cookieDomains = (): string[] => {
  const parts = location.hostname.split(".");
  return parts.slice(0, -1).map((_, i) => parts.slice(i).join("."));
};

const expireCookie = (name: string, domain?: string): void => {
  const scope = domain === undefined ? "" : `; domain=${domain}`;
  // HACK: the Cookie Store API the rule points at is undefined on iOS Safari
  // before 18.4 and outside secure contexts, where a tracking cookie would
  // otherwise outlive the consent that set it.
  // oxlint-disable-next-line unicorn/no-document-cookie
  document.cookie = `${name}=; path=/; max-age=0${scope}`;
};

// NOTE: the stored choice goes too. A page without posthog-config is signed
// out or ineligible, and on a shared device the next person to sign in must
// be asked again rather than inherit the previous one's consent.
const clearTrackingStorage = async (): Promise<void> => {
  for (const key of Object.keys(localStorage)) {
    if (isTrackingKey(key)) localStorage.removeItem(key);
  }
  if (!globalThis.cookieStore) {
    for (const pair of document.cookie.split(";")) {
      const name = pair.split("=")[0]?.trim() ?? "";
      if (!isTrackingKey(name)) continue;
      expireCookie(name);
      for (const domain of cookieDomains()) expireCookie(name, domain);
    }
    return;
  }
  for (const { name } of await globalThis.cookieStore.getAll()) {
    if (!name || !isTrackingKey(name)) continue;
    await globalThis.cookieStore.delete(name);
    for (const domain of cookieDomains()) {
      // A public suffix such as org.pl can hold no cookie, so its delete
      // rejects; that says nothing about the domains still to try.
      await globalThis.cookieStore.delete({ domain, name, path: "/" }).catch(() => null);
    }
  }
};

const init = (): void => {
  const config = readServerConfig();
  const banner = document.getElementById("consent-banner");
  const openers = document.querySelectorAll<HTMLElement>("[data-consent-reopen]");
  const privacy = new PrivacyController({
    clear: clearTrackingStorage,
    render: (state) => {
      renderConsentState(state);
      if (banner instanceof HTMLElement) banner.hidden = state !== null;
      for (const opener of openers) opener.hidden = state === "ineligible";
    },
    revision: config?.privacy_revision ?? null,
    start: async () => {
      if (config) await startCapture(config, privacy.canCapture);
    },
    stop: stopCapture,
  });
  privacy.init();
  if (!(banner instanceof HTMLElement)) return;

  for (const button of banner.querySelectorAll<HTMLButtonElement>("[data-consent-choice]")) {
    button.addEventListener("click", () => {
      const { consentChoice } = button.dataset;
      if (consentChoice !== "accepted" && consentChoice !== "declined") return;
      privacy.choose(consentChoice);
      banner.hidden = true;
    });
  }

  for (const opener of openers) {
    opener.addEventListener("click", () => {
      banner.hidden = false;
      banner.querySelector<HTMLButtonElement>("[data-consent-choice]")?.focus();
    });
  }
};

init();
