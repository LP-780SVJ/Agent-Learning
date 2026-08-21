# 第 4 周 Day 5：Context Compaction + Model / Provider Switching

Day 5 是这一周里很有 **Agent Runtime / Context Engineering 含金量**的一天，因为今天要同时解决两个会在长任务里必然出现的问题：

```text
问题 A：
Session 越来越长
→ 历史消息、Tool Result、代码、测试日志不断增长
→ Context Window 放不下

问题 B：
Agent 不应该绑定一个模型
→ 不同 Provider / Model 的
   Context Window、价格、能力、API 协议都可能不同
```

所以今天这两个主题其实是连在一起的：

```text
Session
  │
  │ durable history 可以一直增长
  ▼
ContextManager
  │
  ├── Context Budget
  ├── Compaction
  └── Current Active Context
           │
           ▼
      ModelSelection
           │
       ┌───┴────┐
       ▼        ▼
 Provider A  Provider B
 Model A     Model B
```

今天最重要的两个认知是：

> **Session 是“Runtime 记住了什么”，Context 是“这一次给模型看什么”。**

以及：

> **Model Switching 不是换一个字符串，而是在改变 Context Capacity、Capability、Cost、Error Semantics 和 Provider Runtime。**

---

# 一、先理解 Context Window 到底是什么

很多初学者会把 Context Window 理解成：

```text
聊天记录最多能有多少字
```

其实 Coding Agent 中远远不止 Conversation。

GitHub Copilot CLI 当前明确说明，Context Window 中会包含系统指令、Tool 定义、用户消息、模型回复、Tool Call 和 Tool Result；Tool Result 甚至可能成为最大的 Context 消耗源。为了防止单个 Tool 输出撑满 Context，Copilot CLI 默认会把超过 20 KiB 的 Tool Output 保存到临时文件，只给模型路径和 Preview。

所以 CodeTeam 一次真实 Model Call 的 Context 更接近：

```text
┌──────────────────────────────────────┐
│            Model Context             │
├──────────────────────────────────────┤
│ System Rules                         │
│ Tool Schemas                         │
│ Repository Rules                     │
│ TaskSpec                             │
│ Active Plan                          │
│ Compact Summary                      │
│ Recent Messages                      │
│ Relevant Code                        │
│ Recent Tool Results                  │
│ Current Error / Test Result          │
│                                      │
│            Free Space                │
│                                      │
│ Reserved Output / Safety Headroom    │
└──────────────────────────────────────┘
```

假设模型支持：

```text
400K tokens
```

并不意味着：

```text
你可以塞 399K Input
```

因为还必须为：

```text
模型 Output

Tool Calls

后续 Tool Result

Safety Headroom
```

留空间。

所以真正应该管理的是：

# Context Budget

---

# 二、Durable Session 和 Active Context 是今天最重要的区别

昨天已经实现：

```text
Session Persistence
```

假设一个 Session 已经运行两小时，磁盘中可能有：

```text
300 messages

120 tool calls

40 file reads

20 test outputs

5 repair attempts

3 plans

完整 event log
```

这些东西作为：

```text
Durable Session History
```

完全可以保留。

但不代表下一次调用 LLM 时要全部重新发送。

正确关系应该是：

```text
                Durable Session

完整 Task
完整 Plan history
完整 Messages
完整 Events
完整 Tool Results
完整 Verification history
完整 Failure history
        │
        │ Context selection
        ▼
┌──────────────────────────┐
│      Active Context      │
│                          │
│ System Rules             │
│ Repo Rules               │
│ TaskSpec                 │
│ Current Plan             │
│ Summary                  │
│ Recent Turns             │
│ Current Code             │
│ Current Test/Error       │
└──────────────────────────┘
        │
        ▼
      Model
```

可以记成一句：

```text
Durable Session
=
完整记忆


Active Context
=
当前工作集
```

这与操作系统里的：

```text
Disk
vs
Working Set / Memory
```

有一点类似。

---

# 三、为什么 Session Persistence 不能代替 Context Compaction

假设：

```text
Session 存 50 万 tokens
```

完全没问题。

JSON/JSONL 在磁盘上可以继续增长。

问题在于某个模型：

```text
Context Window = 200K
```

这次请求根本不可能：

```text
Input = 500K
```

所以：

```text
Persistence
```

解决：

> 进程死了以后，我还记不记得以前发生了什么？

而：

```text
Compaction
```

解决：

> 我记得很多事情，但下一次真正需要给模型看的到底是什么？

这两个千万不要混。

---

# 四、Summarization 和 Compaction 也不是一回事

## Summarization

Summarization 只是：

```text
大量信息
↓
较短摘要
```

例如：

```text
原始：
20 个 Tool Call
10 个 Test Result
30 个 Messages

↓

摘要：
定位到 timeout 根因位于 HttpClient，
第一次 Patch 导致 regression，
当前准备修改 RetryPolicy。
```

它是一种：

```text
信息压缩技术
```

---

## Compaction

Compaction 是完整的 Runtime Operation：

```text
检测 Context 快满
        ↓
确定哪些信息必须保留
        ↓
确定哪些历史可以压缩
        ↓
生成 Summary
        ↓
保留 Recent Window
        ↓
重新注入 Durable Instructions
        ↓
重新计算 Token Budget
        ↓
构造新的 Active Context
        ↓
继续 Agent
```

所以：

```text
Summarization
⊂
Compaction
```

---

# 五、工业案例：GitHub Copilot CLI 的 Compaction 是怎么做的

GitHub 当前公开得非常详细。

Copilot CLI 在 Context 使用率大约达到 80% 时，会在后台启动 Compaction，并预留约 20% 空间让 Tool Call 在压缩期间继续运行；如果 Context 到约 95% 而 Compaction 仍未完成，会短暂停下来等待完成。

Compaction 大致会：

```text
当前完整 conversation
        ↓
snapshot
        ↓
生成 structured summary
        ↓
旧 conversation history
被 summary 替代
        ↓
重新加入：
original instructions
current plan / todo state
        ↓
保留 compaction 期间
新产生的 messages
```

GitHub 文档还明确承认：

> Compaction 是有损的，细粒度历史、命令完整输出、早期小决策可能丢失。

这正是你今天必须理解的：

```text
Compaction
不是
Lossless Compression
```

而是：

```text
Lossy compression
+
重要信息保护策略
```

---

# 六、Claude Code 的工业设计也很值得看

Claude Code 当前同样有自动 Context Compaction，而且 Compaction Threshold 会根据模型实际 Context Window 调整；它甚至允许设置 Auto-compact Window。对于 Gateway 或自定义 Model ID，Claude Code还专门允许声明应该假定的 Context Window，因为 Runtime 如果搞错模型容量，Compaction 时机也会跟着出错。

Claude Code 还允许：

```text
/compact Focus on code samples and API usage
```

指定这一次 Summary 应重点保留什么，也可以在 `CLAUDE.md` 中配置长期的 Compaction 指令。

这里体现了一个非常重要的工业设计：

> **Context Management 必须知道当前模型的真实 Context Capacity。**

这就是为什么今天：

```text
Context Compaction
```

和：

```text
Model Metadata
```

必须一起学习。

---

# 七、OpenAI 当前甚至提供 Provider-native Compaction

OpenAI Responses API 当前提供专门的 `/responses/compact`，用于把长 Conversation State 压缩成更小、可继续使用的 Compacted State；OpenAI 文档把这种 Compaction 明确定位于长时间、多 Tool 的 Agent Workflow。

这给 CodeTeam 两种未来路线：

