# CodeTeam Week4 SingleAgent 下一阶段优化：Progress Control & Diagnostic Affordance

## 角色

你现在是 **CodeTeam / Coding Agent Runtime 的代码修改工程师**。

本轮不是继续修复 Native Tool Calling、Verification Environment、Sandbox Scratch 或 CompletionGate。

这些基础执行闭环已在最新一次 B01 与 11-task 真实运行中通过验证，当前没有直接回归证据；这不等同于已经完成统计意义上的稳定性证明。

本轮目标是解决 SingleAgent 当前暴露出的下一类问题：

> **Agent 在已经拥有足够任务信息、具备实施方案，但仍存在一个局部不确定性时，缺少有效的“进展控制”和“安全诊断能力”，可能持续 read/search/list 而不进入 source edit，最终耗尽 step/token budget。**

本阶段定义为：

```text
SingleAgent Progress Control & Diagnostic Affordance
```

核心不是让 Runtime 替模型做业务推理，而是：

```text
让 Agent 能安全解决不确定性
+
让 Runtime 识别长期没有 source progress 的探索
+
让已有 initial context 真正得到复用
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

必须基于当前最新 `week4` 真实代码进行修改。

---

# 二、修改前必须阅读

首先阅读：

```text
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
README.md
```

重点阅读最新真实运行过程：

```text
/Users/root/workspace/Agent-Learning/completion_gate_b01_20260829_171808
/Users/root/workspace/Agent-Learning/completion_gate_11task_20260829_171835
```

尤其检查：

```text
summary.json
results.jsonl
manifest.json
```

以及：

```text
_artifacts/F03/runtime_messages.json
_artifacts/F03/model_outputs.jsonl
_artifacts/F03/verification.json
_artifacts/F03/final.diff
```

同时抽查本轮成功任务：

```text
B01
B02
B03
F01
F04
R02
R03
```

确认本提示词描述与当前真实代码、真实执行轨迹一致后再开始修改。

---

# 三、当前最新真实结果

最新 B01：

```text
success_count                         = 1
acceptance_passed_count               = 1
regression_passed_count               = 1
task_verification_passed_count        = 1
security_passed_count                 = 1

protocol_repair_attempt_count         = 0
protocol_failed_count                 = 0

actor_completed_count                 = 1
completion_ready_count                = 1
completion_ready_but_actor_failed     = 0
post_ready_tool_call_count            = 0
verification_workspace_mutation_count = 0
```

最新 11-task：

```text
task_count                             = 11
success_count                          = 10
acceptance_passed_count                = 10
regression_passed_count                = 10
task_verification_passed_count         = 10
security_passed_count                  = 11

provider_blocked_count                 = 0
environment_blocked_count              = 0

protocol_repair_attempt_count          = 0
protocol_failed_count                  = 0

actor_completed_count                  = 10
within_budget_count                    = 11

completion_ready_count                 = 10
completion_ready_but_actor_failed      = 0
post_ready_tool_call_count              = 0

verification_workspace_mutation_count  = 0

failure_category_counts:
    max_steps = 1
```

---

# 四、这些结果为哪些问题提供了最新通过证据

当前没有证据支持继续修改以下模块。

## 1. Native Tool Transport 在最新运行中通过

当前：

```text
protocol_repair = 0
protocol_failed = 0
```

不要继续重构：

```text
ModelRequest
ModelTurn
Provider Adapter
native tool calling
provider_call_id
JSON / DSML fallback
```

---

## 2. Verification Environment 在最新运行中通过

当前：

```text
environment_blocked = 0
```

不要继续修改：

```text
VerificationEnvironmentPreflight
pytest toolchain
runtime/grader Python contract
```

除非本轮代码审查发现明确 regression。

---

## 3. Sandbox Scratch Isolation 在最新运行中通过

上一轮 pytest 曾经产生：

```text
pytest-of-root
symlink
```

污染 Git workspace。

当前最新运行：

```text
verification_workspace_mutation_count = 0
```

F03 中 pytest temp path 已进入：

```text
/tmp/pytest-of-root/...
```

不要继续扩展 Sandbox scratch。

尤其禁止：

```text
放宽 Checkpoint symlink protection
增加 pytest artifact cleaner
mount host .venv
```

---

## 4. Completion Ownership 在最新运行中通过

上一轮存在：

```text
correct patch
tests pass
diff reviewed
↓
model continues acting
↓
repeated_action
↓
false failure
```

最新：

```text
completion_ready_count            = 10
actor_completed_count             = 10

completion_ready_but_actor_failed = 0
post_ready_tool_call_count         = 0
```

说明：

```text
Versioned Completion Evidence
CompletionGate
native submit_result
```

已经实现预期目标。

本轮不要继续修改：

```text
CompletionGate
submit_result
READY semantics
workspace-version evidence
completion-ready repeated-action semantics
```

---

# 五、当前唯一失败任务：F03

当前 11-task 唯一失败任务：

```text
F03
```

失败状态：

```text
failure_category = max_steps
```

关键事实：

```text
steps          = 20
tool_calls     = 37
patch_attempts = 0
changed_files  = []
```

也就是说：

> F03 从头到尾没有真正进入 source editing。

这和上一轮 F03 因 pytest workspace pollution 导致 patch 被 Checkpoint 阻止已经不是同一个问题。

---

# 六、F03 当前不是 Context Retrieval Failure

F03 初始上下文已经包含任务最关键的信息：

```text
src/notifications/dispatcher.py
tests/task_verification/test_f03.py
configs/feature_flags.yaml
src/notifications/email.py
```

公开 test 已明确表现：

```text
notifications:
  email_dispatch_enabled: false
