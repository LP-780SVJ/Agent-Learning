# CodeTeam Week4 SingleAgent 第二阶段修复：Sandbox Isolation + Versioned Completion + Runtime-owned Finalization

## 角色

你现在是 **CodeTeam / Coding Agent Runtime 代码修改工程师**。

本次任务不是继续优化模型 Prompt，也不是提升 Context Retrieval，更不是重新设计整个 SingleAgent。

当前 Week4 SingleAgent 已经完成：

```text
ModelRequest / ModelTurn
        ↓
Provider-native Tool Calling
        ↓
Runtime ToolCall
        ↓
SafeExecutionService
```

同时已经完成：

```text
Sandbox Infrastructure Preflight
+
Verification Environment Preflight
```

最新 11-task 真实执行结果为：

```text
task_count                      = 11
success_count                   = 5
acceptance_passed_count         = 9
task_verification_passed_count  = 10
regression_passed_count         = 10
security_passed_count           = 11

provider_blocked_count          = 0
environment_blocked_count       = 0

protocol_repair_attempt_count   = 5
protocol_failed_count           = 0
```

完整过程文件位于：

```text
evals/week4/agent_runs/verification_contract_11task_20260829_134620/
```

你必须以：

```text
week4 最新代码
+
上述 11-task 过程文件
```

作为事实依据。

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

开始修改前，必须阅读：

```text
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
README.md

evals/week4/agent_runs/verification_contract_11task_20260829_134620/
```

当前 Git 工作区还包含一组用户已经确认要保留的删除：仓库根目录旧的
`verification_contract_11task_20260829_134620/` 曾被提交，现已删除；真实本地
实验副本位于被 `.gitignore` 排除的 `evals/week4/agent_runs/` 下。

Coder 必须：

```text
使用 evals/week4/agent_runs/... 作为只读诊断证据
保留根目录旧实验文件的既有删除状态
不得 restore/checkout/reset 这些删除
不得重新把 agent_runs 实验输出加入 Git
不得把这些用户预存变更混入自己的文件修改说明
```

尤其完整检查以下失败任务的过程文件：

```text
B02
B03
F01
F03
R02
R03
```

重点阅读：

```text
results.jsonl
summary.json
manifest.json

_artifacts/<task_id>/runtime_messages.json
_artifacts/<task_id>/model_outputs.jsonl
_artifacts/<task_id>/verification.json
_artifacts/<task_id>/final.diff
```

---

# 二、当前 11-task 的真实 Failure Taxonomy

不要把 `5/11` 理解成“模型有 6 道题不会做”。

完整过程文件已经证明：

```text
B02
B03
F01
R03
```

都属于：

```text
最终代码 correctness 已通过
task verification ✓
regression ✓
hidden acceptance ✓
security ✓
```

但 Actor 最终因为 Runtime control-flow：

```text
repeated_action
```

失败。

因此这 4 个属于：

```text
Control-plane False Negative
```

---

## F03

F03 不是简单的模型 reasoning failure。

真实过程：

```text
pytest verification
        ↓
pytest tmp_path / temp artifacts
写入 Git source workspace
        ↓
pytest-of-root/
symlink
untracked files
        ↓
后续 apply_patch
        ↓
CheckpointManager 尝试 snapshot
        ↓
安全地拒绝 symlink
        ↓
所有后续 patch 无法继续
        ↓
Agent 最终耗尽 steps
```

因此 F03 的核心 Root Cause 是：

```text
Verification scratch data
污染 source workspace
```

不是：

```text
CheckpointManager 太严格
```

CheckpointManager 拒绝 symlink 是正确安全 invariant。

---

## R02

R02 是当前 11 个任务中明确的真实 semantic coding failure。

Actor：

```text
completed ✓
task verification ✓
regression ✓
security ✓
```

但：

```text
hidden acceptance ✗
```

原因是 retry refactor 没有正确覆盖 transient exception semantics。

本次不要针对 R02 hidden oracle 打补丁，也不要修改 benchmark 数据。

这是后续 Agent reasoning quality 问题。

---

# 三、本次整体修复目标

本次只完成三个核心阶段：

```text
Phase A
Sandbox Scratch Isolation

        ↓

Phase B
Versioned Completion Evidence

        ↓

Phase C
Runtime-owned Native Finalization
```

严格按顺序完成。

不要把三个问题混成一次无边界的大重构。

---

# 四、非常重要：本次禁止执行的任务

## 禁止 coder 执行 B01

不要运行任何：

```text
agent-eval --task-id B01
```

B01 由用户本人执行。

---

## 禁止 coder 执行 11-task

不要执行：

```text
agent_task_suite_v1.jsonl
```

完整 11-task。

11-task 由用户本人执行。

