# W4D3 独立验收报告：Error Classification + Retry / Recovery

**日期**: 2026-08-19
**角色**: Independent Evaluator（Test / Evaluation Agent，验收模式）
**分支**: week4 @ 4db29e5（含 Coder 未提交的 W4D3 工作区改动）
**权限**: 只读审查 + 执行测试 + 本报告唯一写入路径
**环境**: Python 3.11.7（.venv），pytest 9.x，ruff 通过

---

# 1. Evaluation Summary

W4D3 交付物（codeteam/failures/ 四文件 + orchestrator 集成 + events + state.py 修复 + 7 个测试文件共 173 个新测试）通过了 9 项验收中的 8 项完整判定与 1 项有条件判定：

- **验收 1~8：PASS**（其中验收 1 附证据链分层说明，验收 4 的 I6 附 Day 4 已知限制）
- **验收 9：PASS**
- **全量回归：987 passed / 6 skipped（与基线完全一致），ruff 0 error**
- **生产缺陷：0 个**（Manager 疑点 A~E 全部有结论，无需阻塞修复）
- **Design Decision：INSUFFICIENT_EVIDENCE**（DD-W4-D3-01 未撰写，周度数据未到位，符合节奏）

# 2. Capability Mapping

```
Module: Error Classification + Retry / Recovery（W4D3）
Primary:  Agent Harness — Error Handling / Recovery Orchestration
Secondary: Safety（SECURITY Fail Closed + 纵深防御）、
           Observability（error./recovery./retry. 事件）、
           Evaluation（50 Case corpus 数据出口）
What was proven:
  1. 8 条 Required 映射：classifier 级全覆盖 + 6/8 条有集成级行为证据
  2. 7 个 Runtime Invariant：I1~I7 断言真实，无一处靠 docstring 自述
  3. 事件时间线：独立重放验证（非仅测试自证）
  4. 分层正确：Unit（raw→AgentFailure）/ Integration（AgentFailure→Orchestrator 真实执行）分离
```

# 3. Repository Inspection

```text
Technical Stack: Python 3.11 + pydantic；.venv/bin/python
Test Framework:   pytest（pytest.ini: testpaths=tests, norecursedirs=tests/fixtures）
Target Module:    codeteam/failures/{models,classifier,recovery,retry}.py
                  集成点: codeteam/agent/orchestrator.py（_execute_with_recovery/_TerminalFailure/注入点）
                          codeteam/events.py（9 个新事件类型）
                          codeteam/task/state.py（3 条 PAUSED 转移，缺陷4）
Target Tests:     tests/failures/（6 文件）+ tests/agent/test_recovery_integration.py
Public API:       ErrorClassifier.classify(error,stage,operation,task_id,attempt,...) → AgentFailure
                  RecoveryPolicy.decide(AgentFailure) → RecoveryAction
                  RetryPolicy.decide(AgentFailure, elapsed) → RetryDecision
Existing Tests:   173 个新测试（failures 110 + fault_injection 54 + recovery_integration 9）
Fixtures:         _FakeInspector/_FlakyPlanner/_RecordingSleeper/_FakeStatusError（全部假对象）
Missing Interface: 无（classifier/policy/retry 三接口齐全）
Implementation/Requirement Differences:
  - REPAIR/REREAD/COMPACT 等恢复的执行接线留 Day 5（代码注释引用「明确不做清单」，
    但该清单尚未以文档形式存在——day3.md §一百三十 Checklist 第 5422 行要求写进报告）
  - retry_scheduled 事件沿用 Week1 下划线命名，与 W4D3 新事件的点号命名风格不一致
Git Status:       4db29e5 + 未提交（MM orchestrator / M events / A+AM failures / M state.py / M day3.md / ?? tests×2）
Applicable Rules: AGENTS.md（.venv、pytest.ini 排除 fixtures、无 skip/xfail 掩盖）
```

# 4. Requirement Coverage

