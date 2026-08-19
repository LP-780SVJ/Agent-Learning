# 第 4 周 Day 3：Error Classification + Retry / Recovery

Day 1 你已经把 Coding Agent 从“一句话 Prompt”升级成：

```text
Natural Language
→ TaskSpec
→ Plan
→ Execution State
```

Day 2 又把一次性代码生成升级成：

```text
Patch
→ Verify
→ Observe failure
→ Repair
→ Verify again
```

今天要解决的是其中非常关键的缺口：

```text
出现 Failure
       ↓
以前：
“失败了，再试一次？”

今天：
“发生了什么类型的失败？”
       ↓
“这个失败是不是暂时性的？”
       ↓
“重试同一个动作有意义吗？”
       ↓
Retry / Repair / Replan /
Reread / Ask User /
Pause / Stop
```

今天最重要的一句话是：

> **Error Handling 的核心不是捕获 Exception，而是把 Failure 翻译成 Runtime 可以执行的 Recovery Decision。**

因此：

```text
Exception
≠
AgentFailure

AgentFailure
=
异常/失败事实
+
发生阶段
+
语义分类
+
恢复策略
```

---

# 一、为什么 `except Exception: retry()` 是 Agent Runtime 的大坑

考虑下面 8 种情况：

```text
① 模型 API 503
② API Key 错误
③ Patch context mismatch
④ pytest assertion failed
⑤ git reset --hard 被 Policy DENY
⑥ 用户拒绝 Approval
⑦ Docker Sandbox 不可用
⑧ 用户 Ctrl+C
```

如果你的代码只有：

```python
try:
    ...
except Exception:
    retry()
```

你会得到：

```text
① retry       ✓ 可能合理

② retry       ✗ 永远不会自己变好

③ retry       ✗ 同一个 Patch 再 apply 还是失败

④ retry       ✗ 重跑测试不能修代码

⑤ retry       ✗ 变成尝试绕过安全 Policy

⑥ retry       ✗ 等于忽略用户决定

⑦ retry       ? 通常应该 fail closed

⑧ retry       ✗ 用户明明要求停止
```

所以今天真正解决的是：

```text
Failure
   ↓
Classification
   ↓
Recovery Policy
```

---

# 二、工业界已经不是用一个 `failed=True`

GitHub Copilot SDK 当前提供 `onErrorOccurred` Hook，并明确建议根据 `errorType` 分类错误；官方 Hook 示例甚至会同时参考 `errorContext` 与 `recoverable`，对 transient model error 返回 `retry` 和 `retryCount`，而不是所有异常统一处理。GitHub 文档还明确建议记录错误、分类错误、不要吞掉关键错误，并给模型提供有助恢复的上下文。

OpenAI API 当前同样明确区分可恢复和不可恢复场景：500/503 等服务端问题建议稍后重试；临时 rate limit 可以遵循 `Retry-After` 或指数退避，而 billing、quota、spend-limit 一类需要用户采取行动的错误，重复 Retry 并不能恢复服务。

Anthropic Claude Code 的 Hook Runtime 甚至根据**错误发生在哪个生命周期阶段**赋予完全不同的语义：`PostToolUseFailure` 表示 Tool 已经失败；`PermissionDenied` 表示权限决定已经发生；某些 Hook timeout 并不会阻止 Tool，而 Agent SDK Callback Hook timeout 则会阻止。这说明错误处理必须知道“**在哪一层、哪一阶段失败**”，不能只看 Unix Exit Code。

这就是你今天的工业核心：

```text
Raw Exception
+
Execution Context
+
Domain Semantics

→

Typed Failure
```

---

# 三、先分清 4 个最容易混淆的概念

今天一定要把下面四组概念分开。

## 1. Error Category

回答：

> **这是哪一类问题？**

例如：

```text
MODEL
PATCH
TEST
SECURITY
```

---

## 2. Retryable

回答：

> **再次执行同一个动作，有没有合理成功概率？**

例如：

```text
MODEL_RATE_LIMIT
→ retryable

INVALID_API_KEY
→ not retryable
```

---

## 3. Transient / Permanent

回答：

> **失败原因本身可能随着时间自然消失吗？**

例如：

```text
503 overloaded
→ transient

invalid API key
→ permanent until configuration changes
```

---

## 4. RecoveryAction

回答：

> **Agent Runtime 下一步实际上应该干什么？**

例如：

```text
RETRY

REREAD_AND_REGENERATE

REPAIR

REPLAN

ASK_USER

PAUSE

STOP
```

这四个不是一回事。

---

# 四、Retryable 和 Transient 也不是完全等价

这是非常重要的一点。

通常：

```text
Transient
→ 很可能 Retryable
```

但并非绝对。

例如：

```text
Network timeout during read-only model call
```

通常：

```text
Transient
Retryable
```

但：

```text
Network timeout during remote write
```

你不知道：

```text
远程系统到底有没有完成写操作
```

这时候直接 Retry 可能：

```text
重复创建资源
重复提交
重复发送消息
```

所以还必须考虑：

# Idempotency

---

# 五、Retry 前必须问：这个操作可以安全重试吗？

例如：

```text
GET repository metadata
```

重复一次通常影响不大。

但：

```text
git push

create issue

send email

charge payment
```

如果第一次请求：

```text
服务器其实成功了
```

只是客户端：

```text
没收到响应
```

第二次 Retry：

```text
可能产生第二次副作用
```

所以正确判断应该接近：

```text
retryable
=
transient
AND
retry_is_safe
AND
retry_budget_remaining
```

而不是：

```text
timeout
→ retry
```

这是工业级 Retry 体系很重要的边界。

---

# 六、因此建议给 Failure 增加一个维度

以后可以有：

```text
retry_safety:

SAFE

CONDITIONAL

UNSAFE
```

Day 3 第一版不一定做完整类型，但概念一定要知道。

例如：

```text
Model generation timeout
→ SAFE-ish

Repository read timeout
→ SAFE

Patch apply timeout
→ 必须先检查 Workspace 状态

Remote write timeout
→ CONDITIONAL / UNKNOWN
```

---

# 七、今天推荐的 Error Taxonomy

你的九个一级 Category 很合理：

```python
class ErrorCategory(str, Enum):
    MODEL = "model"
    CONTEXT = "context"
    PATCH = "patch"
    TOOL = "tool"
    SECURITY = "security"
    TEST = "test"
    GIT = "git"
    SESSION = "session"
    USER_INTERRUPT = "user_interrupt"
```

这里：

```text
Category
```

保持粗粒度。

真正的行为差异放进：

```text
AgentErrorCode
```

---

# 八、为什么不能只靠 Category

例如：

```text
MODEL
```

里面至少可能有：

```text
RATE_LIMIT

OVERLOADED

TIMEOUT

AUTH_FAILED

CONTEXT_OVERFLOW

INVALID_REQUEST

QUOTA_EXCEEDED
```

显然：

```text
RATE_LIMIT
```

与：

```text
AUTH_FAILED
```

恢复策略完全不同。

所以：

```text
Category
=
便于统计的大类


ErrorCode
=
决定恢复策略的具体原因
```

---

# 九、建议的 `AgentErrorCode`

第一版可以覆盖这些：

```python
class AgentErrorCode(str, Enum):

    # MODEL
    MODEL_RATE_LIMIT = "model_rate_limit"
    MODEL_OVERLOADED = "model_overloaded"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_AUTH_FAILED = "model_auth_failed"
    MODEL_CONTEXT_OVERFLOW = "model_context_overflow"
    MODEL_INVALID_REQUEST = "model_invalid_request"

    # CONTEXT
    CONTEXT_INSUFFICIENT = "context_insufficient"
    CONTEXT_STALE = "context_stale"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"

    # PATCH
    PATCH_INVALID = "patch_invalid"
    PATCH_CONTEXT_MISMATCH = "patch_context_mismatch"
    PATCH_PATH_REJECTED = "patch_path_rejected"
    PATCH_APPLY_FAILED = "patch_apply_failed"

    # TOOL
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"

    # SECURITY
    POLICY_DENIED = "policy_denied"
    APPROVAL_DENIED = "approval_denied"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    SANDBOX_VIOLATION = "sandbox_violation"

    # TEST
    TEST_FAILED = "test_failed"
    TEST_TIMEOUT = "test_timeout"
    TEST_FLAKY = "test_flaky"

    # GIT
    GIT_WORKTREE_CONFLICT = "git_worktree_conflict"
    GIT_DIRTY_STATE = "git_dirty_state"
    GIT_BASE_CHANGED = "git_base_changed"

    # SESSION
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_CORRUPTED = "session_corrupted"
    SESSION_WORKTREE_MISSING = "session_worktree_missing"

    # USER
    USER_INTERRUPT = "user_interrupt"
```

第一版不求把世界上所有错误都覆盖。

重点是：

> **Code 足以区分“下一步行为明显不同”的 Failure。**

---

# 十、Error Taxonomy 应该解决什么，而不应该解决什么

不要把分类系统做成：

```text
HTTP 429
Python TimeoutError
FileNotFoundError
...
```

的 Exception Dump。

Domain Classification 应该回答：

```text
这对于 Coding Agent 意味着什么？
```

例如：

```text
FileNotFoundError
```

可能代表三种完全不同的 Domain Error：

```text
Planner 指向不存在文件
→ CONTEXT_STALE

pytest executable 不存在
→ TOOL_NOT_FOUND

Session Worktree 不存在
→ SESSION_WORKTREE_MISSING
```

所以：

> **同一个 Python Exception，在不同 Stage 中可以映射成不同 AgentFailure。**

这是今天最重要的设计原则之一。

---

# 十一、Stage / Context 是 Classification 的关键输入

我建议 ErrorClassifier 不只是：

```python
classify(exception)
```

而应该更接近：

```python
classify(
    error,
    stage,
    operation,
    metadata,
)
```

例如：

```text
TimeoutError
+
stage=MODEL_CALL

→ MODEL_TIMEOUT
```

但：

```text
TimeoutError
+
stage=VERIFICATION

→ TEST_TIMEOUT
```

