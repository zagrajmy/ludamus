import {
  createFacilitator,
  deleteFacilitator,
  restoreFacilitator,
  updateFacilitator,
} from "./facilitators.js";
import {
  changeProposalStatus,
  deleteProposal,
  restoreProposal,
  saveProposal,
} from "./proposals.js";
import { createTrack, deleteTrack, updateTrack } from "./tracks.js";

export const panelCapabilities = [
  createTrack,
  updateTrack,
  deleteTrack,
  createFacilitator,
  updateFacilitator,
  deleteFacilitator,
  restoreFacilitator,
  changeProposalStatus,
  deleteProposal,
  restoreProposal,
  saveProposal,
] as const;
