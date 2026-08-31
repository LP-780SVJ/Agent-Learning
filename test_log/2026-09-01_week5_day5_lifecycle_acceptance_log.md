# Week5 Day5 Agent Lifecycle 独立正式验收

## 1. Evaluation Summary

- 验收日期：2026-08-31 开始只读检查，2026-09-01 完成执行和记录，Asia/Shanghai。日志按完成日期新增。
- 总体结论：**未通过 / FAIL**。存在 2 类可稳定复现的生产缺陷，共 6 个失败参数实例；不建议将 Day5 标为完成或直接进入 Day6 实现。
- 当前工作树验收，不是仅验收 HEAD：原有 staged、unstaged、untracked 实现均纳入。
- 新增 1 个验收测试文件，15 个测试函数、58 个参数实例；52 passed、6 failed。没有修改生产代码或已有测试。
- 原有三份 Day5 测试独立复验 100 passed；模块整体 317 passed、6 failed。
- 最终授权全量复验：1735 passed、6 failed、0 skipped、0 error，59.09s。
- Docker 经审批机制授权复验：71 passed、0 skipped。普通执行沙箱的 9 项 skip 仍保留原始记录，不能当作通过。
- Ruff 最终通过；mypy 4 项历史诊断仍未通过。新增验收测试与 Day5 新增生产文件无 mypy 诊断。
- Benchmark / Ablation：NOT_RUN，按用户要求仅审阅方案。

## 2. Capability Mapping

Primary：Multi-Agent Orchestration / Worker Lifecycle / Ownership / Scheduling / Failure Recovery。
Secondary：Agent Runtime Reliability、Observability、Concurrency Consistency、Regression Evaluation。

本轮证明或反证的是同一进程内的控制面能力：旧 attempt/代际凭据不能污染新任务；失活撤销与任务重排保持状态一致；重启 reservation 与回调需要再次验证；时间边界可确定性复现。它不证明 Worker 实际执行、OS 重启、跨进程 durable resume、分布式租约或外部副作用 exactly-once。

## 3. Repository Inspection / Baseline

仓库：/Users/root/workspace/Agent-Learning
分支：week5，跟踪 origin/week5，ahead 1。
HEAD：25dc4c70ac433e0924a65cd2f3a43a320a812b63。
解释器实测：Python 3.11.15；平台：Darwin arm64。
coder 日志中出现的 3.11.16 是历史报告内容，不当作本次环境数据。

开始时 git status --short --branch --untracked-files=all：

```text
## week5...origin/week5 [ahead 1]
 M codeteam/agent_team/__init__.py
 M codeteam/agent_team/models.py
 M codeteam/agent_team/scheduler.py
 M codeteam/agent_team/worker.py
 M codeteam/events.py
 M docs/benchmark/W5_SCHEDULER.md
 M evals/week5/benchmark_scheduler.py
AM learning-plan/week5/day5.md
 M tests/agent_team/test_mailbox.py
 M tests/agent_team/test_scheduler.py
?? codeteam/agent_team/contracts.py
?? codeteam/agent_team/coordination.py
?? codeteam/agent_team/lifecycle.py
?? codeteam/agent_team/registry.py
?? docs/benchmark/W5_LIFECYCLE.md
?? docs/design_decisions/DD-W5-05.md
?? docs/failure_cases/W5_LIFECYCLE_FAILURE.md
?? test_log/2026-08-31_week5_day5_lifecycle_implementation_log.md
?? tests/agent_team/test_fencing.py
?? tests/agent_team/test_lifecycle.py
?? tests/agent_team/test_registry.py
```

开始时 git diff --stat：10 files changed, 1592 insertions(+), 130 deletions(-)。
git diff --cached --stat：只有 learning-plan/week5/day5.md，3373 insertions。
其 index blob：39669324b43e3156589531ae2512e3016f25a755。

36 个直接输入文件的 SHA256 已在首次审阅阶段记录，并在写测试前、执行阶段、所有复验完成后逐一重新计算；结果全部相同。HEAD 与 staged 摘要也未变化。未发现其他 Agent 修改这些输入，不需要重定生产基线。普通沙箱与授权 Docker 使用同一生产工作树，不混用两个生产版本。

本轮自身测试版本变化：初稿经 ruff format 后 SHA256 为 ebd0b72d97b9772c1204cf7ecd79c6403db1c233de325d284fc8ebc3726360f9；首轮静态检查后，仅补 3 处线程 BaseException 收集的 BLE001 理由注释。最终版本 SHA256 见附录。未改任何测试逻辑或预期；最终授权全量和最后一次定向复验均使用最终版本。

实际读取并审核：
- .codex/AGENTS.md、完整 prompt/test_Agent.md、pytest.ini、pyproject.toml、requirements.txt、requirements-dev.txt。
- learning-plan/week5/week5_plan.md、完整 day5.md，特别是后附实施教程 Step 1–10、Tests、Failure Cases、最终完成标准。
- codeteam/agent_team/ 全部 11 个 Python 文件以及 codeteam/events.py。
- tests/agent_team/ 全部既有 Python 测试；逐项审阅 test_registry.py、test_fencing.py、test_lifecycle.py 的状态断言与交错。
- DD-W5-05.md、W5_LIFECYCLE_FAILURE.md、W5_LIFECYCLE.md、W5_SCHEDULER.md、benchmark_scheduler.py、coder implementation log。
- 对比 HEAD 中 scheduler.py；检查既有 test_scheduler.py/test_mailbox.py 的工作树 diff。
- 为解释环境 skip，补读 tests/sandbox/test_docker_runner_integration.py 的 capability probe 与测试列表。
- 未读取真实 secrets、环境凭据文件或 Docker 认证配置，测试中的 secret 均为合成 canary/字符串。

## 4. Requirement Matrix

