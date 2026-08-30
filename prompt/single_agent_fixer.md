# CodeTeam Week4 SingleAgent 下一轮 Runtime 修复：Finalization-aware Budgeting + Terminal Settlement

## 角色

你现在是 **CodeTeam / Coding Agent Runtime 的代码修改工程师**。

本轮不是继续优化模型推理，不是扩大 Context，不是调整 Native Tool Calling，也不是重新设计 CompletionGate。

当前 Week4 SingleAgent 已经经过多轮真实运行，Provider、协议、Sandbox、安全与 workspace hygiene 路径在最新 campaign 中没有失败；这不表示所有 Runtime completion/finalization 语义已经稳定。

本轮只解决最新稳定性实验暴露出的一个剩余 Runtime correctness 问题：

> **复杂任务在接近 `max_steps` 时，正确代码、验证证据甚至 CompletionGate READY 可能已经出现，但因为没有剩余 Model Turn 完成 `submit_result` 或补齐最终 verification，Actor 仍被判定为 `MAX_STEPS`。**

本轮定义为：

```text
Finalization-aware Budgeting
+
Terminal Runtime Settlement
```

核心目标：

```text
Model step budget
负责限制进一步推理/修改

Runtime settlement
负责在预算边界正确结算已经存在的客观完成证据
```

---

# 一、仓库与分支

仓库：

```text
https://github.com/LP-780SVJ/Agent-Learning
```

目标分支：

```text
week4
```

必须基于当前 `week4` 最新代码修改。

---

# 二、修改前必须阅读

首先阅读：

```text
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
README.md
```

重点阅读最新稳定性实验：

```text
/Users/root/workspace/Agent-Learning/stability_20260830_002409
```

以及执行脚本：

```text
/Users/root/workspace/Agent-Learning/scripts/run_single_agent_stability_validation.sh
```

必须重点阅读真实失败轨迹：

```text
F03 × 5 中唯一 max_steps failure
```

以及：

```text
11-task × 3 中唯一失败的 F04
```

至少检查：

```text
stability_summary.json
results.jsonl

对应 task 的：
runtime_messages.json
model_outputs.jsonl
verification.json
final.diff
```

修改前先确认本提示词描述与最新真实代码、真实过程是否一致。

---

# 三、最新稳定性实验结果

本轮稳定性脚本主要执行：

```text
F03 × 5
B01 × 2
11-task × 3
```

结果总体表现：

```text
B01:
2 / 2 success
```

F03：

```text
4 / 5 success
```

11-task 三轮：

```text
11 / 11
10 / 11
11 / 11
```

即：

```text
32 / 33 success
≈ 97%
```

整个 campaign 共 40 个 task episodes：

```text
actor success = 38 / 40

task verification = 40 / 40
regression = 40 / 40
hidden acceptance = 40 / 40
security = 40 / 40

provider/environment/protocol failure = 0
```

因此最新证据证明的是：

```text
Coding correctness 已经达到 40 / 40
Actor orchestration / finalization 仍有 2 个 false negative
```

其中三轮 11-task full suite 合计：

```text
security = 33 / 33
workspace mutation = 0
no_source_progress false pause = 0
```

此前已经解决：

```text
Native Tool Transport
Verification Environment
Sandbox Scratch Isolation
Normal-path submit_result ownership
Versioned Completion Evidence
Protocol Finalization
Pre-edit Progress Control
Environment Introspection
Initial Context Reuse
```

因此本轮不要无理由重新打开这些已有最新通过证据的设计。Budget-boundary settlement 是 completion ownership 的新增边界语义，必须单独记录和验证，不能宣称原有 Completion Ownership 已经覆盖它。

---

# 四、当前剩余失败并不是 Coding Correctness Failure

最新两个真正失败都表现出：

```text
最终代码 correctness 已通过 task verification、regression、hidden acceptance 和 security
```

而不是模型不会做任务。

---

# 五、F03 唯一失败：CompletionGate 已 READY，但 Actor 仍 MAX_STEPS

这次 F03 failure 的关键状态：

```text
actor_status = failed
failure_category = max_steps

acceptance_passed = true
regression_passed = true
task_verification_passed = true
security_passed = true
within_budget = true

completion_ready = true
```

这意味着：

> Runtime 自己已经知道当前 workspace 满足 completion requirements，但因为 step budget 已耗尽，没有剩余 Model Turn 调用 `submit_result`，最终仍然判失败。

---

# 六、F03 最后几步真实轨迹

关键过程：

```text
Step 16
apply_patch
```

正确代码最终完成。

随后：

```text
Step 17
task verification
PASS
```

```text
Step 18
regression
PASS
```

然后：

```text
Step 19
模型尝试非 authoritative lint / typecheck
Runtime 拒绝
```

最后：

```text
Step 20
git_diff
```

此时 Runtime 已经具备：

```text
real diff ✓
current-version verification ✓
current regression ✓
current diff review ✓
workspace hygiene ✓
```

因此：

```text
CompletionGate = READY
```

但没有 Step 21：

```text
submit_result
```

下一轮 Loop 直接：

```text
MAX_STEPS
```

---

# 七、当前 `max_steps` 混合了两个不同语义

现在：

```text
max_steps = 20
```

同时表达：

## A. Model Work Budget

```text
最多允许模型执行 20 个回合
```

这是合理的。

---

## B. Task Completion Failure Boundary

```text
第 20 个回合结束后没有 model final
→ task failed
```

这不一定合理。

F03 已经证明：