```

并要求：

```text
flag 显式 false
→ 禁止 email dispatch

配置缺失
section 缺失
flag 缺失
→ 保持原行为
```

模型在执行中也已经正确总结出该语义。

因此当前没有证据证明：

```text
RepoMap
Context Retrieval
context_budget = 8192
```

是主要 blocker。

禁止为了 F03：

```text
扩大 context budget
重做 RepoMap
重做 SymbolIndex
重做 FileRanker
```

---

# 七、F03 当前真实问题

模型已经理解：

```text
读取 notifications.email_dispatch_enabled

只有明确 false 时 suppress

missing config/section/flag
保持原 behavior
```

但它开始长期纠结一个局部不确定性：

```text
PyYAML 是否存在？
```

随后不断：

```text
read
search
list
read
search
run diagnostic attempt
read
search
...
```

最终：

```text
MAX_STEPS
```

因此准确问题定义为：

```text
Pre-edit Analysis Paralysis
```

或者：

```text
No Source Progress Under Uncertainty
```

---

# 八、为什么现有 Loop 没识别出来

当前 AgentLoop 已经能处理：

```text
完全相同 semantic action
→ REPEATED_ACTION
```

以及类似：

```text
cached read repeatedly
→ NO_PROGRESS
```

但 F03 的问题是：

```text
read A
read B
search C
list D
read E
search F
...
```

每一步形式都不同。

所以：

```text
Tool Activity > 0
```

但：

```text
Source Progress = 0
```

现有 Runtime 只能看到“Agent 很忙”，无法识别：

> Agent 其实已经很久没有推进代码状态。

本轮第一核心目标就是补这个能力。

---

# 九、本轮整体修改范围

建议严格拆成三个阶段：

```text
D1 — Progress-aware Agent Loop

D2 — Safe Environment Introspection

D3 — Initial Context Reuse + Progress Observability
```

按顺序完成。

---

# 十、D1：Progress-aware Agent Loop

## Problem

当前：

```text
20 steps
37 tool calls
0 patch
0 workspace change
```

只能等到：

```text
MAX_STEPS
```

才停止。

这不是理想 Runtime。

需要让 Runtime 区分：

```text
Tool Activity
```

与：

```text
Task / Source Progress
```

---

# 十一、区分 Source、Diagnostic 与 Completion Progress

第一版不要设计复杂“语义进度评分”，但也不能把所有非 patch 行为都混成同一种状态。

至少区分三类：

```text
Source Progress
    workspace_version changed
    例如 successful apply_patch

Diagnostic Progress
    获得新的、此前没有的任务相关证据
    例如首次读取新相关文件、首次得到测试失败、首次完成安全环境检查

Completion Progress
    当前 workspace_version 的 completion-required verification 通过
    当前版本 final diff 已检查
    CompletionGate ready
```

只有 `Source Progress` 可以重置：

```text
steps_since_workspace_change
```

`Diagnostic Progress` 可以说明探索仍有价值，并延缓或降低 advisory 强度，但不能无限重置 source-progress 计数。否则模型只要持续读取不同文件，就仍能逃避进展控制。

`Completion Progress` 用于识别任务已经进入收尾阶段，不应被误判为“还没有开始工作”。

不要把以下调用仅凭工具名称就视为 progress：

```text
read_file
search_code
list_files
git_status
environment inspection
```

重复、空结果或与任务无关的观察不属于新的 Diagnostic Progress。

---

# 十二、增加小型 ProgressTracker / ProgressPolicy

不要继续把大量 if 塞进 `agent_loop.py`。

如果当前代码没有适合承载该逻辑的已有对象，可新增非常小的：

```text
ProgressTracker
```

或：

```text
ProgressPolicy
```

建议位置遵循当前 package architecture，例如：

```text
codeteam/agent/
```

新增 abstraction 必须购买：

> 跨不同工具调用识别长期没有 source progress，并区分有效诊断探索与无效活动的能力。

不是为了文件拆分美观。

---

# 十三、ProgressTracker 最小状态

例如：

```text
current_step

workspace_version

last_workspace_change_step

steps_since_workspace_change

last_diagnostic_progress_step

unique_evidence_count

first_patch_step

pre_edit_tool_call_count

progress_advisory_count

progress_advisory_level

max_steps_without_workspace_change
```

根据真实代码结构适当调整。

不要一开始记录几十个状态。

---

# 十四、ProgressPolicy 不应该直接强制 Patch

禁止实现：

```text
连续 6 步没 patch
→ NO_PROGRESS
```

因为复杂 repository-level refactor 有可能合理地需要较长探索。

第一版主要应该是：

```text
Soft Intervention
```

而不是：

```text
Force Patch
```

但“不得强制 Patch”不等于允许 Agent 在两次 advisory 后继续无意义消耗到模糊的 `MAX_STEPS`。接近预算末尾时，Runtime 可以 fail-closed 地暂停并给出准确分类。

---

# 十五、建议两级 Soft Progress Checkpoint

不要硬编码 F03 的具体 step。

优先基于：

```text
max_steps
```

比例计算。

阈值按：

```text
model turn / Agent step
```

计算，不按同一 turn 中的单个 tool call 计算。一个 assistant turn 同时调用多个工具，不应导致 checkpoint 被重复触发。

Advisory 应注入到下一次正常 ModelRequest 中，不得为了 advisory 单独增加一次 Provider 调用、step 或 token 预算消耗。

例如概念上：

## Level 1

约：

```text
40% max_steps
```

如果：

```text
workspace_version unchanged
```

且没有 source progress：

向模型注入结构化 advisory：

```text
You have spent several steps without making a source change.

Summarize:
1. what is already known,
2. the single concrete uncertainty still blocking implementation,
3. the next action that resolves that uncertainty.

