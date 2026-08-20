# Week4 Day4 Session Persistence + Resume 验收日志

日期：2026-08-20  
P1 修复复验日期：2026-08-21  
目标分支：week4  
验收对象：`codeteam/session/`、`tests/session/`  
任务开始 HEAD：05c8b067104aff5db9fb89c0b1c475cd4cfa202a

## 1. Capability Mapping

被测模块属于能力树：

- Agent Harness：State / Stop Conditions / Error Handling
- Tool Runtime：可恢复执行边界和运行时重建入口
- Workspace & Sandbox：worktree / checkpoint 引用对账
- Observability：`events.jsonl` 审计事件
- Evaluation：resume、crash consistency、failure case regression

它主要证明的 Agent Runtime 能力：

- Python 进程消失后，Task / Plan / Worktree / Usage / Checkpoint / CurrentState 可由 durable state 恢复。
- `load()` 只读 durable snapshot，`resume()` 负责 lock、reconcile、runtime reconstruction。
- stale / drift / terminal / corrupted / concurrent resume 等失败场景 fail closed。

## 2. Repository Inspection

实际检查文件：

- `learning-plan/week4/day4.md`
- `prompt/test_Agent.md`
- `.codex/AGENTS.md`
- `pytest.ini`
- `codeteam/session/__init__.py`
- `codeteam/session/errors.py`
- `codeteam/session/models.py`
- `codeteam/session/store.py`
- `codeteam/session/service.py`
- `tests/session/conftest.py`
- `tests/session/test_day4_durable_contract.py`
- `tests/session/test_day4_store_events.py`
- `tests/session/test_day4_pause_reconcile_resume.py`
- `tests/session/test_step0_state_gates.py`

Git 状态：

```text
## week4...origin/week4
```

本轮修改后只涉及允许路径：

- `codeteam/session/models.py`
- `tests/session/test_day4_durable_contract.py`
- `tests/session/test_day4_pause_reconcile_resume.py`
- `tests/session/test_step0_state_gates.py`
- `test_log/2026-08-20_week4_day4_session_resume_acceptance_log.md`

未修改学习文档、prompt、fixtures、evals 或项目配置。

## 3. Requirement Matrix

| ID | 要求 | 证据 | 状态 |
| --- | --- | --- | --- |
| R1 | Store / Service 职责分离，load 不等于 resume | Store 无 resume 业务；`test_session_service_resume_exists_on_service_not_outcome` | PASS |
| R2 | Durable Contract：Session 只保存 durable state，不保存 runtime object | `models.py` durable fields；`test_ephemeral_objects_are_rejected_from_durable_snapshot` | PASS |
| R3 | JsonSessionStore create / save / load | `test_store_create_then_load_round_trips`、`test_store_save_increments_state_version_and_updated_at` | PASS |
| R4 | session_id path traversal 防护 | `test_store_rejects_session_id_path_traversal`、`test_store_exposes_public_session_dir_with_path_guard` | PASS |
| R5 | unsupported schema / corrupted / missing session | `test_store_load_missing_session_raises`、`test_store_load_invalid_json_raises_corrupted`、`test_store_load_unsupported_schema_version_raises` | PASS |
| R6 | atomic write fault injection，replace 前失败旧 snapshot 完整 | `test_atomic_save_failure_preserves_previous_snapshot` | PASS |
| R7 | events seq 递增、state_version 对齐 | `test_append_event_seq_starts_at_one_and_uses_state_version` | PASS |
| R8 | partial event line 容忍 | `test_load_events_tolerates_trailing_partial_line` | PASS |
| R9 | duplicate / gap / out-of-order event 检测 | `test_find_timeline_anomalies_reports_duplicate_gap_and_out_of_order` | PASS |
| R10 | pause 顺序：stop active op → save PAUSED → write event | `test_pause_order_is_stop_refresher_save_then_event` | PASS |
| R11 | resume 顺序：load → lock → reconcile → reconstruct runtime → save RUNNING → write event | `test_resume_resumable_reconstructs_runtime_saves_running_and_holds_lock` | PASS |
| R12 | COMPLETED / FAILED session 拒绝 resume | `test_resume_rejects_terminal_session_and_writes_event` | PASS |
| R13 | stale RUNNING → RECOVERY_REQUIRED，不能直接续跑 | `test_reconciler_stale_running_requires_recovery_and_patches_status`、`test_resume_recovery_required_persists_status_and_event` | PASS |
| R14 | repo identity mismatch | `test_reconciler_repo_common_dir_mismatch_is_invalid`、`test_resume_repo_mismatch_rejects_and_releases_writer_lock` | PASS |
| R15 | worktree missing | `test_reconciler_missing_worktree_requires_recovery` | PASS |
| R16 | worktree dirty / head drift | `test_reconciler_worktree_dirty_drift_requires_recovery`、`test_reconciler_worktree_head_drift_requires_recovery` | PASS |
| R17 | checkpoint missing | `test_reconciler_missing_checkpoint_requires_recovery` | PASS |
| R18 | provider/model unavailable，不能静默换模型 | `test_reconciler_provider_unavailable_requires_recovery` | PASS |
| R19 | concurrent resume / single-writer lock | `test_concurrent_resume_allows_only_one_writer` | PASS |
| R20 | last_failure / session 持久化内容不得泄露 secret | `test_last_failure_source_message_is_redacted_when_persisted`；`test_last_failure_metadata_secret_is_redacted_when_persisted` 修复后 PASS | PASS |
| R21 | 新进程恢复 Task / Plan / Worktree / Usage / Checkpoint / CurrentState 未丢 | 新增 `test_resume_in_new_process_preserves_durable_runtime_state` | PASS |
| R22 | K1/K3：VERIFYING→PAUSED、PAUSED→PLANNING | `tests/session/test_step0_state_gates.py` | PASS |
| R23 | 真正 Ctrl+C → Resume 跨进程实验 | 现有 KeyboardInterrupt 单进程闸门 + 新增跨进程 resume；未真实 SIGINT kill/resume | PARTIAL |