---

## 禁止执行 Benchmark

不要执行任何：

```text
benchmark
ablation
baseline suite
performance benchmark
multiple repeated eval runs
```

本次只允许：

```text
单元测试
Fake Provider integration test
Sandbox integration test
针对 Runtime 的 deterministic regression test
```

本轮修复前的历史诊断基线可以引用，但必须标明来源：

```text
Pre-fix 11-task baseline: 5/11
source: evals/week4/agent_runs/verification_contract_11task_20260829_134620
```

本轮修改完成后的效果不得推测，必须写：

```text
Post-fix B01: NOT_RUN_BY_CODER / pending user validation
Post-fix 11-task benchmark: NOT_RUN / pending user validation
Post-fix ablation: NOT_RUN
```

不得编造数字。

---

# 五、第一步：先审查真实代码

正式修改前，先输出：

```text
涉及文件

当前：
SandboxProfile
DockerCommandBuilder
DockerRunner
CheckpointManager
RuntimeEvidence
VerificationEvidence
RuntimeToolbox
AgentLoop
CodingAgentRuntime
ToolRegistry
Final Output handling
repeated_action handling

分别如何工作
```

并明确本提示词中的判断是否仍与当前真实代码一致。

若代码已经部分修复，必须基于当前最新实现继续，不得重复实现。

---

# 六、Phase A：Sandbox Scratch Isolation

## Problem

当前 Docker 通常采用：

```text
read-only root filesystem
+
writable /workspace
```

Verification 执行 pytest 后，真实出现：

```text
pytest-of-root/
pytest-current
symlink
temporary config files
```

写入 source Git workspace。

后果已经真实发生：

### B03

正确代码已经完成，但 pytest 临时 artifact：

```text
污染 Git status
↓
Agent 继续清理
↓
最终 repeated_action
```

### F03

更加严重：

```text
pytest artifact
↓
包含 symlink
↓
CheckpointManager 拒绝 snapshot
↓
后续真实 source patch 永久无法执行
```

---

# 七、正确设计边界

目标：

```text
Source Workspace
/workspace
    ↓
Verification 时默认只读，只存：
repo files
Agent intended edits

Ephemeral Scratch
/tmp
    ↓
存：
pytest tmp_path
tempfile
temporary test files
runtime cache
```

也就是说：

> Verification runtime scratch 不应该默认写入 Git source workspace。

本轮采用纵深防御：

```text
第一层：run_tests 专用 SandboxProfile 将 /workspace 以 readonly 挂载
第二层：为 /tmp 提供 bounded writable tmpfs
第三层：显式重定向 temp/cache/bytecode 环境变量
第四层：verification 前后做 workspace fingerprint/hygiene 检查
```

Patch 继续由 host 侧 `SafeExecutionService` Patch Lane 修改 source workspace；
不能因为 verification 只读而绕过现有 Patch 安全链。

---

# 八、Docker Scratch 最小修改方案

优先在现有：

```text
SandboxProfile
DockerCommandBuilder
DockerRunner
```

上扩展。

建议概念上增加：

```text
bounded tmpfs /tmp
run_tests-specific workspace_write=False
```

例如 Docker argv 等价于：

```text
--tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777,size=<bounded>
```

并显式提供：

```text
TMPDIR=/tmp
TMP=/tmp
TEMP=/tmp
HOME=/tmp/home
XDG_CACHE_HOME=/tmp/cache
PYTHONPYCACHEPREFIX=/tmp/pycache
```

还必须处理 pytest cache，避免 `.pytest_cache` 回写 source workspace。优先采用
run_tests 专用、固定且不可由模型覆盖的环境配置；如果使用
`PYTEST_ADDOPTS=-p no:cacheprovider`，必须增加测试证明它只关闭 cache provider，
不改变 task oracle、test selection 或其他 pytest 行为。

如果某个未来任务确实需要写 workspace，必须由显式、受审计的任务/验证契约选择
受限 writable mount；不得因此把所有 verification 默认恢复为 writable。

具体实现遵循当前 Docker builder 风格。`tmpfs_mb` 必须有正数范围校验和合理上限，
不得允许模型控制 tmpfs mount 参数或环境变量。

---

# 九、不要过度设计

本次不要新建：

```text
MountManager
UniversalFilesystemPolicy
ScratchVolumeManager
LanguageRuntimeFilesystem
```

如果只需在 `SandboxProfile` 增加类似：

```python
tmpfs_mb: int = ...
```

即可完成，不要额外造 abstraction。

这个复杂度购买的能力必须明确：

```text
Ephemeral runtime scratch isolation
```

---

# 十、不要修改 CheckpointManager 的 Symlink 安全规则

明确禁止：

