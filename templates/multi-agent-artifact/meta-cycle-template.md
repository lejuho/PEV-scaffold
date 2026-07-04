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
- cost: `$[totals.costUsd]`  ·  rework cost: `$[totals.reworkCostUsd]`
- failure-tag distribution (last ~20 cycles): executor `[n]` · plan `[n]` ·
  reviewer-FP `[n]` · infra `[n]`
- recent trend (from the dashboard sparkline / history table): `[1–2 sentences]`

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
