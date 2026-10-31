import { Option } from "effect";
import { Command } from "foldkit";
import type { Update } from "foldkit";

import { comboboxInputId, shownOptions } from "./combobox.js";
import {
  BlurActiveElement,
  CloseSessionDialog,
  FocusElement,
  LoadHref,
  PushQuery,
  ReadClock,
  ReadRoster,
  ReplaceQuery,
  ScrollToElement,
  SelectInputText,
  SettleComboboxFocus,
  ShowSessionDialog,
} from "./command.js";
import type { QueryUpdate } from "./command.js";
import { enrollmentActionsFor } from "./enrollment-slot.js";
import {
  enrollmentCommands,
  updateEnrollmentFooter,
} from "./enrollment/update.js";
import {
  EMPTY_FILTERS,
  clearChip,
  isFilterParam,
  parseAge,
  parseFilters,
  serializeFilters,
} from "./filters.js";
import type { ComboboxId, FilterState } from "./filters.js";
import { EventPageMessage } from "./message.js";
import {
  finishedDays,
  openableSession,
  sessionParam,
  showsBookmarked,
  viewParam,
} from "./model.js";
import type { EventPageModel } from "./model.js";

type Return = Update.Return<EventPageModel, EventPageMessage>;

type Commands = NonNullable<Return["commands"]>;

const filterUpdates = (
  model: EventPageModel,
  filters: FilterState
): readonly QueryUpdate[] =>
  serializeFilters({ choices: model.choices, filters }).map(
    ([name, value]) => [name, value] as const
  );

const withFilters = (
  model: EventPageModel,
  filters: FilterState,
  extra: Commands = []
): Return => ({
  commands: [
    ReplaceQuery({ updates: filterUpdates(model, filters) }),
    ...extra,
  ],
  model: { ...model, filters },
});

const sameFilters = (
  model: EventPageModel,
  left: FilterState,
  right: FilterState
) =>
  JSON.stringify(
    serializeFilters({ choices: model.choices, filters: left })
  ) ===
  JSON.stringify(serializeFilters({ choices: model.choices, filters: right }));

const toggled = (values: readonly string[], value: string) =>
  values.includes(value)
    ? values.filter((candidate) => candidate !== value)
    : [...values, value];

const closeCombobox = (model: EventPageModel): EventPageModel => ({
  ...model,
  combobox: Option.none(),
});

const commitOption = (options: {
  readonly id: ComboboxId;
  readonly model: EventPageModel;
  readonly value: string;
}): Return => {
  const { id, model, value } = options;
  const filters = { ...model.filters, [id]: toggled(model.filters[id], value) };
  const all = shownOptions({
    choices: model.choices,
    id,
    query: Option.none(),
  });
  const active = all.findIndex((choice) => choice.value === value);

  return withFilters(
    {
      ...model,
      combobox: Option.some({ active, id, query: Option.none() }),
    },
    filters,
    [SettleComboboxFocus({ selector: `#${comboboxInputId(id)}` })]
  );
};

const openCombobox = (
  model: EventPageModel,
  id: ComboboxId
): EventPageModel => {
  const shown = shownOptions({
    choices: model.choices,
    id,
    query: Option.none(),
  });

  return {
    ...model,
    combobox: Option.some({
      active: shown.findIndex((choice) =>
        model.filters[id].includes(choice.value)
      ),
      id,
      query: Option.none(),
    }),
  };
};

const closePanel = (model: EventPageModel): Return => ({
  commands: [FocusElement({ selector: "#filter-toggle" })],
  model: { ...closeCombobox(model), isPanelOpen: false },
});

const moveActive = (
  model: EventPageModel,
  id: ComboboxId,
  delta: number
): Return => {
  const open = Option.filter(model.combobox, (combobox) => combobox.id === id);

  if (Option.isNone(open)) {
    const shown = shownOptions({
      choices: model.choices,
      id,
      query: Option.none(),
    });

    return {
      model: {
        ...model,
        combobox: Option.some({
          active: delta > 0 ? 0 : shown.length - 1,
          id,
          query: Option.none(),
        }),
      },
    };
  }

  const shown = shownOptions({
    choices: model.choices,
    id,
    query: open.value.query,
  });

  if (shown.length === 0) {
    return { model };
  }

  const current = open.value.active;

  const next =
    current === -1
      ? delta > 0
        ? 0
        : shown.length - 1
      : (current + delta + shown.length) % shown.length;

  return {
    model: {
      ...model,
      combobox: Option.some({ ...open.value, active: next }),
    },
  };
};

