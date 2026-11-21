import type { AnyContract } from "./contract.js";

export const isMutation = (contract: AnyContract) =>
  !contract.annotations.readOnly;

export const requiresSignIn = (contract: AnyContract) =>
  isMutation(contract) && !contract.annotations.anonymousSafe;