```text
Model Work Budget Exhausted
```

不等于：

```text
Task Incorrect
```

因为 Runtime 已经有足够客观证据证明任务完成。

---

# 八、第一核心修改：Terminal Runtime Settlement

当前概念类似：

```python
while True:
    if step_limit_reached:
        return MAX_STEPS

    call_model()
```

需要升级为：

```text
while True:

    if model step budget exhausted:

        evaluate CompletionGate

        if READY:
            Runtime settles COMPLETED
        else:
            MAX_STEPS

    call_model()
```

核心 invariant：

> **Step limit prevents further model work; it must not invalidate already-satisfied Runtime completion evidence.**

---

# 九、Terminal Settlement 不能额外调用一次模型

禁止：

```text
Step 20 用完
↓
免费给 Step 21
↓
让模型 submit_result
```

因为这样会破坏：

```text
max_steps = 20
```

的真实 budget 语义。

正确行为：

```text
No additional provider call
No additional reasoning
No additional source mutation

Runtime-only settlement
```

总 Model Turn 仍然不超过 20。

---

# 十、Terminal Settlement 的安全前提

只有：

```text
CompletionGate.ready == true
```

才允许 terminal settlement。

仍然必须满足当前 CompletionGate 的真实 invariant，例如：

```text
real intended Git diff
current workspace-version required verification
current diff review
workspace hygiene
no security/environment pause
```

不要因为 step limit 到达而放宽任何 completion requirement。

在执行 Runtime-only settlement 前，还必须重新读取当前 workspace 指纹，并确认：

```text
fresh_workspace_fingerprint == completion_evidence.workspace_fingerprint
```

如果二者不一致，说明 CompletionGate 计算后可能发生了 Runtime 未观察到的外部修改，必须拒绝 settlement，重新对账或进入明确失败/暂停状态。不能仅依赖内存中的 `workspace_version`。

Terminal settlement 还必须记录独立完成来源，不得伪装成模型调用了 `submit_result`：

```text
completion_mode = model_submitted
```

或：

```text
completion_mode = runtime_budget_boundary_settlement
```

该字段至少传播到：

```text
CodingAgentRunResult
Session / event payload
Eval task result
run summary / manifest
```

如果现有代码已有等价 provenance 字段，应复用并扩展枚举，不要创建语义重复字段。

---

# 十一、Terminal Settlement 不得依赖 Hidden Grader

严禁：

```text
hidden acceptance passed
→ actor success
```

Runtime 只能使用自己可见的 Completion Evidence。

External Grader 继续保持独立评价边界。

---

# 十二、Terminal Summary

如果 terminal settlement 不再调用 Model，就没有模型提供的：

```text
submit_result(summary=...)
```

因此 Runtime 可以生成一个 bounded fallback summary。

例如：

```text
Completed verified changes in:
- src/common/settings.py
- src/notifications/dispatcher.py
```

或者复用已有 Runtime evidence 生成：

```text
Verified task changes completed successfully.
```

不要加入：

```text
hidden test passed
acceptance passed
```

这类 Runtime 不可见事实。

Summary 只是 presentation，不是 correctness evidence。

---

# 十三、第二核心问题：F04 暴露 Finalization Budget 缺失

11-task 三轮唯一失败任务：

```text
F04
```

其最终：

```text
acceptance PASS
task verification PASS
regression PASS
security PASS
within budget PASS
actor FAILED
```

但是：

```text
completion_ready = false
```

所以 Terminal Settlement 单独不能救它。

同时必须记录一个容易被遗漏的预算事实：

```text
F04 task-declared max_steps = 30
EvalRunConfig max_steps = 20
effective max_steps = min(30, 20) = 20
```

当前 `agent-eval` CLI 没有显式暴露 `--max-steps`，因此 F04 实际按 20 步运行，而不是题目 JSONL 声明的 30 步。

这不是 F04 独有。当前 11-task suite 中共有五题的声明预算高于 20：

```text
B02 = 25
B05 = 25
F04 = 30
R02 = 30
R03 = 30
```

它们在最新 campaign 中都被运行级默认值压到 20。其余四题虽然完成，但不能因此忽略预算来源不透明的问题。

本轮为了与上一轮 campaign 做严格前后对照，**继续显式固定有效预算为 20 步**，不把它提高到 30。修复后稳定性脚本必须明确传入：

```bash
--max-steps 20
```

而不是继续依赖隐藏默认值。

这意味着本轮需要把预算来源变得可见和可审计，但不改变实验预算：

```text
task_declared_max_steps
run_max_steps_cap
effective_max_steps
effective_budget_source
```

以上字段应进入 task result / manifest / stability summary。`agent-eval` CLI 必须新增或接通 `--max-steps`，并把它传入 `EvalRunConfig`。

---

# 十四、F04 真实轨迹

F04 在较早阶段已经：

```text
verification(v4) PASS
regression(v4) PASS
```

但随后模型根据仓库 instruction：

```text
New domain events must be documented in docs/
```

做了一个合理文档 patch：

```text
workspace version
4 → 5
```

因为我们已经实现 Versioned Completion Evidence：

```text
v4 verification
```

必须对：

```text
v5 workspace
```

失效。

这是正确行为。

**禁止放宽。**

---

# 十五、F04 后续浪费了最后几个回合

最后阶段大致：

```text
Step 17
docs patch
→ workspace v5
→ old verification stale

Step 18
尝试 ruff / mypy
→ Runtime 拒绝

Step 19
git_diff

Step 20
submit_result
→ Runtime 正确拒绝：
missing current-version verification

然后 MAX_STEPS
```