## 4. 新增或修改测试

新增测试：

- `test_last_failure_metadata_secret_is_redacted_when_persisted`
- `test_resume_in_new_process_preserves_durable_runtime_state`

修改测试：

- `test_step0_state_gates.py` 中对 fake inspector 使用 `cast(Any, ...)`，消除 tests/session 自身 mypy 错误。

## 5. 实际执行命令与结果

### 5.1 Session focused pytest

```bash
.venv/bin/python -m pytest tests/session -q
```

最终结果：

```text
exit code: 0
57 passed, 0 failed, 0 skipped, 0 errors
```

### 5.2 Session focused pytest with skip reasons

```bash
.venv/bin/python -m pytest tests/session -q -rs
```

最终结果：

```text
exit code: 0
57 passed, 0 failed, 0 skipped, 0 errors
```

### 5.3 Full pytest

```bash
.venv/bin/python -m pytest -q
```

最终结果：

```text
exit code: 0
1044 passed, 0 failed, 6 skipped, 0 errors
```

### 5.4 Ruff

```bash
.venv/bin/python -m ruff check tests/session codeteam/session
```

最终结果：

```text
exit code: 0
All checks passed!
```

### 5.5 Mypy

```bash
.venv/bin/python -m mypy codeteam/session tests/session
```

最终结果：

```text
exit code: 1
24 errors in 6 files
```

mypy 分类：

- Day4 session 生产代码错误：0 个，`codeteam/session/` 未报错。
- Day4 session 测试错误：0 个；本轮修复了 `tests/session/test_step0_state_gates.py` 的 fake inspector 类型问题。
- 项目历史/依赖链类型错误：24 个。

历史/依赖链错误文件：

- `codeteam/instructions/frontmatter.py`：缺少 `yaml` stub，`import-untyped`
- `codeteam/parsing/tree_sitter_parser.py`：bytes/str 与 tree-sitter parse 类型不匹配
- `codeteam/failures/retry.py`：`object` 转 `float` 类型不安全
- `codeteam/failures/classifier.py`：`AgentErrorCode | None` 赋给 `AgentErrorCode`
- `codeteam/search/ripgrep.py`：`None`/IO/dict union 访问问题
- `codeteam/agent/orchestrator.py`：`float | None` 和 `RepairLoopRunResult | None` 未收窄

是否阻塞 Day4 验收：

- 不作为 session 模块新增类型缺陷阻塞。
- 但命令整体 exit code 非 0，项目级 mypy gate 仍未通过。

## 6. 已确认生产代码缺陷与修复

### P1 SECURITY_FAILURE：`last_failure.metadata` 中的 secret 会进入 session JSON（已修复）

模块：

```text
codeteam/session/models.py
```

复现命令：

```bash
.venv/bin/python -m pytest tests/session/test_day4_durable_contract.py -q
```

失败测试：

```text
test_last_failure_metadata_secret_is_redacted_when_persisted
```

预期：

```text
Session 持久化 JSON 中不得包含 sk-test-metadata-secret。
```

实际：

```text
raw_json 中包含 metadata.api_key = "sk-test-metadata-secret"。
```

初步原因：

