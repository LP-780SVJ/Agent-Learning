# CodeTeam Week4 SingleAgent 当前已确认的 Runtime Correctness 修复：Batch-aware Stall Detection

## 角色

你现在是 **CodeTeam / Coding Agent Runtime 的代码修改工程师**。

本轮不是继续优化 CompletionGate、Finalization、Sandbox、Context、ProgressPolicy 阈值，也不是提升模型推理能力。

当前 Week4 SingleAgent 已经经过多轮真实稳定性验证，绝大多数 Runtime 主链路在最新有限样本中表现稳定；这不等于已经证明不存在其他缺陷。

本轮只解决最新稳定性实验暴露出的一个明确 Runtime correctness 缺陷：

> **Native Provider 一次可以返回多个 ToolCall，但当前 AgentLoop 的 cached/repeated no-progress guard 会在 batch 中某一个 ToolCall 命中缓存或重复时立即停止整个 Agent，从而可能丢弃同一 batch 后续尚未执行的新动作。**

本轮定义为：

```text
Batch-aware Stall Detection
```

核心目标：

```text
Per-call Safety
!=
Per-turn Progress

单个 ToolCall 是否 cached / repeated
不能直接代表
整个 Model Turn 是否没有进展
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

必须基于当前最新 `week4` 代码修改。

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
/Users/root/workspace/Agent-Learning/evals/week4/agent_runs/stability_20260830_102307
```

至少检查：

```text
stability_summary.json
```

以及 F03 × 5 中唯一失败的那一轮：

```text
results.jsonl
_artifacts/F03/runtime_messages.json
_artifacts/F03/model_outputs.jsonl
_artifacts/F03/verification.json
_artifacts/F03/final.diff
```

同时阅读当前：

```text
codeteam/agent_loop.py
codeteam/agent/progress.py
codeteam/agent/runtime.py
codeteam/agent/runtime_tools.py
codeteam/state.py
codeteam/evaluation/stability.py
```

以及相关 tests。

正式修改前先确认：

> 本提示词描述是否与当前真实代码完全一致。

若最新代码已经部分修复，必须以真实代码为准，不得重复实现。

---

# 三、最新稳定性实验结论

本轮 stability script 主要运行：

```text
F03 × 5
B01 × 2
11-task × 3
```

整个 campaign 共 40 个 task episodes：

```text
actor success = 39 / 40
security = 40 / 40
```

唯一失败是 targeted F03；同一 campaign 的三轮 full suite 中 F03 均成功，因此 F03 合计为 7 / 8。该结果说明 bug 具有偶发性，但真实可复现。

结果：

## B01

```text
2 / 2 success
```

## 完整 11-task

三轮：

```text
11 / 11
11 / 11
11 / 11
```

即：

```text
33 / 33
```

并且：

```text
grader_correct_but_actor_failed = 0
completion_ready_but_actor_failed = 0

provider failure = 0
environment failure = 0
protocol failure = 0
workspace mutation = 0
```

因此此前以下能力已基本验证稳定：

```text
Native Tool Transport
Verification Environment
Sandbox Scratch Isolation
Versioned Completion Evidence
CompletionGate
Native submit_result
Finalization Reserve
Terminal Settlement
Progress Advisory
Environment Introspection
Initial Context Reuse
```

本轮不要重新打开这些已稳定主链路。

---

# 四、当前唯一失败：F03 × 5 中 1 次 `no_progress`

F03：

```text
4 / 5 success
```

唯一失败不再是：

```text
max_steps
```

而是：

```text
no_progress
```

失败轮关键数据：

```text
steps          = 11
tool_calls     = 33

patch_attempts = 0
changed_files  = []

source_progress     = 0
diagnostic_progress = 31
```

错误语义：

```text
Agent stopped after repeated cached exploration without workspace changes.
```

这是一个已确认的 Runtime premature-stop 缺陷，但不能反向证明模型若继续执行就一定会完成正确代码。最终 workspace 没有 patch，公开验证、regression 与 hidden acceptance 均失败，因此应准确描述为：

```text
Runtime-induced opportunity loss
+
model exploration inefficiency
```

而不是已经完成正确代码后的评测 false negative。

---

# 五、失败发生前模型已经形成实现方向，但仍存在探索冗余

