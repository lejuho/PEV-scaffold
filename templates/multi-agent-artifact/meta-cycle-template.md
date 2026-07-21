# Meta-Cycle Plan — PEV Self-Improvement Retrospective

> A meta-cycle runs PEV against *itself*. Every N cycles (recommended: 10) you
> pause feature work and spend one cycle improving the PEV machine — its
> `AGENTS.md`, plan template, hooks, or the metrics lab — using the numbers the
> lab has been collecting. This is a **human-triggered** procedure: nothing here
> auto-runs. Copy this template into `.review/cycle-<N>/plan.md` (or run it as a
> standalone retro) and fill in the bracketed values from `pev-metrics.json`.

Branch: `meta/cycle-<N>-retro`
Skills: none

## 0. Baseline snapshot (paste from logs/pev-metrics.json → totals)

- cycles measured: `[totals.cycles]`
- first-pass rate: `[totals.firstPassRate]`
- autonomy hours: `[totals.autonomyHours]`
- active agent hours: `[totals.activeAgentHours]` across
  `[totals.activeAgentCycles]` covered cycles
- cost: `$[totals.costUsd]`  · measured rework cost: `$[totals.reworkCostUsd]`
  · backfilled rework estimate: `$[totals.backfilledReworkCostUsd]`
- failure-tag distribution (last ~20 cycles): executor `[n]` · plan `[n]` ·
  reviewer-FP `[n]` · infra `[n]`
- recent trend (from the dashboard sparkline / history table): `[1–2 sentences]`
- selection records: `[totals.selection.recorded]` · average user value:
  `[totals.selection.averageUserValue]` · low-value streak:
  `[totals.selection.lowValueStreak]`
- prediction calibration: duration MAE `[totals.selection.durationPredictionMaeMin]m` ·
  cost MAE `$[totals.selection.costPredictionMaeUsd]` · first-pass Brier
  `[totals.selection.firstPassBrierScore]`
- unit economics: requirements `[totals.units.requirementCount]` at
  `$[totals.units.averageCostPerRequirementUsd]` and
  `[totals.units.averageCyclesPerRequirement]` cycles/FR · tasks
  `[totals.units.taskCount]` at `$[totals.units.averageCostPerTaskUsd]`
- execution: changed lines `[totals.execution.linesChanged]` · verify/implement
  time ratio `[totals.execution.verificationToImplementationTimeRatio]` · failed
  checks `[totals.execution.failedChecks]/[totals.execution.recordedChecks]`
- fragmentation: amplified FRs `[totals.units.amplifiedRequirements]` · fragmented
  FRs `[totals.units.fragmentedRequirements]` · repeated check overhead
  `[totals.units.repeatedCheckOverheadSec]s` · additional-cycle verification cost
  `$[totals.units.additionalCycleVerificationCostUsd]` · timed-check coverage
  `[totals.units.fragmentationCheckCoverage]`
- split discipline: single-task selections `[totals.selection.singleTaskSelections]` ·
  documented rationale coverage `[totals.selection.splitRationaleCoverage]`
- interventions: actionable `[totals.interventions.actionable]` · observations
  `[totals.interventions.observations]` · by type `[totals.interventions.byType]`

## 1. Read the signal

Answer from the data, not from vibes:

1. **Where is the money going?** Is `reworkCostUsd` a large share of `costUsd`?
   Rework is spend that a cleaner first pass would have avoided.
2. **What breaks first-pass?** Which `failureTag` dominates the non-first-pass
   cycles — the executor (implementation drift), the plan (bad scoping), the
   reviewer (false positives), or infra (network/flaky)?
3. **Reviewer accuracy.** A high `reviewer` (false-positive) tag rate means the
   verifier is blocking on non-issues — the fix is in the review criteria, not
   the executor.
4. **Infra noise.** If the error feed is dominated by infra clusters, that is an
   environment problem, not a PEV-logic problem — do not "fix" it in AGENTS.md.
5. **Selection quality.** If low-value work repeats, adjust candidate grouping or
   the rubric before changing agents. If prediction errors are high, improve the
   score anchors/evidence; do not rewrite historical selection records.
6. **Cycle amplification.** Inspect requirements with more than one cycle. Decide
   whether the split removed risk or merely created coordination and review cost.
7. **Verification efficiency.** Compare verify/implement time, failed stages and
   verification cost per changed line. A large ratio is only actionable when
   check coverage is present; missing check/turn records are not zeros.
8. **Fragmentation economics.** For an amplified FR, compare risk actually removed
   by the boundary against repeated-check overhead and additional-cycle verification
   cost. Merge compatible tasks when the latter is larger.

## 2. Propose concrete changes

For each problem worth acting on, write a specific diff proposal against one of:

- `templates/multi-agent-artifact/AGENTS.md` (executor/reviewer behavior)
- `templates/multi-agent-artifact/plan-template.md` (scoping, contract)
- a hook under `templates/multi-agent-artifact/*.sh`
- the metrics lab itself (`dashboard/metrics.py`, dashboard UI)

Each proposal MUST state the metric it targets and the target value:

> Example: "Add a 'no new deps' assertion to the executor contract in AGENTS.md.
> Targets: executor-tagged failures 6→≤2 per 10 cycles. Re-measure after 10
> cycles."

Do not batch more than 2–3 changes per meta-cycle — you must be able to
attribute the next window's movement to what you changed.

## 3. Define the comparison

- Metrics to watch: `[e.g. firstPassRate, reworkCostUsd]`
- Current → target: `[e.g. 0.70 → 0.80]`
- Re-measure after: `[e.g. 10 cycles]`

## 4. Record the meta-cycle

Append one line to `logs/meta-cycles.jsonl` (see RUNBOOK "Meta-cycle operation"):

```json
{"ts":"<UTC ISO>","cyclesAt":<totals.cycles>,"changes":["<short>", "..."],"baseline":{"firstPassRate":0.7,"autonomyHours":41.2,"costUsd":92.1,"reworkCostUsd":8.4}}
```

The `baseline` is the totals snapshot at the moment of the change — the next
meta-cycle diffs against it to decide whether the change helped.

## 5. Verdict

A meta-cycle is READY_TO_MERGE when: proposals are written as concrete diffs,
each names a target metric + value, the change set is ≤3 items, and the
`logs/meta-cycles.jsonl` line is appended. Applying the diffs is normal feature
work in following cycles — the meta-cycle's product is the *decision*, recorded.
