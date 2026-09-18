# Git Author Repair

On 2026-09-05, three commits with author and committer `audit <audit@example.invalid>` were repaired using the configured identity `ControlNet <smczx@hotmail.com>`.

| Original commit | Rewritten commit |
| --- | --- |
| f86ae51 | 10c169e |
| 423df4a | 331c843 |
| b81bd3a | 4016ae4 |

The five descendant commits were rewritten only to update parent references. All eight commits preserve their original trees, messages, timestamps, and other headers. Other contributors retain their original attribution.

The original master tip was `11bb1f4d1a4206c7f26b61d15b549db5de78557e`; the repaired tip is `528fddee572b6c8e48744059840450052a05146b`. A verified local bundle and complete commit mapping are stored in `.git/author-repair-backups/20260905T074159Z/`. The backup is local and is not tracked by Git.

Verification commands:

```bash
git diff --exit-code 11bb1f4d1a4206c7f26b61d15b549db5de78557e 528fddee572b6c8e48744059840450052a05146b
git log master --format='%h %an <%ae> | %cn <%ce>'
git bundle verify .git/author-repair-backups/20260905T074159Z/before.bundle
```

Expected: the diff exits successfully without output; master has no `.invalid` author or committer addresses; bundle verification succeeds. Remote synchronization requires an explicit lease against the original remote tip to protect concurrent remote changes.

Remote synchronization completed on 2026-09-05 after explicit user authorization. `origin/master` was updated from `11bb1f4` to `528fdde` using `--force-with-lease` pinned to the full original remote commit ID.