该 F03 失败轮里，模型已经完成：

```text
Task understanding       ✓
Environment diagnosis    ✓
Implementation direction ✓
```

模型已经理解：

```text
notifications.email_dispatch_enabled

明确 false
→ suppress email

config / section / flag missing
→ preserve existing behavior
```

并通过：

```text
inspect_environment
```

确认：

```text
yaml unavailable
```

随后已经决定：

```text
使用 dependency-free minimal implementation
```

但第 11 轮尚未执行的两个 fresh read 是：

```text
src/experimental/broken_parser_case.py
src/plugins/loader.py
```

它们不是直接的任务实现动作，batch 中也没有 `apply_patch`。因此本轮修复只能证明 Runtime 不应在第一个 cached call 后丢弃后续调用，不能宣称后续调用必然带来任务成功。

所以不能把本轮失败归因于：

```text
Context retrieval failed
模型完全不理解需求
Environment Inspector 无效
```

---

# 六、真正 Root Cause：Runtime 在 Multi-tool Batch 中途提前 STOP

失败关键点：

某一轮模型一次返回多个 native ToolCall，例如：

```text
Assistant Turn N:

1. read_file("AGENTS.md")
2. read_file("src/experimental/broken_parser_case.py")
3. read_file("src/plugins/loader.py")
```

其中：

```text
Tool 1
```

命中 cache。

而前一轮也已经出现 cached observation。

当前 AgentLoop 在处理：

```text
Tool 1
```

时立即：

```text
cached_no_progress_count += 1
```

达到阈值后直接：

```text
return NO_PROGRESS
```

结果：

```text
Tool 2
Tool 3
```

根本没有执行。

这说明当前 Runtime 实际判断的是：

> 连续多少个 ToolCall 是 cached。

而不是：

> 连续多少个完整 Model Turn 没有产生新 information / source progress。

这个粒度是错误的。

---

# 七、Native Tool Calling 的正确抽象粒度

Provider-native Tool Calling 允许：

```text
Assistant Turn
├── ToolCall A
├── ToolCall B
└── ToolCall C
```

因此应该明确区分：

```text
ToolCall-level result
```

与：

```text
Turn-level progress
```

不能在：

```text
ToolCall A
```

结束后就断言：

```text
整个 Turn 没有 progress
```

尤其当：

```text
ToolCall B / C
```

尚未执行时。

---

# 八、本轮核心设计原则

必须建立：

```text
Per-call Safety
+
Per-turn Progress Aggregation
```

### Per-call Safety

可以立即 fail fast。

### Per-turn Progress

必须处理完整个安全 Tool Batch 后才能判断。

---

# 九、哪些情况仍可以立即终止 Batch

以下属于 Safety / Protocol invariant，可以继续 per-call fail-fast：

```text
Security violation
Invalid tool schema
Unknown/forbidden tool
Tool-call budget exceeded
Runtime halt / pause
Mixed submit_result batch violation
Unsafe execution
Critical infrastructure failure
```

这些不是 progress heuristic。

不要为了 batch-aware progress 而放松安全边界。

---

# 十、哪些情况不应立即终止 Batch

以下属于：

```text
Progress / Loop heuristic
```

不应该在单个 ToolCall 后直接结束整个 Agent：

```text
cached read
cached search
cached list
duplicate diagnostic observation
repeated read/search
semantic duplicate non-destructive exploration
```

正确逻辑应是：

```text
记录 duplicate/cached
↓
继续处理 batch 中其余安全 ToolCall
↓
batch 结束
↓
aggregate progress
↓
再决定是否增加 stall streak / STOP
```

---

# 十一、建议引入 Batch Progress Aggregation

不要造大型框架。

可以在当前 `_handle_tool_calls()` 中维护小型局部状态。

例如概念上：

```text
BatchProgress:
    had_source_progress
    had_uncached_observation
    had_cached_observation
    had_repeated_observation
    processed_call_count
    rejected_call_count
    unprocessed_safe_call_count
```

是否真的新增 dataclass，要看当前代码结构。

如果几个 local bool 就能清晰实现，就不要为了抽象而新增文件。

新 abstraction 必须购买：

> Native multi-tool batch 层面的 progress aggregation。

