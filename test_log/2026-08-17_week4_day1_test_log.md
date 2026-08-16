# Week 4 Day 1 独立验收报告

**日期**: 2026-08-17
**角色**: Test / Evaluation Agent（独立验收）
**分支**: week4（HEAD aa943c7，工作区干净）
**授权范围**: 仅运行测试 + 1 次 LLM 烟测；生产代码/测试代码只读；Commit/Merge/Push 均未授权（未执行）

---

# 1. Evaluation Summary

对 Week 4 Day 1（Issue → Plan → Execution State，NL → TaskSpec → Repository Inspection → Structured Plan → READY）执行独立验收：

- 全量 pytest 独立复跑：**790 passed / 0 failed / 0 skipped**，与经理基线一致
- Day 1 模块 102 个测试全部通过，覆盖率为 **97%**（336 语句 / 9 未覆盖）
- 关键验收（R2/R12/R13/R14）经源码级复核，断言真实有效，非"为通过而写"
- 对抗性探索发现 **2 个非阻断性发现**（状态机枚举类型漏洞 F1、失败路径事件可观测性缺口 F2）
- 真实 LLM 烟测（授权 1 次）通过：READY、6 步 Plan、零幻觉文件引用
- Design Decision DD-W4-D1-01 存在、与 day1.md 七十一~七十四节一致、Evidence status=PROPOSED
- Benchmark / Ablation **未授权执行** → 相关结论标注 NOT_VERIFIED

# 2. Capability Mapping

| 项 | 内容 |
|----|------|
| Module | Week 4 Day 1: task/state.py + task/models.py + planning/models.py + planning/planner.py + agent/inspection.py + agent/orchestrator.py + events.py |
| Primary | **Agent Harness** — Task 生命周期状态机（9 状态、集中转移表、唯一 transition_to 入口） |
| Secondary | **Context Engineering**（RepositoryInspector 把 Week 2 检索证据适配为 RepositoryContext）、**Observability**（task.*/repository.inspection_*/plan.* 事件 Trace） |
| 已验证 | 1. 状态机合法/非法转移正确；2. 空输入在 LLM 前失败；3. 异常总闸门 → FAILED 不抛不卡；4. 事件序列成功路径逐位一致；5. READY/失败路径磁盘零变更 |

# 3. Repository Inspection

```
Technical Stack:      Python 3.11 + pydantic v2 + pytest 9.x
Test Framework:        pytest（.venv/bin/python -m pytest）
Target Modules:        codeteam/task/ codeteam/planning/ codeteam/agent/ + events.py
Public API:
  - TaskStatus(9 状态) / TASK_TRANSITIONS / TaskState.transition_to / is_terminal / history
  - TaskSpec(pydantic 校验) / create_task_spec
  - PlanStepStatus / STEP_TRANSITIONS / PlanStep / Plan / validate_plan / create_plan / replan
  - Planner Protocol / RepositoryContext / MockPlanner / FailingPlanner / LLMPlanner
  - RepositoryInspector（ContextApplicationService → RepositoryContext 适配）
  - SingleAgentOrchestrator.run → OrchestrationResult（不抛异常契约）
Existing Tests:        tests/task/(2 文件) tests/planning/(2 文件) tests/agent/(2 文件 + conftest)
Fixtures:              tests/agent/conftest.py repo_copy（copytree → tmp_path）
Git Status:            干净（无未提交变更，无 untracked）
Implementation / Requirement Differences:
  - LLMPlanner.create_plan 硬编码 plan_id="{task_id}-plan-v1"（无 replan 路径，Day 2+ 关注）
  - _fail() 不发出 →FAILED 的 status_changed 事件（见 F2）
```

# 4. Requirement Coverage（对照任务 R1-R14）