| ID | 验收要求 | 状态 | Evidence（测试名） |
|----|---------|------|--------------------|
| A1 | 8 Required 映射真实覆盖 | PASS | 见 §13 验收矩阵逐条 |
| A2 | T09~T18 Recommended；T11/T12 在 corpus | PASS | C01/C02 + classifier/policy 单测 |
| A3 | 50 Case 分布 + spot-check + 可 import | PASS | 程序化分布断言 + 20/50 spot-check |
| A4 | 7 Invariant 断言真实性 | PASS | I1~I7 见 §10 逐条 |
| A5 | 事件时间线重放 | PASS | 独立重放（非仅测试） |
| A6 | Unit/Integration 分层 | PASS | 目录与断言方式分离 |
| A7 | 无 sleep/无外部 API/安全 0 调用 | PASS | grep 审计 + 假对象确认 |
| A8 | 987/6 + ruff 0 | PASS | 实测一致 |
| A9 | 周度节奏 | PASS | 无评测脚本/无 SUPPORTED 声明 |
| RB | 疑点 A~E | 逐条结论 | 见 §12 |

# 5. Tests

- tests/failures/__init__.py（空）
- tests/failures/fault_cases.py — 50 Case corpus（数据，非测试）
- tests/failures/test_models.py — 15 项：枚举数量契约、cause 序列化排除、T17/T18
- tests/failures/test_classifier.py — 17 项：8 Required + stage 敏感性 + T09/T10/T17/T18
- tests/failures/test_recovery_policy.py — 8 项：SECURITY 硬 STOP、T14、一致性守卫、透传
- tests/failures/test_retry_policy.py — 13 项：退避公式、Retry-After、双预算、jitter 确定性
- tests/failures/test_fault_injection.py — 54 项：4 corpus 契约 + 50 参数化
- tests/agent/test_recovery_integration.py — 9 项：真实行为断言

# 6. Test Execution Results

```text
命令与实测结果（全部实际执行）：

.venv/bin/python -m pytest tests/failures -q                     → 110 passed
.venv/bin/python -m pytest tests/agent/test_recovery_integration.py -q → 9 passed
.venv/bin/python -m pytest tests/failures/test_fault_injection.py -q   → 54 passed
.venv/bin/python -m pytest -q                                    → 987 passed, 6 skipped (66.50s)
.venv/bin/python -m ruff check codeteam/failures codeteam/agent/orchestrator.py \
    codeteam/events.py codeteam/task/state.py tests/failures \
    tests/agent/test_recovery_integration.py                     → All checks passed!

skip 明细：6 条全部为 tests/sandbox/test_docker_runner_integration.py
「Docker CLI is not installed」——Week3 Docker 能力性跳过，与 W4D3 无关（确认即可，未动）。

旧的失败测试 test_planner_exception_yields_failed_not_raise 单独复跑 → 1 passed
（缺陷1修复生效：闸门 reason 经 source_type 保留异常类型名）
```

# 7. Coverage

```text
pytest-cov 未安装（项目未配置）→ 覆盖率 NOT_VERIFIED
按任务要求：覆盖率仅为辅助证据，不解释为「模块设计有效」。
本轮验收以行为断言与全量回归为主要证据。
```

# 8. Benchmark

```text
不执行（周度集中，用户已定节奏）。
数据出口完备性评估（供周度只读执行）：
- 50 Case corpus：FAILURE_CASES 顶层 list + FailureCase 六字段 dataclass，可直接 import ✓
- Classification/Recovery Accuracy：expected_category/code/action 与 classifier 输出可直接对比 ✓
- Unnecessary Retry：expected_retryable vs RetryDecision.should_retry 可对比 ✓
- Unsafe Retry：SECURITY 类 case（S01~S06）的 expected_retryable=False + policy 实际决策可交叉验证 ✓
- Typed vs Generic Retry Ablation：corpus 输入与 AgentFailure 字段足以支撑 runner 构造 ablated 变体 ✓
结论：数据出口满足周度只读执行要求。
```

# 9. Ablation

```text
不执行（周度集中）。
与 Benchmark 同口径评估：corpus + AgentFailure/RetryDecision 字段
足以支撑「Typed Recovery vs Generic Retry」的只读执行。
```

# 10. Failure Cases

```text
无新的生产 Failure Case（987 全绿）。
需要记录的「已知限制」2 条（非缺陷，见 §15）：
K1: VERIFYING 无 PAUSED 转移 + execute_plan_step 无 KeyboardInterrupt 处理
    （Day 4/5 接线范围，见疑点 A 结论）
K2: REPAIR/REREAD/COMPACT 恢复执行未接线（代码自注释 Day 5 范围）
```

