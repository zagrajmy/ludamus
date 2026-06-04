import assert from "node:assert/strict";
import test from "node:test";

import * as staging from "./github-staging.mts";
import type { ActionArgs, PullRequestLike } from "./github-staging.mts";

type Call = readonly unknown[];

type MockOptions = {
  currentPr?: PullRequestLike;
  inputs?: {
    pr_number?: string;
    sha?: string;
  };
  labelName?: string;
  pr?: PullRequestLike;
  prsForSha?: PullRequestLike[];
  sha?: string;
  stagingPrs?: PullRequestLike[];
};

const basePr = {
  head: { sha: "head-sha" },
  labels: [{ name: "staging" }],
  number: 2,
  state: "open",
};

const makeArgs = ({
  currentPr = basePr,
  inputs,
  labelName = "staging",
  pr = basePr,
  prsForSha = [],
  sha = "workflow-sha",
  stagingPrs = [],
}: MockOptions = {}): ActionArgs & { calls: Call[] } => {
  const calls: Call[] = [];
  const core = {
    info: (message: string) => calls.push(["info", message]),
    setOutput: (name: string, value: string) => calls.push(["output", name, value]),
  };
  const github: ActionArgs["github"] = {
    paginate: async (
      fn: (params: Record<string, unknown>) => Promise<PullRequestLike[]>,
      params: Record<string, unknown>,
    ) => fn(params),
    rest: {
      actions: {
        createWorkflowDispatch: async (params: Record<string, unknown>) =>
          calls.push(["dispatch", params]),
      },
      issues: {
        listForRepo: async () => stagingPrs,
        removeLabel: async (params: { issue_number: number }) =>
          calls.push(["remove", params.issue_number]),
      },
      pulls: {
        get: async () => ({ data: currentPr }),
      },
      repos: {
        listPullRequestsAssociatedWithCommit: async () => prsForSha,
      },
    },
  };
  const context: ActionArgs["context"] = {
    repo: { owner: "owner", repo: "repo" },
    sha,
    payload: {
      action: "labeled",
      inputs,
      label: { name: labelName },
      pull_request: pr,
      repository: { default_branch: "main" },
    },
  };

  return { calls, context, core, github };
};

test("dispatches the labeled PR and clears stale labels from other PRs", async () => {
  const args = makeArgs({
    stagingPrs: [
      { number: 1, pull_request: {}, state: "open" },
      { number: 2, pull_request: {}, state: "open" },
    ],
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [
    ["remove", 1],
    ["info", "Removed staging from PR #1"],
    [
      "dispatch",
      {
        owner: "owner",
        repo: "repo",
        workflow_id: "deploy-staging.yml",
        ref: "main",
        inputs: {
          pr_number: "2",
          sha: "head-sha",
        },
      },
    ],
    ["info", "Dispatched deploy-staging.yml for PR #2 at head-sha"],
  ]);
});

test("stale explicit dispatch does not remove another PR staging label", async () => {
  const args = makeArgs({
    currentPr: {
      head: { sha: "new-head-sha" },
      labels: [{ name: "staging" }],
      number: 1,
      state: "open",
    },
    inputs: { pr_number: "1", sha: "old-head-sha" },
    stagingPrs: [{ number: 2, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "old-head-sha"],
    ["output", "should_deploy", "false"],
    ["info", "PR #1 is no longer the current staging target for old-head-sha"],
  ]);
});

test("current explicit dispatch deploys and clears other staging labels", async () => {
  const args = makeArgs({
    currentPr: basePr,
    inputs: { pr_number: "2", sha: "head-sha" },
    stagingPrs: [
      { number: 1, pull_request: {}, state: "open" },
      { number: 2, pull_request: {}, state: "open" },
    ],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "head-sha"],
    ["remove", 1],
    ["info", "Removed staging from PR #1"],
    ["output", "should_deploy", "true"],
    ["info", "Deploying PR #2 at head-sha"],
  ]);
});

test("manual dispatch with no unique staging PR is non-mutating", async () => {
  const args = makeArgs({
    inputs: { sha: "manual-sha" },
    prsForSha: [{ number: 1 }],
    stagingPrs: [{ number: 2, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["output", "should_deploy", "false"],
    ["info", "No unique open PR with staging for manual-sha"],
  ]);
});

test("manual dispatch with invalid PR number is non-mutating", async () => {
  const args = makeArgs({
    inputs: { pr_number: "abc", sha: "manual-sha" },
    stagingPrs: [{ number: 2, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["output", "should_deploy", "false"],
    ["info", "Invalid pull request number: abc"],
  ]);
});

test("ignores non-staging labels", async () => {
  const args = makeArgs({ labelName: "bug" });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [["info", "Ignoring non-staging label"]]);
});