If the task is already actionable, make the smallest valid patch now.
Avoid broad repository exploration.
```

---

## Level 2

约：

```text
65–70% max_steps
```

仍无 source progress：

给予更强约束：

```text
No source progress has been made.

Do not continue broad repository exploration.

Choose one:
1. resolve one concrete blocker with an available diagnostic tool,
2. make the smallest reasonable implementation,
3. request user input if the missing fact cannot be discovered safely.
```

仍然不要自动失败。

Level 1 和 Level 2 在同一个 workspace_version 下各最多触发一次。真实 source patch 后，可以基于新版本重新开始观察；不能在每轮重复注入同一 advisory。

---

## Terminal safety net

约：

```text
85% max_steps
```

如果同时满足：

```text
workspace_version 始终未变化
Level 1 和 Level 2 已触发
之后仍没有 source progress
CompletionGate 未 ready
```

不要强制生成 patch，也不要继续等待通用 `MAX_STEPS`。应返回明确、可恢复的：

```text
PAUSED
failure_category = no_source_progress
```

并记录尚未解决的 blocker 与已有诊断证据。该行为是预算安全收口，不是“第 N 步强制修改代码”。

---

# 十六、为什么不是增加 max_steps

当前 F03：

```text
20 steps
37 tool calls
144k+ input tokens
0 patch
```

所以问题不是：

```text
step 不够
```

而是：

```text
decision → action transition 缺失
```

禁止通过：

```text
max_steps 20 → 30 / 40
```

掩盖问题。

---

# 十七、第一版不要加入按工具次数强制 Patch 的 Hard Exploration Budget

暂时不要：

```text
最多只能 read N 次
第 N+1 步强制 patch
```

本轮先验证：

```text
Soft Progress Advisory
+
terminal no-source-progress pause
```

是否足以改变行为并减少无意义预算消耗。

如果后续真实实验仍出现长时间 analysis paralysis，再根据数据设计更细的 hard policy。当前 terminal pause 只负责准确、低成本地停止，不负责替模型决定业务补丁。

---

# 十八、D1 必须测试的情况

## D1-1：不同工具但无 Source Progress

模拟：

```text
read A
read B
search C
list D
read E
search F
```

所有 action 都不同。

但：

```text
workspace_version 始终不变
```

必须触发：

```text
progress advisory
```

而不是只有 MAX_STEPS 才发现。

---

## D1-2：真实 patch 重置进度

```text
read
search
apply_patch
```

成功 patch 后：

```text
steps_since_workspace_change
```

必须 reset。

---

## D1-3：复杂任务允许合理探索

连续读取多个不同相关文件：

```text
不应过早失败
```

最多触发 soft advisory。

必须使用类似最新成功任务 B03 / F04 / R02 的多文件探索轨迹做 deterministic regression，证明新的策略不会在合理的首次 patch 之前提前失败或强制修改。

---

## D1-4：已有保护不能退化

原有：

```text
REPEATED_ACTION
cached NO_PROGRESS
MAX_STEPS
```

仍必须保留。

ProgressPolicy 不是 replacement。

---

## D1-5：Diagnostic Progress 不能无限重置 Source Progress

模拟不断读取不同文件，但始终没有 workspace change：

```text
new read A
new read B
new search C
new read D
...
```

新的相关证据可以降低 advisory 强度，但最终仍应触发 Level 1、Level 2 和 terminal `no_source_progress` pause。

---

## D1-6：Checkpoint 不额外消耗模型调用

断言 advisory 只附加到下一次正常请求：

```text
provider call count == normal Agent step count
```

不得因为触发 checkpoint 多请求一次模型。

---

## D1-7：Resume 语义明确

如果 ProgressTracker 状态进入 Session durable state，必须测试 schema migration 和跨进程 resume；如果选择在 resume 时重建，则必须明确：

```text
advisory streak 可以重置
累计 observability 不能丢失
workspace_version 必须从 Session / Git 对账恢复
```

不得让 resume 后的阈值行为处于未定义状态。

---

# 十九、D2：Safe Environment Introspection

F03 暴露了第二个真实工具边界缺口。

Agent 想知道：

```text
PyYAML 是否可用？
```

它试图通过：

```text
python -c "import yaml ..."
```

确认。

但 Runtime 拒绝是合理的。

---

# 二十、为什么不能放宽 run_tests

`run_tests` 是：

```text
authoritative visible verification
```

其职责是：

```text
运行 Runtime 允许的 task/regression verification commands
```

不能变成：

```text
任意 diagnostic command executor
```

因此禁止：

```text
run_tests 接受任意 argv
关闭 exact verification allowlist
```

---

# 二十一、为什么不能直接允许 python -c

当前 CommandPolicy 对：

```text
python -c
node -e
ruby -e
```

这类 interpreter string execution 应继续保持限制。

禁止为了 F03：

```text
允许 arbitrary python -c
```

这会扩大代码执行攻击面。

---

# 二十二、增加窄的 Environment Introspection Tool

建议新增：

```text
inspect_environment
```

或者如果现有工具风格更适合：

```text
check_python_module
```

优先复用已有：

```text
ToolRegistry
RuntimeToolbox
Sandbox
```

不要重新实现一套 command execution framework。

---

# 二十三、第一版支持范围要窄

推荐仅支持：

```text
python module availability
executable availability
project dependency declaration evidence
```

例如：

```json
{
  "python_module": "yaml"
}
```

返回不能只有一个模糊的 `available`，至少区分目标环境能力与项目依赖契约：

```json
{
  "module": "yaml",
  "runtime_available": true,
  "declared_by_project": false,
  "environment": "verification_sandbox"
}
```

或者：

```json
{
  "module": "yaml",
  "runtime_available": false,
  "declared_by_project": false,
  "environment": "verification_sandbox"
}
```

另一个可能接口：

```json
{
  "executable": "ruff"
}
```

项目声明证据应来自 workspace 中受支持的 manifest，例如当前 Python 项目的 `pyproject.toml`。不要假装能可靠完成所有 import name 到 distribution name 的映射；无法确定时返回明确的 `unknown`，不能猜测。

必须在 system/tool guidance 中说明：

> Runtime 中偶然可导入、但项目没有声明的第三方包，不应被视为可移植的生产依赖。Agent 应优先使用标准库、仓库已有依赖，或在任务允许时显式修改依赖声明。

---

# 二十四、禁止 arbitrary diagnostic code

不要给 Agent：

```text
code: "..."
```

这种参数。

模型不能让 Runtime 执行任意：

```text
python code string
shell string
```

如果内部需要 Python probe：

必须由 Runtime 构造固定逻辑，并通过现有 Sandbox/Docker 执行边界运行。模型只能提供经过 schema validation 的 module/executable 名称。

输入 module name 必须 schema validate。

例如只允许：

```text
[A-Za-z_][A-Za-z0-9_.]*
```

不要直接拼接未经验证字符串。

---

# 二十五、Environment Introspection 的执行环境

必须检查：

```text
Agent 实际运行/验证所在 Sandbox
```

不能：

```text
host .venv 有 yaml
```

就告诉 Agent：

```text
Docker runtime 有 yaml
```

Environment evidence 必须来自真实目标环境。

不得用 host `.venv` 的可用性替代 Sandbox 结果，也不得因为 Sandbox 偶然存在某个未声明模块就告诉 Agent“项目可以安全依赖它”。

---

# 二十六、Environment Introspection 不属于 Verification

必须保持以下 invariant：

调用：

```text
inspect_environment
```

不能影响：

```text
VerificationEvidence
tests_passed
CompletionGate
```

它只是：

```text
Diagnostic Evidence
```

不是：

```text
Task Correctness Evidence
```

---

# 二十七、D2 必须测试

至少：

### D2-1

存在 module：

```text
inspect python module
→ runtime_available = true
```

### D2-2

不存在 module：

```text
→ runtime_available = false
```

### D2-3

非法 module name：

```text
fail closed
```

### D2-4

不能执行任意 code。

### D2-5

调用 inspection：

```text
不会修改 workspace_version
不会增加 VerificationEvidence
不会使 CompletionGate ready
```

### D2-6

实际检查的是 sandbox environment，不是 host Python。

### D2-7

host 可用、Sandbox 不可用：

```text
→ runtime_available = false
```

### D2-8

Sandbox 可用、项目未声明：

```text
runtime_available = true
declared_by_project = false
```

不得把这种情况描述为可移植依赖。

### D2-9

项目已声明、Sandbox 不可用：

```text
runtime_available = false
declared_by_project = true
```

该结果应帮助 Agent 区分“依赖契约存在”与“当前验证环境缺失”。

---

# 二十八、暂时不要新增通用 run_command

虽然真实 Coding Agent 最终可能需要：

```text
run_command
```

但本轮不要因为 F03 直接开放。

当前需求只是：

```text
安全回答环境 capability question
```

使用一个窄 diagnostic tool 就足够。

如果未来多个真实任务证明：

```text
arbitrary safe dev commands
```

确实必要，再基于：

```text
SafeExecutionService
CommandPolicy
Approval
Sandbox
```

设计统一 command tool。

本轮不要提前做。

---

# 二十九、D3：Initial Context Duplicate-read Suppression

F03 还暴露明显 inefficiency：

initial context 已经提供：

```text
dispatcher.py
test_f03.py
feature_flags.yaml
email.py
```

但 Agent 后续又重新：

```text
read_file
read_file
read_file
```

其中多个文件实际上是完整内容重复获取。

---

# 三十、不要只靠 Prompt 告诉模型“别重读”

Prompt 可以保留：

```text
The initial context is a current snapshot.
Do not reread the same file unless...
```

但模型并不总能严格遵守。

因此建议 Runtime 对已有完整 Initial Context 做真正复用，但必须先明确目标：

```text
避免重复模型上下文
```

而不仅是：

```text
少做一次本地磁盘 read
```

如果 cache hit 仍把完整文件内容再次追加为 tool observation，文件仍会第二次进入模型输入，只节省了微不足道的文件 I/O，不能解释为 token 优化。

---

# 三十一、显式 InitialContextSnapshot

不要从序列化后的 user message 或经过 compaction 的消息反向解析缓存。

应在 `ContextBuildReport` 生成后、序列化进入 ModelRequest 前，构造小型显式快照，例如：

```text
path
content
content_hash
compression_level
workspace_version
is_complete
```

如果 initial context file 满足：

```text
compression_level == FULL_FILE
```

且：

```text
该内容对应当前 workspace_version
```

才可以把它作为：

```text
read_file(path)
```

的 current-version snapshot。

当模型重新读取：

```text
read_file("src/notifications/dispatcher.py")
```

如果该完整内容仍存在于当前实际发送给模型的 request messages 中，Runtime 应返回短、结构化引用：

```json
{
  "cache_hit": true,
  "path": "src/notifications/dispatcher.py",
  "content_hash": "...",
  "workspace_version": 0,
  "observation": "Full current-version content is already present in initial_context."
}
```

如果 message compaction 已经从本轮模型输入中移除了该文件内容，则不能只返回引用，必须返回缓存中的完整当前内容。

---

# 三十二、只能缓存完整快照，并保持 read_file 语义

严禁把：

```text
PATH_ONLY
SIGNATURE_ONLY
TRUNCATED
PARTIAL
```

当作完整 `read_file` 响应。

Invariant：

> Only complete current-version snapshots can satisfy a full-file read request.

同时处理 `read_file` 的：

```text
start_line
end_line
```

范围语义。不能用一个 full-file cache hit 响应错误满足不同的 ranged read，也不能遗漏真实 `read_file` 会执行的路径校验。

---

# 三十三、workspace 发生变化后必须失效

例如：

```text
initial context
workspace_version = 0

