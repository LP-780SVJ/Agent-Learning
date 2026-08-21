# W4D5 独立验收报告：Context Compaction + Model/Provider Switching

**日期**: 2026-08-20
**角色**: Independent Evaluator（Test / Evaluation Agent，验收模式）
**分支**: week4 @ 4c78672（工作区干净；疑点 B 所述 dirty diff 已由该提交吸收）
**权限**: 只读审查 + 执行测试 + 本报告唯一写入路径
**环境**: Python 3.11.7（.venv），pytest 9.x，本机 Docker 29.7.2（daemon 可用 + `codeteam-sandbox:latest` 镜像在位）

---

# 0. 第一轮计划（test_Agent.md §七十四固定 10 节）

| # | 节 | 内容概要 |
|---|---|---|
| 1 | Capability Mapping | Primary: Context Engineering（分层重组/Budget/有损压缩）+ Provider-neutral Model Layer；Secondary: Observability / Safety / Evaluation 数据出口 |
| 2 | Requirement Matrix | A(Context 13) + B(Provider 13) + C(K2 债务 3) + D(工程证据 4)，逐项 PASS/FAIL/PARTIAL + 证据测试名 |
| 3 | Repository Inspection | HEAD 4c78672 两提交（a32c9aa 实现 + 4c78672 测试 93 项）；codeteam/session 0 error；tests/llm·tests/context 新建 |
| 4 | Test Strategy | 验收模式不写新测试；逐测试文件核断言真实性（重点：回退语义非仅异常断言、公共路径非私有调用） |
| 5 | Benchmark Plan | NOT_EXECUTED（周度节奏）；仅评估数据出口完备性 |
| 6 | Ablation Plan | NOT_EXECUTED（同上）；A3/A4 数据出口评估 |
| 7 | Failure Cases to Watch | day5 §十三 C1-C5/S1-S6 逐项对照；fits_budget 消费方、SessionService 接线缺口 |
| 8 | Design Decision Evidence Needed | DD-W4-D5-01/02 存在性核查（疑点 F）；PROPOSED 状态不得宣称 SUPPORTED |
| 9 | Files to Create/Modify | 仅本报告（test_log/2026-08-20_week4_day5_test_log.md） |
| 10 | Execution Plan | focused → full → docker 单独复跑 → ruff → grep 审计（sleep/skip/network/credential）→ 疑点 A-F 逐条 → 报告 |

---

# 1. Evaluation Summary

W4D5 交付物（context/compaction+assembler、llm/registry+error_mapper+switching、K2 接线 + 5 个测试文件 93 项新测试）整体质量高：**§四十六 24 项矩阵中 19 项 PASS、4 项 PARTIAL、0 项 FAIL**（矩阵内），K2 债务核心达成。全量 **1165 passed / 0 skipped**（skip 6→0 为本机 Docker 环境变化，非掩盖，已实证）。

四项未达标（均非矩阵内 FAIL 而是矩阵外工程要求）：

- **D2 FAIL**：今日修改的 `orchestrator.py` 含 2 处 ruff error（I001 import 排序 @ L15、F841 未用变量 @ L547）；Coder 提交信息"触达文件 ruff 0 error"的验证口径遗漏了 a32c9aa 中的 orchestrator.py
- **D3 FAIL**：`DD-W4-D5-01.md` / `DD-W4-D5-02.md` **不存在**（docs/design_decisions/ 仅有 D1-D4 六份）；day5 附录 Step 7 明示为"今日收尾产出"，未兑现
- **C3 缺口**：「明确不做清单」仍未以独立文档落盘（W4D3 起延续的文档追溯性缺口，orchestrator 注释仍引用"Step 7 落盘"）
- 4 项 PARTIAL（A10/A13/B8/B9/B11 中详见矩阵）：`fits_budget` 无生产消费方、SessionService 未接 ModelSwitchService、turn.completed 无 tokens/cost

无生产缺陷需要修复才能通过验收的阻塞项；上述缺口按 Day 6 CLI 集成范围记录或要求补齐文档。

# 2. Capability Mapping

```
Module: Context Compaction + Model/Provider Switching（W4D5）
Primary:  Context Engineering — 分层重组（authoritative 重注入/Summary/Recent Window）、
          Token Budget（ModelMetadata 推导）、有损压缩策略
          Agent Runtime — Provider-neutral Model Layer（Registry/Selection/Switch Transaction）
Secondary: Observability（turn./model./recovery.completed 事件、per-turn 归因）
           Safety（API key 不落盘、fail-closed switch、capability 校验）
           Evaluation（CompactionResult 计量 → Benchmark 数据出口）
What was proven:
  1. Durable/Active 分离的结构性保证（compaction 不 import 持久化层，架构测试断言）
  2. 权威四段重注入：Summary 漏报/谎报均不影响约束/Plan/Checkpoint
  3. Switch 事务 fail-closed：4 类拒绝均断言旧 selection 回退（真实回退语义）
  4. Turn Boundary 不变量：mid-turn 排队、嵌套拒绝、异常 Turn 仍 drain
  5. K2 真还债：COMPACT 经 run() 公共路径，recovery.completed/failed 有真实发射方
```

# 3. Repository Inspection