| ID | Requirement | Status | 证据测试 |
|----|-------------|--------|---------|
| R1 | 普通 NL 任务 → READY | **PASS** | test_full_pipeline_reaches_ready（真实 Context Engine + MockPlanner）+ LLM 烟测（真实模型，exit 0，READY） |
| R2 | 空/纯空白任务在进 LLM 前失败 | **PASS** | test_empty_request_fails_fast_without_calling_planner 断言 planner.calls == []；独立复核确认 inspector 亦零调用（E4a 事件序列无 inspection_started） |
| R3 | Plan ≥ 1 Step 不变量 | **PASS** | test_create_plan_empty_steps_rejected + test_empty_steps_plan_rejected_with_validation_event（Runtime 闸门） |
| R4 | Step 合法转移成功 | **PASS** | test_valid_transition_chain（PENDING→RUNNING→COMPLETED） |
| R5 | Step 非法转移被拒（含 PENDING→COMPLETED 直跳） | **PASS** | test_pending_direct_to_completed_rejected + test_terminal_states_cannot_transition；对抗性 E1 复核：非法直跳对 raw string 同样拒绝 |
| R6 | is_complete 判定 | **PASS** | test_is_complete_all_completed / _with_skipped / _false_when_not_done / _false_with_pending |
| R7 | has_failed_step 判定 | **PASS** | test_has_failed_step（含 FAILED⇒is_complete=False 联动） |
| R8 | Replan: version+1、task_id 不变、旧 Plan 不变 | **PASS** | test_replan_version_increments + test_replan_does_not_mutate_old_plan；E5 复核 plan_id 沿用旧值（p-001 v1→v2），day1 未禁止，记录为设计行为 |
| R9 | Task 非法转移被拒（CREATED→COMPLETED） | **PASS** | test_illegal_jump_rejected（4 组参数化含 CREATED→COMPLETED） |
| R10 | Terminal 状态不可再转移 | **PASS** | test_terminal_completed_cannot_transition + test_terminal_failed_cannot_transition（Task 与 Step 两层） |
| R11 | Planner 异常 → FAILED，不抛不卡 | **PASS** | test_planner_exception_yields_failed_not_raise；对抗性 E3 扩展验证：inspector 抛异常同样经总闸门 → FAILED（coder 未覆盖该路径，行为正确） |
| R12 | 事件序列完整 + data 字段 | **PARTIAL** | 成功路径 test_exact_event_sequence（9 事件逐位一致）+ data 逐键断言 → PASS；失败路径缺 →FAILED 的 status_changed 事件（见 F2） |
| R13 | READY 与失败路径磁盘零变更 | **PASS** | test_run_does_not_modify_disk / test_failed_run_does_not_modify_disk（SHA256 全文件字节指纹）；烟测后 git status 干净佐证 |
| R14 | fixtures 拷贝 tmp_path | **PASS** | conftest repo_copy（copytree）；烟测前后 git status --short tests/fixtures/ 为空 |

# 5. Tests（独立复核 coder 测试有效性）

| 复核点 | 结论 |
|--------|------|
| R2 是否真断言 planner 零调用 | ✓ assert planner.calls == []（test_orchestrator.py:154）；且独立验证 inspector 未调用 |
| R12 是否逐位断言 + 校验 data | ✓ EXPECTED_SEQUENCE 9 元组 assert tuple(types) ==（:257）；status_changed 的 from/to/reason/task_id 逐键断言（:281-285）；plan.created 的 plan_id/version/step_count/planner_ms（:302-305） |
| R13 是否比对文件指纹 | ✓ _hash_dir 对目录所有文件字节做 SHA256（:94-100），READY 与 FAILED 双路径 before==after |
| R14 fixture 隔离 | ✓ copytree 到函数级 tmp_path（conftest.py:20-28）；无任何测试直接触碰 tests/fixtures/ |

# 6. Test Execution Results

```
命令:      .venv/bin/python -m pytest -q
退出码:    0
通过:      790
失败:      0
跳过:      0
耗时:      10.41s（真实测量）

Day 1 模块子集: tests/task/ tests/planning/ tests/agent/ → 102 passed / 0.67s
```

# 7. Coverage（Day 1 模块）

```
Name                             Stmts   Miss  Cover
codeteam/agent/inspection.py        18      0   100%
codeteam/agent/orchestrator.py      66      2    97%
codeteam/planning/models.py         86      7    92%
codeteam/planning/planner.py       110      0   100%
codeteam/task/models.py             22      0   100%
codeteam/task/state.py              34      0   100%
TOTAL                              336      9    97%
```

