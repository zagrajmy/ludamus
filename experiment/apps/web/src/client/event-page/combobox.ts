import { Option } from "effect";

import { comboboxLabel, normalizeText } from "./filters.js";
import type { ComboboxId, FilterState } from "./filters.js";
import type { Choice, FilterChoices } from "./flags.js";
import type { OpenCombobox } from "./model.js";

export const comboboxOptions = (
  choices: FilterChoices,
  id: ComboboxId
): readonly Choice[] => {
  if (id === "space") {
    return choices.spaces;
  }

  const values =
    id === "host"
      ? choices.hosts
      : id === "track"
        ? choices.tracks
        : choices.categories;

  return values.map((value) => ({ label: value, value }));
};

export const shownOptions = (options: {
  readonly choices: FilterChoices;
  readonly id: ComboboxId;
  readonly query: Option.Option<string>;
}) => {
  const all = comboboxOptions(options.choices, options.id);

  const needle = normalizeText(
    Option.getOrElse(options.query, () => "").trim()
  );

  return needle === ""
    ? all
    : all.filter((choice) => normalizeText(choice.label).includes(needle));
};

export const selectedLabel = (options: {
  readonly choices: FilterChoices;
  readonly filters: FilterState;
  readonly id: ComboboxId;
}) =>
  options.filters[options.id]
    .map((value) =>
      comboboxLabel({ choices: options.choices, id: options.id, value })
    )
    .join(", ");

export const openFor = (
  combobox: Option.Option<OpenCombobox>,
  id: ComboboxId
) => Option.filter(combobox, (open) => open.id === id);

export const comboboxInputId = (id: ComboboxId) =>
  id === "track" || id === "category"
    ? `tag-filter-__${id}-input`
    : `${id}-filter-input`;

export const comboboxBaseId = (id: ComboboxId) =>
  id === "track" || id === "category" ? `tag-filter-__${id}` : `${id}-filter`;
