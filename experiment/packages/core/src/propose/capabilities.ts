import { checkProposalStep } from "./check-proposal-step.js";
import { readProposalForm } from "./read-proposal-form.js";
import { submitProposal } from "./submit-proposal.js";

export const proposeCapabilities = [
  readProposalForm,
  checkProposalStep,
  submitProposal,
] as const;