所以：

> F04 是复合型 orchestration failure：题目声明 30 步却被运行级默认上限静默压到 20 步；在这个固定的 20 步预算内，晚期有效 patch 又使旧 verification 正确失效，而 Runtime 没有为 current-version verification、diff review 和 submit 预留收尾回合。

本轮修复目标不是靠恢复 30 步掩盖问题，而是在**显式固定 20 步**的同等预算下改善 finalization，并让预算裁剪完全可观测。题目声明预算与运行级 cap 的长期语义是否调整，留到本轮 A/B 稳定性验证之后单独决策。

---

# 十六、不要通过放宽 Versioned Evidence 修 F04

明确禁止：

```text
docs-only patch
→ 不让 verification stale
```

或者：

```text
Runtime 自动判断 docs 修改不影响代码
```

当前没有可靠 File Impact Classifier。

为了一个任务放宽：

```text
workspace version change invalidates old verification
```

会制造 False Success 风险。

继续保持：

```text
任何 workspace version change
→ previous verification stale
```

---

# 十七、第二核心修改：Finalization-aware Step Budget

建议新增一个非常窄的：

```text
FinalizationBudgetPolicy
```

不要设计完整巨大：

```text
PLANNING
CODING
VERIFYING
FINALIZING
```

状态机。

它只回答：

```text
remaining model turns?
current workspace has real diff?
CompletionGate missing requirements?
should Runtime apply finalization pressure?
```

---

# 十八、Finalization Reserve

本轮 stability campaign 的有效预算继续固定为：

```text
max_steps = 20
```

`FinalizationBudgetPolicy` 必须使用确定性、可配置且可记录的 reserve。建议默认公式：

```text
finalization_reserve_steps = max(3, ceil(effective_max_steps * 0.20))
```

因此本轮 20 步 campaign 默认：

```text
finalization_reserve_steps = 4
```

如果现有配置结构更适合显式整数默认值，也可以采用等价实现，但必须满足：同一 `effective_max_steps` 结果确定、可由请求覆盖、进入 manifest，且单元测试覆盖边界值。不要根据 task id 或 F03/F04 特判。

注意：

```text
总 Model Turns 仍然 <= 20
```

不是：

```text
20 + 3
```

概念：

```text
Steps 1–16
normal work

Steps 17–20
finalization reserve
```

请求、Session、Eval result 和 manifest 至少记录：

```text
effective_max_steps
finalization_reserve_steps
finalization_reserve_entered
finalization_reserve_entry_step
```

---

# 十九、进入 Finalization Reserve 的条件

不要仅仅：

```text
step >= 18
```

就进入 finalization。

至少应该考虑：

```text
real workspace diff exists
```

以及剩余预算。

例如：

```text
has_real_diff
AND
remaining_steps <= reserve
```

这表示 Agent 已经进入“有实现结果但必须收尾”的阶段。

---

# 二十、Finalization Reserve 不是代码冻结

进入 reserve 后仍然允许：

```text
apply_patch
```

因为模型可能真的发现当前代码有问题。

如果继续 patch：

```text
workspace_version++
```

旧 verification 自然失效。

Runtime 再根据最新 CompletionGate 给出缺失 requirements。

不要：

```text
step 18 后禁止修改代码
```

---

# 二十一、Finalization Advisory 必须使用真实 CompletionGate 状态

不要再注入泛化：

```text
Please finish soon.
```

Runtime 已经知道具体缺什么。

应该给结构化提示，例如：

```json
{
  "finalization_budget": {
    "remaining_turns": 3,
    "workspace_version": 5,
    "missing_requirements": [
      "current_version_verification",
      "current_diff_review"
    ],
    "guidance": "Prioritize authoritative completion requirements before optional diagnostics."
  }
}
```

Advisory 还必须提供：

```text
authoritative task verification commands
authoritative regression commands
whether git diff is current
allowed completion actions
```

并明确告诉模型：一个合法 Model Turn 可以返回多个有顺序的工具调用；若剩余收尾工作互不冲突，可以在同一轮依次运行 task verification、regression 和 `git_diff`，避免把每个 deterministic action 人为拆成一个新 Model Turn。

每次 `apply_patch` 或任意工具结果返回后，都必须基于最新 workspace version 和 CompletionGate 重新计算 advisory，不能复用上一轮缺失项。

---

# 二十二、Finalization 优先级

Finalization Advisory 必须与现有 safety、halt 和 progress guidance 组合，而不是覆盖它们。统一优先级：

```text
safety / environment halt
>
CompletionGate READY
>
finalization advisory
>
normal progress guidance
```

不得为了加入 finalization 提示而替换或绕过现有 ProgressPolicy provider。

当已经存在 real source diff 且进入 reserve：

## 缺 verification

优先：

```text
authoritative run_tests
```

---

## verification current，但缺 diff review

优先：

```text
git_diff
```

---

## CompletionGate READY

优先：

```text
submit_result
```

---

## 模型发现新问题

允许：

```text
apply_patch
```

然后重新进入：

```text
verification stale
```

状态。

---

# 二十三、不要让 optional lint/typecheck 抢 Finalization Budget

F03 与 F04 两个失败都出现：

```text
required tests 已经完成或接近完成

↓
Agent 又尝试
uv run ruff
uv run mypy

↓
Runtime exact allowlist 拒绝

↓
浪费 1 Model Turn
```