证据缩写均指 tests/agent_team/：R=test_registry.py，F=test_fencing.py，L=test_lifecycle.py，S=test_scheduler.py，M=test_mailbox.py，A=本轮 test_lifecycle_acceptance.py。
除注明 REVIEW/NOT_VERIFIED 的行，证据均已由本轮 pytest 实际执行。级别为 Unit 或进程内 Component/Concurrency，不称为 OS process E2E。

| ID / 优先级 / 类别 | 要求与前置动作 | 实现位置 | 测试证据 / 预期不变量 | 结论 |
| --- | --- | --- | --- | --- |
| R01 / P1 / Ownership | Worker live state 与 Task owner 分离，AgentInfo 只作 bootstrap | registry.py、scheduler.py、models.py | A:test_activation_uses_runtime_status_and_fresh_grace_not_bootstrap_info；CREATED 描述不变但可合法 activate/claim，组合快照一致 | PASS |
| R02 / P1 / Domain | 单 Registry/Scheduler 协调域，拒绝第二绑定 | coordination.py、两类初始化 | R:test_registry_alias_and_single_scheduler_domain；L:test_public_lifecycle_exports_and_wrong_registry_rejected | PASS |
| R03 / P1 / Fencing | 同 worker、同 generation，attempt1 不能 start/complete/fail attempt2 | _require_claim_locked | F:test_same_worker_old_attempt_cannot_mutate_new_attempt 覆盖新 RUNNING；A:test_rejected_token_preserves_business_state_and_only_adds_rejection_audit 覆盖新 CLAIMED | PASS |
| R04 / P1 / Fencing | 跨 runtime、旧 generation 拒绝，不给迟到回调续权 | lease/claim validators | A:test_rejected_token_preserves_business_state_and_only_adds_rejection_audit 的 runtime/generation 三操作；L:test_restart_rejects_old_generation_heartbeat_claim_stop_and_scan | PASS |
| R05 / P1 / Fencing | 缺 token、裸字符串不查新 lease | claim/start/complete/fail | A:test_missing_tokens_never_discover_new_authority，None/string × 四 API；替换 lease discovery 为禁止调用并比较完整状态/审计 | PASS |
| R06 / P1 / Contract | token 版本、空 ID、绕过构造校验仍拒绝 | contracts.py、TaskClaim | R:test_lease_rejects_invalid_fields、test_lease_requires_generation_and_roundtrips；A:test_public_entry_revalidates_bypassed_claim_fields | PASS |
| R07 / P1 / Invariant | CLAIMED/RUNNING owner/gen/attempt 与 BUSY/occupancy 对齐，READY 不重复、终态无 owner | snapshot、claim/release/recover | A:assert_consistent 在合法转换和拒绝后检查；S:test_ready_task_is_enqueued_once_and_schedule_is_idempotent | PASS |
| R08 / P2 / Clock | 注册、激活、publish 给予本地初始宽限，不伪造 heartbeat | register/activate/_finish_restart | R:test_first_heartbeat_grace_is_registration_time_not_zero；A:activation；L:test_restart_rejects_old_generation_heartbeat_claim_stop_and_scan | PASS |
| R09 / P1 / Deadline | FakeClock T-epsilon/T/T+epsilon，READY/BUSY，精确 >= | is_expired、timeout_candidates | L:test_timeout_boundary_and_scan_is_read_only 的六组参数 | PASS |
| R10 / P1 / Heartbeat | 相同时间 revision 递增；心跳不改 Task | heartbeat | R:test_heartbeat_revision_changes_even_at_same_time_and_snapshot_is_defensive；L:test_mailbox_backlog_does_not_block_heartbeat_or_advance_task | PASS |
| R11 / P1 / Validation | NaN/inf/负值/倒退 Clock、非法 timeout/cooldown/budget | _checked_now_locked、LifecyclePolicy | R:test_bad_clock_does_not_mutate_worker、test_clock_rewind_relative_to_previous_read_is_rejected、test_policy_rejects_invalid_time_and_budget；A:invalid_clock、invalid_restart_budget | PASS |
| R12 / P2 / Clock | wall clock 与 liveness deadline 独立 | injected Clock / AgentEvent | L:test_wall_clock_does_not_drive_timeout | PASS |
| R13 / P1 / Scan | detect_timeouts 只读业务和审计，排除非活跃状态 | timeout_candidates | L:timeout_boundary、stop_is_idempotent、stop_during_factory；代码检查只扫描 READY/BUSY | PASS |
| R14 / P1 / Revalidation | scan 后 heartbeat/complete/new claim/stop/gen 变化使候选失效 | recover_worker_loss | L:test_timeout_candidate_is_revalidated_after_state_change、旧代扫描；A:test_previous_task_candidate_cannot_revoke_next_task_on_same_worker 明确 A 完成/B 被 claim | PASS |
| R15 / P1 / Revalidation | candidate task attempt/epoch 不一致、未知 worker 无部分撤销 | recover_worker_loss | A:test_candidate_validation_has_no_partial_revocation；拒绝后 Task/Worker/queue/events 不变 | PASS |
| R16 / P1 / Recovery | idle、CLAIMED、RUNNING 失活，回收 owner，attempt 不随重排增长 | _make_unavailable_locked | L:test_idle_worker_loss_has_no_task_attempt_and_audit_is_correlated、test_recovery_claimed_and_running_respects_retry_budget | PASS |
| R17 / P1 / Retry | retry 耗尽终态 FAILED、不再入队，依赖被阻塞 | _schedule_locked | L 覆盖直接依赖；A:test_exhausted_loss_blocks_all_descendants_in_one_transaction 暴露 Z->M->A 中 A 留 PENDING | FAIL / F02 |
| R18 / P1 / Placement | recovery 只重排，不选 successor，不绕过 role gate | lifecycle.sweep、scheduler.claim | L:test_recovery_does_not_bypass_role_gate_or_pick_successor；A:slow_factory 中 w2 自主 claim A attempt2，w1 仍 RESTARTING | PASS |
| R19 / P1 / Atomicity | 事件准备后异常，Worker/Task/owner/queue/membership/审计计数回滚 | 两层 _transaction | F:test_draft_failure_rolls_back_registry_task_queue_and_audit；L:recovery_prepare_failure；A:test_late_prepare_failure_restores_business_state_and_transaction_audit，8 个操作原事件 append 后注入 | PASS |
| R20 / P1 / Concurrency | concurrent claim/recovery、complete/recovery 不双重接受 | shared RLock + claim/candidate CAS | L:test_claim_vs_recovery_keeps_combined_snapshot_consistent、test_complete_vs_recovery_is_consistent_with_bounded_concurrency；Barrier、有界 join、线程异常回传 | PASS，限所测交错 |
| R21 / P1 / Concurrency | 多 sweep 单 reservation/单 factory/单次入队 | sweep/reserve | L:test_concurrent_sweeps_reserve_only_one_factory_and_requeue_once | PASS |
| R22 / P1 / Restart | reserve/build/publish；factory 锁外，其他 worker 可正常工作 | lifecycle.restart_worker | L:stop_during_factory；A:test_slow_factory_does_not_block_other_worker_task_and_heartbeat，w2 完成 A/B 后才释放 factory | PASS |
| R23 / P1 / Factory | 异常、错误类型/id/display_name/role/capabilities、原对象不能发布 | wrapper + _finish_restart | L:test_factory_must_preserve_identity_and_return_new_object、test_factory_failure_budget_and_cooldown_are_bounded；A:test_wrong_factory_type_fails_without_replacing_worker_or_task_state | PASS；agent_id 判等另由实现审查 |
| R24 / P1 / Restart CAS | 迟到成功/失败不得覆盖 STOPPED、新 generation、新 reservation | _ticket_matches_locked | L:test_stop_during_factory_rejects_late_callback_without_core_lock、test_old_restart_success_and_failure_cannot_change_new_generation、test_old_failure_ticket_cannot_overwrite_new_reservation_same_generation | PASS |
| R25 / P1 / Budget | duplicate reservation、cooldown 精确边界、0 次禁用、lifetime 次数上限 | reserve_restart、LifecyclePolicy | L:test_factory_failure_budget_and_cooldown_are_bounded、test_zero_restart_budget_and_repeated_sweep_never_call_factory、test_restart_success_does_not_reset_lifetime_budget、stop_during_factory 重复预留 | PASS |
| R26 / P1 / Generation | 仅成功 publish generation+1；失败消耗预算，成功不清 lifetime | _finish_restart | L:restart_rejects_old_generation、failure_budget、restart_success；A:wrong_factory_type；最终状态/次数检查 | PASS |
| R27 / P1 / Stop | stop 幂等、stop/factory 和 stop/complete 后不可复活 | stop_worker + reservation validation | L:test_stop_is_idempotent_and_never_resurrects、test_stop_respects_exhausted_task_budget；A:test_stop_complete_ordered_threads_never_revive_stopped_worker 强制两种先后 | PASS |
| R28 / P1 / Interrupt | KeyboardInterrupt/SystemExit 清匹配 reservation 再传播 | lifecycle.restart_worker / reserve_restart | L factory KeyboardInterrupt；A:test_restart_interrupt_cleans_matching_reservation：factory 两组通过，reservation_observer 两组失败 | FAIL / F01 |
| R29 / P1 / Mailbox | backlog 不阻塞 heartbeat；消息不代替 Scheduler 任务结算 | 独立 mailbox/control plane | L:mailbox_backlog；M:test_task_completed_message_does_not_change_scheduler_state、test_task_failed_message_does_not_change_scheduler_state | PASS |
| R30 / P1 / Observer | 回调锁外、普通异常不掩盖已提交状态，重入可 stop | _deliver_events | L:test_worker_observer_runs_outside_core_lock、test_reentrant_and_throwing_observer_cannot_hide_commit；S:sink 测试 | PASS（普通 Exception）；中断另见 R28 |
| R31 / P1 / Audit | 事务相关、事件顺序、拒绝非成功、不泄漏异常内容 | AgentEventType、metadata | L:test_worker_and_task_failure_events_share_transaction、factory_failure_budget；A:rejected_token、late_prepare_failure；S/M 安全字段 allowlist | PASS，仅测试标量审计/合成 secret |
| R32 / P2 / Compatibility | 公共导出、新旧 Registry 及异常 identity 不变 | __init__.py、worker.py alias | L:public_lifecycle_exports；R:registry_alias；A:test_legacy_registry_exception_exports_are_identical | PASS |
| R33 / P1 / Migration | 旧调用迁移保留语义断言，不仅 truthy | 既有 S/M diff、eval 两处 claim | 原 ownership/status/queue/event/role/retry 断言仍保留；claim 保存后传入 start/complete/fail；查无生产迟到回调临时续权 | PASS / REVIEW |
| R34 / P2 / Evidence | DD / failure 文档不把计划或进程内模拟夸成实测进程恢复 | DD、failure cases、implementation log | 当前 DD 明确独立验收 pending、performance NOT_RUN；本轮反证必须另记录 | PARTIAL，DD 不能升级 SUPPORTED |
| R35 / P2 / Regression | 原有 Runtime/Session/Execution、完整 suite、Docker | 指定 commands | 相关 363 passed；最终 full 1735 passed/6 failed；授权 Docker 71 passed | FAIL（full）；相关回归/Docker PASS |
| R36 / P2 / Static | lint 与类型诊断独立核对来源 | Ruff/mypy | Ruff 最终 PASS；mypy 4 项已核对历史文件，新增 0 项 | PARTIAL |
| R37 / P2 / Experiments | 仅审核可复现 benchmark/ablation 方案，周末执行 | W5_LIFECYCLE、旧脚本 | workload/指标/控制变量已设计；无本日性能原始数据；旧脚本待升级 | NOT_RUN |