再比如：

```text
TimeoutError
+
stage=SANDBOX_CONTROL

→ TOOL_TIMEOUT / SANDBOX error
```

所以：

```text
Exception Type
```

只是 Classification Evidence，

不是最终 Classification。

---

# 十二、推荐 `FailureStage`

可以考虑：

```python
class FailureStage(str, Enum):
    PLANNING = "planning"
    CONTEXT_RETRIEVAL = "context_retrieval"
    MODEL_CALL = "model_call"
    PATCH_VALIDATION = "patch_validation"
    PATCH_APPLY = "patch_apply"
    COMMAND_EXECUTION = "command_execution"
    VERIFICATION = "verification"
    APPROVAL = "approval"
    SANDBOX = "sandbox"
    GIT = "git"
    SESSION = "session"
```

以后 Observability 会非常有用。

---

# 十三、`AgentFailure` 应该是什么

这是今天最核心的数据模型。

建议概念上：

```python
class AgentFailure(BaseModel):
    failure_id: str

    task_id: str
    session_id: str | None

    category: ErrorCategory
    code: AgentErrorCode
    stage: FailureStage

    message: str

    transient: bool
    retryable: bool

    attempt: int

    recovery_action: RecoveryAction

    source_type: str | None
    source_message: str | None

    metadata: dict[str, object]
```

---

# 十四、为什么必须保留原始 Exception 信息

今天 Failure Case 中明确有：

```text
原始 Exception 丢失
```

这是非常真实的问题。

错误写法：

```python
except Exception:
    raise AgentFailure(
        message="model failed"
    )
```

然后原始：

```text
HTTP 429
request ID
provider error code
Retry-After
```

全部没了。

以后你根本无法 Debug。

---

# 十五、但也不能把 Exception 原样扔给用户

因为原始错误可能包含：

```text
filesystem path

API response details

credential fragments

internal endpoints
```

所以应该：

```text
Internal diagnostic data
≠
User-facing message
```

内部：

```text
source_type
source_message
metadata
cause chain
```

用户：

```text
Model temporarily unavailable.
Retrying...
```

GitHub Copilot SDK 当前也明确建议既保留错误日志，又提供友好的用户消息，并按错误 Context 分类处理。

---

# 十六、RecoveryAction 是今天真正让 Error Model 发挥作用的地方

建议第一版：

```python
class RecoveryAction(str, Enum):
    RETRY = "retry"

    REREAD_AND_REGENERATE = (
        "reread_and_regenerate"
    )

    RETRIEVE_MORE_CONTEXT = (
        "retrieve_more_context"
    )

    COMPACT_CONTEXT = "compact_context"

    REPAIR = "repair"

    REPLAN = "replan"

    ASK_USER = "ask_user"

    PAUSE = "pause"

    STOP = "stop"
```

以后还可以：

```text
SWITCH_MODEL
ROLLBACK
RECREATE_WORKTREE
```

但今天先别膨胀。

---

# 十七、Retry、Repair、Replan 是三个完全不同的动作

这个一定要掌握。

## Retry

```text
再执行同一个动作
```

例如：

```text
Model 503
↓
等待
↓
重新发送相同请求
```

---

## Repair

```text
当前计划没问题，
但实现没达到验证要求
```

例如：

```text
pytest assertion failed
↓
分析失败
↓
修改代码
```

---

## Replan

```text
新 Evidence 证明当前执行方向本身错了
```

例如：

```text
计划认为 timeout 在 auth.py

实际发现 network proxy 才是根因

→ REPLAN
```

所以：

```text
Retry
=
same action


Repair
=
new implementation attempt


Replan
=
new execution strategy
```

---

# 十八、还有第四种：Reread + Regenerate

例如：

```text
Patch Context Mismatch
```

意味着：

```text
LLM 生成 Patch 时看到的文件版本
和
当前 Workspace
不一致
```

你不应该：

```text
Retry same patch
```

因为大概率：

```text
永远 mismatch
```

也不一定要：

```text
Replan entire task
```

正确：

```text
重新读取文件
↓
基于当前内容
重新生成 Patch
```

也就是：

```text
REREAD_AND_REGENERATE
```

这正是 Domain Error Model 的价值。

---

# 十九、第五种：Ask User

例如：

```text
Task:
删除旧认证接口
```

但是：

```text
代码里有两个“旧接口”
TaskSpec 无法确定是哪一个
```

这不是：

```text
Retry
```

也不是：

```text
Repair
```

更合理：

```text
ASK_USER
```

所以 Recovery 系统最终解决的是：

```text
机器下一步应该怎么推进 Task
```

而不是单纯：

```text
要不要重试 Exception
```

---

# 二十、Retryable 到底怎么定义

建议：

> 在**不改变输入语义、不要求额外用户决策，并且不会产生不可接受重复副作用**的前提下，重复执行当前操作具有合理成功概率。

例如：

```text
503 overloaded
→ retryable
```

OpenAI 当前错误文档明确建议对 500/503 等情况短暂等待后 Retry，而临时 rate-limit 应遵循 `Retry-After` 或使用指数退避；但 quota、billing、spend-limit 等错误不是 Retry 能解决的。

---

# 二十一、Transient 是什么

Transient：

> Failure 的根本原因可能无需修改 Task/Code/Configuration，仅随时间或外部系统恢复而消失。

典型：

```text
temporary rate limit

provider overload

temporary connection failure
```

Permanent：

```text
invalid credentials

invalid model name

policy deny

missing required configuration
```

但“Permanent”通常是：

```text
relative于当前 Runtime State
```

例如：

```text
invalid credentials
```

用户更新配置以后当然能恢复。

所以更精确：

> **Current State 下自动等待不会恢复。**

---

# 二十二、OpenAI Rate Limit 是最典型的工业 Retry Example

OpenAI 当前官方建议对临时 rate limit 优先使用 `Retry-After`；如果没有有效 Header，则使用 exponential backoff + jitter，并同时限制重试次数和总 Retry 时间。官方 SDK 对符合条件的限流错误本身也会自动 Retry，因此应用层还要避免和 SDK Retry 叠加造成 Retry Explosion。

这一段对你的 `RetryPolicy` 设计非常重要。

---

# 二十三、什么是 Exponential Backoff

最简单：

```text
base_delay = 1s
```

第几次失败：

```text
attempt 0
1s

attempt 1
2s

attempt 2
4s

attempt 3
8s

attempt 4
16s
```

公式可以理解为：

```text
delay
=
min(
    max_delay,
    base_delay × 2^attempt
)
```

为什么？

如果 Server 已经拥塞：

```text
Retry instantly
Retry instantly
Retry instantly
```

只会继续加剧拥塞。

---

# 二十四、为什么还需要 Jitter

假设：

```text
10,000 个 Agent
```

同时收到：

```text
429
```

大家严格：

```text
1 秒后 Retry
```

结果：

```text
1 秒以后
10,000 个请求再次同时打过去
```

叫：

```text
Thundering Herd
```

所以加随机：

```text
1.0 ~ 1.5s
```

让请求错开。

OpenAI 当前官方 rate-limit 文档也明确建议在 `Retry-After` 基础上加入小的随机延迟，缺少 Header 时使用 exponential backoff with jitter。

---

# 二十五、我推荐的 Retry Delay 逻辑

概念：

```text
if retry_after exists:
    delay =
        max(retry_after, calculated_backoff)
        + small_jitter

else:
    delay =
        exponential_backoff_with_jitter
```

不过这里具体选：

```text
Full Jitter
Equal Jitter
Decorrelated Jitter
```

Day 3 不值得过度展开。

第一版：

```text
exponential + random jitter
```

足够。

---

# 二十六、Retry Policy 不能只设置 `max_attempts`

建议：

```python
class RetryPolicy(BaseModel):
    max_attempts: int = 3

    base_delay_seconds: float = 1.0

    max_delay_seconds: float = 30.0

    jitter: bool = True

    max_total_delay_seconds: float = 60.0
```

为什么还要：

```text
max_total_delay_seconds
```

因为：

```text
attempt count
```

并不能控制：

```text
总等待时间
```

---

# 二十七、Retry Budget 应该分层

后面成熟一点：

```text
Per Operation

Per Plan Step

Per Task

Per Session
```

例如：

```text
Model Call
最多 Retry 3 次

但整个 Task
最多经历 10 个 provider retries
```

避免：

```text
20 个 PlanStep
×
每个 3 次

=
60 次 Retry
```

---

# 二十八、Retry Storm 是一个值得记录的 Failure Case

假设：

```text
Model SDK
内部 Retry 3 次
```

你的 ProviderClient：

```text
又 Retry 3 次
```

Orchestrator：

```text
再 Retry 3 次
```

实际上最坏：

```text
3 × 3 × 3
```

可能形成大量请求。

OpenAI 当前文档明确提醒，如果添加 application-level Retry，要考虑 SDK 已有的 Retry。

所以：

> **Retry Ownership 必须明确。**

---

# 二十九、我建议 CodeTeam 的 Retry Ownership

未来最好：

```text
HTTP/SDK
负责：
最底层短暂 transport retry


Provider Adapter
负责：
统一 Provider Error


Agent Runtime RetryPolicy
负责：
是否进行 Task-level Retry
```

但是：

```text
Runtime
```

必须知道：

```text
底层已经 Retry 过多少次
```

至少 Event 中要记录。

---

# 三十、Fail Fast 是什么

Fail Fast：

> **一旦确认当前操作无法通过自动恢复解决，就尽快停止继续浪费资源。**

例如：

```text
MODEL_AUTH_FAILED
```

不要：

```text
retry 5 times
```

直接：

```text
STOP
```

然后告诉用户：

```text
Provider authentication failed.
```

---

# 三十一、哪些错误特别适合 Fail Fast

例如：

```text
invalid task input

invalid provider config

invalid model ID

authentication failure

policy deny

corrupted session manifest

cross-task checkpoint
```

这些：

```text
等待 1 秒
```

不会自动恢复。

---

# 三十二、Fail Closed 是什么

Fail Closed：

