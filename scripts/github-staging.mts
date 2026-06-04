interface Label {
  name: string;
}

export interface PullRequestLike {
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

export interface Core {
  info(message: string): void;
  setOutput(name: string, value: string): void;
}

type PaginatedEndpoint = (
  params: Record<string, unknown>,
) => Promise<PullRequestLike[]>;

export interface Github {
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
  sha: string;
}

interface ResolveManualDeployArgs extends ActionArgs {
  sha: string;
}

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

const setShouldDeploy = (core: Core, deploy: boolean, message: string) => {
  core.setOutput("should_deploy", deploy ? "true" : "false");
  core.info(message);
};

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

const exclusiveStagingFor = async (args: ActionArgs, exceptNumber: number) => {
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
      message: `Skipping ${STAGING_LABEL} deploy for fork PR #${pr.number}`,
    };
  }

  await exclusiveStagingFor(args, pr.number);
  return { ok: true };
};

const dispatchDeploy = async ({
  github,
  context,
  pr,
  core,
}: DispatchDeployArgs) => {
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

  const claim = await claimStagingTarget({ github, context, core }, pr);
  if (!claim.ok) {
    core.info(claim.message);
    return;
  }

  await dispatchDeploy({ github, context, pr, core });
};

const listPullRequestsForSha = async ({
  github,
  context,
  sha,
}: ListPullRequestsForShaArgs) =>
  github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit, {
    ...repoParams(context),
    commit_sha: sha,
    per_page: 100,
  });

const fetchPullRequest = async ({
  github,
  context,
  number,
}: FetchPullRequestArgs) => {
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
}: ResolveExplicitDeployArgs) => {
  const pr = await fetchPullRequest({ github, context, number: prNumber });

  if (pr.state !== "open" || !hasStagingLabel(pr) || pr.head?.sha !== sha) {
    setShouldDeploy(
      core,
      false,
      `PR #${prNumber} is no longer the current ${STAGING_LABEL} target for ${sha}`,
    );
    return;
  }

  const claim = await claimStagingTarget({ github, context, core }, pr);
  if (!claim.ok) {
    setShouldDeploy(core, false, claim.message);
    return;
  }

  setShouldDeploy(core, true, `Deploying PR #${pr.number} at ${sha}`);
};

const resolveManualDeploy = async ({
  github,
  context,
  core,
  sha,
}: ResolveManualDeployArgs) => {
  const [stagingPrs, prsForSha] = await Promise.all([
    listStagingPrIssues({ github, context, core }),
    listPullRequestsForSha({ github, context, sha }),
  ]);
  const prNumbersForSha = new Set(
    prsForSha
      .filter((pr) => isSameRepositoryPullRequest(context, pr))
      .map((pr) => pr.number),
  );
  const matchingStagingPrs = stagingPrs.filter(
    (pr) => pr.state === "open" && prNumbersForSha.has(pr.number),
  );

  if (matchingStagingPrs.length !== 1) {
    setShouldDeploy(core, false, `No unique open PR with ${STAGING_LABEL} for ${sha}`);
    return;
  }

  await exclusiveStagingFor({ github, context, core }, matchingStagingPrs[0].number);
  setShouldDeploy(core, true, `Deploying PR #${matchingStagingPrs[0].number} at ${sha}`);
};

export const resolveDeploy = async ({ github, context, core }: ActionArgs) => {
  const inputSha = context.payload.inputs?.sha?.trim();
  const sha = inputSha || context.sha;
  const prNumberInput = context.payload.inputs?.pr_number?.trim();
  const prNumber = prNumberInput ? Number.parseInt(prNumberInput, 10) : undefined;

  core.setOutput("sha", sha);

  if (prNumberInput && (!prNumber || String(prNumber) !== prNumberInput)) {
    setShouldDeploy(core, false, `Invalid pull request number: ${prNumberInput}`);
    return;
  }

  if (prNumber !== undefined) {
    await resolveExplicitDeploy({ github, context, core, prNumber, sha });
    return;
  }

  await resolveManualDeploy({ github, context, core, sha });
};