```text
Route A
CodeTeam 自己生成结构化 ContextSummary

Route B
调用 Provider Native Compaction
```

你的 MVP 我更推荐：

```text
Route A
```

原因非常重要：

```text
CodeTeam
目标是 Provider-neutral Runtime
```

如果 Session 完全依赖：

```text
Provider A
生成的 opaque compact state
```

以后切换：

```text
Provider B
```

可能根本无法使用。

所以第一版最好：

```text
Provider-neutral
Structured ContextSummary
```

成为 CodeTeam 自己的 Runtime State。

Provider-native Compaction 后面可以作为：

```text
Optimization
```

而不是架构基础。

---

# 八、Context 中的信息不能一视同仁

这是今天 Context Engineering 的核心。

建议把信息分成三个权威等级。

| 类型 | 示例 | Compaction 策略 |
|---|---|---|
| Authoritative | System Rules、Repo Rules、TaskSpec、Constraints、Active Plan、Checkpoint | 不依赖 Summary，重新注入 |
| Durable Derived Facts | 已确认根因、设计决定、失败尝试、修改文件、测试状态 | Structured Summary |
| Ephemeral Working Context | Recent Messages、Current File、最近 Tool Output | Recent Window / Retrieval |

最关键的是第一行。

例如用户明确说：

```text
不得修改 Public API
```

不要期望：

```text
LLM Summary
```

每次都正确记住。

应该：

```text
TaskSpec.constraints
```

仍然完整存在于 Session。

每次 Model Call：

```text
重新注入。
```

---

# 九、为什么“Instruction Reinjection”如此重要

一个危险设计：

```text
第一次：

TaskSpec:
不能修改 Public API

↓

Compact

↓

Summary:
目前正在修 timeout...
```

假设 Summary 漏掉：

```text
不能修改 Public API
```

Agent 后面就可能直接：

```text
改变 API
```

所以正确：

```text
System Rules
        │
        │ authoritative reload
        ▼

Repository Rules
        │
        │ authoritative reload
        ▼

TaskSpec
        │
        ▼

Active Plan
        │
        ▼

Compact Summary
```

Summary 只负责：

```text
过去发生了什么
```

不能负责：

```text
Agent 必须遵守什么。
```

这是一条非常重要的 Context Engineering 原则。

---

# 十、Repository Rules 也应该重新加载

你前面已经有类似：

```text
InstructionLoader
```

所以 Compaction 后不要：

```text
依靠 summary 记住 AGENTS.md 内容
```

而应该：

```text
Worktree
   ↓
InstructionLoader
   ↓
current AGENTS.md
   ↓
inject
```

甚至可以保存：

```text
repo_instruction_hash
```

如果发现：

```text
AGENTS.md
发生变化
```

就重新构建 Instruction Context。

这可以防：

```text
Stale Repository Instructions
```

---

# 十一、Active Plan 同样不应该由 Summary 决定

假设真正 Session：

```text
P1 COMPLETE
P2 COMPLETE
P3 RUNNING
P4 PENDING
```

Summary 错写：

```text
P3 已完成
```

如果 Runtime相信 Summary：

```text
会跳过 P3。
```

所以：

```text
Active Plan
```

来自昨天持久化的：

```text
Session.plan
```

Summary 只能补充：

```text
P3 为什么做到这里
```

不能决定：

```text
P3 status
```

---

# 十二、这意味着你的 Context 应该每 Turn 重新 Assemble

不要维护一个越来越大的：

```python
messages.append(...)
```

然后永远直接传给 Model。

更成熟：

```text
Durable Session
       │
       ▼
ContextAssembler
       │
       ├── System Rules
       ├── Repository Rules
       ├── TaskSpec
       ├── Active Plan
       ├── ContextSummary
       ├── Recent Window
       └── Current Retrieved Context
       │
       ▼
ActiveContext
       │
       ▼
ModelClient
```

这其实就是：

# Context Engineering

---

# 十三、Recent Window 是什么

即使有 Summary，也不能只发送：

```text
Summary
```

因为最近几轮通常包含最精确的信息。

例如：

```text
Turn 81:
Agent Patch

Turn 82:
pytest failure

Turn 83:
read retry.py
```

如果马上压成：

```text
“测试失败，正在检查 retry.py”
```

就丢掉了：

```text
具体 Assertion
具体 Stack Trace
具体代码上下文
```

所以：

```text
Summary
+
Recent Window
```

需要同时存在。

---

# 十四、Recent Window 不建议按“最近 10 条消息”

更合理：

```text
Recent Window Token Budget
```

因为：

```text
Message A:
20 tokens

Message B:
20,000 tokens Tool Output
```

两条消息完全不同。

所以：

```text
keep_last_n_messages = 20
```

并不是真正的 Context Budget。

更应该：

```text
recent_budget_tokens
```

然后从后往前装，直到预算满。

---

# 十五、Context Budget 怎么计算

推荐建立类似：

```text
Model Context Window
        │
        ├── Reserved Output
        ├── Safety Headroom
        ├── System / Tools
        ├── Repo Instructions
        ├── TaskSpec / Plan
        │
        └── Dynamic Context Budget
```

概念公式：

```text
usable_dynamic_budget
=
model.context_window
-
reserved_output
-
safety_headroom
-
system_tokens
-
tool_schema_tokens
-
instruction_tokens
-
task_plan_tokens
```

然后：

```text
dynamic budget
```

再分给：

```text
Summary

Recent Messages

Retrieved Code

Tool Results
```

这比：

```text
Context 已到 200K
才处理
```

健康得多。

---

# 十六、为什么必须留 Headroom

假设：

```text
Model Context = 200K

Input = 199K
```

这一次模型如果需要：

```text
8K Output
```

就不够。

更麻烦的是 Coding Agent：

```text
Model
↓
Tool Call
↓
Tool Output
↓
再次 Model Call
```

同一个 Turn 中 Context 还会继续增长。

GitHub 当前在约 80% 就开始后台压缩，正是为了给 Tool Call 和后续运行留下空间。

所以：

> Context Budget 管理必须提前发生，而不是等 Provider 返回 Context Overflow。

---

# 十七、建议的 `ContextSummary`

第一版建议它是**结构化的 Working Memory**，而不是一段散文：

```python
class ContextSummary(BaseModel):
    summary_version: int

    task_goal: str

    confirmed_facts: tuple[str, ...]
    decisions: tuple[str, ...]

    modified_files: tuple[str, ...]

    failed_attempts: tuple[str, ...]
    verification_state: tuple[str, ...]

    current_checkpoint_id: str | None

    unresolved_issues: tuple[str, ...]
    next_actions: tuple[str, ...]

    source_turn_start: str
    source_turn_end: str
```

注意：

```text
Task Constraints
Active Plan Status
```

虽然 Summary 可以有一份人类可读描述，

但真正权威状态仍然来自：

```text
TaskSpec
Plan
Session
```

---

# 十八、`CompactionRequest`

它回答：

> 为什么现在需要 Compact？要 Compact 哪一段？当前模型容量是多少？

例如概念上：

```python
class CompactionRequest(BaseModel):
    session_id: str

    reason: CompactionReason

    model_selection: ModelSelection

    context_window_tokens: int
    current_context_tokens: int

    target_context_tokens: int

    previous_summary: ContextSummary | None

    messages_to_compact: tuple[MessageRef, ...]

    recent_messages_to_keep: tuple[MessageRef, ...]
```

Reason 可以是：

```text
AUTO_THRESHOLD

MODEL_SWITCH

MANUAL

CONTEXT_OVERFLOW_RECOVERY
```

