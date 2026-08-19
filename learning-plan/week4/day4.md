# 第 4 周 Day 4：Session Persistence + Resume

今天开始解决一个非常典型的 **Agent Runtime 问题**：

> 前三天已经让 Agent 知道“做什么、做得对不对、失败后怎么办”，但如果 Python 进程突然退出，这些状态还能不能活下来？

前三天可以抽象成：

```text
Day 1
TaskSpec → Plan → Execution State

Day 2
Patch → Verify → Repair

Day 3
Failure → Classification → RecoveryAction
```

今天要在外面加一层：

```text
                  ┌───────────────────┐
                  │ Persistent Session │
                  │                   │
                  │ Task              │
                  │ Plan              │
                  │ Current State     │
                  │ Model             │
                  │ Worktree          │
                  │ Checkpoints       │
                  │ Usage             │
                  └─────────┬─────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
         Process A dies             Process B starts
                                          │
                                          ▼
                               codeteam resume <id>
                                          │
                                          ▼
                               Reconstruct Runtime
                                          │
                                          ▼
                                 Continue Task
```

所以今天最重要的公式是：

> **Resume = Durable State + State Reconciliation + Runtime Reconstruction**

而绝对不是：

> **Resume = 把之前的 Python Agent 对象反序列化回来。**

---

# 一、为什么 Session Resume 已经是工业 Coding Agent 的核心能力

这次我重点查了 OpenAI Codex、Claude Code 和 GitHub Copilot CLI 当前公开的实现。

OpenAI Codex 当前不仅 CLI 有 `codex resume`，App Server 的核心协议本身就区分 `thread/start`、`thread/resume` 和 `thread/fork`。一个已有 Thread 可以按 ID 恢复，再继续启动新的 Turn。更值得注意的是，Codex Resume 时还会恢复 Thread Metadata；例如动态 Tool 可以持久化后恢复，而被标记为 required 的 MCP Server 如果恢复时初始化失败，`thread/resume` 会直接失败，而不是偷偷降低能力继续运行。

这说明工业意义上的 Resume 并不是：

```text
load conversation
→ 继续聊天
```

而更接近：

```text
load persistent task/thread
        ↓
restore runtime metadata
        ↓
check required runtime dependencies
        ↓
reconstruct execution environment
        ↓
continue
```

Claude Code 当前则会在工作过程中持续把 Session 保存为本地 transcript，因此退出以后可以通过 `--continue` 或 `--resume <session>` 恢复；Claude Agent SDK 进一步暴露了 `SessionStore`，可以把 transcript 镜像到 S3、Redis 或数据库，从而支持容器、CI Worker、Serverless 等不同 Host 之间恢复 Session。

Claude Code 还把 Checkpoint 和 Session 关联起来：Checkpoint 随 Conversation 保存，因此 Resume 之后仍然可以 Rewind。

GitHub Copilot CLI 的实现尤其值得你今天研究：它不仅把每个 Session 完整持久化为本地文件，还另外维护一个 SQLite Session Store，保存结构化子集，用于 `/chronicle` 查询等功能。Session 数据会在运行过程中周期性写盘；如果 SQLite Store 损坏、丢失，甚至进程异常退出，只要 Session Files 还在，就可以通过 reindex 重建 Session Store。

这个设计对 CodeTeam 有一个非常好的启发：

```text
完整 Durable Session
        │
        ├── 用于真正恢复
        │
        └── Source of Truth
               
Derived Index / View
        │
        └── 用于查询、分析、统计
```

不要为了快速查询而让“索引”成为唯一恢复来源。

---

# 二、先彻底理解 Durable State 和 Ephemeral State

这是今天最基础也最重要的概念。

## Durable State

Durable State 是：

> **Python 进程死掉以后仍必须存在，另一个新进程仅凭这些数据就能够理解之前工作到了哪里。**

例如现在这个任务：

```text
Task:
修复登录超时问题

Plan:
P1 定位 timeout
P2 复现 Bug
P3 修改
P4 Target Test
P5 Regression

Current:
P3 RUNNING

Worktree:
task-001

Checkpoint:
cp-003

Provider:
provider-a

Model:
model-x

Usage:
12,342 tokens
```

这些都应该 Durable。

---

## Ephemeral State

Ephemeral State 是：

> **只在当前 Python Process 生命周期中有意义的运行时对象。**

典型例子：

```text
ModelClient HTTP connection

subprocess.Popen

threading.Lock

asyncio.Task

open file descriptor

Docker process handle

socket

in-memory cache

Python function object
```

它们不能被简单保存下来以后继续使用。

比如：

```python
session.http_client = httpx.AsyncClient(...)
```

进程结束后：

```text
TCP connection
已经不存在。
```

所以 Resume 不应该尝试：

```text
恢复旧 HTTP connection
```

而应该：

```text
Session 保存：
provider = "provider-a"

         ↓

新进程 Resume

         ↓

ProviderRegistry

         ↓

重新创建 ModelClient
```

---

# 三、一个非常重要的工业级公式

可以把 Session Resume 理解成：

```text
        Durable Domain State
                │
                ▼
       当前真实系统状态
                │
                ▼
      State Reconciliation
                │
                ▼
      Reconstruct Runtime
                │
                ▼
         Continue Work
```

例如：

```text
Session:
provider = provider-a

Resume:
重新 new ModelClient()
```

再例如：

```text
Session:
worktree = /tmp/codeteam/task-001

Resume:
检查它现在到底还存不存在
```

再例如：

```text
Session:
checkpoint_id = cp-003

Resume:
检查 CheckpointStore 中 cp-003 是否仍然存在
```

也就是说：

> **Durable State 描述“我上次认为世界是什么样”；State Reconciliation 检查“现在世界实际上还是不是那个样子”。**

---

# 四、Task 和 Session 再区分一次

Day 1 已经讲过，现在 Session 真正开始实现后，这个区别变得非常重要：

```text
Task
=
我要完成什么工作？


Session
=
这项工作在 Runtime 中如何持续存在？
```

例如：

```text
Task

修复登录 timeout
```

Session：

```text
ses_abc123

Task:
修复登录 timeout

TaskStatus:
VERIFYING

Plan:
...

Worktree:
...

Checkpoints:
...

Usage:
...

Provider:
...
```

所以：

```text
Task
属于业务执行语义

Session
属于 Agent Runtime 生命周期语义
```

---

# 五、Session 也不应该等于 Conversation

这是 Coding Agent 与普通聊天产品非常重要的区别。

普通 LLM Session 可能主要需要：

```text
messages[]
```

Coding Agent Session 至少还需要：

```text
TaskSpec

Plan

TaskStatus

Worktree identity

Git base

Checkpoint chain

Provider / model

Usage

Recovery state

Current operation
```

所以你的：

```text
session.json
```

绝对不能只有：

```json
{
  "messages": [...]
}
```

否则进程恢复后知道聊过什么，却不知道：

```text
现在应该继续哪一个 PlanStep？

代码现在在哪个 Worktree？

上一个安全恢复点在哪里？

这个任务到底已经花多少钱？

之前用的是什么模型？
```

---

# 六、Session 和 Checkpoint 也是两种完全不同的东西

你 Week 3 已经有 CheckpointManager，这里千万不要混。

```text
Checkpoint
=
Workspace 文件状态


Session Snapshot
=
Agent Runtime 状态
```

例如：

```text
Checkpoint cp-003

A.py = version 3
B.py = version 1
```

Session：

```text
Task:
fix timeout

PlanStep:
P3

TaskStatus:
IMPLEMENTING

Current Checkpoint:
cp-003

Provider:
A

Tokens:
12k
```

所以：

```text
Session
          │
          └── references → Checkpoint
```

而不是：