# 11. Production Defects

```text
0 个。Manager 疑点清单中的「缺陷4越权修改」经复核判定为
I6 所必需的最小修改（详见 §12-A），不构成缺陷。
```

# 12. Manager 疑点清单结论（A~E）

## A. 缺陷4越权修改（task/state.py PAUSED 转移）

**结论：修改最小且为 I6 所必需；I6 验证/修复阶段缺口属「Day 4 范围，记录为已知限制」。**

(1) 最小性与必要性：
- 改动为 3 行（CREATED/INSPECTING/PLANNING 各加 PAUSED 出口），无其他附带修改 ✓
- 必要性成立：run() 管线为 CREATED→INSPECTING→PLANNING→READY，Ctrl+C 可发生于任意点。
  若三态无 PAUSED 出口，闸门 `_pause()` 的 transition_to(PAUSED) 会抛
  InvalidTransitionError——I6 在该阶段不成立。READY/IMPLEMENTING 已有 PAUSED（历史存在）。
- 结论：超出原授权属实，但属于 I6 的正确实现所必需，且已最小化。建议 Manager 事后追认授权。

(2) I6 完整性缺口（独立验证结果）：
- 事实 1：TASK_TRANSITIONS 中 VERIFYING → (COMPLETED, IMPLEMENTING, FAILED)，无 PAUSED ✓（确认）
- 事实 2：execute_plan_step 全函数无 KeyboardInterrupt 处理（grep 确认仅 run() 与
  _execute_with_recovery 两处有 KeyboardInterrupt 分支）✓（确认）
- 事实 3：execute_plan_step 当前无任何生产调用方（grep 确认）✓（确认）
- 推论：Ctrl+C 若发生在验证/修复阶段，KeyboardInterrupt 将向调用方传播；
  即使调用方想 PAUSED，VERIFYING→PAUSED 也会抛 InvalidTransitionError。
  当前该路径不可达（无调用方），故不构成可复现失败。
- 判定：不按缺陷报告（无法复现 + 执行期恢复接线整体属 Day 4/5 范围）。
  标注「Day 4 范围，记录为已知限制」，并要求 Day 4/5 接线时补齐：
  VERIFYING→PAUSED 转移 + execute_plan_step 的 KeyboardInterrupt 分支。
- 附带发现：PAUSED 恢复面仅 (READY, IMPLEMENTING)，无 PLANNING——
  规划期被暂停的任务无法恢复到规划中（Day 4 Session Resume 范围）。

## B. 架构边界声明（PolicyDecision/ApprovalDecision/VerificationStatus 走结果路径）

**结论：PARTIALLY_SUPPORTED（架构事实成立；I1/I2/I5 的「集成级」no-retry 证据为间接证据链）。**

- 架构事实核查（成立）：
  - PolicyDecision 由 execution/command_policy.py、policy_rules.py 以返回值产生，
    无 raise 路径 ✓
  - ApprovalDecision 由 execution/approval.py 以结构化结果产生 ✓
  - VerificationStatus 由 verification/service.py 以结构化结果产生 ✓
- 证据链（真实存在且各自有测试）：
  ① classifier 单测：三者 → SECURITY/TEST 类 + retryable=False（S01/S02/V01~V05）
  ② RecoveryPolicy 单测：SECURITY 类硬编码 STOP，不随 attempt/recommended 改变（T14）
  ③ RetryPolicy 单测：not_retryable → 拒绝重试（纵深防御）
  ④ Week3 执行层回归：test_deny_does_not_call_runner（runner.calls==0）、
     command_policy/approval 的 deny 用例（runner.calls==[]）
  ⑤ I3 端到端：同一 SECURITY→STOP 分支经 run() 全路径验证（planner.calls==1、
     sleeper==[]、无 retry.* 事件）
- 不足：W4D3 自身没有「PolicyDecision.DENY / ApprovalDecision.DENIED /
  VerificationStatus.FAILED 流经 Orchestrator 恢复路径时 retry=0」的集成测试。
  原因合理（这些是结构化结果、不在异常恢复层），但「集成级」表述应降级为
  「classifier+policy 单测 + Week3 执行层回归 + I3 端到端」的间接证据链。