特别注意：

```text
MODEL_SWITCH
```

后面非常重要。

---

# 十九、`CompactionResult`

建议至少能回答：

```text
压缩了什么？

保留了什么？

压缩前多少 Token？

压缩后多少？

生成了哪个 Summary Version？
```

例如：

```python
class CompactionResult(BaseModel):
    summary: ContextSummary

    compacted_turn_ids: tuple[str, ...]
    retained_turn_ids: tuple[str, ...]

    tokens_before: int
    tokens_after: int

    summary_tokens: int

    created_at: datetime
```

这以后 Benchmark 很方便。

---

# 二十、Compaction 最重要的 Invariant

一定记住：

```text
Compaction
只能改变：

Active Context


不能删除：

Durable Session History
```

也就是说：

```text
events.jsonl

完整消息记录

Tool history
```

仍然保留。

只是下一次：

```text
Model Call
```

不再全部携带。

因此用户后面：

```text
查看历史
debug
evaluation
```

仍然可以找到原始事实。

---

# 二十一、Compaction 什么时候触发

第一版不建议追求 GitHub 那种：

```text
background async compaction
```

因为那会引入：

```text
Compaction snapshot
+
同时新消息产生
+
Merge
```

的并发问题。

GitHub 当前专门需要在后台 Compact 时保留 Compact 期间新加入的 Messages。

你的 Single Agent MVP 第一版更适合：

```text
Turn completed
       ↓
calculate context
       ↓
threshold exceeded?
       │
      YES
       ↓
synchronous compaction
       ↓
start next turn
```

也就是：

> **Compaction 只发生在 Turn Boundary。**

这样简单很多。

---

# 二十二、Context Compaction 最危险的 Failure Case

不是：

```text
压缩失败
```

而是：

# Silent Information Loss

例如 Summary 忘了：

```text
用户约束：
不能增加 dependency
```

Agent 后面：

```text
pip install xxx
```

所以你的测试不能只：

```python
assert tokens_after < tokens_before
```

还必须验证：

```text
Semantic Retention
```

---

# 二十三、你要求的摘要保留测试应该怎么做

我建议固定构造一个长 Session，其中明确埋入：

| 必须保留 | 示例 |
|---|---|
| 用户约束 | 不得修改 public API |
| 当前文件 | `src/auth/client.py` |
| 失败测试 | `test_retry_timeout` |
| 当前 Plan | P3 RUNNING |
| Checkpoint | cp-004 |
| 未完成 Step | P4/P5 |

Compact 后同时验证两件事。

第一层：

```text
ContextSummary
```

确实包含这些重要 Working Facts。

第二层更重要：

```text
ActiveContext
```

仍从：

```text
TaskSpec
Plan
Session
```

重新注入约束、Plan、Checkpoint。

这样即使 Summary 偶尔漏一个字段：

```text
Runtime safety
仍不完全依赖 Summary。
```

这是比单纯“让摘要更好”更强的设计。

---

# 二十四、Model Switching：先彻底区分 Provider 和 Model

下午最重要的第一个概念：

```text
Provider
≠
Model
```

例如概念上：

```text
Provider:
OpenAI

Model:
gpt-xxx
```

另一种：

```text
Provider:
公司内部 LLM Gateway

Model:
某模型 ID
```

Provider 决定：

```text
怎么连接

Base URL

Wire Protocol

Authentication

Headers

Retry semantics
```

Model 决定：

```text
能力

Context Window

Output Limit

Reasoning

Cost

Tool capability
```

---

# 二十五、Codex 当前已经明确这么设计

Codex 当前的高级配置把：

```text
model
```

和：

```text
model_provider
```

完全分开。

官方把 Model Provider 定义为 Codex 如何连接到模型，包括 Base URL、Wire API、Authentication 和可选 HTTP Headers；当前也可以配置代理、Ollama、Mistral、Azure 等 Provider。

这个工业设计跟你：

```text
ProviderRegistry
+
ModelSelection
```

几乎是同一个问题。

---

# 二十六、为什么不能写成一个 `model="xxx"`

假设：

```text
model="model-a"
```

Runtime 仍然不知道：

```text
请求发去哪？

用哪个 Credential？

Wire Format 是什么？

Tool Call 怎么解析？

Context Window 多大？

Price 怎么算？
```

因此建议：

```python
class ModelSelection(BaseModel):
    provider_id: str
    model_id: str

    reasoning_effort: str | None = None
```

Selection 表示：

```text
这一次我要使用谁
```

---

# 二十七、`ModelMetadata` 表示什么

建议至少：

```python
class ModelMetadata(BaseModel):
    provider_id: str
    model_id: str

    context_window_tokens: int
    max_output_tokens: int

    supports_tools: bool
    supports_structured_output: bool
    supports_streaming: bool

    input_modalities: tuple[str, ...]

    input_price_per_million: Decimal | None
    output_price_per_million: Decimal | None
```

Codex 当前 App Server 的 `model/list` 本身就会返回模型级 Metadata，例如支持哪些 Reasoning Effort、输入 Modalities、是否支持 Personality、是否为默认模型等。

所以工业产品里的 Model Picker 背后不是：

```text
List[str]
```

而通常是：

```text
Capability Metadata
```

---

# 二十八、ModelMetadata 为什么必须和 Provider 绑定

这是很容易漏掉的一点。

不能单纯：

```text
metadata["model-x"]
```

最好：

```text
metadata[
    (provider_id, model_id)
]
```

因为同一个模型名通过：

```text
Provider A

Gateway B

Cloud Provider C
```

实际：

```text
Context Window

Tool Support

Endpoint

Quota

部署配置
```

可能不同。

Claude Code 当前甚至专门说明：当通过 LLM Gateway 或 Custom Model ID 使用模型时，Runtime 对 Context Window 的假设可能与真实部署不同，因此允许显式修正 Context Window。

这正说明：

> **Context Capacity 属于实际 Model Deployment，而不只是一个模型名称。**

---

# 二十九、`ProviderRegistry`

推荐关系：

```text
                  ProviderRegistry
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
    Provider A Adapter         Provider B Adapter
           │                         │
           ▼                         ▼
      ModelClient                ModelClient
           │                         │
           └────────────┬────────────┘
                        ▼
                    AgentLoop
```

AgentLoop 永远只依赖：

```text
ModelClient Protocol
```

不应该：

```python
if provider == "openai":
    ...

elif provider == "anthropic":
    ...
```

出现在 AgentLoop、Planner、RepairLoop 里。

---

# 三十、Provider Adapter 真正做什么

Provider Adapter 是：

```text
CodeTeam Canonical Request
        ↓
Provider-specific API Request
```

以及：

```text
Provider-specific Response
        ↓
CodeTeam Canonical Response
```

包括：

```text
Messages

Tool definitions

Tool calls

Usage

Streaming

Errors
```

例如：

```text
Provider A RateLimitError

Provider B HTTP 429
```

都应该变成昨天的：

```text
AgentErrorCode.MODEL_RATE_LIMIT
```

这就是：

```text
ModelErrorMapper
```

的作用。

---

# 三十一、`ModelErrorMapper`

它是 Day 3 Error Taxonomy 和 Day 5 Provider Runtime 的连接点：

```text
Provider A Exception
        │
        ▼
ModelErrorMapper A
        │
        ▼
MODEL_RATE_LIMIT


Provider B Exception
        │
        ▼
ModelErrorMapper B
        │
        ▼
MODEL_RATE_LIMIT
```

于是：