说明：
- “只读扫描”允许 DD 明确规定的 _last_clock 观测水位更新，它不是 Worker heartbeat，不算业务变更；不能把此水位纳入业务回滚后允许时间倒退。
- STALE_CANDIDATE/no-op 事务可能消耗内部事务序号，但不会增加成功事件或改变业务。事务准备异常则连 transaction_seq/event_index 一起比较回滚。
- assert_consistent 不把 bootstrap BUSY 强行解释为已有 owner；正常 claim 产生的 BUSY 则必须匹配任务。
- R23 的既有 identity 参数改变 display_name；没有单独新增仅变 agent_id 的动态测试，完整 identity equality 已只读确认。不是把此子项冒充单独实测。
- 并发通过指确定性事件/屏障用例，不是线性化形式证明或大规模压力测试。

## 5. Tests / File Changes

只新增：
1. tests/agent_team/test_lifecycle_acceptance.py。
2. test_log/2026-09-01_week5_day5_lifecycle_acceptance_log.md（本文件）。

新增测试主要补齐：新 attempt 仍 CLAIMED 时的 fencing、只允许拒绝审计、无 token 不查最新 lease、绕过模型构造后的入口重校验、activate 旧 bootstrap 信息、A 完成后 B claim 的旧 candidate、事务 event append 后失败、反字典序多层 DAG、错误 factory 类型、中断清理、慢 factory 期间其他 worker 完整执行、stop/complete 两种顺序及旧异常别名。