> **当安全控制无法确认允许时，默认禁止产生副作用。**

这跟：

```text
Fail Fast
```

不是一回事。

例如：

```text
Sandbox unavailable
```

可能技术上：

```text
稍后 Retry Docker daemon
```

但安全策略：

```text
绝对不能 fallback Host Runner
```

即：

```text
SANDBOX_UNAVAILABLE
→ STOP
```

或：

```text
PAUSE / WAIT
```

但：

```text
绝不能：
“Sandbox 坏了，先裸机执行。”
```

---

# 三十三、Fail Fast vs Fail Closed

可以这样记：

```text
Fail Fast
=
别浪费时间。


Fail Closed
=
别越过安全边界。
```

它们可能同时发生。

例如：

```text
POLICY_DENIED
```

既：

```text
Fail Fast
```

也：

```text
Fail Closed
```

---

# 三十四、现在建立今天最重要的 Recovery Matrix

我建议 CodeTeam 第一版明确成这样：

| Failure | Category | Transient | Retryable | Recovery |
|---|---|---:|---:|---|
| Model rate limit | MODEL | Yes | Yes | RETRY |
| Model overload/503 | MODEL | Yes | Yes | RETRY |
| Model timeout | MODEL | Often | Often | RETRY |
| Invalid API key | MODEL | No | No | STOP |
| Context overflow | CONTEXT | No | No* | COMPACT_CONTEXT |
| Insufficient context | CONTEXT | No | No | RETRIEVE_MORE_CONTEXT |
| Patch context mismatch | PATCH | No | No | REREAD_AND_REGENERATE |
| Invalid patch | PATCH | No | No | REGENERATE / REPAIR |
| Test assertion fail | TEST | No | No | REPAIR |
| Test flaky suspected | TEST | Mixed | Limited | controlled rerun |
| Tool executable missing | TOOL | No | No | STOP / environment recovery |
| Tool process temporary timeout | TOOL | Maybe | Context-dependent | CLASSIFY |
| Policy denied | SECURITY | No | **No** | STOP |
| Approval denied | SECURITY | No | **No** | STOP |
| Sandbox unavailable | SECURITY | Maybe | **No automatic bypass** | STOP/PAUSE |
| Worktree conflict | GIT | Depends | Usually no blind retry | RECOVER |
| Session corrupted | SESSION | No | No | STOP / recovery |
| Ctrl+C | USER_INTERRUPT | — | No | PAUSE |

其中：

```text
Context overflow
```

标 `No*` 是因为：

> 不应该 Retry **完全相同的 Model Call**；应该先改变 Context，再重新尝试。

这和普通 Retry 有本质区别。

---

# 三十五、今天要求：Rate Limit → Retry

这是最标准 Case。

流程：

```text
Provider
↓
429 temporary rate limit
↓
Provider Adapter
↓
MODEL_RATE_LIMIT
↓
ErrorClassifier
↓
RecoveryAction.RETRY
↓
RetryPolicy
↓
Backoff + Jitter
↓
Model call again
```

OpenAI 当前明确提供 `Retry-After` 等 Rate Limit Metadata，并建议临时限制采用退避；GitHub Copilot SDK 当前也直接提供“recoverable model error → retryCount”的 Error Hook 示例。

---

# 三十六、Model Timeout → Retry，要加一个限定

你要求：

```text
timeout → retry
```

这里 Day 3 建议明确为：

```text
MODEL_TIMEOUT
→ RETRY
```

而不是：

```text
所有 TimeoutError
→ RETRY
```

例如：

```text
TEST_TIMEOUT
```

可能代表：

```text
Agent 写出了死循环
```

这时候 Blind Retry：

```text
pytest
pytest
pytest
```

不会解决任何问题。

---

# 三十七、所以 Timeout 是今天最佳教学例子

同一个：

```text
Timeout
```

三种 Context：

```text
Model request timeout
→ RETRY


Test timeout
→ DIAGNOSE / REPAIR


Sandbox control timeout
→ STOP / recovery
```

所以你的 ErrorClassifier 必须看：

```text
stage
```

不能只看：

```text
type(exception)
```

---

# 三十八、Patch Mismatch → Reread / Regenerate

例如：

```text
git apply --check
```

返回：

```text
patch does not apply
```

可能原因：

```text
文件从 Planner 读取后又改变了

LLM Patch Context 错

前一个 Attempt 已修改同一段
```

错误：

```text
retry same patch
```

正确：

```text
PATCH_CONTEXT_MISMATCH
↓
REREAD current file
↓
retrieve current symbols
↓
regenerate patch
```

这就是：

```text
Recovery Policy
```

不是：

```text
Retry Policy
```

---

# 三十九、Test Fail → Repair

Day 2 已经讲过：

```text
pytest exit 1
```

说明：

```text
VerificationResult.FAILED
```

如果 Oracle 可信：

```text
Agent 当前 Candidate
还不满足行为要求。
```

所以：

```text
TEST_FAILED
→ REPAIR
```

不是：

```text
RETRY test
```

区别：

```text
Retry:
什么都不改再跑一次

Repair:
修改实现以后再验证
```

---

# 四十、Policy DENY → No Retry

这是今天最重要的 Security Invariant。

```text
POLICY_DENIED
```

必须：

```text
retryable = False
recovery_action = STOP
```

绝不能：

```text
Agent:
“刚才 git reset --hard 被拒绝，
换种写法再试试。”
```

否则 Agent 会把：

```text
Security Policy
```

当作：

```text
需要绕过的障碍
```

---

# 四十一、这条最好做成硬代码规则

例如：

```text
ErrorCategory.SECURITY

如果：
POLICY_DENIED

→
RecoveryAction.STOP
```

不要让：

```text
LLM Error Diagnosis
```

决定：

```text
是否再试。
```

安全判断应该由：

```text
Trusted Runtime
```

执行。

---

# 四十二、Approval Denied → Stop

这和 Policy Deny 有一点不同：

```text
POLICY_DENIED
=
Runtime 不允许


APPROVAL_DENIED
=
用户明确不允许
```

两者：

```text
都不能自动 Retry。
```

尤其 Approval Denied 后：

```text
Agent 换一条效果相同的 Command
试图规避用户拒绝
```

也应该警惕。

---

# 四十三、Anthropic 当前 Permission Event 很能说明这一点

Claude Code Hook 当前明确把 `PermissionDenied` 看作“Denial 已经发生”的 Event；默认情况下，不是简单靠 Exit Code重新执行。其 Hook 协议甚至有明确的 Retry 信号语义，而不是把所有 Permission Failure 当作普通 Tool Error。

这体现：

```text
Authorization Failure
≠
Operational Failure
```

---

# 四十四、Sandbox Unavailable → Stop

例如：

```text
Docker daemon unavailable
```

错误做法：

```text
Docker failed
↓
fallback
↓
Host CommandRunner
```

正确：

```text
SANDBOX_UNAVAILABLE
↓
Fail Closed
↓
STOP / PAUSE
```

可以让用户：

```text
恢复 Docker 后 resume
```

但不能降低安全边界。

---

# 四十五、Ctrl+C → PAUSED

这是一个特别容易误分类的场景。

用户：

```text
Ctrl+C
```

不是：

```text
ERROR
```

而是：

```text
USER_INTERRUPT
```

下一步：

```text
Cancel active execution
↓
Persist current Task
↓
TaskStatus.PAUSED
```

Claude Code 当前交互模式同样明确区分用户中断：`Esc` 可以在当前 response/tool call 中途停止，然后用户重新引导，而且已经完成的工作会保留。

所以：

> **Cancellation 是 Runtime Control Flow，不应该伪装成普通 Exception Failure。**

---

# 四十六、为什么 `KeyboardInterrupt` 不能被 `except Exception` 吞掉

Python 中实际类型层次你可以自己确认，但从 Runtime Design 看：

```text
Ctrl+C
```

的语义是：

```text
User intentionally requested interruption
```

所以它应该在最外层明确：

```text
catch interrupt
↓
cancel children
↓
persist
↓
PAUSED
```

而不是：

```text
retry active operation
```

---

# 四十七、推荐的 `ErrorClassifier`

职责应该非常窄：

```text
Raw Failure
+
Stage
+
Operation Context

→

AgentFailure
```

不应该：

```text
sleep

retry

rollback

call model
```

那些属于：

```text
Recovery Executor / Orchestrator
```

---

# 四十八、推荐职责分离

```text
Exception / Result
        │
        ▼
  ErrorClassifier
        │
        ▼
   AgentFailure
        │
        ▼
 RecoveryPolicy
        │
        ▼
 RecoveryAction
        │
        ▼
 SingleAgentOrchestrator
        │
   execute recovery
```

而不是：

```text
ErrorClassifier
自己重试
```

---

# 四十九、那为什么 `AgentFailure` 还可以带 `recovery_action`

两种设计都成立：

### A

```text
Classifier
→ Failure

Policy
→ Action
```

职责最干净。

### B

```text
Classifier
→ Failure + recommended action
```

第一版代码简单。

我建议：

```text
AgentFailure
保存 recommended_recovery
```

但真正：

```text
执行 Recovery
```

仍由 Orchestrator。

以后如果 Policy 复杂，再独立：

```text
RecoveryPolicy
```

---

# 五十、`RecoveryPolicy` 是什么

它可以理解成：

```text
if MODEL_RATE_LIMIT:
    RETRY

if CONTEXT_INSUFFICIENT:
    RETRIEVE_MORE_CONTEXT

if PATCH_CONTEXT_MISMATCH:
    REREAD_AND_REGENERATE

if TEST_FAILED:
    REPAIR

if POLICY_DENIED:
    STOP
```

但不要散落在 20 个 `except` 里。

---

# 五十一、今天 Design Decision 的核心就在这里

## 方案 A：Scattered Exception Handling

例如：

```python
# planner.py
except TimeoutError:
    ...

# repair.py
except TimeoutError:
    ...

# provider.py
except TimeoutError:
    ...

# session.py
except Exception:
    ...
```

几个月以后你会发现：

