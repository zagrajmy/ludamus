import assert from "node:assert/strict";
import test from "node:test";

import * as staging from "./github-staging.mts";
import type { ActionArgs, PullRequestLike } from "./github-staging.mts";

type Call = readonly unknown[];

interface MockActionArgs extends ActionArgs {
  calls: Call[];
}

type MockOptions = {
  action?: string;
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
  head: { repo: { full_name: "owner/repo" }, sha: "head-sha" },
  labels: [{ name: "staging" }],
  number: 2,
  state: "open",
};

process.env.GITHUB_RUN_ID = "run-id";
process.env.GITHUB_SERVER_URL = "https://github.com";

const makeArgs = ({
  action = "labeled",
  currentPr = basePr,
  inputs,
  labelName = "staging",
  pr = basePr,
  prsForSha = [],
  sha = "workflow-sha",
  stagingPrs = [],
}: MockOptions = {}): MockActionArgs => {
  const calls: Call[] = [];
  const core = {
    info: (message: string) => calls.push(["info", message]),
    setOutput: (name: string, value: string) =>
      calls.push(["output", name, value]),
  };
  const github: ActionArgs["github"] = {
    paginate: async (
      fn: (params: Record<string, unknown>) => Promise<PullRequestLike[]>,
      params: Record<string, unknown>,
    ) => {
      const perPage = (params.per_page as number | undefined) ?? 100;
      const pages: PullRequestLike[] = [];
      let page = 1;
      while (true) {
        const pageResults = await fn({ ...params, page, per_page: perPage });
        if (pageResults.length === 0) break;
        pages.push(...pageResults);
        if (pageResults.length < perPage) break;
        page += 1;
      }
      return pages;
    },
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
        createDeployment: async (params: Record<string, unknown>) => {
          calls.push(["create-deployment", params]);
          return { data: { id: 42 } };
        },
        createDeploymentStatus: async (params: Record<string, unknown>) =>
          calls.push(["deployment-status", params]),
        listPullRequestsAssociatedWithCommit: async () => prsForSha,
      },
    },
  };
  const context: ActionArgs["context"] = {
    repo: { owner: "owner", repo: "repo" },
    sha,
    payload: {
      action,
      inputs,
      label: { name: labelName },
      pull_request: pr,
      repository: { default_branch: "main" },
    },
  };

  return { calls, context, core, github };
};

