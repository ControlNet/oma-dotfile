# OMO memory reflection parked: "bwrap cannot create a user namespace"

## Symptom (omo 5.1.0, senpi 2026.9.28-7, Linux)

```
Automatic memory reflection paused after 3 failures · bwrap: Can't find source path
~/.omo/memory/agents/<id>/runtime/reflection-sessions: No such file or directory ·
the sandbox helper (bwrap) cannot create a user namespace on this host; set memory.reflection.sandbox to "off" ...
```

## Root cause

- The userns hint is a misclassification: omo maps any stderr matching `/bwrap:/` to the
  "cannot create a user namespace" recommendation.
- Real failure: the reflection sandbox adds `runtime/reflection-sessions` as a writable
  `--bind` source, but the spawn path never runs `ensureIdentityRuntimeDirs` (`mkdir -p`),
  so bwrap exits 1 when the directory is absent. Run artifacts actually go to
  `runtime/reflection/runs/<runId>/`.
- Upstream: https://github.com/code-yeongyu/oh-my-openagent/issues/7012 (open, confirmed by
  maintainer; still reproduces on stable 5.0.0 and later).
- Park state lives in `runtime/reflection/park.json` (`retryable: false`, 6h probe delay).

## Verification that userns is fine

```bash
cat /proc/sys/kernel/unprivileged_userns_clone   # 1
bwrap --ro-bind / / true; echo $?                # 0
```

## Workaround (keep the sandbox on)

```bash
for d in ~/.omo/memory/agents/*/runtime; do mkdir -p -m 700 "$d/reflection-sessions"; done
```

Then run `/reflect` in omo to retry immediately. Do not set `memory.reflection.sandbox` to
`"off"` for this; it only hides the missing-directory bug. New agent identities need the
same `mkdir` until upstream fixes #7012.
