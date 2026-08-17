# Week 4 Day 2 独立验收报告

**日期**: 2026-08-18
**角色**: Test / Evaluation Agent（独立验收）
**分支**: week4（工作区干净，无未提交改动）
**授权范围**: 只读检查 + 全量测试 + 临时脚本对抗性探索；Benchmark/Ablation 未执行；Commit/Merge/Push 未授权（未执行）

---

# 1. Evaluation Summary

对 Week 4 Day 2（Test-Driven Repair Loop：Patch → Verification → Repair 闭环）执行独立验收：

- 全量 pytest 独立复跑：**871 passed / 0 failed / 0 skipped**（11.71s），与经理基线一致
- Day 2 模块 83 个测试全部通过，覆盖率 **97%**（431 语句 / 11 未覆盖）
- R1-R18 全部 PASS，R19 PARTIAL（PATCH_FAILED 事件回放语义缺陷 F3）
- 关键断言（R3 恰好 max 次 / R2 上下文含首次失败 / R14 回归零执行 / R7 truncated 构造）经源码级复核真实有效
- 对抗性探索 7 组：6 组行为正确，1 组发现生产缺陷（F3）
- **验收项 FAIL：DD-W4-D2-01 未落盘**（day2.md 5535 行验收清单明确要求，docs/design_decisions/ 下只有 DD-W4-D1-01.md）
- Benchmark/Ablation 未执行（任务规定每周集中），周度评测数据缺口清单见 §8/§9

# 2. Capability Mapping

| 项 | 内容 |
|----|------|
| Module | codeteam/verification/ + codeteam/repair/ + agent/orchestrator.execute_plan_step + events.py |
| Primary | **Agent Runtime** — Feedback Loop / Retry-Repair Lifecycle / Stopping Condition |
| Secondary | **Tool Runtime**（Verification 三层转换走 Week 3 安全链）、**Evaluation**（Test Oracle / failure_signature 行为验证数据源） |
| 已验证 | 1. 循环终止性强不变量（恰好 max 次调用）；2. Regression Cascade 语义；3. 环境问题≠代码问题；4. 状态推进不变量（R16/R17）；5. 安全边界（R18） |

# 3. Repository Inspection

```
Technical Stack:      Python 3.11 + pydantic v2 + pytest 9.x
Target Modules:
  - codeteam/verification/models.py     VerificationKind/Status(requires_repair)/Request/Result/extract_failure_signature
  - codeteam/verification/service.py    VerificationService（三层转换，执行只经注入 executor）
  - codeteam/repair/models.py           RepairLoopOutcome/Result、RepairAttempt(frozen)、RepairContext、RepairRunOutcome/Result(repair_count)
  - codeteam/repair/loop.py             RepairLoop.run_candidate/run、RepairAgent Protocol、MockRepairAgent
  - codeteam/agent/orchestrator.py      execute_plan_step（依赖守卫/状态推进/事件回放）
  - codeteam/events.py                  verification.* 4 个 + repair.* 7 个事件类型
Existing Tests:        tests/verification/(24) tests/repair/(30) tests/agent/(5 组新增)
Git Status:            干净
Implementation Notes:
  - RepairLoop 不自己 subprocess / git apply / 调模型——只协调 GitWorkspace 与 VerificationService
  - VerificationService 默认 SafeCommandExecutor，测试注入 FakeExecutor（安全链不可绕过）
```

# 4. Requirement Coverage（R1-R19）