进入 Finalization Reserve 后应该明确告诉模型：

```text
Repository-discovered lint/typecheck commands are optional guidance.
They do not contribute to Runtime completion unless explicitly listed as authoritative verification commands.

Do not spend remaining finalization turns on non-authoritative diagnostics.
```

如果 authoritative commands 已明确列出，提示中直接给出规范化后的可调用形式，不要只给抽象描述，让模型再次猜测命令。

---

# 二十四、不要放宽 run_tests allowlist

当前 Runtime 拒绝：

```text
uv run ruff
uv run mypy
```

本身是正确行为。

不要因为它浪费一步就允许 arbitrary repository commands。

真正应该修的是：

```text
Agent 在剩余预算极低时，不应该再选择这些工具。
```

这是 Finalization Policy 问题，不是 CommandPolicy 问题。

---

# 二十五、第三个修改：Completion-ready Tool Tightening

当前 CompletionGate READY 后：

```text
submit_result
```

应该是默认正确下一步。

但稳定性实验里 full suite 仍然记录到少量：

```text
post_ready_tool_call_count > 0
```

这只能说明 READY 之后仍发生了工具调用，**不能直接等同于浪费**。最新轨迹至少包含两种不同语义：

```text
READY 后尝试非 authoritative lint/typecheck
→ 可避免的 optional work
```

以及：

```text
READY 后 apply_patch
→ 模型发现问题并主动重开任务
→ 合法行为
```

建议在：

```text
CompletionGate.ready == true
```

时做窄范围收敛和逐调用动态判断，而不是冻结工具面。

---

# 二十六、READY 状态下允许的下一步

默认优先级是：

```text
submit_result
```

或者：

```text
apply_patch
```

`apply_patch` 表示：

> 模型主动重新打开任务并修改当前 workspace。

必要的 `read_file` / `search_code` 仍可用于确认一个新发现的问题，但 Runtime 应优先返回已有 cache，避免重复昂贵探索。不要把所有 read/search 一刀切禁止，否则模型无法在决定重开任务前核实风险。

---

# 二十七、READY 后跳过明确冗余或非 authoritative 的工具

例如当前 gate 已 READY 时：

```text
run_tests
inspect_environment
```

若命令不是 authoritative verification，或与当前版本已经通过的 authoritative command 语义等价，应 skip，并返回结构化 observation：

```json
{
  "completion_ready": true,
  "allowed_next_actions": [
    "submit_result",
    "apply_patch",
    "targeted_read_or_search_when_reopening"
  ],
  "message": "Current workspace already satisfies completion requirements."
}
```

`list_files`、`git_status`、已缓存的相同 `read_file/search_code` 也应尽量由 cache 或 completion-ready advisory 回答，但不要修改安全工具的正常语义，也不要禁止首次、针对性的风险核查。

如果单个模型 action 含多个 tool calls，必须在**每个 tool call 前**重新计算 gate：

```text
READY
→ apply_patch allowed
→ workspace_version++
→ gate becomes NOT READY
→ 后续 run_tests 按新状态正常执行
```

不能基于 batch 开始时的 READY 状态跳过 patch 后必需的验证。

这样：

```text
READY
```

之后不会再浪费 expensive tool calls。

---

# 二十八、不要禁止 apply_patch

即使 READY，模型也可能突然发现逻辑缺陷。

如果它明确：

```text
apply_patch
```

应该允许。

成功 patch 后：

```text
workspace_version++
```

CompletionGate 自动失效。

这是正确重新打开任务的方式。

不要再只使用含义模糊的：

```text
post_ready_tool_call_count
```

至少拆分为：

```text
post_ready_reopen_patch_count
post_ready_skipped_optional_tool_count
post_ready_nonfinalization_tool_count
```

前者是合法重开，第二项体现策略节省，第三项才用于追踪 READY 后仍发生的非收尾调用。保留旧字段用于兼容时，必须在文档中说明它不是“浪费调用数”。

---

# 二十九、第四项：修正 Stability / Eval False-negative Metric

当前 stability script 对 control false negative 的检测过窄。

如果当前仅检查：

```text
failure_category == no_source_progress
```

那么会漏掉：

```text
actor max_steps
但 external correctness 全通过
```

例如最新 F04。

最新 `stability_summary.json` 曾出现 control false-negative 汇总为 0，但 campaign 实际存在 F04 的 `actor_status != completed` 且全部 Grader 维度通过。这证明脚本不能只围绕某一个 failure category 建立控制指标。

---

# 三十、新增真正的 Correct-but-Actor-Failed 指标

建议定义：

```text
grader_correct_but_actor_failed_count
```

逻辑：

```text
actor_status != completed
AND
acceptance_passed
AND
regression_passed
AND
task_verification_passed
AND
security_passed
AND
within_budget
```

这可以真实测：

> Coding work 正确，但 Actor orchestration 没有成功收口。

---

# 三十一、保留 completion-ready false negative 指标

同时保留：

```text
completion_ready_but_actor_failed_count
```

两个指标语义不同：

### completion_ready_but_actor_failed

Runtime 自己已经 READY，但 Actor 失败。

例如：

```text
F03 terminal settlement bug
```

### grader_correct_but_actor_failed

外部 Grader 证明正确，但 Runtime/Actor 没收口。

例如：

```text
F04 final verification 没来得及刷新
```

两个都应该保留。

---

# 三十二、建议补充指标

如果实现成本低，建议新增：

```text
budget_boundary_completion_count
```