```text
Session
=
Checkpoint
```

---

# 七、今天推荐的 SessionStatus

注意不要把昨天的：

```text
TaskStatus
```

复制一份。

TaskStatus 描述：

```text
INSPECTING
PLANNING
IMPLEMENTING
VERIFYING
```

SessionStatus 应该回答：

> **这个 Session 当前是否处于一个可以继续工作的 Runtime 生命周期状态？**

第一版推荐：

```python
class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"

    RECOVERY_REQUIRED = "recovery_required"

    COMPLETED = "completed"
    FAILED = "failed"
```

这里我尤其建议增加：

```text
RECOVERY_REQUIRED
```

后面会解释为什么它非常重要。

---

# 八、TaskStatus 和 SessionStatus 同时存在是合理的

例如：

```text
SessionStatus:
PAUSED

TaskStatus:
VERIFYING
```

意思：

> Task 当时执行到了 Verification，但整个 Session 因用户 Ctrl+C 被暂停。

恢复：

```text
SessionStatus:
RUNNING

TaskStatus:
VERIFYING
```

继续 Verification。

这比把：

```text
TaskStatus = PAUSED
```

硬塞进 Task State Machine 更清楚。

当然 MVP 中也可以让 TaskStatus 有 PAUSED；但长期设计上，建议至少理解这两个维度不同。

---

# 九、今天推荐的 SessionManifest

你要求实现：

```text
SessionManifest
```

我不建议再额外创建：

```text
manifest.json
```

因为你当前目录已经定成：

```text
session.json
events.jsonl
context.json
```

可以让：

```text
SessionManifest
```

成为 `session.json` 的 Header。

例如：

```python
class SessionManifest(BaseModel):
    schema_version: int = 1

    session_id: str
    state_version: int

    repo_id: str

    created_at: datetime
    updated_at: datetime

    last_event_seq: int
```

---

# 十、为什么必须有 `schema_version`

假设今天：

```json
{
  "status": "paused"
}
```

一个月以后你把模型改成：

```json
{
  "lifecycle": {
    "status": "paused"
  }
}
```

旧 Session 怎么 Resume？

所以：

```text
schema_version
```

告诉 Loader：

```text
这个 Durable State
是哪一代格式？
```

以后：

```text
v1
→ migrate
→ v2
```

成为可能。

这叫：

```text
Persistence Schema Evolution
```

---

# 十一、为什么需要 `state_version`

假设：

```text
Version 17:
P2 RUNNING

Version 18:
P2 COMPLETED

Version 19:
P3 RUNNING
```

`state_version` 可以告诉你：

```text
当前 Snapshot
是哪一次 Durable State Update。
```

以后：

```text
Event Log
Concurrency
Crash Recovery
```

都会需要它。

不要只依赖：

```text
updated_at
```

因为时间戳并不是可靠的状态序号。

---

# 十二、我建议 Session 第一版长这样

概念上：

```python
class Session(BaseModel):
    manifest: SessionManifest

    status: SessionStatus

    task: TaskSpec
    task_status: TaskStatus

    plan: Plan

    provider_id: str
    model_id: str

    usage: UsageSummary

    repo: RepositoryRef
    worktree: WorktreeRef

    checkpoint_ids: tuple[str, ...]
    current_checkpoint_id: str | None

    active_operation: ActiveOperation | None

    last_failure: AgentFailure | None
```

这里我故意没有加入：

```text
ModelClient
CommandRunner
CheckpointManager
DockerRunner
Lock
```

因为它们全都是：

```text
Ephemeral Runtime Object
```

---

# 十三、为什么建议增加 `active_operation`

这是今天很容易漏掉，但非常重要的 Crash Recovery 问题。

假设 Session 保存：

```text
TaskStatus:
IMPLEMENTING
```

然后 Agent 开始：

```text
apply patch
```

中途：

```text
Python process
SIGKILL
```

新进程 Resume 时：

> Patch 到底执行了吗？

可能：

```text
情况 A
没开始


情况 B
完成了一半


情况 C
已经完全成功
只是还没保存 Session
```

所以只保存：

```text
TaskStatus = IMPLEMENTING
```

不够。

---

# 十四、建议记录 Operation Boundary

例如：

```python
class OperationStatus(str, Enum):
    PREPARED = "prepared"
    STARTED = "started"
    COMPLETED = "completed"


class ActiveOperation(BaseModel):
    operation_id: str
    kind: str

    status: OperationStatus

    checkpoint_before: str | None

    started_at: datetime | None
```

于是：

```text
operation STARTED
+
process disappeared
```

Resume 就知道：

> 这里存在一个“结果不确定”的 In-flight Operation。

而不是盲目：

```text
把 Patch 再执行一次。
```

---

# 十五、这就是为什么 `RECOVERY_REQUIRED` 很重要

假设程序正常 Ctrl+C：

```text
Session:
PAUSED
```

很清楚。

但如果程序：

```text
SIGKILL
power loss
Python crash
```

Disk 上最后状态可能仍然：

```text
RUNNING
```

但现在根本没有正在运行的 Runtime。

于是新进程加载：

```text
status == RUNNING
```

绝对不能解释成：

```text
“另一个进程正在运行”
```

也不能：

```text
“那我直接接着下一步”
```

而应该：

```text
stored status = RUNNING
+
no active runtime ownership

→ RECOVERY_REQUIRED
```

然后：

```text
inspect worktree
inspect checkpoint
inspect active operation
```

再决定恢复位置。

Claude Code 当前甚至会为运行中的 Session 保留小型本地 Session 文件，用于检测并发 Session 和 Crash，正常退出后删除，下一次启动时清理 Crash 残留。

这正说明：

> **运行状态和持久化状态不能简单画等号。**

---

# 十六、Snapshot 到底是什么

Snapshot：

> 某一时刻整个 Runtime Domain State 的一个可直接加载版本。

你今天：

```text
session.json
```

就是 Session Snapshot。

例如：

```text
Session v42

Task:
timeout fix

TaskStatus:
VERIFYING

Plan:
P1 complete
P2 complete
P3 complete
P4 running

Usage:
18,442 tokens

Checkpoint:
cp-004
```

读取它：

```text
O(当前状态大小)
```

即可恢复当前视图。

---

# 十七、Event Log 又是什么

Event Log：

> 按时间顺序追加发生过的 Runtime 事实。

例如：

```jsonl
{"seq":1,"type":"session.created"}
{"seq":2,"type":"task.status_changed"}
{"seq":3,"type":"plan.created"}
{"seq":4,"type":"checkpoint.created"}
{"seq":5,"type":"patch.applied"}
{"seq":6,"type":"verification.failed"}
{"seq":7,"type":"repair.started"}
{"seq":8,"type":"session.paused"}
```

它回答的是：

```text
“我是怎么走到现在的？”
```

Snapshot 回答：

```text
“我现在是什么状态？”
```

---

# 十八、为什么 Snapshot 和 Event Log 最好同时有

只有 Event：

```text
1
2
3
...
5000
```

每次 Resume：

```text
从 event 1 replay 到 5000
```

麻烦。

只有 Snapshot：

```text
session.json
```

你只知道：

```text
现在是 VERIFYING
```

但不知道：

```text
为什么？

之前失败过几次？

什么时候 Replan？

为什么换 Model？
```

所以：

```text
Snapshot
=
Fast Recovery


Event Log
=
History / Audit / Debug
```

---

# 十九、但第一版不要急着做完整 Event Sourcing

这是很重要的边界。

不要今天变成：

```text
event 1
event 2
...
```

然后：

```text
所有 Session State
都必须通过 Event Replay 创建
```

那会突然把项目升级成 Event Sourcing 系统。

Week 4 MVP 推荐：