必须区分两个时钟：

```text
Mechanical stall streak
    判断整个 turn 是否只有 cached/repeated observation

Source-progress streak
    继续由 ProgressTracker 根据 successful apply_patch / workspace version change 推进
```

新读取一个此前未缓存但与任务无关的文件，只能说明该 turn 不是“纯机械重复”；它不能重置 source-progress clock，也不能自动宣称获得了有价值的语义进展。

---

# 十二、Cached No Progress 应改成 Turn-level Streak

当前类似：

```text
cached_no_progress_count
```

如果它实际按 ToolCall 计数，语义应调整。

推荐概念：

```text
cached_no_progress_turn_streak
```

如果字段重命名会造成较大兼容影响，可以保留旧名字，但：

```text
必须修改语义
```

并在 Design Decision 中解释。

---

# 十三、关键 Invariant：一个 Turn 最多 +1

例如：

```text
Assistant Turn:

read A → cached
read B → cached
read C → cached
read D → cached
```

当前可能：

```text
+4
```

目标必须：

```text
整个 Turn 全部无新 progress
→ stall streak +1
```

不是：

```text
每个 cached ToolCall +1
```

核心原则：

> Progress guards count stalled model turns, not cached calls inside a single turn.

---

# 十四、如果一个 Batch 中存在 Uncached Observation，就不能判为纯 Mechanical Stall

例如：

```text
read A → cached
read B → cached
search C → uncached observation
```

必须：

```text
search C 真正执行
↓
产生 uncached observation
↓
turn != purely mechanical stall
↓
mechanical stall streak reset / 不增加
```

但如果没有 workspace mutation：

```text
ProgressTracker source-progress streak
```

仍然继续累积，最终仍可由既有 `NO_SOURCE_PROGRESS` 策略收口长期无源码推进的广泛探索。

同样：

```text
read A → cached
apply_patch → successful
```

必须让：

```text
apply_patch
```

执行。

成功 patch 后：

```text
workspace_version++
source progress ✓
stall streak reset
```

---

# 十五、Repeated Action 必须按工具副作用分类审计

当前已直接证明的是 cacheable exploration branch。`REPEATED_ACTION` 还必须审计，但不得假设所有 repeated tool 都能统一跳过并继续。

当前如果：

```text
Tool 1
repeated search
```

立即：

```text
REPEATED_ACTION
```

也可能丢掉同一 batch：

```text
Tool 2
fresh read

Tool 3
apply_patch
```

所以本轮必须检查：

```text
REPEATED_ACTION
```

是不是也在：

```text
for call in tool_calls
```

内部直接终止整个 batch。

如果是，应根据工具类别决定 skip、continue 或 fail-fast。

---

# 十六、Repeated Action 推荐语义

对于：

```text
read/search/list/inspect
```

等非 destructive exploration action：

### 单个 call 重复

可以：

```text
skip execution
return duplicate/cached observation
```

但继续 batch。

---

### Batch 中还有 fresh action

继续执行。

---

### 整个 Batch 全部是重复/cached，且连续多 Turn

再进入：

```text
REPEATED_ACTION
```

或：

```text
NO_PROGRESS
```

具体使用哪个现有 StopReason，尽量保持当前 taxonomy。

对于相同 workspace version 上语义等价的重复 `run_tests`：

```text
不要再次执行昂贵测试
返回结构化 duplicate observation
允许 batch 中后续安全调用继续
```

如果整个 turn 只有重复测试/缓存探索，再在 turn 结束时应用 stall policy。

不要无意义新增多个近义 stop enum。

---

# 十七、不要让 Repeated Action 修复削弱 Safety

对于可能产生副作用或改变控制状态的工具：

```text
apply_patch
submit_result
```

需要遵循当前现有语义。

尤其：

```text
submit_result
```

仍必须保持 completion/finalization invariant。

不要为了统一 batch 处理，导致：

```text
重复 destructive action
```

被无条件执行。

`apply_patch` 不得因为“后面还有调用”而重复执行；同一 workspace version 下重复失败/重复 patch 应保持专用拒绝或 fail-fast 语义。`submit_result` 仍必须独占一个 batch。

必须结合工具语义判断：

```text
skip
continue
fail
```

---