表示：

```text
step budget reached
but Runtime terminal settlement succeeded
```

以及：

```text
finalization_reserve_entry_count
```

```text
finalization_reserve_success_count
```

```text
grader_correct_actor_max_steps_count
```

不要使用 `max_steps_after_correctness_count` 这个名字，因为 Grader 只知道最终 workspace 正确，未必能证明“在第几个 step 已经正确”。新名称只陈述可观察事实：最终 Grader 正确且 Actor 以 `max_steps` 失败。

稳定性脚本必须对所有 task result 统一聚合，并至少在以下任一条件不满足时返回非零退出码：

```text
grader_correct_but_actor_failed_count == 0
completion_ready_but_actor_failed_count == 0
provider_blocked_count == 0
environment_blocked_count == 0
protocol_failure_count == 0
workspace_mutation_count == 0
```

所有 `actor_status != completed` 都必须进入明确 failure-category 汇总，不能因为不属于 `no_source_progress` 就从 control false-negative 判据中消失。

脚本继续执行相同 campaign：

```text
F03 × 5
B01 × 2
11-task × 3
```

并在每次 `agent-eval` 调用中显式传入：

```bash
--max-steps 20
```

以保证修复前后预算一致。脚本输出还应确认每个 task 的 `effective_max_steps == 20`；若不是，实验应 fail-fast，不能把不同预算的结果合并比较。

---

# 三十三、暂时不要实现 Submit-time Auto Verification

存在一个可能的后续增强：

```text
submit_result
↓
唯一缺 current verification
↓
Runtime 自动执行 authoritative verification
↓
re-evaluate gate
```

这理论上可以解决 F04。

但是本轮**不要优先实现**。

因为这会改变：

```text
submit_result
```

从：

```text
check-only control tool
```

变成：

```text
verification side-effect tool
```

属于更大的语义变化。

先通过：

```text
Terminal Settlement
+
Finalization Reserve
+
Finalization Advisory
```

解决问题。

如果真实稳定性实验仍出现类似 F04，再单独设计 Submit-time Verification Refresh。

---

# 三十四、ProgressPolicy 本轮不要继续修改

最新稳定性实验：

```text
F03 × 5
no_source_progress_pause = 0
```

且每次：

```text
first_patch_step = 9–14
```

说明 ProgressPolicy 已经把此前：

```text
20 steps / 0 patch
```

问题解决。

不要继续：

```text
调整 40% / 70% / 85% threshold
增加 hard exploration budget
提高 progress pressure
```

否则可能误杀正常复杂任务。

---

# 三十五、Initial Context Cache 本轮不要修改

真实 stability 中：

```text
initial_context_cache_hit
```

已经大量出现，说明 cache/reference 路径被实际触发；但这**不能证明上下文复用已经节省 token 或避免重复读取**。F03 轨迹中，模型曾把 compact reference 误解为内容为空，随后重新读取完整文件。

因此本轮不重构 Initial Context Cache，但要把它记录为 P2 已知限制，而不是宣称完全稳定。后续可增加：

```text
initial_reference_followup_full_read_count
estimated_initial_context_tokens_saved
```

本轮这些指标若未实现，必须在 Remaining Limitations 中如实说明，不得编造 token savings。

---

# 三十六、Environment Introspection 的两个 P2 小问题

这两个问题可以顺手小修，但不能干扰主任务。

## 1. `inspect_environment` 可以加入 version-scoped cache

同一个：

```text
sandbox image
workspace version
query
```

重复 inspection 没必要再次执行。

例如：

```text
yaml available?
```

同一版本查询两次可以直接 cache。

---

## 2. portability warning 过于粗糙

当前如果：

```text
tomllib
```

runtime available，但不在 project dependencies 中，可能提示：

```text
not portable
```

但：

```text
tomllib
```

属于 Python 3.11 stdlib。

如果项目要求：

```text
Python >= 3.11
```

则这个 warning 不准确。

未来可区分：

```text
stdlib
project_dependency
sandbox_only
executable
```

但这是 P2。

不要为了这一点大改 Environment Inspector。

---

# 三十七、本轮明确不要修改

除非存在直接兼容需求，禁止大改：

```text
Native Tool Calling
ModelRequest / ModelTurn
Provider Adapter

VerificationEnvironmentPreflight

Sandbox tmpfs / scratch

Completion evidence versioning

CompletionGate 核心规则

ProgressPolicy 主阈值

Initial Context Cache

RepoMap / SymbolIndex / ImportGraph

Context Budget

Planner

RepairLoop

CheckpointManager security

Multi-Agent
```

---

# 三十八、本轮禁止通过提高 max_steps 解决

明确禁止：

```text
20 → 30
20 → 40
```

这只是扩大：

```text
flat budget
```

不能解决：

```text
finalization budget starvation
```

而且会破坏之前所有 benchmark/stability 可比性。

本轮要做的是：

```text
保留 effective_max_steps = 20
显式暴露并传递 --max-steps 20
记录 task 声明预算、run cap 与 effective budget
```

不是继续依赖默认值，也不是把 F04 恢复到 30 步后宣称 finalization 已修复。

---

# 三十九、本轮必须执行的 deterministic 验收

只执行 deterministic 项目测试，但以下不是可选项：

```bash
.venv/bin/python -m pytest tests/agent -q
```

```bash
.venv/bin/python -m pytest tests/evaluation -q
```

因为本轮必须接通 `agent-eval --max-steps`，还必须执行：

