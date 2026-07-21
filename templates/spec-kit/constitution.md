# PEV + Spec Kit Constitution

## 1. Artifact hierarchy

Project requirements and architecture principles live in Spec Kit artifacts.
Execution authority lives in PEV artifacts. Resolve conflicts in this order:

1. this constitution;
2. `specs/<feature>/spec.md`;
3. `specs/<feature>/plan.md` and `tasks.md`;
4. `.review/cycle-N/selection.json` and `plan.md`;
5. implementation and review artifacts.

A feature plan is not a PEV cycle plan. The latter must be a smaller,
independently verifiable execution contract.

## 2. Role separation is mandatory

- Spec Kit defines and analyzes requirements, plans and the task graph.
- Codex selects the next PEV slice, writes its immutable selection record,
  reviews implementation and performs the approved merge.
- Claude implements only the active PEV cycle plan and resolves review findings.
- No agent may bypass `.review/cycle-N/plan.md`.

`$speckit-implement` MUST NOT be used in this repository. Product implementation
must start through PEV `/implement`, followed by `/review`, `/fix`/`/recheck` as
needed, and `/merge`.

## 3. Cycle economics

Each candidate must be scored with selection schema v2, including user value,
dependency unlock, code affinity, independent verification, change risk, test
cost, repetition and fragmentation penalties. Preserve requirement IDs and list
all included task IDs.

Do not create a single-task cycle merely because it is easy. When compatible
work from the same requirement remains, bundle it up to the largest boundary
that remains independently verifiable. A smaller boundary requires explicit
evidence that its risk reduction is worth repeated tests and fixed verification
cost.

## 4. Verification and completion

Executor done records must contain every automated check with command,
wall-clock duration and exit code. A task is complete only after the PEV verdict
passes and the cycle is merged. Do not mark Spec Kit tasks complete when merely
assigned to or implemented in an unmerged cycle.

## 5. Governance

Historical selection, review and metric records are immutable observations.
Change scoring weights only in a recorded meta-cycle after a sufficient
comparison window. Amend this constitution intentionally, document the reason,
and keep PEV role separation intact.