# 十八、和新 ProgressTracker 的职责边界

当前已有：

```text
ProgressTracker / ProgressPolicy
```

能够区分：

```text
Source Progress
Diagnostic Progress
Progress Advisory
Terminal no-source-progress
```

而 legacy AgentLoop 还有：

```text
cached_no_progress
repeated_action
```

这两套机制不能互相抢职责。

建议明确：

## Legacy Guard

负责：

```text
明显 mechanical loop
```

例如：

```text
整轮全部 cached
连续多个 Turn
```

---

## ProgressTracker

负责：

```text
跨多个不同工具行为
长期没有 source progress
```

例如：

```text
read A
search B
inspect C
read D
...
```

不要让 legacy：

```text
cached × 2
```

比 ProgressTracker 更激进。

---

# 十九、本轮不要修改 ProgressPolicy Threshold

当前：

```text
40%
70%
85%
```

等 progress thresholds 在最新 campaign 中：

```text
没有造成 false no_source_progress pause
```

所以本轮禁止无证据调整。

不要：

```text
40% → 30%
70% → 50%
85% → 70%
```

也不要增加：

```text
hard exploration budget
```

本轮失败不是新的 ProgressPolicy 导致。

---

# 二十、必须增加的 Deterministic Regression Tests

这是本轮最重要部分。

## Case 1 — 精确复现本次 F03

模拟：

```text
Turn N:
list_files(".") → cached

Turn N+1:
read_file("AGENTS.md")     → cached
read_file("new_file_a.py") → fresh
read_file("new_file_b.py") → fresh
```

断言：

```text
不能在第一个 read_file 后 NO_PROGRESS
```

必须：

```text
new_file_a.py executed
new_file_b.py executed
Agent continues
```

并断言：

```text
declared_tool_calls = 3
processed_tool_calls = 3
unprocessed_safe_tool_calls = 0
```

最终 messages 中存在三个与 provider/runtime call id 对齐的 ToolResult。

---

## Case 2 — 单 Turn 多个 cached

```text
read A cached
read B cached
read C cached
```

整个 Turn：

```text
stall streak += 1
```

不能：

```text
+= 3
```

---

## Case 3 — 两个完整 stalled Turns

```text
Turn 1:
all cached

Turn 2:
all cached
```

如果当前阈值语义仍是 2：

```text
此时才允许 NO_PROGRESS
```

不要在 Turn 1 内部就死。

---

## Case 4 — Cached + Fresh Observation

```text
read A cached
search B fresh
```

必须：

```text
search B executed
mechanical stall streak reset / not incremented
source-progress streak remains unchanged
```

---

## Case 5 — Cached + Apply Patch

```text
read A cached
apply_patch
```

必须：

```text
apply_patch executes
workspace_version advances
source progress recorded
stall streak reset
```

---

## Case 6 — Repeated + Fresh Read

```text
search A repeated
read B fresh
```

不能因为：

```text
search A
```

直接结束 batch。

---

## Case 7 — Repeated + Apply Patch

```text
read A repeated
apply_patch B
```

新 patch 必须有机会执行。

---

## Case 8 — 真正 Mechanical Loop

```text
Turn 1:
all calls cached/repeated
no diagnostic novelty
no workspace change

Turn 2:
same
```

仍然必须能够：

```text
NO_PROGRESS / REPEATED_ACTION
```

不能把 loop guard 修没。

即使第二个 turn 达到停止阈值，也必须先处理完该 turn 中全部安全调用，再返回 stop；每个已接收的安全调用都必须有对应 ToolResult。

---

## Case 9 — Safety / Budget 仍可中途终止

分别覆盖：

```text
tool-call budget exhausted
Sandbox/backend halt
unsafe/forbidden tool
mixed submit_result batch
```

这些场景允许在 batch 中途 fail-fast，并记录未执行调用属于 safety/budget rejection，而不是 progress-heuristic 丢弃。

---

## Case 10 — Failure Origin

分别触发：

```text
cached batch stall
empty tool_calls
model turn without tools/final
completion-ready guidance ignored
```

断言它们可以通过结构化 origin/subcategory 区分，不能靠错误消息字符串判断。

---

# 二十一、必须覆盖 Multi-tool Native Turn

测试不能只调用：