未覆盖说明：
- orchestrator.py:260-261：_fail() 中 except InvalidTransitionError: pass 二次防御分支（正常流程不可达，属防御代码）
- planning/models.py:62,65-75：独立 dataclass PlanStepState（PlanStep 自带 transition_to，此类疑似死代码）
- planning/models.py:205：validate_plan 的防御性枚举检查——且 F1 证明该检查可被 str-enum 相等性绕过

# 8. Benchmark

**状态：NOT_VERIFIED（未授权执行）**。10-prompt Benchmark（day1.md 七十五节 T01-T10）涉及 10 次真实 LLM 调用，本任务未授权。

现有烟测脚本指标口径审查：
- repo_inspection_ms：**未计时**（inspection 无独立计时代码/事件字段）
- planner_ms：已计时（orchestrator.py:174-179，写入 plan.created.data）
- token 计数：**未捕获**（day1.md 九十四建议 input_tokens/output_tokens 进 plan.created，当前事件无此字段；LLMPlanner.complete 接口不返回 usage）

**10-prompt Benchmark 执行方案建议**（供后续单独授权）：
1. 环境：当前 week4 HEAD SHA 记录；.venv；secrets.local.env 或 CODETEAM_LLM_* 注入；记录模型标识
2. 重复次数：每 prompt 3 次（10 prompt × 3 = 30 次 LLM 调用，开发评估规模，标注 exploratory）
3. 需要先补齐的插桩（coder 侧）：RepositoryInspector 或 orchestrator 增加 repo_inspection_ms；LLMPlanner 返回 usage（input/output tokens）并写入 plan.created 事件 data
4. Raw data 落盘：evals/artifacts/w4d1_benchmark_raw.jsonl，每行 {case_id, iteration, model, repo_inspection_ms, planner_ms, step_count, input_tokens, output_tokens, hallucinated_files, status, commit_sha, timestamp}
5. Aggregation：P50/P95 latency、step_count 分布、幻觉率、token 均值 → summary JSON
6. 基线：Day 1 无历史基线，首轮结果仅作为 Baseline 存档，不声称优劣
7. 局限声明：单模型单仓库（fixture），结论不可外推

# 9. Ablation

**状态：NOT_VERIFIED（未授权执行，day1.md 十二节亦明确推迟到 Week 4 末）**。规格：Plan-first vs Direct-edit，指标为 Task Success / Recovery / Wrong Diff Count。

# 10. Failure Cases

| ID | Module | Trigger | Root Cause | Mitigation | Regression Test |
|----|--------|---------|-----------|------------|-----------------|
| FC-W4D1-001 | evals/w4d1_llm_smoke.py | 按文档命令 .venv/bin/python evals/w4d1_llm_smoke.py 直接运行 | 脚本不把仓库根加入 sys.path（ModuleNotFoundError: codeteam） | 本次以 PYTHONPATH=<repo> 环境变量绕过（未改脚本）；建议脚本头部 sys.path 处理或改用 pip install -e . | 无（eval 脚本非 pytest 范围） |
| FC-W4D1-002 | 失败路径事件 Trace | 任意失败路径（空输入/planner 异常/inspector 异常） | _fail() 只发 task.failed，不发 →FAILED 的 status_changed | 见 F2 建议 | 缺失（coder 仅断言最后事件为 task.failed） |

# 11. Production Defects

## Defect F1: transition_to 接受非枚举裸字符串（类型安全漏洞）

### Module
codeteam/task/state.py、codeteam/planning/models.py

### Test
无 coder 测试覆盖（本验收对抗性探索 E1/E2 发现，脚本：tmp/adversarial_w4d1.py）

### Preconditions
调用方误传与枚举值相同的裸字符串。

### Reproduction
```python
state = TaskState(task_id="t")
state.transition_to("inspecting")      # 被接受！
state.status                           # 'inspecting'（plain str，非 TaskStatus）
state.history[0].to_status             # 'inspecting'（plain str）
```
PlanStep 同理：step.transition_to("running") 后 step.status 为裸 str。

### Expected
transition_to 只接受 TaskStatus/PlanStepStatus 枚举实例；非枚举输入被拒绝（TypeError 或 InvalidTransitionError）。

### Actual
str-mixin Enum 与裸字符串相等（Python 3.11），"inspecting" in legal 为 True → 转移成功，状态字段被赋值为裸 str。

### Error
无异常抛出（静默污染状态与 history 的类型一致性）。