所有新增测试均为独立内存对象，复用无副作用测试构造 helper；不创建共享可变 repo，不访问外部进程。无真实 sleep、无限重试、skip、xfail 或真实 provider/API。线程 Event.wait / join 有上限，线程异常收集后在主线程断言。三处带理由 BLE001 注释只用于确保线程中的失败不会丢失，不吞掉错误。

原有 S/M diff 的角色、owner、队列、事件断言未被削弱。注意既有 unknown-worker 测试现在在 lease discovery 处抛异常，不等价于独立测完所有 Scheduler unknown-lease 入口；本轮补测未知 worker candidate 的无副作用拒绝，其他无效身份组合未穷举。

不创建 worktree、不切分支、不 stage/commit/merge/push，不修改 .git 配置，不改生产代码、配置、文档、fixtures、evals、既有日志。工具自动生成的忽略缓存未提交、未清理用户文件。

## 6. Test Execution Results

以下八条是用户要求的执行顺序。重复 suite 的 case 数不能累计为不同覆盖；0 error 表示无 collection/setup/runtime error 计数，正常断言失败归 failed。

| 顺序 | 实际命令 | Exit | Passed | Failed | Skipped | Error | 摘要 / pytest 耗时 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | .venv/bin/python -m pytest tests/agent_team/test_registry.py tests/agent_team/test_fencing.py tests/agent_team/test_lifecycle.py -q | 0 | 100 | 0 | 0 | 0 | 0.14s |
| 2 | .venv/bin/python -m pytest tests/agent_team -q | 1 | 317 | 6 | 0 | 0 | 4.27s；含本轮 58 项 |
| 3 | .venv/bin/python -m pytest tests/agent tests/session tests/execution -q | 0 | 363 | 0 | 0 | 0 | 30.27s |
| 4 | .venv/bin/python -m ruff check codeteam/agent_team codeteam/events.py tests/agent_team evals/week5/benchmark_scheduler.py | 1 | n/a | n/a | n/a | n/a | 首轮 3 个 BLE001，均为本轮验收测试；后续已说明并复验 PASS |
| 5 | .venv/bin/python -m mypy codeteam/agent_team tests/agent_team | 1 | n/a | n/a | n/a | n/a | 4 errors / 3 files，checked 22 source files |
| 6 | .venv/bin/python -m pytest -q | 1 | 1726 | 6 | 9 | 0 | 56.96s；普通沙箱 |
| 7 | .venv/bin/python -m pytest tests/sandbox -q -rs | 0 | 62 | 0 | 9 | 0 | 0.68s；逐项报告权限 skip |
| 8 | git diff --check | 0 | n/a | n/a | n/a | n/a | 无输出；另在验收中间及最终复核执行，均 exit 0 |

额外执行，不替代上述真实结果：

| 实际命令 / 环境 | Exit | Passed | Failed | Skipped | Error | 摘要 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| .venv/bin/python -m ruff format tests/agent_team/test_lifecycle_acceptance.py | 0 | n/a | n/a | n/a | n/a | 1 file reformatted，仅新增文件 |
| .venv/bin/python -m pytest tests/agent_team/test_lifecycle_acceptance.py -q（首轮） | 1 | 52 | 6 | 0 | 0 | 0.16s |
| .venv/bin/python -m pytest tests/sandbox -q -rs（审批授权） | 0 | 71 | 0 | 0 | 0 | 3.31s |
| .venv/bin/python -m ruff check codeteam/agent_team codeteam/events.py tests/agent_team evals/week5/benchmark_scheduler.py（补线程异常说明后） | 0 | n/a | n/a | n/a | n/a | All checks passed! |
| .venv/bin/python -m pytest -q（审批授权，最终版本） | 1 | 1735 | 6 | 0 | 0 | 59.09s |
| .venv/bin/python -m mypy codeteam/agent_team tests/agent_team（最终版本复核） | 1 | n/a | n/a | n/a | n/a | 仍为相同 4 项历史诊断 |
| .venv/bin/python -m pytest tests/agent_team/test_lifecycle_acceptance.py -q --tb=short（最终定向复验） | 1 | 52 | 6 | 0 | 0 | 0.14s，同六项失败 |