const pressedKey = (options: {
  readonly id: ComboboxId;
  readonly key: string;
  readonly model: EventPageModel;
}): Return => {
  const { id, key, model } = options;
  const open = Option.filter(model.combobox, (combobox) => combobox.id === id);

  if (key === "ArrowDown") {
    return moveActive(model, id, 1);
  }

  if (key === "ArrowUp") {
    return moveActive(model, id, -1);
  }

  if (key === "Escape") {
    return Option.isSome(open)
      ? { model: closeCombobox(model) }
      : closePanel(model);
  }

  if (key === "Tab") {
    return { model: closeCombobox(model) };
  }

  if (key === "Enter" && Option.isSome(open)) {
    const shown = shownOptions({
      choices: model.choices,
      id,
      query: open.value.query,
    });
    const row =
      open.value.active === -1
        ? shown.length === 1
          ? shown[0]
          : undefined
        : shown[open.value.active];

    return row === undefined
      ? { model: closeCombobox(model) }
      : commitOption({ id, model, value: row.value });
  }

  return { model };
};

const rosterCommands = (model: EventPageModel, sessionId: number): Commands => {
  const session = model.sessions.find(
    (candidate) => candidate.id === sessionId
  );
  const loaded = model.rosters.some((roster) => roster.sessionId === sessionId);

  return session === undefined || Option.isSome(session.roster) || loaded
    ? []
    : [ReadRoster({ locale: model.locale, sessionId, slug: model.hero.slug })];
};

const enrollmentFor = (model: EventPageModel, sessionId: number) => {
  const session = model.sessions.find(
    (candidate) => candidate.id === sessionId
  );

  return enrollmentActionsFor({
    canEnrollNow:
      session !== undefined &&
      (session.availability === "available" || session.availability === "full"),
    loginUrl: model.loginUrl,
    sessionId,
    signedIn: model.signedIn,
    slug: model.hero.slug,
    takesEnrollment: session?.takesEnrollment ?? false,
  });
};

const openSessionDialog = (
  model: EventPageModel,
  sessionId: number
): Return => ({
  commands: [
    ShowSessionDialog({ animate: true, sessionId }),
    ...rosterCommands(model, sessionId),
    ...enrollmentCommands(model, sessionId),
  ],
  model: {
    ...model,
    enrollment: enrollmentFor(model, sessionId),
    openSession: Option.some(sessionId),
    shownSession: Option.some(sessionId),
  },
});

const closeSessionDialog = (model: EventPageModel): Return =>
  Option.match(model.openSession, {
    onNone: () => ({ model }),
    onSome: (sessionId) => ({
      commands: [CloseSessionDialog({ sessionId })],
      model: { ...model, openSession: Option.none() },
    }),
  });

const unfoldFor = (model: EventPageModel, hash: string): EventPageModel => {
  if (!hash.startsWith("#slot-") || model.layout._tag !== "Compact") {
    return model;
  }

  const key = hash.slice("#slot-".length);
  const day = model.layout.days.find((candidate) =>
    candidate.hours.some((hour) => hour.slotKey === key)
  );

  return day === undefined
    ? model
    : {
        ...model,
        foldedDays: model.foldedDays.filter((date) => date !== day.day.date),
      };
};

const sameSearch = (model: EventPageModel, search: string): Return => {
  const params = new URLSearchParams(search);
  const names = [...params.keys()];
  const filterNames = names.filter(isFilterParam);

  const linked =
    filterNames.length === 0
      ? model.filters
      : {
          ...model.filters,
          ...parseFilters({
            choices: model.choices,
            search,
            showBookmarked: showsBookmarked(model),
          }),
          ...Object.fromEntries(
            Object.entries(model.filters).filter(
              ([key]) =>
                !filterNames.some((name) => paramKeys(name).includes(key))
            )
          ),
        };

  const opened = openableSession(model, search);

  const afterFilters: Return =
    filterNames.length === 0
      ? { model }
      : withFilters(closeCombobox(model), linked);

  if (Option.isSome(opened)) {
    const shown = openSessionDialog(afterFilters.model, opened.value);

    return {
      commands: [
        ...(afterFilters.commands ?? []),
        PushQuery({ updates: [["session", String(opened.value)]] }),
        ...(shown.commands ?? []),
      ],
      model: shown.model,
    };
  }

  if (Option.isSome(afterFilters.model.openSession) && filterNames.length > 0) {
    const closed = closeSessionDialog(afterFilters.model);

    return {
      commands: [
        ...(afterFilters.commands ?? []),
        ...(closed.commands ?? []),
        ReplaceQuery({ updates: [["session", null]] }),
      ],
      model: closed.model,
    };
  }

  return afterFilters;
};

