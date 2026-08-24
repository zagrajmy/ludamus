// Search + filtering for the event page session list. Reads everything it
// needs from `data-*` attributes the Django template renders onto each card,
// so this module stays free of server-side coupling. Active filters are
// mirrored into the query string (replace-only, see url-state.ts): a filtered
// view is shareable and survives reloads and view-tab swaps without becoming
// history entries or server round trips.

import {
  flagParam,
  hrefWithSearchParams,
  intParam,
  replaceSearchParams,
  type SearchParamCodec,
  stringParam,
} from "./url-state";

// Matches the min/max attributes on the age input; a shared bound would be
// a template/TS coupling for two literals.
const ageParam = intParam(0, 99);

// filterSessions runs per keystroke, and Safari rate-limits replaceState hard
// enough (~100 calls per 30s) that typing unthrottled could trip it.
const URL_SYNC_DEBOUNCE_MS = 300;

const byId = <T extends HTMLElement = HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Event filters: missing #${id}`);
  return el as T;
};

const requireChild = <T extends HTMLElement>(parent: HTMLElement, selector: string): T => {
  const el = parent.querySelector<T>(selector);
  if (!el) throw new Error(`Event filters: missing ${selector}`);
  return el;
};

// A location option holds either a space's sort key or, prefixed, a venue slug
// standing for every room under it. Sort keys open with the parent's zero-padded
// order, so no room's key can be mistaken for one.
const VENUE_VALUE_PREFIX = "venue:";

const escapeRegExp = (value: string): string =>
  value.replaceAll(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);

const selectedLabel = (select: HTMLSelectElement): string =>
  select.options.item(select.selectedIndex)?.text ?? "";

const addOption = (
  select: HTMLOptGroupElement | HTMLSelectElement,
  value: string,
  label: string,
): void => {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  select.append(option);
};

let documentListeners = new AbortController();

