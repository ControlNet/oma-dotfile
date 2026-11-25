---
name: auto-review-loop
description: Review a whole repository with an independent reviewer, verify each finding, fix the confirmed ones in parallel worktrees, push, wait for CI, and repeat until a round finds nothing new. Use only when the user invokes it by name (/auto-review-loop or $auto-review-loop); do not start it on your own.
---

# Auto review loop

Stop when a full round ends with no new confirmed findings and CI is green on the pushed commit.
Findings already rejected, deferred or left to the user do not count as new. Also stop at the
user's turn or time limit, or when only a decision by the user can unblock the work; say which.

End every round with one status line, so progress is visible in the conversation (a `/goal`
evaluator reads only the conversation):

`Round N: X confirmed (Y fixed, Z deferred), W rejected, CI <green|red|pending> at <sha>`

## Each round

1. **Baseline.** Pull, note the branch and HEAD, and leave uncommitted changes that are not yours
   alone. Read AGENTS.md, README, design notes and `.omo/knowledges/` first, so deliberate design
   decisions are known before the review.
2. **Review the whole repository**, not only the last round's changes.
   - Use the reviewer the user named; by default another agent CLI. Inside Herdr, start it in a
     sibling pane with the herdr skill. Otherwise run it read-only and headless, for example
     `codex exec -m <model> -c model_reasoning_effort=high -s read-only -o <report.md> "<prompt>" < /dev/null`.
   - Use high reasoning effort, not max.
   - If the reviewer runs out of quota or fails, keep its partial report and finish the review
     with subagents split by area.
   - Ask for findings ranked by severity, each with file:line, trigger, consequence, evidence and
     whether it was reproduced or inferred, plus a list of the areas covered. Pass the findings
     already fixed, rejected or deferred so they are not reported again.
3. **Verify every finding** before acting: read the code path, reproduce it where practical, and
   look for counter-evidence. Mark each confirmed, rejected (with the reason) or needs-user-decision.
   Behavior that matches a documented or deliberate design is not a bug; ask before changing it.
4. **Fix the confirmed findings.** Group them by shared cause. Give each independent group to a
   subagent or another agent in its own worktree and branch, with a short brief: findings,
   expected behavior, files it owns, how to validate. Workers commit but do not push or merge.
   Fix small or tightly coupled findings directly. For behavior bugs, prefer a test that fails
   before the fix and passes after.
5. **Integrate.** Read each worker's diff, not just its summary. Merge into the current branch,
   run the project's lint and tests on the merged result, commit and push.
6. **Wait for CI** on the pushed SHA with a script. Fix failures this round caused and push again.
7. **Clean up** this round's worktrees and their local and remote branches.
8. Print the status line. Start the next round unless the stop condition holds.

## Final report

Outcome first: rounds run, final SHA and CI run link, then one line per finding fixed, rejected or
deferred, and anything waiting on the user's decision. Do not claim the project is bug-free.