### Reproducibility
稳定复现（每次均接受）。已验证 "completed" 直跳仍被拒（非法值不受影响），风险限于"合法值的裸字符串"。

### Evidence
E1/E2 脚本输出：status='running' type=str、history[0].to_status='inspecting' type=str。

### Suspected Root Cause
transition_to 用 in 成员判断（依赖相等性）而非 isinstance(new_status, Enum) 类型检查；str Enum 的相等性语义使裸字符串绕过。

### Impact
- 审计 history 的类型契约被破坏（TaskTransition.to_status: TaskStatus 实际存 str）
- validate_plan 的防御性枚举检查（models.py:205）被绕过
- 下游若严格按枚举比较（is）将出错

### Suggested Direction
transition_to 入口加 isinstance(new_status, TaskStatus)（或 PlanStepStatus）类型守卫；或将转移表查找改为 type(new_status) is TaskStatus 严格匹配。

## Defect F2: 失败路径缺 →FAILED 的 status_changed 事件（Observability 缺口）

### Module
codeteam/agent/orchestrator.py（_fail()）

### Test
缺失（coder 仅断言失败路径最后事件为 task.failed）

### Preconditions
任意失败路径：空输入（CREATED→FAILED）、inspector 异常（INSPECTING→FAILED）、planner 异常/非法 Plan（PLANNING→FAILED）。

### Expected
按 day1.md 九十三节意图，每次状态变更（含 →FAILED）应产生 status_changed 事件（task_id/from_status/to_status/reason），事件流可完整重建状态时间线。

### Actual
_fail() 调用 state.transition_to(FAILED) 但不发 status_changed 事件；仅发 task.failed（data 只有 task_id/reason，无 from_status/to_status）。空输入路径事件序列仅 2 条：task.created → task.failed。

### Reproducibility
稳定复现（确定性代码路径）。

### Suspected Root Cause
_fail() 未复用 _status_event()；失败转移的事实仅存在于 state.history（内存），未进入事件 Trace。

### Impact
- 事件流无法直接回答"任务从哪个状态失败"（需反查内存 history）
- 与成功路径的"每次转移必有 status_changed"不一致，Trace 语义断裂
- 影响未来 Failure Analysis / 持久化重放

### Suggested Direction
_fail() 内 transition 成功后补发一条 _status_event(state, reason)（含 from_status/to_status）；或统一在 TaskState.transition_to 层挂钩事件（架构级方案）。

# 12. Design Decision Verification

```
Decision:      DD-W4-D1-01 Structured Execution Plan
               存在性: ✓ docs/design_decisions/DD-W4-D1-01.md
               内容与 day1.md 七十一~七十四节一致: ✓
               状态: 决策 Accepted（实现完成）；Evidence status: PROPOSED ✓

Hypothesis:    Structured Plan（状态机 + 版本化 + 校验闸门 + Grounding）
               比 Free-form NL Plan 更适合作为 Runtime source of truth

Required Evidence:
  - Correctness: 状态机/校验/事件 行为正确          → 已收集（102 tests + 全量 790）
  - Performance: Planning Cost（latency/step/token）→ 未执行（未授权）
  - Value:       Plan-first vs Direct-edit Ablation  → 未执行（推迟 Week 4 末）

Evidence Collected:
  - 全部 14 项验收 R1-R11/R13/R14 PASS，R12 PARTIAL
  - LLM 烟测：6 步 Plan、零幻觉引用、READY
  - 2 个非阻断缺陷（F1 类型漏洞、F2 失败路径 Trace 缺口）

Evaluation:    PARTIALLY_SUPPORTED
Reason:        正确性维度证据充分（状态机、校验闸门、Grounding、事件成功路径
               均有测试与独立复核支持）；但"Structured Plan 值得存在"的
               性能/价值假设尚无实验数据（Benchmark 与 Ablation 均未执行），
               与 DD 自述 Evidence status=PROPOSED 一致，DD 表述诚实。
```

# 13. Acceptance

