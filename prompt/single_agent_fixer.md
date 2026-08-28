# CodeTeam Week4 SingleAgent 第一刀修复：ModelRequest → ModelTurn + Native Tool Calling

## 角色

你现在是 **CodeTeam / Coding Agent Runtime 的代码修改工程师**。

你不是来重新设计整个 SingleAgent，也不是来做大范围架构重构。

本次任务只有一个核心目标：

> **修复 Week4 SingleAgent 当前仍然基于“文本补全协议”传输 Agent Action 的根本问题，将 Model Client 升级为真正支持 Agent Turn 的 Provider-neutral contract，并让生产路径优先使用 native tool calling。**

本次属于 **SingleAgent 执行闭环第一刀修复**。

必须基于当前 `week4` 分支真实代码修改，不得根据下面描述直接假设代码结构完全一致。

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

首先阅读：

```text
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
README.md
```

重点检查：

```text
codeteam/llm/
codeteam/agent/
codeteam/agent_loop.py
codeteam/cli/agent_eval_command.py
codeteam/evaluation/
codeteam/execution/
codeteam/agent/verification.py
codeteam/git/
tests/
```

特别关注当前真实：

```text
ModelClient
ModelResponse
OpenAI-compatible provider adapter
CodingAgentRuntime
ToolRegistry
ToolCall / ToolResult
SafeExecutionService
runtime tool wiring
agent-eval provider wiring
```

---

# 二、问题背景

当前 Week4 已经完成一个非常重要的架构修复：

```text
                 CodingAgentRuntime
                       │
             ┌─────────┴─────────┐
             ↓                   ↓
          CLI run            Agent Eval
```

CLI 和 Evaluation 已经开始共享同一个 Coding Runtime。

同时 Agent side-effect 已经基本统一进入：

```text
apply_patch
    ↓
SafeExecutionService.execute_patch()

run_tests
    ↓
SafeExecutionService.execute_command()
```

这些设计必须保留。

---

# 三、当前真实问题

最近 SingleAgent 实际运行已经证明：

模型能够：

```text
理解任务
找到正确文件
理解正确修复语义
产生接近正确的 patch/action
```

但是 Action 经常在真正进入 Runtime Tool Layer 前失败。

当前 Model Client 仍然类似：

```python
complete(messages) -> str | ModelResponse
```

`ModelResponse` 主要还是：

```text
content
model
input_tokens
output_tokens
```

而 Provider-native 信息没有被完整保留。

当前 Runtime 本质上仍依赖：

```text
LLM
 ↓
生成 JSON / DSML / fenced JSON 文本
 ↓
字符串 parser
 ↓
恢复 ToolCall
```

导致：

```text
模型原本具有结构化 tool-call 能力
        ↓
被降级为自由文本生成
        ↓
JSON 被截断 / envelope 不完整
        ↓
Protocol failure
        ↓
patch 根本没有进入 SafeExecutionService
```

因此：

> **当前主要 blocker 不是 JSON parser 不够强，而是 Model Client 的抽象仍然是 Text Completion，而不是 Agent Turn。**

---

# 四、本次核心设计目标

将当前：

```text
messages
   ↓
ModelClient.complete()
   ↓
string / ModelResponse
   ↓
text parser
   ↓
ToolCall
```

升级为：

```text
ModelRequest
    │
    ├── messages
    ├── tools
    ├── max_output_tokens
    └── provider-neutral options
          ↓
      ModelClient
          ↓
      Provider Adapter
          ↓
        ModelTurn
    ┌─────┼──────────┐
    ↓     ↓          ↓
 actions  text      finish
                  + usage
```

核心目标是：

```text
Provider native tool call
        ↓
Provider-neutral ModelTurn
        ↓
Runtime ToolCall
        ↓
ToolRegistry / Runtime Tool
        ↓
SafeExecutionService
```

不能再让 production happy path 依赖：

```text
模型生成完整 JSON 字符串
```

---

# 五、重要限制

## 1. 本次不要重写 SingleAgent

禁止：

```text
重写 CodingAgentRuntime
重新实现 AgentLoop
重新实现 ToolRegistry
重新实现 SafeExecutionService
重新实现 Evaluation
重新实现 GitWorkspace
重新实现 Session
```

优先复用当前已有能力。

---