```text
Technical Stack: Python 3.11 + pydantic；.venv/bin/python
Test Framework:  pytest（pytest.ini: testpaths=tests, norecursedirs=tests/fixtures）
Target Module:   codeteam/context/{compaction,assembler}.py（新增 543 行）
                 codeteam/llm/{registry,error_mapper,switching}.py（新增 746 行）
                 codeteam/llm/base.py（ModelClient Protocol 形式化）
                 集成点: agent/orchestrator.py（K2 +105 行）、events.py（+6 行 5 事件）、
                         failures/classifier.py（①b 归一化分支 +22 行）、
                         session/models.py（ContextMetadata 升级）
Target Tests:    tests/context/{test_compaction,test_assembler}.py（800 行）
                 tests/llm/{test_registry,test_switching}.py（706 行）
                 tests/agent/test_recovery_executors.py（365 行）
Public API:      ContextCompactor.compact / ContextAssembler.assemble / build_recent_window /
                 is_compaction_needed / ProviderRegistry.{metadata,require_credential,build_client} /
                 compute_context_budget / ModelSwitchService.{turn,request_switch} /
                 MapperChain.map / TO_AGENT_ERROR_CODE
Existing Tests:  93 项新增（compaction 27 + assembler 24 + registry 20 + switching 22 含架构 2）
Missing Interface: 无（矩阵所需接口齐全）
Git Status:      4c78672 工作区干净（疑点 B 的三文件改动已并入该提交）
Applicable Rules: AGENTS.md（.venv、无 skip/xfail 掩盖、tmp_path 隔离）

与 day5 附录工程地图的差异（Implementation/Requirement Differences）:
  D-1: 附录修改清单要求 events.py 增加 context.compacted / context.stale_rebuilt——
       实际只加了 model.switch_* 与 turn.* 共 5 个（context.* 事件缺失，附录 §7 也要求
       "context_version 匹配? 不匹配 → CONTEXT_STALE → rebuild" 的事件可观测）
  D-2: 附录要求 DD-W4-D5-01/02 "今日收尾产出"——未产出（Step 7 未完成）
  D-3: 附录要求「明确不做清单」落位 docs/design_decisions/W4-not-doing-list.md——未落盘
       （附录自注"待用户确认"，但矩阵 C3 要求如实记录缺口）
```

# 4. Requirement Coverage

## A. Context（§四十六 10 项 + §五十六附加 3 项）

| ID | 要求 | 状态 | Evidence（测试名） |
|----|------|------|--------------------|
| A1 | 早期用户约束 Compact 后仍在 Active Context（authoritative 重注入，非靠 Summary） | **PASS** | `test_user_constraint_survives_even_if_summary_omits_it`（故意构造 Summary 漏约束，断言 TASK 段仍含"不能修改公开 API"+ SYSTEM 段含 system_rules） |
| A2 | Current Plan 从 Session 重注入 | **PASS** | `test_plan_status_comes_from_session_plan_not_summary`（Summary 谎称 s1 已完成，断言 Plan 段 "○ s1" PENDING 且 "✓ s1" 不存在——C2 幻觉防御实证） |
| A3 | Current Checkpoint 从 Session 重注入 | **PASS** | `test_checkpoint_reinjected_in_plan_section`（断言 "Checkpoint: cp-003" 在 PLAN 段） |
| A4 | Earlier failed test 在 Summary 中保留 | **PASS** | `test_failed_test_kept_via_summary_section` + `test_fact_groups_survive_compaction`（8 字段全保留断言） |
| A5 | Current file 保留在 Recent/Retrieval | **PASS** | `test_current_file_kept_via_recent_section`（summary=None 时经 RECENT 段可见） |
| A6 | Unfinished step 保持 PENDING/RUNNING | **PASS** | 同 A2（PENDING 渲染断言） |
| A7 | Huge tool output 不永久占 Active Context | **PASS** | `test_huge_tool_output_not_in_recent_window`（1500-token tool 输出移入 compacted 段）+ `test_fallback_summary_does_not_embed_raw_log`（原始全文不进 Summary，引用可回溯） |
| A8 | Under budget 不触发 Compact | **PASS** | `test_under_budget_no_compaction_needed` + `test_boundary_equal_is_not_over`（等值不压，严格大于才压） |
| A9 | 超阈值触发 Compact | **PASS** | `test_over_threshold_triggers_compaction` |
| A10 | 压缩后仍超限 → 不开始下一 Model Turn | **PARTIAL** | `test_overflow_result_signals_no_next_turn` 断言 `fits_budget=False` 信号 ✓；但 grep 确认 `fits_budget` 在生产代码中**仅 assembler.py 定义/计算，无任何消费方**（orchestrator/agent_loop 不读它）——"不开始下一 Turn"目前是约定信号，无运行时 Gate 强制 |
| A11 | Invariant：Compact 不删 Durable History（专门测试） | **PASS** | `test_compact_never_mutates_input_messages`（输入 5 条消息 dump 前后一致 + compacted/retained refs 合计=5，产出引用清单而非删除动作）+ `test_module_has_no_persistence_dependency`（**架构级断言**：compaction.py 不 import codeteam.session/git——依赖方向结构性保证） |
| A12 | Budget 基于 (provider, model) ModelMetadata；headroom 有测试 | **PASS** | `test_budget_formula_window_minus_output_minus_headroom`（1000-100-100=800）、`test_different_models_get_different_budgets`（C5：window 属于部署）、`test_fixed_overheads_shrink_budget`、`test_headroom_leaves_margin_below_window`、registry 侧 `test_headroom_default_ratio_is_ten_percent` / `test_custom_headroom_ratio` / `test_non_positive_budget_raises`（fail-fast） |
| A13 | CONTEXT_STALE → rebuild（不 fail Session） | **PASS** | `test_version_mismatch_raises_stale_error`、`test_aligned_versions_pass`、`test_uninitialized_sides_treated_as_fresh`、`test_stale_context_is_rebuildable_not_fatal`（组装纯函数 → rebuild 幂等：同材料两次组装 sections/tokens 全等）。附注：ContextMetadata.expected_summary_version 已在 session/models.py 落字段，但 SessionService 层的 stale 判定接线留 Day 6（assembler 层语义完整） |

## B. Provider / Model（§四十六 14 项收敛为 13 项 + §五十六）