test("dispatches the labeled PR without mutating other labels", async () => {
  const args = makeArgs({
    stagingPrs: [
      { number: 1, pull_request: {}, state: "open" },
      { number: 2, pull_request: {}, state: "open" },
    ],
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [
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

test("redeploys a labeled PR on synchronize", async () => {
  const args = makeArgs({
    action: "synchronize",
    labelName: undefined,
    stagingPrs: [{ number: 2, pull_request: {}, state: "open" }],
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [
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

test("does not redeploy an unlabeled PR on synchronize", async () => {
  const args = makeArgs({
    action: "synchronize",
    labelName: undefined,
    currentPr: { ...basePr, labels: [] },
    pr: { ...basePr, labels: [] },
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [["info", "PR #2 does not have staging"]]);
});

test("does not redeploy a fork PR on synchronize", async () => {
  const forkPr = {
    head: { repo: { full_name: "contributor/repo" }, sha: "head-sha" },
    labels: [{ name: "staging" }],
    number: 3,
    state: "open",
  };
  const args = makeArgs({
    action: "synchronize",
    labelName: undefined,
    currentPr: forkPr,
    pr: forkPr,
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [
    ["info", "Skipping staging deploy for fork PR #3"],
  ]);
});

test("stale explicit dispatch does not remove another PR staging label", async () => {
  const args = makeArgs({
    currentPr: {
      head: { repo: { full_name: "owner/repo" }, sha: "new-head-sha" },
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
    [
      "info",
      "PR #1 head new-head-sha no longer matches requested old-head-sha",
    ],
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

test("explicit dispatch deploys an unlabeled PR and rips staging from others", async () => {
  const args = makeArgs({
    currentPr: { ...basePr, labels: [] },
    inputs: { pr_number: "2", sha: "head-sha" },
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
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

test("explicit dispatch does not deploy fork pull requests", async () => {
  const args = makeArgs({
    currentPr: {
      head: { repo: { full_name: "contributor/repo" }, sha: "head-sha" },
      labels: [{ name: "staging" }],
      number: 2,
      state: "open",
    },
    inputs: { pr_number: "2", sha: "head-sha" },
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "head-sha"],
    ["output", "should_deploy", "false"],
    ["info", "Skipping staging deploy for fork PR #2"],
  ]);
});

test("explicit dispatch does not deploy an unlabeled fork PR", async () => {
  const args = makeArgs({
    currentPr: {
      head: { repo: { full_name: "contributor/repo" }, sha: "head-sha" },
      labels: [],
      number: 2,
      state: "open",
    },
    inputs: { pr_number: "2", sha: "head-sha" },
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "head-sha"],
    ["output", "should_deploy", "false"],
    ["info", "Skipping staging deploy for fork PR #2"],
  ]);
});

test("explicit dispatch does not deploy draft pull requests", async () => {
  const args = makeArgs({
    currentPr: { ...basePr, draft: true },
    inputs: { pr_number: "2", sha: "head-sha" },
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "head-sha"],
    ["output", "should_deploy", "false"],
    ["info", "PR #2 is not an open, non-draft pull request"],
  ]);
});

test("explicit dispatch on closed pull request does not deploy or mutate labels", async () => {
  const args = makeArgs({
    currentPr: { ...basePr, state: "closed" },
    inputs: { pr_number: "2", sha: "head-sha" },
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "head-sha"],
    ["output", "should_deploy", "false"],
    ["info", "PR #2 is not an open, non-draft pull request"],
  ]);
});

test("manual dispatch deploys the associated PR and clears other staging labels", async () => {
  const args = makeArgs({
    inputs: { sha: "manual-sha" },
    prsForSha: [
      {
        head: { repo: { full_name: "owner/repo" }, sha: "manual-sha" },
        number: 2,
        state: "open",
      },
    ],
    stagingPrs: [
      { number: 1, pull_request: {}, state: "open" },
      { number: 2, pull_request: {}, state: "open" },
    ],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["remove", 1],
    ["info", "Removed staging from PR #1"],
    ["output", "should_deploy", "true"],
    ["info", "Deploying PR #2 at manual-sha"],
  ]);
});

test("manual dispatch deploys an unlabeled PR and rips staging from the labeled one", async () => {
  const args = makeArgs({
    inputs: { sha: "manual-sha" },
    prsForSha: [
      {
        head: { repo: { full_name: "owner/repo" }, sha: "manual-sha" },
        labels: [],
        number: 2,
        state: "open",
      },
    ],
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["remove", 1],
    ["info", "Removed staging from PR #1"],
    ["output", "should_deploy", "true"],
    ["info", "Deploying PR #2 at manual-sha"],
  ]);
});

test("manual dispatch of a commit without a PR clears every staging label", async () => {
  const args = makeArgs({
    inputs: { sha: "manual-sha" },
    prsForSha: [],
    stagingPrs: [
      { number: 1, pull_request: {}, state: "open" },
      { number: 2, pull_request: {}, state: "open" },
    ],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["remove", 1],
    ["remove", 2],
    ["info", "Removed staging from PR #1"],
    ["info", "Removed staging from PR #2"],
    ["output", "should_deploy", "true"],
    ["info", "Deploying manual-sha"],
  ]);
});

test("manual dispatch with several associated PRs refuses without mutating labels", async () => {
  const args = makeArgs({
    inputs: { sha: "manual-sha" },
    prsForSha: [
      {
        head: { repo: { full_name: "owner/repo" }, sha: "manual-sha" },
        number: 1,
        state: "open",
      },
      {
        head: { repo: { full_name: "owner/repo" }, sha: "manual-sha" },
        number: 2,
        state: "open",
      },
    ],
    stagingPrs: [{ number: 3, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["output", "should_deploy", "false"],
    [
      "info",
      "Multiple open PRs for manual-sha; pass pr_number to disambiguate",
    ],
  ]);
});

test("manual dispatch ignores fork pull requests", async () => {
  const args = makeArgs({
    inputs: { sha: "manual-sha" },
    prsForSha: [
      {
        head: { repo: { full_name: "contributor/repo" }, sha: "manual-sha" },
        number: 1,
        state: "open",
      },
    ],
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["output", "should_deploy", "false"],
    ["info", "Skipping staging deploy for fork PR #1"],
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

test("dispatch with non-positive PR number is non-mutating", async () => {
  const args = makeArgs({
    inputs: { pr_number: "-1", sha: "manual-sha" },
    stagingPrs: [{ number: 2, pull_request: {}, state: "open" }],
  });

  await staging.resolveDeploy(args);

  assert.deepEqual(args.calls, [
    ["output", "sha", "manual-sha"],
    ["output", "should_deploy", "false"],
    ["info", "Invalid pull request number: -1"],
  ]);
});

test("ignores non-staging labels", async () => {
  const args = makeArgs({ labelName: "bug" });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [["info", "Ignoring non-staging label"]]);
});

test("does not dispatch staging deploys for fork pull requests", async () => {
  const forkPr = {
    head: { repo: { full_name: "contributor/repo" }, sha: "head-sha" },
    labels: [{ name: "staging" }],
    number: 3,
    state: "open",
  };
  const args = makeArgs({
    currentPr: forkPr,
    pr: forkPr,
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [
    ["info", "Skipping staging deploy for fork PR #3"],
  ]);
});

test("does not dispatch or mutate labels for closed pull requests", async () => {
  const args = makeArgs({
    currentPr: { ...basePr, state: "closed" },
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [["info", "PR #2 is not open"]]);
});

test("does not dispatch or mutate labels for draft pull requests", async () => {
  const args = makeArgs({
    currentPr: { ...basePr, draft: true },
    stagingPrs: [{ number: 1, pull_request: {}, state: "open" }],
  });

  await staging.handlePullRequest(args);

  assert.deepEqual(args.calls, [["info", "PR #2 is a draft"]]);
});

test("creates staging deployment for the resolved SHA", async () => {
  const args = makeArgs();

  await staging.createStagingDeployment({
    ...args,
    sha: "head-sha",
    environmentUrl: "https://test.zagrajmy.net",
  });

  assert.deepEqual(args.calls, [
    [
      "create-deployment",
      {
        owner: "owner",
        repo: "repo",
        ref: "head-sha",
        environment: "staging",
        auto_merge: false,
        required_contexts: [],
        transient_environment: false,
        production_environment: false,
      },
    ],
    ["output", "id", "42"],
    [
      "deployment-status",
      {
        owner: "owner",
        repo: "repo",
        deployment_id: 42,
        state: "in_progress",
        environment_url: "https://test.zagrajmy.net",
        log_url: "https://github.com/owner/repo/actions/runs/run-id",
      },
    ],
  ]);
});

test("marks successful staging deployments successful", async () => {
  const args = makeArgs();

  await staging.finishStagingDeployment({
    ...args,
    deploymentId: 42,
    environmentUrl: "https://test.zagrajmy.net",
    jobStatus: "success",
  });

  assert.deepEqual(args.calls, [
    [
      "deployment-status",
      {
        owner: "owner",
        repo: "repo",
        deployment_id: 42,
        state: "success",
        environment_url: "https://test.zagrajmy.net",
        log_url: "https://github.com/owner/repo/actions/runs/run-id",
      },
    ],
    ["info", "Marked staging deployment 42 as success"],
  ]);
});

test("marks failed staging deployments failed", async () => {
  const args = makeArgs();

  await staging.finishStagingDeployment({
    ...args,
    deploymentId: 42,
    environmentUrl: "https://test.zagrajmy.net",
    jobStatus: "failure",
  });

  assert.deepEqual(args.calls, [
    [
      "deployment-status",
      {
        owner: "owner",
        repo: "repo",
        deployment_id: 42,
        state: "failure",
        environment_url: "https://test.zagrajmy.net",
        log_url: "https://github.com/owner/repo/actions/runs/run-id",
      },
    ],
    ["info", "Marked staging deployment 42 as failure"],
  ]);
});

test("marks canceled staging deployments as error", async () => {
  const args = makeArgs();

  await staging.finishStagingDeployment({
    ...args,
    deploymentId: 42,
    environmentUrl: "https://test.zagrajmy.net",
    jobStatus: "cancelled",
  });

  assert.deepEqual(args.calls, [
    [
      "deployment-status",
      {
        owner: "owner",
        repo: "repo",
        deployment_id: 42,
        state: "error",
        environment_url: "https://test.zagrajmy.net",
        log_url: "https://github.com/owner/repo/actions/runs/run-id",
      },
    ],
    ["info", "Marked staging deployment 42 as error"],
  ]);
});