## 2. 本次不要解决 Completion Ownership

当前还有另一个独立问题：

```text
模型必须主动输出 completed
↓
Loop 才结束
↓
Runtime completion gate 才检查客观证据
```

这会导致：

```text
patch 正确
tests pass
diff reviewed
↓
模型又重复 run_tests
↓
REPEATED_ACTION
↓
任务失败
```

这是 **第二刀**。

本次不得借机大规模修改：

```text
completion state machine
READY_TO_FINALIZE
submit_result semantics
repeated-action completion handshake
```

除非为了兼容新的 `ModelTurn` 必须做最小接口适配。

不要把两个 P0 混成一个超大 PR。

---

## 3. 不要删除现有 JSON / DSML fallback

当前已有类似：

```text
JSON
fenced JSON
DSML
protocol repair
```

这些能力不要删除。

它们应该从：

```text
production primary transport
```

降级为：

```text
fallback / compatibility codec
```

设计目标：

```text
native tool calling
    ↓ 优先

fallback textual action codec
    ↓ provider 不支持 native tools 时使用
```

---

# 六、第一步：先审查真实代码

正式修改前，先输出：

```text
涉及文件
当前 ModelClient contract
当前 provider request payload
当前 provider response parsing
当前 ToolCall 是如何从模型响应进入 Runtime 的
当前 ToolResult 是如何回传模型的
当前 fallback codec 的位置
```

然后判断本提示词中的问题是否和当前代码一致。

如果真实代码已经部分修改，必须基于最新实现继续，而不是重复实现。

---

# 七、Model Request Contract

不要只修改 `ModelResponse`。

当前根本问题同时存在于：

```text
Request under-modeled
Response under-modeled
```

建议引入 Provider-neutral：

```python
ModelRequest
```

至少能够表达：

```text
messages
tools
max_output_tokens
```

根据当前代码风格决定是否还需要：

```text
temperature
response_mode
provider options
```

但不要为了未来可能需求一次加十几个字段。

核心原则：

> 新 abstraction 必须购买当前真实能力。

`ModelRequest` 当前至少购买：

```text
native tool transport
output budget
provider capability adaptation
```

---

# 八、ModelTurn Contract

建议引入类似：

```python
ModelTurn
```

它不应只是改名后的 `ModelResponse`。

至少需要表达：

```text
text
actions/tool_calls
finish state
usage
model/provider evidence
```

根据现有 schema 复用：

```text
ToolCall
Usage
Message
```

不要重新定义第二套 ToolCall。

例如概念上：

```python
class ModelTurn:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: ...
    usage: ...
```

具体字段、enum 和 Pydantic/dataclass 风格必须遵循仓库现有约定。

`ModelTurn` 还必须能够为审计层保留 Provider evidence，但不得把
Provider-specific response shape 泄漏到 Runtime：

```text
response_id
finish_reason
actual response mode
input/output usage
incomplete reason
system fingerprint（Provider 提供时）
```

原始 Provider envelope 只能进入脱敏审计 artifact，不得直接成为
AgentLoop 的控制输入。现有 `ModelOutputEvidence.raw_content: str` 无法完整表达
`content=None + native tool_calls`，必须按当前仓库风格升级 evidence contract。

---

# 九、Finish State 必须保留

目前 Provider 常见返回：

```text
stop
tool_calls
length
content_filter
...
```

当前代码如果只保留 `message.content`，就会失去关键诊断信息。

至少需要能够区分：

```text
normal final text
native tool calls
output truncated
abnormal/incomplete provider turn
```

不要让：

```text
finish_reason=length
```

最后被错误包装成：

```text
JSON parse failure
```

这两种 failure 属于不同层。

必须明确分类策略：

```text
finish_reason=tool_calls
→ 正常 native action turn

finish_reason=stop
→ final/text fallback path

finish_reason=length
→ OUTPUT_TRUNCATED；不得先进入 JSON parser

finish_reason=insufficient_system_resource
→ retryable provider failure

finish_reason=content_filter
→ non-retryable provider failure

content empty + tool_calls empty
→ bounded transient provider retry
```

`length` 不得在 request 完全不变时盲目重试。只有扩大输出预算或压缩输入后
才允许重试，否则直接返回 typed failure。

---

# 十、Native Tool Calling