```text
一次一个 ToolCall
```

至少一个 deterministic FakeModel 必须返回：

```text
tool_calls = [
  ...,
  ...,
  ...
]
```

确保真实模拟 Provider-native multi-tool batch。

否则无法验证本轮核心 bug。

---

# 二十二、Stability / Evaluation Metrics 需要补一个语义缺口

当前存在两个容易混淆的失败：

```text
no_progress
```

和：

```text
no_source_progress
```

其中：

```text
no_progress
```

偏 Legacy AgentLoop mechanical stop。

```text
no_source_progress
```

来自新 ProgressTracker / ProgressPolicy。

二者名字很接近，但语义不同。

更重要的是，当前 `StopReason.NO_PROGRESS` 同时用于：

```text
cached exploration stall
empty tool_calls
model produced neither tools nor final
completion-ready guidance ignored
```

因此仅凭：

```text
failure_category == "no_progress"
```

不能可靠判断 failure 是否来自 mechanical batch guard。

---

# 二十三、建议 Eval 层明确统计

至少增加结构化 failure origin/subcategory，例如：

```text
failure_origin:
  cached_batch_stall
  empty_tool_batch
  empty_model_turn
  completion_guidance_ignored
```

字段名称可遵循现有模型风格，但必须从 AgentLoopResult 传播到 Runtime result、Eval task result、summary/manifest 和 stability aggregation。不得解析 `error` 文本。

同时统计：

```text
mechanical_no_progress_failure_count
batch_premature_stop_count
progress_guard_unprocessed_safe_tool_call_count
```

其中 `mechanical_no_progress_failure_count` 是观察指标，不自动代表 Runtime bug；合法的两个完整 stalled turns 本来就应该触发 guard。

另外保留：

```text
StopReason.NO_PROGRESS
```

以及：

```text
source_no_progress_failure_count
```

对应：

```text
NO_SOURCE_PROGRESS
```

以及现有：

```text
repeated_action_failure_count
```

具体字段名称遵循当前 taxonomy。

不要为了 metrics 大规模修改 StopReason enum。

---

# 二十四、Stability Gate 增加 Harness Premature-stop 检查

当前 stability campaign：

```text
passed = true
```

但 F03 实际存在一个：

```text
NO_PROGRESS
```

Runtime premature stop。

因为当前 gate 主要检查：

```text
no_source_progress
```

而没显式覆盖：

```text
legacy no_progress
```

不要简单要求所有：

```text
mechanical_no_progress_failure_count == 0
```

因为修复后的合法 mechanical loop 仍应被停止。真正的 correctness gate 应直接检查：

```text
batch_premature_stop_count == 0
progress_guard_unprocessed_safe_tool_call_count == 0
```

目的：

> 允许 F03 偶尔因为真正模型 reasoning failure 不成功，也允许 Runtime 正确终止完整 mechanical loop；但不能让 progress heuristic 在 batch 中丢弃尚未处理的安全调用并仍静默通过 stability gate。

---

# 二十五、不要把 F03 Stability 标准强行改成 5/5

本轮不要：

```text
F03 >= 4/5
```

直接改：

```text
F03 == 5/5
```

原因：

外部模型仍有行为方差。

更合理的是：

```text
F03 >= 4/5
```

继续作为 stress success floor。

同时增加：

```text
progress-guard unprocessed safe calls = 0
batch premature stop = 0
```

这样可以区分：

```text
模型偶发写错
```

和：

```text
Runtime 把模型提前杀死
```

---

# 二十六至二十八、Environment Inspector P2 本轮延期

最新 campaign 中 environment inspection 数量仍偏高，stdlib portability warning 也可能较粗，但它们不是本次 batch premature-stop 的直接根因。

本轮不要顺手修改：

```text
inspect_environment cache
stdlib / project dependency classification
cross-run environment metadata
```

将以下内容写入 Remaining Limitations / 后续优化即可：

```text
P2: version-scoped environment inspection cache
P2: distinguish stdlib, project dependency, sandbox-only and executable sources
```

这样可以避免在修复 AgentLoop 控制流时同时改变环境探测行为，保持稳定性实验的因果可解释性。

---

# 二十九、本轮明确冻结的模块

除非真实代码存在直接兼容需要，不要修改：