```text
session.json
=
Resume 的 Source of Truth


events.jsonl
=
Audit / Debug / Evaluation history
```

以后需要更强恢复再研究：

```text
Event Sourcing
```

---

# 二十、GitHub Copilot 的实现特别值得作为这个设计参考

GitHub Copilot CLI 当前就是一种很典型的 Hybrid Persistence：完整 Session 保存在 Session-specific files 中，而结构化子集进入 SQLite Session Store；SQLite Store 可以根据 Session Files 重新构建。这既保留完整 Durable Record，又支持高效查询。

你的 MVP：

```text
session.json
+
events.jsonl
```

虽然实现更简单，但思想非常接近：

```text
Durable record

+

Queryable / analyzable history
```

---

# 二十一、`context.json` 今天应该负责什么

Day 5 才正式做：

```text
Context Compaction
```

所以今天不要提前做完整 Compactor。

先让：

```text
context.json
```

承担：

```text
当前 Working Context Metadata

Context version

Summary（如果已有）

recent turn references

retrieved files metadata
```

例如：

```json
{
  "context_version": 3,
  "summary": null,
  "recent_turn_ids": [
    "turn-017",
    "turn-018"
  ],
  "retrieved_files": [
    "src/auth/client.py"
  ]
}
```

明天会把它升级成真正：

```text
Model-visible Context State
```

---

# 二十二、推荐目录

最终：

```text
.codeteam/
└── sessions/
    └── ses_abc123/
        ├── session.json
        ├── events.jsonl
        └── context.json
```

但：

```text
CheckpointStore
```

继续放自己的 Runtime State：

```text
.codeteam/
└── checkpoints/
```

不要复制所有 Workspace Snapshot 到 Session Directory。

Session 只保存：

```text
checkpoint id/reference
```

---

# 二十三、SessionStore 和 SessionService 必须分开

这是今天很关键的职责划分。

## SessionStore

回答：

> 数据怎么读写？

应该负责：

```text
create

save

load

append_event
```

---

## SessionService

回答：

> Session 生命周期应该怎么变化？

负责：

```text
create_session

pause

resume
```

---

所以用户要求的：

```text
create()
save()
load()
pause()
resume()
```

逻辑上最好不是全部塞进：

```text
SessionStore
```

而是：

```text
SessionStore
├── create
├── save
├── load
└── append_event


SessionService
├── create
├── pause
└── resume
```

---

# 二十四、为什么 Store 不应该自己 Resume

Resume 需要：

```text
Load Session

Validate Repo

Validate Worktree

Validate Checkpoints

Rebuild ModelClient

Rebuild SafeExecutor

Reconcile active operation

Change SessionStatus
```

这些完全不是：

```text
Filesystem Persistence
```

的职责。

所以：

```text
SessionStore.load()
```

只应该说：

```text
“这是磁盘里的 Session。”
```

而：

```text
SessionService.resume()
```

才回答：

```text
“这个 Session 现在能不能继续？”
```

---

# 二十五、工业界 Codex 的设计也体现这种分离

Codex App Server 当前有：

```text
thread/read
```

用于读取持久 Thread，

和：

```text
thread/resume
```

用于真正恢复它进入可继续工作的状态。

这是一个非常好的类比：

```text
load
≠
resume
```

---

# 二十六、`create()` 应该做什么

第一版：

```text
Generate session_id
        ↓
Validate task
        ↓
Create SessionManifest
        ↓
SessionStatus = CREATED
        ↓
Atomic save
        ↓
session.created event
        ↓
return Session
```

Session ID 建议：

```text
ses_<uuid>
```

不要：

```text
session-1
session-2
```

因为以后并发创建容易冲突。

---

# 二十七、`save()` 应该做什么

`save()` 不应该简单：

```python
with open("session.json", "w") as f:
    json.dump(...)
```

正确目标是：

> 要么读到旧的完整 Snapshot，要么读到新的完整 Snapshot；尽量避免出现半个 JSON。

稍后讲 Atomic Write。

同时：

```text
state_version += 1
updated_at = now
```

---

# 二十八、`pause()` 应该是什么顺序

这是一个非常重要的生命周期问题。

错误：

```text
status = PAUSED
save()

kill command
```

因为如果：

```text
save() 完成
```

然后进程自己 Crash，

Disk 上：

```text
PAUSED
```

但后台 Command：

```text
还在运行
```

这明显不对。

---

# 二十九、正确的 Pause Pipeline

应该更接近：

```text
User Ctrl+C
        ↓
stop accepting new operations
        ↓
interrupt active command/model call
        ↓
wait for process cleanup
        ↓
capture current workspace/checkpoint references
        ↓
persist SessionStatus = PAUSED
        ↓
append session.paused
        ↓
exit
```

Day 5 CommandRunner 已经处理：

```text
Process Group
SIGTERM
SIGKILL
```

今天应该复用。

---

# 三十、如果 Active Operation 无法确认是否结束怎么办

不要：

```text
status = PAUSED
```

假装一切正常。

可以：

```text
RECOVERY_REQUIRED
```

例如：

```text
Docker cleanup
结果未知
```

Session：

```text
RECOVERY_REQUIRED
```

下一次 Resume：

```text
inspect state
```

---

# 三十一、`resume()` 才是今天最重要的函数

我建议你脑中先建立如下 Pipeline：

```text
codeteam resume ses_abc123
            │
            ▼
       Locate Session
            │
            ▼
       Load Snapshot
            │
            ▼
   Validate Schema Version
            │
            ▼
      Acquire Ownership
            │
            ▼
   Validate Repository Identity
            │
            ▼
   Validate Task Worktree
            │
            ▼
   Validate Checkpoint Chain
            │
            ▼
  Reconcile Current Git State
            │
            ▼
   Reconcile Active Operation
            │
            ▼
 Check Provider / Model Config
            │
            ▼
 Reconstruct Runtime Components
            │
            ▼
    Determine Safe Resume Point
            │
            ▼
   SessionStatus = RUNNING
            │
            ▼
       Continue Task
```

这才叫 Resume。

---

# 三十二、第一步：Session 是否存在

```text
ses_abc123
```

找不到：

```text
SESSION_NOT_FOUND
```

Day 3 已经有：

```text
ErrorCategory.SESSION
```

今天正式产生：

```text
SessionNotFound
→ STOP
```

不要：

```text
“找不到就创建一个新的同名 Session”
```

否则恢复语义完全混乱。

---

# 三十三、第二步：Schema 是否兼容

例如磁盘：

```text
schema_version = 3
```

当前 CodeTeam 只理解：

```text
1 / 2
```

不能：

```text
Pydantic 强行 parse
```

然后产生奇怪状态。

应该：

```text
SESSION_SCHEMA_UNSUPPORTED
```

未来：

```text
Migration v1 → v2
```

再支持。

---

# 三十四、第三步：Session Ownership / Lock

假设两个 Terminal 同时：

```bash
codeteam resume ses_abc123
```

如果都成功：

```text
Process A
修改 Plan

Process B
修改 Plan

Process A
apply Patch

Process B
apply Patch
```

Session 和 Worktree 很快损坏。

所以一个 Session 第一版应该：

```text
single writer
```

Resume 时：

```text
acquire session lock
```

失败：

```text
SESSION_ALREADY_ACTIVE
```

GitHub Copilot CLI 当前管理 Session 时也会区分正在被另一个进程使用的 Session，例如批量删除会跳过正在使用的 Session；Claude Code 当前也维护运行中 Session 文件用于检测并发和 Crash。

---

# 三十五、第四步：Repository Identity

这是用户要求：

```text
Cross-repo resume
```

的核心。

千万不要：

```text
session repo = 当前 cwd
```

假设：

```text
ses-001
属于：
repo-A
```