```text
ErrorClassifier
RecoveryPolicy
RetryPolicy
```

完全不需要知道：

```text
到底用了哪家公司。
```

这就是 Provider-neutral Runtime 的真正价值。

---

# 三十二、为什么 Model Switch 只能发生在 Turn Boundary

这是下午最重要的 Runtime Invariant。

假设：

```text
Turn 23
```

已经使用：

```text
Provider A / Model A
```

生成：

```text
Tool Call:
read_file(...)
```

Tool Result 回来后，

如果突然：

```text
Provider B / Model B
```

继续同一个 Turn，

你可能出现：

```text
工具调用语义变化

Prompt Format 变化

Token Accounting 混乱

Context Capacity 改变

Model-specific state 丢失

Trace 不知道一次 Turn 属于谁
```

所以建议：

```text
TurnExecution
开始
    │
    ▼
ModelSelection
固定
    │
    ▼
Model Call
    │
    ▼
Tool
    │
    ▼
Model continuation
    │
    ▼
Turn Complete

──────────── boundary ────────────

现在才能 Switch
```

---

# 三十三、GitHub Copilot CLI 当前就是这个策略

GitHub 当前 `/model` 支持 Session、Repository 和 Global 等 Scope；如果 Agent 正在运行时用户请求切换 Model，这个切换会被排队，等当前 Turn 完成之后才应用，而不会直接改变正在运行中的请求。

这是非常典型的：

# Turn-level Immutability

你的 CodeTeam 非常值得照这个思想做。

---

# 三十四、Codex Resume 换模型也很值得学习

Codex 当前 `thread/resume` 支持用不同于原 Thread 的 Model 恢复；如果 Resume 时模型变化，会给出 Warning，并在下一 Turn 应用一次 Model-switch Instruction。

这说明模型改变并不是：

```text
session.model = "new"
```

这么简单。

Runtime 应明确知道：

```text
模型发生了变化。
```

---

# 三十五、为什么切模型和 Context Compaction 紧密相关

假设：

```text
Model A:
Context Window = 400K

Current Active Context:
260K
```

用户切到：

```text
Model B:
Context Window = 128K
```

你不能：

```text
selection = ModelB
→ 直接发送 260K
```

必然出错。

正确：

```text
Switch requested
       ↓
load target ModelMetadata
       ↓
calculate target ContextBudget
       ↓
current context fits?
       │
   ┌───┴───┐
   ▼       ▼
 YES       NO
  │         │
  │         ▼
  │     COMPACT
  │         │
  │     fits now?
  │         │
  │    ┌────┴────┐
  │    ▼         ▼
  │   YES       NO
  │    │         │
  └────┘      reject switch /
               require new session
       │
       ▼
apply switch
```

这就是今天两个主题真正的连接点。

---

# 三十六、Anthropic 当前甚至公开处理这个问题

Claude Code 当前支持 Fallback Model Chain，但在执行 Compaction 时，不会切换到 Context Window 比 Primary 更小的 Fallback Model，因为那样可能在压缩之前就无法容纳当前 Conversation。

这是非常好的工业例子：

> **Model Routing 必须考虑 Context Compatibility，而不能只考虑“这个模型现在可用”。**

---

# 三十七、所以 Model Switch 最好是一个 Transaction

不要：

```python
session.model = new_model
```

马上完成。

推荐：

```text
Switch Request

1. Resolve provider
2. Resolve model
3. Validate capabilities
4. Validate credentials
5. Get model metadata
6. Check context compatibility
7. Compact if required
8. Rebuild ModelClient
9. Persist selection
10. Emit event
11. Next Turn uses new selection
```

任何一步失败：

```text
旧 ModelSelection
仍然保持有效。
```

这类似：

```text
Atomic Configuration Change
```

---

# 三十八、Model Capability Validation

假设 Planner 依赖：

```text
Structured Output
```

目标 Model：

```text
supports_structured_output=False
```

如果你只是：

```text
model ID 有效
→ 切换
```

下一 Turn 才炸。

更合理：

```text
Task Runtime
required capabilities

          ↓

ModelMetadata

          ↓

compatible?
```

例如：

| Runtime Requirement | Metadata |
|---|---|
| Tool calling | `supports_tools` |
| Structured Plan | `supports_structured_output` |
| Image input | `input_modalities` |
| Required context | `context_window_tokens` |

不满足：

```text
MODEL_CAPABILITY_MISMATCH
```

直接拒绝 Switch。

---

# 三十九、Session 中怎么持久化 Model

昨天 Session：

```text
provider_id
model_id
```

今天建议稍微升级。

Session 保存：

```text
current_selection
```

但每个 Turn 还必须单独记录：

```text
Turn 31:
provider=A
model=X

Turn 32:
provider=A
model=X

Turn 33:
provider=B
model=Y
```

原因是最终 Evaluation：

```text
Task tokens
cost
latency
success
```

必须知道：

```text
是谁产生的。
```

---

# 四十、推荐 Event

例如：

```text
model.switch_requested

model.switch_applied

model.switch_rejected

turn.started

turn.completed
```

`turn.started`：

```text
turn_id
provider_id
model_id
reasoning_effort
context_tokens
```

`turn.completed`：

```text
input_tokens
output_tokens
cost
latency
```

这样：

```text
Provider Benchmark
```

后面基本免费得到。

---

# 四十一、Resume 时 Model Override 的推荐优先级

你的 CLI 后面准备：

```bash
codeteam resume ses123 \
  --provider B \
  --model Y
```

我建议定义明确优先级：

```text
Explicit Resume CLI Override
        ↓
Saved Session Selection
        ↓
Repository Default
        ↓
User Default
        ↓
Built-in Default
```

也就是说：

```text
--provider / --model
```

如果用户明确给了：

```text
一定优先。
```

没有给：

```text
默认恢复原 Session Model。
```

不要因为默认配置改变了：

```text
偷偷换 Model。
```

这是你的设计建议；各家产品的 Resume 规则并不完全相同，例如 Claude Code 当前就有自己的配置优先级和 Resume Model 行为。

---

# 四十二、API Key 千万不要进 Session

Session：

```text
provider_id = provider-a
```

可以保存。

但：

```text
api_key = sk-...
```

不要。

Resume：

```text
provider_id
     ↓
ProviderRegistry
     ↓
ProviderConfig
     ↓
Environment / Secret Store
     ↓
Credential
```

这样：

```text
Session Persistence
```

不会变成：

```text
Credential Database。
```

---

# 四十三、推荐上午的数据结构关系

```text
                  Durable Session
                        │
                        ▼
                ContextCompactor
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
      ContextSummary         Recent Window
             │                     │
             └──────────┬──────────┘
                        ▼
                 ContextAssembler
                        │
        ┌───────────────┼──────────────┐
        ▼               ▼              ▼
   Task/Rules       Current Plan   Retrieved Code
                        │
                        ▼
                  ActiveContext
```

`ContextCompactor`：

```text
压缩历史
```

`ContextAssembler`：

```text
决定下一次真正发送什么。
```

这两个职责最好不要合成一个 God Object。

---

# 四十四、下午的数据结构关系

```text
                  ModelSelection
                        │
                        ▼
                 ProviderRegistry
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
        Provider A            Provider B
              │                   │
              ▼                   ▼
         ModelClient           ModelClient
              │                   │
              └─────────┬─────────┘
                        ▼
                   AgentLoop
```

另一个：

```text
Provider Error
     │
     ▼
ModelErrorMapper
     │
     ▼
AgentFailure
     │
     ▼
Day 3 RecoveryPolicy
```

