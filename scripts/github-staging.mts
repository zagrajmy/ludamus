type Label = {
  name: string;
};

export type PullRequestLike = {
  head?: {
    repo?: {
      full_name: string;
    };
    sha: string;
  };
  labels?: Label[];
  number: number;
  pull_request?: unknown;
  state?: string;
};

export type Context = {
  payload: {
    action?: string;
    inputs?: {
      pr_number?: string;
      sha?: string;
    };
    label?: Label;
    pull_request?: PullRequestLike;
    repository: {
      default_branch: string;
    };
  };
  repo: {
    owner: string;
    repo: string;
  };
  sha: string;
};

export type Core = {
  info(message: string): void;
  setOutput(name: string, value: string): void;
};

type PaginatedEndpoint = (
  params: Record<string, unknown>,
) => Promise<PullRequestLike[]>;

export type Github = {
  paginate(
    fn: PaginatedEndpoint,
    params: Record<string, unknown>,
  ): Promise<PullRequestLike[]>;
  rest: {
    actions: {
      createWorkflowDispatch(params: Record<string, unknown>): Promise<unknown>;
    };
    issues: {
      listForRepo: PaginatedEndpoint;
      removeLabel(params: Record<string, unknown>): Promise<unknown>;
    };
    pulls: {
      get(params: Record<string, unknown>): Promise<{ data: PullRequestLike }>;
    };
    repos: {
      listPullRequestsAssociatedWithCommit: PaginatedEndpoint;
    };
  };
};

export type ActionArgs = {
  context: Context;
  core: Core;
  github: Github;
};

type RemoveArgs = ActionArgs & {
  issueNumber: number;
};

type RemoveManyArgs = ActionArgs & {
  exceptNumber?: number;
  prs: PullRequestLike[];
};

const STAGING_LABEL = "staging";
const DEPLOY_WORKFLOW_ID = "deploy-staging.yml";

const repoParams = (context: Context) => ({
  owner: context.repo.owner,
  repo: context.repo.repo,
});

const repoFullName = (context: Context) => `${context.repo.owner}/${context.repo.repo}`;

const isSameRepositoryPullRequest = (context: Context, pr: PullRequestLike) =>
  pr.head?.repo?.full_name === repoFullName(context);

const hasStagingLabel = (pr: PullRequestLike) =>
  (pr.labels ?? []).some((label) => label.name === STAGING_LABEL);

const listStagingPrIssues = async ({
  github,
  context,
}: ActionArgs): Promise<PullRequestLike[]> => {
  const issues = await github.paginate(github.rest.issues.listForRepo, {
    ...repoParams(context),
    state: "all",
    labels: STAGING_LABEL,
    per_page: 100,
  });

  return issues.filter((issue) => issue.pull_request);
};

const removeStagingLabel = async ({
  github,
  context,
  issueNumber,
  core,
}: RemoveArgs) => {
  try {
    await github.rest.issues.removeLabel({
      ...repoParams(context),
      issue_number: issueNumber,
      name: STAGING_LABEL,
    });
    core.info(`Removed ${STAGING_LABEL} from PR #${issueNumber}`);
  } catch (error) {
    if ((error as { status?: number }).status !== 404) throw error;
  }
};

const removeStagingFrom = async ({
  github,
  context,
  prs,
  exceptNumber,
  core,
}: RemoveManyArgs) => {
  await Promise.all(
    prs
      .filter((pr) => pr.number !== exceptNumber)
      .map((pr) =>
        removeStagingLabel({
          github,
          context,
          issueNumber: pr.number,
          core,
        }),
      ),
  );
};

const dispatchDeploy = async ({
  github,
  context,
  pr,
  core,
}: ActionArgs & { pr: PullRequestLike }) => {
  if (!pr.head) throw new Error("Expected pull_request head");

  await github.rest.actions.createWorkflowDispatch({
    ...repoParams(context),
    workflow_id: DEPLOY_WORKFLOW_ID,
    ref: context.payload.repository.default_branch,
    inputs: {
      pr_number: String(pr.number),
      sha: pr.head.sha,
    },
  });
  core.info(`Dispatched ${DEPLOY_WORKFLOW_ID} for PR #${pr.number} at ${pr.head.sha}`);
};