用户在：

```text
repo-B/
```

运行：

```bash
codeteam resume ses-001
```

不能把：

```text
ses-001
```

偷偷绑定到：

```text
repo-B
```

---

# 三十六、建议保存 RepositoryRef

例如：

```python
class RepositoryRef(BaseModel):
    repo_id: str

    git_common_dir: str

    base_sha: str
```

注意：

```text
remote URL
```

不能单独作为 Repo Identity。

因为：

```text
clone-A
clone-B
```

可能：

```text
remote URL 完全相同
```

但它们是两个本地 Runtime Workspace。

---

# 三十七、Cross-repo Resume 我建议的安全语义

如果：

```text
当前 cwd
≠
session repository
```

但 Session 中保存的 Repo：

```text
仍然存在
```

你有两个合理设计。

方案 A：

```text
拒绝：
请回到原 Repo Resume
```

方案 B：

```text
根据 Session RepositoryRef
自动切回原 Repo
```

MVP 我更推荐 A。

原因：

```text
行为更显式
不容易在用户不知情时操作另一个目录
```

以后 CLI 可以：

```bash
codeteam resume <id> --repo <path>
```

显式指定。

---

# 三十八、这里可以和 Claude Code 当前行为比较

Claude Code 当前 Resume 可以通过 Session ID 在当前项目和 Git Worktree 中搜索，较新版本甚至可以跨项目搜索唯一匹配的 Session ID；如果存在冲突副本，则不会随便选择一个。

你的 CodeTeam 不必照搬，但可以学习其中的重要思想：

> **Session ID Resolution 必须是确定性的，不能在多个可能 Workspace 中猜一个。**

---

# 三十九、第五步：Worktree Identity

Session 至少保存：

```text
task_id

worktree_path

task_branch

base_sha

last_known_head_sha
```

Resume：

```text
Does path exist?

Is it still a Git worktree?

Does it belong to this repo?

Does it belong to this task?

Is branch correct?

What is current HEAD?
```

---

# 四十、用户要求的 “Repo HEAD changed” 要更精确地理解

这是今天一个很重要的细节。

假设：

```text
Main Worktree
main:

昨天：
HEAD=A

今天：
HEAD=B
```

但：

```text
Task Worktree

codeteam/task-001
HEAD=T1

仍然存在
```

这并不一定意味着 Session 无法 Resume。

因为 Week 3 的 Worktree 正是为了：

```text
Task Isolation
```

---

# 四十一、真正要比较的是 Task Worktree

例如 Session 保存：

```text
base_sha=A

task_head=T1
```

Resume：

```text
main HEAD = B
```

可能只是：

```text
别人继续开发 main
```

Task 仍然可以基于：

```text
A
```

继续。

但如果：

```text
task worktree HEAD
从 T1
变成 T9
```

而 CodeTeam 没记录这个变化，

那才是：

```text
External Drift
```

应该：

```text
RECOVERY_REQUIRED
```

---

# 四十二、所以不要写一个粗暴测试

错误：

```python
if current_repo_head != session.repo_head:
    fail()
```

因为：

```text
Main HEAD 变化
```

不一定影响 Task。

正确应该验证：

```text
Repository Identity

Base SHA existence

Task Worktree identity

Task branch

Task Worktree HEAD

Dirty state
```

这说明今天的：

```text
State Reconciliation
```

为什么不是简单字段比较。

---

# 四十三、第六步：Checkpoint Chain

Session：

```text
checkpoint_ids:

cp001
cp002
cp003

current_checkpoint:
cp003
```

Resume 时应该：

```text
cp003 exists?

belongs to same task?

shadow state valid?
```

如果：

```text
cp003 missing
```

不要直接：

```text
current_checkpoint = None
```

然后继续。

这属于：

```text
SESSION_RECOVERY_REQUIRED
```

甚至：

```text
STOP
```

取决于当前任务是否依赖它。

---

# 四十四、第七步：Provider / Model

Session：

```text
provider:
provider-a

model:
model-x
```

新进程必须：

```text
ProviderRegistry
→ provider-a
→ new ModelClient
```

如果：

```text
API credential
今天没有了
```

Session 依旧保存正确，

但 Runtime 无法恢复。

所以：

```text
Durable State valid
≠
Environment resumable
```

---

# 四十五、工业界 Codex 也处理这种问题

Codex `thread/resume` 可以恢复已有 Thread，同时允许对 Model 等配置做 override；如果 Resume 使用与原来不同的 Model，当前实现会发出警告，并在后续 Turn 应用 Model-switch Instruction。

给 CodeTeam 的设计启示是：

```text
默认：
恢复原 Provider / Model


需要切换：
必须显式 override
```

而不要：

```text
原 Model 不可用
→ 随便找一个 Model 继续
```

Day 5 会正式处理 Model Switching。

---

# 四十六、第八步：Reconstruct Ephemeral Runtime

加载：

```text
Session
```

以后：

```text
ModelClient
ContextEngine
GitWorkspace
CheckpointManager
SafeExecutor
DockerRunner
EventSink
```

都重新创建。

例如：

```text
Session.provider_id
     ↓
ProviderRegistry
     ↓
ModelClient


Session.worktree
     ↓
WorktreeManager
     ↓
GitWorkspace


checkpoint_ids
     ↓
CheckpointStore
```

所以：

> **Session 保存的是构建 Runtime 所需要的“配方”，而不是 Runtime 本身。**

---

# 四十七、第九步：Determine Safe Resume Point

这是 Resume 的最后一个关键问题。

例如：

```text
TaskStatus:
VERIFYING

Plan:
P4 RUNNING
```

但 Crash 发生在：

```text
pytest 执行中
```

新进程不能简单：

```text
P4 继续到下一步
```

因为：

```text
Verification 没有完成。
```

合理：

```text
rerun verification
```

因为 Test 通常是可重试的 read-ish verification。

---

# 四十八、但 Patch Operation 不一样

如果：

```text
active_operation:
PATCH_APPLY
STARTED
```

然后 Crash，

不要：

```text
same patch apply again
```

应该：

```text
inspect Git status
inspect changed files
compare checkpoint
```

判断：

```text
Patch completely applied?

Not applied?

Unknown?
```

再决定：

```text
continue

regenerate

rollback

RECOVERY_REQUIRED
```

这就是：

# State Reconciliation

---

# 四十九、State Reconciliation 的正式定义

你可以记：

> **把“持久化记录的期望状态”与“当前外部世界的实际状态”进行比较，并决定是否安全继续。**

例如：

```text
Stored:
worktree HEAD = A

Actual:
worktree HEAD = B
```

需要解释。

---

```text
Stored:
checkpoint cp3 exists

Actual:
cp3 missing
```

需要恢复。

---

```text
Stored:
operation=verification started

Actual:
no process running
```

需要重新执行验证。

---

# 五十、为什么只保存 Session 不够

这是很多初级实现会犯的问题：

```text
我已经 JSON dump 了 Session，
所以 Resume 完成了。
```

不对。

假设 Session 保存：

```text
worktree=/tmp/task001
```

但：

```text
/tmp 被系统清理
```

你读 JSON 完全成功，

实际上：

```text
无法 Resume。
```

所以：

```text
Persistence
```

只是解决：

```text
“我记得什么。”
```

而：

```text
Reconciliation
```

解决：

```text
“记忆和现实还一致吗？”
```

---

# 五十一、Crash Consistency 是什么

接下来进入今天最有系统含金量的部分。

Crash Consistency：

> **程序在任意写入点突然 Crash 后，磁盘状态仍然处于一个 Runtime 可以理解和恢复的状态。**

最简单反例：

```python
with open("session.json", "w") as f:
    json.dump(session, f)
```

假设：