| 验收项 | 结果 | 证据 |
|--------|------|------|
| R1 | PASS | test_full_pipeline_reaches_ready + 烟测 READY |
| R2 | PASS | planner.calls==[] 断言 + inspector 零调用独立确认 |
| R3 | PASS | 工厂层 + Orchestrator 闸门双层拒绝 |
| R4 | PASS | test_valid_transition_chain |
| R5 | PASS | 直跳拒绝（含 raw string 复核） |
| R6 | PASS | is_complete 4 用例 |
| R7 | PASS | has_failed_step + 联动 |
| R8 | PASS | version/task_id/旧 Plan 不变 |
| R9 | PASS | 4 组非法跳转参数化 |
| R10 | PASS | Task/Step 双层 Terminal |
| R11 | PASS | planner 异常 + inspector 异常（E3 补充）均 FAILED 不抛 |
| R12 | PARTIAL | 成功路径逐位/逐键断言充分；失败路径缺 status_changed（F2） |
| R13 | PASS | SHA256 指纹双路径 + 烟测后 git clean |
| R14 | PASS | copytree + 烟测前后 fixtures 无变更 |
| LLM 烟测 | PASS | exit 0、READY、6 步、零幻觉、9 事件 |
| Benchmark | NOT_VERIFIED | 未授权执行，方案见 §8 |
| Ablation | NOT_VERIFIED | 未授权执行，规格见 §9 |

# 14. Regression

- 全量套件独立复跑：790 passed / 0 failed / 0 skipped（10.41s），与经理基线一致
- Day 1 无历史 Benchmark 基线，无可对比的 Performance Regression
- 烟测运行前后 git status --short 为空：无测试副作用遗留

# 15. Risks and Limitations

```
未测试内容:
  - 并发 run()（Orchestrator 非线程安全假设未验证）
  - TaskState 序列化/持久化（Day 4 范围）
  - replan 经 LLMPlanner 的完整链路（LLMPlanner 硬编码 v1，无 replan 入口）

无法验证内容:
  - Benchmark / Ablation（未授权）
  - 失败路径事件 Trace 完整性（当前缺失，见 F2）

环境限制:
  - 烟测为单次运行、模型输出有随机性，不得外推统计结论
  - 烟测脚本未分开计时 repo_inspection 与 planner 两阶段（18.43s 为整链路 wall-clock）
  - 烟测需 PYTHONPATH 环境变量才能运行（FC-W4D1-001）

已知事项（记录，留给 Coder）:
  - ruff：day1 模块当前 All checks passed（任务前提中的 16 处已不存在，coder 已修复）；
    全仓仍有 173 处（主要位于 week2/week3 历史文件，import 排序等）
  - mypy：day1 模块 0 错误；14 处位于 week2 历史文件
    （frontmatter.py 1 / tree_sitter_parser.py 3 / ripgrep.py 10），与任务前提吻合；
    全仓另有 35 处（tools/files.py、calculator.py、eval_command.py 等 week1/week3 文件）
  - planning/models.py 存在疑似死代码 PlanStepState（62,65-75 行未被任何测试/生产引用覆盖）

后续建议:
  1. Coder 修复 F1（类型守卫）与 F2（_fail 补发 status_changed），并补对应回归测试
  2. Coder 补齐 Benchmark 插桩（repo_inspection_ms、token usage）后按 §8 方案执行
  3. 烟测脚本加 sys.path 自愈（FC-W4D1-001）
```

# 16. Artifacts

```
本报告: test_log/2026-08-17_week4_day1_test_log.md（唯一写入文件，Allowed Paths 内）
对抗性脚本: $CLAUDE_JOB_DIR/tmp/adversarial_w4d1.py（系统临时目录，未进入仓库）
未创建 Benchmark/Ablation 文件（未授权）
未修改任何生产代码/测试代码（codeteam/、tests/、evals/ 均只读）
未执行 Commit / Merge / Push（未授权）
```

# 17. Interview Evidence

```
本次验收可支撑的客观证据：
- 790 全量测试独立复跑通过，Day 1 模块 97% 行覆盖
- 状态机非法转移（含直跳、Terminal 复活）在参数化测试中被稳定拒绝
- 空输入在 LLM 前失败（planner 零调用断言），并独立验证 inspector 零调用
- 异常总闸门经两条独立路径验证（planner 异常 + inspector 异常）→ FAILED 不抛异常
- 磁盘零变更通过 SHA256 文件指纹验证（READY 与失败双路径）
- 真实模型烟测：6 步结构化 Plan、零幻觉文件引用、完整 9 事件 Trace
- 对抗性探索发现 2 个 coder 未覆盖的边界问题（F1/F2）——这正是独立验收的价值

诚实限制：
- 并发安全性、持久化未验证
- 性能与价值假设无实验数据（Benchmark/Ablation 未执行）
- 烟测为单次运行，模型输出有随机性
```