apply_patch
workspace_version = 1
```

那么旧：

```text
FULL_FILE snapshot v0
```

不能继续满足：

```text
read_file
```

应该重新读取当前 workspace。

缓存键至少包含：

```text
canonical path
content hash
workspace version
read range
```

resume 后必须通过持久化证据或 Git/workspace 对账确认版本；不能默认旧 snapshot 仍然有效。

---

# 三十四、不要复用现有 Repeated-action Cache 的停止计数

Initial-context duplicate suppression 与当前运行后的 `tool_result_cache` 目的不同。

禁止直接让 initial-context cache hit 推进：

```text
cached_no_progress_count
```

否则模型在同一个 assistant turn 中重新读取两个 initial-context 文件时，可能在第二个 cached result 后直接触发 `NO_PROGRESS`，剩余 tool calls 未执行，形成新的 control-plane false negative。

Initial-context hit 应记录独立 metric，并正常生成对应 `ToolResult`；是否构成长期无进展，由 ProgressPolicy 在 model-turn 边界统一判断。

同时不要伪造：

```text
list_files
search_code
```

初始 RepoMap 不是这两个工具的真实完整结果。

---

# 三十五、Initial Context Reuse 不应改变 correctness 语义

它是：

```text
performance / efficiency optimization
```

不是 correctness shortcut。

当返回完整内容时，内容必须等价于真实 `read_file`；当返回短引用时，必须证明同一完整 current-version 内容仍在本轮实际 ModelRequest 中可见。

---

# 三十六、D3 测试

至少：

### D3-1

FULL_FILE initial context：

```text
read_file
→ compact reference cache hit when initial content is still model-visible
```

### D3-2

TRUNCATED：

```text
read_file
→ real backend read
```

### D3-3

patch 后：

```text
old initial cache invalid
```

### D3-4

cache hit：

```text
不推进 workspace_version
```

### D3-5

cache content 与真实 initial snapshot 完全一致。

### D3-6

structured compaction 已移除 initial file content：

```text
read_file
→ 返回完整缓存内容，不能只返回 pointer
```

### D3-7

同一 assistant turn 读取多个 initial-context 文件：

```text
不会因 cached_no_progress_count 提前停止
```

### D3-8

`start_line/end_line` 不同的 ranged read 保持正确结果。

### D3-9

断言 compact reference 相比完整重复内容真实减少下一轮估算 input tokens；不能只断言 backend 没有调用文件读取。

---

# 三十七、Progress Observability

当前已经有非常好的：

```text
completion_ready_count
post_ready_tool_call_count
verification_workspace_mutation_count
```

本轮建议继续补最小必要指标。

---

# 三十八、建议新增指标

至少：

```text
first_patch_step
pre_edit_step_count
pre_edit_tool_call_count
progress_advisory_count
progress_advisory_level_counts
no_source_progress_pause_count
max_no_source_progress_streak
```

建议增加：

```text
environment_inspection_count
initial_context_cache_hit_count
initial_context_reference_hit_count
source_progress_count
diagnostic_progress_count
```

如果实现成本很低，还可以：

```text
first_environment_inspection_step
```

---

# 三十九、为什么 first_patch_step 很重要

当前 F03：

```text
first_patch_step = null
```

这比：

```text
total steps = 20
```

更直接解释问题。

未来复杂任务可能：

```text
first_patch_step = 9
```

但最终成功。

这说明：

```text
探索较长
```

不一定等于失败。

因此 Progress 策略不能简单拿 total reads 做 hard limit。

---

# 四十、不要现在优化 Message Compaction

F03 当前有：

```text
144k+ input tokens
```

确实很高。

但很大一部分来自：

```text
20-step analysis paralysis
```

先修：

```text
Progress Control
```

再重新观察：

```text
steps
tokens
cost
```

如果无效 step 已显著下降后 message token 仍然过高，再单独研究 Context Compaction。

禁止本轮同时修改：

```text
context budget algorithm
message compaction
token window management
```

否则无法判断收益来自哪里。

---

# 四十一、不要根据 R02 上一轮失败写 task-specific hack

上一轮 R02 hidden acceptance 曾失败。

最新 11-task：

```text
R02 success
```

因此它目前更像：

```text
LLM semantic stability variance
```

而不是稳定 Harness bug。

禁止：

```text
把 RuntimeError retry 写进 system prompt
为 RetryExecutor 增加 task-specific heuristic
读取 hidden oracle 后修改 Agent
```

---

# 四十二、本轮明确不要修改的模块

除非当前真实代码存在直接兼容需求，否则禁止大改：

```text
CompletionGate
submit_result
workspace-version completion evidence