另实际执行 git status、rev-parse HEAD、diff --stat、diff --cached --stat、diff HEAD -- 三个类型债文件、git show HEAD:codeteam/agent_team/scheduler.py、git ls-files -s、shasum -a 256、文件只读 cat/sed/rg/nl/wc、uname -sm、date、.venv/bin/python --version。均是检查命令；不存在本轮 Git mutation。日志同名存在检查 test -e 返回 1，确认新增，不覆盖旧文件。

与 coder 数字对照：其 265 项 agent_team + 新增 58 = 323 项，本次 317 pass + 6 fail；其全量 1683 + 新增 58 = 1741 项，本次最终 1735 pass + 6 fail。这只是复验后的数量解释，不是为匹配数字调整测试；原有测试独立运行未出现失败。

## 7. Coverage / Test Limits

未运行 line/branch coverage 工具，不提供虚构覆盖率。Requirement Matrix 是需求行为证据，不等同代码百分比覆盖。

新增文件中 6 项失败各自经历首轮、模块、普通全量、授权全量、最终定向共 5 次运行，均稳定失败（每实例 5/5），没有“重跑直到变绿”。失败注入不是实际 OS signal delivery 测量，是同步精确注入 KeyboardInterrupt/SystemExit 的中断处理契约测试。

既有并发测试用例包含 complete/recovery 20 个重复参数和 claim/recovery 10 个重复参数；并不保证调度器每次都选择两种先后。本轮另用 Event 强制 stop/complete 双向先后，但未穷举所有机器调度或多进程交错。

## 8. Benchmark

状态：NOT_RUN（方案已设计）。未执行 benchmark_scheduler.py，无新 raw data、manifest、latency 或 throughput 结果。

W5_LIFECYCLE.md 具备：100/500/1000 worker、READY/BUSY 和 CLAIMED/RUNNING 比例、0/10/100% 失活、1/4/8 线程、5 warmup/30 measured 的计划；分离真实 perf_counter 与 FakeClock，指标分别为 heartbeat、scan、detection overshoot、恢复处理、factory/control plane、scheduling wait、错误接受/重复入队、event 保留成本。

数据出口：公开 snapshot/queue/runtime_records/events、transaction_id/event_index、generation/attempt/restart_attempts，以及 detect/recover/restart 独立调用可用于后续计时和正确性统计。接口可测不代表本次已测性能。

W5_SCHEDULER.md 正确标为 STALE_AFTER_LIFECYCLE_MIGRATION。旧脚本仅做显式 lease 迁移，不能证明 Day5 性能。周末执行前仍需新增生命周期 workload、raw sample/manifest 出口；当前旧脚本只聚合输出并会写 docs/benchmark/W5_SCHEDULER.md。其 git probes 缺 timeout/显式 shell=False、Barrier.wait 缺 timeout，是只读审核发现的既有实验 harness 待完善项（P3 / REVIEW_ONLY），本轮未运行或修改脚本。

## 9. Ablation

状态：NOT_RUN（方案已设计）。

已审核控制变量隔离：同 worker/同 generation 的 no-attempt fencing、独立 no-generation fencing、no candidate revalidation、split transaction、no timeout recovery、no restart budget；每对比较应保持拓扑/角色/时钟轨迹/预算/事件策略/线程数一致，保留中间状态与原始输入 token。

本轮不实现弱化生产防护的 adapter，不运行无界重启、不运行真实 LLM/API。不能声称降低故障率或带来百分比提升。

## 10. Failure Cases

现有 docs/failure_cases/W5_LIFECYCLE_FAILURE.md 的 F-W5-D5-01 至 12 已按对应测试审查：CLAIMED/RUNNING 失活、同代旧 attempt、旧 generation、stale candidate、预算、factory 异常、stop/迟到回调、事务准备回滚、多 sweep、claim/complete 竞争、wall clock、旧 ticket 均有本轮执行证据。

该文档列举的是防守场景，不是“所有故障模式已消失”。本轮新增下面 F01/F02 反证；仅写本日志，不越权修改 failure docs 或 DD。

## 11. Production Defects / P0-P3 Findings

P0：未发现。
P1：F01，reservation 中断未清理。
P2：F02，多级依赖未在恢复事务中传播到全部后继。
P2 / QUALITY_GATE：mypy 四项已确认历史债，见第 14 节，不等价于新增功能缺陷。
P3 / REVIEW_ONLY：第 8 节旧 benchmark harness 的复现材料与有界执行缺口，待周末准备，不作为已运行的性能失败。

### F01 / P1：预留事件投递中断遗留 RESTARTING

分类：PRODUCTION_DEFECT / RECOVERY_FAILURE / RESOURCE_LIFECYCLE。
来源：Day5 新增 lifecycle.py、registry.py。
位置：codeteam/agent_team/lifecycle.py:55；codeteam/agent_team/registry.py:281、389。
失败测试：A:test_restart_interrupt_cleans_matching_reservation 的 reservation_observer-KeyboardInterrupt / reservation_observer-SystemExit。

复现命令：

```bash
.venv/bin/python -m pytest tests/agent_team/test_lifecycle_acceptance.py -q -k restart_interrupt --tb=short
```

这是从已执行的最终定向命令提取的最小选择器；本轮实际完整执行了同文件全部 58 项。

前置与触发：
1. w1 generation1 持有 RUNNING A，在 FakeClock=15 时合法回收，A 重排，w1 FAILED。
2. 调 restart_worker；reserve 提交 RESTARTING、restart_attempts=1、restart_id。
3. WORKER_RESTARTING observer 抛 KeyboardInterrupt 或 SystemExit，factory 尚未执行。
4. 调用方捕获中断后读取组合快照。

预期：匹配 reservation 清理为 FAILED、restart_id=None，原 generation 与 Worker 对象不变，预算消耗一次，Task/owner/queue 保持已完成回收的状态，中断继续传播。

