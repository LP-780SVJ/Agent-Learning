# W5 Lifecycle Failure Cases

## Evidence Boundary

Deterministic regression coverage for the in-process Day5 control plane.
These cases inject local time/order/factory failures, not real process crashes.
Performance ablations remain PLANNED / NOT_RUN. Independent acceptance is pending.
Exact run totals/environment are in the Day5 implementation log.

## Case Matrix

| ID | Initial state and injected order | Expected invariant / regression |
| --- | --- | --- |
| F-W5-D5-01 | CLAIMED or RUNNING; advance to timeout; recover | owner cleared; bounded READY/FAILED; Worker FAILED; `test_recovery_claimed_and_running_respects_retry_budget` |
| F-W5-D5-02 | Same w1/gen1: attempt1 fail, attempt2 RUNNING, late attempt1 start/complete/fail | new attempt unchanged; `test_same_worker_old_attempt_cannot_mutate_new_attempt` |
| F-W5-D5-03 | w1/gen1 restarted to gen2, submit old heartbeat/claim/stop/result | stale generation rejected; `test_restart_rejects_old_generation_heartbeat_claim_stop_and_scan` |
| F-W5-D5-04 | Scan, then heartbeat/complete/new claim/stop, submit old candidate | STALE_CANDIDATE; no revocation; `test_timeout_candidate_is_revalidated_after_state_change` |
| F-W5-D5-05 | Recover task with 1 or 2 max attempts; duplicate sweep | FAILED Worker not released READY; no terminal resurrection; recovery/budget tests |
| F-W5-D5-06 | Factory raises twice with controlled cooldown | FAILED; no generation bump; count exhausted; `test_factory_failure_budget_and_cooldown_are_bounded` |
| F-W5-D5-07 | Factory waiting on Event; stop; release callback | STALE_TICKET, STOPPED, no restarted event; `test_stop_during_factory_rejects_late_callback_without_core_lock` |
| F-W5-D5-08 | Raise during event preparation after draft Worker/Task change | Task/Worker/queue/events rollback together; `test_recovery_prepare_failure_rolls_back_all_objects` and fencing draft rollback |
| F-W5-D5-09 | Concurrent sweeps while first factory waits | One reservation/factory, one queue entry; `test_concurrent_sweeps_reserve_only_one_factory_and_requeue_once` |
| F-W5-D5-10 | Claim/complete compete with old recovery candidate; snapshot reader | Only consistent outcomes; bounded Barrier/Event/join tests |
| F-W5-D5-11 | Wall clock jumps, monotonic remains controlled | Deadlines unchanged; `test_wall_clock_does_not_drive_timeout` |
| F-W5-D5-12 | Old restart failure after new reservation, or after gen2 publication | New reservation/generation unchanged; old-ticket regression tests |

Root-cause classes guarded here: identity reused without attempt fencing;
generation-only validation missing revision; Task/Worker writes split across
locks; recovery calling an unconditional release-to-READY helper; factory called
under lock or published without reservation CAS; retry/restart budget reset;
wall-clock deadlines; message transport confused with task authority.

Reproduce the deterministic cases from repository root:

```bash
.venv/bin/python -m pytest tests/agent_team/test_registry.py tests/agent_team/test_fencing.py tests/agent_team/test_lifecycle.py -q
```

## Explicit Remaining Limitations

1. A synchronous factory that never returns is not preempted. Other threads can
   revoke it logically; there is no actual process/thread kill. Tests bound their
   own Event waits but that is NOT production factory timeout enforcement.
2. A Worker can heartbeat while making no task progress. No execution/progress
   deadline was implemented under the label heartbeat timeout.
3. A fenced-out result can still have caused earlier external tool effects.
   SafeExecution/Runtime do not yet consume Team tokens; no exactly-once claim.
4. In-memory state and audit disappear on process exit. Day6 durable reconciliation
   must issue a new runtime epoch, not reuse monotonic readings blindly.
5. Event history and copy costs grow with lifetime; no retention/performance
   conclusion until the weekend experiment.

## Template for Future Observed Failures

```text
ID / Status:
Capability and violated invariant:
HEAD / dirty / environment / exact command:
Initial Worker / Task / queue / lease / claim:
Injected order (FakeClock, Barrier, Event):
Expected state and zero-side-effect assertions:
Actual state and event transaction IDs:
Root cause and smallest reproducer:
Fix / regression test:
What this proves and what remains unverified:
```