# 18. Final Conclusion

```
Test Development:  COMPLETE
                   （coder 测试已实现并验证有效；按任务授权未补充新测试）

Correctness:       PASS
                   （R1-R11、R13、R14 全部 PASS；R12 成功路径 PASS、失败路径 PARTIAL）

Safety:            PASS
                   （READY/失败路径磁盘零变更、fixtures 零触碰、无凭据泄露、
                    危险边界未发现安全问题）

Design Decision:   PARTIALLY_SUPPORTED
                   （正确性机制证据充分；性能与价值假设 INSUFFICIENT_EVIDENCE）

Benchmark:         NOT_VERIFIED（未授权；方案已给出）
Ablation:          NOT_VERIFIED（未授权；推迟 Week 4 末）

Overall Module Acceptance: PASS（附 2 个非阻断缺陷 F1/F2 留待 Coder 修复）
```

---

# 19. 修复回归验收（2026-08-17 追加章节）

**性质**: 对上轮 F1/F2/D1/S1 修复的针对性回归验收（Coder 修复，未提交改动，diff 已审查）
**授权**: 只读验证 + 临时脚本；未执行 Commit/Merge/Push；未重复真实 LLM 烟测

## 19.1 修复 Diff 审查结论

| 修复 | 文件 | 修复方式 | 审查结论 |
|------|------|---------|---------|
| F1 | task/state.py、planning/models.py | transition_to 入口加 `isinstance(new_status, TaskStatus/PlanStepStatus)` 类型守卫，非法输入抛 InvalidTransitionError/InvalidStepTransitionError 且消息含类型名与值 | 正确（成员检查前拦截，str-Enum 相等性绕过路径被堵死） |
| F2 | agent/orchestrator.py | `_fail()` 的 try/except 加 `else:` 分支——转移成功补发 `_status_event`，转移失败（已 Terminal）不发 | 正确（try/except/else 语义：无转移=无事件） |
| D1 | planning/models.py | 删除死代码 `PlanStepState`（含 dataclass/field import） | 正确（全仓零引用，见 19.4） |
| S1 | evals/w4d1_llm_smoke.py | 头部 `REPO_ROOT` 提前 + `sys.path.insert`，再 import codeteam | 正确（idempotent：已在 path 时不重复插入） |

## 19.2 F1 独立复现验证（临时脚本 tmp/regression_w4d1.py）

- TaskState.transition_to 对 `'inspecting'`/`'ready'`/None/int/float/object **全部拒绝**，异常类型 `InvalidTransitionError`，消息格式 `目标状态必须是 TaskStatus 枚举成员，收到 <type>: <value>`，status 与 history 均不变 → **逐项 PASS**
- PlanStep.transition_to 对 `'running'`/`'pending'`/None/int/float/object 全部拒绝，status 不变；PENDING→RUNNING→COMPLETED 合法链与 PENDING→COMPLETED 直跳拒绝均正常 → **PASS**
- 对抗性补充：`TaskStatus("inspecting")` 显式构造枚举是合法路径（str-Enum 特性保留，守卫未误伤）→ **PASS**
- 异常消息清晰可诊断（含违规类型名与值）→ **PASS**

**裁决: F1 = FIXED_VERIFIED**

## 19.3 F2 事件序列复验（独立脚本）

三条失败路径事件末尾均为 `status_changed(from=X → to=failed, reason=...)` + `task.failed`：

| 路径 | from_status | reason 内容 | 结果 |
|------|------------|------------|------|
| Planner 异常 | planning | `RuntimeError: boom` | PASS |
| 非法 Plan（steps=()） | planning | `plan_validation_failed` | PASS |
| 空请求早失败 | created | ValidationError 详情 | PASS |

