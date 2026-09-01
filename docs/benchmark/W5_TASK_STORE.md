# W5 TaskStore, Hydration and Resume Benchmark Plan

## Status

PLANNED / NOT_RUN. Per the Week5 schedule, performance and ablation runs are
deferred to the unified weekend experiment. No measurements or raw samples were
created during Day6 implementation.

## Workloads

Generate deterministic DAGs with 100, 500 and 1000 Tasks. Record edge count,
READY/waiting/terminal/in-flight distribution, Worker count, messages, in-flight
claims, dedupe ids and Team events. Use the same seed and state for paired runs.

Measure cold and warm conditions separately. Cold opens a new Python process and
SQLite connection; warm repeats against OS/page-cache-warmed files. Setup and test
data generation are excluded from timed intervals.

## Timing Segments

| Metric | Start / end boundary |
| --- | --- |
| `T_load` | Store open/schema gate to validated `TeamStateSnapshot` |
| `T_reconcile` | Validated snapshot to reconciliation report |
| `T_hydrate` | Prepared snapshot to complete fresh Runtime graph |
| `T_persist` | Begin CAS transaction to committed state+events |
| `T_recovery_ready` | Resume start/writer acquisition to Session RUNNING publication |

Report p50/p95 and raw samples. Also report SQLite file/WAL size, rows by table,
event count and correctness failures. Planned warmup and iteration counts must be
declared in the manifest before running, not chosen after seeing results.

## Baselines and Ablations

All variants are test-only adapters and must pass the same correctness gate.

| Variant | Controlled comparison | Purpose |
| --- | --- | --- |
| Full normalized SQLite | Selected production design | Reference |
| Memory-only | Same state transitions, no persistence | Quantify durability overhead; cannot count as correct recovery |
| Atomic JSON snapshot | Same durable fields, no claim/event transaction | Compare format/write costs and exposed correctness limitations |
| SQLite JSON blob | Same SQLite settings and revision protocol | Measure normalization cost without changing storage engine |
| No event history | Same state tables, event writes removed in adapter | Isolate audit write cost; correctness/audit gate intentionally fails |
| Destructive receive | Same messages, pop-before-persist adapter | Demonstrate crash-loss behavior, not a production optimization |

Do not weaken production code with feature flags. Use the same DAG, messages,
events, SQLite journal/synchronous settings (except the explicit variant), machine,
Python process model and crash points for paired comparisons.

## Reproducibility Manifest

Record HEAD and dirty state, Python version, SQLite library version, OS/machine,
filesystem, journal/synchronous/foreign-key settings, schema version, seed,
Task/edge/Worker/message/event counts, cold/warm mode, warmups, iterations, timing
clock and raw sample path.

## Correctness Gate

Before timing, each adapter must demonstrate CAS conflict handling, old epoch
fencing, queue/ownership consistency, Mailbox ordering/dedupe, state/event crash
behavior and unknown Git-effect fail-closed. A faster incorrect variant remains
an ablation observation, not a viable implementation.

## Unverified Scope

No numbers exist yet. The plan does not benchmark remote storage, multiple hosts,
real LLM calls, real Worker processes, arbitrary SIGKILL points or external
side-effect exactly-once.
