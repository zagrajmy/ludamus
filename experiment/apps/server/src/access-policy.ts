import { isMutation, requiresSignIn } from "@zagrajmy/capability/access";
import type { AnyContract } from "@zagrajmy/capability/contract";
import { CrossSiteRequest, SignInRequired } from "@zagrajmy/capability/refusal";
import { Effect, Schema } from "effect";

export const Admission = Schema.Union([CrossSiteRequest, SignInRequired]);

export interface Requirement {
  readonly capabilityName: string;
  readonly mutation: boolean;
  readonly signIn: boolean;
}

export interface Caller {
  readonly sameOrigin: boolean;
  readonly signedIn: boolean;
}

export const requirementOf = (contract: AnyContract): Requirement => ({
  capabilityName: contract.name,
  mutation: isMutation(contract),
  signIn: requiresSignIn(contract),
});

export const strictestRequirement = (capabilityName: string): Requirement => ({
  capabilityName,
  mutation: true,
  signIn: true,
});

export const admit = Effect.fn("AccessPolicy.admit")(function* admit(
  requirement: Requirement,
  caller: Caller
) {
  const { capabilityName } = requirement;

  if (requirement.mutation && !caller.sameOrigin) {
    yield* new CrossSiteRequest({ capabilityName });
  }

  if (requirement.signIn && !caller.signedIn) {
    yield* new SignInRequired({ capabilityName });
  }
});

export const refuseWithoutUser = <A, E, R>(
  contract: AnyContract,
  run: Effect.Effect<A, E, R>
) =>
  requiresSignIn(contract)
    ? Effect.die(new SignInRequired({ capabilityName: contract.name }))
    : run;
