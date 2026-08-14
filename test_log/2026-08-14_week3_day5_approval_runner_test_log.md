# Week3 Day5 ApprovalManager + Safe CommandRunner Formal Test Log

## 1. Evaluation Summary

- Date: 2026-08-14
- Mode: read-only acceptance, except this test log
- Project root: `/Users/workplace/Agent-Learning`
- Branch: `week3`
- HEAD: `cb81ec8e277e7d229a5f60018ed60f6b450ff6d2`
- Target modules:
  - `codeteam/execution/approval.py`
  - `codeteam/execution/runner.py`
  - `codeteam/execution/output_limiter.py`
  - `codeteam/execution/safe_executor.py`
  - `codeteam/execution/models.py`
  - `codeteam/execution/command_policy.py`
- Target tests:
  - `tests/execution/test_approval.py`
  - `tests/execution/test_output_limiter.py`
  - `tests/execution/test_runner.py`
  - `tests/execution/test_safe_executor.py`
  - related Day4 policy regression: `tests/execution/test_command_policy.py`
- Final status: PASS with one hardening recommendation

No production code, test code, or learning-plan document was modified.

## 2. Capability Mapping

Primary capability:

- Tool Runtime: human-in-the-loop authorization, safe command execution, timeout, output control, environment isolation.

Secondary capabilities:

- Workspace & Sandbox: cwd boundary, pre-sandbox least privilege runner.
- Agent Runtime: action gating and process lifecycle supervision.
- Observability: approval requested / approved / denied / consumed audit events.
- Safety: DENY gate, one-shot approval consumption, command fingerprinting, secret-safe audit and env filtering.

What this module proves:

- A command must pass Policy and, when required, a matching Approval grant before Runner execution.
- A started process is supervised with bounded time, bounded output, non-interactive stdin, and process group cleanup.

## 3. Repository Inspection

Technical stack:

- Python 3.11
- pytest 9.1.1
- ruff 0.16.2
- pydantic 2.13.4

Public API inspected:

- `CommandRequest.fingerprint()` and `command_request_fingerprint()`
- `ApprovalManager.create_request()`, `approve()`, `deny()`, `consume()`, `is_authorized()`
- `CommandRunner.run()`
- `OutputLimiter.feed()` / `snapshot()`
- `SafeCommandExecutor.execute()`

Project rules applied:

- `.venv/bin/python` used for all commands.
- No edits to production code or tests.
- Test execution did not operate on project Git state destructively.

## 4. Requirement Matrix

| ID | Requirement | Evidence | Status |
|---|---|---|---|
| R-D5-001 | Approval must not elevate DENY into execution | `SafeCommandExecutor.execute()` returns `POLICY_DENIED` before approval flow; `test_deny_does_not_call_runner` asserts runner calls = 0 | PASS at system boundary |
| R-D5-002 | Approval must bind task / agent / command fingerprint | `_matching_grant()` checks task_id, agent_id, fingerprint; tests cover cross-task, cross-agent and modified argv | PASS |
| R-D5-003 | ONCE grant can be consumed once only | `consume()` marks `consumed_at`; test covers second use rejected and consumed event count | PASS |
| R-D5-004 | TASK grant must not become allow everything | TASK grant still requires exact task_id, agent_id and fingerprint; tests cover cross-task and fingerprint mismatch | PASS |
| R-D5-005 | Approval audit records requested / approved / denied / consumed | Approval events are emitted for request, approve, deny, consume; tests assert request / deny / consume event behavior | PASS |
| R-D5-006 | Audit must not leak full argv / env / secret | audit event data contains approval_id, task_id, agent_id, fingerprint, scope, decision, risks, actor; test asserts no argv and no SECRET | PASS |
| R-D5-007 | Runner uses shell=False, stdin=DEVNULL, env allowlist, cwd boundary | implementation inspected; tests cover stdin EOF, env secret filtering and cwd outside workspace rejection | PASS |
| R-D5-008 | Timeout sends SIGTERM, waits grace, then SIGKILL process group | implementation uses `start_new_session`, `killpg`; tests cover timeout, ignored SIGTERM, child process cleanup | PASS |
| R-D5-009 | stdout/stderr continuously drain with bounded head+tail capture | implementation uses drain threads and `OutputLimiter`; tests cover huge stdout, huge stderr, concurrent streams, head+tail semantics | PASS |
| R-D5-010 | Safe executor chains Policy -> Approval -> Runner | `SafeCommandExecutor.execute()` inspected; tests cover DENY, approval required, invalid grant, modified request and approved grant | PASS |
| R-D5-011 | deny / unapproved / invalid grant runner invocation count = 0 | `FakeRunner.calls` assertions in safe executor tests | PASS |
| R-D5-012 | Required tests exist and cover Day5 completion standard | `tests/execution/test_approval.py`, `test_output_limiter.py`, `test_runner.py`, `test_safe_executor.py` exist and pass | PASS |
| R-D5-013 | Full regression remains green | `.venv/bin/python -m pytest -q` -> 620 passed | PASS |

Important nuance:

- `ApprovalManager.create_request()` does not itself check that `PolicyEvaluation.decision == REQUIRE_APPROVAL`. The system entrypoint prevents DENY escalation, but the lower-level manager can be misused by direct callers. This is a hardening recommendation, not an observed execution failure in the approved SafeCommandExecutor path.

## 5. Test Plan

Executed and audited categories:

- Unit: fingerprint, approval grant matching, output limiter head/tail behavior.
- Component: ApprovalManager audit event lifecycle.
- Component / integration: CommandRunner process supervision with real subprocesses.
- Safety: deny path, invalid grant, TOCTOU request mutation, env secret filtering, cwd boundary.
- Regression: all `tests/execution` and full pytest suite.