```text
允许 checkpoint snapshot symlink
忽略 symlink
follow symlink
把 symlink 当 regular file
```

当前 Checkpoint fail-closed 是正确安全行为。

真正的问题发生在：

```text
verification process
```

不应该首先污染 workspace。

---

# 十一、增加 Workspace Hygiene Detection

Scratch isolation 解决当前 pytest 问题，但 Verification 仍可能产生：

```text
.coverage
cache
generated output
snapshot update
formatter change
compiler output
```

因此建议在 `run_tests` 或其相邻 Runtime 层增加：

```text
before workspace fingerprint
↓
verification
↓
after workspace fingerprint
```

至少能够检测：

```text
verification_introduced_workspace_changes
```

不要立即自动删除。

Fingerprint 不能只比较 changed-file 路径集合，因为 verification 可能修改一个本来
已经被 Agent 修改的文件，路径不变但内容已经变化。Fingerprint 至少要覆盖：

```text
tracked diff content
untracked non-ignored path + content
symlink metadata（不得跟随 target）
```

优先复用现有 GitWorkspace / snapshot helper；不要再写一套不安全的目录递归。

目标是 Runtime 能知道：

```text
Verification changed source workspace
```

而不是默默把它当 Agent patch。

---

# 十二、Workspace Mutation 与 workspace_version

当前需要检查：

```text
workspace_version
```

是否只由：

```text
apply_patch
```

推进。

如果 Verification 确实造成 Git workspace mutation，但：

```text
workspace_version
```

不变，那么 Runtime state 和真实 workspace state 不一致。

本次应该建立 invariant：

> Runtime 对 workspace mutation 的版本认知必须和实际 source workspace 一致。

最优方案优先是：

```text
verification 不污染 source workspace
```

Workspace Hygiene Detection 作为防守层。

不要靠“verification 每次都 workspace_version++”掩盖 scratch pollution。

真实状态推进顺序必须是：

```text
capture before fingerprint/version
↓
run verification
↓
capture after fingerprint
↓
if fingerprint changed:
    workspace_version++
    classify verification-introduced mutation
↓
record VerificationEvidence against the resulting current workspace_version
```

如果 verification 引入 source mutation：

```text
不得把它默认为 Agent intended diff
不得让旧 verification evidence 继续满足 completion
不得要求模型清理基础设施垃圾
应阻止 CompletionGate ready，并给出 workspace_hygiene_failed / 等价 typed 状态
```

---

# 十三、Phase A 核心测试

至少覆盖：

## A1. Writable scratch

Docker 内：

```text
python tempfile
pytest tmp_path
```

可以正常创建临时文件。

---

## A2. Temp path 不进入 Git workspace

执行一个使用：

```text
pytest tmp_path
```

的测试。

断言：

```text
GitWorkspace.changed_files()
```

中没有：

```text
pytest-of-root
pytest-current
```

---

## A3. Verification 后仍能 checkpoint

流程：

```text
run pytest using tmp_path
↓
CheckpointManager.create()
```

必须成功。

---

## A4. Verification 后仍能 apply_patch

流程：

```text
verification
↓
apply_patch
```

必须正常进入现有：

```text
SafeExecutionService
```

并成功修改 source。

---

## A5. Checkpoint symlink protection regression

真实 source workspace 人工存在危险 symlink 时：

```text
CheckpointManager
```

仍必须拒绝。

---

## A6. Read-only source workspace

Verification 中尝试直接写 `/workspace/src/...` 必须失败；同一个容器仍能写 `/tmp`。
断言失败不会回退 host shell，也不会改变 Git workspace。

---

## A7. Content-sensitive hygiene fingerprint

先让 Agent 修改 `src/example.py`，再模拟 verification 修改同一路径的内容。即使
changed-file 路径集合完全相同，也必须检测到 fingerprint 变化、推进 version，并阻止
旧 verification evidence 满足 completion。

---

# 十四、Phase B：Versioned Completion Evidence

## Problem

当前：

```text
RuntimeEvidence.workspace_version
```

会在成功 patch 后递增。

但：

```text
VerificationEvidence
```

没有记录它是在哪个 workspace version 上产生的。

同时：

```text
git_diff_checked
```

通常只是 bool。

这会产生严重 stale evidence 风险：

```text
workspace v1
↓
tests PASS
↓
workspace v2
↓
再次 patch
↓
旧 test PASS 仍可能被认为有效
```

如果此时直接增加 CompletionGate：

```text
tests_passed
+
git_diff_checked
→ READY
```

就可能产生 False Success。

---

# 十五、VerificationEvidence 必须版本化

最小目标：

```python
VerificationEvidence(
    ...
    workspace_version: int
)
```

每次 Verification 执行时，记录：

