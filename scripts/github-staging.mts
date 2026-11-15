interface Label {
  name: string;
}

export interface PullRequestLike {
  draft?: boolean;
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
}

export interface Context {
  payload: {
    action?: string;
    inputs?: {
      pr_number?: string;
      sha?: string;
      skip_if_stale?: boolean | string;
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
}

export interface Summary {
  addHeading(text: string, level?: number): Summary;
  addRaw(text: string, addEOL?: boolean): Summary;
  write(): Promise<unknown>;
}

export interface Core {
  info(message: string): void;
  setFailed(message: string): void;
  setOutput(name: string, value: string): void;
  summary: Summary;
}

type PaginatedEndpoint = (params: Record<string, unknown>) => Promise<PullRequestLike[]>;

export interface Github {
  paginate(fn: PaginatedEndpoint, params: Record<string, unknown>): Promise<PullRequestLike[]>;
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
      createDeployment(params: Record<string, unknown>): Promise<{ data: { id: number } }>;
      createDeploymentStatus(params: Record<string, unknown>): Promise<unknown>;
      listPullRequestsAssociatedWithCommit: PaginatedEndpoint;
    };
  };
}

export interface ActionArgs {
  context: Context;
  core: Core;
  github: Github;
}

interface RemoveArgs extends ActionArgs {
  issueNumber: number;
}

interface RemoveManyArgs extends ActionArgs {
  exceptNumber?: number;
  prs: PullRequestLike[];
}

interface DispatchDeployArgs extends ActionArgs {
  pr: PullRequestLike;
}

interface RepoGithubArgs {
  github: Github;
  context: Context;
}

interface ListPullRequestsForShaArgs extends RepoGithubArgs {
  sha: string;
}

interface FetchPullRequestArgs extends RepoGithubArgs {
  number: number;
}

interface ResolveExplicitDeployArgs extends ActionArgs {
  prNumber: number;
  requestedSha?: string;
  skipIfStale: boolean;
}

interface ResolveManualDeployArgs extends ActionArgs {
  sha: string;
}

interface CreateDeploymentArgs extends ActionArgs {
  environmentUrl: string;
  sha: string;
}

interface FinishDeploymentArgs extends ActionArgs {
  deploymentId: number;
  environmentUrl: string;
  jobStatus: string;
}

type DeploymentState = "error" | "failure" | "success";

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

const deploy = (core: Core, sha: string, message: string) => {
  core.setOutput("sha", sha);
  core.setOutput("should_deploy", "true");
  core.info(message);
};

const halt = async (core: Core, heading: string, message: string) => {
  core.setOutput("should_deploy", "false");
  await core.summary.addHeading(heading, 2).addRaw(message, true).write();
};

const skip = async (core: Core, message: string) => {
  core.info(message);
  await halt(core, "Staging deploy skipped", message);
};

const refuse = async (core: Core, message: string) => {
  core.setFailed(message);
  await halt(core, "Staging deploy refused", message);
};

const workflowLogUrl = (context: Context) =>
  `${process.env.GITHUB_SERVER_URL}/${repoFullName(context)}/actions/runs/${process.env.GITHUB_RUN_ID}`;

const deploymentStateFor = (jobStatus: string): DeploymentState => {
  if (jobStatus === "success") return "success";
  if (jobStatus === "failure") return "failure";
  return "error";
};

const createDeploymentStatus = async ({
  github,
  context,
  deploymentId,
  environmentUrl,
  state,
}: ActionArgs & {
  deploymentId: number;
  environmentUrl: string;
  state: "in_progress" | DeploymentState;
}) => {
  await github.rest.repos.createDeploymentStatus({
    ...repoParams(context),
    deployment_id: deploymentId,
    state,
    environment_url: environmentUrl,
    log_url: workflowLogUrl(context),
  });
};