```text
同一个 Failure
不同模块有不同语义
```

---

# 五十二、方案 B：Typed Domain Failure

所有底层：

```text
Provider exception
Git error
Patch result
Verification result
Security decision
```

被规范化成：

```text
AgentFailure
```

Orchestrator：

```text
只理解 Domain Failure
```

这是今天推荐方案。

---

# 五十三、为什么 Typed Error 属于 Domain Model

因为：

```text
PATCH_CONTEXT_MISMATCH
```

不是 Python 的概念。

```text
TEST_FAILED
```

不是 OS 的概念。

```text
APPROVAL_DENIED
```

不是 HTTP 的概念。

它们都是：

> **CodeTeam Agent Runtime 世界里的业务语义。**

就像电商系统有：

```text
ORDER_NOT_PAYABLE
```

数据库系统有：

```text
TRANSACTION_CONFLICT
```

你的 Agent Runtime 有：

```text
PATCH_CONTEXT_MISMATCH
MODEL_RATE_LIMIT
POLICY_DENIED
```

因此它们属于 Domain Model。

---

# 五十四、Typed Failure 带来的最大价值之一：Provider Neutral

例如 OpenAI Provider：

```text
HTTP 429
```

另一个 Provider：

```text
RateLimitException
```

都转成：

```text
MODEL_RATE_LIMIT
```

AgentLoop：

```text
完全不用知道供应商差异。
```

这和你后面：

```text
Provider Switching
```

直接相关。

---

# 五十五、工业界的 GitHub Copilot SDK 就明显体现这个思路

Copilot SDK 当前的 Error Hook 并不是让用户直接根据任意底层 Exception 自己猜，而提供类似：

```text
errorContext

recoverable

errorType
```

等 Runtime-level 信息，让应用决定 Retry、通知用户还是 graceful shutdown。

你的：

```text
AgentFailure
+
RecoveryAction
```

本质上是在自己 Agent Harness 中实现更细粒度版本。

---

# 五十六、ErrorClassifier 不应完全由 LLM 实现

非常重要。

例如：

```text
POLICY_DENIED
```

如果让 LLM 判断：

```text
“这个 Error 是否 Retryable？”
```

模型可能说：

```text
“可以尝试换一种命令。”
```

这会破坏 Security Boundary。

因此分类应该分两层：

```text
Deterministic Classification
+
Optional semantic diagnosis
```

---

# 五十七、哪些应该 Deterministic

例如：

```text
HTTP 429
→ MODEL_RATE_LIMIT

PatchValidator mismatch
→ PATCH_CONTEXT_MISMATCH

PolicyDecision.DENY
→ POLICY_DENIED

ApprovalDecision.DENIED
→ APPROVAL_DENIED

VerificationStatus.FAILED
→ TEST_FAILED

KeyboardInterrupt
→ USER_INTERRUPT
```

这些不需要 LLM。

---

# 五十八、LLM 可以帮助什么

例如 Test Failed：

```text
TEST_FAILED
```

已经由 Runtime 确定。

模型可以分析：

```text
为什么失败？

可能是哪段代码的问题？

应该 Repair 还是 Replan？
```

但模型不应该重新定义：

```text
“其实这个 test failure 可以忽略。”
```

除非 Runtime/用户允许。

所以：

```text
Classification
=
Trusted Runtime


Diagnosis
=
Model-assisted
```

这是非常好的分层。

---

# 五十九、建议把 Error Handling 分成 3 层

```text
Layer 1
Detection

发生了什么？


Layer 2
Classification

这在 Agent Domain 中是什么？


Layer 3
Recovery

下一步做什么？
```

例子：

```text
Detection:
HTTP 429

Classification:
MODEL_RATE_LIMIT

Recovery:
RETRY with backoff
```

---

# 六十、另一个例子

```text
Detection:
git apply --check failed

Classification:
PATCH_CONTEXT_MISMATCH

Recovery:
REREAD_AND_REGENERATE
```

---

# 六十一、再一个

```text
Detection:
pytest exit code 1

Classification:
TEST_FAILED

Recovery:
REPAIR
```

这个三层模型特别重要。

---

# 六十二、Retry Policy 的代码职责

建议：

```text
RetryPolicy
```

负责回答：

```text
现在还能不能 Retry？

应该等多久？
```

不负责：

```text
这个错误是什么
```

---

# 六十三、概念接口

```python
class RetryDecision(BaseModel):
    should_retry: bool

    delay_seconds: float | None

    attempt: int

    reason: str
```

然后：

```python
decision = retry_policy.decide(
    failure,
    attempt=2,
)
```

---

# 六十四、RetryPolicy 要考虑哪些输入

至少：

```text
failure.retryable

attempt

max_attempts

Retry-After

elapsed retry time
```

以后：

```text
operation idempotency

task budget

provider retry metadata
```

---

# 六十五、不要 `time.sleep()` 写死在 Policy

Policy 负责：

```text
算 delay
```

执行器负责：

```text
等待
```

为什么？

因为 Unit Test：

```text
不应该真的等：
1s
2s
4s
8s
```

你需要：

```text
FakeClock / Sleeper
```

或让 Orchestrator 注入：

```text
sleep function
```

---

# 六十六、今天测试 Rate Limit 不应该真的打爆 API

正确：

```text
Fault Injection
```

例如：

```text
FakeModelClient

call 1:
raise rate limit

call 2:
success
```

验证：

```text
retry_count == 1

sleep called once

event emitted

最终成功
```

不要真实：

```text
疯狂发 API 请求
```

制造 429。

---

# 六十七、Fault Injection 是今天 Benchmark 的核心手段

你要求：

```text
50 error cases
```

非常适合构造一个：

```text
Fault Injection Corpus
```

每个 Case：

```text
input failure

stage

expected category

expected code

expected recovery action
```

---

# 六十八、建议建立 `FailureCase`

例如：

```python
@dataclass(frozen=True)
class FailureCase:
    case_id: str

    stage: FailureStage

    raw_error: object

    expected_category: ErrorCategory

    expected_code: AgentErrorCode

    expected_action: RecoveryAction

    expected_retryable: bool
```

然后：

```text
50 cases
```

全部 data-driven test。

---

# 六十九、50 个 Fault Case 怎么分

建议：

```text
MODEL       10
CONTEXT      6
PATCH        7
TOOL         6
SECURITY     6
TEST         5
GIT          4
SESSION      4
INTERRUPT    2
----------------
TOTAL       50
```

这样不是 50 个重复 Timeout。

---

# 七十、MODEL 10 Cases 示例

例如：

```text
M01 temporary rate limit
M02 Retry-After rate limit
M03 provider overload
M04 model timeout
M05 connection reset
M06 auth invalid
M07 quota exceeded
M08 invalid model
M09 context overflow
M10 malformed provider response
```

注意：

```text
M09
```

虽然 API 层发生于 Model，

在你的 Domain 中也可以分类成：

```text
CONTEXT
```

取决于你决定的 Ownership。

这就是需要 Design Decision 的地方。

---

# 七十一、我更推荐 Context Overflow 属于 CONTEXT

因为：

```text
RecoveryAction
=
COMPACT_CONTEXT
```

它主要是：

```text
Context Management Problem
```

而不是：

```text
Provider Availability Problem
```

即使底层 Exception 来自模型 API。

这进一步体现：

> Domain Category 不等于底层 Exception Origin。

---

# 七十二、CONTEXT Cases

例如：

```text
C01 token budget exceeded
C02 insufficient relevant files
C03 stale file content
C04 important symbol missing
C05 compact summary missing constraint
C06 model context overflow
```

Recovery：

```text
RETRIEVE_MORE_CONTEXT

REREAD

COMPACT_CONTEXT
```

而不是 Retry same call。

---

# 七十三、PATCH Cases

例如：

```text
P01 syntax invalid patch
P02 context mismatch
P03 forbidden path
P04 absolute path
P05 binary patch rejected
P06 too many files
P07 apply precondition changed
```

注意：

```text
P03/P04
```

其实可能也是：

```text
SECURITY
```

但我建议保留：

```text
PATCH
```

Category，

然后：

```text
retryable=False
```

避免模型重复尝试 Escape。

---

# 七十四、TOOL Cases

例如：

```text
T01 executable missing

T02 start permission error

T03 process timeout

T04 non-zero exit

T05 malformed tool result

T06 sandbox control command failed
```

其中：

```text
non-zero exit
```

不能单凭这个就映射一个 Recovery。

因为：

```text
pytest exit 1
```

属于：

```text
TEST_FAILED
```

而：

```text
rg exit 1
```

可能只是：

```text
no match
```

所以 Tool Wrapper 应该尽量先做：

```text
Tool-specific interpretation
```

再交给 ErrorClassifier。

---

# 七十五、这是另一个重要原则：Exit Code ≠ Error Meaning

例如：

```text
rg
exit 1
```

通常代表：

```text
no matches
```

不是 Runtime Failure。

而：

```text
pytest
exit 1
```

通常意味着测试失败。

所以：

```text
CommandResult
```

不应该直接变：

```text
AgentFailure
```

中间应该经过：

```text
Tool / Verification semantic layer
```

Day 2 已经开始这样设计。

---

# 七十六、SECURITY Cases

至少：

```text
S01 Policy DENY
S02 Approval DENIED
S03 Approval expired
S04 Cross-task grant
S05 Sandbox unavailable
S06 Sandbox violation
```

我建议：

```text
全部：
automatic retry = False
```

因为安全相关 Error 应该优先：

```text
Fail Closed
```

---

# 七十七、TEST Cases

例如：

```text
V01 assertion failure
V02 regression failure
V03 timeout
V04 flaky suspected
V05 oracle inconsistency
```

Recovery：

```text
REPAIR

REPAIR

CLASSIFY/REPAIR

controlled retry or ASK_USER

ASK_USER / INCONCLUSIVE
```

---

# 七十八、GIT Cases

例如：

```text
G01 worktree conflict

G02 branch already checked out

G03 dirty worktree removal

G04 base SHA missing
```

这些大多数：

```text
不适合 Blind Retry
```