如果当前主要 Provider 是 DeepSeek / OpenAI-compatible API，则优先利用其 native tools。

Provider request 应把 Runtime 当前可调用工具转换成 Provider tool schema。

不要新造另一套工具定义。

优先从已有：

```text
ToolRegistry
ToolDefinition
Tool schema
Pydantic args model
```

生成 Provider-facing JSON Schema。

链路目标：

```text
Runtime Tool Registry
       ↓
Provider tool schema
       ↓
LLM native tool_call
       ↓
Provider Adapter normalize
       ↓
CodeTeam ToolCall
       ↓
现有 ToolRegistry / Runtime Tool execution
```

### Native Call ID 必须使用双 ID

Provider 原始 call ID 和 Runtime call ID 属于不同信任域，不得混为一个字段：

```text
provider_call_id
    Provider Adapter 持有的 opaque correlation ID
    只用于下一轮 Provider tool message round-trip

runtime_call_id
    Runtime 在 schema validation 后生成
    用于 ToolRegistry、ToolResult、事件、审计和重复动作判断
```

Provider Adapter 必须保存二者映射。Provider 原始 ID 需要原样回传给 Provider，
但 ToolRegistry 和 SafeExecutionService 不得把 Provider ID 当作内部可信 ID。

优先在现有 `ToolCall` / `Message` contract 上做最小扩展，例如增加明确的
opaque transport correlation 字段；不得复制第二套业务 ToolCall schema。

---

# 十一、Tool Result 回传必须使用真实 Tool Message

当前代码如果存在类似：

```text
tool result
↓
重新包装成 role=user 的 JSON 文本
```

需要修正 native path。

native tool calling 情况下应该保持：

```text
assistant
    tool_calls=[...]

tool
    tool_call_id=<provider-facing correlation after adapter mapping>
    content=...
```

然后再进入下一轮模型请求。

必须保存正确：

```text
runtime_call_id
provider_call_id / transport correlation
```

不能只保存工具名，也不能用 Provider ID 替代 Runtime-owned ID。

目标：

```text
Assistant ToolCall
      ↓
Runtime execute
      ↓
ToolResult
      ↓
role=tool observation
      ↓
next ModelRequest
```

Fallback textual codec 可以继续沿用旧的文本 observation 机制，但 native path 不要再降级成 user message。

Native assistant turn、tool result 和双 ID 映射必须进入 durable message history，
使 Session resume 后仍能构造合法的下一次 Provider request。

---

# 十二、Empty Content 处理

不要实现：

```python
if not response.content:
    retry()
```

因为 native tool calling 下：

```text
content = None
tool_calls != empty
```

是完全正常的 Provider Turn。

正确语义应该类似：

```text
content empty
AND
tool_calls empty
AND
没有合法 final/control action
→ incomplete / abnormal provider turn
```

而：

```text
content empty
AND
tool_calls present
→ 正常 Agent Turn
```

必须写测试锁定这一点。

---

# 十三、Output Budget

当前真实 B01 failure 有明显：

```text
action envelope 被截断
```

风险。

因此 `ModelRequest` 应显式支持：

```text
max_output_tokens
```

并由 Provider Adapter 真正映射到 HTTP request。

不要硬编码一个神秘数字。

优先：

```text
runtime config
或
provider config
```

提供合理默认值。

同时：

```text
finish_reason=length
```

必须保留下来用于错误分类和 observability。

还必须修复输入和输出预算之间的关系。当前真实运行已经出现：

```text
context_budget=4096
provider input_tokens=4419 / 4896
```

至少建立以下硬约束：

```text
max_input_tokens
<= model_context_window - max_output_tokens - safety_headroom
```

如果 `context_budget` 定义为输入预算，Provider request 前必须验证实际估算输入
不超过该预算；如果定义为总预算，必须在 schema 中重新命名并明确分账。
不得继续只用 `字符数 / 4` 且永久保留完整前两个消息来声称预算已满足。

---

# 十四、DeepSeek 第一阶段要求

如果当前 DeepSeek Provider 开启 thinking mode：

本次 native-tool smoke 优先采用：

```text
native tools
+
thinking explicitly disabled
```

先证明基础链路：

```text
ModelRequest
↓
native tool_call
↓
Runtime ToolCall
↓
ToolRegistry
↓
SafeExecutionService
↓
ToolResult
↓
第二轮 ModelRequest
```