| ID | 要求 | 状态 | Evidence |
|----|------|------|----------|
| B1 | Provider A / B 双 Mock 正常运行 | **PASS** | `test_provider_a_turn_completes` / `test_provider_b_turn_completes`（真实 complete 往返 + turn.started 归因） |
| B2 | invalid provider / model / missing credential / missing capability → 切换失败且旧 selection 保留（fail-closed） | **PASS** | 4 项测试（`test_invalid_provider_rejected_old_kept` 等）**均断言 `service.current_selection == 旧 selection`**（真实回退语义断言，非仅断言抛异常/REJECTED——疑点 C 核心关切已确认）+ `test_rejection_events_emitted` |
| B3 | Smaller context model → 先 Compact | **PASS** | `test_compact_hook_invoked_before_applying`（compat_check 在 APPLIED 前被调用且收到目标 selection）。附注：压缩执行权在调用方（本层判定放行），架构语义见 switching.py L206-213 注释 |
| B4 | Compact 后仍放不下 → 拒绝 Switch | **PASS** | `test_still_overflow_after_compact_rejects`（REJECTED + `context_still_overflow` + 旧 selection 保留） |
| B5 | Mid-turn switch → 排队不立即生效 | **PASS** | `test_midturn_switch_is_queued_not_applied`（QUEUED + mid-turn 时 current_selection 不变 + 当前 client 继续用旧模型完成） |
| B6 | 下一 Turn 使用新 Model | **PASS** | `test_queued_switch_applied_at_boundary`（boundary drain + 带 queued 标记事件 + 下一 Turn complete 返回 B 模型输出） |
| B7 | 双 Provider 429 等价错误 → 同归一化为 MODEL_RATE_LIMIT | **PASS** | `test_429_maps_rate_limit_with_retry_after`（openai）+ `test_rate_limit_error_type_maps`（anthropic）+ **`test_two_providers_same_code`**（A 的 429 与 B 的 rate_limit_error → 同 AgentErrorCode，provider_id 各自保留归因）+ `test_raw_and_normalized_paths_agree`（裸异常/归一化双路径收敛） |
| B8 | Resume 无 override → 恢复 Session 原 selection | **PARTIAL** | `test_resume_without_override_restores_session_selection`（registry 层：durable (provider_id, model_id) 重建 + metadata 验证通过）+ `test_corrupt_durable_ids_rejected_at_rebuild`（provider 下线 → 拒绝，S5 防御）。**缺口**：SessionService.resume 未接 ModelSwitchService/registry（service.py 仅有 Day4 的 `is_provider_available` 探测 @ L362-405）；测试 docstring 自认"完整接线属 Day 6 CLI 集成" |
| B9 | Resume 显式 override → 验证后应用 | **PARTIAL** | `test_resume_with_override_validated_before_apply`（switching 层：合法 override 生效 / 非法 override 拒绝且 selection 不动）。同 B8 缺口：SessionService 层无 override 入口 |
| B10 | AgentLoop / Planner / RepairLoop 零 Provider-specific 分支 | **PASS** | `test_core_runtime_has_no_provider_branches`（5 核心文件 grep '"openai"'/'"anthropic"'/'provider == ' 字面量）+ `test_core_runtime_depends_only_on_client_protocol`（agent_loop 对 llm 的 import 白名单 = 仅 base 契约层）+ registry 侧 `test_provider_config_is_ephemeral_not_pydantic`（adapter 与 core 边界） |
| B11 | 每 Turn 记录 provider/model/tokens/cost（事件审计） | **PARTIAL** | `test_turn_events_carry_selection_for_attribution`（turn.started/completed 各带 provider_id/model_id/turn_id ✓）。**缺口**：生产代码 switching.py L144-148 确认 `turn.completed` 仅含 turn_id/provider/model——**无 tokens/cost 字段**；Week1 usage tracker 是另一条链路且未与 turn 事件关联。per-turn cost 归因数据出口不完整 |
| B12 | API key 绝不进 Session/events | **PASS** | `test_selection_never_carries_credential_material`（ModelSelection dump 字段集 = {provider_id, model_id, reasoning_effort}，无凭证可达）+ `test_provider_config_is_ephemeral_not_pydantic`（含 factory 的 config 为 dataclass，不进 session.json）+ session 层既有脱敏链（models.py L41-74 `SENSITIVE_KEYS`/`_redact_metadata` + L250-264 source_message→`<redacted>`，Day4 R20 验收过）+ `test_message_template_not_raw_text`（异常文本不进用户可见消息） |
| B13 | Turn 内 ModelSelection immutable | **PASS** | 同 B5（mid-turn 请求不改 current_selection）+ `test_nested_turn_rejected`（嵌套 turn 状态机拒绝）+ registry `test_no_client_caching_per_turn_lifecycle`（client 生命周期与 Turn 对齐）+ `test_exception_inside_turn_still_drains_and_completes`（异常 Turn finally 语义：completed 事件 + drain 不丢） |

## C. K2 债务清偿（W4D3 遗留）

| ID | 要求 | 状态 | Evidence |
|----|------|------|----------|
| C1 | COMPACT 分支真实接线：成功 → recovery.completed + 继续；失败 → recovery.failed + 终态 | **PASS** | `test_compact_success_retries_once_and_completes`（**走 `orchestrator.run()` 公共路径**：READY + planner.calls==2 真实重试 + RECOVERY_COMPLETED 且无 RETRY_SCHEDULED）、`test_compactor_receives_provider_materials`（材料同源身份断言）、`test_compactor_not_injected_fails_terminal` / `test_compactor_exception_fails_terminal` / `test_provider_exception_fails_terminal`（三路失败均 FAILED + RECOVERY_FAILED）、`test_repeated_overflow_bounded_by_attempt_loop`（两轮 COMPACT + 第 3 次成功，事件流完整） |
| C2 | recovery.completed / failed 有真实发射方 | **PASS** | COMPACT 路径经 run() 公共断言（C1）；REREAD 路径 `test_reread_success_retries_operation`（RECOVERY_COMPLETED action=reread_and_regenerate + attempts==2）与 `test_rereader_not_injected_fails_terminal`（RECOVERY_FAILED）。W4D3 "零发射方"状态解除 |
| C3 | 「明确不做清单」文档落盘 | **FAIL（文档缺口）** | docs/design_decisions/ 下无 W4-not-doing-list.md 或等价物（grep 全仓确认）。day5.md 附录仅有"落位提议：待用户确认"；orchestrator.py 注释（L475、L533）仍引用"明确不做清单，Step 7 落盘"——承诺未兑现。DD-W4-D4-01/02 各含 Day4 范围不做清单段，但 W4D5 的 REPAIR/RETRIEVE_MORE_CONTEXT/REPLAN/ASK_USER 保持终态的决策无文档。**如实记录为文档追溯性缺口（W4D3 起延续）** |

