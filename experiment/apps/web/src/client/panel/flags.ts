import { Schema } from "effect";
import { defineTaggedUnion } from "foldkit/schema";

import { CfpFlags } from "./cfp/flags.js";
import { PanelChromeFlags } from "./chrome.js";
import { DashboardFlags } from "./dashboard/flags.js";
import {
  FacilitatorBinFlags,
  FacilitatorDetailFlags,
  FacilitatorFormFlags,
  FacilitatorsFlags,
} from "./facilitators/flags.js";
import {
  ProposalDetailFlags,
  ProposalFormFlags,
  ProposalsFlags,
} from "./proposals/flags.js";
import { TimetableFlags } from "./timetable/flags.js";
import { TrackFormFlags, TracksFlags } from "./tracks/flags.js";

export const PanelPageFlags = defineTaggedUnion({
  Cfp: { flags: CfpFlags },
  Dashboard: { flags: DashboardFlags },
  FacilitatorBin: { flags: FacilitatorBinFlags },
  FacilitatorDetail: { flags: FacilitatorDetailFlags },
  FacilitatorForm: { flags: FacilitatorFormFlags },
  Facilitators: { flags: FacilitatorsFlags },
  ProposalDetail: { flags: ProposalDetailFlags },
  ProposalForm: { flags: ProposalFormFlags },
  Proposals: { flags: ProposalsFlags },
  Timetable: { flags: TimetableFlags },
  TrackForm: { flags: TrackFormFlags },
  Tracks: { flags: TracksFlags },
});

export type PanelPageFlags = typeof PanelPageFlags.Type;

export const PanelFlags = Schema.Struct({
  chrome: PanelChromeFlags,
  page: PanelPageFlags,
});

export type PanelFlags = typeof PanelFlags.Type;