Sandbox tmpfs
VerificationEnvironmentPreflight

ModelRequest
ModelTurn
Provider Adapter
native tool calling

Context retrieval / RepoMap
SymbolIndex
ImportGraph

Planner
RepairLoop

CheckpointManager safety rules

Multi-Agent
Scheduler
Mailbox
```

---

# 四十三、本轮不执行真实 LLM Evaluation

**B01、F03 和 11-task 的真实 LLM 验证都由用户本人执行。**

Coder 不得运行任何真实 Provider 的：

```text
.venv/bin/python -m codeteam.cli.app agent-eval ... --actor llm
```

包括：

```text
单题 B01
单题 F03
完整 agent_task_suite_v1.jsonl
```

即使你认为修改已完成，也不要自行调用真实 LLM 验证。

最终只能写：

```text
No post-change real-LLM evaluation was executed by the coder.
Pending user-run validation.
```

## 用户运行的稳定性验收脚本

Coder 必须新增一个可复用脚本：

```text
scripts/run_single_agent_stability_validation.sh
```

该脚本是交付物，只能由 Coder 做 shell 语法检查和不访问 Provider 的 deterministic test；Coder 不得实际执行其中的真实 LLM 命令。

脚本必须按顺序执行：

```text
F03 × 5
↓
B01 × 2
↓
11-task × 3
```

每次 invocation 必须使用真实 CLI：

```bash
.venv/bin/python -m codeteam.cli.app agent-eval
```

共同参数与本轮事实基线保持一致：

```text
--suite evals/week4/agent_task_suite_v1.jsonl
--actor llm
--mode baseline
--context-budget 8192
--max-output-tokens 4096
--model-context-window 32768
--safety-headroom-tokens 1024
--native-tools
--no-reasoning
--worktree-root "$HOME/.codeteam/worktrees"
```

F03/B01 使用各自的：

```text
--task-id F03
--task-id B01
```

完整 11-task 不传 `--task-id`。

脚本还必须满足：

```text
set -euo pipefail
从脚本位置可靠定位仓库根目录
只使用项目 .venv/bin/python
不读取、打印或复制 API key；由现有 CLI 自行加载 secrets.local.env
支持 --dry-run；只打印将执行的命令和输出目录，不调用 CLI/Provider
支持 --output-root 指定整次 campaign 根目录
每次运行使用独立且带时间戳/序号的 --output
output 必须位于被 Git 忽略的 evals/week4/agent_runs/
单次业务失败不能导致剩余重复实验被跳过
记录每个 CLI 进程 exit code
支持通过环境变量选择是否 --keep-workspaces，默认不保留，避免 33 个 task worktree 长期堆积
最终从每次 summary.json/results.jsonl 生成一个总 stability_summary.json
不得依赖 jq；汇总使用 .venv/bin/python
验收阈值未满足时脚本最终返回非零，但必须先完成并汇总所有计划运行
```

最终汇总至少包含：

```text
run group / repetition / output path / process exit code
success_count / task_count
provider_blocked_count / environment_blocked_count
protocol_failed_count
failure_category_counts
completion_ready_but_actor_failed_count
verification_workspace_mutation_count
总 steps / input tokens / output tokens / cost
每个 task 在重复运行中的 success 次数
first_patch_step / pre_edit_step_count / pre_edit_tool_call_count
progress advisory level/count / no_source_progress pause
environment inspection count
initial-context reference/full cache hit count
```

脚本验收标准：

```text
F03:
    success >= 4/5
    max_steps = 0/5
    provider/environment/protocol failure = 0/5
    verification workspace mutation = 0/5

