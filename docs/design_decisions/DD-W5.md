# Week5 Design Decision Summary

## Status

IMPLEMENTED summary of DD-W5-01 through DD-W5-07, with the post-fix real B01 and
independent Day7 re-acceptance still gated. Weekend experiment evidence remains
pending.

## Decision Chain

| Day | Decision | Authority / fence |
| --- | --- | --- |
| 1 | Lead/Worker contracts | structured identity and assignment |
| 2 | Validated Task DAG | topology and dependency invariants |
| 3 | Deterministic Scheduler | Task ownership and attempt fencing |
| 4 | Durable Mailbox semantics | message id, claim and dedupe |
| 5 | Registry/Lifecycle recovery | Worker runtime_id and generation |
| 6 | SQLite Team state + Session resume | revision CAS and new runtime epoch |
| 7 | TeamCodingRuntime adapter | runtime_id + generation + attempt + artifact |

## Week5 Boundary

The implementation proves a local Team control plane and reuses one existing
Coding Runtime and external grader. It deliberately does not allow concurrent
real coding Workers to mutate one shared worktree. Week6 must introduce explicit
per-Worker workspace ownership, patch artifacts and integration policy before a
real multi-Worker coding claim is credible.

## Evidence

Functional tests and Coder verification exist through Day7. Two historical real
B01 Team smokes are **RUN_FAILED**, not passes: the first reached patch but violated
the Checkpoint child-id contract; the second made no patch after schema-driven
initial compaction and repeated cached reads. Those deterministic defects, stale
manifest state and Team failure taxonomy now have regressions, including one
offline B01 production-chain completion. Post-fix real Provider evidence remains
pending. Deterministic benchmark and sequential/parallel ablation remain `NOT_RUN`;
Single-vs-Team remains `DESIGNED / NOT_RUN`.