实际：中断传播，但 status=RESTARTING，restart_id 仍非空；generation=1、restart_attempts=1；factory 调用为 0。Task/owner/queue 未被破坏，但 Worker 没有正在运行的 factory，也不会被普通 timeout 扫描或 FAILED restart 路径接手。
断言位置：tests/agent_team/test_lifecycle_acceptance.py:434。
factory 阶段的两个中断参数均通过，证明不是所有中断都坏，而是 reservation 回调阶段缺口。

原因：reserve_restart 在提交后先同步投递 observer，再返回 ticket；异常发生于返回 ticket 之前。Lifecycle 对 BaseException 的清理只包住后续 factory，覆盖不到该路径。Registry observer 只隔离普通 Exception，不能承担中断后的 reservation 清理。

影响：长存活控制进程捕获中断后，worker 可停留在不可调度、不可自动恢复的状态；违反本日“中断清理匹配 reservation”。
建议 coder 在持有实际 ticket 的预留/投递边界补清理，必须重校验 reservation，不能用最新 lease 无条件改状态，也不能吞 KeyboardInterrupt/SystemExit。测试应继续保留 stopped/newer-ticket 不被中断清理覆盖的约束。
本轮未修生产代码。

### F02 / P2：反字典序依赖链留下 PENDING 后继

分类：PRODUCTION_DEFECT / CORRECTNESS_FAILURE / STATE_RECONCILIATION。
来源：历史 Scheduler 算法延续到 Day5 recovery/stop。git show HEAD 与工作树 diff 证实 _schedule_locked 单次 sorted 遍历逻辑并非本轮新写；不把它归为新文件缺陷。
位置：codeteam/agent_team/scheduler.py:642、656、669、816。
失败测试：A:test_exhausted_loss_blocks_all_descendants_in_one_transaction 的 timeout/stop × CLAIMED/RUNNING，共 4 组。

复现命令：

```bash
.venv/bin/python -m pytest tests/agent_team/test_lifecycle_acceptance.py -q -k exhausted_loss --tb=short
```

前置：有效 DAG Z -> M -> A，max_attempts=1；w1 claim Z，可选择保持 CLAIMED 或进入 RUNNING。
动作：timeout recovery 或 stop_worker 一次提交。
预期：Z FAILED，M/A BLOCKED，所有任务无 owner，queue 空；后继阻塞审计属于同次终态恢复事务。
实际：Z FAILED、M BLOCKED、A PENDING；owner/queue 已撤销正确，attempt 保持 1。A 没有对应 blocked 事件。断言位置 A:352。
这不是旧任务被重新执行，而是终态依赖结算不完整。额外显式 schedule 可以继续传播，但调用方不应被要求按依赖深度隐式轮询来补完一次恢复事务。

原因：按节点 ID 字典序只扫描一遍，检查 A 时 M 仍 PENDING，稍后才把 M 置 BLOCKED，不再回访 A。直接依赖测试只用 A->B，未触发这个顺序问题。
影响：合法 DAG 的相同依赖关系因命名不同而得到不同终态快照，未来 Team completion/durable reconciliation 可能保留永久等待节点。
建议 coder 在同一事务中采用拓扑序或有界传递闭包传播 BLOCKED，避免依赖 ID 排序；保留原子审计/队列约束。本轮未修生产代码。

## 12. Design Decision Verification

DD-W5-05 当前 Status=IMPLEMENTED_WITH_TESTS; pending independent tester acceptance，未夸为实测性能 SUPPORTED。
单一状态权威、强制 token、共享锁事务、锁外 factory/observer 的设计有确定性行为证据；generation/attempt 分离与多 sweep 去重测试通过。

本轮 Evaluation：**PARTIALLY_SUPPORTED**，而不是 SUPPORTED。
原因：F01 反证完整中断清理保证，F02 反证全部依赖的原子终态结算；Performance/Ablation 均 NOT_RUN，相关收益只能 INSUFFICIENT_EVIDENCE。
源 DD 未修改；coder 后续应根据独立验收修正完成状态或补修复证据。

## 13. Acceptance

| 维度 | 状态 | 判断 |
| --- | --- | --- |
| 功能 | FAIL | 核心 happy path 多数通过，但 reservation 中断和多级依赖结算违反要求 |
| 并发一致性 | PARTIAL | 所测 claim/recovery、complete/recovery、多 sweep、stop/factory、stop/complete 均保持 owner/队列一致；F01 暴露回调中断清理漏洞，不能完整签收 |
| 安全 | PASS（限定范围） | 已测 attempt/generation/runtime fencing、角色 gate、STOPPED 不复活、Mailbox 不越权、合成 secret 审计；不扩展成 OS/外部副作用安全 |
| 回归 | FAIL（全量门禁） | 相关 363 项和原有测试通过，但完整套件有 6 项必须保留的生产缺陷失败 |
| 静态检查 | PARTIAL | Ruff 最终 PASS；mypy 历史 4 项未解决 |
| Docker 环境 | PASS（授权复验） | 71 项真实运行，普通沙箱 9 项权限 skip 单独保留 |
| Benchmark | NOT_RUN | 本日按授权仅设计审阅 |
| Ablation | NOT_RUN | 无消融数字或收益结论 |
| Day5 总体 | 未通过 | 不建议作为完成基线进入 Day6 实现 |

## 14. Regression / Static Classification

mypy 两次实际输出相同：

```text
codeteam/agent_team/dag.py:197: error: Need type annotation for "dependents"  [var-annotated]
tests/agent_team/test_models.py:107: error: Argument "role" to "AgentInfo" has incompatible type "str"; expected "AgentRole"  [arg-type]
tests/agent_team/test_models.py:110: error: Argument "status" to "AgentInfo" has incompatible type "str"; expected "AgentStatus"  [arg-type]
tests/agent_team/test_dag.py:86: error: Argument "status" to "TaskNode" has incompatible type "str"; expected "TaskStatus"  [arg-type]
Found 4 errors in 3 files (checked 22 source files)
```