```text
旧 session.json
20 KB
```

`open(..., "w")` 后文件先被截断。

然后只写了：

```text
4 KB
```

突然：

```text
SIGKILL
```

磁盘：

```text
session.json

{
 "manifest": {
   "session_
```

整个 Session 损坏。

---

# 五十二、Atomic Write 是怎么解决的

MVP 推荐模式：

```text
session.json
   │
   │ 不直接修改
   ▼

session.json.tmp

write full JSON
        ↓
flush
        ↓
fsync
        ↓
replace session.json
```

Python 官方 `os.fsync()` 会强制把文件描述符对应的数据写入磁盘；对于 Python Buffered File，官方建议先 `flush()` 再 `os.fsync()`。

POSIX 的 `rename`/replace 语义则允许你在相同文件系统上通过替换目录项避免暴露“半个新文件”的普通更新窗口。

---

# 五十三、推荐概念实现

不要照抄为最终代码，但逻辑应该理解：

```python
def atomic_write_json(
    target: Path,
    payload: bytes,
) -> None:
    tmp = target.with_suffix(".tmp")

    with open(tmp, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, target)
```

这样如果 Crash 在：

```text
tmp 写一半
```

旧：

```text
session.json
```

仍然完整。

如果：

```text
replace 已完成
```

则读新 Snapshot。

---

# 五十四、为什么 Temp File 最好和目标文件同目录

因为：

```text
os.replace
```

跨 File System 可能不能直接工作。

所以：

```text
sessions/ses001/session.json.tmp

→

sessions/ses001/session.json
```

比：

```text
/tmp/random123

→

another filesystem/session.json
```

更可靠。

如果后续追求更强的掉电持久性，POSIX 系统上还可以考虑在 replace 后 `fsync` 父目录；但 Week 4 MVP 的重点先是避免进程 Crash 留下半个 Snapshot。

---

# 五十五、Atomic Write 解决不了一切

你现在有：

```text
session.json
events.jsonl
context.json
```

假设更新 Session：

```text
write session.json
↓
process crash
↓
events.jsonl 没写
```

这叫：

```text
Multi-file Consistency Problem
```

单个文件 Atomic：

```text
≠
三个文件一起 Transactional。
```

---

# 五十六、Week 4 MVP 我建议明确一个 Source of Truth

选择：

```text
session.json
=
Resume Source of Truth
```

而：

```text
events.jsonl
=
Audit / Debug


context.json
=
Derived Context State
```

于是如果：

```text
Session saved
Event 没保存
```

最坏：

```text
Event history 少了一条
```

但 Resume 状态仍然正确。

而不能反过来：

```text
events.jsonl
决定当前 Session State
```

除非你真正实现 Event Replay。

---

# 五十七、为什么长期可以考虑 SQLite

如果以后需要：

```text
Session State

Event

Context Metadata

Usage

全部一次性 Transaction 更新
```

JSON 多文件会越来越难。

SQLite 官方专门设计了事务机制，以在应用 Crash、OS Crash 甚至 Power Failure 等情况下提供 Atomic Commit；WAL/rollback journal 负责实现这类原子提交语义。

所以未来可能：

```text
SessionStore Protocol

├── JsonSessionStore   MVP
└── SqliteSessionStore Future
```

---

# 五十八、这也是为什么 Store Interface 很有价值

今天不要让：

```text
SessionService
```

到处：

```python
open("session.json")
```

而只：

```python
store.save(session)
store.load(session_id)
```

未来从：

```text
JSON
```

换成：

```text
SQLite
```

Orchestrator 不需要改。

---

# 五十九、events.jsonl 也有 Crash 问题

假设：

```jsonl
{"seq":98,...}
{"seq":99,...}
{"seq":100,"type":"repair.star
```

写第 100 行时 Crash。

Loader：

```text
不能因为最后一行坏了
整个 Event Log 都打不开。
```

MVP 可以：

```text
逐行 parse

前 99 条合法
→ 保留

最后 partial line
→ 标记/截断/忽略
```

同时：

```text
seq
```

应该严格：

```text
1
2
3
...
```

方便发现：

```text
缺失
重复
乱序
```

---

# 六十、建议 Event 模型

例如：

```python
class SessionEvent(BaseModel):
    event_id: str

    session_id: str

    seq: int

    state_version: int

    type: str

    timestamp: datetime

    payload: dict[str, object]
```

`state_version` 可以把 Event 和 Snapshot 对齐。

---

# 六十一、今天最重要的 Crash Case：进程在 Save 中途被 Kill

测试不要：

```text
真的等碰巧 Crash
```

而应该 Fault Injection。

例如：

```text
Step 1:
existing session v10

Step 2:
attempt save v11

Step 3:
在 temp write 后、
replace 前模拟异常

Step 4:
load session.json
```

必须仍然：

```text
valid v10
```

而不是：

```text
corrupted
```

这才叫 Atomic Snapshot Test。

---

# 六十二、Session Resume 与 Worktree Recovery 最容易产生什么问题

假设：

```text
Session:
PAUSED

Worktree:
task001
```

用户暂停以后手动打开 IDE：

```text
修改 task001/file.py
```

再：

```bash
codeteam resume ses001
```

这时：

```text
Session 认为 Workspace 是 S1

实际 Workspace 是 S2
```

不能：

```text
无视差异
```

应该：

```text
EXTERNAL_WORKSPACE_DRIFT
```

进入：

```text
RECOVERY_REQUIRED
```

---

# 六十三、怎样判断 External Drift

可以保存：

```text
last_known_head_sha

git status fingerprint

last_checkpoint_tree_sha
```

Resume：

```text
current HEAD
current status
```

与上次持久化状态比较。

第一版不一定做到字节级所有文件 Hash，

但至少：

```text
HEAD
+
Git status
+
Checkpoint reference
```

可以发现大量异常。

---

# 六十四、Session 保存 Usage 的意义

你要求必须保存：

```text
Usage
```

这不是为了 UI 好看。

例如 Task：

```text
已使用：
40k tokens

预算：
60k
```

进程 Crash。

如果 Resume 后：

```text
usage = 0
```

Agent 就获得了新的：

```text
60k
```

总预算实际变成：

```text
100k
```

Runtime Budget 被绕过。

所以：

```text
tokens
cost
tool calls
repair attempts
retry counts
elapsed active time
```

都应该 Durable。

---

# 六十五、Retry / Repair Counter 同理

Day 2：

```text
max_repair_attempts=3
```

Session：

```text
repair attempts = 2
```

Crash。

Resume：

如果：

```text
attempts=0
```

Agent 可以重新：

```text
再修 3 次
```

原来的 Stopping Condition 失效。

所以：

> **凡是影响 Runtime Budget / Safety / Stopping Condition 的 Counter，都应该 Durable。**

---

# 六十六、Provider / Model 为什么也必须保存

否则：

```text
前半任务：
Model A
```

Crash 后：

```text
默认 Model B
```

你之后 Evaluation：

```text
这个 Task
到底是谁完成的？
```

完全说不清。

所以至少：

```text
session.provider_id

session.model_id
```

每个 Turn 最好再单独 Event 记录。

---

# 六十七、为什么 Context 不应该全部塞 session.json

假设后面：

```text
Conversation
200 条

Tool Output
10MB

Summary
...
```

全部：

```text
session.json
```

每一次状态变化：

```text
PlanStep status changed
```

都需要重写几十 MB。

所以：

```text
session.json
=
核心 Durable State


context.json
=
Model Context State


events.jsonl
=
Append-only History
```

职责分开非常合理。

---

# 六十八、强制实验：Ctrl+C → Resume

这是今天必须真正做的一次实验。

不要只写 Unit Test。

理想流程：

