# W5 Scheduler Benchmark

## Scope

This benchmark measures the in-process synchronous TaskScheduler only. It covers schedule latency, first-wave claim throughput, and duplicate-claim contention failure rate. It does not measure Worker execution, mailbox behavior, crash recovery, durable queue replay, or Multi-Agent speedup.

## Environment

- Generated at: 2026-08-26 14:38:58 +0800
- Commit SHA: `32c4666`
- Working tree: `dirty`
- Python: `CPython 3.11.16`
- Random seed: `20260826`
- Warmup runs per case: `5`
- Measured runs per case: `30`

## Results

| tasks | workers | schedule median ms | schedule p95 ms | claim throughput median ops/s | claim throughput p95 ops/s | contention failure median | contention failure p95 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1 | 6.737 | 11.084 | 13471.208 | 17772.722 | 0.000 | 0.000 |
| 100 | 4 | 7.048 | 9.024 | 21453.631 | 25262.732 | 0.750 | 0.750 |
| 100 | 8 | 8.197 | 14.067 | 24937.136 | 29371.703 | 0.875 | 0.875 |
| 100 | 16 | 13.132 | 18.883 | 15154.600 | 25642.710 | 0.938 | 0.938 |
| 500 | 1 | 50.337 | 64.571 | 9013.496 | 12309.813 | 0.000 | 0.000 |
| 500 | 4 | 60.987 | 78.891 | 12399.686 | 16024.871 | 0.750 | 0.750 |
| 500 | 8 | 51.423 | 71.831 | 23560.695 | 25999.097 | 0.875 | 0.875 |
| 500 | 16 | 41.787 | 56.863 | 24261.053 | 27865.826 | 0.938 | 0.938 |
| 1000 | 1 | 80.058 | 95.122 | 12366.078 | 14662.112 | 0.000 | 0.000 |
| 1000 | 4 | 86.018 | 102.341 | 19364.741 | 22658.268 | 0.750 | 0.750 |
| 1000 | 8 | 87.452 | 102.638 | 23324.013 | 26548.702 | 0.875 | 0.875 |
| 1000 | 16 | 82.823 | 100.161 | 22355.474 | 28196.317 | 0.938 | 0.938 |

## Interpretation

- Schedule latency includes dependency-ready resolution and idempotent enqueue for independent tasks.
- Claim throughput measures only the first wave of in-process claims; it does not include Worker execution.
- Contention failure rate is expected to approach `(workers - 1) / workers` for one task because exactly one worker should win.
- These results do not prove end-to-end Multi-Agent acceleration.

## Deferred Metrics

- Recovery latency: DEFERRED / NOT_RUN until Day5 crash and heartbeat semantics exist.
- Durable replay latency: DEFERRED / NOT_RUN until Day6 TaskStore exists.
- End-to-end task success/cost/latency: DEFERRED / NOT_RUN until Worker execution and merge/review are connected.
