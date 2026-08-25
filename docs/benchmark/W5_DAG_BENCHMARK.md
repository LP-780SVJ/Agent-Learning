# W5 DAG Benchmark

## Scope

This benchmark measures in-memory `TaskDAG` operations only: build, validate, topological sort, and ready-task query. It does not measure Scheduler throughput, Worker execution, mailbox behavior, or Multi-Agent speedup.

## Environment

- Generated at: 2026-08-25 23:41:53 +0800
- Commit SHA: `4f8aa91`
- Python: `CPython 3.11.16`
- Random seed: `20260825`
- Warmup runs per case: `5`
- Measured runs per case: `30`

## Results

| shape | nodes | edges | build median ms | build p95 ms | validate median ms | validate p95 ms | topo median ms | topo p95 ms | ready median ms | ready p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| chain | 100 | 99 | 2.511 | 3.401 | 1.859 | 2.688 | 1.632 | 2.357 | 0.104 | 0.142 |
| wide | 100 | 196 | 2.556 | 3.289 | 2.151 | 3.044 | 1.994 | 2.984 | 0.112 | 0.224 |
| layered | 100 | 173 | 3.073 | 5.006 | 1.850 | 2.520 | 1.813 | 2.407 | 0.312 | 0.513 |
| disconnected | 100 | 90 | 2.639 | 4.017 | 1.835 | 2.522 | 2.187 | 3.360 | 0.245 | 0.374 |
| chain | 500 | 499 | 14.129 | 17.877 | 9.898 | 12.467 | 8.953 | 11.040 | 0.503 | 0.606 |
| wide | 500 | 996 | 15.245 | 22.410 | 14.403 | 17.935 | 15.057 | 18.905 | 0.616 | 0.876 |
| layered | 500 | 886 | 23.103 | 32.621 | 14.766 | 19.476 | 14.147 | 19.146 | 1.892 | 3.117 |
| disconnected | 500 | 450 | 19.560 | 28.014 | 13.735 | 16.684 | 13.200 | 15.838 | 2.114 | 2.844 |
| chain | 1000 | 999 | 56.472 | 79.117 | 31.894 | 40.210 | 32.429 | 42.350 | 1.915 | 2.282 |
| wide | 1000 | 1996 | 33.456 | 54.807 | 24.482 | 43.273 | 28.904 | 40.335 | 1.270 | 1.973 |
| layered | 1000 | 1791 | 32.423 | 43.494 | 21.858 | 31.465 | 20.006 | 24.328 | 3.092 | 4.185 |
| disconnected | 1000 | 900 | 32.223 | 39.037 | 21.205 | 27.568 | 21.230 | 29.764 | 3.454 | 5.737 |

## Interpretation

- These numbers show the local cost of deterministic DAG operations.
- They do not prove that multiple agents are faster or better.
- Snapshot copying is included in `topological_sort()` and `get_ready_tasks()` because public node references are defensive copies.
- Deterministic Kahn sorting uses a heap, so the expected complexity is `O((V + E) log V)` rather than strict `O(V + E)`.

## Ablation Status

- Remove dependency graph: DEFERRED / NOT_RUN. Requires Day3 Scheduler metrics to measure wrong parallelism or serialization.
- Remove cycle detection: DEFERRED / NOT_RUN. Requires Scheduler deadlock/no-ready metrics.
- Ignore failed dependencies: DEFERRED / NOT_RUN. Requires Day3 failure propagation behavior.