| ID | Requirement | Status | 证据测试 |
|----|-------------|--------|---------|
| R1 | 首次成功 → SUCCESS、repair_count==0、agent 零调用 | **PASS** | test_t1_first_patch_success（三个断言全部存在且精确） |
| R2 | 首次失败二次成功 → repair_count==1、首次 failure 进 RepairContext | **PASS** | test_t2_fail_once_then_success（`"FIRST" in agent.calls[0].failure_tail`） |
| R3 | 达 max → REPAIR_EXHAUSTED、agent 恰好 max 次 | **PASS** | test_t3：`len(agent.calls) == max_attempts`（精确相等，非 ≤）+ `len(attempts)==max` |
| R4 | Target PASS + Regression FAIL → 不 SUCCESS、下轮上下文来自回归失败 | **PASS** | test_t4（attempts[0].failure_signature == 回归签名） |
| R5 | 命令不存在 → EXECUTION_ERROR、agent 零调用 | **PASS** | test_t5_start_failed_no_repair |
| R6 | 超时 → EXECUTION_ERROR、agent 零调用 | **PASS** | test_t6_timed_out_no_repair |
| R7 | truncated 是 metadata，判定按 exit code | **PASS** | test_truncated_exit_0_still_passed（真实构造 stdout_truncated=True + exit 0 → PASSED） |
| R8 | BLOCKED → agent 零调用 | **PASS** | test_t8_blocked_no_repair |
| R9 | Regression PASS 但 Target FAIL → 仍失败 | **PASS** | 语义由 T14 保证：Target FAIL 时回归根本不执行，结果不可能 SUCCESS（见 R14） |
| R10 | 相同 failure_signature 连续出现可记录 | **PASS** | test_t10_same_failure_signature_repeated |
| R11 | agent 空串 → EXECUTION_ERROR 无无限循环 | **PASS** | test_t11 + 独立 E6（恰好 1 次调用、NO_PATCH） |
| R12 | Patch 无法应用 → PATCH_FAILED ≠ TEST_FAILED、验证不调用 | **PASS** | test_patch_failed_skips_verification（`svc.called_verification_ids == []`） |
| R13 | checkpoint_id 正确关联 | **PASS** | test_t13_checkpoint_hook_linkage（hook_calls==[1]、checkpoint_id=="cp-1"） |
| R14 | Target FAIL 时回归不执行 | **PASS** | test_t14（`called_verification_ids == ["vt"]` 精确断言） |
| R15 | 上限后不再调用模型 | **PASS** | T3 精确相等断言 + 独立 E1（max=0 时零调用） |
| R16 | 不变量：Target FAIL → task not complete 等 | **PASS** | test_exhausted_progression / test_success_progression |
| R17 | execute_plan_step 状态推进三分支 | **PASS** | success_progression / exhausted_progression / execution_error_keeps_intermediate_state |
| R18 | 安全边界：执行只经注入 executor | **PASS** | service.py 无 subprocess；全映射测试注入 FakeExecutor；BLOCKED 不触发 repair |
| R19 | 事件类型存在 + 回放数据正确 | **PARTIAL** | 类型存在 ✓（events.py 11 个）；正常 attempt 回放 ✓；**PATCH_FAILED attempt 回放发出误导性 repair.patch_applied（缺陷 F3）** |

# 5. Tests（独立复核 coder 测试有效性）

| 复核点 | 结论 |
|--------|------|
| R3 是否断言"恰好 max"而非"≤ max" | ✓ `assert len(agent.calls) == max_attempts` 精确相等（test_loop.py:260）+ attempts 数量同断言 |
| R2 是否断言第二次上下文含首次失败 | ✓ marker "FIRST" 注入首次失败 stderr，断言进入 `agent.calls[0].failure_tail`（test_loop.py:234） |
| R14 是否断言回归零执行 | ✓ `svc.called_verification_ids == ["vt"]`（精确列表断言，test_loop.py:493） |
| R7 是否真实构造 truncated | ✓ FakeExecutor 返回 stdout_truncated=True + exit 0（test_service.py:112-125） |
| 其他质量点 | ✓ T12 断言 verification 零调用；T13 断言 hook 调用序列；test_models 覆盖 frozen/attempt_no≥1/failure_tail 边界 |

# 6. Test Execution Results

```
命令:      .venv/bin/python -m pytest -q
退出码:    0
通过:      871
失败:      0
跳过:      0
耗时:      11.71s

Day 2 模块子集: tests/verification/ tests/repair/ tests/agent/ → 83 passed / 1.81s
ruff:     目标目录（codeteam/verification codeteam/repair codeteam/agent codeteam/events.py
          tests/verification tests/repair tests/agent）→ All checks passed（0 error）
```

# 7. Coverage（Day 2 模块）

```
Name                             Stmts   Miss  Cover
codeteam/agent/orchestrator.py     114      4    96%   303-305, 367-368
codeteam/repair/loop.py            107      6    94%   164, 230-236, 302, 376
codeteam/repair/models.py           91      0   100%
codeteam/verification/models.py     80      1    99%   173
codeteam/verification/service.py    39      0   100%
TOTAL                              431     11    97%
```

未覆盖说明：
- orchestrator.py:303-305：_fail 的防御分支（Day 1 已有）
- orchestrator.py:367-368：execute_plan_step 非 READY 状态进入的拒绝路径（**本验收 E4 已验证行为正确，coder 测试未覆盖**）
- loop.py:230-236：repair_agent.propose_patch 抛异常 → NO_PATCH 路径（coder 测试未覆盖；建议补 1 条）
- loop.py:164/302/376：PATCH_FAILED/inconclusive 上下文分支（本验收 E2/E7 已验证行为正确）
- verification/models.py:173：AssertionError 防御兜底行

# 8. Benchmark

**状态：NOT_VERIFIED（任务规定每周集中执行，本轮不执行）。**

生产代码数据可用性审查（对照 day2.md 一百一十八节指标）：

