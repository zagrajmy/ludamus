import { implement } from "@zagrajmy/capability/implement";
import { Effect } from "effect";

import { checkProposalStepContract } from "../contracts.js";
import { loadWizard } from "./context.js";
import { checkStep } from "./steps.js";

export const checkProposalStep = implement(
  checkProposalStepContract,
  ({ categoryId, data, eventSlug, step }) =>
    Effect.gen(function* checkProposalStepHandler() {
      const wizard = yield* loadWizard(eventSlug);

      return yield* checkStep({ categoryId, data, step, wizard });
    })
);