```bash
codeteam run "修复登录超时问题"
```

运行到例如：

```text
Session:
ses_123

✓ Inspect
✓ Plan

→ P2 reproduce bug
```

此时：

```text
Ctrl+C
```

---

# 六十九、Ctrl+C 后应该看到

```text
Interrupting current operation...

Saving session...

Session paused:
ses_123

Resume with:
codeteam resume ses_123
```

Disk：

```text
session.json

status:
PAUSED

task status:
...

plan:
P1 COMPLETE
P2 RUNNING

worktree:
...

checkpoint:
...
```

---

# 七十、然后彻底退出 Python

不能：

```text
在同一个 Python Process
重新调用 resume()
```

那不能证明 Persistence。

必须：

```text
Process A
完全结束
```

然后新 Terminal：

```bash
codeteam resume ses_123
```

产生：

```text
Process B
```

---

# 七十一、新 Process 必须证明 6 件事

应该检查：

```text
Task 没丢

Plan 没丢

Current Step 没丢

Worktree 修改没丢

Usage 没重置

Checkpoint Chain 没丢
```

然后：

```text
继续从安全位置工作
```

这才真正达到：

```text
中断恢复
```

---

# 七十二、今天要求的测试，推荐这样定义预期

| Case | 预期 |
|---|---|
| 创建 Session | 目录与有效 Snapshot 产生 |
| save/load | Domain State 等价 |
| 新进程恢复 | 能从 Durable State 重构 |
| PAUSED → RUNNING | Reconciliation 成功后允许 |
| Session 不存在 | 明确 SESSION_NOT_FOUND |
| session.json 损坏 | 不运行 Task，报 CORRUPTED |
| Worktree missing | RECOVERY_REQUIRED / STOP |
| Main HEAD changed | 不应仅因此误判 Task 无法恢复 |
| Task Worktree drift | RECOVERY_REQUIRED |
| Cross-repo resume | 不允许静默绑定错误 Repo |

其中“Repo HEAD changed”特别建议按前面讲的：

```text
Main HEAD drift
```

和：

```text
Task Worktree drift
```

分成两个测试。

---

# 七十三、我建议额外增加 8 个高价值测试

第一个是 **Stale RUNNING**：磁盘保存 `RUNNING`，模拟进程直接 Crash，新 Runtime 加载时不得把它当正常运行，应进入 `RECOVERY_REQUIRED`。

第二个是 **Atomic Write Failure**：旧 Snapshot 为 v10，保存 v11 时在 replace 前故障，最后必须仍可加载完整 v10。

第三个是 **Partial Event Line**：`events.jsonl` 最后一行只有半条 JSON，前面的合法 Event 必须仍能读取。

第四个是 **Concurrent Resume**：两个 Process 同时 Resume 同一个 Session，只允许一个获得 Writer Ownership。

第五个是 **Checkpoint Missing**：Session 指向不存在 Checkpoint，不允许悄悄移除引用继续执行。

第六个是 **Provider Missing**：Session 正确但 Provider 配置不存在，应产生明确恢复错误而不是静默换模型。

第七个是 **Schema Version Unsupported**：明确拒绝而不是任由 Pydantic 猜字段。

第八个是 **Completed Session Resume**：如果 CodeTeam 定义一个 Session 对应一个 Task，我建议 `COMPLETED` 不重新进入 RUNNING；新的需求应该建立新 Task/Session 或未来 fork。

---

# 七十四、Completed Session 为什么我建议不能 Resume

这里和 Claude/Codex 的“Chat Session”稍有不同。

当前 Codex、Claude Code 都允许恢复一个旧对话并继续发送新的 Turn。

但你的：

```text
CodeTeam Session
```

当前更偏：

```text
一个 Coding Task Runtime
```

如果：

```text
Task:
修复 timeout

COMPLETED
```

用户又输入：

```text
再顺便给日志加追踪
```

从评测角度这是：

```text
新的 Task
```

所以第一版我建议：

```text
PAUSED
→ resume


RECOVERY_REQUIRED
→ reconcile → resume


COMPLETED
→ no resume as same task
```

未来再加：

```text
fork
continue-as-new-task
```

更清楚。

---

# 七十五、Design Decision：为什么不能 Pickle 整个 Agent

看起来最省事：

```python
pickle.dump(
    agent,
    file
)
```

第二天：

```python
agent = pickle.load(...)
```

似乎：

```text
ModelClient
Plan
Counters
Context
```

什么都有了。

实际上这是非常差的 Runtime Persistence 边界。

---

# 七十六、问题一：大量 Runtime Object 根本不应该恢复

例如：

```text
socket

Popen

Lock

thread

HTTP connection

Docker process
```

它们对应的是：

```text
昨天那个 OS Process
```

新 Process 中已经没有意义。

---

# 七十七、问题二：Persistence 与代码实现强耦合

例如今天：

```python
class Agent:
    model: ModelClient
```

明天重构：

```python
class Agent:
    provider_registry: ...
```

旧 Pickle 加载：

```text
极容易出现实现兼容问题。
```

而 JSON Domain State：

```text
schema_version=1
```

可以：

```text
Migration
```

---

# 七十八、问题三：不可观察

Pickle：

```text
binary
```

你很难：

```text
cat session
```

立即知道：

```text
当前 Plan
当前 Worktree
当前状态
```

JSON：

```text
直接 inspect
```

非常适合学习阶段和 Debug。

---

# 七十九、问题四：安全性

Python 官方文档明确警告，Pickle 并不安全；恶意 Pickle 在反序列化时可能执行任意代码，因此只能反序列化可信数据。

即使 CodeTeam 当前 Session 只来自本机，这种能力也没有必要成为 Agent State Format 的基础。

---

# 八十、推荐 Design

所以今天的正式 Decision：

```text
Durable Domain State
        ↓
JSON / JSONL
        ↓
Explicit Schema
        ↓
Runtime Reconstruction
```

而不是：

```text
Serialize Runtime Object Graph
```

---

# 八十一、Design Decision 文档可以这样写

```text
DD-W4-D4-01

Title:
Durable Domain State
vs Runtime Object Serialization

Problem:
How should CodeTeam persist an
in-progress coding task across
process restarts?

Alternative A:
Serialize the live Agent Runtime.

Alternative B:
Persist explicit domain state and
reconstruct ephemeral runtime
components on resume.

Decision:
B

Reasons:
- process resources cannot be resumed
- explicit schema evolution
- observable/debuggable state
- provider/runtime decoupling
- safer serialization boundary
- supports state reconciliation

Trade-offs:
- more explicit models
- reconstruction logic required
- schema migrations required

Evidence:
PROPOSED
```

---

# 八十二、第二个非常值得写的 Design Decision

我还建议增加：

```text
DD-W4-D4-02

Snapshot + Append-only Event Log
```

比较：

```text
Snapshot only

vs

Event only

vs

Snapshot + Events
```

第一版选：

```text
Snapshot
=
Resume Source of Truth


Events
=
Audit / Evaluation History
```

不要今天就搞完整 Event Sourcing。

---

# 八十三、Benchmark：Session Save Latency

你要求：

```text
100 / 500 / 1000 events
```

非常适合。

注意分别测：

```text
session.json save latency
```

和：

```text
event append latency
```

不要全部混成一个数字。

---

# 八十四、建议 Benchmark Dataset

构造同一个 Session，

分别：

```text
B100
events = 100

B500
events = 500

B1000
events = 1000
```

而：

```text
Task
Plan
Session Snapshot
```

尽量保持相同。

这样才能看到：

```text
Event History 规模
```

对 Load/Storage 的影响。

---

# 八十五、记录这些指标

建议结果表：

