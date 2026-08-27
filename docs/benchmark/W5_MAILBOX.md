# W5 Mailbox Benchmark

## Scope

This benchmark measures the in-process synchronous AgentMailbox only. It covers setup, send, receive, concurrent producer send, broadcast fan-out, and approximate backlog size. It does not measure Worker execution, crash recovery, durable replay, exactly-once delivery, or Multi-Agent speedup.

## Environment

- Generated at: 2026-08-26 21:33:59 +0800
- Base HEAD: `a45ff93ad3ee09a5e1247375e3b3fa9e78d9ed2f`
- Commit SHA: `a45ff93`
- Working tree: `dirty`
- OS: `macOS-14.2.1-x86_64-i386-64bit`
- mailbox.py SHA-256: `5adc8125fec87d168910a6833348e44f085c80419188d90c353eb54444935498`
- benchmark_mailbox.py SHA-256: `52ce21a66c11da02fec3cd3e38f4056a9850a971818889daca43fc33f39ea0a5`
- Python: `CPython 3.11.16`
- Random seed: `20260826`
- Warmup runs per case: `5`
- Measured runs per case: `30`

## Message Hot Path Results

| messages | setup median ms | setup p95 ms | send median ms | send p95 ms | receive median ms | receive p95 ms | send throughput median ops/s | send throughput at p95 latency ops/s | receive throughput median ops/s | receive throughput at p95 latency ops/s | approx backlog bytes |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 0.060 | 0.108 | 7.815 | 11.145 | 3.571 | 5.860 | 12795.376 | 8973.007 | 28005.278 | 17064.744 | 29400 |
| 1000 | 0.043 | 0.046 | 77.942 | 99.369 | 32.972 | 45.172 | 12830.065 | 10063.450 | 30329.046 | 22137.447 | 293000 |
| 10000 | 0.065 | 0.128 | 890.007 | 1077.413 | 311.940 | 361.556 | 11235.867 | 9281.495 | 32057.415 | 27658.229 | 2930000 |

## Concurrent Producer Results

| messages | producers | concurrent send median ops/s | concurrent send p95 ops/s |
|---:|---:|---:|---:|
| 100 | 1 | 10474.137 | 14301.479 |
| 100 | 4 | 11803.351 | 14022.645 |
| 100 | 8 | 9480.890 | 14084.092 |
| 1000 | 1 | 15224.958 | 17265.921 |
| 1000 | 4 | 13117.498 | 15489.595 |
| 1000 | 8 | 10628.201 | 15238.148 |
| 10000 | 1 | 13249.459 | 14748.079 |
| 10000 | 4 | 12085.273 | 12983.416 |
| 10000 | 8 | 9329.939 | 10919.861 |

## Broadcast Results

| fanout | broadcast median ms | broadcast p95 ms |
|---:|---:|---:|
| 1 | 0.064 | 0.133 |
| 4 | 0.323 | 0.412 |
| 16 | 1.082 | 1.724 |
| 64 | 3.996 | 6.230 |

## Interpretation

- Setup latency is reported separately from send and receive hot paths.
- Concurrent producer throughput measures in-process thread contention only; it is not a distributed queue benchmark.
- Approximate backlog bytes are based on serialized message size, not process RSS.
- These results do not prove end-to-end Multi-Agent acceleration.

## Deferred Metrics

- Crash recovery: DEFERRED / NOT_RUN until Day5 heartbeat and failure detection exist.
- Durable replay latency: DEFERRED / NOT_RUN until Day6 durable Team Task Store exists.
- Exactly-once delivery: DEFERRED / NOT_RUN; it requires ack/nack, dedupe, and durable transaction semantics.
