# W5 Mailbox Ablation

## Scope

This is a correctness/safety ablation for AgentMailbox broadcast atomicity. It is not a performance benchmark and does not measure Multi-Agent speedup.

## Environment

- Generated at: 2026-08-27 16:10:34 +0800
- Base HEAD: `076b5c23a930536cbc44941d708cab1bc41440c8`
- Commit SHA: `076b5c2`
- Working tree: `dirty`
- OS: `macOS-14.2.1-x86_64-i386-64bit`
- Python: `CPython 3.11.16`
- Random seed: `20260827`
- mailbox.py SHA-256: `7a89e795a0017ca9754272f16da57ad030963e8835a15e825d950c8a052d5c2f`
- ablation_mailbox.py SHA-256: `278863d5dbd5062b35718bfc7eb51cf4f6da45a2e348030ac3f47f706de30047`

## Systems

- Full: current all-or-nothing `AgentMailbox.broadcast()`.
- Ablated: one-off experiment code that loops over `send()` recipients.

## Workloads

| workload | failure mode | full error | full new messages | ablated error | ablated new messages | partial delivery | inbox divergence | cleanup required |
|---|---|---|---:|---|---:|---:|---:|---:|
| unknown-recipient-second-of-three | unknown recipient | UnknownAgentError | 0 | UnknownAgentError | 1 | 1 | 1 | 1 |
| unknown-recipient-third-of-four | unknown recipient | UnknownAgentError | 0 | UnknownAgentError | 2 | 1 | 1 | 2 |
| full-recipient-second-of-three | full recipient | MailboxFullError | 0 | MailboxFullError | 1 | 1 | 1 | 1 |
| full-recipient-third-of-four | full recipient | MailboxFullError | 0 | MailboxFullError | 2 | 1 | 1 | 2 |

## Aggregate Results

- workloads: `4`
- partial_delivery_count: `4`
- inbox_divergence_count: `4`
- cleanup_required_count: `6`

## Delta

- Full broadcast produced `0` partial deliveries across all failure workloads.
- Ablated loop-send produced `4` partial delivery workloads and `6` messages that would require cleanup.

## Interpretation

The all-or-nothing broadcast contract prevents team-state divergence when one recipient is missing or full. Looping over `send()` is simpler, but it can deliver earlier messages before a later recipient fails.

## Limitations

- This ablation does not modify production code.
- It does not measure latency or throughput.
- It covers deterministic unknown-recipient and full-inbox failures.
- Tester still decides whether DD-W5-04 should be marked SUPPORTED.