```text
ModelRequest
ModelTurn
Provider Adapter
Native Tool Calling

Verification Environment
Sandbox Scratch

Versioned Completion Evidence
CompletionGate
submit_result
Terminal Settlement
Finalization Reserve

ProgressPolicy thresholds

Initial Context Cache

RepoMap
SymbolIndex
ImportGraph
Context Budget

Planner
RepairLoop

CheckpointManager

Multi-Agent
Scheduler
Mailbox
```

---

# 三十、不要通过提高 threshold 掩盖 Batch Bug

禁止：

```text
cached_no_progress threshold 2 → 5
```

作为主要修复。

也不要：

```text
REPEATED_ACTION threshold 增大
```

这种方式只是在降低复现概率。

Root Cause 是：

```text
progress stop 粒度错在 ToolCall level
```

所以必须修：

```text
Turn / Batch aggregation
```

---

# 三十一、不要删除 No-progress Protection

同样禁止：

```text
关闭 cached no progress
关闭 repeated action
```

因为真实 pathological loop 仍需要保护。

正确设计：

```text
Detection 保留
Decision 粒度从 ToolCall → Model Turn
```

---

# 三十二、推荐变更分组

## Change Group F1

```text
fix(agent-loop): make stall detection native-batch aware
```

内容：

```text
batch progress aggregation
turn-level cached stall streak
batch-aware repeated action
deterministic regression tests
```

这是本轮核心变更组。

---

## Change Group F2

```text
fix(eval): distinguish mechanical and source-progress stalls
```

内容：

```text
failure_origin / stall subtype
mechanical_no_progress observation metric
batch premature-stop metric
unprocessed safe call metric
source_no_progress metric
repeated_action metric
stability gate update
```

Coder 不得自行创建 commit，除非用户另行明确授权。最终按变更组汇报，由用户统一检查并提交。

---

# 三十三、Design Decision

新增或更新：

## DD — Batch-aware Stall Detection

必须至少包括：

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

同时同步更新持续维护文档：

```text
README.md
learning-plan/代码架构.md
learning-plan/设计决策.md
learning-plan/单Agent执行闭环修复记录.md
对应的 Week4 Day7 Design Decision / Failure Case 文档
```

`单Agent执行闭环修复记录.md` 继续使用：

```text
问题 → 方法 → 新问题 → 新方法 → 证据
```

叙事，记录上一轮 finalization 修复后 40 次 campaign 达到 39/40，以及新出现的 batch premature-stop 问题。

---

# 三十四、Problem 应写清楚

类似：

> Native providers can emit multiple tool calls in a single assistant turn. The legacy cached/repeated-action guard evaluated progress after each individual tool call and could terminate the entire agent before later fresh calls in the same batch were executed.

---

# 三十五、Alternatives 至少比较

### Alternative A

提高：

```text
cached_no_progress threshold
```

拒绝原因：

```text
只降低复现概率
不修粒度错误
```

---

### Alternative B

删除 cached/repeated guards。

拒绝原因：

```text
会失去 pathological loop protection
```

---

### Alternative C

只依赖 ProgressPolicy。

讨论：

```text
ProgressPolicy 负责跨-turn source progress
但 mechanical duplicate loop 仍值得快速保护
```

---

### Alternative D

Batch aggregation + Turn-level stall decision。

当前 Decision。

---

# 三十六、核心 Invariant

DD 中必须写：

> A model turn must not be classified as stalled until all safe executable tool calls in that turn have been considered.

以及：

> Multiple cached tool calls inside one turn count as at most one stalled turn.

以及：

> Any fresh observation or source progress in the same batch prevents that turn from being classified as fully stalled.

这里的 `fresh observation` 只表示“未从 action cache 返回的 observation”，不能描述为 source progress；只有 workspace mutation 才推进 source-progress clock。

---

# 三十七、Failure Case

新增本次真实 F03 Failure Case：

```text
model understands the main behavior
↓
environment uncertainty resolved
↓
implementation direction selected
↓
assistant emits multi-tool batch

Tool 1 = cached read
Tool 2 = fresh read
Tool 3 = fresh read

↓
legacy cached-no-progress counter reaches threshold at Tool 1
↓
Agent returns NO_PROGRESS
↓
Tool 2 / Tool 3 never execute
↓
0 patch
```