| 来源 | 数量 / 文件 | 核对方式 | 是否阻塞 |
| --- | --- | --- | --- |
| Day5 新增/修改生产文件的新类型问题 | 0 项报告 | 检查完整 mypy 输出 | 未发现此类新增诊断，不代表未启用 strict 的全部函数已证明类型安全 |
| 本轮新增验收测试 | 0 项报告 | test_lifecycle_acceptance.py 纳入 checked 22 files | 无新增类型阻塞 |
| 历史生产类型债 | 1，dag.py:197 var-annotated | git diff HEAD -- 该文件为空；读取实际行；与 coder 基线记录交叉验证 | 包级 mypy 门禁不通过；不是 Day5 新增错误 |
| 历史测试类型债 | 3，test_models.py 两处与 test_dag.py 一处 arg-type | 同上，文件与 HEAD 完全一致；故意输入非法枚举的测试写法未兼容类型检查 | 需后续修测试类型表达，不得删运行时拒绝断言 |
| 缺 stub / 第三方 import-chain | 0 | 本次输出没有这类诊断 | 不可套用 Week4 的历史失败分类 |

本轮没有重新构造旧 worktree 运行旧版本 mypy，历史归类依据当前诊断、对应文件与 HEAD 一致，以及已记录基线交叉核对；未把所有失败默认推给历史债。

Ruff 首轮新增 3 项 BLE001（A:462、476、526）。为了把线程 AssertionError/KeyboardInterrupt/SystemExit 交回主线程，按现有项目模式添加理由注释；errors 仍在主线程 assert == []，没有降低断言或隐藏失败。最终相同完整 Ruff 命令 All checks passed!。

## 15. Risks and Limitations / Docker Skip Audit

普通沙箱的统一 skip 原因：
permission denied while trying to connect to the docker API at unix:///Users/sqlee/.colima/default/docker.sock

被跳过的九项均在 tests/sandbox/test_docker_runner_integration.py：

| 行 | 测试 | 普通沙箱未验证范围 | 授权复验 |
| --- | --- | --- | --- |
| 205 | test_read_workspace_succeeds_when_docker_available | /workspace 读取 | PASS |
| 222 | test_verification_toolchain_is_available_when_docker_available | verification toolchain | PASS |
| 242 | test_real_verification_preflight_reports_image_and_toolchain_metadata | 实际 preflight metadata | PASS |
| 264 | test_write_workspace_succeeds_when_docker_available | workspace 写入 | PASS |
| 283 | test_unmounted_host_secret_is_not_readable_when_docker_available | 未挂载合成 host secret 拒绝 | PASS |
| 310 | test_network_is_blocked_when_docker_available | 默认网络隔离 | PASS |
| 335 | test_root_filesystem_write_fails_but_workspace_write_succeeds | rootfs 只读 | PASS |
| 360 | test_verification_profile_has_read_only_source_and_writable_tmp | source 只读/tmp 可写 | PASS |
| 389 | test_docker_socket_is_not_mounted_when_docker_available | Docker socket 不挂载 | PASS |

按照工具审批机制实际重新执行了 Docker suite 和全量 suite。没有 chmod socket、宿主机执行 fallback、关闭隔离、拉取镜像或伪造结果。最终授权全量无 skip；普通沙箱结果不能被覆盖为全绿。

明确未覆盖/未执行：
- OS Worker process/thread kill、WorkerExecutor、Runtime/工具真实 Team-token 集成、跨进程持久恢复、Team Session resume、外部副作用 exactly-once。
- 真实 LLM/API、网络分区、付费调用、benchmark/ablation、长时压力或泄漏测量。
- factory 时间抢占、任务 progress deadline、审计 retention 上限。同步 factory 永不返回是已声明限制，但不是 F01 未清 reservation 的免责理由。
- 所有 arbitrary signal 位置、所有嵌套 observer reentry 与全量调度排列未穷举；本轮中断是精确位置的同步异常注入。
- 用户指定参数预算的主要非法组合与实际状态边界已覆盖；未对所有模型字段做穷举/property-based 测试。
- 既有 S/M 和 benchmark harness 部分 Barrier.wait 没有 timeout；新增测试均有界，未越权重构已有代码。
- Docker 部分是回归边界证据，不把它推导为 Day5 执行器能力已经接通。

## 16. Artifacts / Input Fingerprints

本轮新增测试最终 SHA256：
```text
415c3bf2e0cf2a099aabca1b8ecedab3f24bb10c67fb17df46228fa9d7bdb599  tests/agent_team/test_lifecycle_acceptance.py
```

