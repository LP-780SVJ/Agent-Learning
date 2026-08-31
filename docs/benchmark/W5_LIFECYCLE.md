# W5 Lifecycle Benchmark and Ablation Plan

## Status

PLANNED / NOT_RUN. Deferred to the unified Week5 weekend experiments by user
instruction. No raw samples, manifest, API calls or benchmark results produced
in this implementation task. Correctness test results are not performance data.

The old `W5_SCHEDULER.md` measurements do not describe the Day5 implementation.
Its existing benchmark script only received a required explicit-lease API
migration; it was not executed. Do not compare its old measurements to invented
Day5 numbers.

## Workload and Baseline

- Fake Worker/short FakeFactory, not a real provider or Worker process.
- 100/500/1000 Workers; fixed recorded READY/BUSY and CLAIMED/RUNNING ratios.
- 0%/10%/100% timeout candidates, available/missing compatible roles.
- One thread and 4/8 contending threads; new candidates and repeated sweeps separate.
- Fresh identical setup per sample; setup, first claim and hot paths separate.
- Baseline: snapshot/deadline-only scan. Full: revalidation, atomic ownership
  revocation, budgeted requeue, audit, and separately logical restart. An operation
  that performs no recovery is not a functionally equivalent faster implementation.

Planned warmup: 5 iterations; measured: 30, no data collected yet. Use
`time.perf_counter()` for real operation timings and FakeClock for injected failure
order. Never report artificial FakeClock advancement as measured recovery time.

## Metrics

| Metric | Interval / interpretation |
| --- | --- |
| Heartbeat P50/P95 and ops/s | Valid current-generation heartbeat submission |
| Scan P50/P95 | Snapshot and deadline computation only |
| Detection latency | First detection minus last heartbeat |
| Detection overshoot | First detection minus last heartbeat minus timeout |
| Recovery processing P50/P95 | Revalidation start to atomic recovery commit |
| Logical restart | Reserve to publication; separate factory and control-plane costs |
| Scheduling wait | Requeue to next successful compatible claim |
| Correctness | Stale acceptance, duplicate requeue, ownership divergence, terminal resurrection, budget violation |
| Retention | Event count, serialized bytes, tracemalloc growth; not mislabeled RSS |

Audit-history copying and shared-lock contention must be measured rather than
assumed negligible. Heartbeat latency does not prove useful task progress.

## Ablation Plan

All rows NOT_RUN. Weakened variants belong only in experimental adapters, never
in production defaults. Save intermediate states and submitted tokens, not just
one final success flag.

| Variant | Same controlled scenario as full system | Primary observation |
| --- | --- | --- |
| No attempt fencing | Same worker_id, same generation, attempt1 fail then attempt2 RUNNING; late start/complete/fail from attempt1 | Accepted stale result / corrupted attempt2 |
| No generation fencing | generation1 callback after generation2 publication | New-generation corruption / false heartbeat freshness |
| No candidate revalidation | Scan, then heartbeat/complete/new claim, then old candidate | False revocation / terminal resurrection |
| Split non-atomic updates | Barrier between Task/Worker writes, reader plus injected failure | Partial state / ownership divergence |
| No timeout recovery | Same missing-heartbeat trace | Stranded CLAIMED/RUNNING, not a zero-latency performance victory |
| No restart budget | Identical repeated factory failure, externally bounded number of probes | Factory count / budget violation |

No-attempt-fencing must NOT change worker_id: that would let owner checking reject
the result and conceal the defect being measured. Isolate generation and attempt
as separate variables. Same seeds, topology, clock trace, role constraints,
thread count, callbacks, budget settings, audit strategy and machine resources
across paired comparisons. Explicitly label variants which remove audit itself.

## Reproducibility Plan

Record HEAD/dirty, touched code hashes, Python/dependency/OS versions, seed,
Worker/Task counts, role distribution, heartbeat/timeout/cooldown, retry/restart
budgets, warmups, iterations, thread count, factory behavior, event policy,
precise timing endpoints and raw per-run samples. Pin one code revision for the
comparison and separate cold setup from steady state. No performance conclusion
or SUPPORTED label before raw evidence and independent review.

## Unverified Scope

Process kill, network partitions across hosts, durable restart, model progress,
real tool cancellation and external exactly-once effects are NOT covered by this
plan's in-memory loss simulation. Future integration needs a different workload
and explicit process/runtime/worktree evidence.