Root Cause：

> The stall detector operated at ToolCall granularity instead of native assistant-turn granularity.

Limit：

> The dropped calls were fresh reads rather than a patch, so this trace proves lost execution opportunity, not that the model would certainly have completed the task.

---

# 三十八、Benchmark / Ablation

本轮 coder 不执行。

Design Decision 中可以设计未来 Ablation：

```text
A:
legacy per-call stall detection

B:
batch-aware turn-level stall detection
```

比较：

```text
mechanical premature stops
F03 success
first_patch_step
pre-edit tool calls
tool calls
tokens
```

但是本轮只写：

```text
Pending user-run stability validation.
```

不得自行填写数字。

---

# 三十九、Coder 不执行 Stability Campaign

真实：

```text
F03 × 5
B01 × 2
11-task × 3
```

仍由用户本人执行。

Coder 不得执行：

```text
scripts/run_single_agent_stability_validation.sh
```

也不要自行跑完整 11-task。

允许且必须执行：

```bash
bash -n scripts/run_single_agent_stability_validation.sh
bash scripts/run_single_agent_stability_validation.sh --dry-run
```

`--dry-run` 不得调用 Provider、Docker task runtime 或 Grader，只验证 F03×5、B01×2、11-task×3 命令仍正确生成，且显式保持 `--max-steps 20`。

---

# 四十、Coder 不执行 Benchmark

明确禁止：

```text
benchmark
ablation
multi-run LLM benchmark
11-task benchmark
F03 stress benchmark
```

只允许：

```text
unit tests
deterministic integration tests
FakeModel tests
```

---

# 四十一、必须执行的 deterministic 验收

必须执行：

```bash
.venv/bin/python -m pytest tests/agent -q
```

```bash
.venv/bin/python -m pytest tests/evaluation -q
```

如改到 Runtime Tool：

```bash
.venv/bin/python -m pytest tests/execution -q
```

全量回归必须执行：

```bash
.venv/bin/python -m pytest -q
```

同时必须执行：

```bash
.venv/bin/python -m ruff check <本轮触达的 Python 路径>
.venv/bin/python -m mypy <本轮触达的 Python 路径>
git diff --check
bash -n scripts/run_single_agent_stability_validation.sh
bash scripts/run_single_agent_stability_validation.sh --dry-run
```

若全量 mypy 仍受历史 import-chain/type debt 影响，必须区分本轮触达文件与历史错误；本轮不得新增 mypy error。

不要调用真实 Provider。

---

# 四十二、修改完成后的汇报格式

完成后按以下结构回答。

## 1. Root Cause Confirmation

明确：

```text
cached no-progress 是否真实按 ToolCall 计数？
是否在 batch 中途 return？
Repeated Action 是否存在同类风险？
F03 轨迹是否能由当前代码完全解释？
```

---

## 2. Files Changed

逐项：

```text
path
what changed
why
```

任何新增 abstraction：

> 为什么不能复用已有逻辑？

---

## 3. Old vs New Batch Semantics

旧：

```text
Tool 1 cached
→ threshold reached
→ STOP
→ Tool 2/3 dropped
```

新：

```text
Tool 1 cached
Tool 2 fresh
Tool 3 fresh
↓
aggregate batch
↓
turn is not a pure mechanical stall
↓
continue
```

---

## 4. Stall Invariants

说明：

```text
一个 Turn 最多增加多少 stall streak
什么算 fresh observation
什么算 source progress
什么情况下仍然立即 fail-fast
```

---

## 5. Repeated Action Semantics

说明：

```text
重复 exploration call
重复 destructive call
mixed repeated + fresh batch
all repeated batch
```

分别如何处理。

---

## 6. Compatibility

说明是否影响：

```text
ProgressPolicy
CompletionGate
Finalization
Tool-call budget
Native Tool Calling
SafeExecution
Session
```

---

## 7. Failure Origin And Metrics

说明：

```text
NO_PROGRESS 的不同 origin 如何区分
declared / processed / rejected / unprocessed-safe tool calls 如何统计
stability gate 为什么检查 batch premature stop，而不是禁止所有 mechanical stop
```

---

## 8. Tests

列出：