| Events | Snapshot Save P50 | P95 | Load P50 | P95 | events.jsonl Size |
|---:|---:|---:|---:|---:|---:|
| 100 | | | | | |
| 500 | | | | | |
| 1000 | | | | | |

并额外记录：

```text
session.json size

context.json size

bytes / event
```

---

# 八十六、如果 Session Load 不 Replay Event，会发生什么

按照我推荐的 MVP：

```text
load(session)
```

只读取：

```text
session.json
```

那么理论上：

```text
events 100
vs
events 1000
```

Session Load 差异应该很小。

这是一个很好的设计验证。

而：

```text
chronicle / history viewer
```

读取 Event 才随 History 增长。

这正是 Snapshot 的价值。

---

# 八十七、建议增加一个 Resume Latency

真正最重要的不是：

```text
json.load
用了多少 ms
```

而是：

```text
codeteam resume
→
Runtime Ready
```

所以额外测：

```text
Resume-to-ready latency
```

包括：

```text
load
+
reconcile git
+
checkpoint validation
+
runtime reconstruction
```

这个指标对 Agent Runtime 更有意义。

---

# 八十八、再增加 Crash Recovery Latency

模拟：

```text
status=RUNNING
active_operation=verification
process disappears
```

然后：

```text
resume
```

测：

```text
crash detection
→ reconciliation
→ resumable
```

时间。

以后就是：

```text
Recovery Time
```

---

# 八十九、今天的 Ablation：No Persistence vs Persistence

这个实验不要比较：

```text
JSON vs Pickle
```

最重要的是：

```text
No Persistence

vs

Durable Session Persistence
```

---

# 九十、实验方式

准备相同 Task：

```text
P1
P2
P3
P4
P5
```

运行：

```text
执行到 P3
```

人为：

```text
Kill process
```

---

## Group A：No Persistence

重新启动：

```text
TaskSpec
Plan
Context
Usage
```

全部丢失。

必须：

```text
重新理解任务

重新 Scan Repo

重新 Plan

重新读取文件
```

---

## Group B：Persistence

```text
load Session
↓
reconcile
↓
resume P3 / safe boundary
```

---

# 九十一、不要只比较 Restart Time

建议至少比较：

```text
Time to next productive action

Repeated model calls

Repeated tool calls

Repeated tokens

Work lost

Task completion rate
```

比如：

```text
No Persistence
```

可能 10 秒就启动程序，

但又重新：

```text
Repo scan
Plan
Context
```

耗费 2 分钟和 10k tokens。

真正重要：

```text
Time to Recover Useful Work
```

而不是：

```text
Process Startup Time
```

---

# 九十二、Ablation 还有一个很强的指标

可以定义：

```text
Rework Ratio
```

例如：

```text
Crash 前已经完成：
10 个 Tool Calls
```

无 Persistence：

```text
重新做了 8 个
```

则：

```text
Rework Ratio = 80%
```

有 Persistence：

```text
重新做 1 个 Verification
```

则：

```text
10%
```

这个指标非常能体现 Session Persistence 的价值。

---

# 九十三、Failure Case：Session File 原地写损坏

已经讲过。

解决：

```text
temp
flush
fsync
replace
```

并 Fault Injection Test。

---

# 九十四、Failure Case：多个 Durable 文件不一致

例如：

```text
session.json
version 31

context.json
version 29
```

怎么办？

建议：

```text
session.json
保存：
expected_context_version
```

如果：

```text
context_version mismatch
```

不要一定让整个 Session 死掉。

Context 通常可以：

```text
rebuild
```

所以：

```text
CONTEXT_STALE
→ rebuild
```

这正好连接明天 Day 5。

---

# 九十五、Failure Case：Stale RUNNING

程序 Crash，

磁盘：

```text
RUNNING
```

新程序：

```text
不能直接 RUNNING
```

必须：

```text
RECOVERY_REQUIRED
```

这是今天必须有的 Regression Test。

---

# 九十六、Failure Case：Concurrent Resume

两个 Runtime 同时控制：

```text
同一 Worktree
同一 Session
```

必须禁止。

第一版：

```text
Single Writer Lock
```

足够。

以后 Multi-Agent 是：

```text
不同 Worker
不同 Task/Worktree
```

不是两个 Runtime 无协调地写同一 Session。

---

# 九十七、Failure Case：Worktree 被删除

Session：

```text
valid
```

但：

```text
workspace gone
```

不能：

```text
重新创建一个空 Worktree
然后假装继续。
```

因为未提交文件状态可能已经永久丢失。

应该：

```text
RECOVERY_REQUIRED
```

根据：

```text
CheckpointStore
```

判断是否能恢复。

---

# 九十八、Failure Case：外部用户修改 Worktree

Resume 前 IDE 手动改文件。

不能：

```text
覆盖用户修改
```

也不能：

```text
无视。
```

应该：

```text
External Drift Detected
```

并提示：

```text
review
adopt
rollback
fork
```

后续再实现交互策略。

---

# 九十九、Failure Case：Main HEAD 变化导致误判

这是一个很容易写出的 Bug：

```python
if current_main_head != saved_head:
    reject_resume()
```

会让 Worktree Isolation 的价值被你自己抵消。

真正要关心：

```text
Task Worktree State
```

而不是 Main 是否继续前进。

---

# 一百、Failure Case：Checkpoint Chain 损坏

Session：

```text
cp1 → cp2 → cp3
```

但是：

```text
cp2 metadata missing
```

需要：

```text
CheckpointStore validation
```

不能仅检查：

```text
cp3 file exists
```

---

# 一百零一、Failure Case：Model/Provider 消失

原：

```text
provider-a/model-x
```

Resume：

```text
model no longer configured
```

不能：

```text
random model
```

应该：

```text
explicit error
```

或未来：

```text
--provider ...
--model ...
```

由用户显式 Override。

---

# 一百零二、Failure Case：Schema Upgrade

旧 Session：

```text
schema_version=1
```

代码：

```text
version=3
```

不要：

```text
try:
    Session.model_validate_json(...)
except:
    corrupted
```

因为：

```text
OLD
```

和：

```text
CORRUPTED
```

不是同一个问题。

以后需要：

```text
MigrationRegistry
```

---

# 一百零三、Failure Case：Disk Full

Atomic Write：

```text
tmp write
```

期间：

```text
ENOSPC
```

好消息：

```text
旧 session.json
仍然存在。
```

这正是 temp+replace 的价值。

Runtime 应：

```text
SESSION_PERSIST_FAILED
```

然后考虑：

```text
fail/pause
```

而不是继续执行大量新副作用。

---

# 一百零四、Failure Case：In-flight Side Effect 的结果不确定

这是最成熟的 Failure Case。

例如：

```text
remote push
```

执行中 Crash。

Resume：

```text
不知道 push 是否成功。
```

不能：

```text
自动重试。
```

需要：

```text
check remote state
```

这就是 Day 3 讲的：

```text
Idempotency
```

和今天：

```text
State Reconciliation
```

真正汇合的地方。

---

# 一百零五、Failure Case：Session 中泄露 Secret

Session / Event 很可能保存：

```text
Tool output
Command argv
Error
Environment
```

它们可能出现：

```text
API token
password
credential path
```

所以 Persistence 层应该：

```text
sanitize before persist
```

不要因为“这是本地文件”就完全忽略。

Claude Code 当前官方也明确说明本地 transcript 会保存 Tool 中经过的内容，而且默认是 plaintext，因此这类 Session Storage 本身就是需要认真治理的数据边界。

---

# 一百零六、今天真正推荐的代码结构

保持简单：

```text
codeteam/
└── session/
    ├── models.py
    ├── store.py
    ├── service.py
    └── errors.py
```

其中：

```text
models.py

Session
SessionStatus
SessionManifest
RepositoryRef
WorktreeRef
ActiveOperation
```

