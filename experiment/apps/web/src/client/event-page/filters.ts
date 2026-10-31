import { Option, Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import type { Translator } from "../../ui/i18n.js";
import type { FilterChoices, SessionView } from "./flags.js";

export const TagPick = Schema.Struct({
  slug: Schema.String,
  value: Schema.String,
});

export type TagPick = typeof TagPick.Type;

export const FilterState = Schema.Struct({
  age: Schema.String,
  ageMin: Schema.String,
  category: Schema.Array(Schema.String),
  day: Schema.String,
  enrollment: Schema.Boolean,
  hideEnded: Schema.Boolean,
  host: Schema.Array(Schema.String),
  hour: Schema.String,
  q: Schema.String,
  space: Schema.Array(Schema.String),
  status: Schema.String,
  tags: Schema.Array(TagPick),
  track: Schema.Array(Schema.String),
});

export type FilterState = typeof FilterState.Type;

export const ComboboxId = Schema.Literals([
  "category",
  "host",
  "space",
  "track",
]);

export type ComboboxId = typeof ComboboxId.Type;

export const SelectId = Schema.Literals(["ageMin", "day", "hour", "status"]);

export type SelectId = typeof SelectId.Type;

export const FlagId = Schema.Literals(["enrollment", "hideEnded"]);

export type FlagId = typeof FlagId.Type;

export const EMPTY_FILTERS: FilterState = {
  age: "",
  ageMin: "",
  category: [],
  day: "",
  enrollment: false,
  hideEnded: false,
  host: [],
  hour: "",
  q: "",
  space: [],
  status: "",
  tags: [],
  track: [],
};

export const VENUE_PREFIX = "venue:";

export const STATUS_VALUES = [
  "available",
  "full",
  "in-progress",
  "unavailable",
  "ended",
  "my-enrolled",
  "my-waiting",
  "my-bookmarked",
] as const;

const NON_DECOMPOSING: Readonly<Record<string, string>> = {
  ß: "ss",
  æ: "ae",
  ø: "o",
  đ: "d",
  ħ: "h",
  ı: "i",
  ł: "l",
  œ: "oe",
};

export const normalizeText = (value: string) =>
  value
    .toLowerCase()
    .replaceAll(/[łøđħıœæß]/gu, (char) => NON_DECOMPOSING[char] ?? char)
    .normalize("NFD")
    .replaceAll(/[̀-ͯ]/gu, "");

export const parseAge = (raw: string) => {
  if (raw.trim() === "") {
    return Option.none<number>();
  }

  const value = Number(raw);

  return Number.isInteger(value) && value >= 0 && value <= 99
    ? Option.some(value)
    : Option.none<number>();
};

const parseList = (raw: string | null): readonly string[] => {
  if (raw === null || raw === "") {
    return [];
  }

  const decoded = Option.getOrUndefined(
    Schema.decodeUnknownOption(Schema.fromJsonString(Schema.Unknown))(raw)
  );

  if (decoded === undefined) {
    return [raw];
  }

  if (!Array.isArray(decoded)) {
    return [raw];
  }

  return [
    ...new Set(
      decoded.flatMap((value: unknown) =>
        typeof value === "string" && value !== "" ? [value] : []
      )
    ),
  ];
};

const known = (values: readonly string[], allowed: ReadonlySet<string>) =>
  values.filter((value) => allowed.has(value));

const choiceOrEmpty = (raw: string | null, allowed: ReadonlySet<string>) =>
  raw !== null && allowed.has(raw) ? raw : "";

export const statusValues = (options: {
  readonly showBookmarked: boolean;
}): readonly string[] =>
  STATUS_VALUES.filter(
    (value) => value !== "my-bookmarked" || options.showBookmarked
  );

export const parseFilters = (options: {
  readonly choices: FilterChoices;
  readonly search: string;
  readonly showBookmarked: boolean;
}): FilterState => {
  const params = new URLSearchParams(options.search);
  const { choices } = options;

  const ageMins = new Set(choices.minAges.map(String));

  const tags = choices.tagFields.flatMap((field) => {
    const value = params.get(`tag-${field.slug}`);

    return value !== null && field.options.includes(value)
      ? [{ slug: field.slug, value }]
      : [];
  });

  return {
    age: Option.match(parseAge(params.get("age") ?? ""), {
      onNone: () => "",
      onSome: String,
    }),
    ageMin: choiceOrEmpty(params.get("age-min"), ageMins),
    category: known(
      parseList(params.get("category")),
      new Set(choices.categories)
    ),
    day: choiceOrEmpty(
      params.get("day"),
      new Set(choices.days.map((day) => day.value))
    ),
    enrollment: (params.get("enrollment") ?? "") !== "",
    hideEnded: (params.get("hide-ended") ?? "") !== "",
    host: known(parseList(params.get("host")), new Set(choices.hosts)),
    hour: choiceOrEmpty(params.get("hour"), new Set(choices.hours)),
    q: params.get("q") ?? "",
    space: known(
      parseList(params.get("space")),
      new Set(choices.spaces.map((space) => space.value))
    ),
    status: choiceOrEmpty(
      params.get("status"),
      new Set(statusValues({ showBookmarked: options.showBookmarked }))
    ),
    tags,
    track: known(parseList(params.get("track")), new Set(choices.tracks)),
  };
};

const list = (values: readonly string[]) =>
  values.length === 0 ? null : JSON.stringify(values);

const text = (value: string) => (value.trim() === "" ? null : value.trim());

export const FILTER_PARAMS = [
  "q",
  "enrollment",
  "hide-ended",
  "status",
  "space",
  "age",
  "age-min",
  "day",
  "hour",
  "track",
  "category",
  "host",
] as const;

export const isFilterParam = (name: string) =>
  name.startsWith("tag-") || FILTER_PARAMS.some((param) => param === name);

export const serializeFilters = (options: {
  readonly choices: FilterChoices;
  readonly filters: FilterState;
}): readonly (readonly [string, string | null])[] => {
  const { filters } = options;

  return [
    ["q", text(filters.q)],
    ["enrollment", filters.enrollment ? "1" : null],
    ["hide-ended", filters.hideEnded ? "1" : null],
    ["status", text(filters.status)],
    ["space", list(filters.space)],
    ["age", text(filters.age)],
    ["age-min", text(filters.ageMin)],
    ["day", text(filters.day)],
    ["hour", text(filters.hour)],
    ["track", list(filters.track)],
    ["category", list(filters.category)],
    ...options.choices.tagFields.map(
      (field) =>
        [
          `tag-${field.slug}`,
          filters.tags.find((tag) => tag.slug === field.slug)?.value ?? null,
        ] as const
    ),
    ["host", list(filters.host)],
  ];
};

export const filterSearch = (options: {
  readonly choices: FilterChoices;
  readonly filters: FilterState;
  readonly search: string;
}) => {
  const params = new URLSearchParams(options.search);

  for (const [name, value] of serializeFilters(options)) {
    if (value === null) {
      params.delete(name);
    } else {
      params.set(name, value);
    }
  }

  const rendered = params.toString();

  return rendered === "" ? "" : `?${rendered}`;
};

export const isEnded = (session: SessionView, now: number) =>
  Option.match(session.timing, {
    onNone: () => false,
    onSome: (timing) => timing.endsAt <= now,
  });

const isOngoing = (session: SessionView, now: number) =>
  Option.match(session.timing, {
    onNone: () => false,
    onSome: (timing) => timing.startsAt <= now && now < timing.endsAt,
  });

export const availabilityAt = (session: SessionView, now: number) => {
  if (session.availability === "proposal") {
    return session.availability;
  }

  return isEnded(session, now) ? "ended" : session.availability;
};

export const statusAt = (session: SessionView, now: number) =>
  isOngoing(session, now) ? "in-progress" : availabilityAt(session, now);

const haystackOf = (session: SessionView) =>
  normalizeText(
    `${session.title.toLowerCase()} ${session.host} ${session.description} ${session.tags.replaceAll(",", " ")}`
  );

const matchesStatus = (session: SessionView, value: string, now: number) => {
  if (value === "my-enrolled") {
    return session.userEnrolled;
  }

  if (value === "my-waiting") {
    return session.userWaiting;
  }

  if (value === "my-bookmarked") {
    return session.userBookmarked;
  }

  return statusAt(session, now) === value;
};

const matchesSpace = (session: SessionView, value: string) =>
  value.startsWith(VENUE_PREFIX)
    ? session.venueId === value.slice(VENUE_PREFIX.length)
    : session.spaceId === value;

const tagPairs = (session: SessionView) =>
  session.tagCategories
    .split(";")
    .filter((pair) => pair.trim() !== "")
    .map((pair) => pair.toLowerCase());

const matchesTag = (session: SessionView, slug: string, value: string) =>
  tagPairs(session).includes(`${slug}:${value}`.toLowerCase());

const timingField = (session: SessionView, key: "day" | "hour") =>
  Option.match(session.timing, {
    onNone: () => "",
    onSome: (timing) => timing[key],
  });

const anyOf = (values: readonly string[], test: (value: string) => boolean) =>
  values.length === 0 || values.some(test);

const exact = (value: string, test: (value: string) => boolean) =>
  value === "" || test(value);

export const sessionMatches = (options: {
  readonly filters: FilterState;
  readonly now: number;
  readonly session: SessionView;
}) => {
  const { filters, now, session } = options;
  const tokens = normalizeText(filters.q).split(/\s+/u).filter(Boolean);
  const haystack = tokens.length === 0 ? "" : haystackOf(session);
  const age = parseAge(filters.age);

  return (
    tokens.every((token) => haystack.includes(token)) &&
    (!filters.enrollment || session.takesEnrollment) &&
    (!filters.hideEnded || !isEnded(session, now)) &&
    exact(filters.status, (value) => matchesStatus(session, value, now)) &&
    anyOf(filters.space, (value) => matchesSpace(session, value)) &&
    Option.match(age, {
      onNone: () => true,
      onSome: (limit) => session.minAge <= limit,
    }) &&
    exact(filters.ageMin, (value) => session.minAge >= Number(value)) &&
    exact(filters.day, (value) => timingField(session, "day") === value) &&
    exact(filters.hour, (value) => timingField(session, "hour") === value) &&
    anyOf(filters.track, (value) => matchesTag(session, "__track", value)) &&
    anyOf(filters.category, (value) =>
      matchesTag(session, "__category", value)
    ) &&
    filters.tags.every((tag) => matchesTag(session, tag.slug, tag.value)) &&
    anyOf(filters.host, (value) => session.host === value)
  );
};

export const FilterChip = defineTaggedUnion({
  Age: {},
  Combobox: { id: ComboboxId, value: Schema.String },
  Flag: { id: FlagId },
  Select: { id: SelectId },
  Tag: { slug: Schema.String },
});

export type FilterChip = typeof FilterChip.Type;

export type LabelledChip = Readonly<{ chip: FilterChip; label: string }>;

export const statusLabel = (value: string, translator: Translator) => {
  const labels: Readonly<Record<string, string>> = {
    available: translator.t("Available spots"),
    ended: translator.t("Ended"),
    full: translator.t("Full"),
    "in-progress": translator.t("In progress"),
    "my-bookmarked": translator.t("Bookmarked"),
    "my-enrolled": translator.t("I am enrolled"),
    "my-waiting": translator.t("I am waiting"),
    unavailable: translator.t("Enrollment unavailable"),
  };

  return labels[value] ?? value;
};

export const comboboxValues = (filters: FilterState, id: ComboboxId) =>
  filters[id];

export const comboboxLabel = (options: {
  readonly choices: FilterChoices;
  readonly id: ComboboxId;
  readonly value: string;
}) =>
  options.id === "space"
    ? (options.choices.spaces.find((space) => space.value === options.value)
        ?.label ?? options.value)
    : options.value;

export const activeChips = (options: {
  readonly choices: FilterChoices;
  readonly filters: FilterState;
  readonly translator: Translator;
}): readonly LabelledChip[] => {
  const { choices, filters, translator } = options;

  const combo = (id: ComboboxId) =>
    filters[id].map((value) => ({
      chip: FilterChip.Combobox({ id, value }),
      label: comboboxLabel({ choices, id, value }),
    }));

  const select = (id: SelectId, label: string) =>
    filters[id] === "" ? [] : [{ chip: FilterChip.Select({ id }), label }];

  return [
    ...(filters.enrollment
      ? [
          {
            chip: FilterChip.Flag({ id: "enrollment" }),
            label: translator.t("Only with enrollment"),
          },
        ]
      : []),
    ...(filters.hideEnded
      ? [
          {
            chip: FilterChip.Flag({ id: "hideEnded" }),
            label: translator.t("Hide ended"),
          },
        ]
      : []),
    ...select("status", statusLabel(filters.status, translator)),
    ...combo("space"),
    ...(filters.age === ""
      ? []
      : [
          {
            chip: FilterChip.Age(),
            label: `${translator.t("Participant age")}: ${filters.age}`,
          },
        ]),
    ...select("ageMin", `${filters.ageMin}+`),
    ...select(
      "day",
      choices.days.find((day) => day.value === filters.day)?.label ??
        filters.day
    ),
    ...select("hour", filters.hour),
    ...combo("track"),
    ...combo("category"),
    ...filters.tags.map((tag) => ({
      chip: FilterChip.Tag({ slug: tag.slug }),
      label: tag.value,
    })),
    ...combo("host"),
  ];
};

export const clearChip = (
  filters: FilterState,
  chip: FilterChip
): FilterState =>
  FilterChip.match(chip, {
    Age: () => ({ ...filters, age: "" }),
    Combobox: ({ id, value }) => ({
      ...filters,
      [id]: filters[id].filter((candidate) => candidate !== value),
    }),
    Flag: ({ id }) => ({ ...filters, [id]: false }),
    Select: ({ id }) => ({ ...filters, [id]: "" }),
    Tag: ({ slug }) => ({
      ...filters,
      tags: filters.tags.filter((tag) => tag.slug !== slug),
    }),
  });

export const isFiltering = (filters: FilterState) =>
  filters.q.trim() !== "" ||
  filters.enrollment ||
  filters.hideEnded ||
  filters.status !== "" ||
  filters.space.length > 0 ||
  filters.age !== "" ||
  filters.ageMin !== "" ||
  filters.day !== "" ||
  filters.hour !== "" ||
  filters.track.length > 0 ||
  filters.category.length > 0 ||
  filters.tags.length > 0 ||
  filters.host.length > 0;
