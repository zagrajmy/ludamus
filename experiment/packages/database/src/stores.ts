import { SubmissionThrottle } from "@zagrajmy/core";
import { Layer } from "effect";

import { AgendaItemStoreLive } from "./agenda-item-store.js";
import { AnnouncementStoreLive } from "./announcement-store.js";
import { BookmarkStoreLive } from "./bookmark-store.js";
import { ChangeLogStoreLive } from "./change-log-store.js";
import { DjangoSessionStoreLive } from "./django-session-store.js";
import { EncounterStoreLive } from "./encounter-store.js";
import { EnrollmentConfigStoreLive } from "./enrollment-config-store.js";
import { EnrollmentLive } from "./enrollment-layer.js";
import { EventStoreLive } from "./event-store.js";
import { FacilitatorStoreLive } from "./facilitator-store.js";
import { FieldStoreLive } from "./field-store.js";
import { PanelStoreLive } from "./panel-store.js";
import { ParticipationStoreLive } from "./participation-store.js";
import { PartyStoreLive } from "./party-store.js";
import { ProposalCategoryStoreLive } from "./proposal-category-store.js";
import { ProposerStoreLive } from "./proposer-store.js";
import { SafetyStoreLive } from "./safety-store.js";
import { SessionStoreLive } from "./session-store.js";
import { SpaceStoreLive } from "./space-store.js";
import { SphereStoreLive } from "./sphere-store.js";
import { TimeSlotStoreLive } from "./time-slot-store.js";
import { TrackStoreLive } from "./track-store.js";
import { StoreTransactionLive } from "./transaction.js";
import { UserDirectoryLive } from "./user-directory.js";
import { UserStoreLive } from "./user-store.js";

export const StoresLive = Layer.mergeAll(
  AgendaItemStoreLive,
  AnnouncementStoreLive,
  BookmarkStoreLive,
  ChangeLogStoreLive,
  DjangoSessionStoreLive,
  EncounterStoreLive,
  EnrollmentConfigStoreLive,
  EnrollmentLive,
  EventStoreLive,
  FacilitatorStoreLive,
  FieldStoreLive,
  PanelStoreLive,
  ParticipationStoreLive,
  PartyStoreLive,
  ProposalCategoryStoreLive,
  ProposerStoreLive,
  SafetyStoreLive,
  SessionStoreLive,
  SpaceStoreLive,
  SphereStoreLive,
  StoreTransactionLive,
  SubmissionThrottle.memory,
  TimeSlotStoreLive,
  TrackStoreLive,
  UserDirectoryLive,
  UserStoreLive
);