这样前三天和今天就完全接起来了。

---

# 四十五、推荐今天的实现顺序

建议不要上午一上来就调用真实模型 Compact。第一步先建立 `ModelMetadata` 和 Context Budget，因为没有目标 Model Capacity，你连什么时候应该 Compact 都不知道。之后实现 `ContextSummary`、`CompactionRequest/Result` 和一个 deterministic `ContextAssembler`，再用 Mock Compactor 测试 authoritative instruction reinjection、recent window 和 token budget。第三步才接真实 LLM 做 Structured Summary，并把每次 Summary 版本持久化到昨天的 `context.json`。

下午先把 Provider Registry 与现有 `ModelClient` 接通，保证 AgentLoop 不出现 Provider-specific `if/else`；然后实现 `ModelSelection`、`ModelMetadata`、Provider-specific `ModelErrorMapper`。接着实现一个 `ModelSwitchService`，把 Switch 变成“validate capability → validate context → compact if needed → rebuild client → persist → next turn apply”的完整操作。最后再真实跑两个 Provider，不要先用真实 Provider Debug 基础状态机。

---

# 四十六、今天最关键的测试矩阵

Context 测试不应该只测“Summary 有内容”。你真正要验证的是下面这些不变量：

| Case | 预期 |
|---|---|
| 用户约束在很早的 Turn | Compact 后仍在 Active Context |
| Current Plan | 从 Session 重新注入 |
| Current Checkpoint | 从 Session 重新注入 |
| Earlier failed test | Summary 中保留 |
| Current file | Recent/Retrieval Context 保留 |
| Unfinished step | Plan 中仍保持 PENDING/RUNNING |
| Huge Tool output | 不让原始全文永久占 Active Context |
| Context under budget | 不应无意义 Compact |
| Context over threshold | 触发 Compact |
| Compaction result still too large | 不开始下一 Model Turn |

Model 测试建议同时覆盖：

| Case | 预期 |
|---|---|
| Provider A | 正常运行 |
| Provider B | 正常运行 |
| Invalid provider | 切换失败，旧 Selection 保留 |
| Invalid model | 切换失败 |
| Missing credential | 切换失败 |
| Missing tool capability | 切换失败 |
| Smaller context model | 先 Compact |
| Compact 后仍放不下 | 拒绝 Switch |
| Switch during active turn | Queue，不立即生效 |
| Next turn | 使用新 Model |
| Provider A 429 | 统一成 MODEL_RATE_LIMIT |
| Provider B 429 equivalent | 同样映射 MODEL_RATE_LIMIT |
| Resume without override | 恢复 Session Selection |
| Resume with explicit override | 验证后使用 Override |

---

# 四十七、Benchmark：Provider A vs Provider B 怎么正确做

你要求固定 5 个 Coding Tasks，非常合理。

但这里有一个实验陷阱：

如果：

```text
Provider A
=
Model A


Provider B
=
Model B
```

你测到的不是：

```text
Provider Difference
```

而是：

```text
Provider
+
Model
+
Pricing
+
Context
+
Capability
```

的综合差异。

所以最终报告应该准确叫：

```text
Model/Provider Configuration Comparison
```

而不是宣称：

```text
“Provider A 比 Provider B 强 20%。”
```

除非两边真正暴露的是同一个模型。

---

# 四十八、5 Task Benchmark 建议统计

你原来的指标全部保留：

| Task | Selection | Success | Input Tok | Output Tok | Cost | Latency | Tool Calls | Repairs |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| T1 | A | | | | | | | |
| T1 | B | | | | | | | |
| … | | | | | | | | |

另外我建议加入：

```text
Context Compaction Count

Time-to-first-green

Provider Retry Count
```

因为模型不同可能造成：

```text
更多 repair

更多 context consumption

更多 retry
```

这些都会最终反映到：

```text
Cost / Success
```

---

# 四十九、Context Compaction Benchmark 应该测什么

不要只：

```text
tokens_before
→
tokens_after
```

因为最暴力的：

```text
把全部历史删掉
```

Token Reduction：

```text
100%
```

但 Agent 彻底失忆。

真正指标应同时看：

| 指标 | 含义 |
|---|---|
| Token Reduction | 压缩程度 |
| Task Success | 最终还能否完成任务 |
| Lost Constraint Rate | 是否忘记用户约束 |
| Plan Continuity | 是否继续正确 Step |
| Repeated Retrieval | 是否因为忘记信息又重复搜索 |
| Compaction Latency | 压缩本身耗时 |
| Compaction Cost | Summary 使用的 Token/费用 |

这里：

```text
Lost Constraint Rate
```

尤其值得成为核心指标。

---

# 五十、Ablation 1：No Compaction vs Structured Compaction

准备一个长任务：

```text
多个 PlanStep

多轮 Tool Call

多次 Test Failure

大量文件读取
```

Full：

```text
Structured Compaction
```

Ablation：

```text
No Compaction
```

最终比较：

```text
Task completion

context overflow

tokens

cost

latency

lost constraints
```

但这个实验可能有一个自然结果：

```text
No Compaction
最终直接撞 Context Limit。
```

因此我还建议加一个更有研究价值的第二组：

```text
Naive Truncation
vs
Structured Compaction
```

Naive：

```text
只保留最后 N Tokens
```

Structured：

```text
Task + Plan + Summary + Recent + Retrieval
```

这更能证明：

> **Structured Context Engineering 是否比简单截断更有价值。**

---

# 五十一、Ablation 2：Single Provider vs Provider-neutral Runtime

这个实验不像 Context 那么容易用：

```text
Task Success
```

证明。

它更偏：

# Architecture Ablation

可以测：

| 指标 | Single-provider | Provider-neutral |
|---|---:|---:|
| 新增 Provider 需要修改的 Core Files | | |
| AgentLoop 改动 LOC | | |
| Planner 改动 LOC | | |
| RepairLoop 改动 LOC | | |
| Provider Contract Tests | | |
| Error Mapping Consistency | | |

理想设计应该是：

```text
新增 Provider B
```

主要新增：

```text
Provider Adapter

Provider Config

Error Mapper
```

而不是改：

```text
AgentLoop
Planner
RepairLoop
Session
ContextCompactor
```

这就是：

```text
Provider Neutrality
```

真正的工程证据。

---

# 五十二、Context Compaction 的典型 Failure Cases

这里值得重点记录五类。

第一类是 **Constraint Loss**。用户早期说“不能修改 API”，Summary 丢失，后续 Agent 越界。解决方案不是只提高 Prompt，而是把 Task Constraints 当 authoritative state 重新注入。

第二类是 **Summary Hallucination**。模型摘要写成“timeout 根因已确认是 retry.py”，实际上那只是一个已被证伪的旧假设。所以 Summary 最好区分：

```text
confirmed_facts

failed_hypotheses

unresolved_questions
```

而不是全部写成一个 Narrative。

第三类是 **Summary Drift**。第一次 Summary → 第二次对第一次 Summary 再总结 → 第三次再总结，逐渐像“传话游戏”。因此应该保留 Durable History 和版本化 Summary，必要时能从较早 Context Checkpoint 重新生成，而不是永远把前一个 Summary 当唯一真相。

第四类是 **Recent Tool Causality Loss**。刚执行了 Patch，紧接着 Test Failed，却在二者中间 Compact，模型可能失去“这个 Error 是由哪个 Patch 引起”的细节。所以 MVP 最好只在 Turn Boundary Compact。