export const handlePullRequest = async ({ github, context, core }: ActionArgs) => {
  const pr = context.payload.pull_request;
  if (!pr) throw new Error("Expected pull_request payload");

  if (
    context.payload.action === "labeled" &&
    context.payload.label?.name !== STAGING_LABEL
  ) {
    core.info("Ignoring non-staging label");
    return;
  }

  if (!hasStagingLabel(pr)) {
    core.info(`PR #${pr.number} does not have ${STAGING_LABEL}`);
    return;
  }

  if (!isSameRepositoryPullRequest(context, pr)) {
    core.info(`Skipping ${STAGING_LABEL} deploy for fork PR #${pr.number}`);
    return;
  }

  const stagingPrs = await listStagingPrIssues({ github, context, core });
  await removeStagingFrom({
    github,
    context,
    prs: stagingPrs,
    exceptNumber: pr.number,
    core,
  });

  await dispatchDeploy({ github, context, pr, core });
};

const listPullRequestsForSha = async ({
  github,
  context,
  sha,
}: ActionArgs & { sha: string }) =>
  github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit, {
    ...repoParams(context),
    commit_sha: sha,
    per_page: 100,
  });

const fetchPullRequest = async ({
  github,
  context,
  number,
}: ActionArgs & { number: number }) => {
  const response = await github.rest.pulls.get({
    ...repoParams(context),
    pull_number: number,
  });
  return response.data;
};

const resolveExplicitDeploy = async ({
  github,
  context,
  core,
  prNumber,
  sha,
}: ActionArgs & { prNumber: number; sha: string }) => {
  const pr = await fetchPullRequest({ github, context, core, number: prNumber });

  if (pr.state !== "open" || !hasStagingLabel(pr) || pr.head?.sha !== sha) {
    core.setOutput("should_deploy", "false");
    core.info(`PR #${prNumber} is no longer the current ${STAGING_LABEL} target for ${sha}`);
    return;
  }

  if (!isSameRepositoryPullRequest(context, pr)) {
    core.setOutput("should_deploy", "false");
    core.info(`Skipping ${STAGING_LABEL} deploy for fork PR #${pr.number}`);
    return;
  }

  const stagingPrs = await listStagingPrIssues({ github, context, core });
  await removeStagingFrom({
    github,
    context,
    prs: stagingPrs,
    exceptNumber: pr.number,
    core,
  });
  core.setOutput("should_deploy", "true");
  core.info(`Deploying PR #${pr.number} at ${sha}`);
};

const resolveManualDeploy = async ({
  github,
  context,
  core,
  sha,
}: ActionArgs & { sha: string }) => {
  const stagingPrs = await listStagingPrIssues({ github, context, core });
  const prsForSha = await listPullRequestsForSha({ github, context, sha, core });
  const prNumbersForSha = new Set(
    prsForSha
      .filter((pr) => isSameRepositoryPullRequest(context, pr))
      .map((pr) => pr.number),
  );
  const matchingStagingPrs = stagingPrs.filter(
    (pr) => pr.state === "open" && prNumbersForSha.has(pr.number),
  );

  if (matchingStagingPrs.length !== 1) {
    core.setOutput("should_deploy", "false");
    core.info(`No unique open PR with ${STAGING_LABEL} for ${sha}`);
    return;
  }

  await removeStagingFrom({
    github,
    context,
    prs: stagingPrs,
    exceptNumber: matchingStagingPrs[0].number,
    core,
  });
  core.setOutput("should_deploy", "true");
  core.info(`Deploying PR #${matchingStagingPrs[0].number} at ${sha}`);
};

export const resolveDeploy = async ({ github, context, core }: ActionArgs) => {
  const inputSha = context.payload.inputs?.sha?.trim();
  const sha = inputSha || context.sha;
  const prNumberInput = context.payload.inputs?.pr_number?.trim();
  const prNumber = prNumberInput ? Number.parseInt(prNumberInput, 10) : undefined;

  core.setOutput("sha", sha);

  if (prNumberInput && (!prNumber || String(prNumber) !== prNumberInput)) {
    core.setOutput("should_deploy", "false");
    core.info(`Invalid pull request number: ${prNumberInput}`);
    return;
  }

  if (prNumber !== undefined) {
    await resolveExplicitDeploy({ github, context, core, prNumber, sha });
    return;
  }

  await resolveManualDeploy({ github, context, core, sha });
};