| 周度指标 | 数据源 | 可用性 |
|---------|--------|--------|
| repairs | RepairLoopRunResult.repair_count | ✓ 可用 |
| success | RepairRunOutcome | ✓ 可用 |
| verification latency | VerificationResult.duration_ms | ✓ 可用 |
| failure signature 序列 | RepairAttempt.failure_signature | ✓ 可用 |
| **target latency** | — | ✗ **缺口**（loop 内 target 验证阶段无独立计时） |
| **tool calls** | — | ✗ **缺口**（无 tool call 计数/分类） |
| **tokens** | — | ✗ **缺口**（RepairAgent 协议只返回 str，无 usage；LLMPlanner 同） |
| attempt 明细 | RepairAttempt（frozen：checkpoint_id/patch_hash/changed_files/outcome） | ✓ 可用 |
| full regression 数据 | FULL_REGRESSION kind 预留未执行 | ✗ 预留（day2 设计如此） |

**数据缺口清单（周度评测前需 Coder 补齐）**：
1. RepairLoop 每次 target 验证的 wall-clock（或复用 VerificationResult.duration_ms 聚合，需明确口径）
2. 每次 repair 的模型 token 用量（RepairAgent 协议需扩展返回 usage）
3. Tool call 计数/类型（当前无）
4. 事件流中无 repair 起止时间戳（events 无 timestamp 字段，影响 makespan 统计）

# 9. Ablation

**状态：NOT_VERIFIED（未执行）。** day2 相关消融（如 repair loop 开关、regression cascade 开关）留待周度集中评测。

# 10. Failure Cases

| ID | Module | Trigger | Root Cause | Mitigation | Regression Test |
|----|--------|---------|-----------|------------|-----------------|
| FC-W4D2-001 | agent/orchestrator.py 事件回放 | attempt.outcome=PATCH_FAILED 且 affected_paths 非空 | apply_patch 失败路径仍携带预期 affected_paths（workspace.py:243/259/269），回放只看 changed_files 非空即发 applied | 见缺陷 F3 建议 | 缺失（coder 测试仅覆盖正常 applied 回放） |

# 11. Production Defects

## Defect F3: PATCH_FAILED attempt 被回放为 repair.patch_applied（事件语义误导）

### Module
`codeteam/agent/orchestrator.py`（execute_plan_step 事件回放，:411-417）
根因链路：`codeteam/git/workspace.py` apply_patch 失败路径仍返回 `affected_paths` → `codeteam/repair/loop.py:277-280` RepairAttempt.changed_files 非空 → 回放发 applied

### Test
无 coder 测试覆盖（本验收对抗性探索 E3 发现，脚本 tmp/adversarial_w4d2.py）

### Preconditions
RepairAgent 生成的 patch 无法应用（context 行不匹配/文件已变化）。

### Reproduction
1. 初始候选 Target FAIL 或 Regression FAIL 进入 repair
2. agent 返回一个无法 apply 的 patch（如 make_patch("x = 999", "x = 1000")）
3. attempt.outcome = PATCH_FAILED，但 patch_hash 非空、changed_files=('m.py',)
4. execute_plan_step 回放 → 发出 repair.patch_proposed **和 repair.patch_applied**

### Expected
PATCH_FAILED 的 attempt 只应发出 repair.patch_proposed（或一个 patch_failed 类事件），不应发出 applied——事件流应忠实反映"patch 没有落地"。

### Actual
事件流声称 patch 已应用（repair.patch_applied），与磁盘事实相反。

### Reproducibility
稳定复现（确定性：apply_patch 失败路径恒返回 affected_paths）。

### Suspected Root Cause
回放条件只看 `attempt.changed_files` 非空，未结合 `attempt.outcome` 判断；而 loop.py 对 PATCH_FAILED attempt 的 changed_files 取自 patch_result.affected_paths（失败时仍非空）。

### Impact
- 审计 Trace 失真：下游按事件流重放会误以为 patch 已落地
- 与 R19 的事件数据正确性契约冲突
- 未来 Session 持久化/重放（Day 4）依赖此事件流

### Suggested Direction
回放条件加 `attempt.outcome != RepairOutcome.PATCH_FAILED`；或 loop.py 对 PATCH_FAILED attempt 的 changed_files 置空（语义更本源）；建议同时补回归测试（PATCH_FAILED attempt 只发 proposed）。

# 12. Design Decision Verification

```text
Decision:      DD-W4-D2-01 Tiered Verification Strategy
存在性:        ✗ FAIL — docs/design_decisions/ 下只有 DD-W4-D1-01.md，
               DD-W4-D2-01.md 未落盘（day2.md 八十三节/一百一十九节/
               5535 行验收清单均明确要求）
内容核对:      BLOCKED（文件不存在）
Evidence status: BLOCKED（无法核对 PROPOSED）

行为证据（独立于文档）:
  - Tiered 策略已实现：Target → Related Regression（Full 预留）
  - T4/T14/T9 测试证明 cascade 语义正确
  - 但"策略文档"缺失 → 面试证据链不完整

Evaluation:    NOT_VERIFIED（文档缺失，无法给出 SUPPORTED 级结论）
               实现行为维度：有测试支持（PASS），文档维度：MISSING_ARTIFACT
```