第五类是 **Wrong Context Window Metadata**。Runtime 以为目标模型有 400K，但 Gateway 实际只允许 128K，于是 Compaction 触发太晚。Claude Code 当前专门提供 Custom/Gateway Context Window 修正机制，正是因为这是真实工业问题。

---

# 五十三、Model Switching 的典型 Failure Cases

最重要的是 **Smaller-window Switch**：

```text
400K model
→
128K model
```

没有提前 Compact。

其次是 **Capability Mismatch**：

```text
Planner 需要 Structured Output
→
目标 Model 不支持
```

第三类是 **Mid-turn Switching**：

```text
Model A
生成 Tool Call

Model B
接 Tool Result
```

导致 Turn Trace 和语义不一致。

第四类是 **Usage Attribution Error**。Model 已经切换，但 Token/Cost 仍计在旧 Model 上，Benchmark 全部失真。

第五类是 **Silent Resume Switch**。用户 Resume 一个长期任务，却因为全局 Default 改变而偷偷换 Model。你的 CodeTeam 第一版最好恢复 Saved Selection，除非用户显式 Override。

第六类是 **Provider Error Leakage**。Provider A 抛一种 RateLimit Exception，Provider B 抛另一种，结果 Orchestrator 为两个 Provider 写两套逻辑。这说明 `ModelErrorMapper` 没有真正隔离 Provider。

---

# 五十四、今天我建议写两个 Design Decision

第一个可以叫：

```text
DD-W4-D5-01
Structured Context Compaction
```

核心 Decision：

```text
Durable History remains complete.

Active Context is reconstructed
from authoritative state,
structured summary,
recent messages,
and current retrieval.

LLM summary is not the source of truth
for safety instructions,
task constraints,
plan state,
or checkpoint identity.
```

Evidence Status 当前：

```text
PROPOSED
```

等长任务 Ablation 后再决定是否 `SUPPORTED`。

第二个：

```text
DD-W4-D5-02
Provider-neutral Model Runtime
```

核心 Decision：

```text
AgentLoop depends only on ModelClient.

Provider-specific transport,
authentication,
wire protocol,
model discovery,
and error mapping remain behind
ProviderRegistry / ProviderAdapter.

Model selection is immutable
within a turn.
```

---

# 五十五、今天结束后的完整 Runtime

Day 1～Day 5 到这里已经可以连接成：

```text
                      Durable Session
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
       TaskSpec            Plan             Usage
          │                 │
          └─────────┬───────┘
                    ▼
               ContextManager
                    │
          ┌─────────┴───────────┐
          ▼                     ▼
   ContextCompactor        ContextAssembler
          │                     │
          ▼                     ▼
       Summary             Active Context
                                │
                                ▼
                         ModelSelection
                                │
                         Turn Boundary
                                │
                                ▼
                         ProviderRegistry
                            /          \
                           ▼            ▼
                     Provider A     Provider B
                           \            /
                            ▼          ▼
                             ModelClient
                                 │
                                 ▼
                              AgentLoop
                                 │
                     ┌───────────┴──────────┐
                     ▼                      ▼
                   Patch                Tool Call
                     │                      │
                     ▼                      ▼
                 Verification          SafeExecutor
                     │
                     ▼
                   Failure
                     │
                     ▼
               ErrorClassifier
                     │
                     ▼
               RecoveryPolicy
```

现在你已经能看到 Day 1～Day 5 的逻辑关系了：

```text
Day 1：
我应该做什么？

Day 2：
我做得对不对？

Day 3：
做错后怎么办？

Day 4：
进程死后怎么继续？

Day 5：
任务很长时怎么继续记住重点，
以及怎么在不同模型之间继续工作？
```

---

# 五十六、今天最终验收标准

你今天真正达标，不是只让：

```text
Provider A works
Provider B works
```

而是应该达到：

```text
Context

[ ] Durable Session 与 Active Context 分离
[ ] Token Budget 基于 ModelMetadata
[ ] Structured ContextSummary
[ ] Recent Window
[ ] System Rules authoritative reinjection
[ ] Repository Rules authoritative reinjection
[ ] TaskSpec authoritative reinjection
[ ] Active Plan authoritative reinjection
[ ] Context compaction 不删除 durable history
[ ] Compact 后用户约束仍然存在
[ ] Compact 后 current Plan / checkpoint 正确


Provider

[ ] Model 和 Provider 分离
[ ] ProviderRegistry
[ ] ModelSelection
[ ] ModelMetadata
[ ] ModelErrorMapper
[ ] AgentLoop 不包含 Provider-specific branch
[ ] Provider A 实际运行
[ ] Provider B 实际运行


Switching

[ ] Turn 内 ModelSelection immutable
[ ] Mid-turn switch 被推迟
[ ] Target model capability validation
[ ] Smaller context → compact first
[ ] Compact 后仍超限 → reject switch
[ ] 每个 Turn 记录 provider/model
[ ] Resume 默认恢复原 selection
[ ] Explicit resume override 可验证后应用


Evaluation

[ ] 5 fixed tasks
[ ] Success
[ ] Token
[ ] Cost
[ ] Latency
[ ] Tool Calls
[ ] Repair Attempts
[ ] Compaction Count
[ ] Lost Constraint Rate


Evidence

[ ] Context Benchmark
[ ] Compaction Ablation
[ ] Provider Architecture Ablation
[ ] Failure Case Database
[ ] 2 个 Design Decisions
```

---

完成 Day 5 后，你应该已经能够回答一个 Agent Infra 面试里非常核心的问题：

> **“你的 Agent 会话已经运行几个小时，Context 快满了，而且用户此时切换到 Context Window 更小的另一个 Provider，你怎么保证任务还能继续？”**

你的答案不应该只是“总结历史然后换模型”，而应该是：

> CodeTeam 的 Durable Session 和 Model-visible Active Context 是分离的。Session 保留完整执行历史，但每个 Turn 由 ContextAssembler 从 authoritative Task/Plan/Instructions、版本化 Structured Summary、Recent Window 和当前 Retrieval 重新构建 Active Context。ContextBudget 由实际 `(provider, model)` 的 ModelMetadata 决定。切换 Model 时先在 Turn Boundary 固定当前 Turn，验证目标模型的 Capability 和 Context Capacity；如果目标窗口更小，则先执行 Compaction，且 Summary 不作为安全约束和 Plan State 的权威来源，这些信息会从 Durable State 重新注入。切换成功后重新构建 Provider Client，并从下一个 Turn 开始生效；每个 Turn 单独记录 Provider、Model、Usage 和 Cost。Provider-specific Error 则统一映射到 CodeTeam 的 AgentFailure，因此上层 Repair/Retry Runtime 不依赖具体供应商。

到这个程度，你实现的已经不再是“**支持两个 API 的 Agent**”，而开始真正接近一个 **Provider-neutral、Long-running、Context-aware Agent Runtime**。

---

# 附录：W4D5 当日工程地图（Coder Agent 产出，2026-08-21）