需要：

```text
reconcile state
```

以后可以新增：

```text
RECOVER_WORKSPACE
```

第一版可以：

```text
STOP
```

并记录清楚。

---

# 七十九、SESSION Cases

例如：

```text
SESSION_NOT_FOUND
```

→ STOP

```text
SESSION_CORRUPTED
```

→ STOP / recover metadata

```text
WORKTREE_MISSING
```

→ recovery required

```text
CHECKPOINT_MISSING
```

→ STOP / ask user

这些后面 Day 4 会重点完善。

---

# 八十、USER_INTERRUPT

Case：

```text
KeyboardInterrupt

Esc-like user cancel
```

应该：

```text
USER_INTERRUPT
↓
PAUSE
```

而不是：

```text
FAILED
```

除非用户明确：

```text
cancel permanently
```

---

# 八十一、今天测试 1：Rate Limit → Retry

用 FakeModel：

```text
Call 1
MODEL_RATE_LIMIT

Call 2
success
```

断言：

```text
classification:
MODEL / RATE_LIMIT

action:
RETRY

retry policy:
called

orchestrator:
最终继续
```

---

# 八十二、测试 2：Model Timeout → Retry

仍然 Fake。

不要真正让测试等待几十秒。

```text
MODEL_CALL stage
+
Timeout
```

expected：

```text
MODEL_TIMEOUT

retryable=True

RETRY
```

---

# 八十三、测试 3：Patch mismatch

输入：

```text
PatchValidator result:
context mismatch
```

预期：

```text
PATCH_CONTEXT_MISMATCH

retryable=False

action:
REREAD_AND_REGENERATE
```

强不变量：

```text
same patch apply call
不能再执行。
```

---

# 八十四、测试 4：Test Fail

输入：

```text
VerificationStatus.FAILED
```

预期：

```text
TEST_FAILED

action:
REPAIR
```

并且：

```text
RetryPolicy
不应该被调用。
```

---

# 八十五、测试 5：Policy DENY

```text
PolicyDecision.DENY
```

预期：

```text
POLICY_DENIED

retryable=False

STOP
```

另外最好断言：

```text
Model 不被再次要求：
“换一种命令”
```

---

# 八十六、测试 6：Approval DENIED

预期：

```text
APPROVAL_DENIED

STOP
```

且：

```text
Runner = 0

Retry = 0
```

这是 Week 3 Security Regression 应继续存在的 Invariant。

---

# 八十七、测试 7：Sandbox unavailable

预期：

```text
SANDBOX_UNAVAILABLE

STOP
```

最重要：

```text
HostRunner calls = 0
```

也就是：

```text
Fail Closed
```

---

# 八十八、测试 8：Ctrl+C

模拟：

```text
UserInterrupt
```

预期：

```text
TaskStatus
→ PAUSED

Session persistence hook
→ called

Retry
→ 0
```

后续 Day 4 真正保存 Session。

---

# 八十九、我建议额外加 10 条重点测试

### T09

```text
Invalid API Key
→ STOP
```

---

### T10

```text
Quota exceeded
→ STOP
```

OpenAI 当前明确指出 billing/quota 类错误不是不断 Retry 可以解决的。

---

### T11

```text
Context overflow
→ COMPACT_CONTEXT
```

不是：

```text
same request retry
```

---

### T12

```text
Insufficient retrieval
→ RETRIEVE_MORE_CONTEXT
```

---

### T13

```text
Test timeout
→ 不自动映射 MODEL_TIMEOUT Retry
```

---

### T14

```text
Repeated security failure
→ still STOP
```

不能因为 attempt 改变。

---

### T15

```text
Retry max exhausted
→ STOP
```

---

### T16

```text
Retry-After provided
→ delay respects it
```

---

### T17

```text
Original exception/cause preserved
```

---

### T18

```text
User-facing message sanitized
```

不泄漏 Secret。

---

# 九十、ErrorClassifier 的 Unit Test 和 Recovery 的 Integration Test 要分开

## Unit

```text
raw failure
→ expected AgentFailure
```

例如：

```text
429
→ MODEL_RATE_LIMIT
```

---

## Integration

```text
AgentFailure
→ RecoveryAction
→ Orchestrator actually does it
```

例如：

```text
MODEL_RATE_LIMIT
→ wait
→ second model call
```

不能只测：

```python
assert action == RETRY
```

然后 Orchestrator 实际没 Retry。

---

# 九十一、Benchmark 1：Classification Accuracy

50 Case Corpus：

```text
expected category/code
vs
actual category/code
```

计算：

```text
Classification Accuracy
=
correct cases / 50
```

但我建议：

```text
Category Accuracy

Code Accuracy
```

分开。

因为：

```text
MODEL
```

对了，

但：

```text
RATE_LIMIT
```

误判成：

```text
AUTH_FAILED
```

仍然可能导致错误 Recovery。

---

# 九十二、最好增加 Confusion Matrix

例如：

| Expected | MODEL | CONTEXT | PATCH | TEST | SECURITY |
|---|---:|---:|---:|---:|---:|
| MODEL | | | | | |
| CONTEXT | | | | | |
| PATCH | | | | | |
| TEST | | | | | |
| SECURITY | | | | | |

看看：

```text
哪些 Error 最容易被混淆。
```

尤其：

```text
TOOL
vs
TEST
```

和：

```text
MODEL
vs
CONTEXT
```

很可能容易混。

---

# 九十三、Benchmark 2：Correct Recovery Action

这比 Classification Accuracy 更重要。

定义：

```text
Recovery Accuracy
=
expected action == actual action
```

因为即使 Category 错一点，

但：

```text
最终 Recovery 正确
```

实际影响可能不大。

反过来：

```text
Category 对
Recovery 错
```

系统还是坏。

---

# 九十四、Benchmark 3：Unnecessary Retry Count

定义：

> 对明确 Non-retryable Error 发起的 Retry 次数。

例如：

```text
POLICY_DENIED
→ retry
```

就是 1 次。

目标：

```text
0
```

这尤其能体现 Typed Recovery 比：

```text
Generic Retry
```

的价值。

---

# 九十五、建议再加一个指标：Unsafe Retry Count

比 unnecessary retry 更严重：

```text
Security errors

User denial

Unknown remote-write outcomes
```

被自动 Retry 的数量。

Acceptance：

```text
0
```

---

# 九十六、再加一个：Recovery Success Rate

例如 transient fault cases：

```text
Rate Limit
503
Connection reset
```

在允许 Retry 后：

```text
多少最终自动恢复。
```

定义：

```text
recovered transient cases
/
retryable transient cases
```

---

# 九十七、Benchmark 不要真的故障 50 次外部系统

全部：

```text
Fault Injection
```

最好。

例如：

```text
FakeModelClient

FakePatchValidator

FakeVerificationService

FakeSandboxRunner
```

由 Harness：

```text
在第 N 次调用
注入指定 Failure
```

这样：

```text
可复现
快速
CI 稳定
```

---

# 九十八、Failure Injection 的工业价值

你不是为了测试：

```text
“公网今天会不会真的 503”
```

而是在验证：

```text
“如果 Provider 503，
我的 Runtime 怎么做？”
```

因此 deterministic injection 比真实外部故障更适合作为回归测试。

---

# 九十九、Ablation：Typed Recovery vs Generic Retry

这是今天最有价值的实验。

## Full

```text
Failure
↓
Classification
↓
Recovery Policy
↓
Retry / Repair / Replan / Stop
```

---

## Ablation

```text
Exception
↓
retry up to N times
```

---

# 一百、设计一组相同 Failure Corpus

例如：

```text
10 transient

10 patch

10 verification

10 security

10 permanent
```

两个系统都跑。

记录：

```text
Task success

Total attempts

Unnecessary retries

Unsafe retries

Wall time

Tool calls
```

---

# 一百零一、你很可能看到的现象，但现在不能提前宣称结果

Generic Retry 理论上容易在：

```text
Rate Limit
```

有效。

但对于：

```text
Patch mismatch

Test fail

Policy deny

Invalid credentials
```

没有改变任何导致 Failure 的 State，

因此重试很可能：

```text
重复同一个失败。
```

这是实验假设。

必须跑数据以后再写：

```text
SUPPORTED
```

---

# 一百零二、今天 Design Decision 建议这样写

```text
DD-W4-D3-01

Title:
Typed Domain Error Recovery

Problem:
How should CodeTeam react to
heterogeneous runtime failures?

Alternative A:
Handle exceptions locally with
module-specific try/except and retries.

Alternative B:
Normalize failures into a shared
AgentFailure domain model and map
them to explicit RecoveryAction.

Decision:
B

Rationale:
- consistent recovery semantics
- provider independence
- observability
- deterministic security handling
- measurable retry behavior
- easier fault injection
- supports session persistence

Trade-offs:
- more domain types
- mapping maintenance
- misclassification risk

Evidence Status:
PROPOSED
```

---

# 一百零三、Failure Case 1：错误分类错

例如：

```text
Invalid API key
```

误分类：

```text
MODEL_TIMEOUT
```

Runtime：

```text
Retry 3 次
```

结果：

```text
浪费时间
浪费请求
用户等待
```

---

# 一百零四、严重一点的 Misclassification

例如：

```text
POLICY_DENIED
```

误分类：

```text
TOOL_FAILED
```

然后：

```text
RETRY
```

这就不只是效率问题，

而是：

```text
Security Bug
```

所以：

```text
SECURITY Category
```

相关分类必须拥有最高测试优先级。

---

# 一百零五、Failure Case 2：Transient 被判断 Permanent

例如：

```text
temporary 503
```

被：

```text
STOP
```

结果：

```text
Task unnecessarily fails
```

降低：

```text
Task Success Rate
```

这类错误主要影响：

```text
availability
```

---

# 一百零六、Failure Case 3：Permanent 无限 Retry

例如：

```text
invalid credential
```

Retry：

```text
1
2
4
8
16
...
```

等待再久：

```text
API key 仍然错。
```

所以：

```text
Retry Budget
```

只是一道兜底。