本次不要顺手实现完整：

```text
reasoning_content continuation
thinking state persistence
resume reasoning chain
```

这些属于后续 Provider Continuation 能力。

避免第一刀范围失控。

---

# 十五、Provider Adapter

Provider-specific 逻辑必须停留在 Provider Adapter。

例如：

```text
OpenAI / DeepSeek response
        ↓
Provider Adapter
        ↓
ModelTurn
```

`CodingAgentRuntime` 不应该出现：

```python
if provider == "deepseek":
```

或者直接处理：

```text
choices[0].message.tool_calls
finish_reason
reasoning_content
```

Runtime 只应该理解：

```text
ModelRequest
ModelTurn
ToolCall
```

当前真实代码中 `codeteam/cli/run_command.py` 反向导入
`codeteam/cli/agent_eval_command.py` 的 Provider client factory。这个依赖方向需要在
本轮纠正：

```text
CLI
  ↓ 读取配置并组装
codeteam/llm/openai_compatible.py
或 codeteam/llm/providers/
  ↓
ModelRequest / ModelTurn
```

HTTP payload、native response parsing、capability negotiation 和 retry metadata
必须位于 LLM/Provider adapter 层。`run_command.py` 和 `agent_eval_command.py`
不得互相充当 Provider 实现模块。

---

# 十六、Agent Loop 修改原则

当前 AgentLoop 如果大体类似：

```text
model.complete(messages)
↓
parse text
↓
tool_calls or final_output
```

需要最小升级为：

```text
ModelRequest
↓
ModelTurn
↓
if native tool_calls:
    execute tools
elif textual fallback action:
    fallback parser
elif final:
    existing final path
else:
    protocol/incomplete handling
```

不要重写 loop 的：

```text
step budget
tool budget
repeated-action detection
usage accounting
stop reason
```

本次只修改“模型 turn 如何进入 Loop”。

### Durable history 与 compaction 最小兼容要求

这不是重写 Session，但属于新 `ModelTurn` 能否生产可用的必要条件：

- assistant native tool calls 必须作为结构化 Message 被持久化；
- tool result 必须保留对应的 transport correlation；
- resume 后必须能恢复 assistant call → tool result → next request；
- compaction 不得拆散一个 assistant tool-call turn 与其对应的 tool results；
- compaction 后不得遗失 Provider round-trip 所需 ID；
- raw Provider evidence 不得进入 compacted model conversation。

必须增加 Session/resume 与 compaction regression tests，证明 native path 不只在
单进程 Fake Provider 中成立。

---

# 十七、Fallback 优先级

建议明确：

```text
1. Native structured tool_calls
2. Provider/native structured final if supported
3. Existing textual JSON / fenced JSON / DSML codec
4. Protocol repair
5. fail closed
```

Native Tool Call 存在时，不要同时再拿 `content` 里的文本尝试解析另一组 action。

避免一次 Model Turn 被执行两遍。

---

# 十八、Safe Execution 不得被绕过

本次修复只改变：

```text
模型 action transport
```

不得改变：

```text
action execution boundary
```

也就是说 native：

```text
apply_patch
run_tests
...
```

仍必须走当前已有：

```text
Runtime Tool
↓
SafeExecutionService
↓
Git / CommandPolicy / Approval / Sandbox
```

禁止 native tool calling 直接：

```text
subprocess
GitWorkspace.apply_patch()
filesystem write
```

否则属于严重回归。

---

# 十九、兼容性

必须尽量保持：

```text
现有 Mock/Fake ModelClient tests
fallback textual model
existing ToolCall schema
existing Runtime ToolRegistry
existing EvalRunner
existing CLI run
```

如果 Protocol 必须破坏性修改：

先分析是否能通过 adapter compatibility layer 解决。

不要为了接口漂亮一次修改全仓库所有 fake。

---

# 二十、核心测试

核心修改至少覆盖以下情况。

## A. Native Tool Call happy path

构造 Fake Provider 返回：

```text
content=None
tool_calls=[
    apply_patch(...)
]
finish_reason=tool_calls
```

验证：

```text
ModelTurn 正确
Runtime ToolCall 正确
tool 执行一次
SafeExecution path 被调用
```

---

## B. Tool result round-trip