`store.py`：

```text
JsonSessionStore
```

`service.py`：

```text
SessionService
```

不要今天搞十几个文件。

---

# 一百零七、建议按 7 步实现

这是今天唯一我建议你严格按顺序做的任务清单：

1. **定义 Durable Contract**：实现 `SessionStatus`、`SessionManifest`、`Session` 和必要的 Ref Models，先明确哪些字段 Durable，哪些绝对不进 Session。
2. **实现 JsonSessionStore**：支持 `create/save/load`，`session.json` 必须使用 temp + flush/fsync + replace 方式更新。
3. **实现 Event Writer**：`events.jsonl` 增加 `seq`、`state_version`，Loader 能容忍末尾一条 partial record。
4. **实现 SessionService.pause()`**：先停止 Active Operation，再保存 `PAUSED`，绝不能先写 PAUSED 再放任子进程运行。
5. **实现 State Reconciliation**：至少检查 Repo Identity、Task Worktree、HEAD/Dirty State、Checkpoint 和 stale `RUNNING`。
6. **实现 `resume()`**：load → reconcile → reconstruct runtime → RUNNING；不要在 Store 中写 Resume 业务。
7. **最后做真正 Cross-process 验收与 Benchmark**：用两个完全不同的 Python Process 做 Ctrl+C → resume，不要用同进程模拟。

---

# 一百零八、今天的核心 Integration Architecture

最终应该逐渐变成：

```text
                       CLI
                        │
                        ▼
                 SessionService
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
    SessionStore   Reconciler    RuntimeFactory
          │             │             │
          ▼             ▼             ▼
     Durable State   Git/Worktree   ModelClient
          │          Checkpoints     ContextEngine
          │          Repo State      SafeExecutor
          │
          ▼
    session.json
    events.jsonl
    context.json
```

这里：

```text
SessionStore
```

只管：

```text
“记忆”
```

`Reconciler`：

```text
“现实”
```

`RuntimeFactory`：

```text
“重新搭机器”
```

`SessionService`：

```text
“决定能不能继续”
```

这四个职责分开，你今天的架构就已经非常健康。

---

# 一百零九、Benchmark 最终建议

除了原来的：

```text
Session save latency
Session load latency
events size
```

我建议正式记录五类指标：

| 指标 | 回答的问题 |
|---|---|
| Snapshot Save P50/P95 | 持久化状态开销多大 |
| Session Load P50/P95 | 单纯读取多快 |
| Resume-to-ready P50/P95 | Runtime 真正恢复多快 |
| Events bytes/event | 长会话磁盘增长速度 |
| Crash Recovery Latency | 非正常中断多久恢复 |

真正的：

```text
Resume-to-ready
```

比 `json.load()` 延迟更有工程价值。

---

# 一百一十、Ablation 最值得证明什么

最后的实验应该回答：

> Persistence 是否真的减少了 Agent 崩溃后的重复工作？

所以 Full 与 Ablation：

```text
A:
No Session Persistence


B:
Durable Session Persistence
```

控制：

```text
Task
Model
Repo
Kill point
```

相同。

然后比较：

```text
Time to next productive action

Repeated tool calls

Repeated model tokens

Repeated cost

Work lost

Final task success
```

不要只比较：

```text
程序重新启动花多少毫秒。
```

---

# 一百一十一、Day 4 之后应该能回答的 Interview Questions

你需要真正能回答这些问题：

**基础概念方面**：Durable State 和 Ephemeral State 有什么区别？Task、Session 和 Checkpoint 分别解决什么问题？为什么 Session 不能只是 Conversation History？Snapshot 和 Event Log 为什么都需要？

**Resume Runtime 方面**：为什么 `load()` 不等于 `resume()`？Resume 为什么需要 State Reconciliation？如果 Session 记录为 RUNNING，但旧进程已经死了怎么办？如果 Crash 发生在 Patch Apply 中间怎么办？为什么 Worktree Missing 不能简单重新创建？Main Branch HEAD 变化为什么不一定意味着 Task Session 无效？

**Persistence 方面**：为什么不能直接覆写 `session.json`？Atomic Write 怎么做？`flush()`、`fsync()` 和 replace 分别解决什么问题？为什么三个 JSON 文件无法天然形成 Transaction？什么时候应该从 JSON/JSONL 升级到 SQLite？

**设计方面**：为什么不 Pickle 整个 Agent？为什么 Runtime Object 应重建而不是恢复？为什么 Session Schema 需要 version？为什么 Usage/Repair Counter 也属于 Durable State？

**Evaluation 方面**：怎么证明 Resume 真正有效？为什么必须 Cross-process Test？怎样 Fault Injection 测 Crash Consistency？No Persistence vs Persistence 的 Ablation 应该比较哪些指标？

---

# 一百一十二、面试官如果问：“Resume 不就是把聊天历史读回来吗？”

你应该能够回答：

> 对 Coding Agent 来说，Conversation 只是 Session State 的一部分。我把 Session 设计成显式 Durable Domain State，除了 Task 和 Plan，还持久化当前执行状态、Provider/Model、Usage Budget、Task Worktree Identity、Checkpoint Chain 和可能的 In-flight Operation。`resume()` 也不是简单的 `load()`：新进程首先读取 Atomic Snapshot，然后校验 Schema、获得 Session Writer Ownership，并把持久化状态与当前 Git Repo、Task Worktree、Checkpoint 和 Provider Environment 做 State Reconciliation。如果上次进程在 RUNNING 状态异常退出，或者在副作用 Operation 中间 Crash，我不会盲目继续，而会进入 `RECOVERY_REQUIRED` 并检查 Workspace Postcondition。ModelClient、SafeExecutor、Lock 和 Process 等 Ephemeral Runtime Object 全部从 Durable Configuration 重建。Session Snapshot 用于快速恢复，JSONL Event Log 用于 Audit 和 Evaluation；第一版以 Atomic JSON Snapshot 为 Source of Truth，未来需要跨文件事务和更强并发时可以把 `SessionStore` 替换为 SQLite。

这时你讲的已经不是：

```text
Chat History Persistence
```

而是：

```text
Agent Runtime Persistence
+
Crash Recovery
+
State Reconciliation
+
Workspace Recovery
+
Schema Evolution
+
Observability
```

---

# 一百一十三、Day 4 在整个 Single-Agent MVP 中的位置

现在 Week 4 前四天终于连接起来：

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
                         Patch
                           │
                           ▼
                     Verification
                           │
                    ┌──────┴──────┐
                    ▼             ▼
                  PASS          FAILURE
                                  │
                                  ▼
                           ErrorClassifier
                                  │
                                  ▼
                         RecoveryAction
                                  │
                 ┌────────────────┼───────────────┐
                 ▼                ▼               ▼
               RETRY            REPAIR          REPLAN
                 │                │               │
                 └────────────────┴───────────────┘
                                  │
                                  ▼
                         Persistent Session
                                  │
                        ┌─────────┴─────────┐
                        ▼                   ▼
                     Process A            Crash
                                             │
                                             ▼
                                          Process B
                                             │
                                             ▼
                                      State Reconcile
                                             │
                                             ▼
                                           Resume
```

Day 1 让 Agent 知道：

```text
我要做什么。
```

Day 2 让 Agent 知道：

```text
我做得对不对。
```

Day 3 让 Agent 知道：

```text
做错后怎么办。
```

Day 4 则第一次保证：

> **即使运行 Agent 的那个 Python Process 消失，上面这些 Task、Plan、Recovery、Worktree 和 Budget 仍然不会一起消失。**

这就是从一个“可以跑几十分钟的 Agent Script”向真正 **Agent Runtime** 跨出的关键一步。