真正关键还是：

```text
正确 Classification。
```

---

# 一百零七、Failure Case 4：原始 Exception 丢失

假设：

```text
MODEL_TIMEOUT
```

但底层其实：

```text
TLS certificate error
```

因为 ErrorMapper 粗暴把：

```text
所有 connection error
→ TIMEOUT
```

以后 Debug 时：

```text
完全不知道 root cause
```

所以：

```text
Domain Error
```

不能代替：

```text
Cause Chain
```

应该：

```text
wrap
not erase
```

---

# 一百零八、Failure Case 5：安全错误被自动 Retry

最重要：

```text
POLICY_DENIED
APPROVAL_DENIED
SANDBOX_VIOLATION
```

都必须：

```text
auto retry = false
```

尤其：

```text
“换个命令试试”
```

不能成为普通 Error Recovery。

---

# 一百零九、Failure Case 6：Timeout 全部统一 Retry

前面讲过：

```text
MODEL_TIMEOUT
→ retry

TEST_TIMEOUT
→ possibly repair

COMMAND_TIMEOUT
→ inspect

SANDBOX_TIMEOUT
→ fail closed/recover
```

如果统一：

```text
TimeoutError
→ retry
```

非常危险。

---

# 一百一十、Failure Case 7：Retry 没有 Backoff

例如：

```text
while retryable:
    request()
```

Provider Rate Limit 时：

```text
每毫秒继续请求
```

不仅恢复不了，

还可能进一步触发 Rate Limit。

OpenAI 当前明确指出失败请求同样会贡献 Rate Limit，持续不断重发不会奏效。

---

# 一百一十一、Failure Case 8：Backoff 没有 Jitter

大量 Worker：

```text
同时失败
同时 1 秒
同时 2 秒
同时 4 秒
```

持续同步冲击 Provider。

这就是为什么：

```text
jitter
```

很重要。

---

# 一百一十二、Failure Case 9：Retry 层级叠加

```text
SDK
×
Provider
×
Agent
```

全部 Retry。

导致：

```text
实际调用次数失控
```

解决：

```text
明确 Retry Ownership
+
记录 actual_attempts
```

---

# 一百一十三、Failure Case 10：Retry 有副作用

例如：

```text
remote write
```

第一次：

```text
Server success
Response lost
```

Runtime：

```text
timeout
→ retry
```

产生：

```text
duplicate side effect
```

所以未来：

```text
RetryPolicy
```

还必须考虑：

```text
Idempotency
```

---

# 一百一十四、Failure Case 11：Recovery 自己失败

例如：

```text
PATCH_CONTEXT_MISMATCH
↓
REREAD
```

结果：

```text
read file
又失败
```

这说明：

```text
Recovery Action
```

自身也是 Runtime Operation，

也可能产生：

```text
新的 AgentFailure。
```

所以不能假设：

```text
Recovery 一定成功。
```

---

# 一百一十五、Recovery Failure 不应该无限套娃

例如：

```text
failure
→ recover
→ failure
→ recover
→ failure
```

必须受到：

```text
Task Budget
Recovery Budget
```

限制。

否则 Error Handler 自己会进入：

```text
Recovery Loop
```

---

# 一百一十六、Failure Case 12：Unknown Error 被当 Retryable

成熟 Runtime 必须有：

```text
UNKNOWN
```

但推荐默认：

```text
retryable=False
```

或者非常保守地处理。

尤其涉及：

```text
Side Effect
Security
```

时应该：

```text
Fail Closed
```

不要：

```text
“不认识，那试一下。”
```

---

# 一百一十七、Unknown Error 的合理策略

```text
Unknown model-side read error
→ maybe limited retry

Unknown mutation error
→ inspect state before recovery

Unknown security error
→ stop
```

所以最终：

```text
Stage
```

仍然非常重要。

---

# 一百一十八、Error Event 应该记录什么

建议：

```text
error.detected

error.classified

recovery.decided

retry.scheduled

retry.started

retry.exhausted

recovery.started

recovery.completed

recovery.failed

task.paused
```

这样才能回答：

```text
这个 Task
为什么用了 8 分钟？
```

---

# 一百一十九、例如 Event Timeline

```text
10:00:00
model.call.started

10:00:04
model.call.failed
503

10:00:04
error.classified
MODEL_OVERLOADED

10:00:04
recovery.decided
RETRY

10:00:04
retry.scheduled
delay=1.34s

10:00:06
model.call.started
attempt=2

10:00:09
model.call.completed
```

这就是：

```text
Observability
```

---

# 一百二十、为什么 Error Metrics 会成为 Agent Evaluation 的重要部分

以后 15 Task：

你不仅知道：

```text
12/15 successful
```

还可以知道：

```text
失败 3 个：

1 context
1 patch
1 verification
```

再比如：

```text
成功任务中：
平均每 Task
0.7 model retry

0.4 repair
```

这样你才能真正优化 Agent。

---

# 一百二十一、今天建议的架构

最终应该接近：

```text
                    SingleAgentOrchestrator
                              │
                              ▼
                         Operation
                              │
                     ┌────────┴─────────┐
                     │                  │
                  SUCCESS             FAILURE
                                         │
                                         ▼
                                  ErrorClassifier
                                         │
                                         ▼
                                    AgentFailure
                                         │
                                         ▼
                                   RecoveryPolicy
                                         │
            ┌──────────────┬─────────────┼─────────────┐
            ▼              ▼             ▼             ▼
          RETRY          REPAIR        REPLAN         STOP
            │              │             │
            ▼              ▼             ▼
       RetryPolicy      Day2 Loop     Day1 Planner
            │
            ▼
       Backoff/Jitter

其它：
RETRIEVE_CONTEXT
COMPACT_CONTEXT
REREAD
ASK_USER
PAUSE
```

这三天已经开始真正组成一个 Runtime。

---

# 一百二十二、和 Day 1/2 的连接

Day 1：

```text
Plan
```

回答：

```text
应该做什么？
```

Day 2：

```text
Verification
```

回答：

```text
做得对不对？
```

Day 3：

```text
Error Classification
```

回答：

```text
不对以后怎么办？
```

因此：

```text
Plan
+
Verification
+
Recovery
```

才构成真正 Agent Loop。

---

# 一百二十三、推荐今天的代码结构

第一版不需要很复杂：

```text
codeteam/
└── errors/
    ├── models.py
    ├── classifier.py
    ├── recovery.py
    └── retry.py
```

或者项目还小：

```text
errors.py
retry.py
```

即可。

关键职责：

```text
models
→ Domain Types

classifier
→ Raw failure → AgentFailure

recovery
→ AgentFailure → Action

retry
→ Retry timing/budget
```

---

# 一百二十四、建议今天按 7 个 Step 实现

## Step 1：Error enums

先：

```text
ErrorCategory

AgentErrorCode

FailureStage

RecoveryAction
```

不写任何复杂逻辑。

---

## Step 2：AgentFailure

确定：

```text
cause preservation

retryable

transient

stage

recovery
```

的契约。

---

## Step 3：Deterministic ErrorClassifier

先覆盖今天 8 个验收：

```text
rate limit
model timeout
patch mismatch
test fail
policy deny
approval deny
sandbox unavailable
interrupt
```

---

## Step 4：RecoveryPolicy

明确：

```text
failure code
→ action
```

不要执行 Action。

---

## Step 5：RetryPolicy

实现：

```text
max attempts

exponential delay

jitter

Retry-After

total retry budget
```

Unit Test 不真实 sleep。

---

## Step 6：接 Orchestrator

例如：

```text
Model Error
↓
classify
↓
retry

Test Error
↓
repair

Patch Error
↓
reread

Interrupt
↓
pause
```

这一步才证明真正有价值。

---

## Step 7：50 Case Fault Injection

最后做：

```text
classification
recovery
benchmark
ablation
```

---

# 一百二十五、今天特别推荐先用 Deterministic Classifier

例如：

```text
OpenAIRateLimit
```

由 Provider Adapter 转：

```text
ProviderError.RATE_LIMIT
```

再由 CodeTeam：

```text
MODEL_RATE_LIMIT
```

不要调用：

```text
LLM:
“请判断这个 Exception 是什么。”
```

否则：

```text
错误分类本身
也变成不稳定模型输出。
```

---

# 一百二十六、LLM 应该放在哪里

例如：

```text
TEST_FAILED
```

Runtime 已分类。

之后：

```text
Repair Agent
```

可以用 LLM 判断：

```text
这次失败说明什么代码问题？
```

也就是：

```text
Classification
→ deterministic


Diagnosis
→ model-assisted
```

这会非常漂亮。

---

# 一百二十七、今天 Benchmark 推荐结果表

实际跑后填写：

| Case | Expected Code | Actual Code | Expected Action | Actual Action | Retries |
|---|---|---|---|---|---:|
| E01 | | | | | |
| E02 | | | | | |
| … | | | | | |
| E50 | | | | | |

汇总：

```text
Category Accuracy

Error Code Accuracy

Recovery Action Accuracy

Unnecessary Retry Count

Unsafe Retry Count
```

---

# 一百二十八、Ablation 结果表

后面可以：

| Metric | Typed Recovery | Generic Retry |
|---|---:|---:|
| Task Success | | |
| Total Attempts | | |
| Unnecessary Retries | | |
| Unsafe Retries | | |
| Median Recovery Time | | |
| Tool Calls | | |

这张表很适合最终 README。

---

# 一百二十九、今天最关键的 7 个 Runtime Invariant

### I1

```text
POLICY_DENIED
→ Retry = 0
```

### I2

```text
APPROVAL_DENIED
→ Retry = 0
```

### I3

```text
SANDBOX_UNAVAILABLE
→ Host fallback = 0
```

### I4

```text
PATCH_CONTEXT_MISMATCH
→ same patch retry = 0
```

### I5

```text
TEST_FAILED
→ repair
not blind test retry
```

### I6

```text
USER_INTERRUPT
→ PAUSED
not FAILED
```

### I7

```text
Retry Budget exhausted
→ no further operation
```