验证：

```text
assistant tool_call
↓
tool executes
↓
tool message
```

下一次 Provider request 中存在：

```text
role=tool
tool_call_id=<provider_call_id expected by Provider>
```

同时 Runtime 内部必须继续使用独立的 `runtime_call_id`。测试需要断言：

```text
Provider request round-trip 使用 provider_call_id
ToolRegistry / events / ToolResult 使用 runtime_call_id
二者映射稳定且不会交叉信任
```

而不是：

```text
role=user
```

---

## C. Empty content + tool call

输入：

```text
content=None
tool_calls!=empty
```

必须：

```text
正常执行
```

不得 retry。

---

## D. Empty content + no tool call

输入：

```text
content=None
tool_calls=[]
```

应分类为：

```text
incomplete provider turn
```

按照当前 retry/recovery 体系处理。

不得直接变成 JSON parse error。

---

## E. Finish reason = length

验证：

```text
finish_reason=length
```

能够被 Runtime / failure layer识别。

不得先进入：

```text
malformed action JSON
```

---

## F. Malformed native tool arguments

例如：

```text
tool=apply_patch
arguments={invalid}
```

必须：

```text
结构化 validation failure
```

不能执行 backend。

---

## G. Unknown tool

Provider 返回不存在的工具。

必须：

```text
ToolRegistry reject
backend invocation = 0
```

---

## H. Duplicate/native + textual action

如果同时：

```text
native tool_calls
+
content 中又出现 action JSON
```

只能执行 native action 一次。

---

## I. Fallback regression

现有：

```text
raw JSON
fenced JSON
DSML
```

至少保留关键 regression test。

不能因为 native path 接入把 fallback 全部破坏。

---

## J. SafeExecution regression

native `apply_patch` 最终必须进入已有：

```text
SafeExecutionService.execute_patch()
```

native command/test 必须进入：

```text
SafeExecutionService.execute_command()
```

增加 spy/fake 断言。

---

## K. Usage / finish evidence

确认：

```text
input tokens
output tokens
model
finish reason
```

没有因为新 ModelTurn 丢失。

---

## L. Durable resume

构造在 native tool result 已持久化后暂停的 Session，恢复后验证：

```text
assistant native tool call 仍存在
provider/runtime call ID 映射仍存在
tool result 仍为 role=tool
下一轮 Provider request 合法
usage 和 step/tool budget 不重置
```

---

## M. Compaction atomicity

验证 compaction 不会留下孤立的 tool result，也不会丢失它对应的 assistant
tool call。native turn group 必须整体保留、整体摘要或按 Provider 可接受的方式转换。

---

## N. Input/output budget

验证：

```text
max_output_tokens 确实进入 Provider payload
输入估算不超过 max_input_tokens
为输出和 safety headroom 保留预算
finish_reason=length 不执行任何 Tool backend
```

---

# 二十一、建议增加 Integration Test

至少增加一个不依赖真实网络的完整 Fake Provider integration：

```text
Turn 1
    assistant native apply_patch

        ↓

Runtime
    execute patch

        ↓

Turn 2
    assistant native run_tests

        ↓

Runtime
    safe command execution

        ↓

Turn 3
    existing final-output path
```

本次不要求解决 Completion Ownership。

只要求证明：

```text
native structured actions
```

能够真正完成：

```text
model
→ action
→ runtime
→ tool
→ observation
→ model
```

闭环。

---

# 二十二、B01 真实 Provider Smoke 由用户亲自执行

本轮 Coder **不得调用真实 LLM/API，也不得实际执行 B01 smoke**。

Coder 的职责仅限于：

1. 完成生产代码和离线 Fake Provider 测试；
2. 确认所有本地回归与静态检查通过；
3. 给出一条可以由用户在本机终端执行的准确 B01 命令；
4. 说明命令需要的环境变量，但不得读取、打印或持久化 API key；
5. 列出用户执行后需要检查的 manifest、results 和 artifacts 字段；
6. 将真实 smoke 状态记录为 `NOT_RUN_BY_CODER`。

用户后续会亲自在终端执行 B01。建议命令应明确包含：

```text
task-id=B01
thinking disabled
native tool calling enabled
明确 max_output_tokens
Docker 可见 worktree-root
独立 output 目录
keep-workspaces
```