36 个原有直接输入的首次 SHA256，最终复核全部一致：
```text
28ec41cba8fc8757c58ac6fdcd7a74f1724c1a33486c5b4e614b51250f1c4922  .codex/AGENTS.md
09d56dd38c8d7446092fb5d6707aff67c2c50d0e06ff89b794ff57305654327d  prompt/test_Agent.md
8c4db7af5cc95792ed8bd0f8883dd9adfa64d9d7ea6968c43743dca2f5e4ecdf  learning-plan/week5/week5_plan.md
a58ac73d30138bd98ad55256fff27f39e5bafeec0961a43462cdf026853a248f  learning-plan/week5/day5.md
5c138a216c496a1d8bb2f274cd343369661f465942d7344f7dea07bfd8fd4b98  codeteam/agent_team/__init__.py
f0b63411b14bddf998922b69f47f2978148feec280a45b5fb832bcb10d5eb671  codeteam/agent_team/contracts.py
3f510e8bc63fa9fe625be8bf199a654b16f32532caf2fd58844d16f4df8dad38  codeteam/agent_team/coordination.py
9a41cdab8925e054b5e13427382503053dd5e97fd6c63b07b4d7181c7119f4d8  codeteam/agent_team/dag.py
6345c57d0295d87766808cf544add2e72de4fba4675c1317668b2397f23540fd  codeteam/agent_team/lead.py
5c5bd5ee837f189bc0c59a56458d173cd674759d18f321885a2a55e26c3256a9  codeteam/agent_team/lifecycle.py
7a89e795a0017ca9754272f16da57ad030963e8835a15e825d950c8a052d5c2f  codeteam/agent_team/mailbox.py
dd6cafff7d488f3ff9e8227d56e38148ab44980e13dfb9029fe7b50ed6090317  codeteam/agent_team/models.py
835c20b38bbd3870c02866990af5d465620f29c34c3685e2c7a7699d87666221  codeteam/agent_team/registry.py
1001aaf5b4e4f2ef2096e84cb55ec351518708719b4b7cff0a16c35b88d3a25b  codeteam/agent_team/scheduler.py
f352b86f7229e9452b6fd72eb9bdaf4e6f9b5abf540b3455f9b3d0559d393b0c  codeteam/agent_team/worker.py
02ad4e9c2e3e0b4d6c96c2e336048c462ea6a2725914ef03c86104fb1948f843  codeteam/events.py
01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b  tests/agent_team/__init__.py
fed393b77cf77a318abdc4fb508db5af331ac68792346925f71f45948f3f9693  tests/agent_team/test_dag.py
7eeeac0b3fb17b04099855246c8dfe500ba12c1eea97e42cb18fb2f864733966  tests/agent_team/test_fencing.py
0115ceb925785e2f50c36044f8f8c771c8de625f7d866e0354999b82515480c0  tests/agent_team/test_lead.py
2e55f7a659cc5445f9c34a6044eff09528a7b3e2925badd740defee7e6333b25  tests/agent_team/test_lifecycle.py
20505561e2c6b1f8d7650b049f563a0bf341f4f038518f5b4532e47450050311  tests/agent_team/test_mailbox.py
ff22deac7f17b8a9e88545b3f79fb9b33a04e7205cd8904bb96e76dd3da86c60  tests/agent_team/test_models.py
2b625b4382ca7fb78578b03b70566f10e16a8715fe4d0411b84223ada4b91dd8  tests/agent_team/test_registry.py
f80bd4740e188d76b9c55d24e777972d6964a7350687514a060eaf83e9b71a4c  tests/agent_team/test_scheduler.py
7027bf1b977904bbd2e1c3c6693a6eb1ce8b8ba69077ba61df2d24d1219b7016  tests/agent_team/test_worker.py
8787f999271c500e2e11867f237d7c48974efdbdd3406cc32bf35e5e59ca8bc4  docs/design_decisions/DD-W5-05.md
c2768bd4d54553b02cf76c99b3694a7398b33e333de93ce28cfa871a787969ac  docs/failure_cases/W5_LIFECYCLE_FAILURE.md
eeedfdd43a85d143617ecc4777a9dde6b3042817241df09f0eb84149cfc2718e  docs/benchmark/W5_LIFECYCLE.md
93cbaa829fa42d77c43d1f68755654e306a46af69769d03674b3a50cd6b57af1  docs/benchmark/W5_SCHEDULER.md
32b7ed65ba68746f782a296de9c75a59d1cb3bbe455230f7334febcd24ccfb24  evals/week5/benchmark_scheduler.py
e3c7523a74cc48a8aa6142c7963e3fd2438eb3fc2ea1cc6f5360168349d974a0  test_log/2026-08-31_week5_day5_lifecycle_implementation_log.md
5c2e793bf6a98be5e39e43b2fbd3ac5851d7015c8745a8f747c147f960290607  pyproject.toml
5f679eaef68016eebe3533f218b9db24ff44244451395643f45ab2d2518c51b6  pytest.ini
ca2051d116726c22f164d0b8392e4eeef44036786dea650d99cb8122a582553f  requirements.txt
0bac135ed14f23277d67d3244e9d886186005fdb1b8c4d06f0b0547284ca9c2c  requirements-dev.txt
```

没有创建 commit，无测试 commit SHA；没有 merge 或 push。所有 coder/user 原有修改保留。

## 17. Interview Evidence

可使用的客观证据：
- 同 worker 同代旧 attempt 的 start/complete/fail 在新 CLAIMED/RUNNING 场景被拒，业务状态不变且只记录拒绝审计。
- 注入 draft event append 后异常，八种操作的跨对象业务、队列 membership 和事务审计计数回滚。
- factory 被 Event 暂停时，另一 worker 可完成两项任务并提交 heartbeat，之后才允许新 generation 发布。
- 同时明确承认独立验收发现了 reservation 中断和依赖传播缺口，不能用原有 265 个绿色测试替代边界审查。
- 不宣称已有吞吐优势、真实进程恢复或分布式 exactly-once。

## 18. Final Conclusion / Next Steps

Day5 独立验收执行完成，产品验收未通过。必须保留当前 6 个失败参数实例，不 skip/xfail，不修生产代码迎合本轮结论。

建议顺序：
1. coder 修 F01：reservation 回调中断时清理实际匹配 ticket，保护 STOPPED/newer reservation，不吞中断。
2. coder 修 F02：同一事务内完成多层 BLOCKED 传播，保持审计与所有权一致。
3. 明确修复或单独登记接受 mypy 的 4 项历史债；静态门禁未全绿必须继续明示。
4. 重新执行本轮定向、agent_team、相关回归、全量和静态命令；环境受限时继续按审批机制复验 Docker。
5. 修复并复验后再进入 Week5 Day6 TaskStore/Session 集成，避免把当前不完整终态/悬挂 reservation 序列化为 durable state。
6. Benchmark/Ablation 留周末，在固定修复版本上补 raw samples/manifest，不能沿用过期 Scheduler 数字。

本日志是新增文件，不覆盖或追加 2026-08-31 的 coder implementation log。