```text
test file
case
command
actual result
```

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

## 12. Failure Case

列出 F03 batch premature-stop Failure Case 路径。

---

## 13. Remaining Limitations

至少说明：

```text
Turn-level stall detection remains heuristic.

ProgressPolicy still measures source-state progress rather than semantic task completion.

External LLM reasoning variance remains possible.

F03 may still occasionally fail for genuine model reasoning reasons.

No claim of deterministic 100% success is made.

The failed F03 trace proves lost execution opportunity, not guaranteed counterfactual success.

Environment inspection caching and stdlib portability classification remain deferred P2 work.
```

---

# 四十三、最终验收清单

只有全部满足才算完成：

```text
[ ] cached no-progress 不再在单个 ToolCall 中途直接决定整个 Turn

[ ] multi-tool batch 中后续 fresh calls 不会被前面的 cached call 丢弃

[ ] 一个 assistant turn 最多贡献一个 cached-stall count

[ ] batch 中存在 fresh observation 时，不判整个 turn stalled

[ ] fresh observation 不会错误重置 source-progress clock

[ ] batch 中存在 successful apply_patch 时，source progress 正确记录

[ ] repeated exploration + fresh action 不会 premature stop

[ ] repeated action guard 仍保留 pathological loop protection

[ ] 真正连续 stalled turns 仍能 NO_PROGRESS

[ ] progress heuristic stop 前已处理完整个安全 batch

[ ] safety/budget halt 仍可在 batch 中途停止并记录 rejection 原因

[ ] per-call safety invariant 没有放宽

[ ] tool-call budget 没有放宽

[ ] Security / Protocol / Runtime halt 仍能立即 fail-fast

[ ] ProgressPolicy thresholds 未无理由修改

[ ] CompletionGate 未修改

[ ] Finalization Budget 未修改

[ ] Terminal Settlement 未修改

[ ] Sandbox 未修改

[ ] Native Tool protocol 未修改

[ ] Context Retrieval 未修改

[ ] Eval 能用结构化 failure origin 区分 cached stall、empty batch、empty model turn 与 completion guidance ignored

[ ] declared / processed / rejected / unprocessed-safe tool-call 指标一致

[ ] stability gate 检查 batch premature stop 和未处理安全调用，而不是禁止所有合法 mechanical stop

[ ] deterministic multi-tool FakeModel regression tests 真实通过

[ ] 项目自身 tests 真实通过

[ ] tests/agent、tests/evaluation 与全量 pytest 均真实通过

[ ] 触达范围 Ruff/mypy、git diff --check、脚本 bash -n/dry-run 已执行

[ ] Design Decision 已更新

[ ] Failure Case 已更新

[ ] README、代码架构、设计决策、单 Agent 修复记录已同步

[ ] coder 没有执行 stability campaign

[ ] coder 没有执行 11-task

[ ] coder 没有执行 benchmark / ablation
```

---

# 四十四、核心设计原则

本轮始终坚持：

```text
ToolCall != Model Turn
```

---

```text
Cached observation != Stalled turn
```

---

```text
A turn is stalled only when the whole safe tool batch produces no new progress.
```

---

```text
Safety may stop immediately.
Progress heuristics must aggregate before stopping.
```

最终目标是把当前错误路径：

```text
Assistant Turn
├── cached call
├── fresh call
└── fresh call

↓
cached threshold reached at first call

↓
NO_PROGRESS

↓
fresh calls discarded
```

改成：

```text
Assistant Turn
├── cached call → record
├── fresh call  → execute
└── fresh call  → execute

↓
aggregate batch

↓
fresh progress exists

↓
continue Agent Loop
```

本轮修复完成后，由用户本人重新执行相同 stability campaign：

```text
F03 × 5
B01 × 2
11-task × 3
```

重点验证：

```text
batch premature stop = 0
progress-guard unprocessed safe tool calls = 0
grader_correct_but_actor_failed = 0
completion_ready_but_actor_failed = 0
B01 stable
full 11-task stable
```

如果这些 Runtime-induced failure 均不再出现，应停止继续打磨 Week4 SingleAgent correctness，将当前 Week4 固化为稳定 SingleAgent baseline，并继续 Week5 Agent Team / Task DAG / Scheduler。