B01:
    success = 2/2
    control-plane false negative = 0/2

11-task:
    共 3 轮 / 33 episodes
    每轮 security = 11/11
    总体 task success >= 90%
    每个 task 至少 success 2/3
    control-plane false negative = 0
    verification workspace mutation = 0
```

Provider/environment 可用性同时属于产品稳定性指标，不能从原始 operational success 中静默排除；可以额外报告排除环境故障后的 conditional capability，但必须与原始结果并列。

---

# 四十四、本轮不执行 Benchmark

不要执行：

```text
Benchmark
Ablation
multi-run success rate
performance benchmark
token benchmark
cost benchmark
```

即使增加了：

```text
first_patch_step
progress_advisory_count
```

也不能自己跑 benchmark 填数字。

相关文档统一写成：

```text
No post-change benchmark was executed by the coder.
Pending user-run validation.
```

不得编造数据。

---

# 四十五、允许执行的测试

可以并且必须运行项目自身 deterministic tests。

至少根据实际改动运行：

```bash
.venv/bin/python -m pytest tests/agent -q
```

```bash
.venv/bin/python -m pytest tests/execution -q
```

```bash
.venv/bin/python -m pytest tests/sandbox -q
```

```bash
.venv/bin/python -m pytest tests/evaluation -q
```

如果修改 Session/resume durable state，还必须运行：

```bash
.venv/bin/python -m pytest tests/session -q
```

本轮修改覆盖 Runtime、Sandbox、Evaluation 和 Context 边界，最终必须运行：

```bash
.venv/bin/python -m pytest -q
```

同时必须运行触达范围静态检查和 diff 检查：

```bash
.venv/bin/python -m ruff check <touched production and test paths>
.venv/bin/python -m mypy <touched production and test paths>
git diff --check
bash -n scripts/run_single_agent_stability_validation.sh
bash scripts/run_single_agent_stability_validation.sh --dry-run
```

如果 mypy 因已知 import-chain 历史债失败，必须区分：

```text
本轮触达文件新增错误
历史/导入链错误
```

不得把新增类型错误归入历史债，也不得因此跳过命令。

必须使用：

```text
.venv/bin/python
```

运行 CodeTeam 自身项目测试。

---

# 四十六、可以使用 FakeModel 做 deterministic integration

建议增加一个类似 F03 行为的 Fake Model：

```text
Turn 1 read A
Turn 2 search B
Turn 3 read C
Turn 4 list D
Turn 5 search E
...
```

每次 action 都不同：

```text
不触发 REPEATED_ACTION
```

但：

```text
workspace_version 始终不变
```

验证 ProgressPolicy 能触发 advisory。

不需要真实 DeepSeek。

---

# 四十七、建议变更分组

按三个可独立 review 的变更组组织。除非用户明确授权 Coder 提交，否则只保持 commit-ready，不得自行 `git commit`。

## Change Group D1

```text
feat(agent): add source-progress checkpoints
```

包含：

```text
ProgressTracker / Policy
soft advisory
progress metrics
相关 tests
```

---

## Change Group D2

```text
feat(agent): add safe environment introspection
```

包含：

```text
inspect_environment
python module capability
executable capability
sandbox-backed implementation
security tests
```

---

## Change Group D3

```text
perf(agent): suppress duplicate initial-context reads
```

包含：

```text
explicit InitialContextSnapshot
compaction-aware compact reference
version invalidation
cache metric
相关 tests
```

如果真实代码依赖关系决定 D1 与 metrics 必须一起提交，可以合并。

---

# 四十八、Design Decision 要求

本项目核心模块仍遵循：

```text
Design Decision
Benchmark
Ablation
Failure Case
```

但本轮：

```text
Benchmark/Ablation 不执行
```

只设计并标记 pending。

本轮代码与设计变更必须同步维护：

```text
README.md
learning-plan/代码架构.md
learning-plan/设计决策.md
learning-plan/单Agent执行闭环修复记录.md
对应 Week4 Day7 Design Decision / Failure Case 文档
```

其中 `单Agent执行闭环修复记录.md` 必须继续使用连贯的“问题 → 方法 → 新问题 → 新方法 → 证据”叙事，追加本次 F03 analysis paralysis、进展控制、诊断能力和后续用户验证状态，不得改写为孤立的功能列表。

---

# 四十九、DD：Progress-aware Agent Execution

新增或更新 DD。

至少包括：

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

> Repeated-action detection only recognized identical/cached actions and could not identify long sequences of diverse read/search operations with zero source progress.

Alternatives 至少讨论：

```text
increase max_steps
hard read limit
prompt-only intervention
soft source-progress checkpoints
soft checkpoints + terminal paused safety net
```

Decision：

```text
source/diagnostic/completion progress separation
soft source-progress checkpoints
terminal no_source_progress pause near budget exhaustion
```

不要第一版 hard fail。

这里的 terminal pause 不是 correctness failure，也不是强制 patch；它是 fail-closed 的预算收口和可恢复状态。

---

# 五十、DD：Environment Introspection

Problem：

> The agent could not safely resolve simple runtime capability uncertainty without abusing completion verification commands or arbitrary interpreter execution.

Alternatives：

```text
allow python -c
open generic run_command
hardcode dependency assumptions
safe capability introspection
```

Decision：

```text
safe capability introspection
```

同时记录：

```text
runtime availability != project dependency declaration
```

以及为什么未声明但偶然安装在 Sandbox 的包不能被当作可移植生产依赖。

---

# 五十一、Failure Case：F03 Analysis Paralysis

记录真实案例：

```text
task context sufficient
↓
model understands target behavior
↓
uncertainty: PyYAML availability
↓
cannot safely inspect environment
↓
repeated broad read/search/list
↓
20 steps
37 tool calls
0 patch
↓
MAX_STEPS
```

Root Cause 不要写：

```text
Context retrieval failed
```

也不要写：

```text
Model cannot understand YAML feature flags
```

而应写成分层原因：

> Primary: the Runtime lacked progress-aware intervention after the model had enough information to act. Secondary: the Runtime had no narrow diagnostic affordance for environment capability uncertainty. Efficiency contributor: complete initial-context files were reread without a compaction-aware duplicate-read mechanism.

必须如实记录：模型在第 19 步已经提出可执行的最小解析方案，但仍未 patch。这证明 environment introspection 不是充分修复，D1 才是主要控制面修复。

---

# 五十二、Benchmark 设计但不执行

后续用户运行 11-task 后可以比较：

```text
success_count