## D. 工程证据

| ID | 要求 | 状态 | Evidence |
|----|------|------|----------|
| D1 | 全量回归 ≥ 1044 基线且不引入回归 | **PASS** | `.venv/bin/python -m pytest -q` → **1165 passed / 0 skipped, 25.12s, exit 0**（基线 1044 → +121：D5 新增 93 + Docker 6 项由 skip 转 pass + 其余为 D4 后续修复测试）。逐目录无失败 |
| D2 | 触达文件 ruff 0 error | **FAIL** | ruff 13 errors exit=1。**今日触达文件违规 2 处**：`codeteam/agent/orchestrator.py` I001（L15 import 块未排序——a32c9aa 将新 import 追加在文件末尾）+ F841（L547 `result` 赋值未使用）。今日**新增**文件（context×2 / llm×5 / 测试×5）与 `codeteam/session/` 包均 0 error ✓（Day4 ruff 债已还）。其余 11 条为非今日触达遗留：`llm/mock.py` 4 条 + `llm/openai_compatible.py` 4 条（Week1 旧文件）、`tests/context/test_build_context_budget.py` 1 条 + `test_compressor.py` 2 条（Week2 旧文件）。Coder 提交信息"触达文件 ruff 0 error"声称与实际不符（口径只覆盖了 4c78672 触达文件，漏了 a32c9aa 的 orchestrator.py） |
| D3 | DD-W4-D5-01/02 已写且 Evidence: PROPOSED | **FAIL** | 两文件均不存在（疑点 F 详述）。DD-W4-D4-01/02 存在且合格 |
| D4 | 测试工程约束：无真实网络 / 无 sleep / 无 skip 掩盖 / 全 Mock-Fake | **PASS** | grep 审计：tests/llm、tests/context（新增两文件）、tests/agent/test_recovery_executors.py 中 `time.sleep`/`pytest.skip`/`xfail`/`requests`/`httpx`/`urllib` 零命中（唯一命中为 docstring 文字）。全 Fake：_FakeClient/_RecordingEvents/_CharCounter/_ScriptedSummarizer/_RecordingCompactor/_OverflowOncePlanner；K2 测试 tmp_path 仅作 repository_root 占位 |

# 5. Tests

- tests/context/test_compaction.py — 27 项：触发判定 3 / Durable 分离 2（含架构断言）/ Recent Window 5 / Huge Tool Output 2 / working facts 4 / 计量防御 2 / 压后仍超 1 等
- tests/context/test_assembler.py — 24 项：权威重注入 6 / 分层顺序 1 / Budget 4 / 裁剪序 3 / CONTEXT_STALE 4 / to_messages 1 等
- tests/llm/test_registry.py — 20 项：注册解析 7 / 失败路径 3 / 凭证纪律 5 / client 重建 3 / Budget 公式 5（部分计入）
- tests/llm/test_switching.py — 22 项：双 Provider 4 / 拒绝矩阵 5 / 小窗口 3 / Turn Boundary 4 / persist 2 / resume 3 / 架构 2
- tests/llm/test_error_mapper.py — 20 项（a32c9aa 引入）：openai mapper 7 / anthropic 3 / chain 2 / classifier 归一化 7 / legacy 回归 1
- tests/agent/test_recovery_executors.py — 9 项：COMPACT 公共路径 6 / REREAD 直接路径 3

# 6. Test Execution Results

```text
全部实际执行（验收模式，无新增测试）：

1. .venv/bin/python -m pytest tests/llm tests/context tests/agent/test_recovery_executors.py -q
   → 133 passed in 0.85s, exit 0
2. .venv/bin/python -m pytest -q
   → 1165 passed in 25.12s, exit 0 【0 skipped】
3. .venv/bin/python -m pytest tests/sandbox/test_docker_runner_integration.py -q
   → 6 passed in 2.23s, exit 0（疑点 A 单独复核：真实执行非 skip）
4. .venv/bin/python -m ruff check <触达文件清单：context×2 + llm 包 + orchestrator +
   events + classifier + session 包 + tests/llm + tests/context + test_recovery_executors>
   → Found 13 errors, exit 1（逐条 file:line 见 §4-D2 与 §14-E）
```

**skip 明细：0 条**。原 6 条 skip（tests/sandbox/test_docker_runner_integration.py "Docker CLI is not installed"）全部转为真实执行——非掩盖，详见疑点 A。

# 7. Coverage

```text
pytest-cov 未安装（项目未配置）→ NOT_VERIFIED。
按任务要求覆盖率仅为辅助证据。本轮以行为断言真实性 + 全量回归为主要证据。
特别地：矩阵各项均落实到具体行为断言（非仅 docstring 自述），见 §4 证据列。
```

# 8. Benchmark