- 对验收 1 的影响：policy deny→stop / approval deny→stop 两项的充分证据 =
  ①+②+④（跨层互补），判定 PASS 但证据性质为「间接集成」，Day 5 接线执行
  结果路径后应补直接集成测试。

## C. V01/V02 不可区分声明

**结论：声明准确。**

- 事实：V01 与 V02 的 raw_error 均为 VerificationStatus.FAILED，classifier 均映射
  TEST_FAILED / REPAIR / retryable=False（实测 + corpus 注释明示「回归失败：结构化信号同为 FAILED」）
- 影响评估准确：classifier 仅凭结构化信号无法区分「目标断言失败」与「回归失败」；
  区分信息只在调用点上下文（target vs regression request），当前未传入 classifier。
  两类失败都会得到 REPAIR 建议——回归失败可能触发不必要的修复尝试。
- 该限制已在 corpus 中以注释形式诚实记录，未掩盖。

## D. 缺陷1/2/3 修复真实性（回归验证）

**结论：修复真实且未引入新问题。**

- 缺陷1（闸门 reason 保留异常类型）：独立复跑旧测试
  test_planner_exception_yields_failed_not_raise → 1 passed。
  reason 格式实测含 code + message + 终态原因 + source_type ✓
- 缺陷2（stage 级消息分类）：corpus 50 条中仅 2 条 UNKNOWN（M10 malformed provider
  response、V05 INCONCLUSIVE——均为 spec 有意 fail-closed 的兜底），48/50 落具体 code。
  Coder 声称的「31/50 不再落 UNKNOWN」方向正确（消息型 stage 分类覆盖 CONTEXT/PATCH/
  TOOL/GIT/SESSION/APPROVAL 约 25+ 条），精确数字无法复算（无改造前基线），不追究。
- 缺陷3（终态原因入 reason）：test_retry_budget_exhausted_fails_task 断言
  "max_attempts_exhausted" in result.error ✓
- 回归：全量 987 passed / 6 skipped 与基线完全一致，ruff 0 error ✓

## E. 测试质量审计

**结论：未发现 skip/xfail 掩盖、断言降级、docstring 与行为不符、假对象失效。**