```text
当前 RuntimeEvidence.workspace_version
```

历史 Verification 不要删除。

---

# 十六、不要 clear verification history

禁止：

```python
verification.clear()
```

因为：

```text
v1 PASS
v2 FAIL
v3 PASS
```

对于：

```text
repair
trace
evaluation
observability
```

都非常有价值。

正确方式：

```text
history 保留

Completion 只消费：
workspace_version == current
```

---

# 十七、git_diff evidence 也要版本化

当前如果类似：

```python
git_diff_checked: bool
```

建议升级成：

```python
git_diff_checked_version: int | None
```

执行：

```text
git_diff()
```

以后记录：

```text
git_diff_checked_version = workspace_version
```

然后定义：

```text
current_diff_reviewed
=
git_diff_checked_version == workspace_version
```

这样再次 patch：

```text
workspace_version++
```

旧 diff review 自然失效。

---

# 十八、Completion Evidence 应只看 Current Version

目标概念：

```text
current workspace version = N

Completion required verification：

只接受：
VerificationEvidence.workspace_version == N
```

例如：

```text
v1
patch
tests PASS
git_diff
→ READY

v2
apply patch
→ NOT READY

v1 test PASS 不再有效

v2 tests PASS
v2 git_diff
→ READY
```

Completion evidence 必须与 Session / resume 一致。本轮允许对 Session schema 做
**最小兼容更新**，但不允许重构整个 Session architecture。

至少持久化或可安全重建：

```text
current workspace fingerprint/version
current-version 各 required command 的最新 VerificationEvidence
git_diff_checked_version
workspace hygiene state
```

Resume 时必须先通过现有 reconciliation 获取真实 workspace fingerprint：

```text
fingerprint 与 durable state 一致
→ 可以恢复 current-version completion evidence

fingerprint drift / 证据缺失 / 旧 schema
→ readiness fail-closed
→ 重新运行 required verification + git_diff
```

不得只恢复一个没有版本上下文的 `last_verification`，也不得持久化一个可直接信任的
`ready=true`。CompletionGate 状态应从 durable evidence 重算。旧 Session schema
必须有安全默认迁移，默认值不能制造 ready。

---

# 十九、增加 CompletionGate

在 evidence 版本化之后，才允许引入：

```text
CompletionGate
```

它应该是非常小、可纯测试的领域组件。

不要把 completion 判断再次散落到：

```text
AgentLoop
RuntimeToolbox
AgentGrader
CLI
```

概念接口类似：

```python
CompletionGate.evaluate(...)
```

返回类似：

```text
ready
workspace_version
missing_requirements
```

---

# 二十、CompletionGate 当前至少检查

必须基于 Runtime 客观事实：

```text
real intended Git diff exists
current-version task verification passed
current-version broad regression commands passed（只要 request 中提供）
current-version final diff reviewed
verification environment not blocked
security/execution not paused
workspace hygiene clean
```

本轮已经确定：`task_verification_commands` 与所有配置的 broad
`verification_commands` 都属于 Runtime completion-required gate。没有提供
task-specific command 时，现有 verification fallback 语义保持兼容；提供两类命令时，
两类都必须在 current workspace version 上通过。

不要改变 benchmark grader 的外部判定。

---

# 二十一、CompletionGate 不能使用 hidden oracle

严禁：

```text
hidden acceptance
```

进入 Runtime CompletionGate。

Runtime 只能看到 Agent 可见事实。

Hidden oracle 永远属于：

```text
External Grader
```

---

# 二十二、Phase B 必须测试 stale evidence

至少：

## B1

```text
patch v1
test v1 PASS
diff v1 reviewed
→ ready
```

---

## B2

```text
patch v1
tests PASS

patch v2
→ NOT READY
```

---

## B3

```text
git_diff v1
patch v2
→ current_diff_reviewed = false
```

---

## B4

```text
tests v2 PASS
git_diff v2
→ READY
```

---

## B5

验证历史：

```text
v1 evidence
v2 evidence
```

都保留，但 CompletionGate 只使用 current version。

---

## B6

同时提供 task verification 和 broad regression：

```text
task PASS + regression 未运行/失败
→ NOT READY

task PASS + regression PASS + current diff reviewed
→ READY
```

---

## B7

Session / resume：

```text
durable evidence 与 workspace fingerprint 一致
→ resume 后 CompletionGate 可从 evidence 重算

workspace drift / old schema / evidence 缺失
→ NOT READY
→ 必须重新 verification + diff review
```

---

# 二十三、Phase C：Runtime-owned Native Finalization

## Problem

当前 Native Action 已经走：

```text
Provider native tools
```

但任务结束仍然依赖：

```text
模型生成文本 / JSON final
↓
parser
↓
Runtime finalize
```