```text
NOT_EXECUTED（周度集中节奏，合规——day5 附录 §11 "仅设计，数据出口今日保证"）。
不得虚构任何性能数字。

数据出口完备性评估（供周度只读执行）：
- Compaction 七指标（§四十九）：CompactionResult 携带 tokens_before/after、
  summary_tokens、recent_window_tokens、recent_window_over_budget、compacted/retained
  refs、reason → Token Reduction / Compaction Latency（可计时）/ bytes 可直接取 ✓
- Lost Constraint Rate：需 LLM-in-loop 任务运行（Day 7 15-Task 评测时采集）；
  ContextSummary.confirmed_facts/decisions 字段可承载判定输入 ✓（依赖评测 harness）
- Provider A/B 对比（§四十八）：persist hook + registry.list_selections 支撑；
  per-turn cost 归因受 B11 缺口影响（turn.completed 无 tokens/cost，需从
  Week1 usage tracker 取数且无 turn_id 关联）→ 出口不完整 ⚠
结论：Context 侧出口完备；Model 侧 per-turn cost 归因出口有缺口（B11）。
```

# 9. Ablation

```text
NOT_EXECUTED（周度节奏，合规）。
- A3（No Compaction vs Naive Truncation vs Structured）：三组变体可由
  ContextCompactor(summarizer=None)（≈naive：role 统计）与调用方直传全量
  （no compaction）构造；recent window 引用清单支持 Repeated Retrieval 统计 ✓
- A4（Provider-neutral 架构度量）：test_switching.py 的架构测试已是静态度量样本
  （零 provider 字面量 + import 白名单）；"新增 Provider 需改 core 文件数"可由
  该 grep 协议程序化复测 ✓
结论：两组 Ablation 数据出口就绪。
```

# 10. Failure Cases

```text
无新的生产 Failure Case（全量 1165 全绿；无掩盖性 skip）。
本轮记录的已知限制（非缺陷，Day 6+ 范围或文档债务）：

L1: fits_budget=False 无生产消费方——"不开始下一 Model Turn"无运行时 Gate
    （矩阵 A10 PARTIAL 的根因；Turn Gate 接线属 Day 6 CLI/AgentLoop 集成）
L2: SessionService.resume 未接 ProviderRegistry/ModelSwitchService——B8/B9 完整
    链路（durable selection → rebuild client → override 事务）留 Day 6
L3: turn.completed 事件无 tokens/cost 字段——per-turn cost 归因出口不完整
    （建议 Day 6 接 usage tracker 时把 usage 快照并入 turn.completed payload）
L4: SwitchOutcome.COMPACTED_THEN_APPLIED 枚举值为死值——switching.py L215 起
    compacted 恒 False（压缩执行权在调用方 compat_check 回调，本层无法感知
    是否真实压缩过）。语义缺口非行为缺陷，观察项
L5: 无 context.compacted / context.stale_rebuilt 事件——day5 附录 §6/§7 修改
    清单要求但未实现；compaction 执行与 stale rebuild 不可从事件流观测
L6: DD-W4-D5-01/02 未撰写（矩阵 D3 FAIL；day5 附录 Step 7 未完成）
L7: 「明确不做清单」未落盘（C3；W4D3 起第三次记录该缺口）

Observations（非缺陷）：
O1: _validate_capability MVP 服务级硬编码 requires tools（switching.py L232-242
    注释自认；SwitchRequest 无 capability 需求字段——未来扩展点）
O2: CompactionRequest._target_within_window validator 为空实现（L86-91 注释
    自认跨字段断言移至 Compactor；test_target_must_be_below_window 覆盖行为）
```

# 11. Production Defects

```text
0 个阻塞性生产缺陷。
需要报告的偏差 2 项（非运行时缺陷）：
P1: Coder 提交信息声称"触达文件 ruff 0 error"与实测不符（orchestrator.py 2 处
    error）——属验证口径遗漏（只查了 4c78672 的触达文件），非故意造假；
    修复建议：ruff check --fix 可清 I001/F841（2 处均为自动可修），建议随 Day 6
    收尾一并处理。本轮不改生产代码。
P2: DD-W4-D5-01/02 缺失 + 不做清单未落盘（文档债务，见 L6/L7）。
```

# 12. Manager 疑点清单结论（A~F）

## A. skip 计数变化（6 → 0）

**结论：环境变化，非掩盖性改动。**

- 实测本机：`docker version` → Client 29.7.2 / daemon 响应正常；`docker image inspect codeteam-sandbox:latest` → sha256:546debef...（镜像在位）
- skip 判定是**运行时探测**（test_docker_runner_integration.py L38-89：`docker version` → `docker image inspect` → 容器内 python 探测），非静态条件
- `git log -- tests/sandbox/test_docker_runner_integration.py` → 仅 1 条（31a7786 Week3D6 创建后**零改动**）
- 单独复跑该文件 → **6 passed in 2.23s**（真实执行容器边界/网络阻断/socket 未挂载等安全测试）
- 判定：本机 Docker 环境自 W4D4 验收后变为可用（安装/启动 + 镜像已构建），skip 条件自然不满足。**非生产缺陷**。附带收益：6 项 Docker 安全测试首次真实执行且全绿

## B. 未提交改动的性质（assembler -2 / compaction +9 / switching +5）

**结论：Coder 收尾修复，已随 4c78672 提交，内容最小且有配套测试。验收对象 = 当前 HEAD（工作区干净）。**

逐条审计（git show 4c78672）：

