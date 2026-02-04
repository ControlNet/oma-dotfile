# gh read-only command map

Use these as examples. All commands are read-only.

## Auth and context
- `gh auth status -h github.com`
- `gh help`
- `gh <cmd> -h`

## Repositories
- `gh repo list OWNER --limit 100 --json name,description,visibility,updatedAt`
- `gh repo view OWNER/REPO --json name,description,defaultBranchRef,visibility,homepageUrl,topics,updatedAt`
- `gh repo view OWNER/REPO --json issues,pullRequests --jq '{issues: .issues.totalCount, prs: .pullRequests.totalCount}'`

## Issues
- `gh issue list --repo OWNER/REPO --state all --limit 100 --json number,title,state,author,createdAt,updatedAt`
- `gh issue view 123 --repo OWNER/REPO --json number,title,body,labels,assignees,comments`
- `gh issue status --repo OWNER/REPO`

## Pull requests
- `gh pr list --repo OWNER/REPO --state all --limit 100 --json number,title,state,author,createdAt,updatedAt`
- `gh pr view 123 --repo OWNER/REPO --json number,title,body,commits,checks,reviewRequests`
- `gh pr checks 123 --repo OWNER/REPO`
- `gh pr status --repo OWNER/REPO`

## Releases and tags
- `gh release list --repo OWNER/REPO --limit 100`
- `gh release view v1.2.3 --repo OWNER/REPO`
- `gh api -X GET repos/OWNER/REPO/tags --jq '.[].name'`

## Commits and compare
- `gh api -X GET repos/OWNER/REPO/commits --jq '.[0].sha'`
- `gh api -X GET repos/OWNER/REPO/commits?per_page=20 --jq '.[].commit.message'`
- `gh api -X GET repos/OWNER/REPO/compare/BASE...HEAD`

## Actions and workflows
- `gh workflow list --repo OWNER/REPO`
- `gh workflow view WORKFLOW_ID --repo OWNER/REPO`
- `gh run list --repo OWNER/REPO --limit 50`
- `gh run view RUN_ID --repo OWNER/REPO`

## Search
- `gh search repos "topic:cli" --limit 20`
- `gh search issues "is:issue is:open label:bug" --repo OWNER/REPO --limit 50`
- `gh search prs "is:pr is:open" --repo OWNER/REPO --limit 50`
- `gh search commits "fix" --repo OWNER/REPO --limit 20`

## Gists (read-only)
- `gh gist list --limit 50`
- `gh gist view GIST_ID`

## Organizations and teams
- `gh org list --limit 100`
- `gh api -X GET orgs/ORG/teams --jq '.[].name'`

## Generic REST and GraphQL (read-only)
- `gh api -X GET repos/OWNER/REPO/pulls --jq '.[].number'`
- `gh api -X GET repos/OWNER/REPO/issues --jq '.[].number'`
- `gh api graphql -f query='query($owner:String!,$name:String!){repository(owner:$owner,name:$name){stargazerCount forkCount}}' -F owner=OWNER -F name=REPO`