# 13. Acceptance

| 验收项 | 结果 | 证据 |
|--------|------|------|
| R1-R18 | PASS × 18 | §4 逐项证据 |
| R19 | PARTIAL | 类型存在+正常回放 ✓；F3 缺陷 |
| 全量回归 | PASS | 871 passed，与基线一致 |
| ruff | PASS | 目标目录 0 error |
| DD-W4-D2-01 落盘 | **FAIL** | 文件不存在（MISSING_ARTIFACT） |
| Benchmark | NOT_VERIFIED | 未执行（规定） |
| Ablation | NOT_VERIFIED | 未执行（规定） |

# 14. Regression

- 全量套件独立复跑：871 passed / 0 failed / 0 skipped（11.71s），与经理基线一致
- Day 1 修复（F1/F2/D1/S1）无回归：全量通过且 Day 1 测试仍在
- 无历史 Benchmark 基线，无可对比的性能回归

# 15. Risks and Limitations

```
未测试内容:
  - repair_agent 抛异常路径（loop.py:230-236，行为已由本验收推理确认但无固化用例）
  - execute_plan_step 非 READY 进入（orchestrator.py:367-368，E4 已验证行为）
  - 并发 run/execute_plan_step（未验证线程安全）
  - should_stop 在 execute_plan_step 层未暴露（loop 层支持）

无法验证内容:
  - Benchmark / Ablation（未执行）
  - DD-W4-D2-01 内容与 Evidence status（文件不存在）

环境限制:
  - 对抗性探索全部使用真实临时 Git 仓库（无外部依赖）

残留风险:
  - F3 事件语义缺陷影响未来重放（非阻断，修复成本低）
  - DD-W4-D2-01 缺失使 Design Decision 证据链不完整（面试证据缺口）

后续建议:
  1. Coder 修复 F3（回放条件加 outcome 判断或 changed_files 置空）+ 补回归测试
  2. Coder 补落 DD-W4-D2-01（内容按 day2.md 八十三节，Evidence=PROPOSED）
  3. Coder 补 2 条测试：agent 异常路径、非 READY 进入路径
  4. 周度评测前补齐 §8 数据缺口（token/tool calls/target latency）
```

# 16. Artifacts

```
本报告: test_log/2026-08-18_week4_day2_test_log.md（唯一写入文件，Allowed Paths 内）
对抗性脚本: $CLAUDE_JOB_DIR/tmp/adversarial_w4d2.py + adv_w4d2_e7.py（系统临时目录）
未创建 Benchmark/Ablation 文件（未授权）
未修改任何生产代码/测试代码（codeteam/、tests/、evals/ 均只读）
未执行 Commit / Merge / Push（未授权）
```

# 17. Interview Evidence

```
本次验收可支撑的客观证据：
- 871 全量测试独立复跑通过，Day 2 模块 97% 行覆盖
- 修复循环终止性通过"恰好 max 次调用"的精确断言证明（强不变量）
- 环境问题≠代码问题的分层语义（START_FAILED/TIMED_OUT/BLOCKED 均零修复调用）有 3 组独立测试
- Regression Cascade（Target→Related）语义正确：回归失败驱动修复、Target 失败时不浪费回归执行
- 安全边界：Verification 执行只经注入 executor（Week 3 安全链），无法绕过
- 对抗性探索发现 PATCH_FAILED 事件回放语义缺陷（F3）——独立验收的增量价值

诚实限制：
- repair_agent 异常路径与非 READY 进入路径无固化测试（行为已独立验证）
- DD-W4-D2-01 文档缺失，Design Decision 证据链不完整
- 性能/价值无实验数据（Benchmark/Ablation 未执行）
```

# 18. Final Conclusion

```
Test Development:  COMPLETE
                   （coder 测试 83 用例已验证有效；按授权未补测试）

Correctness:       PASS
                   （R1-R18 全 PASS；R19 PARTIAL 因 F3）

Safety:            PASS
                   （执行只经注入安全链；BLOCKED 不触发修复；无越权写）

Design Decision:   NOT_VERIFIED
                   （DD-W4-D2-01 文档缺失；实现行为有测试支持但证据链不完整）

Benchmark:         NOT_VERIFIED（未执行；数据缺口清单见 §8）
Ablation:          NOT_VERIFIED（未执行）

Overall Module Acceptance: PARTIAL
                   （代码行为验收通过；F3 缺陷 + DD-W4-D2-01 缺失两项待 Coder 处理）
```