| 文件 | 改动 | 性质判定 | 配套测试 |
|---|---|---|---|
| assembler.py -2 | 移除未用 `import BaseModel` | 纯 lint 修复 | 现有 24 项全绿即回归 |
| compaction.py +9 | `_fallback_summary` 补必填 `summary_version=1`（docstring 说明 compact() 随后经 model_copy 按版本链重算，此占位不进结果） | 修复真实缺陷：缺必填字段时未注入 summarizer 的 compact() 直接 ValidationError，**默认压缩器不可用** | `test_first_compaction_starts_at_version_1` 及所有未注入 summarizer 的 fallback 路径测试（K2 测试的 _RecordingCompactor 不经此路径，但 context 系列测试覆盖） |
| switching.py +5 | `except RegistryError` 兜底 → CAPABILITY_MISMATCH 拒绝路径 | 修复真实缺陷：capability mismatch 抛出的 RegistryError 此前未被捕获，**REJECTED 路径不可达**（直接异常穿透） | `test_capability_mismatch_rejected_old_kept`（docstring 明注"修复回归：曾未捕获 RegistryError 直接抛出"，断言 REJECTED + 回退） |

两处修复均为"测试先行复现 → 最小修复"（提交信息自述"均已先复现确认"，与测试注释互证）。**判定为合法收尾修复，非掩盖**。

## C. 矩阵覆盖真实性（§四十六 24 项逐项对照）

**结论：19 项有直接行为测试；4 项 PARTIAL（信号/原语有、运行时接线缺）；1 项文档缺口（C3）。无"仅断言抛异常"的伪覆盖。**

- **"旧 selection 保留"验证**（疑点核心）：4 个拒绝测试（invalid provider/model/credential/capability）均含 `assert service.current_selection == _sel("prov-a", "model-a")` **回退语义断言**，且 _seed() 先真实应用一个 selection 作为旧值——非仅断言 REJECTED outcome。✓
- 缺直接测试/仅间接证据项：
  - A10：`fits_budget` 信号有断言，但无"Gate 阻止下一 Turn"行为测试（生产无消费方，grep 确认）
  - A13：rebuild 幂等有断言；"不 fail Session"的 Session 层集成无（assembler 层语义完整）
  - B8/B9：switching/registry 层原语验证充分；SessionService 层接线无（测试 docstring 自认 Day 6）
  - B11：provider/model ✓，tokens/cost ✗（生产事件无该字段）
- C3：不做清单文档缺失（非测试覆盖问题）

## D. K2 是否真还债（公共路径升级）

**结论：核心真还债。COMPACT 分支达成公共路径化；REREAD 保持直接路径但有如实标注（其阶段无生产调用方）。**

- W4D3 遗留问题："私有方法 `_execute_with_recovery` 直接调用应升级为公共路径测试"
- 本轮核实：`TestCompactRecoveryPublicPath` 6 项全部经 `orchestrator.run()` 驱动（断言 `result.status == TaskStatus.READY`、事件在 `result.events`、planner.calls==2）——**公共路径 ✓**
- `TestRereadRecoveryDirectPath` 3 项仍直接调 `_execute_with_recovery`，但 docstring 明确标注原因："PATCH_APPLY 阶段尚无 run() 公共调用方（execute_plan_step 未接线），与 W4D3 TestRecoveryLoopDirect 同一架构边界，如实标注"——该阶段公共路径化依赖 Day 6 的 execute_plan_step 接线，当前不可达路径无法走公共入口，标注诚实
- recovery.completed/failed 发射方：COMPACT（公共）+ REREAD（直接）双路径均有事件断言 ✓（W4D3 O2 解除）

## E. ruff 触达面（含 Day4 还账）

**结论：今日触达文件 2 处 error（FAIL）；session 包 0 error（Day4 债已还）；另 11 处为 Week1/2 遗留非今日触达。**

逐条（file:line）：

今日触达（矩阵 D2 范围）：
```
codeteam/agent/orchestrator.py:15   I001  import 块未排序（a32c9aa 追加 import 于文件末尾所致）
codeteam/agent/orchestrator.py:547  F841  `result` 赋值未使用（_try_compact）
```
——两项均可 `ruff --fix` 自动修复；修复建议已列入 §11-P1（本轮不越权重改生产代码）。

Day4 还账核查：
```
codeteam/session/（四文件 + 测试）→ 0 error ✓
```
——W4D4 验收时已知的 RUF022/I001 已被清理（Day4 P1 修复周期内完成）。

非今日触达遗留（记录备查，不计入 D2）：
```
codeteam/llm/mock.py:3             I001 / UP035 / F401(AgentFinalOutput 未用) / UP006(List)  [Week1]
codeteam/llm/openai_compatible.py:17 I001 / :19 UP035 / :53,:56 TRY201                    [Week1]
tests/context/test_build_context_budget.py:1 I001                                           [Week2]
tests/context/test_compressor.py:8 I001 / :175 RUF059                                       [Week2]
```
注：Day5 新增的 5 个 llm/context 文件与 5 个测试文件全部 0 error——新代码纪律良好，遗留均为旧文件。

## F. DD 文档存在性

**结论：DD-W4-D4-01/02 齐全且合格；DD-W4-D5-01/02 不存在（FAIL）。**

