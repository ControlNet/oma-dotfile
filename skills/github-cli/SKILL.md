---
name: github-cli
description: Read-only GitHub inspection via gh CLI (repos, issues, PRs, releases, actions, search).
---

# GitHub CLI (Read-only)

## When to use
Use this skill when you need to **inspect** GitHub data (list/view/search/fetch) without making changes:
- Browse repos, issues, pull requests, releases/tags, commits, actions/workflows, gists
- Summarize status (checks, CI failures) with links, not full logs
- Run GitHub REST/GraphQL **read-only** queries

Do **not** use when the user wants to create/edit/merge/close/delete anything.

## Safety Rules
- Only run read-only commands (`list`, `view`, `status`, `search`, `api -X GET`).
- Never run write actions (`create`, `edit`, `close`, `merge`, `delete`, `run`, `enable`, `disable`, `secret/variable set`, `repo fork/create/delete`).
- For `gh api`, force `-X GET`. For GraphQL, use `query` only and never `mutation`.
- If the user requests a write action, ask for explicit confirmation and restate the impact before proceeding.

## Authentication
- Require `GITHUB_PERSONAL_ACCESS_TOKEN` in the environment. If missing, ask the user to set it.
- Check status with:
  - `gh auth status -h github.com`
- If not authenticated, log in without printing the token:
  - `echo "$GITHUB_PERSONAL_ACCESS_TOKEN" | gh auth login -h github.com --with-token`
- Do not print the token or run commands with shell tracing enabled.

## Usage Patterns
- Prefer fully qualified repos: `--repo OWNER/REPO`.
- Use `--json` + `--jq` for stable parsing.
- Use `--limit` for list commands and paginate with `gh api --paginate` when needed.
- Use `gh help` or `gh <cmd> -h` to confirm a command is read-only before running it.

## References
- Use `references/gh-readonly.md` for a categorized command map and examples.