Key tests inspected:

- `test_once_scope_consumes_only_once`
- `test_task_scope_does_not_cross_task_or_agent`
- `test_fingerprint_mismatch_rejects_grant`
- `test_deny_does_not_create_usable_grant`
- `test_deny_does_not_call_runner`
- `test_invalid_grant_does_not_call_runner`
- `test_modified_request_cannot_reuse_old_approval`
- `test_runner_falls_back_to_sigkill_after_sigterm`
- `test_runner_process_group_cleans_child_process`
- `test_runner_drains_concurrent_stdout_and_stderr`
- `test_runner_env_allowlist_does_not_leak_secrets`

## 6. Correctness Execution

### py_compile

Command:

```text
.venv/bin/python -m py_compile codeteam/execution/*.py
```

Result:

```text
Exit code: 0
```

### ruff

Command:

```text
.venv/bin/python -m ruff check codeteam/execution tests/execution
```

Result:

```text
All checks passed!
Exit code: 0
```

### Day5 execution tests

Command:

```text
.venv/bin/python -m pytest tests/execution -q
```

Result:

```text
110 passed in 4.16s
Exit code: 0
```

### Full regression

Command:

```text
.venv/bin/python -m pytest -q
```

Result:

```text
620 passed in 56.26s
Exit code: 0
```

## 7. Failure Analysis

No failing test was observed.

No production defect was confirmed by the executed acceptance suite.

Hardening recommendation:

- Add a direct unit test that `ApprovalManager.create_request()` rejects or refuses to create grants for `PolicyDecision.DENY`, or document that only `SafeCommandExecutor` may call it after policy gating. Current system-level behavior is safe, but a lower-level misuse path remains possible.

## 8. Acceptance Evaluation

| Area | Status | Notes |
|---|---|---|
| Approval scope | PASS | ONCE and TASK implemented; TASK remains fingerprint-bound |
| DENY enforcement | PASS | SafeCommandExecutor returns before approval / runner |
| TOCTOU prevention | PASS | command fingerprint includes argv, cwd, workspace_root, task_id, agent_id, timeout |
| Audit safety | PASS | event data omits argv/env and records fingerprint instead |
| Runner subprocess safety | PASS | shell=False, stdin DEVNULL, captured stdout/stderr, env allowlist |
| Timeout lifecycle | PASS | SIGTERM then grace then SIGKILL process group |
| Output bounds | PASS | drain threads + bounded head/tail capture |
| Executor orchestration | PASS | Policy -> Approval -> Runner tested with runner call counts |
| Regression | PASS | full suite green |

## 9. Design Decision Verification

Decision 1:

- Approval Scope first supports ONCE and TASK.

Evaluation:

- PARTIALLY_SUPPORTED.

Reason:

- Correctness and safety tests support scope semantics. No concurrent race test was run for atomic ONCE consumption under simultaneous threads, although implementation uses a lock.

Decision 2:

- Runner uses process group + SIGTERM/SIGKILL timeout handling.

Evaluation:

- SUPPORTED for current local POSIX test scope.

Reason:

- Tests verify timeout, ignored SIGTERM fallback, and child process cleanup.

Decision 3:

- Output capture uses continuous drain + bounded head/tail, not full communicate-then-truncate.

Evaluation:

- SUPPORTED for current tested workloads.

Reason:

- Tests verify huge stdout, huge stderr, concurrent output, no deadlock, byte counts and truncation flags.

Benchmark / Ablation:

- NOT RUN in this acceptance pass.
- Any performance claim about runner overhead, output scalability versus alternatives, or approval ablation remains INSUFFICIENT_EVIDENCE.

## 10. Regression

Target regression:

- `tests/execution`: PASS, 110 passed.

Full regression:

- whole project: PASS, 620 passed.

## 11. Risks and Limitations

- ApprovalManager direct misuse: lower-level `create_request()` does not reject a DENY `PolicyEvaluation`; safe executor prevents this in the intended path.
- TASK scope is exact-fingerprint based, which is safe but more restrictive than the Day5 narrative of a command capability class.
- No explicit multi-threaded race test proves one ONCE grant cannot be consumed twice under concurrent calls.
- Runner is not a sandbox. It limits process behavior from the runner layer, but filesystem/network isolation belongs to Day6 sandbox work.
- Windows-specific process group semantics were not validated; current evidence is POSIX/macOS oriented.

## 12. Evidence Artifacts

Main evidence:

- command outputs above
- `codeteam/execution/approval.py`
- `codeteam/execution/runner.py`
- `codeteam/execution/output_limiter.py`
- `codeteam/execution/safe_executor.py`
- `tests/execution/test_approval.py`
- `tests/execution/test_runner.py`
- `tests/execution/test_output_limiter.py`
- `tests/execution/test_safe_executor.py`

## 13. Interview Evidence

This Day5 module provides concrete evidence that CodeTeam separates:

- policy risk classification
- human approval
- safe process execution

Useful proof points:

- DENY and invalid approvals produce runner invocation count 0.
- Approval grants are task / agent / fingerprint bound.
- ONCE grants are consumed and cannot be reused.
- audit events record approval lifecycle without full argv or env.
- runner terminates process groups and handles large stdout/stderr without unbounded memory capture.

## 14. Final Conclusion

Day5 ApprovalManager + Safe CommandRunner acceptance:

- Correctness: PASS
- Safety: PASS
- Observability: PASS
- Regression: PASS
- Benchmark: NOT RUN
- Ablation: NOT RUN
- Overall: PASS with one hardening recommendation for direct ApprovalManager misuse.