- DD-W4-D4-01（Durable Domain State vs Runtime Serialization）：✓ 存在。含 Problem/Context/Requirements/**Alternatives（Option A pickle vs Option B durable+reconstruct 逐维对比）**/Decision（13 项子决策落地表）/Why/Trade-offs/Consequences/When to Revisit/**Evidence: PROPOSED**（明确"不声称任何性能结论"，Benchmark/Ablation 待周度）——结构与 day4 §八十一骨架吻合
- DD-W4-D4-02（Snapshot + Event Log）：✓ 存在。三方案对比（Snapshot-only / Event-only / Snapshot+Event）+ 9 项子决策表 + "load latency 不随 events 增长目前是设计论断非实测结论"的诚实声明
- DD-W4-D5-01（Structured Context Compaction）：✗ **不存在**
- DD-W4-D5-02（Provider-neutral Model Runtime）：✗ **不存在**
- 判定：矩阵 D3 FAIL。day5 附录 Step 7（"「明确不做清单」+ DD-W4-D5-01/02 + 13 节总结"）整步未执行。待验证架构假设（H1~H6）在文档缺失期间全部维持 INSUFFICIENT_EVIDENCE（见 §12 附表）

# 13. Acceptance（汇总）

| 验收项 | 结果 | Evidence |
|--------|------|----------|
| A. Context 矩阵 13 项 | **11 PASS + 2 PARTIAL**（A10/A13） | §4-A 表 |
| B. Provider/Model 矩阵 13 项 | **10 PASS + 3 PARTIAL**（B8/B9/B11） | §4-B 表 |
| C. K2 债务 3 项 | **2 PASS + 1 FAIL**（C3 文档缺口） | §4-C 表 |
| D. 工程证据 4 项 | **2 PASS + 2 FAIL**（D2 ruff / D3 DD 缺失） | §4-D 表 |
| day5 §五十六完成标准 | 主体达成；DD/不做清单/部分接线缺口 | §10 L1-L7 |

# 14. Regression

```text
Full suite: 1165 passed / 0 skipped（基线 1044/6 → +121 且零失败）
  - 93 项 D5 新增测试全绿
  - 6 项 Docker 测试 skip→pass（环境变化，真实执行）
  - 22 项为 D4 后续修复（P1 复验等）带来的增量
低于基线项：无。
Docker 安全测试（网络阻断/socket 未挂载/主机秘密不可读）首次真实执行全绿。
Benchmark/Ablation Regression: 不适用（周度未执行）。
```

# 15. Risks and Limitations

```text
已知限制（L1~L7 见 §10）：最关键三项——
L1  fits_budget 无消费方（A10）：当前"不开始下一 Turn"靠调用方自觉读信号，
    AgentLoop 未接线 Gate；若 Day 6 不接，压缩后仍超的 Turn 仍可能发出
L2  SessionService 未接 ModelSwitchService（B8/B9）：resume 的 selection
    重建/override 目前只有 registry/switching 层原语，端到端链路断在 service 层
L3  turn.completed 无 tokens/cost（B11）：per-turn 成本归因需 Day 6 拼接
    usage tracker，评测口径依赖该数据

观察项：L4（COMPACTED_THEN_APPLIED 死值）/ L5（无 context.* 事件）/
O1（capability 硬编码）/ O2（空 validator）

Test limitations:
- 样本量：24 项矩阵为确定性单元/组件级验证；无 LLM-in-loop 端到端（Day 7 15-Task）
- 无覆盖率数据（pytest-cov 未配置）
- A4 架构度量为静态 grep 协议（字面量清单有限），不排除间接 provider 耦合
```

# 16. Artifacts

```text
本报告：test_log/2026-08-20_week4_day5_test_log.md
被测工件（Coder 产出，未改动）：
  codeteam/context/{compaction,assembler}.py
  codeteam/llm/{registry,error_mapper,switching,base,__init__}.py
  codeteam/agent/orchestrator.py（K2 接线）
  codeteam/events.py（5 新事件）/ failures/classifier.py（①b 分支）
  codeteam/session/models.py（ContextMetadata 升级）
  tests/context/{test_compaction,test_assembler}.py
  tests/llm/{test_registry,test_switching,test_error_mapper}.py
  tests/agent/test_recovery_executors.py
验收依据：learning-plan/week4/day5.md §四十六 / §五十六 / 附录 §15
```

# 17. Interview Evidence

```text
可支撑的客观证据（全部实测，无虚构）：
- 权威重注入的反直觉证明：构造"Summary 故意漏掉用户约束/谎报 step 完成"的对抗样本，
  断言 Active Context 仍从 TaskSpec/Plan 取真值——LLM 摘要幻觉无法污染安全约束与
  执行状态（C1/C2 两类事故的结构性防御）
- Durable 分离的架构级断言：compaction 模块被测试强制"不 import 任何持久化层"，
  "绝不删历史"由依赖方向保证而非口头承诺
- Switch 事务 fail-closed：4 类非法切换全部断言旧 selection 真实回退（非仅异常）；
  mid-turn 请求排队、嵌套 Turn 拒绝、异常 Turn finally 不丢事件
- 双 Provider 错误归一化：openai 429 与 anthropic rate_limit_error → 同一
  AgentErrorCode 且保留各自 provider_id 归因；裸异常/归一化双路径收敛测试
- K2 还债的公共路径证据：COMPACT 恢复经 run() 全路径，planner 真实第二次调用
  （retry once）+ recovery.completed 事件 + RETRY_SCHEDULED 不出现
- 诚实限制：fits_budget 尚无消费方、resume-selection 链路断在 service 层、
  per-turn cost 归因缺口、DD-W4-D5 未写——全部如实记录
```

# 18. Final Conclusion

```text
Test Development:        N/A（验收模式，未写测试）
Correctness:             PASS（1165/0 全绿；矩阵 24 项 19 PASS + 4 PARTIAL + 1 文档项）
Safety:                  PASS（fail-closed switch 回退断言 + 凭证纪律三层 +
                          session 脱敏链 + Docker 安全测试首次真实执行 6/6）
Observability:           PARTIAL（recovery.completed/failed 补齐发射方、turn./model. 
                          5 事件新增；但 turn.completed 无 tokens/cost、
                          无 context.compacted/stale_rebuilt 事件）
Benchmark:               NOT_EXECUTED（周度节奏合规；Context 侧数据出口完备，
                          Model 侧 per-turn cost 出口有 B11 缺口）
Ablation:                NOT_EXECUTED（周度节奏合规；A3/A4 出口就绪）
Design Decision:         INSUFFICIENT_EVIDENCE（DD-W4-D5-01/02 未撰写——较 W4D3
                          的"未撰写+假设已记录"更进一步缺失文档载体；DD-W4-D4-01/02
                          已补写且含完整备选对比与 PROPOSED 状态）
Overall Module Acceptance: PARTIAL
  —— 运行时核心（压缩分层/预算推导/切换事务/错误归一化/K2 还债）正确且证据充分；
     阻碍 FULL 的四件事：① orchestrator.py 2 处 ruff（可自动修复）② DD-W4-D5-01/02
     与不做清单未落盘（Step 7 未执行）③ SessionService↔ModelSwitchService 接线留
     Day 6 ④ turn tokens/cost 归因缺口。①②可立即补齐，③④属既定 Day 6 范围。

Manager 疑点 A~F：全部有结论（A=环境变化非掩盖，B=合法收尾修复已提交且有配套
测试，C=19 直接 + 4 部分 + 回退语义为真实断言，D=COMPACT 公共路径达成/REREAD 
如实标注，E=今日触达 2 处 FAIL+session 包已还账+11 处旧遗留备查，F=D4 齐全合格/
D5 缺失）。
```

---

## 附：待验证架构假设（DD-W4-D5-01/02 未撰写 → 全部 INSUFFICIENT_EVIDENCE）

| # | 隐含决策 | 当前证据 | 周度后预期结论 |
|---|---------|---------|---------------|
| H1 | Structured Compaction（权威重注入 + 结构化 Summary）vs naive truncation | 对抗样本测试（Summary 漏报/谎报不影响权威段）| 待 A3 Ablation（lost-constraint / plan continuity） |
| H2 | Summary 不是 safety/constraints/plan 的权威来源 | A1/A2/A3 重注入测试 | 已有正确性证据；价值量化待 A3 |
| H3 | Budget 由 (provider, model) ModelMetadata 推导（非固定常量） | 同名模型不同部署 → 不同预算测试 | 待 Provider Benchmark 联动验证 |
| H4 | Turn Boundary 切换 + 事务 fail-closed | mid-turn 排队/回退断言 | 待 Mid-turn 场景端到端（Day 7） |
| H5 | Provider-neutral：新增 Provider = 新增 adapter 零 core 改动 | 静态 grep 架构测试（字面量 + import 白名单） | 待 A4 程序化度量（core files 改动数） |
| H6 | 错误归一化收敛（裸/归一化双路径同 code） | test_raw_and_normalized_paths_agree | 已有正确性证据；覆盖率随真实 Provider 接入扩展 |

在 DD 文档与周度 Benchmark/Ablation 数据到位前，以上全部标记 INSUFFICIENT_EVIDENCE，不得宣称 SUPPORTED。

---

# 19. Coder 修复后复验（2026-08-21）

## 19.1 P2 Observability 修复

```text
修复项：
- recent_window_over_budget=True 且 tokens_after <= target_context_tokens：
  允许发 recovery.completed，并保留 observation=recent_window_over_budget 审计信息。
- recent_window_over_budget=True 且 tokens_after > target_context_tokens：
  不再由 _try_compact() 发 recovery.completed。
  外层恢复失败路径发 recovery.failed，避免一次最终失败的 COMPACT recovery
  同时出现 misleading recovery.completed。

修复文件：
- codeteam/agent/orchestrator.py
- tests/agent/test_recovery_executors.py
```

## 19.2 新增/调整测试证据

```text
新增测试：
- tests/agent/test_recovery_executors.py::
  TestCompactRecoveryPublicPath::
  test_recent_window_over_budget_and_still_over_target_fails_without_completed_observation

保留并复验：
- test_compaction_still_over_budget_fails_terminal
- test_recent_window_over_budget_is_observable
- compactor 未注入/异常 fail-closed
- Day3 兼容 recovery integration
- 50 Case fault injection
```

## 19.3 实测命令

```text
.venv/bin/python -m pytest tests/agent/test_recovery_executors.py -q
  12 passed in 0.55s

.venv/bin/python -m pytest tests/failures/test_fault_injection.py -q
  54 passed in 0.08s

.venv/bin/python -m pytest tests/agent/test_recovery_integration.py -q
  9 passed in 0.10s

.venv/bin/python -m pytest tests/agent/test_recovery_executors.py tests/failures/test_fault_injection.py tests/agent/test_recovery_integration.py -q
  75 passed in 0.52s

.venv/bin/python -m ruff check codeteam/agent/orchestrator.py tests/agent/test_recovery_executors.py
  All checks passed!

.venv/bin/python -m pytest -q
  1162 passed, 6 skipped in 11.85s

.venv/bin/python -m pytest tests/sandbox/test_docker_runner_integration.py -q -rs
  6 skipped
  原因：Codex sandbox 内访问 Colima Docker socket 权限不足：
  permission denied while trying to connect to unix:///Users/sqlee/.colima/default/docker.sock
```

# 20. Updated Final Conclusion

```text
Day5 功能验收：PASS

已闭环：
- ruff 触达文件已通过。
- DD-W4-D5-01 / DD-W4-D5-02 已补齐。
- W4-not-doing-list 已补齐。
- P1 _try_compact() 已消费 CompactionResult.tokens_after：
  压缩后仍超 target_context_tokens 会 fail closed，不 retry 烧配额。
- P1 recent_window_over_budget 已有观测事件：
  仅在压缩整体达标时记录 recovery.completed observation。
- P2 recent_window_over_budget + over-budget 组合语义已修复：
  最终失败的 COMPACT recovery 不再出现 misleading recovery.completed。

仍保留为后续债务：
- SessionService / CLI 与 ModelSwitchService 的完整 resume override 链路留后续集成。
- turn.completed 暂无 tokens/cost 字段。
- 周度 Benchmark / Ablation 尚未执行。
- Docker boundary 在当前 Codex sandbox 中因 Docker socket 权限不足被 skip；
  本次全量 pytest 只能证明非 Docker integration 路径与 skip 机制通过，
  不能宣称真实 Docker 边界在该沙箱中完成复验。

最终结论：
Day5 功能验收通过；Benchmark/Ablation 与部分集成链路留后续。
```