const initSessionFilters = (): void => {
  documentListeners.abort();
  documentListeners = new AbortController();
  const sessionFilter = byId<HTMLInputElement>("session-filter");
  const statusFilter = byId<HTMLSelectElement>("status-filter");
  const dayFilter = byId<HTMLSelectElement>("day-filter");
  const hourFilter = byId<HTMLSelectElement>("hour-filter");
  const spaceFilter = byId<HTMLSelectElement>("space-filter");
  const hostFilter = byId<HTMLSelectElement>("host-filter");
  const ageFilter = byId<HTMLInputElement>("age-filter");
  const enrollmentFilter = document.querySelector<HTMLInputElement>("#enrollment-filter");
  const filterToggle = byId("filter-toggle");
  const filterPanel = byId("filter-panel");
  const filterChipsBar = byId("active-filter-chips");
  const filterCountBadge = byId("active-filter-count");

  const filterChipsInner = requireChild<HTMLElement>(filterChipsBar, "[data-filter-chips-inner]");

  const filterNoResults = document.getElementById("filter-no-results");
  const clearFiltersFromNoResults = document.getElementById("clear-filters-from-no-results");
  const sessionCards = document.querySelectorAll<HTMLElement>(".session");

  const tagFilters: Record<string, HTMLSelectElement> = {};

  const COMBINING_MARKS = /[\u0300-\u036F]/g;
  const NON_DECOMPOSING_MAP: Record<string, string> = {
    æ: "ae",
    đ: "d",
    ħ: "h",
    ı: "i",
    ł: "l",
    ø: "o",
    œ: "oe",
    ß: "ss",
  };
  const normalizeText = (value: string): string =>
    value
      .toLowerCase()
      .replaceAll(/[łøđħıœæß]/g, (char) => NON_DECOMPOSING_MAP[char] ?? char)
      .normalize("NFD")
      .replaceAll(COMBINING_MARKS, "");

  // Field values ride in the haystack because a value typed into an
  // allow_custom field is not a choice and so never becomes a filter option —
  // search is where it stays findable.
  const cardHaystacks = new Map<HTMLElement, string>();
  for (const card of sessionCards) {
    const descEl = card.querySelector("[data-session-description]");
    const description = descEl ? (descEl.textContent ?? "") : "";
    const tags = (card.dataset.tags ?? "").replaceAll(",", " ");
    cardHaystacks.set(
      card,
      normalizeText(
        `${card.dataset.title ?? ""} ${card.dataset.host ?? ""} ${description} ${tags}`,
      ),
    );
  }

  const dayMap = new Map<string, string>();
  for (const card of sessionCards) {
    const { day } = card.dataset;
    if (day && !dayMap.has(day)) dayMap.set(day, card.dataset.dayLabel ?? day);
  }
  for (const [value, label] of [...dayMap.entries()].sort((a, b) => a[0].localeCompare(b[0])))
    addOption(dayFilter, value, label);
  if (dayMap.size > 1) {
    document.getElementById("day-filter-group")?.classList.remove("hidden");
  }

  const hourSet = new Set<string>();
  for (const card of sessionCards) {
    if (card.dataset.hour) hourSet.add(card.dataset.hour);
  }
  for (const hour of [...hourSet].sort()) addOption(hourFilter, hour, hour);
  if (hourSet.size > 1) {
    document.getElementById("hour-filter-group")?.classList.remove("hidden");
  }
  if (dayMap.size > 1 || hourSet.size > 1) {
    document.getElementById("day-hour-filter-group")?.classList.remove("hidden");
  }

  // data-host is lowercased for the search haystack, so it is the match key;
  // data-host-label carries the display casing for the option text.
  const hostMap = new Map<string, string>();
  for (const card of sessionCards) {
    const { host } = card.dataset;
    if (host && !hostMap.has(host)) hostMap.set(host, card.dataset.hostLabel ?? host);
  }
  for (const [value, label] of [...hostMap.entries()].sort((a, b) => a[1].localeCompare(b[1])))
    addOption(hostFilter, value, label);
  if (hostMap.size > 1) {
    document.getElementById("host-filter-group")?.classList.remove("hidden");
  }

  // Populate the location filter — one control for the whole space tree. The
  // option value is the space's sort key, so sorting the entries lays the rooms
  // out in the panel's tree order and lands every room of a parent space in one
  // run, which is what the <optgroup>s are cut from. Each group opens with an
  // option selecting the venue whole; rooms with no parent go straight onto the
  // select.
  const allRoomsLabel = spaceFilter.dataset.allRoomsLabel ?? "";
  const spaceMap = new Map<string, { groupKey: string; groupName: string; name: string }>();
  for (const card of sessionCards) {
    const spaceKey = card.dataset.space;
    if (spaceKey && !spaceMap.has(spaceKey)) {
      spaceMap.set(spaceKey, {
        // The run is cut on the parent's slug, never its name: a name is unique
        // only among its siblings, so two branches can carry the same one and
        // must not collapse into a single group.
        groupKey: card.dataset.venue ?? "",
        groupName: card.dataset.venueName ?? "",
        name: card.dataset.spaceName ?? spaceKey,
      });
    }
  }
  let currentGroup: HTMLOptGroupElement | undefined;
  let currentGroupKey: string | undefined;
  // Codepoint order, not localeCompare: the key's structure is carried by its
  // "|" separators, and collation treats punctuation as ignorable.
  for (const [key, { groupKey, groupName, name }] of [...spaceMap.entries()].sort(([a], [b]) =>
    a < b ? -1 : Number(a > b),
  )) {
    if (!groupKey) {
      currentGroup = undefined;
      currentGroupKey = undefined;
    } else if (currentGroupKey !== groupKey) {
      currentGroup = document.createElement("optgroup");
      currentGroup.label = groupName;
      currentGroupKey = groupKey;
      spaceFilter.append(currentGroup);
      addOption(
        currentGroup,
        `${VENUE_VALUE_PREFIX}${groupKey}`,
        `${groupName} — ${allRoomsLabel}`,
      );
    }
    addOption(currentGroup ?? spaceFilter, key, name);
  }
  if (spaceMap.size > 1) {
    document.getElementById("space-filter-group")?.classList.remove("hidden");
  }

  for (const select of document.querySelectorAll<HTMLSelectElement>(".tag-filter")) {
    const categorySlug = select.dataset.category;
    if (!categorySlug) continue;
    tagFilters[categorySlug] = select;

    const categoryTags = new Set<string>();
    for (const card of sessionCards) {
      const tagCategoriesData = card.dataset.tagCategories;
      if (!tagCategoriesData) continue;
      for (const pair of tagCategoriesData.split(";").filter((pair) => pair.trim())) {
        const [cardCategorySlug, tagName] = pair.split(":");
        if (cardCategorySlug === categorySlug && tagName) {
          categoryTags.add(tagName.trim());
        }
      }
    }

    // One rule for every tag filter: the server renders what can be picked,
    // this drops what no card uses. A session field offers its defined choices
    // only — a value typed into an allow_custom field reaches the card but is
    // not a choice, and search is where it stays findable.
    // querySelectorAll, not select.options: the live collection would skip an
    // option as the one before it is removed. The valueless "All ..."
    // placeholder stays.
    for (const option of select.querySelectorAll("option")) {
      if (option.value && !categoryTags.has(option.value)) option.remove();
    }
    select.addEventListener("change", filterSessions);
  }

  // Controls whose value lives in the query string too, each bound through a
  // typed codec from url-state.ts (which also lists the reserved param names
  // a mirror must stay clear of). The codec is the type boundary: the erased
  // entry below only ever moves raw URL strings, so a parse and a serialize
  // that disagree can't typecheck their way in.
  interface MirrorEntry {
    /** Push a raw URL value into the control, through the codec. */
    applyRaw: (raw: string | null) => void;
    /** Does the control already hold what `raw` decodes to? */
    matchesRaw: (raw: string | null) => boolean;
    /** Current control value, URL-encoded; null when the param drops. */
    readRaw: () => string | null;
  }

  const mirrored = new Map<string, MirrorEntry>();
  const mirror = <T>(
    name: string,
    codec: SearchParamCodec<T>,
    read: () => T,
    write: (value: T) => void,
  ): void => {
    mirrored.set(name, {
      applyRaw: (raw) => {
        write(codec.parse(raw));
      },
      matchesRaw: (raw) => read() === codec.parse(raw),
      readRaw: () => codec.serialize(read()),
    });
  };

  const mirrorInput = (name: string, input: HTMLInputElement): void => {
    mirror(
      name,
      stringParam,
      () => input.value,
      (value) => {
        input.value = value;
      },
    );
  };
  // Assigning a value no <option> carries leaves a select on "", so a stale
  // deep link (a venue renamed, a tag gone) degrades to "all", not an error.
  // That makes the DOM the value schema here; the options are built from the
  // cards at init, so a static codec could only restate them, worse.
  const mirrorSelect = (name: string, select: HTMLSelectElement): void => {
    mirror(
      name,
      stringParam,
      () => select.value,
      (value) => {
        select.value = value;
      },
    );
  };
  // A number input's value is "" or a numeric string, never garbage; the
  // codec adds the range check the attribute alone doesn't enforce on load.
  const mirrorAge = (name: string, input: HTMLInputElement): void => {
    mirror(
      name,
      ageParam,
      () => (input.value === "" ? null : Number(input.value)),
      (value) => {
        input.value = value === null ? "" : String(value);
      },
    );
  };

  mirrorInput("q", sessionFilter);
  mirrorSelect("status", statusFilter);
  if (enrollmentFilter) {
    mirror(
      "enrollment",
      flagParam,
      () => enrollmentFilter.checked,
      (value) => {
        enrollmentFilter.checked = value;
      },
    );
  }
  mirrorSelect("day", dayFilter);
  mirrorSelect("hour", hourFilter);
  mirrorSelect("space", spaceFilter);
  mirrorSelect("host", hostFilter);
  mirrorAge("age", ageFilter);
  // `__track` and `__category` are the template's own pseudo-categories, so
  // they get clean names; organizer-defined categories are event-scoped slugs,
  // prefixed so one named e.g. "status" cannot shadow a built-in param.
  const TAG_PARAM_NAMES: Record<string, string> = { __category: "category", __track: "track" };
  for (const [slug, select] of Object.entries(tagFilters)) {
    mirrorSelect(TAG_PARAM_NAMES[slug] ?? `tag-${slug}`, select);
  }

  const mirrorState = (): Map<string, string | null> =>
    new Map([...mirrored].map(([name, entry]) => [name, entry.readRaw()]));

  let urlSyncTimer: ReturnType<typeof setTimeout> | undefined;
  documentListeners.signal.addEventListener("abort", () => clearTimeout(urlSyncTimer));
  const scheduleUrlSync = (): void => {
    clearTimeout(urlSyncTimer);
    urlSyncTimer = setTimeout(() => {
      const state = mirrorState();
      replaceSearchParams(state);
      // The view tabs are hx-boosted GETs to `?view=…`; splice the mirror
      // into their hrefs so open-in-new-tab keeps the filters. A plain click
      // ignores this — htmx captured the href at process time — and is
      // covered by the htmx:configRequest listener below instead.
      for (const tab of document.querySelectorAll<HTMLAnchorElement>(
        '#schedule-region a[role="tab"][href]',
      )) {
        tab.setAttribute("href", hrefWithSearchParams(tab.getAttribute("href") ?? "", state));
      }
    }, URL_SYNC_DEBOUNCE_MS);
  };

  // Filters survive a view-tab switch by riding the pushed URL: the mirror is
  // spliced into the boosted request path at send time (fresh, no debounce
  // staleness), and the swapped-in toolbar reads it back off location.
  document.body.addEventListener(
    "htmx:configRequest",
    (event) => {
      const { detail } = event as CustomEvent<{ elt: Element; path: string }>;
      if (!detail.elt.matches('#schedule-region a[role="tab"]')) return;
      detail.path = hrefWithSearchParams(detail.path, mirrorState());
    },
    { signal: documentListeners.signal },
  );

  /** Read the query string back into the controls; true when anything moved. */
  const applyUrlState = (): boolean => {
    const params = new URLSearchParams(globalThis.location.search);
    let changed = false;
    for (const [name, entry] of mirrored) {
      const raw = params.get(name);
      if (entry.matchesRaw(raw)) continue;
      const before = entry.readRaw();
      entry.applyRaw(raw);
      changed ||= entry.readRaw() !== before;
    }
    return changed;
  };

  function filterSessions(): void {
    const searchTokens = normalizeText(sessionFilter.value).split(/\s+/).filter(Boolean);
    const statusValue = statusFilter.value;
    const enrollmentOnly = enrollmentFilter?.checked ?? false;
    const dayValue = dayFilter.value;
    const hourValue = hourFilter.value;
    const spaceValue = spaceFilter.value;
    const hostValue = hostFilter.value;
    const ageValue = ageFilter.value;

    const activeTagFilters: Record<string, string> = {};
    for (const categorySlug of Object.keys(tagFilters)) {
      const filterValue = tagFilters[categorySlug].value;
      if (filterValue) activeTagFilters[categorySlug] = filterValue;
    }

    for (const card of sessionCards) {
      let show = true;

      if (searchTokens.length > 0) {
        const haystack = cardHaystacks.get(card) ?? "";
        show &&= searchTokens.every((token) => haystack.includes(token));
      }

      if (statusValue) {
        switch (statusValue) {
          case "my-bookmarked": {
            show &&= card.dataset.bookmarked === "true";

            break;
          }
          case "my-enrolled": {
            show &&= card.dataset.userEnrolled === "true";

            break;
          }
          case "my-waiting": {
            show &&= card.dataset.userWaiting === "true";

            break;
          }
          default: {
            show &&= card.dataset.status === statusValue;
          }
        }
      }

      if (enrollmentOnly) show &&= card.dataset.takesEnrollment === "true";
      if (dayValue) show &&= card.dataset.day === dayValue;
      if (hourValue) show &&= card.dataset.hour === hourValue;
      if (spaceValue) {
        show &&= spaceValue.startsWith(VENUE_VALUE_PREFIX)
          ? card.dataset.venue === spaceValue.slice(VENUE_VALUE_PREFIX.length)
          : card.dataset.space === spaceValue;
      }

      if (hostValue) show &&= card.dataset.host === hostValue;

      // The participant's age against the session's requirement: an
      // unrestricted session (min age 0) admits everyone, so it always stays.
      if (ageValue) {
        const sessionMinAge = Number.parseInt(card.dataset.minAge ?? "", 10) || 0;
        show &&= sessionMinAge <= Number.parseInt(ageValue, 10);
      }

      if (Object.keys(activeTagFilters).length > 0) {
        const cardTagCategories = card.dataset.tagCategories ?? "";
        const cardTags = card.dataset.tags ?? "";
        let matchesAllFilters = true;
        for (const categorySlug of Object.keys(activeTagFilters)) {
          const requiredTag = escapeRegExp(activeTagFilters[categorySlug]);
          const escapedCategory = escapeRegExp(categorySlug);
          const categoryPattern = new RegExp(
            `(?:^|;)${escapedCategory}:${requiredTag}(?:;|$)`,
            "i",
          );
          const simpleTagPattern = new RegExp(String.raw`\b${requiredTag}\b`, "i");
          if (!categoryPattern.test(cardTagCategories) && !simpleTagPattern.test(cardTags)) {
            matchesAllFilters = false;
          }
        }
        show &&= matchesAllFilters;
      }

      const cardContainer = card.closest<HTMLElement>(".session-wrapper");
      if (cardContainer) cardContainer.hidden = !show;
    }

    for (const section of document.querySelectorAll<HTMLElement>(".time-slot-section")) {
      const cardGrid = section.querySelector(".session-grid") ?? section;
      let visibleCards = cardGrid.querySelectorAll(".session-wrapper:not([hidden])");
      if (visibleCards.length === 0 && section.dataset.slotHour) {
        visibleCards = document.querySelectorAll(
          `.session-wrapper[data-slot-hour="${CSS.escape(section.dataset.slotHour)}"]:not([hidden])`,
        );
      }
      section.hidden = visibleCards.length === 0;
    }

    // slot is now empty so the header doesn't dangle. No-op on the card layout.
    for (const day of document.querySelectorAll<HTMLElement>("[data-schedule-day]")) {
      const visibleSlots = day.querySelectorAll(".time-slot-section:not([hidden])");
      day.hidden = visibleSlots.length === 0;
    }

    updateFilterUI();

    document.dispatchEvent(new CustomEvent("schedule:filtered"));
  }

  function clearAllFilters(): void {
    sessionFilter.value = "";
    statusFilter.value = "";
    if (enrollmentFilter) enrollmentFilter.checked = false;
    dayFilter.value = "";
    hourFilter.value = "";
    spaceFilter.value = "";
    hostFilter.value = "";
    ageFilter.value = "";
    for (const categorySlug of Object.keys(tagFilters)) {
      tagFilters[categorySlug].value = "";
    }

    for (const section of document.querySelectorAll<HTMLElement>(".time-slot-section")) {
      section.hidden = false;
    }
    for (const day of document.querySelectorAll<HTMLElement>("[data-schedule-day]")) {
      day.hidden = false;
    }
    for (const cardContainer of document.querySelectorAll<HTMLElement>(".session-wrapper")) {
      cardContainer.hidden = false;
    }

    filterSessions();
  }

  interface FilterChip {
    clear: () => void;
    label: string;
  }

  function updateFilterUI(): void {
    const chips: FilterChip[] = [];
    const pushSelectChip = (select: HTMLSelectElement): void => {
      if (!select.value) return;
      chips.push({
        clear: () => {
          select.value = "";
          filterSessions();
        },
        label: selectedLabel(select),
      });
    };
    const pushAgeChip = (input: HTMLInputElement, prefix: string): void => {
      if (!input.value) return;
      chips.push({
        clear: () => {
          input.value = "";
          filterSessions();
        },
        label: `${prefix} ${input.value}`,
      });
    };

    if (enrollmentFilter?.checked) {
      chips.push({
        clear: () => {
          enrollmentFilter.checked = false;
          filterSessions();
        },
        label: filterChipsBar.dataset.enrollmentLabel ?? "",
      });
    }
    pushSelectChip(statusFilter);
    pushSelectChip(dayFilter);
    pushSelectChip(hourFilter);
    pushSelectChip(spaceFilter);
    pushSelectChip(hostFilter);
    pushAgeChip(ageFilter, filterChipsBar.dataset.ageLabel ?? "");
    for (const cat of Object.keys(tagFilters)) pushSelectChip(tagFilters[cat]);

    if (chips.length > 0) {
      filterCountBadge.textContent = String(chips.length);
      filterCountBadge.classList.add("is-visible");
    } else {
      filterCountBadge.classList.remove("is-visible");
    }

    filterChipsInner.innerHTML = "";
    if (chips.length > 0) {
      filterChipsBar.classList.add("has-chips");
      for (const chip of chips) {
        const el = document.createElement("span");
        el.className = "filter-chip";
        el.textContent = chip.label;
        const btn = document.createElement("button");
        const removeLabel = filterChipsBar.dataset.removeFilterLabel;
        if (removeLabel) btn.setAttribute("aria-label", removeLabel);
        btn.textContent = "×";
        btn.addEventListener("click", chip.clear);
        el.append(btn);
        filterChipsInner.append(el);
      }
      const clearBtn = document.createElement("button");
      clearBtn.className = "filter-chips-clear";
      clearBtn.textContent = filterChipsBar.dataset.clearAllLabel ?? "";
      clearBtn.addEventListener("click", clearAllFilters);
      filterChipsInner.append(clearBtn);
    } else {
      filterChipsBar.classList.remove("has-chips");
    }

    scheduleUrlSync();

    const visibleCards = document.querySelectorAll(".session-wrapper:not([hidden])");
    const anyFilterActive = chips.length > 0 || sessionFilter.value.trim() !== "";
    if (filterNoResults) {
      filterNoResults.hidden = !(
        anyFilterActive &&
        visibleCards.length === 0 &&
        sessionCards.length > 0
      );
    }
  }

  sessionFilter.addEventListener("input", filterSessions);
  statusFilter.addEventListener("change", filterSessions);
  enrollmentFilter?.addEventListener("change", filterSessions);
  dayFilter.addEventListener("change", filterSessions);
  hourFilter.addEventListener("change", filterSessions);
  spaceFilter.addEventListener("change", filterSessions);
  hostFilter.addEventListener("change", filterSessions);
  ageFilter.addEventListener("input", filterSessions);

  filterToggle.addEventListener("click", () => {
    const isOpen = filterPanel.classList.toggle("is-open");
    filterToggle.setAttribute("aria-expanded", String(isOpen));
  });

  const filtersWrapper = filterToggle.closest<HTMLElement>(".filters-popover-wrapper");
  if (filtersWrapper) {
    const closePanel = (): void => {
      filterPanel.classList.remove("is-open");
      filterToggle.setAttribute("aria-expanded", "false");
    };
    const closeWhenOutside = (target: EventTarget | null): void => {
      if (
        filterPanel.classList.contains("is-open") &&
        target instanceof Node &&
        !filtersWrapper.contains(target)
      ) {
        closePanel();
      }
    };
    document.addEventListener("click", (e) => closeWhenOutside(e.target), {
      signal: documentListeners.signal,
    });
    document.addEventListener("focusin", (e) => closeWhenOutside(e.target), {
      signal: documentListeners.signal,
    });
  }

  if (clearFiltersFromNoResults) {
    clearFiltersFromNoResults.addEventListener("click", clearAllFilters);
  }

  // Back/forward can land on an entry whose query differs (a view-tab push
  // made under other filters); the URL is the truth on traversal, so read it
  // back in. Traversals across modal entries carry identical filter params,
  // leaving this a no-op while a modal morph runs.
  globalThis.addEventListener(
    "popstate",
    () => {
      if (applyUrlState()) filterSessions();
    },
    { signal: documentListeners.signal },
  );

  // Deep links: seed the controls from the query string and run the filters
  // once. A parameterless load skips the pass — and with it any replaceState.
  if (applyUrlState()) filterSessions();
};

const bootSessionFilters = (): void => {
  const searchBox = document.getElementById("session-filter");
  if (!searchBox) {
    documentListeners.abort();
    return;
  }
  if ("filtersBound" in searchBox.dataset) return;
  searchBox.dataset.filtersBound = "";
  initSessionFilters();
};

bootSessionFilters();
document.body.addEventListener("htmx:afterSwap", bootSessionFilters);