const paramKeys = (name: string): readonly string[] => {
  if (name.startsWith("tag-")) {
    return ["tags"];
  }

  if (name === "hide-ended") {
    return ["hideEnded"];
  }

  if (name === "age-min") {
    return ["ageMin"];
  }

  return [name];
};

const switchedView = (model: EventPageModel, view: EventPageModel["view"]) =>
  model.layout._tag === "Compact" && model.view !== view
    ? {
        commands: [
          PushQuery({
            updates: [
              ["view", view === "rooms" ? "rooms" : null],
              ...filterUpdates(model, model.filters),
            ],
          }),
        ],
        model: { ...model, view },
      }
    : { model };

const clickedSamePageLink = (
  model: EventPageModel,
  link: Readonly<{ hash: string; search: string }>
): Return => {
  const params = new URLSearchParams(link.search);
  const names = [...params.keys()];
  const handled = names.every(
    (name) => isFilterParam(name) || name === "session" || name === "view"
  );

  if (!handled) {
    return {
      commands: [LoadHref({ href: `${link.search}${link.hash}` })],
      model,
    };
  }

  const viewed =
    params.has("view") && names.length === 1
      ? switchedView(model, viewParam({ isCompact: true, search: link.search }))
      : { model };

  const searched =
    names.length === 0 || (params.has("view") && names.length === 1)
      ? { model: viewed.model }
      : sameSearch(viewed.model, link.search);

  const scrolled = unfoldFor(searched.model, link.hash);

  return {
    commands: [
      ...(viewed.commands ?? []),
      ...(searched.commands ?? []),
      ...(link.hash === "" ? [] : [ScrollToElement({ selector: link.hash })]),
    ],
    model: scrolled,
  };
};

const changedUrl = (model: EventPageModel, search: string): Return => {
  const filters = parseFilters({
    choices: model.choices,
    search,
    showBookmarked: showsBookmarked(model),
  });

  const filtered = sameFilters(model, filters, model.filters)
    ? model
    : { ...model, filters };

  const view = viewParam({
    isCompact: model.layout._tag === "Compact",
    search,
  });

  const viewed = { ...filtered, view };
  const wanted = Option.filter(sessionParam(search), (id) =>
    model.sessions.some((session) => session.id === id)
  );

  if (
    Option.getOrElse(wanted, () => -1) ===
    Option.getOrElse(model.openSession, () => -1)
  ) {
    return { model: viewed };
  }

  return Option.match(wanted, {
    onNone: () => closeSessionDialog(viewed),
    onSome: (id) => openSessionDialog(viewed, id),
  });
};

export const initEventPageCommands = (model: EventPageModel): Commands => [
  ReadClock(),
  ...(Option.isSome(model.openSession)
    ? [
        ShowSessionDialog({
          animate: false,
          sessionId: Option.getOrElse(model.openSession, () => 0),
        }),
      ]
    : []),
  ReplaceQuery({ updates: filterUpdates(model, model.filters) }),
  ...Option.match(model.openSession, {
    onNone: () => [],
    onSome: (id) => [
      ...rosterCommands(model, id),
      ...enrollmentCommands(model, id),
    ],
  }),
];