11-task 中真实出现：

```text
B01
B04
F04
R01
R02
```

共 5 次：

```text
自然语言 final
↓
protocol repair
↓
JSON final
```

说明：

```text
Action Transport 已 Native
Finalization 仍 Textual
```

---

# 二十四、增加 Native `submit_result`

在现有 Runtime ToolRegistry 中增加：

```text
submit_result
```

它不是普通副作用工具。

参数应尽量窄：

```python
summary: str
```

最多根据现有需求增加：

```python
notes: str | None
```

不要增加：

```text
tests_passed
status=completed
diff_checked
verification_passed
hidden_tests_passed
```

---

# 二十五、为什么 Model 不应该再传 tests_passed

这些已经是 Runtime 客观 evidence：

```text
VerificationEvidence
Git diff
workspace version
CompletionGate
```

所以：

```text
Model:
tests_passed = true
```

没有事实价值。

正确 ownership：

```text
Model:
“I want to submit.”

Runtime:
“I decide whether the current workspace is actually ready.”
```

---

# 二十六、submit_result 的行为

模型：

```text
submit_result(summary=...)
```

Runtime：

```text
CompletionGate.evaluate(current evidence)
```

### Ready

```text
append role=tool result with accepted=true
↓
persist state/evidence
↓
typed terminal completion signal
↓
AgentLoop stops as COMPLETED
```

### Not Ready

不要失败。

返回结构化 ToolResult，例如：

```text
accepted = false

missing_requirements:
- task_verification_required
- final_diff_review_required
```

然后 Agent 继续。

`submit_result` 的控制协议必须明确：

```text
submit_result 必须是该 assistant turn 唯一的 tool call
Runtime 不信任模型声明，只消费 summary/notes
CompletionGate 在工具执行时读取 current evidence
无论 accepted true/false，都必须追加与 provider_call_id 对应的 role=tool 消息
accepted=true 后不得执行同一 turn 的其他工具，也不得再次调用 Provider
accepted=false 时才继续下一轮
```

如果模型在同一 turn 同时提交 `submit_result` 和其他 tool calls，应返回结构化拒绝，
不得部分执行后再完成。测试必须覆盖 submit-first、submit-last 和 mixed multi-call。

当前 `halt_signal_provider` 主要服务 PAUSED 流程，不能简单传入 COMPLETED 后仍调用
pause helper。应采用最小 typed terminal signal / terminal tool outcome，使 AgentLoop 在
tool result 已写入 canonical conversation 和 durable state 后正常完成。不得让
RuntimeTools 直接抛特殊字符串异常来终止循环。

---

# 二十七、不要 Gate Ready 就自动 terminate

不要实现：

```text
tests pass
+
diff reviewed
→ immediately completed
```

原因：

模型可能还需要：

```text
发现问题
做真正新的 patch
```

推荐：

```text
gate ready
↓
Runtime 明确告知 Model completion-ready
↓
Model:
submit_result
或
apply_patch
```

如果：

```text
apply_patch
```

那么：

```text
workspace_version++
```

旧 readiness 自动失效。

---

# 二十八、Completion-ready 状态下 repeated_action 语义必须调整

当前：

```text
same semantic tool
+
same workspace version
→ REPEATED_ACTION
```

在未完成任务时应继续保留。

但是如果：

```text
CompletionGate.ready == true
```

再出现：

```text
重复 run_tests
重复 git_status
no-op patch
```

不要立刻：

```text
FAILED
```

建议第一次：

```text
不执行 duplicate expensive action
↓
追加与该 provider tool call 对应的真实 role=tool advisory result
```

例如：

```text
Current workspace already satisfies completion requirements.
Submit the result or make a real workspace change.
```

然后给模型一次 finalization opportunity。

不得只在内部跳过重复动作而留下没有 tool result 的 assistant tool call；native
provider 对话必须始终保持 assistant tool call 与 tool result 完整配对。

如果仍持续无进展，再触发 stop condition。

---

# 二十九、不要彻底删除 Repeated Action

这是非常重要的 Runtime safety 机制。

禁止：

```text
关闭 repeated_action
把 threshold 调到很大
所有重复动作都允许
```

只针对：

```text
completion-ready
```

增加 finalization-aware behavior。

---

# 三十、Textual Final 继续作为 Fallback

不要删除现有：

```text
AgentFinalOutput
JSON final
fenced JSON
DSML
protocol repair
```

目标：

```text
Native provider:
submit_result
    ↓ primary

Non-native / legacy provider:
textual final
    ↓ fallback
```

所以 current tests 也要继续覆盖 legacy final path。

---

# 三十一、Runtime Completion 不能依赖 Grader

严禁：

```text
if hidden acceptance passes:
    actor success
```

