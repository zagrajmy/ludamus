// Search behaviour for [data-multiselect-filter], in two modes.
//
// Default: every option is already in the DOM, so typing hides non-matching
// rows without a round trip. Ticked rows stay visible whatever the query --
// otherwise a search would hide part of what Apply is about to submit.
//
// With data-multiselect-url the option rows are fetched instead, for a list
// too long, too private, or too wide to ship whole. The request carries the
// ticked values so the server can keep them in the response; without that a
// second search would drop the first search's picks on the floor. Failures
// surface through the global htmx:responseError handler in flash.ts.

const DEBOUNCE_MS = 300;

const wire = (root: HTMLElement): void => {
  const search = root.querySelector<HTMLInputElement>("[data-multiselect-search] input");
  const list = root.querySelector<HTMLElement>("[data-multiselect-options]");
  const empty = root.querySelector<HTMLElement>("[data-multiselect-empty]");
  if (!search || !list || !empty) return;

  const url = list.dataset.multiselectUrl;

  const filterInPlace = (): void => {
    const query = search.value.toLowerCase().trim();
    let matches = 0;
    for (const row of list.querySelectorAll<HTMLElement>(".multiselect-option")) {
      const matched = !query || (row.dataset.search ?? "").includes(query);
      if (matched) matches++;
      row.hidden = !matched && !row.querySelector("input")?.checked;
    }
    empty.hidden = matches > 0;
  };

  const fetchOptions = (): void => {
    const params = new URLSearchParams({ q: search.value.trim() });
    for (const box of list.querySelectorAll<HTMLInputElement>("input:checked")) {
      params.append(box.name, box.value);
    }
    htmx.ajax("GET", `${url}?${params}`, { swap: "innerHTML", target: `#${list.id}` });
  };

  if (url === undefined) {
    search.addEventListener("input", filterInPlace);
    list.addEventListener("change", filterInPlace);
    return;
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  search.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(fetchOptions, DEBOUNCE_MS);
  });
};

for (const root of document.querySelectorAll<HTMLElement>("[data-multiselect-filter]")) {
  wire(root);
}