first_patch_step
pre_edit_step_count
pre_edit_tool_call_count

progress_advisory_count
environment_inspection_count
initial_context_cache_hit_count

steps
tokens
cost
```

但当前修改完成后只能写：

```text
No post-change benchmark was executed by the coder.
Pending user-run validation.
```

---

# 五十三、Ablation 设计但不执行

可以记录未来：

```text
A:
Current runtime

B:
+ ProgressPolicy

C:
+ ProgressPolicy
+ Environment Introspection

D:
+ ProgressPolicy
+ Environment Introspection
+ Initial Context Cache
```

比较：

```text
first patch latency
pre-edit steps
success
token usage
```

本轮不得运行。

---

# 五十四、修改完成后的汇报格式

完成后必须按以下结构回复。

## 1. Root Cause Confirmation

说明真实代码和过程文件是否确认：

```text
F03 context sufficient?
F03 source progress = 0?
current no-progress detection limitation?
environment introspection gap?
initial context duplicate reads?
```

---

## 2. Files Changed

逐项：

```text
path
what changed
why
```

任何新增文件必须回答：

> 为什么不能复用现有模块？

---

## 3. Progress Architecture

给出修改后的：

```text
Agent actions
↓
ProgressTracker
↓
workspace-version/source-progress observation
↓
source / diagnostic / completion progress classification
↓
soft checkpoint
↓
model advisory
↓
terminal no_source_progress pause when required
```

---

## 4. Environment Inspection Flow

```text
Model
↓
inspect_environment
↓
validated capability request
↓
target sandbox
↓
structured result
```

说明为什么不存在 arbitrary code execution。

---

## 5. Initial Context Reuse

说明：

```text
哪些 compression level 可以 cache
什么时候失效
怎么保证内容正确
什么时候返回 compact reference
什么时候必须返回完整内容
为什么不会复用 cached_no_progress_count
```

---

## 6. Safety Compatibility

必须说明：

```text
CommandPolicy
SafeExecutionService
Sandbox
run_tests allowlist
Checkpoint
```

是否发生变化。

尤其明确：

```text
python -c arbitrary execution
```

是否仍被禁止。

---

## 7. Tests

列出：

```text
test path
case
command
actual result
```

不得编造。

---

## 8. User-run Stability Script

必须列出：

```text
scripts/run_single_agent_stability_validation.sh
```

说明脚本将执行：

```text
F03 × 5
B01 × 2
11-task × 3
```

以及 output root、配置方式、汇总文件路径和验收阈值。必须明确脚本只生成并做 deterministic validation，Coder 没有执行真实 LLM。

---

## 9. Real LLM Evaluation

必须明确写：

```text
No post-change real-LLM evaluation was executed by the coder.
Pending user-run validation.
```

---

## 10. Benchmark

必须写：

```text
No post-change benchmark was executed by the coder.
```

---

## 11. Design Decisions

列出 DD 路径。

---

## 12. Failure Case

列出 F03 Failure Case 更新路径。

---

## 13. Remaining Limitations

必须真实说明，例如：

```text
ProgressPolicy uses explicit source/diagnostic/completion evidence rather than claiming full semantic task understanding.