或者：

```text
grader rescue actor failure
```

正确边界：

```text
Runtime
负责自身 completion correctness

External Grader
负责独立评价真实 task correctness
```

---

# 三十二、P1：顺手补 Evaluation Observability

这部分必须控制范围。

不是新增大型 observability system。

只是让下一次用户执行 11-task 时，不必再次人工翻 11 个 artifact。

建议 summary 增加：

```text
actor_completed_count
within_budget_count
```

以及 failure histogram：

```text
failure_category_counts
```

至少区分：

```text
repeated_action
max_steps
protocol_failure
environment_failure
task_verification_failure
acceptance_failure
budget
```

具体名称遵循现有 model。

---

# 三十三、Completion 指标

建议新增：

```text
completion_ready_count
completion_ready_but_actor_failed_count
post_ready_tool_call_count
```

若当前架构便于实现，再增加：

```text
completion_ready_step
finalization_step
post_ready_input_tokens
```

不要为了这几个 metric 侵入大量 AgentLoop 代码。

优先可维护性。

---

# 三十四、Workspace Hygiene 指标

建议新增：

```text
verification_workspace_mutation_count
```

这样用户下次运行 11-task 可以直接确认：

```text
pytest scratch pollution
```

是否归零。

---

# 三十五、R02 本次不要修模型业务答案

当前 R02 hidden failure 属于真正 semantic miss：

```text
retry executor
遇到 transient exception
应该继续 retry
```

本次不要：

```text
改 hidden oracle
修改 task prompt
把 transient RuntimeError 写入 system prompt
硬编码 retry exception 规则
```

这些会污染 Benchmark。

Completion Runtime 修完后再单独分析：

```text
Agent semantic review
```

是否值得改进。

---

# 三十六、本次禁止修改的其他模块

除非真实代码兼容要求，不要修改：

```text
Context Engine
RepositoryScanner
SymbolIndex
ImportGraph
FileRanker
RepoMap
Planner
Multi-Agent
Scheduler
Mailbox
Session broad architecture（仅允许 Phase B 所需的最小 schema/migration 更新）
Git worktree architecture
Provider Adapter 核心 native tools protocol
```

当前 11-task 没有证据支持这些是主要 blocker。

---

# 三十七、测试策略

本次 coder 只运行：

```text
Unit Tests
Integration Tests
Deterministic Fake Model tests
Docker Sandbox integration tests
```

不运行真实 LLM Eval。

Phase C 的 deterministic tests 还必须覆盖：

```text
submit_result accepted 后 role=tool 配对并 terminal completed
submit_result rejected 后返回 missing requirements 并继续
submit_result 与其他 call 混在同一 turn 时 fail-closed
accepted 后 Provider 不再被调用
completion-ready duplicate 返回 advisory tool result，而不是立即 repeated_action
not-ready duplicate 仍保持原 protection
legacy textual final fallback
Session resume 后 completion evidence 重算
```

---

# 三十八、强制测试命令

先运行触达范围测试：

```bash
.venv/bin/python -m pytest tests/sandbox tests/execution tests/git tests/agent tests/session tests/evaluation tests/cli -q
```