## 2026-09-01 Independently Found Defects and Coder Corrections

Historical source: `test_log/2026-09-01_week5_day5_lifecycle_acceptance_log.md`.
That log remains unchanged: FAIL, 52 passed / 6 failed in its focused suite.
The first Coder run in this repair task reproduced exactly those six failures.
The earlier case matrix was not exhaustive; green foundation tests did not
establish these two missing boundary guarantees.

### F-W5-D5-13 / Acceptance F01 / P1

Status: REPRODUCED, CODER_FIXED_WITH_REGRESSION; independent re-acceptance pending.
Module: registry.py / lifecycle.py.

Scenario: revoke a RUNNING attempt, reserve a replacement, then raise
KeyboardInterrupt/SystemExit from WORKER_RESTARTING observer before the ticket
returns. Expected FAILED with no reservation; actual RESTARTING with restart_id,
factory uncalled. Impact: Worker excluded from heartbeat scanning and unable to
restart, while its prior task recovery is already committed.

Root cause: Lifecycle's exception handler only surrounded factory construction;
it did not own the ticket at the earlier callback boundary. Fix: Registry cleans
the exact committed ticket at that boundary; factory shares the same cleanup.
Matching cleanup preserves original Worker/generation/budget/cooldown and task
recovery, publishes FAILED/no restart_id, then re-raises the original interrupt.
STOPPED, new ticket or new generation makes old cleanup stale instead.

Cleanup observer errors cannot undo committed cleanup or replace the primary
interrupt. They produce delivery-failure audit plus safe notes; failed secondary
audit recording leaves a note. Reservation history is retained, and the cleanup
reason `restart_interrupted` does not imply the factory was called.

Regression: `test_restart_interrupt_preserves_original_and_committed_facts`,
`test_reentrant_stop_before_interrupt_is_not_overwritten`,
`test_old_interrupt_cleanup_cannot_overwrite_new_ticket_or_generation`,
`test_interrupt_cleanup_revalidates_every_ticket_fence`,
`test_cleanup_audit_error_does_not_mask_original_interrupt`, and
`test_cleanup_observer_is_outside_lock_and_cannot_mask_interrupt` in
`tests/agent_team/test_lifecycle_fixes.py`. These assert exception identity, state,
object identity, callback counts, cooldown, budget and ordered committed facts.

Remaining risk: not process termination, arbitrary signal masking or durable
failure logging. A synchronous callback that never returns remains unbounded.

### F-W5-D5-14 / Acceptance F02 / P2

Status: REPRODUCED, CODER_FIXED_WITH_REGRESSION; independent re-acceptance pending.
Module: scheduler.py.

Scenario: reverse lexical chain Z -> M -> A, max_attempts=1, timeout/stop from
CLAIMED/RUNNING. Expected Z FAILED and all descendants BLOCKED in one transaction;
actual M BLOCKED but A PENDING. Four original tester instances failed. Normal
terminal fail shared the same incomplete propagation helper.

Root cause: a single lexicographic scan examined A before M became BLOCKED.
Fix: bounded topological closure from the cached DAG order, then original ID-order
transition/event application inside the same transaction. The closure costs
O(V + E), visits each node once and needs no repeated external schedule. Overall
Scheduler still pays sorting, role lookup and draft-copy costs.

Regression: `test_terminal_closure_is_atomic_and_independent_of_node_names`
(64-node chain, diamond, renamed nodes, unrelated branch and all terminal causes),
`test_retry_blocks_descendants_only_after_budget_is_exhausted`, and
`test_descendant_event_failure_rolls_back_entire_terminal_transaction`.
Tests assert every descendant status/owner/attempt, deterministic event ordering,
transaction correlation, stable unrelated work, no duplicates and rollback after
the second descendant event has already been appended to the draft.

### Reproduction and Evidence

```bash
.venv/bin/python -m pytest tests/agent_team/test_lifecycle_acceptance.py -q
.venv/bin/python -m pytest tests/agent_team/test_lifecycle_fixes.py -q
```

Post-fix focused evidence: original acceptance 58 passed; new regressions 60
passed. See the new `test_log/2026-09-01_week5_day5_lifecycle_fix_log.md` for the
ordered re-verification, exact environment and unchanged historical type debt.
Benchmark/Ablation remain NOT_RUN; no measured performance improvement or
independent acceptance approval is implied.
