// Client-side narrowing for [data-multiselect-filter]: every option is already
// in the DOM, so typing hides non-matching rows without a round trip. Ticked
// rows stay visible whatever the query -- otherwise a search would hide part of
// what Apply is about to submit.

const wire = (root: HTMLElement): void => {
  const search = root.querySelector<HTMLInputElement>("[data-multiselect-search] input");
  const list = root.querySelector<HTMLElement>("[data-multiselect-options]");
  const empty = root.querySelector<HTMLElement>("[data-multiselect-empty]");
  if (!search || !list || !empty) return;

  const refresh = (): void => {
    const query = search.value.toLowerCase().trim();
    let matches = 0;
    for (const row of list.querySelectorAll<HTMLElement>(".multiselect-option")) {
      const matched = !query || (row.dataset.search ?? "").includes(query);
      if (matched) matches++;
      row.hidden = !matched && !row.querySelector("input")?.checked;
    }
    empty.hidden = matches > 0;
  };

  search.addEventListener("input", refresh);
  list.addEventListener("change", refresh);
};

for (const root of document.querySelectorAll<HTMLElement>("[data-multiselect-filter]")) {
  wire(root);
}