然后必须运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check <本轮触达路径>
.venv/bin/python -m mypy --follow-imports=skip <本轮触达路径>
git diff --check
```

`<本轮触达路径>` 必须替换成真实文件或目录，不能原样执行。全量 pytest 不是可选项；
如果无法完成，最终状态必须如实标记为 blocked/partial。

Docker daemon 可用时，额外运行：

```bash
.venv/bin/python -m pytest tests/sandbox -q -rs
```

必须报告真实 passed/skipped 数量和 skip 原因，不得把 conditional skip 当成真实 Docker
边界通过。上述命令不调用真实 LLM，不属于 B01 或 benchmark。

所有项目测试使用：

```text
.venv/bin/python
```

---

# 三十九、禁止 coder 运行以下命令

不要执行任何：

```text
.venv/bin/python -m codeteam.cli.app agent-eval
```

包括：

```text
B01
B02
B03
F01
F03
R03
11-task
```

都不要运行。

这些真实 LLM 任务由用户本人运行。

---

# 四十、不要执行 Benchmark / Ablation

本次任何 Design Decision 中可以引用明确标注的 pre-fix 5/11 诊断基线，但对于
post-fix：

```text
Benchmark
Ablation
```

只能写：

```text
Post-fix B01: pending user-run validation.
Post-fix 11-task benchmark: NOT_RUN.
Post-fix ablation: NOT_RUN.
```

不得填写 success rate、token savings、latency 等数字。

---

# 四十一、实施阶段与提交边界

本轮按三个逻辑阶段实施，但 Coder **不得执行 `git commit`**。用户会在检查后亲自
提交。Coder 必须保持每个阶段的改动边界清楚，并在最终报告给出 commit-ready 分组和
建议 commit message。

## Phase A

```text
fix(sandbox): isolate verification scratch from source workspace
```

内容：

```text
tmpfs /tmp
TMPDIR
workspace hygiene detection
sandbox regression tests
```

---

## Phase B

```text
fix(runtime): version completion evidence by workspace state
```

内容：

```text
VerificationEvidence.workspace_version
git_diff_checked_version
CompletionGate
stale evidence tests
```

---

## Phase C

```text
fix(runtime): make finalization runtime-owned via submit_result
```

内容：

```text
native submit_result
completion-ready advisory
repeated-action awareness
legacy final fallback
eval observability
```

如果真实代码依赖关系决定必须合并 B/C 的文件修改，可以说明原因。

但不要把 A 与 B/C 无理由揉成一个巨大修改集合，也不得 stage、commit、push 或
操作用户已有的实验文件删除。

---

# 四十二、Design Decision

至少更新/新增两个 DD。

## DD 1 — Verification Scratch Isolation

至少包含：

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

核心 invariant：

> Verification runtime temporary files must not become source-workspace changes.

Alternatives 至少比较：

```text
自动删除 pytest-of-root
放宽 checkpoint symlink
writable host /tmp
Docker tmpfs scratch
```

Decision 应选择真正的 scratch isolation。

---

## DD 2 — Runtime-owned Versioned Completion

核心 Problem：

```text
The model controlled task termination even when Runtime evidence already proved completion.
```

同时记录：

```text
completion evidence was not workspace-version scoped
```

核心 Decision：

```text
Completion evidence is versioned.
Model requests completion.
Runtime authorizes completion.
```

除对应 DD 外，必须同步维护：

```text
README.md
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
```

其中必须记录：

```text
readonly verification workspace + bounded scratch
workspace fingerprint/version lifecycle
Session resume 的 evidence reconciliation
CompletionGate required commands
submit_result terminal protocol
pre-fix 5/11 与 post-fix NOT_RUN 的证据边界
```

---

# 四十三、Failure Case

必须至少更新两个 Failure Case。

## Failure Case A — F03

记录：

```text
verification
↓
pytest temp artifact in source workspace
↓
symlink
↓
checkpoint fail-closed
↓
future patch impossible
↓
step exhaustion
```

Root Cause：

> Verification scratch and source workspace were not isolated.

不要怪 CheckpointManager。

---

## Failure Case B — B02/F01/R03

记录：

```text
correct patch
↓
verification pass
↓
diff reviewed
↓
workspace objectively complete
↓
model keeps acting
↓
repeated action
↓
actor false failure
```

Root Cause：

> Completion ownership remained model-driven after objective completion evidence was already available.

---

# 四十四、修改完成后的汇报格式

完成后严格按以下结构回答。

## 1. Root Cause Confirmation

分别确认：

```text
Sandbox pollution
Stale completion evidence
Model-owned finalization
Protocol repair tail
```

当前真实代码是否和本提示词一致。

---

## 2. Files Changed

逐文件：

```text
path
what changed
why
```

新增文件必须回答：

> 为什么不能复用已有模块？

---

## 3. Sandbox Lifecycle

画出：

```text
Docker
├── /workspace → source repo
└── /tmp       → ephemeral scratch
```

说明 test temp data 如何隔离。

---

## 4. Completion Lifecycle

画出：

```text
patch
↓
workspace_version=N
↓
verification(N)
↓
git_diff(N)
↓
CompletionGate READY
↓
submit_result
↓
Runtime COMPLETED
```

---

## 5. Stale Evidence Invariant

明确说明：

```text
v1 PASS
+
v2 patch
```

为什么不可能错误满足 v2 CompletionGate。

---

## 6. Repeated Action Behavior

说明：

```text
NOT READY
```

与：

```text
READY
```

下重复工具调用的不同处理。

---

## 7. Compatibility

说明是否影响：

```text
Native Tool Calling
Textual final fallback
CLI run
Agent Eval
SafeExecutionService
CheckpointManager
Session
Grader
```

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

## 9. B01

必须明确：

```text
B01 was NOT executed by the coder.
It is pending user validation.
```

同时输出但不要执行：

```bash
RUN_DIR="evals/week4/agent_runs/completion_gate_b01_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output "$RUN_DIR" \
  --actor llm \
  --mode baseline \
  --task-id B01 \
  --context-budget 8192 \
  --max-output-tokens 4096 \
  --model-context-window 32768 \
  --safety-headroom-tokens 1024 \
  --native-tools \
  --no-reasoning \
  --worktree-root "$HOME/.codeteam/worktrees" \
  --keep-workspaces