```bash
.venv/bin/python -m pytest tests/cli -q
```

若 completion mode/provenance 写入 Session，必须执行：

```bash
.venv/bin/python -m pytest tests/session -q
```

触达 execution policy 时执行：

```bash
.venv/bin/python -m pytest tests/execution -q
```

全量回归必须执行：

```bash
.venv/bin/python -m pytest -q
```

同时执行：

```bash
.venv/bin/python -m ruff check <本轮触达的 Python 路径>
.venv/bin/python -m mypy <本轮触达的 Python 路径>
git diff --check
bash -n scripts/run_single_agent_stability_validation.sh
bash scripts/run_single_agent_stability_validation.sh --dry-run
```

若全量 mypy 仍受历史 import-chain/type debt 影响，必须区分本轮触达文件与历史错误；本轮不得新增 mypy error。

---

# 四十、本轮不要由 coder 运行 Stability Campaign

真实：

```text
F03 × 5
B01 × 2
11-task × 3
```

由用户本人运行。

Coder 不要执行：

```text
scripts/run_single_agent_stability_validation.sh
```

也不要运行真实 LLM suite。

允许且必须运行：

```bash
bash -n scripts/run_single_agent_stability_validation.sh
bash scripts/run_single_agent_stability_validation.sh --dry-run
```

`--dry-run` 不得调用 Provider、Docker task runtime 或 hidden grader，只输出将要执行的 F03×5、B01×2、11-task×3 命令，并显示每条命令都包含 `--max-steps 20`。

---

# 四十一、不要执行 Benchmark / Ablation

本轮 coder：

```text
不执行 benchmark
不执行 ablation
不执行 11-task
不执行 F03×5
```

Design Decision 中可以记录未来 validation plan。

统一标记：

```text
Pending user-run stability validation.
```

不得编造成功率、token savings 或 latency。

---

# 四十二、推荐变更分组

## Change Group E1

```text
fix(runtime): settle ready tasks at model-step boundary
```

内容：

```text
Terminal Settlement
budget-boundary completion
fallback Runtime summary
tests
```

---

## Change Group E2

```text
feat(runtime): reserve model turns for deterministic finalization
```

内容：

```text
FinalizationBudgetPolicy
remaining-turn advisory
completion missing requirements
tests
```

---

## Change Group E3

```text
fix(runtime): harden ready-state tools and eval false-negative metrics
```

内容：

```text
READY tool tightening
grader_correct_but_actor_failed_count
budget-boundary metrics
optional inspect_environment cache
```

如果 E1/E2 在真实架构中高度耦合，可以合并，但必须说明原因。

本轮 Coder 不要自行创建 commit，除非用户另行明确授权。最终只按上述分组汇报文件和逻辑，由用户统一检查并提交。

---

# 四十三、E1 必须覆盖的核心测试

## E1-1

```text
max_steps reached
CompletionGate NOT READY
→ MAX_STEPS
```

原行为保持。

---

## E1-2 — F03 Regression

模拟：

```text
Step 20
git_diff
↓
CompletionGate READY
↓
step budget exhausted
```

预期：

```text
no extra provider call

RuntimeStatus.COMPLETED
```

不是：

```text
MAX_STEPS
```

---

## E1-3

断言：

```text
provider call count <= max_steps
```

Terminal Settlement 不能隐藏额外 LLM call。

---

## E1-4

存在：

```text
security pause
environment failure
unsafe workspace
```

即使表面 gate 条件部分满足，也不能 settlement。

---

## E1-5

stale verification：

```text
v1 tests pass
v2 patch
```

仍不能因为 step limit settlement。

---

## E1-6

模拟 CompletionGate 计算后发生 Runtime 未观察到的外部 workspace mutation：

```text
fresh fingerprint != evidence fingerprint
```

即使内存中的 gate 曾是 READY，也不得 terminal settlement。

---

## E1-7

分别断言正常模型提交与预算边界结算的 provenance：

```text
model_submitted
runtime_budget_boundary_settlement
```

并验证它传播到 Runtime result、Session/event 和 Eval result，不把 Runtime fallback summary 伪装为模型输出。

---

# 四十四、E2 必须覆盖 F04 场景

模拟：

```text
verification v4 PASS

late patch
→ workspace v5
→ verification stale

remaining_turns = 3
```

Runtime advisory：

```text
missing:
current_version_verification
current_diff_review
```

下一步：

```text
run required verification
```

再：

```text
git_diff
```

最终：

```text
submit_result
```

或者如果最后一个合法回合完成：

```text
git_diff
→ gate READY
→ Terminal Settlement
```

也必须成功。

还必须覆盖预算裁剪事实：

```text
task declared max_steps = 30
run cap = 20
effective max_steps = 20
```

断言 CLI 参数被传入 `EvalRunConfig`，Runtime 最多调用 Provider 20 次，result/manifest 同时记录三种预算值及来源。本轮测试不得把 effective budget 改成 30。

对 B02/B05/F04/R02/R03 做参数化预算测试，证明它们的声明值分别为 25/25/30/30/30，但本轮脚本显式 run cap 下 effective budget 均为 20；不要只为 F04 写 task-specific 分支。

补一个 batch tool-call 测试：同一 action 在 READY 时先 `apply_patch`，随后调用 authoritative `run_tests`。Runtime 必须在 patch 后重新计算 gate，允许新版本验证，不能沿用 batch 开始时的 READY 状态把它跳过。

---

# 四十五、E2 不能强制错误行为

测试：