> 基线：week4 @ e96ac58，全量 1044 passed / 6 skipped（6 skip 均为 Docker 能力跳过）。
> 本地图基于对仓库的只读检查（llm/base、llm/mock、llm/openai_compatible、context/*、events、session/service、orchestrator K2 接线点、tests 布局），所有接口以实测代码为准。

## 1. 今天在整个 Coding Agent 中做什么

前四天回答了“做什么 / 对不对 / 错了怎么办 / 死了怎么续”。今天解决两个**长任务必然撞上**的问题：

```text
问题 A：Session 跑了 2 小时、300 条消息、120 次 Tool Call
        → 下一次 Model Call 不可能全发 → 压缩什么？谁权威？

问题 B：Agent 不能绑死一个模型
        → 换 Provider/Model 改变的是 Capacity/Capability/Cost/Error 语义
```

两大主题的连接点（正文 §三十五，今天最核心的一张图）：

```text
Durable Session（完整记忆，只增不减）
        │ Context selection（每 Turn 重组）
        ▼
┌─ Active Context（当前工作集）────────────────┐
│ System Rules / Repo Rules / TaskSpec / Plan   │ ← Authoritative 重新注入
│ Compact Summary（结构化 Working Memory）      │ ← Durable Derived Facts
│ Recent Window / Retrieved Code                │ ← Ephemeral
└──────────────────┬────────────────────────────┘
                   ▼ 按 (provider, model) 的 ModelMetadata 算 Budget
            ModelSelection ──Turn Boundary──→ Provider A / Provider B
                   ▼
              ModelClient → AgentLoop
```

两条铁律：**Session 是“记住了什么”，Context 是“这次给模型看什么”**；**Compaction 只改 Active Context，绝不删 Durable History**。

## 2. Capability Mapping

```text
Primary:   Context Engineering（分层重组 / Token Budget / 有损压缩策略）
           Agent Runtime — Provider-neutral Model Layer
Secondary: Agent Harness（turn boundary 不变量、恢复动作接线 K2）
           Observability（turn.* / model.* / context.* 事件、per-turn 归因）
           Safety（API key 不落盘、capability 校验、fail-closed switch）
           Evaluation（Lost Constraint Rate 等数据出口）
```

**面试价值**：正文结尾那道题——“会话几小时、Context 快满、用户切到小窗口 Provider，怎么保证任务继续？”——是 Agent Infra 岗位的高频区分题，答案的全部零件今天造。

## 3. Theory（必须吃透的概念）

| 概念 | 一句话 | 反例 |
|---|---|---|
| Durable vs Active Context | 磁盘全量记忆 vs 每 Turn 工作集 | messages 无限 append 直接发 |
| Summarization ⊂ Compaction | 前者是压缩技术，后者是完整 Runtime Operation（检测→保留策略→重组→重算预算） | 以为“生成摘要”=Compaction |
| 三级权威分层 | Authoritative（重注入）/ Durable Facts（结构化 Summary）/ Ephemeral（Recent/Retrieval） | 用户约束指望 LLM Summary 记住 |
| Context Budget 公式 | window − reserved_output − headroom − system/tools/instructions/task_plan | 塞到 window−1 再等 Provider 报错 |
| Recent Window 按 token 不按条数 | 20 条消息 ≠ 预算（一条 Tool Output 可 20K） | keep_last_n=20 |
| Turn Boundary 切换 | Turn 内 ModelSelection 不可变；mid-turn 请求排队 | Model A 发 Tool Call、Model B 接 Result |
| Provider ≠ Model | 连接方式 vs 能力容量；metadata 键是 (provider_id, model_id) | metadata["model-x"] 单键 |
| Switch = Transaction | validate→compat→compact→rebuild→persist→event，任一步失败旧 selection 有效 | session.model = new 一行了事 |
| 有损但可防 | Compaction 是 lossy + 重要信息保护策略 | 只测 tokens_after < tokens_before |

## 4. Industrial Design

| 系统 | 做法 | 启发 |
|---|---|---|
| GitHub Copilot CLI | ~80% 触发后台压缩留 20% headroom；~95% 等待完成；>20KiB Tool Output 落盘只给 preview；公开承认有损 | headroom 提前量；Tool Output 是最大消耗源 |
| Claude Code | 阈值随真实 window 调整；Gateway/Custom Model 可显式修正 window；/compact 指定保留重点；Fallback 不切更小窗口模型 | **window metadata 属于部署而非模型名** |
| OpenAI | /responses/compact Provider-native 压缩 | 选 Route A（自有结构化 Summary）保 Provider-neutral，native 作未来优化 |
| Codex | model 与 model_provider 分离；resume 换模型给 Warning + 下 Turn 生效 | resume override 语义 |

方案权衡：后台异步压缩（GitHub）vs **Turn Boundary 同步压缩（我们，MVP）**——避免 snapshot+并发 merge 复杂度；自有 Summary vs Provider-native——neutrality 优先。

## 5. 当前仓库检查（2026-08-21 实测）

| 现状 | 接口事实 | 对今天的意义 |
|---|---|---|
| `codeteam/llm/base.py` | 仅 ModelResponse dataclass | **ModelClient Protocol 尚未形式化**，今天补 |
| `codeteam/llm/mock.py` | MockModelClient.complete(*args, **kwargs) -> str | 双 Provider Mock 的基础 |
| `codeteam/llm/openai_compatible.py` | OpenAICompatibleClient.complete(messages) -> str + RetryConfig | 真实 Adapter 原型；error mapper 接它 |
| `codeteam/context/` **名称冲突警示** | Week 2 的 compressor.py/budget.py/models.py 是 **repo-map 代码文件压缩**（CompressionLevel 降级链），非会话压缩 | 新文件必须用 **compaction.py / assembler.py** 区分，docstring 首行声明区别 |
| `codeteam/events.py:61-62` | recovery.completed/failed **已定义、零发射方**（W4D3 O2） | K2 债务确认 |
| `codeteam/agent/orchestrator.py:467` | 非 RETRY/PAUSE 动作 → recovery_executor_not_wired:{action} + Terminal | K2 接线点 |
| `codeteam/session/service.py:196` | resume(session_id, *, current_repo) 完整落地（lock/reconciler/runtime_factory） | override 优先级在此扩展 |
| session/models.py | ContextMetadata 最小版；provider_id/model_id 已 durable | 今天升级 ContextMetadata |
| 测试 | 1044/6 全绿；tests/llm/ 不存在 | 新建测试目录 |
| docs | DD-W4-D4-01/02 已补写（2026-08-21 Step 0 完成） | Step 0 已还债 |

**缺口**：compaction/assembler/registry/selection/error_mapper/switching 全部不存在；无 context.*/model.switch_*/turn.* 事件；DD-W4-D5-01/02 未写（今日收尾产出）。

## 6. 涉及文件

**新增（生产）**：

```text
codeteam/llm/
├── registry.py      ProviderConfig / ProviderRegistry /
│                    ModelSelection / ModelMetadata / ContextBudget 计算
├── error_mapper.py  ModelErrorMapper：Provider 异常 → 7 类统一码
│                    （RATE_LIMIT/TIMEOUT/AUTH/CONTEXT_OVERFLOW/
│                     INVALID_REQUEST/SERVER/UNKNOWN）→ 接 AgentErrorCode
└── switching.py     ModelSwitchService：11 步 Transaction +
│                    TurnBoundaryQueue（mid-turn 排队）

codeteam/context/
├── compaction.py    CompactionReason / ContextSummary（§十七结构化）/
│                    CompactionRequest / CompactionResult /
│                    ContextCompactor（summarizer 注入式）
└── assembler.py     ActiveContext / ContextAssembler /
                     Recent Window token 装配 / Tier 重注入

tests/llm/           registry / error_mapper / switching 测试
tests/context/       compaction / assembler 测试（追加文件，不动 Week2 测试）
docs/design_decisions/  DD-W4-D5-01 / DD-W4-D5-02
「明确不做清单」      落位提议：docs/design_decisions/W4-not-doing-list.md（待用户确认）
```

**最小修改（逐条理由）**：

