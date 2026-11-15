# Claude Code plugins synced from claude.ai

Checked with Claude Code on 2026-11-15.

- A plugin uploaded on claude.ai ("My Uploads", `marketplace_kind: account_uploads`) syncs into
  every Claude Code signed in to that account, under `~/.claude/plugins/synced/<bucket>/<name>/`.
  It is not in `installed_plugins.json`; `claude plugin list` shows it under
  "Synced from claude.ai" with the id `<name>@synced`, and its skills appear prefixed
  (`<name>:<skill>`).
- An upload is a snapshot: it does not follow the upstream repo. A copy installed with the
  skills CLI does, so when both exist the skills show twice and drift apart.
- `claude plugin disable <name>@synced` works and only writes `"<name>@synced": false` under
  `enabledPlugins` in `~/.claude/settings.json`; the upload on claude.ai is untouched. Running
  it again also succeeds. `claude plugin enable <name>@synced` undoes it.
- `claude plugin list --json` reports a synced plugin with `"enabled": false` both while it is
  loaded and after it is disabled, so read `enabledPlugins` in settings.json to know whether it
  is off. The human-readable `claude plugin list` shows `loaded` vs `disabled` correctly.
- pull.py disables only the ids in `CLAUDE_SYNCED_DUPLICATES` (`ccfa-skills@synced`), only
  when Claude Code lists them and the same source was just linked into `~/.claude/skills`.
  A synced plugin is not disabled just because its skill names match: an upload may be a newer
  or edited version that the user wants.