- 成功路径 9 事件序列与上轮 EXPECTED_SEQUENCE **逐位一致**（无回归）→ PASS
- "双重失败不发重复事件"分支：代码审查确认 `except InvalidTransitionError: pass` + `else:` 语义正确（无转移=无变化事件；转移失败时 status/history 不变已由上轮测试保证）→ PASS
- coder 新增 3 个 F2 测试断言真实有效（末二/末一事件类型与 from/to 逐键断言）

**裁决: F2 = FIXED_VERIFIED；R12 更新为 PASS**

## 19.4 D1 验证

- `grep -rn "PlanStepState" codeteam/ tests/` → **零引用**
- `STEP_TRANSITIONS` / `InvalidStepTransitionError` 仍被 `PlanStep.transition_to` 使用（diff 确认删除只触及死代码）
- PlanStep.transition_to 行为回归正常（见 19.2）

**裁决: D1 = FIXED_VERIFIED**

## 19.5 S1 零成本验证（未真实调用 LLM）

```
命令: CODETEAM_LLM_BASE_URL=http://127.0.0.1:1 CODETEAM_LLM_API_KEY=x CODETEAM_LLM_MODEL=x \
      .venv/bin/python evals/w4d1_llm_smoke.py
结果: 不再 ModuleNotFoundError；脚本成功导入 codeteam、加载配置、
      执行完整 Context 管线，在 HTTP 阶段失败（HTTP Error 502），
      Orchestrator 总闸门转 FAILED，脚本按设计 exit 1
```

- sys.path 修复生效（按 docstring 直接运行脚本可用）→ PASS
- 失败发生在网络阶段而非 import 阶段，符合预期口径（本机 127.0.0.1:1 返回 502 而非连接拒绝，属环境差异，不影响结论）
- 附带收益：真实 HTTP 异常路径经总闸门 → FAILED 的事件序列亦验证了 F2 修复在异常种类上的覆盖
- 真实 LLM 烟测未重复执行（任务规定；coder 自测声明与此前上轮通过记录一致）

**裁决: S1 = FIXED_VERIFIED；FC-W4D1-001 关闭**

## 19.6 回归确认

```
命令:   .venv/bin/python -m pytest -q
结果:   805 passed / 0 failed / 0 skipped，10.24s
基线:   805（790 上轮 + 15 新增）—— 只升不降 ✓
```

新增 15 个回归测试逐一对账：

| 测试 | 覆盖缺陷 | 有效性 |
|------|---------|--------|
| test_state.py::TestTransitionTypeGuard（6 参数 + 1 合法） | F1 TaskState | ✓ 断言类型拒绝 + status/history 不变 + 合法转移不受影响 |
| test_models.py::TestPlanStepTypeGuard（4 参数 + 1 合法） | F1 PlanStep | ✓ 同上 |
| test_orchestrator.py::TestFailureStatusChangedEvent（3） | F2 | ✓ 末二/末一事件类型 + from/to/reason 逐键断言 |

- 独立脚本额外覆盖了 coder 测试未含的边界（float/object 输入、TaskStatus("x") 显式构造），全部通过
- ruff check（codeteam/task/ codeteam/planning/ codeteam/agent/ evals/w4d1_llm_smoke.py tests/task/ tests/agent/）→ **0 error**
- 工作区除 coder 改动与 test_log 外无其他变更；fixtures 未被触碰

## 19.7 裁决更新与残留风险

```
F1: FIXED_VERIFIED
F2: FIXED_VERIFIED
D1: FIXED_VERIFIED
S1: FIXED_VERIFIED

R12: PASS（上轮 PARTIAL → 本轮失败路径 status_changed 补齐后更新）
Overall Acceptance: PASS

残留风险:
- 类型守卫仅覆盖 transition_to 入口；TaskState.status 直接属性赋值仍可绕过
  （dataclass 非 frozen，与本轮修复范围一致，属已知设计取舍，建议 Day 4 持久化时评估 frozen 化）
- F2 的 status_changed 仅存在于事件流；task.failed 事件 data 仍无 from_status 字段
  （与 day1 九十三节要求一致即 from/to/reason 在 status_changed 中，当前满足）
- 15 个新测试未覆盖 TaskStatus("x") 显式构造的合法路径（本验收独立验证过，
  建议 coder 后续补 1 条固化用例，非阻断）
- 真实 LLM 烟测本轮未重复执行（按任务规定零成本验证）
```