```

---

## 10. 11-task

必须明确：

```text
The 11-task LLM evaluation was NOT executed by the coder.
It is pending user validation.
```

同时输出但不要执行：

```bash
RUN_DIR="evals/week4/agent_runs/completion_gate_11task_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output "$RUN_DIR" \
  --actor llm \
  --mode baseline \
  --context-budget 8192 \
  --max-output-tokens 4096 \
  --model-context-window 32768 \
  --safety-headroom-tokens 1024 \
  --native-tools \
  --no-reasoning \
  --worktree-root "$HOME/.codeteam/worktrees" \
  --keep-workspaces
```

两条命令都必须先通过当前 CLI help/参数定义核对。不得读取、打印或持久化用户
API key；只提示用户在自己的终端加载 ignored `secrets.local.env`。

---

## 11. Benchmark

必须明确：

```text
Historical pre-fix 11-task evidence: 5/11 at the recorded run.
Post-fix benchmark was NOT executed by the coder.
Post-fix ablation was NOT executed.
```

---

## 12. Design Decisions

列出新增/修改 DD 路径。

---

## 13. Failure Cases

列出新增/更新 Failure Case 路径。

---

## 14. Remaining Issues

至少明确：

```text
R02 semantic retry failure remains unresolved.
```

以及当前代码中发现的其他真实 limitation。

不要声称 SingleAgent 已经完全没有问题。

---

# 四十五、最终验收标准

只有同时满足下列条件，任务才算完成：

```text
[ ] Verification scratch 不再写入 Git source workspace

[ ] run_tests 默认 readonly 挂载 source workspace，Patch Lane 仍由 SafeExecutionService 控制写入

[ ] Docker 有独立 bounded writable scratch

[ ] TMPDIR/TMP/TEMP/HOME/XDG_CACHE_HOME/PYTHONPYCACHEPREFIX 指向 scratch

[ ] pytest tmp_path 不再产生 workspace pytest-of-root

[ ] pytest cache/bytecode 不再污染 source workspace

[ ] Checkpoint symlink fail-closed 仍然保持

[ ] Verification 后仍可正常 checkpoint + patch

[ ] Verification workspace mutation 可被 Runtime 检测

[ ] workspace fingerprint 对同路径内容变化敏感，且不跟随 symlink target

[ ] VerificationEvidence 绑定 workspace_version

[ ] Git diff review 绑定 workspace_version

[ ] v1 verification 不能满足 v2 completion

[ ] current-version task verification 与配置的 broad regression 都是 completion-required

[ ] Session/resume 能重算 completion evidence；drift/旧 schema 默认 NOT READY

[ ] CompletionGate 是 Runtime-owned

[ ] Native submit_result 已实现

[ ] submit_result 是 sole-call terminal protocol，accepted/rejected 都有完整 role=tool 配对

[ ] accepted submit_result 后不再执行其他 tool 或调用 Provider

[ ] 模型不能自行声明 tests_passed 作为事实来源

[ ] completion-ready 后重复动作不会立即 false-fail

[ ] 未完成状态下 repeated-action protection 仍保留

[ ] Native provider 不再依赖 textual JSON final 作为正常 happy path

[ ] legacy textual final fallback 仍然可用

[ ] Hidden oracle 未进入 Runtime completion logic

[ ] Grader 未被用于 rescue actor failure

[ ] Eval summary 增加必要 control-plane metrics

[ ] 触达测试、全量 pytest、触达范围 Ruff/Mypy 和 git diff --check 真实通过

[ ] README、单Agent执行闭环修复记录、代码架构、设计决策和对应 DD 已更新

[ ] Failure Case 已更新

[ ] coder 没有执行 B01

[ ] coder 没有执行 11-task

[ ] coder 没有执行 benchmark / ablation

[ ] coder 没有 stage/commit/push，也没有恢复用户确认保留的实验文件删除

[ ] R02 没有被 benchmark leakage 式硬编码修复
```

---

# 四十六、核心架构原则

本轮修改始终坚持三个原则：

## 1.

```text
Verification temporary state
!=
Source workspace state
```

---

## 2.

```text
Completion evidence
必须属于
当前 workspace version
```

---

## 3.

```text
Model requests completion
Runtime authorizes completion
```

最终目标是：

```text
LLM
负责：
reasoning
tool intent
coding decisions
completion request

Runtime
负责：
workspace truth
verification truth
completion truth
safety boundary
```

这次修改的目标不是让模型“更聪明”，而是让 Runtime 不再把：

```text
正确完成的 coding work
```

因为自己的控制流和执行环境问题判成失败。

B01 与 11-task 的真实验证全部由用户在 coder 修改完成后亲自执行。