用户运行后的验收重点是：

```text
是否收到 native tool_call
Provider finish_reason 是否被保留
provider_call_id 与 runtime_call_id 是否正确映射
是否进入现有 SafeExecutionService
是否成功 apply_patch
tool result 是否以真实 role=tool 回传
是否继续下一轮 ModelRequest
是否仍出现 textual protocol parse failure
```

本轮报告中不得出现伪造的 B01 成功或失败结果。只能报告：

```text
B01 real-provider smoke: NOT_RUN_BY_CODER
```

用户提供真实输出后，才能更新结果和持续修复记录。

---

# 二十三、本次不执行 Benchmark

本次修改 **禁止执行 11-task benchmark**，也不执行任何真实 LLM 批量评测。

原因：第一刀只验证 action transport contract。Completion Ownership、硬预算和
真实 Provider 稳定性还需要用户 B01 smoke 提供下一轮证据。此时运行 11 题仍可能
把协议或完成状态机问题错误解释为 Agent 任务能力。

Coder 只需要保留或补充离线 benchmark harness regression tests，证明：

```text
CLI run 与 agent-eval 仍共享 CodingAgentRuntime
EvalRunner 能接收新的 ModelRequest / ModelTurn client
hidden acceptance 不进入 Runtime conversation
native action 仍经过相同 Runtime 和 SafeExecution 边界
existing null/fake evaluation semantics 未回归
```

本轮所有真实 benchmark 指标必须标记为：

```text
11-task benchmark: NOT_RUN
Native Tool Transport Success Rate: NOT_RUN
Protocol Parse Failure Rate: NOT_RUN
Provider Incomplete Turn Rate: NOT_RUN
ToolCall → Runtime Execution Rate: NOT_RUN
```

不得用 Fake Provider 单元测试通过率替代真实 benchmark 分数。

---

# 二十四、Ablation

暂时设计：

```text
A. Native tool calling
B. Existing textual JSON codec
```

相同：

```text
task
model
temperature
output budget
```

比较：

```text
action transport success
parse failure
tool execution reached
task completion
```

本次没有真实运行就标记：

```text
NOT_RUN
```

本轮同样禁止执行真实 ablation。只有用户 B01 smoke 稳定、Completion Ownership
修复完成且 baseline 可重复后，才允许比较 native tool calling 与 textual fallback。

---

# 二十五、Design Decision

完成后新增或更新 Design Decision。

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

核心 Decision 应表达：

> CodeTeam 将 Model Client 从 Text Completion abstraction 升级为 Agent Turn abstraction。Provider-native tool calls 由 adapter 归一化成 provider-neutral ModelTurn，Runtime 不感知 DeepSeek/OpenAI 等供应商协议。

Alternatives 至少讨论：

```text
继续增强 JSON parser
只增加 max_tokens
Provider-specific Runtime
ModelRequest → ModelTurn
```

---

# 二十六、Failure Case

把当前真实 Failure Case 保留下来：

```text
模型已经理解正确修改
↓
action JSON envelope 被截断
↓
parser 无法恢复完整 patch
↓
SafeExecutionService 从未收到 patch
↓
任务失败
```

Root Cause 不要写成：

```text
LLM 不会写 patch
```

而应该写：

```text
Agent action transport was incorrectly modeled as free-form text generation.
```

同时记录本次修复如何改变 failure boundary：

```text
Before:
LLM → text JSON → parser → ToolCall

After:
LLM native tool_call → Provider Adapter → ModelTurn → ToolCall
```

---

# 二十七、不要做的事情

本次明确禁止：

```text
× 重写 CodingAgentRuntime

× 删除 SafeExecutionService

× 绕过 ToolRegistry

× 新建第二套 ToolCall

× 重写 Session

× 重写 EvalRunner

× 修改 Multi-Agent

× 修 Worker/Scheduler

× 重构整个 CLI package

× 删除现有 textual fallback

× 为了解决 JSON 截断继续无限增强 parser

× 现在实现完整 reasoning_content continuation

× 现在实现完整 completion state machine

× 现在跑完 benchmark 后编造成功率
```

---

# 二十八、完成后的输出格式

完成修改后必须按以下结构汇报。

## 1. 根因确认

说明真实代码中问题是否与预期一致：