如果这 7 个成立，你今天核心实现就已经比较扎实。

---

# 一百三十、今日最终验收 Checklist

### Theory

```text
[ ] Error Taxonomy

[ ] Category vs Code

[ ] Retryable

[ ] Transient vs Permanent

[ ] Idempotency

[ ] Recovery Policy

[ ] Retry vs Repair vs Replan

[ ] Exponential Backoff

[ ] Jitter

[ ] Fail Fast

[ ] Fail Closed
```

### Implementation

```text
[ ] ErrorCategory

[ ] AgentErrorCode

[ ] FailureStage

[ ] AgentFailure

[ ] ErrorClassifier

[ ] RecoveryAction

[ ] RecoveryPolicy

[ ] RetryPolicy
```

### Required Tests

```text
[ ] rate limit → retry

[ ] model timeout → retry

[ ] patch mismatch
    → reread/regenerate

[ ] test fail → repair

[ ] policy deny → stop

[ ] approval deny → stop

[ ] sandbox unavailable → stop

[ ] Ctrl+C → PAUSED
```

### Recommended Tests

```text
[ ] invalid auth → stop

[ ] quota error → stop

[ ] context overflow → compact

[ ] insufficient context → retrieve

[ ] test timeout != model timeout

[ ] retry limit

[ ] Retry-After

[ ] cause preservation

[ ] secret-safe message
```

### Benchmark

```text
[ ] 50 fault cases

[ ] Category Accuracy

[ ] Error Code Accuracy

[ ] Recovery Accuracy

[ ] Unnecessary Retry Count

[ ] Unsafe Retry Count
```

### Evidence

```text
[ ] Design Decision

[ ] Typed vs Generic ablation

[ ] Failure Cases

[ ] Raw benchmark
```

---

# 一百三十一、今天必须能回答的 Interview Questions

### Error Model

1. 为什么不能统一 `except Exception: retry()`？
2. Exception 和 AgentFailure 有什么区别？
3. ErrorCategory 和 AgentErrorCode 为什么都需要？
4. 为什么同一个 TimeoutError 可以映射成不同 Agent Error？
5. 为什么 Error Classification 属于 Domain Model？

### Retry

6. Retryable 和 Transient 有什么区别？
7. 为什么 Retry 必须考虑 Idempotency？
8. 什么是 exponential backoff？
9. 为什么需要 jitter？
10. 为什么 Retry 需要 attempt 和 time 两种 Budget？
11. SDK Retry 和 Application Retry 为什么可能产生 Retry Storm？

### Recovery

12. Retry、Repair、Replan 有什么区别？
13. Patch mismatch 为什么不是 Retry？
14. Context overflow 为什么不是 Retry same request？
15. Test Failure 为什么应该 Repair？
16. 什么情况需要 Ask User？

### Safety

17. Policy Deny 为什么不能 Retry？
18. Approval Deny 为什么不能 Retry？
19. Sandbox unavailable 为什么必须 Fail Closed？
20. Fail Fast 和 Fail Closed 有什么区别？

### Runtime

21. Ctrl+C 为什么是 PAUSED 而不是 FAILED？
22. Recovery Action 自己失败怎么办？
23. Unknown Error 默认怎么处理？
24. 怎么保存原始 Exception 又不泄露 Secret？
25. Error Event 怎样帮助 Observability？

### Evaluation

26. Classification Accuracy 为什么不够？
27. 为什么 Recovery Action Accuracy 更重要？
28. 什么叫 Unnecessary Retry？
29. 怎样用 Fault Injection 测 Error Handling？
30. Typed Recovery vs Generic Retry Ablation 怎么设计？

---

# 一百三十二、如果面试官问：“不就是写一堆异常类型吗？”

你应该能回答：

> 我不是把 Python Exception 换了一套名字，而是在 Runtime 中建立从底层故障到 Agent 行为的语义层。Provider、Git、Patch、Verification、Security 和 Session 的底层错误首先结合发生阶段被规范化成 `AgentFailure`，再通过 `RecoveryPolicy` 映射成 `RETRY`、`REPAIR`、`REPLAN`、`REREAD_AND_REGENERATE`、`COMPACT_CONTEXT`、`PAUSE` 或 `STOP`。比如 Model Rate Limit 可以通过带 jitter 的 exponential backoff 重试，而 Patch Context Mismatch 必须重新读取文件再生成 Patch，Test Failure 进入 Repair Loop，Policy/Approval Denial 则是不可自动重试的安全终止条件。Retry 同时受到次数和总时间 Budget 控制，并考虑底层 SDK Retry 和 Side-effect Idempotency。我还用 50 个 deterministic fault-injection cases 测 Classification 与 Recovery Accuracy，并和 generic retry-all 做 Ablation。

这就不是：

```text
Exception Handling
```

而是：

```text
Agent Runtime Fault Model
+
Recovery Orchestration
+
Safety
+
Observability
+
Evaluation
```

---

# 一百三十三、Day 3 在整个 Single-Agent Runtime 中的位置

现在前三天终于连成：

```text
                 Natural Language
                        │
                        ▼
                    TaskSpec
                        │
                        ▼
                      Plan
                        │
                        ▼
                   PlanStep
                        │
                        ▼
                     Patch
                        │
                        ▼
                 Verification
                        │
                ┌───────┴───────┐
                ▼               ▼
              PASS            FAILURE
                │               │
                │               ▼
                │        ErrorClassifier
                │               │
                │               ▼
                │          AgentFailure
                │               │
                │               ▼
                │        RecoveryPolicy
                │               │
                │     ┌─────────┼──────────┐
                │     ▼         ▼          ▼
                │   RETRY     REPAIR      REPLAN
                │     │         │          │
                │     │         └────┐     │
                │     └──────────────┴─────┘
                │                    │
                └────────────────────┘
```

Day 1 解决：

```text
我应该做什么？
```

Day 2 解决：

```text
我做得对吗？
```

Day 3 解决：

```text
做错以后我到底该怎么办？
```

这三个能力组合以后，你的 Agent 才从“**会调用 Tool 的 LLM**”真正开始接近“**具备长期任务纠错能力的 Agent Runtime**”。

明天 Day 4 的 Session Persistence 则会解决最后一个非常现实的问题：

```text
现在它知道怎么恢复错误了，
但如果整个 CodeTeam 进程直接退出，
这些 Task / Plan / Attempt / Failure / Recovery State
还能不能继续存在？
```

也就是从 **Failure Recovery** 正式走向 **Crash Recovery + Resume**。

---

# 附录：Day 3 教学工程地图（Coder Agent 首轮输出）

> 以下为 Coder Agent 按规约 §三十一 15 节结构输出的工程地图，基于只读检查的实际代码接口。

## 1. 今天在整个 Coding Agent 中做什么

**一句话**：把 Orchestrator 里那个"任何异常 → 直接 FAILED"的总闸门，升级成一个**有语义的故障分类 + 恢复决策系统**。

```
以前（D1/D2 现状）：
  出现异常 → except Exception → _fail() → FAILED
  （无论 429、Policy DENY、Ctrl+C 全部一视同仁）

今天（Day 3）：
  出现异常 → ErrorClassifier（这是什么类型的失败？）
           → AgentFailure（typed domain failure）
           → RecoveryPolicy（下一步做什么？）
           → RETRY / REPAIR / REPLAN / REREAD / PAUSE / STOP
```

真实世界中 Agent 会遭遇 8 种完全不同的失败——模型 503（重试有意义）、API Key 错误（重试永远无效）、Patch 上下文失配（重试同一个 Patch 一定失败）、pytest 失败（重跑测试不能修代码）、Policy DENY（重试等于绕过安全策略）、用户拒绝审批（重试等于忽略用户决定）、Sandbox 不可用（绝不能降级裸机执行）、用户 Ctrl+C（重试等于无视用户停止请求）。用一个 `retry()` 处理全部 8 种，是 Agent Runtime 的典型大坑。

## 2. Capability Mapping

```text
Primary:
  Agent Runtime（Fault Model + Recovery Orchestration）

Secondary:
  Observability（error.* / recovery.* / retry.* 事件序列）
  Safety（SECURITY 类 Fail Closed、Policy/Approval Deny 硬编码 STOP）
  Evaluation（50 Case Fault Injection 数据驱动测试）

求职价值：这不是"写一堆异常类型"，而是
「底层故障 → Agent 行为」的语义层——面试时可讲
Retry Ownership、Fail Closed、Thundering Herd、Retry Storm 等工业概念。
```

## 3. Theory（压缩版）

4 组核心概念：

| 概念 | 回答的问题 | 例子 |
|---|---|---|
| ErrorCategory | 这是哪一类问题？ | MODEL / PATCH / TEST / SECURITY |
| Retryable | 重试同一动作有合理成功概率吗？ | RATE_LIMIT=是，AUTH_FAILED=否 |
| Transient/Permanent | 原因会随时间消失吗？ | 503=是，API Key 错误=否 |
| RecoveryAction | Runtime 下一步干什么？ | RETRY / REPAIR / REPLAN / PAUSE / STOP |

四个**不是**一回事。Retryable ≠ Transient（远程写超时是 transient 但不可盲重试——幂等性问题）。Retry ≠ Repair ≠ Replan（同动作 / 新实现 / 新策略）。

**最核心设计原则**：同一个 `TimeoutError` 在不同 stage 映射成不同 AgentFailure——MODEL_CALL stage → MODEL_TIMEOUT→RETRY；VERIFICATION stage → TEST_TIMEOUT→REPAIR。所以 Classifier 必须接收 `(error, stage, operation, metadata)`，不能只看 `type(exception)`。

## 4. Industrial Design（压缩版）

| 工业系统 | 做法 | 启示 |
|---|---|---|
| GitHub Copilot SDK | `onErrorOccurred` Hook 提供 `errorType`/`errorContext`/`recoverable` | 分类信息由 Runtime 提供，应用决定恢复 |
| OpenAI API | 明确区分可恢复（500/503/429）与不可恢复（billing/quota/auth） | Transient 才 Retry；billing 类 Retry 无效 |
| Claude Code Hooks | `PostToolUseFailure` vs `PermissionDenied` 是不同生命周期事件 | 授权失败 ≠ 操作失败 |
| OpenAI rate-limit 指南 | Retry-After 优先，无 Header 用 backoff+jitter；避免 SDK/应用层 Retry 叠加 | RetryPolicy 设计 + Retry Storm 规避 |