```text
进入 finalization reserve
但模型发现真实 source bug
↓
apply_patch
```

必须允许。

然后：

```text
workspace_version++
verification stale
```

重新计算 completion requirements。

---

# 四十六、E3 READY-state Tests

## READY + submit_result

```text
accepted
```

---

## READY + apply_patch

```text
allowed
workspace version advances
gate invalidated
```

---

## READY + optional/non-authoritative run_tests

应该：

```text
skip expensive execution
return completion-ready advisory
```

## READY + authoritative command already current

语义等价的重复验证应 skip，并计入：

```text
post_ready_skipped_optional_tool_count
```

## READY + targeted first read/search

允许模型在明确准备重开任务时做针对性核查；相同参数优先使用 cache。不得把所有 read/search 一刀切拒绝。

## READY + cached list/status/read/search

返回 cache/advisory，不重复调用昂贵 backend。

---

# 四十七、Eval Metric Tests

必须验证：

```text
actor failed
+
acceptance PASS
+
regression PASS
+
task verification PASS
+
security PASS
+
within budget
```

统计为：

```text
grader_correct_but_actor_failed_count += 1
```

不管 failure category 是：

```text
max_steps
no_source_progress
repeated_action
```

都应该被捕获。

还必须验证 stability script 的聚合判据：即使 `no_source_progress` 为 0，只要存在一个上述 Actor false negative，脚本仍返回非零；所有任务完成且控制指标为 0 时才返回 0。

---

# 四十八、Design Decision

新增/更新：

## DD — Finalization-aware Step Budget

至少：

```text
Problem
Alternatives
Decision
Invariant
Trade-offs
Verification
Limitations
Interview Version
```

Problem：

> A flat model-step budget allowed complex tasks to consume all turns before deterministic completion requirements could be finalized, causing correct work to be reported as MAX_STEPS.

Alternatives：

```text
Increase max_steps
Free extra LLM finalization turns
Relax completion evidence
Runtime terminal settlement
Finalization reserve
```

Decision：

```text
Terminal Runtime Settlement
+
Finalization-aware reserve within existing model-step budget
```

DD 还必须记录：

```text
completion_mode / provenance
fresh workspace fingerprint settlement guard
task-declared budget vs run cap vs effective budget
为什么本轮显式固定 20 步而不采用 F04 声明的 30 步
READY 后合法 reopen patch 与冗余 optional tool 的区别
```

同步更新以下持续维护文档：

```text
README.md
learning-plan/代码架构.md
learning-plan/设计决策.md
learning-plan/单Agent执行闭环修复记录.md
对应的 Week4 Day7 Design Decision / Failure Case 文档
```

`单Agent执行闭环修复记录.md` 必须继续使用连贯的：

```text
问题 → 方法 → 新问题 → 新方法 → 证据
```

叙事，并明确最新 campaign 的“40/40 correctness、38/40 actor success”与本轮预算边界修复，不得只写最终方案。

---

# 四十九、Failure Case

至少记录两个真实 Failure Case。

## F03

```text
correct final patch
↓
current verification pass
↓
current regression pass
↓
last legal turn git_diff
↓
CompletionGate READY
↓
no remaining model turn for submit_result
↓
MAX_STEPS false failure
```

Root Cause：

> Model work budget exhaustion incorrectly prevented Runtime settlement of already-ready completion evidence.

---

## F04

```text
verification v4 pass
↓
late valid docs patch
↓
workspace v5
↓
old verification correctly stale
↓
remaining turns consumed by optional diagnostics/diff
↓
submit_result reports missing current verification
↓
MAX_STEPS
↓
external grader proves final code correct
```

Root Cause：

> F04 declared a 30-step task budget but was silently capped by the run-level 20-step default. Within that fixed 20-step experiment, a late valid workspace mutation correctly invalidated prior verification, while the flat budget reserved no turns for current-version verification and finalization.

---

# 五十、不要把这两个 Failure Case 归因为模型不会写代码

因为两者：

```text
external correctness
```

均已通过。

应该归类：

```text
Finalization Budget / Actor Orchestration False Negative
```

---

# 五十一、修改完成后的汇报格式

完成后必须按以下结构回复。

## 1. Root Cause Confirmation

确认：

```text
F03 gate-ready-at-step-limit 是否与真实代码一致
F04 late-patch verification invalidation 是否与真实代码一致
flat step budget 是否是当前根因
F04 declared 30 / run cap 20 / effective 20 是否与真实代码一致
```

---

## 2. Files Changed

逐文件：

```text
path
what changed
why
```

新增 abstraction 必须说明：

> 为什么不能复用现有模块？

---

## 3. Budget Lifecycle

画出：

```text
Normal Work Budget
↓
Finalization Reserve
↓
CompletionGate
↓
submit_result
or
Terminal Settlement
```

---

## 4. Terminal Settlement Invariants

说明：

```text
什么时候可以 settlement
什么时候必须 MAX_STEPS
是否额外调用 Provider
是否使用 hidden grader
fresh workspace fingerprint 如何防止未观察 mutation
completion_mode 如何记录和传播
```

---

## 5. Finalization Reserve

说明：

```text
reserve 如何计算
remaining turns 如何传给模型
missing requirements 如何生成
为什么本轮 effective max_steps 固定为 20
task budget / run cap / effective budget 如何记录
```

---

## 6. READY Tool Behavior

说明：

```text
submit_result
apply_patch
其他 read/search/test/status
```

分别如何处理。

必须区分：