- skip/xfail：tests/failures/* 与 test_recovery_integration.py 中 grep 结果为零 ✓
- 真实 sleep：零（仅 test_retry_policy.py docstring 提及；_RecordingSleeper 记录不睡）✓
- 外部 API/网络：零 ✓
- Security 零调用断言：test_sandbox_unavailable_never_retries（planner.calls==1、
  sleeper==[]、无 retry.* 事件）+ Week3 执行层 runner.calls==0/[] ✓
- case_id 唯一性断言：test_case_ids_are_unique 真实存在 ✓
- 字段完整性断言：test_failure_case_fields_match_weekly_export_contract 真实存在 ✓
- docstring 与行为：逐文件抽读比对一致（例如「planner.calls == 2 且 sleeper 被调用
  1 次」与实现事实相符）
- 时间依赖风险排查：jitter 测试用 seeded Random ✓；纯计算测试阈值 1s 容差极大 ✓；
  唯一潜在弱断言为 test_many_decisions_take_no_sleep_time（墙钟 <1s），
  1000 次纯计算实测毫秒级，flaky 风险极低（记为 exploratory 观察）
- 备注：TestRecoveryLoopDirect 直接调用私有方法 _execute_with_recovery（I4/I5 的
  集成表达）——因对应阶段无生产调用方，属当前架构下的合理选择，但应在 Day 5
  接线后升级为公共路径测试。

# 13. Acceptance

| 验收项 | 结果 | Evidence / Test |
|--------|------|-----------------|
| 1. 8 Required 映射真实覆盖 | **PASS**（附证据分层说明） | 见下表 |
| 2. T09~T18；T11/T12 在 corpus | **PASS** | C01/C02 + test_classifier/test_recovery_policy/test_retry_policy |
| 3. 50 Case 分布 + spot-check + 可 import | **PASS** | 分布程序化断言 ✓；20/50 spot-check 全一致 ✓；import ✓ |
| 4. 7 Invariant 断言真实性 | **PASS**（I6 附 K1 限制） | §10 逐条 + 独立重放 |
| 5. 事件时间线重放 | **PASS** | 独立重放（§10 实测序列） |
| 6. Unit/Integration 分层 | **PASS** | 目录分离 + 真实行为断言（planner.calls==2） |
| 7. 测试工程约束 | **PASS** | grep 审计零违规 |
| 8. 全量回归 987/6 + ruff 0 | **PASS** | 实测一致（66.50s） |
| 9. 周度节奏遵守 | **PASS** | 无评测脚本/无 SUPPORTED 声明/corpus 仅正确性测试 |

## 验收 1 逐条（8 Required 映射）

| 映射 | Classifier 单测 | Orchestrator 集成 | 判定 |
|------|----------------|-------------------|------|
| rate limit→retry | test_rate_limit_maps_to_retry | test_rate_limit_retries_then_succeeds（planner.calls==2, sleeper 1 次） | PASS |
| model timeout→retry | test_model_timeout_maps_to_retry | test_model_timeout_retries_then_succeeds（planner.calls==2） | PASS |
| patch mismatch→reread | test_patch_check_failed_maps_to_reread | test_patch_mismatch_never_retries_same_patch（无 retry.scheduled、sleeper==[]） | PASS |
| test fail→repair | test_test_failed_maps_to_repair | test_verification_timeout_repairs_not_retries（REPAIR 变体；纯 FAILED 无集成测试，见 B） | PASS |
| policy deny→stop | test_policy_denied_maps_to_stop | 无 W4D3 集成测试；证据=classifier+policy 单测+Week3 runner.calls==0（见 B） | PASS（间接集成） |
| approval deny→stop | test_approval_denied_maps_to_stop | 同上（见 B） | PASS（间接集成） |
| sandbox unavailable→stop | test_sandbox_unavailable_maps_to_stop | test_sandbox_unavailable_never_retries（planner.calls==1、sleeper==[]） | PASS |
| Ctrl+C→PAUSED | test_keyboard_interrupt_maps_to_pause | test_keyboard_interrupt_pauses_not_fails（status==PAUSED、task.paused 事件、sleeper==[]） | PASS |

Coder 声称「classifier 8 条 + 集成 5 条」：classifier 层实际 9 条测试（8 Required +
retry-after 提取）；集成层实际 9 条测试（4 条 run() 路径 + 2 条直接 _execute_with_recovery
+ 事件时间线 + 预算耗尽 + reason 契约）。声称方向正确，计数偏保守。无一处仅靠 docstring 自述。

# 14. Regression

```text
Full suite: 987 passed / 6 skipped —— 与 Manager 基线完全一致，无低于基线项。
旧的失败测试（test_planner_exception_yields_failed_not_raise）已转绿。
ruff: All checks passed!（0 error）
Benchmark/Ablation Regression: 不适用（周度未执行）
```

# 15. Risks and Limitations

```text
已知限制（非缺陷）：
K1: VERIFYING 无 PAUSED 转移 + execute_plan_step 无 KeyboardInterrupt 处理。
    当前无生产调用方、不可复现失败。Day 4/5 接线时需补齐（疑点 A）。
K2: REPAIR / REREAD / COMPACT / RETRIEVE 等恢复动作的执行接线留 Day 5。
    当前这些动作的集成表现为「RECOVERY_STARTED 事件 + _TerminalFailure」。
    代码注释引用「明确不做清单」，但该清单尚未以文档形式落盘
    （day3.md Checklist 第 5422 行要求写进报告）——文档追溯性缺口。
K3: 恢复面语义：PAUSED 只能恢复到 READY/IMPLEMENTING，无 PLANNING（Day 4 范围）。

Observations（非缺陷）：
O1: retry_scheduled 事件沿用 Week1 下划线命名，与 W4D3 新事件点号命名不一致。
O2: RECOVERY_COMPLETED / RECOVERY_FAILED 事件类型已定义但无发射方（与 K2 一致，Day 5）。
O3: UNKNOWN 的 category 为 TOOL（_SIGNALS 表）——spec 未规定 UNKNOWN 类别，
    不影响行为（fail closed→STOP），但语义上「未知错误归 TOOL 类」略显牵强。
O4: TOOL_TIMEOUT 定为 transient=True + retryable=False + STOP，
    与 Recovery Matrix「Context-dependent/CLASSIFY」的 v1 简化（保守选择，可接受）。
O5: GIT_WORKTREE_CONFLICT 定 STOP，与 Matrix「RECOVER」的 v1 简化（代码注释引用 §七十八）。

Test limitations:
- I4/I5 集成表达经私有方法 _execute_with_recovery（无生产调用方），Day 5 应升级。
- 无覆盖率数据（pytest-cov 未配置）。
- 样本量：50 Case 为开发集（Development Set），非 held-out；周度评测不得宣称 unseen。
```

# 16. Artifacts

```text
本报告：test_log/2026-08-19_week4_day3_test_log.md
被测工件（Coder 产出，未改动）：
  codeteam/failures/{__init__,models,classifier,recovery,retry}.py
  codeteam/agent/orchestrator.py（集成）
  codeteam/events.py（9 个新事件）
  codeteam/task/state.py（3 条 PAUSED 转移）
  tests/failures/（6 文件）
  tests/agent/test_recovery_integration.py
```

# 17. Interview Evidence

```text
可支撑的客观证据（全部实测）：
- 50 Case Fault Injection corpus：分布与 day3 §六十九 完全一致，20/50 spot-check 与
  Recovery Matrix 零偏差，48/50 落具体错误码（仅 2 条 spec 有意 fail-closed）
- Rate limit 恢复端到端：planner 真实第二次调用 + sleeper 真实等待（RecordingSleeper 记录）
  + 5 段事件时间线可重放
- 安全不变量三层纵深防御：classifier 表 → RecoveryPolicy 硬编码 SECURITY→STOP →
  RetryPolicy 拒绝 not_retryable；I3 端到端零重试
- 全量回归 987/6 + ruff 0：无一处失败被掩盖
- 诚实限制：I6 的验证/修复阶段覆盖是 Day 4/5 范围；50 Case 是开发集；
  Benchmark/Ablation 数据尚未产生（周度）
```

# 18. Final Conclusion

```text
Test Development:        N/A（验收模式，未写测试）
Correctness:             PASS
Safety:                  PASS（I1/I2/I3 三层防御 + Week3 执行层回归）
Observability:           PASS（事件时间线独立重放验证；Day 5 补齐 recovery.completed/failed 发射）
Evaluation:              PASS（corpus 数据出口完备，周度可只读执行）
Benchmark:               NOT_EXECUTED（周度节奏，合规）
Ablation:                NOT_EXECUTED（周度节奏，合规）
Design Decision:         INSUFFICIENT_EVIDENCE（DD-W4-D3-01 未撰写；待验证架构假设已记录）
Overall Module Acceptance: PASS（附 K1/K2 已知限制与 O1~O5 观察项，无阻塞缺陷）

Manager 疑点清单 A~E：全部有结论（A=Day4 范围限制，B=PARTIALLY_SUPPORTED，
C=声明准确，D=修复真实，E=无质量问题）。
```

---

## 附：待验证架构假设（DD-W4-D3-01 未撰写 → INSUFFICIENT_EVIDENCE）

| # | 隐含决策 | 当前证据 | 周度后预期结论 |
|---|---------|---------|---------------|
| H1 | 独立 failures 包分层（Domain 层与 Week1 传输层分离） | 枚举隔离测试通过；分层测试完备 | 待 Classification Accuracy |
| H2 | deterministic classification + model-assisted diagnosis 分界 | 50 Case 全绿 + 48/50 具体码 | 待周度数据 |
| H3 | Retry Ownership（classifier 建议 / Orchestrator 执行） | 集成测试证明执行真实发生 | 待 Unnecessary/Unsafe Retry |
| H4 | AgentFailure 携带 recommended_recovery | 契约测试 + policy 透传 | 待 Recovery Action Accuracy |
| H5 | RecoveryPolicy 硬编码安全规则（纵深防御） | T14 + 一致性守卫测试 | 待 Ablation（Typed vs Generic） |

在周度 Benchmark/Ablation 数据到位前，以上全部标记 INSUFFICIENT_EVIDENCE，不得宣称 SUPPORTED。