export const updateEventPage = (
  model: EventPageModel,
  message: EventPageMessage
): Return =>
  EventPageMessage.match<Return>(message, {
    BlurredCombobox: ({ id }) =>
      Option.exists(model.combobox, (open) => open.id === id)
        ? { model: closeCombobox(model) }
        : { model },
    ChangedAge: ({ value }) =>
      withFilters(model, {
        ...model.filters,
        age: Option.match(parseAge(value), {
          onNone: () => "",
          onSome: String,
        }),
      }),
    ChangedSearch: ({ value }) =>
      withFilters(model, { ...model.filters, q: value }),
    ChangedSelect: ({ id, value }) =>
      withFilters(model, { ...model.filters, [id]: value }),
    ChangedTag: ({ slug, value }) =>
      withFilters(model, {
        ...model.filters,
        tags: [
          ...model.filters.tags.filter((tag) => tag.slug !== slug),
          ...(value === "" ? [] : [{ slug, value }]),
        ],
      }),
    ChangedUrl: ({ search }) => changedUrl(model, search),
    ChangedViewport: ({ isNarrow }) => ({ model: { ...model, isNarrow } }),
    ClickedApplyFilters: () => closePanel(model),
    ClickedClearAll: () =>
      withFilters(
        { ...closeCombobox(model), isPanelOpen: false },
        EMPTY_FILTERS
      ),
    ClickedCloseFilters: () => closePanel(model),
    ClickedCombobox: ({ id }) =>
      Option.exists(model.combobox, (open) => open.id === id)
        ? { model }
        : {
            commands: [
              SelectInputText({ selector: `#${comboboxInputId(id)}` }),
            ],
            model: openCombobox(model, id),
          },
    ClickedComboboxToggle: ({ id }) => ({
      commands: [FocusElement({ selector: `#${comboboxInputId(id)}` })],
      model: Option.exists(model.combobox, (open) => open.id === id)
        ? closeCombobox(model)
        : openCombobox(model, id),
    }),
    ClickedDayFold: ({ date }) => ({
      model: {
        ...model,
        foldedDays: model.foldedDays.includes(date)
          ? model.foldedDays.filter((candidate) => candidate !== date)
          : [...model.foldedDays, date],
      },
    }),
    ClickedFiltersToggle: () =>
      model.isPanelOpen
        ? { model: { ...closeCombobox(model), isPanelOpen: false } }
        : {
            commands: model.isNarrow
              ? [FocusElement({ selector: "#filter-close" })]
              : [],
            model: { ...model, isPanelOpen: true },
          },
    ClickedOutsideFilters: () => {
      if (model.isPanelOpen) {
        return { model: { ...closeCombobox(model), isPanelOpen: false } };
      }

      return Option.isSome(model.combobox)
        ? { model: closeCombobox(model) }
        : { model };
    },
    ClickedRemoveChip: ({ chip }) =>
      withFilters(
        { ...closeCombobox(model), isPanelOpen: false },
        clearChip(model.filters, chip)
      ),
    ClickedSamePageLink: (link) => clickedSamePageLink(model, link),
    ClosedSessionDialog: () => {
      const closed = closeSessionDialog(model);

      return {
        commands: [
          ...(closed.commands ?? []),
          ReplaceQuery({ updates: [["session", null]] }),
        ],
        model: closed.model,
      };
    },
    CompletedFocus: () => ({ model }),
    CompletedScroll: () => ({ model }),
    CompletedUrlUpdate: () => ({ model }),
    FailedReadRoster: () => ({ model }),
    FocusedGuard: ({ selector }) => ({
      commands: [FocusElement({ selector })],
      model,
    }),
    GotBootClock: ({ now }) => ({
      model: {
        ...model,
        foldedDays: finishedDays({ ...model, now }),
        now,
      },
    }),
    GotEnrollmentMessage: ({ message: enrollmentMessage }) =>
      updateEnrollmentFooter(model, enrollmentMessage),
    HoveredOption: ({ id, index }) => ({
      model: {
        ...model,
        combobox: Option.map(model.combobox, (open) =>
          open.id === id && open.active !== index
            ? { ...open, active: index }
            : open
        ),
      },
    }),
    PickedOption: ({ id, pointerType, value }) => {
      const committed = commitOption({ id, model, value });

      return pointerType === "touch"
        ? {
            commands: [...(committed.commands ?? []), BlurActiveElement()],
            model: closeCombobox(committed.model),
          }
        : committed;
    },
    PressedComboboxKey: ({ id, key }) => pressedKey({ id, key, model }),
    PressedEscape: () => {
      if (Option.isSome(model.openSession)) {
        const closed = closeSessionDialog(model);

        return {
          commands: [
            ...(closed.commands ?? []),
            ReplaceQuery({ updates: [["session", null]] }),
          ],
          model: closed.model,
        };
      }

      if (model.isCalendarMenuOpen) {
        return { model: { ...model, isCalendarMenuOpen: false } };
      }

      return model.isPanelOpen && Option.isNone(model.openSession)
        ? closePanel(model)
        : { model };
    },
    SucceededReadRoster: ({ entries, sessionId }) => ({
      model: {
        ...model,
        sessions: model.sessions.map((session) =>
          session.id === sessionId
            ? { ...session, roster: Option.some(entries) }
            : session
        ),
      },
    }),
    SwitchedView: ({ view }) => switchedView(model, view),
    Ticked: ({ now }) => ({ model: { ...model, now } }),
    ToggledCalendarMenu: ({ isOpen }) => ({
      model: { ...model, isCalendarMenuOpen: isOpen },
    }),
    ToggledFlag: ({ checked, id }) =>
      withFilters(model, { ...model.filters, [id]: checked }),
    TypedCombobox: ({ id, value }) => ({
      model: {
        ...model,
        combobox: Option.some({ active: -1, id, query: Option.some(value) }),
      },
    }),
  });

export const isSessionOpen = (model: EventPageModel, id: number) =>
  Option.contains(model.openSession, id);