```text
legitimate reopen patch
skipped optional tool
remaining non-finalization tool call
```

---

## 7. Eval Metrics

说明新增：

```text
grader_correct_but_actor_failed_count
budget_boundary_completion_count
其他指标
```

说明稳定性脚本如何在 `no_source_progress == 0` 但存在其他 Actor false negative 时仍 fail。

---

## 8. Tests

列出：

```text
test path
case
command
actual result
```

不得编造。

---

## 9. Stability Campaign

必须写：

```text
The stability campaign was NOT executed by the coder.
Pending user-run validation.
```

---

## 10. Benchmark

必须写：

```text
No benchmark or ablation was executed.
```

---

## 11. Design Decision

列出 DD 以及 README、代码架构、设计决策、单 Agent 修复记录的更新路径。

---

## 12. Failure Cases

列出 F03 / F04 Failure Case 更新路径。

---

## 13. Remaining Limitations

至少说明：

```text
Finalization reserve is budget-aware, not a full semantic phase planner.

Terminal settlement only applies when current Runtime completion evidence is already READY.

No submit-time automatic verification is implemented yet.

Environment introspection portability classification may still be coarse.

Complex tasks may still have model reasoning variance.

Initial Context Cache hit does not yet prove token savings; compact references may trigger follow-up full reads.

Task-declared budgets and run-level caps remain a separate policy decision; this campaign intentionally fixes effective max_steps at 20 for causal comparison.
```

---

# 五十二、最终验收清单

只有同时满足这些条件才算完成：

```text
[ ] max_steps 到达时先检查 Runtime completion readiness

[ ] READY 可以 Runtime-only terminal settlement

[ ] terminal settlement 前重新校验 fresh workspace fingerprint

[ ] model_submitted 与 runtime_budget_boundary_settlement provenance 可区分并持久化

[ ] NOT READY 仍然 MAX_STEPS

[ ] Terminal Settlement 不产生额外 Provider call

[ ] 总 model turns 不超过 max_steps

[ ] stale verification 仍不能 settlement

[ ] security/environment failure 仍不能 settlement

[ ] Finalization reserve 位于原有 max_steps 内部

[ ] reserve 由确定性配置计算并记录，本轮 20 步默认 reserve 为 4

[ ] reserve 不等于禁止 apply_patch

[ ] Runtime 能告诉模型剩余 turns

[ ] Runtime 能告诉模型当前 completion missing requirements

[ ] finalization reserve 优先 authoritative verification / diff / submit

[ ] optional lint/typecheck 不再轻易消耗最后几个 turns

[ ] CompletionGate READY 后冗余或非 authoritative 工具可被收敛

[ ] READY 后 targeted first read/search 未被一刀切禁止

[ ] multi-tool batch 在每个调用前重新计算 CompletionGate

[ ] READY 后 apply_patch 仍可重新打开任务

[ ] Versioned Completion Evidence 未放宽

[ ] docs-only patch 仍使 previous verification stale

[ ] max_steps 未提高

[ ] agent-eval 显式支持并传递 --max-steps 20

[ ] task-declared / run-cap / effective max_steps 全部进入结果与 manifest

[ ] CompletionGate 核心 correctness 未降低

[ ] ProgressPolicy 主逻辑未无理由修改

[ ] Native Tool Calling 未无理由修改

[ ] Sandbox scratch 未无理由修改

[ ] Initial Context Cache 未无理由重构

[ ] grader_correct_but_actor_failed 指标能捕获 max_steps false negative

[ ] stability script 不再只检查 no_source_progress

[ ] stability script 聚合 F03×5、B01×2、11-task×3 并在控制指标非零时失败

[ ] stability script --dry-run 不调用 Provider/Docker/Grader

[ ] 项目 deterministic tests 真实通过

[ ] tests/agent、tests/evaluation、tests/cli 与全量 pytest 均真实通过

[ ] 触达范围 Ruff/mypy、git diff --check、脚本 bash -n/dry-run 已执行

[ ] Design Decision 已更新

[ ] Failure Cases 已更新

[ ] README、代码架构、设计决策、单 Agent 修复记录已同步

[ ] coder 没有执行 stability campaign

[ ] coder 没有执行 11-task

[ ] coder 没有执行 Benchmark / Ablation
```

---

# 五十三、核心设计原则

本轮始终坚持：

```text
Model Budget Exhausted
!=
Task Incorrect
```

---

```text
Step budget limits further model work.
CompletionGate decides whether existing work is complete.
```

---

```text
Finalization must fit inside the declared budget,
not receive hidden free LLM turns.
```

---

```text
Runtime may settle objective completion,
but must never relax current-version verification or use hidden grader evidence.
```

最终希望把当前偶发路径：

```text
correct code
↓
tests pass
↓
budget nearly exhausted
↓
last diff / late patch
↓
no turn left
↓
MAX_STEPS
```

变成：

```text
correct code
↓
finalization reserve
↓
current verification
↓
current diff review
↓
submit_result
```

或者在最后合法回合恰好使：

```text
CompletionGate READY
```

时：

```text
Terminal Runtime Settlement
↓
COMPLETED
```

而不增加任何额外模型预算。

本轮完成后，由用户本人使用更新后的 stability script 在**显式 `--max-steps 20`** 下重新执行 F03×5、B01×2、11-task×3，判断是否消除 `grader-correct / actor-failed` 的 finalization false negative。Coder 最终只提供可直接运行的脚本、dry-run 证据和预期判据，不执行真实 campaign。