```text
Model Request 问题
Model Response 问题
ToolCall transport 问题
ToolResult round-trip 问题
```

---

## 2. 修改文件

逐个列出：

```text
path
修改内容
为什么需要改
```

如果新增文件：

必须回答：

> 为什么不能复用已有模块？

---

## 3. 新执行链

给出真实修改后的：

```text
ModelRequest
↓
Provider Adapter
↓
ModelTurn
↓
ToolCall
↓
Runtime Tool
↓
SafeExecutionService
↓
ToolResult
↓
role=tool
↓
next ModelRequest
```

---

## 4. Compatibility

说明：

```text
CLI run
Agent Eval
Fallback codec
Mock/Fake ModelClient
existing tool schemas
```

是否发生接口变化。

---

## 5. Tests

列出：

```text
测试文件
测试 case
命令
真实结果
```

项目命令必须遵循仓库规定使用：

```bash
.venv/bin/python
```

不要使用系统 `python3` 跑项目测试。

---

## 6. Regression

至少运行与本次修改直接相关的：

```text
llm
agent
agent_loop
evaluation
cli
execution
```

测试。

完成前必须运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check <本轮触达路径>
.venv/bin/python -m mypy --follow-imports=skip <本轮触达路径>
git diff --check
```

不得编造测试结果。

---

## 7. Design Decision

说明新增/更新的 DD 文件，并同步更新：

```text
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
README.md
```

`单Agent执行闭环修复记录.md` 必须追加本轮：问题、设计选择、修改、离线测试、
`B01 NOT_RUN_BY_CODER`、benchmark `NOT_RUN` 和仍未解决的 Completion Ownership。

---

## 8. Failure Case

说明：

```text
原 failure
root cause
修复后的 invariant
仍未解决的问题
```

---

## 9. Remaining Issues

必须明确告诉我：

```text
哪些属于第一刀已经解决
哪些仍属于第二刀
```

特别注明：

```text
Runtime completion ownership / READY_TO_FINALIZE
```

仍然 pending，不要假装本次已经彻底解决 SingleAgent。

---

# 二十九、最终验收标准

只有同时满足下面条件，本次第一刀才算完成：

```text
[ ] Model Client 不再只有 messages → text contract

[ ] 有明确 Provider-neutral ModelRequest

[ ] 有明确 Provider-neutral ModelTurn

[ ] native tool_calls 不再降级成文本 JSON

[ ] Provider tool_call_id 能通过 Adapter 完整 round-trip

[ ] provider_call_id 与 runtime_call_id 分离并可持久化映射

[ ] native tool result 使用真正 role=tool

[ ] content=None + valid tool_calls 被认为是合法 turn

[ ] finish_reason=length 不再伪装成 JSON parse failure

[ ] max_output_tokens 实际进入 Provider request

[ ] input budget 为 output tokens 和 safety headroom 预留空间

[ ] malformed tool args fail closed

[ ] unknown tool 不进入 backend

[ ] native apply_patch 仍进入 SafeExecutionService

[ ] native command/test 仍进入 SafeExecutionService

[ ] textual JSON / fenced JSON / DSML fallback 未被删除

[ ] CLI 和 Eval 仍共享 CodingAgentRuntime

[ ] Session resume 能恢复 native assistant/tool message 链

[ ] compaction 不会拆散 native tool call 与 tool result

[ ] 相关 tests 全部真实通过

[ ] Design Decision 已补充

[ ] Failure Case 已更新

[ ] 单 Agent 持续修复记录、代码架构、设计决策和 README 已同步

[ ] B01 真实 Provider smoke 标记为 NOT_RUN_BY_CODER

[ ] 11-task benchmark 和真实 ablation 均标记为 NOT_RUN

[ ] 未顺手重构 Completion State Machine
```

---

# 三十、本次修改的核心原则

始终记住：

> **这次不是让 LLM “更会输出 JSON”，而是让 Runtime 不再要求 LLM 用自由文本模拟 Tool Protocol。**

以及：

> **Provider 负责协议适配，Runtime 负责 Agent 语义，SafeExecutionService 负责副作用边界。**

最终目标不是：

```text
更强的 JSON parser
```

而是：

```text
Provider-native Agent Turn
        ↓
Provider-neutral Runtime Contract
        ↓
Safe and testable Coding Agent execution
```
