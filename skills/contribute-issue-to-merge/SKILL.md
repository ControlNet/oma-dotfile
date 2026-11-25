---
name: contribute-issue-to-merge
description: Take a GitHub issue, or a pull request already open, through to a merged pull request - pick or confirm the issue, fix it in its own worktree, open a minimal PR, then follow CI and maintainer feedback until it is merged, closed, or waiting only on the maintainers. For the user's own repositories and external projects. Use only when the user invokes it by name (/contribute-issue-to-merge or $contribute-issue-to-merge); do not start it on your own.
---

# Contribute issue to merge

Done means one of: the PR is merged (check `gh pr view <n> --json state,mergedAt,mergeCommit`), the
PR is closed, or the PR waits only on the maintainers, with CI green on the current head and every
review comment answered. In the last case stop and say so instead of looping. A green CI run, a
pushed branch or an approval alone is not done.

End every turn with one status line, so progress is visible in the conversation (a `/goal`
evaluator reads only the conversation):

`PR #N: <state>, CI <green|red|pending> at <sha>, <k> unresolved threads, next: <action | waiting on maintainers>`

## 1. Pick the work

- If the user named an issue or PR, use it. For an open PR, resume from its current head, CI and
  all of its comments.
- If asked to find issues, list candidates (open, unassigned, no linked PR, a scope that fits)
  with one line on why each fits, and let the user pick.
- Read the whole issue thread, CONTRIBUTING, the PR template, commit conventions and the CI setup.
  Check that nobody already has a PR for it.
- Settle what counts as fixed. If the issue leaves a product decision open, ask in the issue or
  ask the user before coding.
- Several independent issues: one worktree, branch, PR and subagent each.

## 2. Make the change

- Pull the default branch, then create a worktree and branch for the issue. Push to the upstream
  repository if you have write access (`gh repo view --json viewerPermission`), otherwise to a fork.
- Read the real code paths first. Reproduce a bug before fixing it; if the project has tests, add
  one that fails before the fix and passes after.
- Keep the diff minimal: only what the issue needs, in the project's own style. No unrelated
  refactors, formatting churn or extra files.
- Run the project's own lint, tests and build.

## 3. Open the PR

- Write issue comments, the PR title and body in the language the repository uses (check its recent
  issues and PRs). Follow its template, link the issue (`Fixes #N`), and say what changed, how it
  was tested and what is not covered.
- Before pushing or posting, check the diff, commit messages and text for secrets, personal data
  and private project names.
- Read back what you posted once; never create a duplicate issue, PR or comment.

## 4. Follow until done

- Watch CI and new comments with one background script, for example `gh run watch <id> --exit-status`
  for CI and a loop over `gh pr view <n> --json state,headRefOid,comments,reviews` every few minutes
  that exits when something changes.
- On every change, re-read all comments, reviews and inline threads, not only the newest; earlier
  requests may have been revised or withdrawn.
- On a CI failure, read the failing step's log and decide whether the change, a test or the
  infrastructure is at fault before acting.
- Handle each review request in the same PR, reply in each thread with what changed, re-run the
  local checks, push, and go back to watching.
- Never merge, approve or bypass branch protection for the maintainers. Merge only when the user
  asks and has the rights, with the repository's normal method, after CI passes on the final head.
- After merge or close, remove the worktree and the local branch, and delete the branch from the
  fork or remote.