## 5. 当前仓库检查（只读核实结果）

### 已存在、今天要复用的

| 模块 | 实际接口 | 今天的用途 |
|---|---|---|
| `task/state.py` | `TaskState.PAUSED` 已存在（第 31 行） | I6 不需要新增状态 |
| `planning/models.py` | `replan()` 已存在 | REPLAN 动作直接复用 |
| `repair/` | Day2 RepairLoop 已存在 | REPAIR 动作直接复用 |
| `verification/models.py` | `VerificationStatus`：PASSED/FAILED/TIMED_OUT/START_FAILED/BLOCKED/INCONCLUSIVE | TEST_FAILED/TEST_TIMEOUT 映射源 |
| `execution/models.py` | `PolicyDecision.DENY`、`ApprovalDecision.DENIED`、`CommandStatus` | POLICY_DENIED/APPROVAL_DENIED 映射源 |
| `sandbox/errors.py` | `SandboxError`/`DockerUnavailableError` | SANDBOX_UNAVAILABLE 映射源 |
| `events.py` | 已有 task.*/verification.*/repair.*/approval.* + Week1 的 `RETRY_SCHEDULED` | 需新增 error./recovery./retry. 事件 |

### 冲突与缺口

| 问题 | 详情 |
|---|---|
| 命名冲突 | day3 建议 `codeteam/errors/` 包，但 `codeteam/errors.py` 已被 Week1 传输层占用，被 `llm/openai_compatible.py` + 2 个测试文件依赖（禁止修改） |
| Retry Storm 风险 | `llm/openai_compatible.py` 已有 `RetryConfig(base_delay=0.5, 指数退避)`——传输层已 Retry，Task-level RetryPolicy 必须明确 Ownership |
| 总闸门 | `orchestrator.py:159` `except Exception → _fail()`——今天升级为 classify → recover → 预算耗尽才 FAILED |
| events.py 缺口 | 缺 error.detected/error.classified/recovery.decided/retry.scheduled/retry.started/retry.exhausted/recovery.started/recovery.completed/recovery.failed/task.paused |

## 6. 涉及文件

新增：

```text
codeteam/failures/            ← 新 Domain 错误包（DD 中论证命名）
├── __init__.py
├── models.py                 ← ErrorCategory/AgentErrorCode/FailureStage/RecoveryAction/AgentFailure
├── classifier.py             ← ErrorClassifier：raw failure + stage → AgentFailure
├── recovery.py               ← RecoveryPolicy：AgentFailure → RecoveryAction（只决策）
└── retry.py                  ← RetryPolicy：backoff+jitter+Retry-After+budget（只算 delay）

tests/failures/               ← test_classifier / test_recovery_policy / test_retry_policy / test_fault_injection
docs/design_decisions/DD-W4-D3-01.md
```

修改：

```text
codeteam/agent/orchestrator.py   ← Step 6：总闸门升级
codeteam/events.py               ← 新增 error/recovery/retry 事件
tests/agent/                     ← 恢复集成测试
```

禁止修改：`codeteam/errors.py`、`codeteam/llm/`、Week1 传输层测试、`tests/fixtures/` 原件、已有 DD 文件、规约文件。

## 7. Architecture / Data Flow

```text
                    SingleAgentOrchestrator.run()
                              │
                              ▼
                      Operation 执行
                              │
                      ┌───────┴───────┐
                      ▼               ▼
                   SUCCESS         FAILURE
                                      │
                                      ▼
                     ┌────────────────────────────────┐
                     │ ① ErrorClassifier              │
                     │   classify(error, stage,       │
                     │            operation, metadata)│
                     │   只分类：不 sleep 不 retry     │
                     │   不调模型（deterministic）     │
                     └────────────────┬───────────────┘
                                      ▼
                              AgentFailure（typed）
                        category/code/stage/retryable/
                        transient/cause 链（wrap not erase）
                                      │
                                      ▼
                     ┌────────────────────────────────┐
                     │ ② RecoveryPolicy               │
                     │   failure.code → action        │
                     │   只决策：不执行               │
                     │   SECURITY 类硬编码 STOP       │
                     └────────────────┬───────────────┘
                                      ▼
                     ┌────────────────────────────────┐
                     │ ③ Orchestrator 执行 Recovery   │
                     │   RETRY → RetryPolicy 算 delay │
                     │   REPAIR → Day2 RepairLoop     │
                     │   REPLAN → Day1 planner        │
                     │   REREAD → 重读+重生成         │
                     │   PAUSE → TaskState.PAUSED     │
                     │   STOP → _fail()               │
                     └────────────────────────────────┘
```

RetryPolicy 内部：

```text
RetryPolicy.decide(failure, attempt, retry_after, elapsed)
    ├── failure.retryable == False → should_retry=False（秒判）
    ├── attempt >= max_attempts → should_retry=False（retry.exhausted）
    ├── elapsed >= max_total_delay → should_retry=False（时间预算）
    └── 否则 → delay = min(max_delay, base × 2^attempt)
              有 Retry-After → max(retry_after, backoff)
              加 jitter → RetryDecision(delay)

注意：Policy 只算 delay，不 time.sleep——
等待由 Orchestrator 或注入的 sleeper 完成（可测性）
```

## 8. 今日步骤拆分（7 步）

| Step | 目标 | 涉及文件 | 完成标志 |
|---|---|---|---|
| 1 | 4 个枚举（Category/Code/Stage/Action） | `failures/models.py`（部分） | 枚举可导入，覆盖 day3 规格 |
| 2 | AgentFailure 模型（cause preservation） | `failures/models.py` | 能构造完整实例 |
| 3 | Deterministic ErrorClassifier | `failures/classifier.py` | 8 Required 映射全对 |
| 4 | RecoveryPolicy（只决策） | `failures/recovery.py` | SECURITY 硬编码 STOP |
| 5 | RetryPolicy（只算 delay） | `failures/retry.py` | decide() 可测，不真 sleep |
| 6 | 接 Orchestrator + events | `agent/orchestrator.py` + `events.py` | 8 集成测试全绿 |
| 7 | 50 Case Fault Injection | `tests/failures/` | 50 条全绿，FailureCase 可被周度脚本 import |

依赖：1→2→3→4→5 线性；6 依赖 3/4/5；7 依赖 3/4。

## 9. Test Strategy

Required 8 条：rate limit→retry / model timeout→retry / patch mismatch→reread / test fail→repair / policy deny→stop / approval deny→stop / sandbox unavailable→stop / Ctrl+C→PAUSED。每条说明对应哪条验收、为什么能证明。

Recommended 10 条：重点 cause preservation（T17）、secret-safe message（T18）、Retry-After（T16）、retry exhausted（T15）。

50 Case 分布：MODEL10/CONTEXT6/PATCH7/TOOL6/SECURITY6/TEST5/GIT4/SESSION4/INTERRUPT2。全部 Fake，不真实打爆外部系统，不真实 sleep。

## 10. Design Decision Plan

DD-W4-D3-01（Evidence = PROPOSED）必须回答 9 个问题：新包命名（推荐 `codeteam/failures/`，旧 errors.py 保留传输层）、Retry Ownership、职责分离、Classification=deterministic / Diagnosis=model-assisted、方案 B（recommended_recovery 存 Failure 但执行在 Orchestrator）、stage 敏感性、cause preservation、Unknown 默认 fail closed、第一版不做清单。

## 11. Benchmark Plan（周度预留，今天不执行）

今天只做数据出口：FailureCase 可被周度脚本 import；AgentFailure/RetryDecision 字段包含周度指标所需信息。周度实验规格写进 DD：Category/Code Accuracy（含 Confusion Matrix）、Recovery Action Accuracy、Unnecessary/Unsafe Retry Count。禁止写评测脚本、宣称 SUPPORTED、虚构数字。

## 12. Ablation Plan（周度预留）

Typed Recovery vs Generic Retry。Hypothesis：Typed Recovery 在 patch/test/security/permanent 类失败上显著优于 Generic Retry（Generic Retry 不改变导致失败的 State）。Corpus：10 transient/10 patch/10 verification/10 security/10 permanent。SUPPORTED 结论必须等数据。

## 13. Failure Cases to Watch

12 个模式：误分类（SECURITY 类最高测试优先级）、Permanent 无限 Retry（双预算）、原始 Exception 丢失（wrap not erase）、安全错误被自动 Retry（硬编码 STOP）、Timeout 统一 Retry（stage 敏感）、无 Backoff/Jitter、Retry Storm（Ownership）、Retry 副作用（幂等性）、Recovery 自己失败/无限套娃（Recovery Budget）。

## 14. Interview Focus

30 个问题按 6 组。最易答错的：同 Timeout 不同 stage 不同 code、Retryable vs Transient、Retry Storm 叠加、Policy Deny 不可 Retry 的安全理由、Fault Injection 的确定性价值、"不就是写一堆异常类型吗"的标准答案模板（day3 §一百三十二）。

## 15. 今日最终完成标准

```text
[ ] 7 个 Runtime Invariant 全部成立并有对应测试（I1~I7）
[ ] 8 条 Required 测试全绿，每条说明对应验收
[ ] 10 条 Recommended 尽量覆盖
[ ] 50 Case Fault Injection 数据驱动测试全绿
[ ] 全量 pytest ≥ W4D2 基线，Week1 传输层测试不破坏
[ ] ruff 0 error
[ ] DD-W4-D3-01 落盘（Evidence = PROPOSED）
[ ] 事件序列完整：Rate Limit 恢复可重放 day3 §一百一十九 时间线
[ ] 总闸门升级后：意外异常仍 FAILED（D1 不回归），已知 Domain Failure 走恢复
[ ] 明确不做清单写进报告
```