const listStagingPrIssues = async ({ github, context }: ActionArgs): Promise<PullRequestLike[]> => {
  const issues = await github.paginate(github.rest.issues.listForRepo, {
    ...repoParams(context),
    state: "open",
    labels: STAGING_LABEL,
    per_page: 100,
  });

  return issues.filter((issue) => issue.pull_request);
};

const removeStagingLabel = async ({ github, context, issueNumber, core }: RemoveArgs) => {
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

const removeStagingFrom = async ({ github, context, prs, exceptNumber, core }: RemoveManyArgs) => {
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

const exclusiveStagingFor = async (args: ActionArgs, exceptNumber?: number) => {
  const stagingPrs = await listStagingPrIssues(args);
  await removeStagingFrom({
    ...args,
    prs: stagingPrs,
    exceptNumber,
  });
};

const claimStagingTarget = async (
  args: ActionArgs,
  pr: PullRequestLike,
): Promise<{ ok: true } | { ok: false; message: string }> => {
  if (!isSameRepositoryPullRequest(args.context, pr)) {
    return {
      ok: false,
      message: `Refusing ${STAGING_LABEL} deploy for fork PR #${pr.number}`,
    };
  }

  await exclusiveStagingFor(args, pr.number);
  return { ok: true };
};

const dispatchDeploy = async ({ github, context, pr, core }: DispatchDeployArgs) => {
  if (!pr.head) throw new Error("Expected pull_request head");

  await github.rest.actions.createWorkflowDispatch({
    ...repoParams(context),
    workflow_id: DEPLOY_WORKFLOW_ID,
    ref: context.payload.repository.default_branch,
    inputs: {
      pr_number: String(pr.number),
      sha: pr.head.sha,
      skip_if_stale: "true",
    },
  });
  core.info(`Dispatched ${DEPLOY_WORKFLOW_ID} for PR #${pr.number} at ${pr.head.sha}`);
};

export const handlePullRequest = async ({ github, context, core }: ActionArgs) => {
  const eventPr = context.payload.pull_request;
  if (!eventPr) throw new Error("Expected pull_request payload");

  if (context.payload.action === "labeled" && context.payload.label?.name !== STAGING_LABEL) {
    core.info("Ignoring non-staging label");
    return;
  }

  const pr = await fetchPullRequest({
    github,
    context,
    number: eventPr.number,
  });

  if (pr.draft) {
    core.info(`PR #${pr.number} is a draft`);
    return;
  }

  if (pr.state !== "open") {
    core.info(`PR #${pr.number} is not open`);
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

  await dispatchDeploy({ github, context, pr, core });
};

export const createStagingDeployment = async ({
  github,
  context,
  core,
  sha,
  environmentUrl,
}: CreateDeploymentArgs) => {
  const response = await github.rest.repos.createDeployment({
    ...repoParams(context),
    ref: sha,
    environment: STAGING_LABEL,
    auto_merge: false,
    required_contexts: [],
    transient_environment: false,
    production_environment: false,
  });
  const deploymentId = response.data.id;

  core.setOutput("id", String(deploymentId));
  await createDeploymentStatus({
    github,
    context,
    core,
    deploymentId,
    environmentUrl,
    state: "in_progress",
  });
};

export const finishStagingDeployment = async ({
  github,
  context,
  core,
  deploymentId,
  environmentUrl,
  jobStatus,
}: FinishDeploymentArgs) => {
  const state = deploymentStateFor(jobStatus);
  await createDeploymentStatus({
    github,
    context,
    core,
    deploymentId,
    environmentUrl,
    state,
  });
  core.info(`Marked ${STAGING_LABEL} deployment ${deploymentId} as ${state}`);
};

const listPullRequestsForSha = async ({ github, context, sha }: ListPullRequestsForShaArgs) =>
  github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit, {
    ...repoParams(context),
    commit_sha: sha,
    per_page: 100,
  });

const fetchPullRequest = async ({ github, context, number }: FetchPullRequestArgs) => {
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
  requestedSha,
  skipIfStale,
}: ResolveExplicitDeployArgs) => {
  const pr = await fetchPullRequest({ github, context, number: prNumber });
  if (!pr.head) throw new Error(`Expected PR #${prNumber} to have a head`);

  // An explicit dispatch is itself the authorization to deploy, so we do NOT
  // require the staging label here (that gate is only for the auto-flow). We
  // still refuse closed/draft PRs and commits other than the PR head, and
  // claimStagingTarget strips the label from any other PR so only the explicit
  // target is on staging. A label-triggered dispatch that a newer push or a
  // merge overtook is skipped, not failed: the newer run deploys instead.
  const outdated = skipIfStale ? skip : refuse;

  if (pr.state !== "open" || pr.draft) {
    await outdated(core, `PR #${prNumber} is not an open, non-draft pull request`);
    return;
  }

  const headSha = pr.head.sha;
  if (requestedSha && requestedSha !== headSha) {
    await outdated(
      core,
      skipIfStale
        ? `PR #${prNumber} moved on to ${headSha}; ${requestedSha} is superseded`
        : `PR #${prNumber} head ${headSha} does not match requested ${requestedSha}; leave sha empty to deploy the current head`,
    );
    return;
  }

  const claim = await claimStagingTarget({ github, context, core }, pr);
  if (!claim.ok) {
    await refuse(core, claim.message);
    return;
  }

  deploy(core, headSha, `Deploying PR #${pr.number} at ${headSha}`);
};

const resolveManualDeploy = async ({ github, context, core, sha }: ResolveManualDeployArgs) => {
  const openPrsForSha = (await listPullRequestsForSha({ github, context, sha })).filter(
    (pr) => pr.state === "open",
  );

  // A manual dispatch is itself the authorization to deploy `sha`, so we do NOT
  // require the staging label, and (unlike the explicit/label paths) we accept
  // drafts — a human asking for a draft preview is intentional. Whatever we
  // deploy takes over staging, so we strip the label off every other PR
  // (claimStagingTarget semantics).
  if (openPrsForSha.length > 1) {
    await refuse(core, `Multiple open PRs for ${sha}; pass pr_number to disambiguate`);
    return;
  }

  if (openPrsForSha.length === 0) {
    await exclusiveStagingFor({ github, context, core });
    deploy(core, sha, `Deploying ${sha}`);
    return;
  }

  // Re-fetch the single PR for an authoritative head repo: the associated-
  // commits payload can carry a null/sparse head (e.g. a deleted fork) that
  // would misclassify a real PR. Fork PRs stay off staging.
  const pr = await fetchPullRequest({
    github,
    context,
    number: openPrsForSha[0].number,
  });
  if (!isSameRepositoryPullRequest(context, pr)) {
    await refuse(core, `Refusing ${STAGING_LABEL} deploy for fork PR #${pr.number}`);
    return;
  }

  await exclusiveStagingFor({ github, context, core }, pr.number);
  deploy(core, sha, `Deploying PR #${pr.number} at ${sha}`);
};

export const resolveDeploy = async ({ github, context, core }: ActionArgs) => {
  const inputs = context.payload.inputs ?? {};
  const requestedSha = inputs.sha?.trim() || undefined;
  const skipIfStale = String(inputs.skip_if_stale) === "true";
  const prNumberInput = inputs.pr_number?.trim();

  if (!prNumberInput) {
    await resolveManualDeploy({ github, context, core, sha: requestedSha ?? context.sha });
    return;
  }

  const prNumber = Number.parseInt(prNumberInput, 10);
  if (!(Number.isSafeInteger(prNumber) && prNumber > 0 && String(prNumber) === prNumberInput)) {
    await refuse(core, `Invalid pull request number: ${prNumberInput}`);
    return;
  }

  await resolveExplicitDeploy({ github, context, core, prNumber, requestedSha, skipIfStale });
};
