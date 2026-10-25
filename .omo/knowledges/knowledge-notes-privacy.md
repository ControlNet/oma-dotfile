# Knowledge notes must not carry personal data

This repo is public, so `.omo/knowledges/*.md` is public too. Keep these out of notes:

- home paths with a user name (write `~/...`), absolute paths of other machines
- host names, names of the user's other projects, e-mail addresses
- account and auth details of the local tools (which login, which plan)
- local machine state: installed versions, install times, chosen languages, counts of
  local configs or sessions. Describe the behavior instead ("an older nvm node can hold
  an old codex").
- secrets of any kind; tests and notes use `test-only-fake-...` values

Before committing a note, scan it:

```bash
grep -nEi '/home/[a-z]|/Users/[a-z]|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}|this machine|on this host' .omo/knowledges/*.md
```

Hits on `example.com`/`example.invalid` and quoted upstream error text are fine.

## History rewrite (2026-10-23)

Earlier notes had leaked a user name in home paths, host names, another project's
name, an e-mail address and local machine state. They were removed from all history:

- Inventory: `git rev-list --all | xargs -I{} git grep -lE '<patterns>' {}` over every
  commit, plus `git log --all --format=%B` for messages. Only `.omo/knowledges/` was hit.
- Rewrite in a scratch clone (`git clone --no-local`), never in the working repo:
  filter-repo resets the work tree and would drop uncommitted files.
  `git-filter-repo` v2.38.0 (single stdlib script, works with git 2.34) was run as
  `python3 -I git-filter-repo --replace-text rules.txt`. Each rule maps an old line to
  the already-sanitized line at HEAD, so the final tree equals the sanitized tree and
  no extra cleanup commit remains. `regex:` rules handle multi-line text (`\n` in
  both sides). The rules file lists the leaked strings, so it is never committed.
- Checks: no pattern left in any commit or message; authors, dates and subjects
  identical; short hashes in commit messages are rewritten by filter-repo.
- Pushed with `--force-with-lease=master:<old full sha>`. A `git bundle --all` of the
  old history was kept locally first.
- filter-repo does not touch hashes inside file contents. Notes that cite commits were
  updated from `.git/filter-repo/commit-map`.
- filter-repo drops commit signatures. Four commits made on the GitHub web UI (the
  initial commit, the AGPL license, PR #2 and its merge) carried GitHub's signature, so
  even the root commit got a new id and **every** commit changed, not only those after
  the first leak. Old and new history share no ancestor; GitHub's "Verified" badges on
  those four are gone, and the forks and merged PR refs now point at unrelated history.
  To keep the untouched prefix, run filter-repo with `--refs <first-leaking>^..master`
  instead of all of history.
- The local repo then follows with `git fetch origin && git reset --mixed origin/master`,
  which keeps uncommitted files.
- GitHub may still serve old commits by direct id until its own GC. Forks and PR refs
  that predate the leaks contain none of the leaked text.
