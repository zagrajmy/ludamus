import { Schema } from "effect";
import { defineMessageUnion } from "foldkit/message";

import { EnrollmentSlotMessage } from "./enrollment-slot.js";
import { ComboboxId, FilterChip, FlagId, SelectId } from "./filters.js";
import { RosterEntry, ScheduleView } from "./flags.js";

export const EventPageMessage = defineMessageUnion({
  BlurredCombobox: { id: ComboboxId },
  ChangedAge: { value: Schema.String },
  ChangedSearch: { value: Schema.String },
  ChangedSelect: { id: SelectId, value: Schema.String },
  ChangedTag: { slug: Schema.String, value: Schema.String },
  ChangedUrl: { search: Schema.String },
  ChangedViewport: { isNarrow: Schema.Boolean },
  ClickedApplyFilters: {},
  ClickedClearAll: {},
  ClickedCloseFilters: {},
  ClickedCombobox: { id: ComboboxId },
  ClickedComboboxToggle: { id: ComboboxId },
  ClickedDayFold: { date: Schema.String },
  ClickedFiltersToggle: {},
  ClickedOutsideFilters: {},
  ClickedRemoveChip: { chip: FilterChip },
  ClickedSamePageLink: { hash: Schema.String, search: Schema.String },
  ClosedSessionDialog: {},
  CompletedFocus: {},
  CompletedScroll: {},
  CompletedUrlUpdate: {},
  FailedReadRoster: { sessionId: Schema.Int },
  FocusedGuard: { selector: Schema.String },
  GotBootClock: { now: Schema.Number },
  GotEnrollmentMessage: { message: EnrollmentSlotMessage },
  HoveredOption: { id: ComboboxId, index: Schema.Int },
  PickedOption: {
    id: ComboboxId,
    pointerType: Schema.String,
    value: Schema.String,
  },
  PressedComboboxKey: {
    id: ComboboxId,
    key: Schema.String,
    shiftKey: Schema.Boolean,
  },
  PressedEscape: {},
  SucceededReadRoster: {
    entries: Schema.Array(RosterEntry),
    sessionId: Schema.Int,
  },
  SwitchedView: { view: ScheduleView },
  Ticked: { now: Schema.Number },
  ToggledCalendarMenu: { isOpen: Schema.Boolean },
  ToggledFlag: { checked: Schema.Boolean, id: FlagId },
  TypedCombobox: { id: ComboboxId, value: Schema.String },
});

export type EventPageMessage = typeof EventPageMessage.Type;