```text
Session._sanitize_last_failure() 只将 AgentFailure.source_message 替换为 "<redacted>"；
metadata 字段原样 model_dump，未递归脱敏。
```

影响：

```text
违反 Day4 Failure Case F10：secret 落盘。Session 是 durable artifact，
一旦写入磁盘会扩大凭证暴露面。
```

修复方式：

```text
在 Session.last_failure 的序列化边界递归脱敏 metadata。
敏感 key 包括 api_key / token / secret / password / credential /
authorization / private_key 等，落盘值替换为 "<redacted>"。
未 skip/xfail；未降低断言。
```

修复后复验：

```bash
.venv/bin/python -m pytest tests/session/test_day4_durable_contract.py::test_last_failure_metadata_secret_is_redacted_when_persisted -q
```

```text
1 passed
```

## 7. Failure Cases 覆盖情况

| Failure Case | 覆盖状态 |
| --- | --- |
| F1 原地写损坏半个 JSON | PASS，atomic write fault injection |
| F2 stale RUNNING 被当正常续跑 | PASS，RECOVERY_REQUIRED |
| F3 Patch 半途 Crash / ActiveOperation 边界 | PARTIAL，STARTED active_operation 检测已覆盖，真实 patch side effect 未覆盖 |
| F4 双进程并发 resume | PASS，single-writer lock |
| F5 worktree 被删后假装继续 | PASS，worktree_missing |
| F6 main HEAD 粗暴比较误拒 | NOT_VERIFIED，当前测试聚焦 repo common dir 与 task worktree drift |
| F7 checkpoint 引用悬空 | PASS，checkpoint_missing |
| F8 provider 消失静默换模型 | PASS，provider_unavailable |
| F9 events.jsonl 半行 | PASS，partial line dropped and counted |
| F10 secret 落盘 | PASS，source_message 与 metadata secret 均已脱敏 |
| F11 Usage/repair counter 不 durable | PASS，cross-process resume 保留 SessionUsage |

## 8. Benchmark / Ablation 状态

Benchmark：DESIGNED / NOT_RUN

- save/load latency 可测：`JsonSessionStore.save/load` 是独立同步 API，可用 `time.monotonic()` 包裹。
- events size/event count 可测：`events.jsonl` append-only，event 数与文件字节数可直接统计。
- resume-to-ready 可测：`SessionService.resume()` 包含 load + lock + reconcile + runtime_factory + save + event。
- stale RUNNING → RECOVERY_REQUIRED 可测：已有 focused regression。

Ablation：DESIGNED / NOT_RUN

- No Persistence vs Persistence 的字段来源清楚：
  - repeated tool calls / total tool calls：来自事件流或后续 tool event。
  - repeated tokens/cost：来自 `SessionUsage`。
  - time to next productive action：可用 resume-to-ready + first productive event 时间戳。

本日按文档不要求执行完整 benchmark/ablation，因此未生成性能数值。

## 9. 未覆盖或无法验证内容

- 真正两个 OS 进程的 Ctrl+C/SIGINT → durable pause → 新进程 resume 全链路未完整执行。
- checkpoint chain 当前只验证 ID 是否存在，未验证链完整性或 checkpoint metadata。
- provider unavailable 当前通过 injected callback 验证，没有真实 provider registry。
- main HEAD changed 不误判未形成显式测试。
- DD-W4-D4-01/02 文档是否已写未在本轮允许路径内修改；未检查 `docs/design_decisions/` 产物。
- mypy 项目级 gate 仍受历史类型问题阻塞。

## 10. Day4 最终结论

Day4 结论：功能验收通过；工程证据仍有待补强。

通过部分：

- Store/Service 分离成立。
- Durable snapshot、schema gate、path traversal、atomic write、events.jsonl、pause/resume 顺序、single-writer lock、reconciliation 主要场景均有测试证据。
- 新增跨进程 resume 测试证明 Task / Plan / Worktree / Usage / Checkpoint / CurrentState 未丢，且 runtime_factory 被新进程重建。
- P1 secret persistence defect 已修复，`last_failure.metadata` 不再把 secret 写入 durable session JSON。

仍未完全覆盖或仍需后续处理：

- 真正 Ctrl+C/SIGINT 中断进程后 resume 的端到端强制实验仍未完整覆盖。
- mypy 命令整体失败，虽然不是 session 新增类型错误。

是否建议进入 Week4 Day5：可以进入。

进入 Day5 后建议保留的后续任务：

1. 补真正跨进程 Ctrl+C/SIGINT → resume 的端到端实验。
2. 明确处理或豁免项目历史 mypy gate。
3. 周度执行 Benchmark / Ablation。
