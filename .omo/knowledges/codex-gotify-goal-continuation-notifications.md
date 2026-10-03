# Codex Gotify: notifications from goal-continuation turns

## Symptom

Gotify receives Codex notifications for intermediate status such as
"队列未退出，继续等待结束通知" (queue still running, keep waiting), even
though the agent has not finished the user's task.

## Cause

Codex thread goals (`/goal`) make Codex start continuation turns on its own.
Each continuation turn starts with an injected user-role message:

```text
<codex_internal_context source="goal">
Continue working toward the active thread goal.
...
<objective>...</objective>
```

Every continuation turn ends with a normal `agent-turn-complete` notify event,
so a "watch this job until it ends" goal sends one notification per polling
turn. Evidence: local rollout `rollout-2026-09-26T18-40-12-01a0dcdf-...` had
about 25 goal-triggered turns, each followed by a notification.

## Codex goal state (codex-cli 0.160.0)

- Stored in `~/.codex/goals_1.sqlite`, table `thread_goals`, one row per
  `thread_id` (primary key).
- `status` is one of `active`, `paused`, `blocked`, `usage_limited`,
  `budget_limited`, `complete`.
- The model ends a goal with `update_goal({status: "complete"})` during the
  final turn, so the row is already `complete` when that turn's notify fires.
  `blocked` is only set after the same blocker repeats for 3 goal turns;
  `paused` requires an explicit user request; a budget overrun becomes
  `budget_limited` and triggers one wrap-up turn.
- Table `thread_goal_continuation_deferrals` lists threads whose automatic
  continuation is deferred.
- Rollouts also record `thread_goal_updated` events.

## Fix in codex-gotify-notify.py

Skip an `agent-turn-complete` notification only when the thread's goal is
`active` and has no continuation deferral, because Codex will then start the
next turn by itself. Every other case still notifies: no goal, any non-active
status, deferred continuation, non-turn events (permission requests), and any
failure to read the DB (fail-open). Log line: `run_skip reason=goal_continuation`.

- Opt out of the filter: `CODEX_NOTIFY_GOAL_CONTINUATION=true`.
- DB path override: `CODEX_NOTIFY_GOALS_DB`; default is the newest
  `~/.codex/goals_<N>.sqlite`.

Known residual risk: Codex logs rare cases where it skips a continuation even
though the goal stays `active` ("skipping goal continuation because automatic
idle work was rejected" / "turn input submission failed"). Such a turn would
produce no notification.