Environment introspection supports only narrow capabilities.

Initial-context duplicate suppression only supports complete current-version snapshots and compact references while that content remains model-visible.

No forced-patch exploration budget is implemented; the terminal safety net pauses instead of fabricating a patch.
```

---

# 五十五、最终验收清单

只有同时满足这些条件，本轮才算完成：

```text
[ ] 能识别“不同工具调用但长期无 source progress”

[ ] 区分 source / diagnostic / completion progress

[ ] Diagnostic Progress 不能无限重置 Source Progress

[ ] Progress checkpoint 不额外发起 Provider 调用

[ ] ProgressPolicy 第一版以 soft intervention 为主，不强制生成 patch

[ ] 接近预算耗尽且仍无 source progress 时进入 PAUSED/no_source_progress，而不是模糊 MAX_STEPS

[ ] successful source patch 会 reset progress state

[ ] 原有 REPEATED_ACTION / NO_PROGRESS / MAX_STEPS 仍保留

[ ] 没有通过提高 max_steps 掩盖问题

[ ] 有窄的 environment introspection capability

[ ] Environment tool 不允许 arbitrary code

[ ] python -c 等危险 interpreter string execution 未被放宽

[ ] environment inspection 在真实 target sandbox 中执行

[ ] environment inspection 区分 runtime availability 与 project dependency declaration

[ ] 未声明但 Sandbox 偶然可用的依赖不会被描述为可移植生产依赖

[ ] environment inspection 不修改 VerificationEvidence

[ ] environment inspection 不贡献 CompletionGate

[ ] FULL_FILE initial context 能被显式 InitialContextSnapshot 安全复用

[ ] partial/truncated context 不会伪装成 full-file read

[ ] workspace change 后旧 initial-context cache 失效

[ ] initial content 仍 model-visible 时返回 compact reference，已被 compaction 移除时返回完整内容

[ ] initial-context cache hit 不推进 cached_no_progress_count

[ ] ranged read 保持正确语义

[ ] 有测试证明 duplicate-read suppression 真实减少 input token estimate，而不只是减少磁盘读取

[ ] 增加 first_patch/pre-edit/progress 等必要 observability

[ ] CompletionGate 没有被无理由重构

[ ] Sandbox scratch 没有被无理由重构

[ ] Provider/native tools 没有被无理由重构

[ ] Context Retrieval 没有因 F03 被大规模重构

[ ] 没有针对 F03/YAML 写 task-specific hack

[ ] 没有针对 R02 写 hidden-oracle-specific hack

[ ] 项目自身相关 tests 真实通过

[ ] Design Decision 已更新

[ ] Failure Case 已更新

[ ] README / 代码架构 / 设计决策 / 单Agent执行闭环修复记录已同步

[ ] 已生成 scripts/run_single_agent_stability_validation.sh

[ ] 脚本封装 F03 × 5、B01 × 2、11-task × 3，并生成 stability_summary.json

[ ] 脚本只做 bash -n / deterministic test，未被 Coder 实际调用真实 Provider

[ ] coder 没有执行 B01 / F03 / 11-task 真实 LLM evaluation

[ ] coder 没有执行 Benchmark

[ ] coder 没有执行 Ablation
```

---

# 五十六、核心设计原则

本轮始终遵循：

```text
Activity != Progress
```

模型调用很多工具，不代表任务在前进。

---

```text
Uncertainty should be resolvable safely.
```

Agent 不应该为了知道一个 Python module 是否存在而获得 arbitrary code execution。

---

```text
Runtime should encourage action,
not perform business reasoning for the model.
```

ProgressPolicy 负责提醒：

```text
你已经很久没有推进 source state
```

但不负责告诉模型：

```text
F03 应该怎么写 YAML parser
```

---

```text
Initial context is an asset,
not merely prompt text.
```

如果 Runtime 已经持有当前完整文件快照，就应该能够安全复用，而不是反复消耗 step/token 再读一次。

最终目标是把当前：

```text
uncertainty
↓
broad exploration
↓
more exploration
↓
MAX_STEPS
```

变成：

```text
uncertainty
↓
focused diagnosis
↓
decision
↓
source progress
↓
verification
↓
completion
```

本轮完成后，不要自行执行 11-task。由用户使用相同配置亲自进行真实 LLM 验证，并根据新增的 progress metrics 判断本轮修改是否真正减少 pre-edit exploration 和无效 token 消耗。
