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

const escapeRegExp = (value: string): string =>
  value.replaceAll(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);

const selectedLabel = (select: HTMLSelectElement): string =>
  select.options.item(select.selectedIndex)?.text ?? "";

const addOption = (select: HTMLSelectElement, value: string, label: string): void => {
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
  const venueFilter = byId<HTMLSelectElement>("venue-filter");
  const minAgeFilter = byId<HTMLInputElement>("min-age-filter");
  const maxAgeFilter = byId<HTMLInputElement>("max-age-filter");
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

  const cardHaystacks = new Map<HTMLElement, string>();
  for (const card of sessionCards) {
    const descEl = card.querySelector("[data-session-description]");
    const description = descEl ? (descEl.textContent ?? "") : "";
    cardHaystacks.set(
      card,
      normalizeText(`${card.dataset.title ?? ""} ${card.dataset.host ?? ""} ${description}`),
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

  const venueMap = new Map<string, string>();
  for (const card of sessionCards) {
    const venueSlug = card.dataset.venue;
    if (venueSlug && !venueMap.has(venueSlug)) {
      venueMap.set(venueSlug, card.dataset.venueName ?? venueSlug);
    }
  }
  for (const [slug, name] of [...venueMap.entries()].sort((a, b) => a[1].localeCompare(b[1])))
    addOption(venueFilter, slug, name);
  if (venueMap.size > 1) {
    document.getElementById("venue-filter-group")?.classList.remove("hidden");
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

    for (const tag of [...categoryTags].sort()) addOption(select, tag, tag);
    select.addEventListener("change", filterSessions);
  }

  function filterSessions(): void {
    const searchTokens = normalizeText(sessionFilter.value).split(/\s+/).filter(Boolean);
    const statusValue = statusFilter.value;
    const enrollmentOnly = enrollmentFilter?.checked ?? false;
    const dayValue = dayFilter.value;
    const hourValue = hourFilter.value;
    const venueValue = venueFilter.value;
    const minAgeValue = minAgeFilter.value;
    const maxAgeValue = maxAgeFilter.value;

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
      if (venueValue) show &&= card.dataset.venue === venueValue;

      if (minAgeValue || maxAgeValue) {
        const sessionMinAge = Number.parseInt(card.dataset.minAge ?? "", 10) || 0;
        if (minAgeValue) show &&= sessionMinAge >= Number.parseInt(minAgeValue, 10);
        if (maxAgeValue) show &&= sessionMinAge <= Number.parseInt(maxAgeValue, 10);
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
    venueFilter.value = "";
    minAgeFilter.value = "";
    maxAgeFilter.value = "";
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
    pushSelectChip(venueFilter);
    pushAgeChip(minAgeFilter, filterChipsBar.dataset.minAgeLabel ?? "Age ≥");
    pushAgeChip(maxAgeFilter, filterChipsBar.dataset.maxAgeLabel ?? "Age ≤");
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
  venueFilter.addEventListener("change", filterSessions);
  minAgeFilter.addEventListener("input", filterSessions);
  maxAgeFilter.addEventListener("input", filterSessions);

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
