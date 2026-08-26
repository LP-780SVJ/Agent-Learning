# W5 Scheduler Benchmark

## Scope

This benchmark measures the in-process synchronous TaskScheduler only. It covers schedule latency, first-wave claim throughput, and duplicate-claim contention failure rate. It does not measure Worker execution, mailbox behavior, crash recovery, durable queue replay, or Multi-Agent speedup.

## Environment

- Generated at: 2026-08-26 17:06:22 +0800
- Base HEAD: `3c23661985ddcdb39f78b7c4dc574b39620472df`
- Commit SHA: `3c23661`
- Working tree: `dirty`
- scheduler.py SHA-256: `6cc46d198bd019224556df40a19d464231025e6c88fcfa695124772ac2aea580`
- benchmark_scheduler.py SHA-256: `3214f191036ed59ccff4d7a2b3a758040aa76f627e6972dffa8a1ae949ffd6c7`
- Python: `CPython 3.11.16`
- Random seed: `20260826`
- Warmup runs per case: `5`
- Measured runs per case: `30`

## Results

| tasks | workers | setup median ms | setup p95 ms | schedule median ms | schedule p95 ms | claim throughput median ops/s | claim throughput p95 ops/s | contention failure median | contention failure p95 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1 | 20.620 | 32.675 | 4.862 | 6.971 | 9209.343 | 14539.322 | 0.000 | 0.000 |
| 100 | 4 | 15.674 | 28.712 | 2.847 | 5.108 | 10054.689 | 20160.071 | 0.750 | 0.750 |
| 100 | 8 | 16.541 | 28.969 | 4.250 | 6.416 | 11506.870 | 17027.907 | 0.875 | 0.875 |
| 100 | 16 | 16.728 | 19.832 | 4.780 | 6.584 | 12238.022 | 21468.038 | 0.938 | 0.938 |
| 500 | 1 | 83.565 | 105.417 | 21.031 | 29.033 | 7328.311 | 11708.779 | 0.000 | 0.000 |
| 500 | 4 | 83.460 | 111.972 | 21.994 | 35.552 | 10631.189 | 20736.885 | 0.750 | 0.750 |
| 500 | 8 | 73.657 | 91.431 | 19.889 | 33.035 | 9917.038 | 13011.896 | 0.875 | 0.875 |
| 500 | 16 | 103.159 | 126.848 | 30.588 | 42.042 | 10469.392 | 16962.180 | 0.938 | 0.938 |
| 1000 | 1 | 168.688 | 200.932 | 34.395 | 49.122 | 7065.884 | 11136.602 | 0.000 | 0.000 |
| 1000 | 4 | 146.190 | 173.644 | 34.186 | 45.453 | 12440.831 | 19413.612 | 0.750 | 0.750 |
| 1000 | 8 | 168.712 | 228.819 | 36.489 | 54.077 | 13893.387 | 21766.990 | 0.875 | 0.875 |
| 1000 | 16 | 159.354 | 198.733 | 36.949 | 50.457 | 14399.861 | 20131.458 | 0.938 | 0.938 |

## Interpretation

- Schedule latency includes dependency-ready resolution and idempotent enqueue for independent tasks. Scheduler/DAG/Registry setup is reported separately.
- Claim throughput measures only the first wave of in-process claims; it does not include Worker execution.
- Contention failure rate is expected to approach `(workers - 1) / workers` for one task because exactly one worker should win.
- These results do not prove end-to-end Multi-Agent acceleration.

## Deferred Metrics

- Recovery latency: DEFERRED / NOT_RUN until Day5 crash and heartbeat semantics exist.
- Durable replay latency: DEFERRED / NOT_RUN until Day6 TaskStore exists.
- End-to-end task success/cost/latency: DEFERRED / NOT_RUN until Worker execution and merge/review are connected.