| 文件 | 改动 | 理由 |
|---|---|---|
| events.py | +context.compacted / context.stale_rebuilt / model.switch_requested / applied / rejected / turn.started / completed | 可观测 + per-turn 归因 |
| session/models.py | ContextMetadata 升级（+summary_version / compaction 引用）；CONTEXT_STALE 判定 | §四：model-visible state |
| agent/orchestrator.py | K2：COMPACT 动作接线 + recovery.completed/failed 发射 | 偿还 W4D3 债 |
| failures/（若必须） | classifier 消费归一化错误码的最小接入 | §4.9 |
| llm/base.py | 形式化 ModelClient Protocol（现有 complete 签名为准） | registry 返回类型契约 |

## 7. Architecture / Data Flow

```text
【上午】Compaction
Turn 结束 → 量 context tokens（按 (provider,model) metadata）
  → 超阈值? → CompactionRequest(reason=AUTO_THRESHOLD)
  → ContextCompactor：老 Summary + 待压消息 → 注入 summarizer
  → ContextSummary vN（结构化）+ Recent Window（token 预算内从后往前装）
  → 写 context.json（version+1）
下一 Turn → ContextAssembler：
  TaskSpec/Plan/Repo Rules/Checkpoint ← 从 Session 权威重注入（不信任 Summary）
  + Summary + Recent + Retrieved → ActiveContext
  → 前置检查：context_version 匹配? 不匹配 → CONTEXT_STALE → rebuild（不 fail Session）

【下午】Switching
switch_requested(selection) → [turn 进行中? → 排队，Turn 完成后处理]
  → resolve provider/model → capability 校验 → credential 校验
  → target window < current context? → COMPACT → 仍超? → reject（旧 selection 有效）
  → rebuild ModelClient → persist（Session.current_selection + 事件）→ 下一 Turn 生效
每 Turn：turn.started(provider/model/context_tokens) + turn.completed(tokens/cost/latency)

【K2】_execute_with_recovery 的 COMPACT 分支：
  compact() 成功 → recovery.completed + retry once
  compact() 失败 → recovery.failed + _TerminalFailure
```

## 8. 今日步骤拆分（正文 §四十五顺序）

| Step | 内容 | 时机 | 完成标志 |
|---|---|---|---|
| 0 | 补写 DD-W4-D4-01/02 | 热身还债 | ✅ 已完成（2026-08-21） |
| 1 | llm/registry.py：ModelSelection/ModelMetadata/ProviderRegistry + Budget 公式 | 上午 | **先有容量才知道何时压**（§四十五明令） |
| 2 | context/compaction.py：Summary/Request/Result/Compactor（summarizer 注入，Mock 可测） | 上午 | 6 要素保留测试 |
| 3 | context/assembler.py + ContextMetadata 升级 + CONTEXT_STALE→rebuild | 上午 | Invariant + tier 重注入测试 |
| 4 | llm/error_mapper.py：双 Provider 异常→统一码→接 classifier | 下午 | 双样例归一化测试 |
| 5 | llm/switching.py：Switch Transaction + turn boundary 队列 + per-turn 持久化 + resume override | 下午 | §四十六 Model 矩阵 14 项 |
| 6 | K2 接线：orchestrator COMPACT 分支 + recovery.completed/failed + 私有测试升级公共路径 | 下午 | W4D3 债清 |
| 7 | 「明确不做清单」+ DD-W4-D5-01/02 + 13 节总结 | 收尾 | REREAD/RETRIEVE 归属明确 |

## 9. Test Strategy

§四十六矩阵全量：**Context 10 项**（约束/Plan/checkpoint 重注入、failed test 保留、huge tool output 不永久占位、under-budget 不压、超阈值触发、压后仍超不开下一 Turn）+ **Model 14 项**（双 Provider 正常、invalid provider/model/credential/capability 拒绝且旧 selection 保留、小窗口先压、压后仍超拒绝、mid-turn 排队、next turn 生效、双 Provider 429 同归一化、resume 无/有 override）。

工程约束：全 Mock/Fake client、无真实网络 / sleep / skip、tmp_path、遵守 AGENTS.md。

## 10. Design Decision Plan

- **DD-W4-D5-01** Structured Context Compaction（核心：LLM summary 不是 safety/constraints/plan/checkpoint 的权威来源）——Ablation A3 后定 SUPPORTED
- **DD-W4-D5-02** Provider-neutral Model Runtime（核心：AgentLoop 只依赖 ModelClient；turn 内 selection 不可变）——A4 架构度量

## 11. Benchmark Plan（仅设计，数据出口今日保证）

Provider A/B × 5 固定任务：success / tokens / cost / latency / tool calls / repairs + **compaction count / time-to-first-green / provider retry count**（§四十八）。命名纪律：报告叫 *Model/Provider Configuration Comparison*（§四十七陷阱：不可宣称“Provider A 比 B 强 20%”）。Compaction Benchmark 七指标（§四十九），**Lost Constraint Rate 为核心**。

## 12. Ablation Plan（仅设计）

- **A3**：No Compaction vs Naive Truncation vs Structured（三组——No Compaction 预期撞墙，真正的对手是 naive truncation）→ lost-constraint / plan continuity / repeated retrieval
- **A4**：Single vs Provider-neutral——**架构度量**（新增 Provider 需改的 core files 数、AgentLoop/Planner/RepairLoop 改动 LOC、契约测试数）

## 13. Failure Cases to Watch

C1 约束丢失（Summary 漏“不改 API”）；C2 Summary 幻觉（不区分 confirmed/failed/unresolved）；C3 传话游戏式 Summary Drift（版本化+可回溯）；C4 Recent 因果丢失（只在 Turn Boundary 压）；C5 **window metadata 错**（Gateway 实际 128K、以为 400K→压缩太晚）；S1 小窗口切换不预压；S2 capability mismatch 下一 Turn 才炸；S3 mid-turn 切换；S4 usage 归因错（per-turn 记录防）；S5 silent resume 换模；S6 Provider 错误泄漏进 Orchestrator。

## 14. Interview Focus

必答：Session Persistence 与 Compaction 区别？为什么 Durable Instructions 不能靠 Summary？Recent Window 为什么按 token？为什么 switch 只在 Turn Boundary？Switch 的 11 步里哪步最容易失败？window metadata 为什么绑定 (provider,model)？Lost Constraint Rate 怎么测？API key 为什么绝不进 Session？

杀手题就是正文结尾那道——用 §五十五架构答（分离→重组→metadata 预算→boundary 事务→归因→错误归一）。

## 15. 今日最终完成标准

```text
[ ] Durable Session 与 Active Context 分离（assembler 每 Turn 重组）
[ ] Budget 基于 ModelMetadata；headroom 有测试
[ ] 结构化 ContextSummary + Recent Window + 4 类权威重注入
[ ] Compact 不删 durable history（Invariant 测试）
[ ] 6 要素保留 + CONTEXT_STALE→rebuild 测试
[ ] ProviderRegistry / Selection / Metadata / ErrorMapper；AgentLoop 零 provider 分支
[ ] Turn 内 selection 不可变；mid-turn 排队；小窗口先压；压后仍超拒绝
[ ] per-turn provider/model/tokens/cost 落事件；resume override 优先级
[ ] K2：COMPACT 接线 + recovery.completed/failed 发射；不做清单落盘
[ ] 全量回归 ≥ 1044/6，触达文件 ruff 0 error
[ ] DD-W4-D5-01/02（PROPOSED）✓ DD-W4-D4-01/02 已于 Step 0 补写完成
[ ] 13 节每日总结
```