# Week5 Day 6：TaskStore + Session Integration

这次 Day6 要建立在你刚完成的 **Day5 最新 `week5` 实现**上，而不是重新设计一套持久化系统。

我先看了当前分支里 Day5 相关代码。现在你的 Multi-Agent 控制面已经明显比最初计划成熟：

- `AgentRegistry` 已经明确定位为 **live Worker 的唯一权威状态源**，维护 `WorkerRuntimeRecord`、generation、revision、heartbeat 和 restart reservation。
- `contracts.py` 已经有 `WorkerLease`、`OwnedTaskToken`、`WorkerRuntimeRecord`、`WorkerTimeoutCandidate`、`LifecyclePolicy` 等 fencing contract。
- `AgentLifecycleManager` 明确只做 **in-process liveness coordination**，不负责选任务、不负责执行任务。
- `TeamStateCoordinator` 更关键，它自己写得很明确：这是 **“one in-process transaction domain, not a durable state store”**。也就是说，你 Day5 已经解决了进程内一致性，但整个 Python 进程一死，这套状态仍然会消失。
- Day5 测试已经覆盖 timeout、CLAIMED/RUNNING recovery、generation fencing、restart cooldown、并发 sweep、stale callback 等，不需要 Day6 再重复实现这些能力。

所以今天真正的问题非常明确：

> **如何把 Day5 的“可靠内存 Runtime”变成“进程崩溃后仍可恢复的 Durable Runtime”。**

---

# 一、先把 Day5 和 Day6 的故障边界彻底分清

这是今天最重要的第一件事。

## Day5：Worker 挂了，但 CodeTeam Runtime 还活着

例如：

```text
CodeTeam Process
│
├── Scheduler      alive
├── Registry       alive
├── Lifecycle      alive
│
├── Worker A       CRASH
├── Worker B       alive
└── Worker C       alive
```

这时候：

```text
Heartbeat timeout
        ↓
Registry: A FAILED
        ↓
Scheduler: reclaim T1
        ↓
T1 → READY
        ↓
B / restart A 再认领
```

Day5 能解决。

---

## Day6：整个 CodeTeam Process 挂了

例如：

```text
CodeTeam Process
    ↓
SIGKILL / crash

Scheduler      消失
Registry       消失
Mailbox        消失
Lifecycle      消失
Python objects 消失
```

这时候 Day5 的 Heartbeat 完全没用。

因为：

> 连负责检测 Heartbeat 的进程本身都没了。

今天要做到：

```text
Process A

Task T1 RUNNING
Worker A BUSY
Mailbox 有 3 条消息

        ↓

      kill

        ↓

Process B

        ↓

load durable state

        ↓

reconcile

        ↓

rebuild Runtime

        ↓

继续执行
```

这就是：

# Durable Agent State

---

# 二、什么叫 Durable Agent State？

通俗地说：

> **Runtime 中真正决定“任务下一步怎么走”的东西，不能只放在 Python dict 里。**

目前你的 Day5 有大量类似：

```text
AgentRegistry
TaskScheduler
AgentMailbox
```

内部状态。

但是 Python 对象：

```text
RAM
```

不是可靠存储。

所以要把：

```text
Memory State
```

转换为：

```text
Durable State
```

---

# 三、哪些东西必须保存？

一个非常常见的错误：

> “那我把所有 Python 对象 pickle 一下不就行了？”

不对。

工业 Runtime 通常会明确区分三类数据：

```text
A. 必须持久化

B. 可以重建

C. 绝对不应该恢复
```

---

# 四、CodeTeam 中必须持久化的内容

## 1. Task

例如：

```text
T1
Implement backend API

status = RUNNING
owner = worker-1
attempt = 2
```

至少包括：

```text
node_id
role
status
owner_id
owner_generation
attempt
failure_reason
```

否则 restart 后：

> 连哪些 Task 完成过都不知道。

---

## 2. DAG

例如：

```text
A ──→ C
B ──→ C
```

必须保存：

```text
A → C
B → C
```

否则：

Task 都恢复了，

Scheduler 却不知道：

```text
C 为什么不能执行？
```

---

## 3. Agent Identity / Durable Metadata

例如：

```text
worker-1
role=BACKEND
capabilities=[python, pytest]
generation=2
```

但是这里有一个非常重要的细节：

> 保存的是 **Agent 的身份和恢复信息**，不是 `WorkerAgent` Python object。

---

## 4. Message

你现在的 Mailbox 还是：

```python
dict[str, deque[AgentMessage]]
```

并维护：

```python
_seen_message_ids
```

也就是说当前 mailbox 本质还是内存结构；如果整个进程挂掉，队列内容和 dedup state 都会消失。

所以至少需要保存：

```text
message_id
sender
recipient
type
task_id
node_id
correlation_id
payload
delivery state
```

---

## 5. Event

例如：

```text
TASK_CLAIMED
WORKER_FAILED
TASK_REQUEUED
WORKER_RESTARTED
```

用来回答：

> “系统为什么变成现在这个状态？”

---

# 五、哪些东西不应该直接恢复？

这一点比“保存什么”更重要。

## 1. Python Lock

例如：

```python
RLock()
Lock()
```

不能持久化。

Process B：

必须创建新的。

---

## 2. Thread

不能：

```text
恢复旧线程
```

必须重新启动。

---

## 3. SQLite Connection / socket / callback

全部重新构建。

---

## 4. WorkerAgent object

保存：

```text
AgentInfo
```

然后：

```text
WorkerFactory
    ↓
new WorkerAgent(...)
```

---

# 六、最重要的一个：`runtime_id` 不能恢复成旧 Runtime

你现在 `TeamStateCoordinator`：

```python
runtime_id = f"team-runtime-{uuid4().hex}"
```

而且源码自己明确说明：

> 它是 **in-process transaction domain，不是 durable store**。

所以：

```text
Process A
runtime_id = R1
```

挂了。

Process B 必须：

```text
runtime_id = R2
```

绝对不能：

```text
reload R1
```

然后假装旧 Runtime 还活着。

---

## 为什么？

因为你 Day5 已经使用：

```text
WorkerLease
=
runtime_id
+
worker_id
+
generation
``` 


这其实是非常好的 fencing。

旧 Process A 的：

```text
WorkerLease(R1, worker-1, generation=2)
```

到了 Process B：

```text
current runtime = R2
```

自然失效。

这意味着：

> **进程重启本身就是一个新的 Runtime epoch。**

这个概念非常工业化。

---

# 七、第二个绝对不能直接恢复的东西：monotonic heartbeat 时间

Day5 你已经正确用了：

```python
time.monotonic()
```

做 heartbeat timeout。

例如：

```text
Process A:

last_heartbeat_monotonic = 9382.3
```

Process A 死了。

Process B：

自己的 monotonic clock 起点可能完全不同。

所以不能：

```text
load 9382.3
↓
继续算 heartbeat timeout
```

---

正确做法：

```text
旧 heartbeat
只作为历史信息

Process restart
↓
所有旧 live-worker liveness 失效
↓
重新创建 Worker
↓
设置新的 heartbeat baseline
```

这是今天必须写进 Design Decision 的 invariant：

> **Monotonic liveness timestamps are process-local and must never be treated as durable cross-process time.**

---

# 八、工业界怎么做：Temporal

Temporal 是今天最值得学习的系统之一。

它的核心目标就是：

> 执行过程中即便进程崩溃、网络中断、基础设施故障，Workflow 也可以从之前的 durable execution state 恢复。Temporal 官方直接把这种能力描述成 crash-proof execution。

可以把 Temporal 理解成：

```text
Workflow Code
      ↓
Durable History
      ↓
Worker crashes
      ↓
new Worker
      ↓
reconstruct execution
```

---

## 映射到 CodeTeam

Temporal：

```text
Workflow
```

对应：

```text
Task DAG
```

Temporal：

```text
Activity
```

对应：

```text
Worker Task Attempt
```

Temporal：

```text
Event History
```

对应：

```text
AgentEvent / TaskEvent
```

Temporal：

```text
Worker Retry
```

对应：

```text
Worker generation
Task attempt
```

---

# 九、但是不要简单说“CodeTeam 使用 Temporal Event Sourcing”

因为你目前并没有实现完整 Temporal 模式。

这就涉及今天第二个核心概念：

# Event Sourcing

---

# 十、什么是 Event Sourcing？

普通数据库思路：

你只保存：

```text
T1 status = COMPLETED
```

你只知道：

> 现在是什么状态。

---

Event Sourcing：

不保存“结果”作为唯一事实。

保存：

```text
EVENT 1
TASK_CREATED

EVENT 2
TASK_READY

EVENT 3
TASK_CLAIMED(worker1)

EVENT 4
TASK_STARTED

EVENT 5
WORKER_FAILED

EVENT 6
TASK_REQUEUED

EVENT 7
TASK_CLAIMED(worker2)

EVENT 8
TASK_COMPLETED
```

然后：

```text
Event 1
+
Event 2
+
...
+
Event 8

        ↓ replay

T1 = COMPLETED
```

也就是：

> **Event log 才是 Source of Truth。**

---

# 十一、你的 Week4 Session 其实已经接近这个问题了

你现在的：

```text
JsonSessionStore
```

已经非常不错。

它采用：

```text
session.json
=
当前 durable snapshot

events.jsonl
=
append-only audit history
```

`session.json` 使用 temp → flush → fsync → `os.replace` 做 crash-safe 替换；`events.jsonl` append 后 flush + fsync，并允许恢复时丢弃末尾半条损坏记录。

而且事件带：

```text
seq
state_version
```

用来和 Snapshot 对齐。

---

# 十二、但这严格来说不是 Pure Event Sourcing

你的 Session 现在是：

```text
session.json
     ↓
恢复的主要状态

events.jsonl
     ↓
审计 / debugging
```

而不是：

```text
events.jsonl
     ↓ replay
重建整个 Session
```

所以更准确叫：

> **Snapshot + Append-only Event Log**

这其实非常适合 CodeTeam。

---

# 十三、Day6 我不建议你实现“纯 Event Sourcing”

三个方案：

## 方案 A：只有 Snapshot

```text
SQLite current state
```

优点：

简单。

缺点：

无法回答：

> 为什么这个 Task 又 READY 了？

---

## 方案 B：Pure Event Sourcing

```text
Events
  ↓ replay
Everything
```

优点：

历史非常完整。

缺点：

- recovery 慢
- migration 复杂
- replay correctness 难
- 你当前状态机非常复杂
- 开发成本过高

---

## 方案 C：Current State + Event Log

推荐：

```text
SQLite

Current State Tables
+
Append-only Events
```

恢复：

```text
直接 load current state
```

调试：

```text
query events
```

这是当前 CodeTeam 最合适的。

---

# 十四、所以今天的正确表述

以后面试不要说：

> “我实现了完整 Event Sourcing。”

如果你按照今天方案做，应该说：

> **我采用 durable state snapshot + append-only event history 的混合模型。当前状态用于快速恢复，事件流用于审计、tracing 和 failure analysis。**

这更准确。

---

# 十五、工业案例：Kubernetes 的 Recovery 思想

Kubernetes Controller 的核心不是：

> “恢复之前那个 Python/Go 函数执行到第几行。”

而是：

```text
读取 Desired State

+

读取 Current State

        ↓

Reconcile
```

Controller 不断比较期望状态与真实状态，然后修正差异。Kubernetes 官方对 reconciliation loop 的描述也是：事件进入队列，Reconcile 读取当前状态，决定需要创建、修改或删除什么，然后新的状态变化再次产生事件。

这对 CodeTeam 特别重要。

Process crash 后：

不要想：

> “怎么让 scheduler.run() 从上一行继续？”

而应该：

```text
Durable Task State
+
Git Worktree State
+
Checkpoint State
+
Agent State
+
Mailbox State

          ↓

      Reconcile

          ↓

construct new Runtime
```

这才是 Runtime 思维。

---

# 十六、工业案例：Microsoft AutoGen

AutoGen Team 提供：

```text
save_state()
load_state()
```

并且保存 Team 中各 participant 和 group-chat manager 的状态。官方也明确提醒：如果 Team 正在运行时直接 `save_state()`，得到的状态可能不一致，因此推荐在 Team 停止或安全边界保存。

这恰好说明：

> **Multi-Agent persistence 最大问题并不是“JSON 怎么写”，而是怎样拿到一致的 multi-component snapshot。**

这就是你 Day5 `TeamStateCoordinator` 的价值。

---

# 十七、工业案例：阿里 AgentScope

AgentScope V2 对这件事划分得非常清楚：

```text
AgentState
→ AgentStateStore

Workspace durable artifacts
→ Workspace Storage
```

`AgentStateStore` 保存 conversation、summary、permission、tool state 等可恢复运行状态；Workspace 另存 session log、memory、files 等长期产物。生产多副本场景还建议将本地 JSON store 替换为 Redis/MySQL 等分布式后端。

这个设计和你的项目应该非常接近：

```text
Session / Team Runtime State
       ≠
Git Worktree
```

---

# 十八、CodeTeam Day6 最重要的架构原则：不要产生双 Source of Truth

你已经有：

```text
JsonSessionStore
```

今天再加：

```text
TaskStore(SQLite)
```

最大的危险是：

```text
session.json
说 Task = RUNNING

SQLite
说 Task = READY
```

然后：

> 到底听谁的？

---

# 十九、今天必须明确 Authority Boundary

建议正式定义：

## `JsonSessionStore`

继续负责：

```text
Session identity
Repository identity
provider / model
top-level SessionStatus
worktree references
checkpoint references
single-agent resume metadata
```

它现在已经是成熟实现，不要重写。

---

## 新 `TeamStateStore`

负责：

```text
Task nodes
Task runtime states
DAG dependencies
Agent identities/runtime metadata
Mailbox durable state
Scheduler queue state
Team runtime events
```

---

## Git / Worktree

负责：

```text
真实代码副作用
```

---

所以：

```text
SessionStore
≠
TeamStateStore
≠
Workspace
```

三者生命周期不同。

---

# 二十、TaskStore 这个名字其实已经有一点不准确

原计划：

```text
task_store.py
```

但你现在要求它保存：

```text
Task
DAG
Agent
Message
Event
```

其实已经不仅仅是 TaskStore。

所以我建议：

文件仍然按计划：

```text
codeteam/agent_team/task_store.py
```

但是核心 abstraction 叫：

```python
TeamStateStore
```

实现：

```python
SQLiteTeamStateStore
```

比：

```python
class TaskStore:
```

更准确。

---

# 二十一、为什么 Day6 使用 SQLite 很合适？

现在你的目标是：

```text
local-first Coding Agent Runtime
```

SQLite 的优点：

```text
不需要 server
单文件
transaction
crash recovery
index
schema
SQL query
```

对于：

```text
1~几十个 Worker
几百~几千 Task
单机 Runtime
```

非常合适。

没必要马上：

```text
Redis
PostgreSQL
Kafka
```

---

# 二十二、我建议直接用 Python stdlib `sqlite3`

不要今天引入：

```text
SQLAlchemy
```

你最需要学习的是：

```text
transaction boundary
consistency
recovery
```

而不是 ORM。

---

# 二十三、SQLite 文件放在哪里？

不要：

```text
repo/
codeteam.db
```

更不要放 Worker Worktree。

因为 Worktree：

可能：

```text
rollback
delete
recreate
```

---

最好直接利用你现有 Session Layout：

```text
.codeteam/
└── sessions/
    └── ses_xxxx/
        ├── session.json
        ├── events.jsonl
        ├── context.json
        ├── model_outputs.jsonl
        └── team_state.sqlite3
```

这样：

> 一个 Session 对应一个 Team Runtime DB。

这个模型和你现有 `SessionWriterLock` 也非常匹配。

---

# 二十四、推荐 SQLite Schema

不建议所有东西：

```text
dump成一个巨大 JSON blob
```

否则 SQLite 没什么意义。

建议至少：

```text
runtime_meta
tasks
task_dependencies
agents
messages
ready_queue
events
```

---

# 二十五、`runtime_meta`

例如：

```text
schema_version
store_revision
last_event_seq
created_at
updated_at
previous_runtime_id
```

注意：

```text
previous_runtime_id
```

只能用于：

> audit

不能：

> restore 为当前 runtime_id。

---

# 二十六、`tasks`

建议至少：

```text
node_id            PRIMARY KEY

role
task_payload_json

status
owner_id
owner_generation

attempt
failure_reason

claimed_at
revision
```

其中：

```text
task_payload_json
```

保存：

- goal
- assignment
- metadata

这种不需要 SQL query 的静态结构。

而：

```text
status
attempt
owner
```

作为真正 column。

因为恢复时经常查询：

```sql
WHERE status = 'ready'
```

---

# 二十七、`task_dependencies`

```text
prerequisite_id
dependent_id
```

组合主键：

```text
(prerequisite_id, dependent_id)
```

并加 foreign key。

---

# 二十八、`agents`

保存：

```text
worker_id
role
capabilities_json

generation
revision
status

restart_attempts
```

但请注意：

```text
last_heartbeat_monotonic
```

不要作为跨进程恢复依据。

可以：

- 不保存；
- 或只作为 debug metadata 保存。

恢复时一定 reset。

---

# 二十九、`messages`

建议：

```text
message_id PRIMARY KEY
sender_id
recipient_id
type
task_id
node_id
correlation_id
payload_json

delivery_status
created_at
sequence
```

---

# 三十、为什么要保存 `message_id`？

你 Day4 已经做：

```text
_seen_message_ids
```

来防重复。

Process restart 后如果：

```text
seen ids
```

没保存：

旧消息重新发送：

Runtime 可能重新接受。

所以 dedup state 也属于 Durable State。

---

# 三十一、`ready_queue`

一种偷懒方式：

Restart 后：

```text
SELECT *
FROM tasks
WHERE status='READY'
ORDER BY node_id
```

重新生成 queue。

对于当前项目可能可以。

但这会改变：

```text
原 Scheduler queue ordering
```

如果后面加入：

```text
priority
fairness
ready timestamp
```

问题就出现。

所以可以存：

```text
queue_position
node_id
```

或者存：

```text
ready_seq
```

然后重建。

---

# 三十二、`events`

建议：

```text
seq INTEGER
event_type TEXT

runtime_id TEXT
transaction_id INTEGER/TEXT
transaction_event_index INTEGER

worker_id
node_id
attempt

payload_json
created_at
```

你的 Day5 已经为事件放入：

```text
runtime_id
transaction_id
transaction_event_index
```

这其实正好为 Durable Event History 做准备。

Day5 测试甚至验证了 Worker failure 与 Task recovery 事件属于同一个 transaction，并保持 event index 顺序。

这部分设计非常值得保留。

---

# 三十三、SQLite 初始化建议

连接创建时：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
```

---

## `foreign_keys = ON`

SQLite foreign key 不应该假设默认开启；官方建议应用明确设置。

---

## WAL

未来你的：

```text
CLI / TUI / API
```

可能同时读取状态。

WAL 比 rollback journal 更适合：

```text
1 writer
+
multiple readers
```

的控制面。

---

## `synchronous=FULL`

今天你做的是：

> Failure Recovery。

所以 correctness 应该优先。

SQLite 官方说明，在 WAL 模式下 `FULL` 提供更强的断电 durability；`NORMAL` 对应用进程 crash 仍能保持事务一致性，但断电情况下最后 commit 可能丢失。

所以：

```text
Day6 默认 FULL
```

以后 Benchmark 再决定是否：

```text
FULL → NORMAL
```

---

# 三十四、SQLite 最核心知识：Transaction

今天不要把数据库理解成：

> “保存 Python 对象的地方。”

真正价值是：

# Atomic State Transition

例如 Worker timeout：

最终业务变化实际上是：

```text
Worker:
BUSY → FAILED

Task:
RUNNING → FAILED → READY

Task.owner:
worker-1 → NULL

Event:
WORKER_FAILED
TASK_FAILED
TASK_REQUEUED
```

这五件事情逻辑上：

> 是一个 transaction。

---

# 三十五、错误写法

```python
update_worker()

commit()

update_task()

commit()

append_event()
```

如果中间 crash：

```text
Worker = FAILED

但是

Task = RUNNING
owner = worker-1
```

出现：

# Torn State

---

# 三十六、正确做法

```text
BEGIN

update Worker

update Task

update Queue

append Event1

append Event2

append Event3

COMMIT
```

要么：

```text
全部成功
```

要么：

```text
全部没有发生
```

SQLite transaction 原生提供这种保证。

---

# 三十七、这和你 Day5 的 TeamStateCoordinator 正好能接上

Day5：

```text
TeamStateCoordinator
```

解决：

```text
in-memory atomicity
```

Day6：

```text
SQLite transaction
```

解决：

```text
durable atomicity
```

最终目标：

```text
            one logical transition

                   ↓

       TeamStateCoordinator

                   ↓

           prepare new state

                   ↓

          SQLite Transaction

                   ↓

                COMMIT

                   ↓

          publish/ack success
```

这就是非常标准的 Runtime engineering 思路。

---

# 三十八、不要把 `event_sink` 当 Durable Commit

这个区别很重要。

现在 Day5 的 event observer：

```text
state commit
   ↓
event sink
```

observer 失败不会反向破坏已经成功的内存状态。

这对于：

```text
logging
metrics
UI
```

是正确的。

但是：

> Durable Store 不能只是一个普通 best-effort event observer。

因为：

```text
内存状态成功
↓
进程突然 kill
↓
SQLite event 还没写
```

状态就丢了。

所以需要明确：

```text
Observability Sink
!=
Durability Boundary
```

这是 Day6 非常重要的 Design Decision。

---

# 三十九、Store Revision / CAS

你 Day5 已经用了：

```text
WorkerRuntimeRecord.revision
``` 


SQLite 也可以利用同样思想：

例如：

```sql
UPDATE tasks
SET status=?, revision=revision+1
WHERE node_id=?
AND revision=?
```

如果：

```text
affected rows = 0
```

说明：

> 你正在用旧状态写数据库。

也就是：

```text
stale writer
```

这个机制后面如果你有：

```text
API thread
CLI
background recovery
```

会很有价值。

---

# 四十、Day6 的 Recovery 绝对不是简单 `load()`

一个成熟恢复流程应该是：

```text
Load

↓

Validate

↓

Reconcile

↓

Reconstruct

↓

Resume
```

不是：

```python
state = db.load()
scheduler = state
```

---

# 四十一、Step 1：Load

读取：

```text
Session

Team DB

Tasks

DAG

Agents

Messages

Events
```

---

# 四十二、Step 2：Validate

检查：

```text
schema_version supported?

所有 dependency task 都存在？

Task owner 对应 Agent 是否存在？

READY task 是否有 owner？

COMPLETED task 是否仍有 owner？

message sender/recipient 是否存在？
```

SQLite foreign key 可以帮你挡住部分错误。

---

# 四十三、Step 3：Reconcile

这是最重要一步。

你已经有非常成熟的：

```text
SessionReconciler
```

它当前会比较：

- repository
- base SHA
- worktree
- dirty state
- checkpoint
- provider
- in-flight operation 


所以 Team Recovery 应该继续这个思想。

---

# 四十四、不同 Task 状态在 Process Restart 后怎么处理？

## `PENDING`

```text
PENDING → PENDING
```

安全。

---

## `READY`

```text
READY → READY
```

安全。

重新放入 ready queue。

---

## `COMPLETED`

```text
COMPLETED → COMPLETED
```

绝不能重新执行。

---

## `FAILED / BLOCKED`

保持。

---

# 四十五、`CLAIMED` 怎么办？

例如：

```text
Worker A
刚 claim T1

但还没 start

↓

Process Crash
```

理论上还没有 side effect。

可以：

```text
CLAIMED
    ↓
recovery
    ↓
READY
```

下一次：

```text
attempt + 1
```

比较合理。

---

# 四十六、最危险的是 `RUNNING`

例如：

```text
T1 RUNNING

Worker 已经：

修改了一半 auth.py
执行过 migration
apply patch
```

然后 Process Crash。

你不能：

```text
RUNNING
 ↓
READY
 ↓
重新执行
```

无脑重试。

因为这可能产生：

```text
duplicate side effects
```

---

# 四十七、这里必须复用 Week3 / Week4 的能力

你已经有：

```text
Worktree
Checkpoint
Git state
SafeExecution
```

所以恢复：

```text
RUNNING Task
      ↓
inspect worktree
      ↓
inspect checkpoint
      ↓
inspect active operation
```

如果确认：

```text
可安全 replay
```

再：

```text
READY
```

否则：

```text
RECOVERY_REQUIRED
```

---

# 四十八、这是你的项目比普通 Multi-Agent Demo 更应该强调的地方

很多 Demo：

```text
crash
→ retry
```

就结束了。

Coding Agent 不能这样。

因为 Coding Agent 有：

```text
filesystem side effect
git side effect
command side effect
```

真正安全的恢复逻辑应该是：

```text
Crash Recovery
=
Durable State
+
External World Reconciliation
```

这和 Kubernetes Controller 思想完全一致。

---

# 四十九、你的现有 SessionService 已经采取 fail-closed

当前 `SessionService.resume()`：

```text
load session
↓
acquire writer lock
↓
reconcile
```

如果发现：

```text
disk says RUNNING
但没有活跃 writer
```

`SessionReconciler` 会把它视为：

```text
RECOVERY_REQUIRED
```

而不是直接继续运行。

这是对的。

---

# 五十、所以 Day6 不要破坏这个安全设计

目标不是：

```text
kill

↓

resume

↓

无条件继续
```

而应该：

```text
kill

↓

restart

↓

resume

↓

发现 stale RUNNING

↓

Team Recovery Reconcile

↓

安全处理 inflight task

↓

构造新 Runtime

↓

RUNNING
```

---

# 五十一、现有 SessionService 已经留好了非常漂亮的扩展点

你现在：

```python
RuntimeFactory = Callable[[Session], Any]
```

并且 `resume()` 在 reconcile 成功后：

```text
runtime_factory(session)
```

重新构建 ephemeral runtime。

这意味着你 Day6 不需要：

> 重写 Session Persistence。

只需要实现类似：

```text
TeamRuntimeFactory
```

负责：

```text
Session
  ↓
TeamStateStore.load()
  ↓
new TeamStateCoordinator
  ↓
new AgentRegistry
  ↓
new TaskScheduler
  ↓
new Mailbox
  ↓
new LifecycleManager
```

这就是今天和真实仓库最重要的结合点。

---

# 五十二、Recovery 后一定创建新的 TeamStateCoordinator

再次强调：

```text
DB:

previous_runtime_id = R1
```

Process B：

```python
TeamStateCoordinator()
```

得到：

```text
R2
```

然后：

```text
old WorkerLease(R1)
```

全部失效。

这就是正确 fencing。

---

# 五十三、Agent 恢复怎么做？

数据库保存：

```text
worker_id
role
capabilities
generation
status
```

但是 restart 后不能说：

```text
worker.status = BUSY
```

然后继续。

因为旧 Worker process/object 根本不存在。

应该：

```text
load durable AgentInfo

↓

WorkerFactory

↓

new WorkerAgent

↓

register into new Registry

↓

activate

↓

READY
```

---

# 五十四、generation 应该怎么处理？

至少有两个 fencing 维度：

```text
runtime_id

generation
```

Process restart：

```text
runtime_id
R1 → R2
```

已经足够挡住旧 callback。

可以保留：

```text
previous generation
```

用于 audit。

然后新 Registry：

可以：

```text
generation = previous + 1
```

或者新 runtime 内重新起 generation。

我更建议：

> 保持 generation 单调增加。

这样 Trace 更容易解释：

```text
worker-1

generation 1
generation 2
generation 3
```

---

# 五十五、Message Recovery 是 Day6 一个容易忽略的大坑

当前：

```python
receive()
```

实际上：

```python
popleft()
```

也就是取到消息后立刻从 inbox 删除。

考虑：

```text
receive message M1

↓

M1 从 queue 删除

↓

还没真正处理

↓

Process SIGKILL
```

restart：

M1 没了。

这就是：

# Lost Message Window

---

# 五十六、工业 Message Queue 怎么解决？

典型设计：

```text
PENDING
  ↓
DELIVERED / IN_FLIGHT
  ↓
ACKED
```

Consumer：

```text
receive

≠

delete
```

而是：

```text
receive
↓
mark IN_FLIGHT
↓
processing
↓
ack
```

如果 Consumer crash：

```text
IN_FLIGHT timeout
↓
PENDING
```

这就是：

```text
at-least-once delivery
```

---

# 五十七、Day6 要不要现在完全重写 Mailbox？

我建议：

## Day6 必做

至少支持：

```text
pending messages restore

seen_message_ids restore
```

---

## 进阶项

增加：

```text
receive()
+
ack()
```

以及：

```text
PENDING
IN_FLIGHT
ACKED
```

如果一天时间有限：

先记录为：

```text
Known Limitation
```

但面试一定要知道。

---

# 五十八、SQLite TeamStateStore 推荐 API

不要设计成：

```python
save_task()
save_agent()
save_message()
save_event()
```

然后上层自己随便调用。

因为这样特别容易破坏 transaction。

---

我更建议围绕：

# Snapshot / Transaction

例如概念接口：

```python
class TeamStateStore(Protocol):

    def initialize(
        self,
        snapshot: TeamStateSnapshot,
    ) -> None:
        ...

    def load(
        self,
    ) -> TeamStateSnapshot:
        ...

    def commit(
        self,
        snapshot: TeamStateSnapshot,
        events: tuple[AgentEvent, ...],
        *,
        expected_revision: int,
    ) -> TeamStateSnapshot:
        ...

    def load_events(
        self,
        *,
        after_seq: int = 0,
    ) -> tuple[DurableEvent, ...]:
        ...
```

这样：

```text
one logical runtime transition
=
one durable commit
```

---

# 五十九、推荐增加 `TeamStateSnapshot`

不要让 TaskStore 直接读取：

```text
scheduler._records
registry._records
mailbox._inboxes
```

定义正式 Contract：

```text
TeamStateSnapshot
├── tasks
├── dependencies
├── workers
├── ready_queue
├── messages
├── revision
└── previous_runtime_id
```

这会成为：

```text
Runtime
↔
Persistence
```

之间的边界。

---

# 六十、为什么不能分别 Snapshot？

错误：

```text
scheduler.snapshot()

↓

过了 10ms

↓

registry.snapshot()

↓

过了 10ms

↓

mailbox.snapshot()
```

中间状态可能已经变化。

最后得到：

```text
Task says:
owner=worker1

Registry says:
worker1 READY
```

不一致。

---

所以需要：

```text
consistent Team Snapshot
```

AutoGen 官方提醒“运行中的 Team 保存 state 可能不一致”，本质就是这个问题。

你的 `TeamStateCoordinator` 正好应该成为这个 consistency boundary。

---

# 六十一、Schema Version

你现有 SessionStore 已经很正确地做：

```text
schema_version gate
```

而且明确：

> future schema 不能让 Pydantic 靠默认值“猜”。

SQLite 也应该一样。

推荐：

```sql
PRAGMA user_version = 1;
```

或者：

```text
runtime_meta.schema_version
```

加载时：

```text
v1 → supported

v0 → migrate

v99 → reject
```

不要：

```text
missing column
→ 给默认值
→ 假装恢复成功
```

---

# 六十二、Day6 完整恢复流程

最终应该是：

```text
                 codeteam resume

                       ↓

              JsonSessionStore.load

                       ↓

               SessionWriterLock

                       ↓

                SessionReconcile
                repo / worktree
                 checkpoint

                       ↓

             SQLiteTeamStateStore

                       ↓

                 load snapshot

                       ↓

              validate Team state

                       ↓

          reconcile inflight Tasks

                       ↓

          new TeamStateCoordinator
             runtime_id = NEW

                       ↓

               rebuild Registry

                       ↓

               rebuild Scheduler

                       ↓

               rebuild Mailbox

                       ↓

              LifecycleManager

                       ↓

               persist recovery

                       ↓

                     RUN
```

这就是今天真正的架构。

---

# 六十三、测试：不要只写 `save → load`

最基础当然要：

```text
save

↓

load

↓

equal
```

但 Day6 的核心是：

> kill process。

所以测试一定分三层。

---

# 六十四、Level 1：SQLite Unit Test

至少覆盖：

### 1. Empty DB initialize

```text
schema 正确创建
```

### 2. Task round-trip

```text
Task → DB → Task
```

### 3. DAG round-trip

```text
A→B,C
```

恢复完全一致。

### 4. Agent round-trip

role、generation、capabilities。

### 5. Message round-trip

payload / message id / queue order。

### 6. Event order

```text
seq 1
seq 2
seq 3
```

不重复。

### 7. Transaction rollback

故意在：

```text
update Worker
```

之后抛异常。

验证：

```text
Worker
Task
Event
```

一个都没 commit。

---

# 六十五、Level 2：Runtime Reconstruction Test

构造：

```text
A COMPLETED

B RUNNING

C READY
```

然后：

```text
persist

↓

destroy all Python objects

↓

load

↓

create entirely new Runtime
```

注意：

不要：

```text
reuse old scheduler
```

测试真正的：

```text
new object graph
```

---

验证：

```text
new runtime_id != old runtime_id
```

非常重要。

---

# 六十六、旧 WorkerLease 必须失效

例如：

```text
old lease:

runtime_id = R1
worker = w1
generation = 2
```

resume：

```text
runtime_id = R2
```

调用：

```text
heartbeat(old lease)
```

必须失败。

这个测试和你 Day5 stale-generation tests 是天然衔接。

---

# 六十七、Level 3：真正 Kill Process

这是今天最有价值的 Integration Test。

Parent：

```text
启动 child runtime
```

Child：

```text
create session
↓
build DAG
↓
claim task
↓
start task
↓
persist state
```

Parent：

```text
SIGKILL child
```

不要：

```text
graceful shutdown
```

否则没有测试 crash。

---

然后启动：

```text
Process 2
```

执行：

```text
resume
```

验证。

---

# 六十八、Kill Test 应该验证哪些东西？

## Completed Task

```text
COMPLETED
```

必须仍：

```text
COMPLETED
```

不能重复执行。

---

## READY Task

继续：

```text
READY
```

---

## RUNNING Task

不能静默变：

```text
RUNNING
```

应该经过：

```text
recovery reconciliation
```

---

## Worker

旧：

```text
BUSY
```

不能继续 BUSY。

必须重新实例化。

---

## Message

Pending message：

必须仍然存在。

---

## Events

例如：

```text
before crash seq=100
```

恢复后：

```text
next event seq=101
```

不能重新从：

```text
1
```

开始。

---

# 六十九、一个非常重要的测试：DB transaction 中途 kill

例如：

```text
BEGIN

update Worker

update Task

   ← kill here
```

Restart 后 SQLite 应该：

```text
rollback uncommitted transaction
```

而不是得到半个 transaction。

这正是 SQLite crash recovery 的价值；它的 rollback journal/WAL 正是用来在 crash 后恢复一致数据库状态。

---

# 七十、还有一个测试：双 Resume

你现有：

```text
SessionWriterLock
```

就是用来避免：

```text
Process A resume session-X

同时

Process B resume session-X
```

两边同时执行。

Day6 不要因为 SQLite 自己有锁就删除这层。

SQLite 解决：

```text
database write serialization
```

SessionWriterLock 解决：

```text
application ownership
```

这是不同问题。

---

# 七十一、Benchmark：1000 Tasks 怎么正确测？

原计划：

```text
1000 tasks

load latency
recovery time
```

这个方向正确，但两个指标必须定义清楚。

---

# 七十二、Metric 1：Load Latency

不要模糊说：

```text
db.load()
```

定义：

> 从打开 SQLite 到得到经过 Pydantic validation 的 `TeamStateSnapshot`。

即：

```text
open db

↓

read runtime_meta

↓

read 1000 tasks

↓

read dependencies

↓

read workers/messages

↓

deserialize

↓

validate

↓

TeamStateSnapshot ready
```

记作：

```text
T_load
```

---

# 七十三、Metric 2：Runtime Hydration Latency

这个最好额外记录。

```text
TeamStateSnapshot

↓

new Coordinator

↓

new Registry

↓

new Scheduler

↓

new Mailbox

↓

new Lifecycle
```

记作：

```text
T_hydrate
```

---

# 七十四、Metric 3：Recovery Time

真正：

```text
T_recovery
=
T_load
+
T_reconcile
+
T_hydrate
+
T_persist_recovery
```

最终终点：

> Scheduler 能够再次安全 `schedule/claim`。

这才叫：

```text
Recovery Ready
```

---

# 七十五、Benchmark 数据集

至少：

```text
1000 Tasks

≈ 2000~3000 dependencies

30~50 Workers

1000+ Messages

10000 Events
```

Task DAG 不要全：

```text
A→B→C→D
```

建议混合：

```text
chain

fan-out

fan-in

layered DAG
```

---

# 七十六、测试次数

不要只跑：

```text
一次 42ms
```

至少：

```text
20~30 runs
```

统计：

```text
p50
p95
min
max
```

---

# 七十七、Cold vs Warm

可以进一步区分：

```text
cold-ish load

warm load
```

因为 OS page cache 会影响 SQLite。

如果面试展示数据：

记录：

```text
machine
Python version
SQLite version
storage
task count
event count
```

否则数字没意义。

---

# 七十八、Benchmark 表

先建表，不填假数字：

| Tasks | Edges | Events | Load p50 | Load p95 | Recovery p50 | Recovery p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | | | pending | pending | pending | pending |
| 500 | | | pending | pending | pending | pending |
| 1000 | | | pending | pending | pending | pending |

---

# 七十九、今天可以做一个非常有价值的 Ablation

## Snapshot + Event Log

vs

## Pure Event Replay

假设：

```text
10000 events
```

A：

```text
直接 load current state
```

B：

```text
从 event 1 replay 到 event 10000
```

比较：

```text
Recovery latency
Implementation complexity
Replay bugs
```

这能很好地支持你选择 Hybrid Persistence 的 Design Decision。

---

# 八十、DD-W5-06 建议标题

> **Durable Team State with SQLite Snapshot and Append-only Event History**

---

## Problem

当前：

```text
Registry
Scheduler
Mailbox
Lifecycle
```

只保证：

```text
in-process consistency
```

整个 Process crash 后：

Multi-Agent execution state 消失。

---

## Alternatives

### A. Memory only

最简单。

无法跨 Process restart。

---

### B. JSON Snapshot

与现有 Session 一致。

简单。

但 Team state：

- Task 多
- Message 多
- Event 多
- query 多
- atomic cross-entity transition 多

JSON 文件开始不合适。

---

### C. Pure Event Sourcing

很强。

但当前项目复杂度不值得。

---

### D. SQLite current state + Event History

选择。

---

# 八十一、核心 Invariants

建议把这些写进 DD。

## I1

```text
JsonSessionStore
is authority for Session lifecycle.
```

---

## I2

```text
TeamStateStore
is authority for durable Team Runtime state.
```

---

## I3

```text
Git Worktree
is authority for code side effects.
```

---

## I4

```text
New process
must create a new runtime_id.
```

---

## I5

```text
Old WorkerLease
must never be valid after process restart.
```

---

## I6

```text
Monotonic heartbeat time
must not drive cross-process recovery.
```

---

## I7

如果你做强事务：

```text
State transition and its durable events
commit atomically.
```

---

## I8

```text
RUNNING task
must never be blindly resumed.
```

---

## I9

```text
Recovery rebuilds Runtime objects;
it never resurrects old Python objects.
```

---

# 八十二、Failure Cases

今天至少记录下面这些。

## F-W5-D6-01：Dual Source of Truth

现象：

```text
session.json = RUNNING
SQLite = READY
```

根因：

authority 不清楚。

---

## F-W5-D6-02：Restored Monotonic Clock

现象：

restart 后：

Worker 立刻 timeout，

或者永远不 timeout。

根因：

错误恢复旧 `monotonic` 时间。

---

## F-W5-D6-03：Blind RUNNING Resume

Process crash 时任务已经产生部分副作用。

Restart 后无条件重跑。

结果：

```text
duplicate patch
duplicate command
corrupted workspace
```

---

## F-W5-D6-04：State/Event Split Brain

```text
Task persisted

Event not persisted
```

或者反过来。

根因：

不在同一个 durable transaction。

---

## F-W5-D6-05：Lost Mailbox Message

```text
receive
↓
queue pop
↓
crash
```

消息永远消失。

---

## F-W5-D6-06：Duplicate Resume

两个 Process：

同时 resume 同一个 Session。

需要：

```text
SessionWriterLock
```

---

## F-W5-D6-07：Schema Drift

新版本代码读取旧 DB：

默认值“猜出来”。

应该：

```text
migrate
or reject
```

---

## F-W5-D6-08：Event Log Infinite Growth

长期：

```text
events
events
events
...
```

DB 增长。

现在先记录 limitation；

Week7 Evaluation / Tracing 再讨论 retention。

---

# 八十三、今天实际建议修改的文件

基于你当前仓库，而不是新造 Runtime：

```text
codeteam/agent_team/
├── task_store.py          NEW
├── contracts.py           扩充 durable snapshot contract
├── coordination.py        durable commit/snapshot integration
├── scheduler.py           restore/hydrate support
├── registry.py            restore identity/runtime support
├── mailbox.py             snapshot/restore pending messages
└── lifecycle.py           基本不用重写
```

Session：

```text
codeteam/session/
├── store.py               尽量不改
└── service.py             接 Team Runtime recovery hook/factory
```

测试：

```text
tests/agent_team/
├── test_task_store.py
├── test_team_recovery.py
└── test_process_restart.py
```

---

# 八十四、今天的编码顺序

我不建议第一步就写 SQL。

按照：

```text
Step 1
定义 Durable State Authority

↓

Step 2
定义 TeamStateSnapshot contract

↓

Step 3
设计 SQLite schema

↓

Step 4
实现 SQLiteTeamStateStore

↓

Step 5
save/load snapshot

↓

Step 6
DAG restore

↓

Step 7
Registry restore

↓

Step 8
Scheduler restore

↓

Step 9
Mailbox restore

↓

Step 10
TeamRuntimeFactory

↓

Step 11
Recovery Reconciler

↓

Step 12
kill-process integration test

↓

Step 13
Benchmark
```

---

# 八十五、Day6 完成后的架构

```text
                       SessionService
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
      JsonSessionStore            SQLiteTeamStateStore
              │                           │
       Session lifecycle            Team runtime state
                                          │
                            ┌─────────────┼──────────────┐
                            ▼             ▼              ▼
                        Task/DAG       Agents         Messages
                            │             │              │
                            └─────── Events ─────────────┘

                                          │
                                      Recovery
                                          │
                                          ▼
                              new TeamStateCoordinator
                                          │
                    ┌─────────────────────┼───────────────────┐
                    ▼                     ▼                   ▼
              AgentRegistry        TaskScheduler          Mailbox
                    │
                    ▼
              LifecycleManager
```

---

# 八十六、今天真正应该学会什么？

表面看：

> SQLite。

实际上今天真正学习的是四个 Agent Harness / Runtime 核心概念：

```text
1. Durable State
   哪些状态必须活得比进程久

2. Durability Boundary
   什么情况下才可以向上层说“操作成功”

3. Event History
   系统为什么变成现在这样

4. Recovery / Reconciliation
   新 Runtime 如何根据 durable state
   和真实外部环境恢复
```

---

# 八十七、面试怎么回答

如果面试官问：

> 你的 Multi-Agent Runtime 整个进程挂掉以后怎么恢复？

可以回答：

> CodeTeam 将进程内状态和 durable state 分离。SessionStore 继续负责 Session、仓库和 provider 等顶层状态，Multi-Agent 的 Task DAG、Task Runtime、Agent metadata、Mailbox 和事件历史由独立 SQLite TeamStateStore 持久化。Runtime 重启后不会恢复旧 Python 对象，而是创建新的 runtime epoch，加载 durable snapshot，重新构造 Registry、Scheduler 和 Mailbox，再结合 Git Worktree、Checkpoint 与 active operation 做 reconciliation。对于 crash 时仍处于 RUNNING 的任务不会直接重试，而是先判断已有副作用能否安全恢复，避免重复执行。

如果继续追问：

> 为什么不用纯 Event Sourcing？

回答：

> 当前系统采用 current-state snapshot 加 append-only event history，而不是完全依赖 event replay。Task/Agent 当前状态可以直接快速恢复，Event Log 用于 audit、trace 和 failure analysis。纯 Event Sourcing 虽然历史表达能力更强，但会引入 replay、schema evolution 和长事件流恢复成本，对当前 local-first Coding Agent Runtime 性价比不高。

如果追问：

> 为什么 SQLite，而不是 Redis/PostgreSQL？

回答：

> 当前 CodeTeam 是 local-first Runtime，主要运行在单机，SQLite 提供事务、crash recovery 和结构化查询，同时没有独立服务依赖。Store 接口与 SQLite 实现解耦，因此以后如果演进为多副本 Runtime，可以把持久化后端替换成 PostgreSQL/Redis，而不改变 Scheduler 和 Agent 生命周期模型。

---

## Day6 最终验收标准

我建议把原计划的验收扩展为：

```text
[ ] 新增 SQLiteTeamStateStore

[ ] 能持久化 Task
[ ] 能持久化 DAG dependencies
[ ] 能持久化 Agent identity/runtime metadata
[ ] 能持久化 pending Message
[ ] 能持久化 Event History

[ ] SessionStore 和 TeamStateStore authority 明确
[ ] 不存在同一 Task 状态双写为两个权威来源

[ ] Process restart 创建新的 runtime_id
[ ] 旧 WorkerLease 重启后失效
[ ] 旧 monotonic heartbeat 不参与新 Runtime liveness

[ ] PENDING / READY / COMPLETED 正确恢复
[ ] CLAIMED 可以进入 recovery
[ ] RUNNING 不允许无脑 resume

[ ] Registry 可以从 durable state 重建
[ ] Scheduler 可以从 durable state 重建
[ ] Mailbox pending queue 可以恢复

[ ] SQLite multi-entity mutation 使用 transaction
[ ] transaction 失败不会留下半状态
[ ] schema version 有明确 gate

[ ] 真正执行 kill → restart → recovery 集成测试
[ ] 不是 graceful shutdown 假装 crash test

[ ] 1000 Task Benchmark
[ ] 记录 load latency
[ ] 记录 runtime hydration latency
[ ] 记录 total recovery time
[ ] 结果不预填、不编造
```

其中最值得你今天抓牢的是：

> **Day5 解决“Worker 死了怎么办”；Day6 解决“整个 Runtime 死了以后，系统凭什么知道自己之前做到哪了”。**

这一步完成后，CodeTeam 的 Multi-Agent 部分才真正从**内存编排器**迈向 **Durable Agent Runtime**。

# 基于当前 Week5 代码的 Day6 实施教程

> 本节从当前 `week5` 工作树的真实接口出发，把前面的理论草案收敛为可以逐步编码、逐步验收的路线。本节中的新类、新方法和文件都属于**待你逐步实现的参考设计**，不是仓库中已经存在的事实。Benchmark 与 Ablation 只制定计划，统一留到 Week5 周末执行。

## 0. 先做事实校正，不从原稿反推代码

### 0.1 本次只读检查基线

编写本教程时核对到的工作树事实如下：

- 当前分支：`week5`。
- 当前 HEAD：`c39f0fb025c92e7cb9d261b0444add299a7a94da`。
- `learning-plan/week5/day6.md` 当前是未跟踪文件；原有 3910 行全部保留。
- Day5 最新 Coder 自检为：原 6 项验收失败已经修复，独立 tester 再验仍待进行。
- Day5 的真实边界仍然是**进程内恢复**，没有 SQLite、跨进程 Team resume 或 WorkerExecutor。

你以后真正开始编码前，要再次运行：

```bash
git status --short --branch --untracked-files=all
git rev-parse HEAD
```

原因是本节记录的是教程编写时的事实，不是永久不变的事实。

### 0.2 事实校正表

| 主题 | 当前代码事实 | 原稿中需要澄清的地方 | Day6 参考设计 |
| --- | --- | --- | --- |
| Worker 权威 | `AgentRegistry` 是 live Worker 状态权威 | 不能再增加一份可独立修改的 Worker 状态表 | SQLite 保存 Registry 的 durable 投影；运行时仍由 Registry 唯一修改 |
| Task 权威 | `TaskScheduler` 拥有 Task status、owner、attempt、ready queue | `TaskDAG.status` 不是 Day5 runtime 权威 | Store 保存 Scheduler 的 durable 投影和 DAG 定义，hydrate 后 Scheduler 重新成为 live 权威 |
| 事务域 | `TeamStateCoordinator` 只有 `RLock`、`runtime_id` 和审计序号 | 它不是 durable store，也不能跨进程恢复 | resume 必须创建新 Coordinator 和新 `runtime_id` |
| Fencing | `WorkerLease(runtime_id, worker_id, generation)` 与 `TaskClaim(..., attempt, runtime_id, worker_generation)` 已实现 | `attempt`、`generation`、`runtime_id` 不能合成一个数字 | 三个维度分别持久化历史事实，但旧 token 对象一律丢弃 |
| Scheduler 快照 | 当前 `TeamSnapshot` 只有 tasks、workers、queue、ownership | 它不含 DAG、AgentInfo、waiting、restart policy、Mailbox 或 durable revision | 新增完整 `TeamStateSnapshot`，不能直接复用现有 `TeamSnapshot` 冒充 durable contract |
| Scheduler 构造 | 当前构造器要求所有 DAG 节点都是 `PENDING` | 不能拿非 PENDING 快照直接调用现有构造器 | 新增经过验证的 `hydrate()`/`from_durable_state()` 公共入口 |
| Registry 恢复 | 当前 Registry 通过 `register()` 从 generation=1 建立 Worker | 没有导入历史 generation/restart budget 的公开入口 | 新增受约束的 hydrate 入口；不得写 `_records`、`_workers`、`_infos` |
| Mailbox | 当前是 `Lock + deque + seen_message_ids`，`receive()` 先 `popleft()` | event sink 不是 durable commit；崩溃会产生 lost-message window | pending message 与 dedupe 集合进入同一 SQLite 快照；commit 成功后才能向调用方返回消息 |
| Session | `JsonSessionStore` 保存 Session、事件和 context；`SessionService.resume()` 持有 writer lock 并调用 `RuntimeFactory(Session)` | 当前 factory 不懂 Team snapshot；Session JSON 和 SQLite 也不能组成一个原子事务 | 增加 Team runtime hook/factory，并用 revision hint + reconciliation 处理跨文件 crash window |
| Git 副作用 | Git Worktree/Checkpoint 才是代码真实状态 | Task 状态不能证明 patch 是否已经产生 | CLAIMED/RUNNING 恢复必须与 Git/Checkpoint 对账，不能直接继续执行 |
| 时间 | heartbeat 使用 monotonic clock，Session audit 使用 aware wall clock | monotonic 数值跨进程没有意义 | 丢弃旧 heartbeat deadline；durable audit 使用 UTC wall clock |

### 0.3 Day5 与 Day6 的故障边界

```text
Day5: Python Runtime 仍活着
Worker timeout
  -> 旧 runtime_id 仍有效
  -> 校验 generation / attempt
  -> 进程内 recovery / restart

Day6: 整个 Python Process 已退出
new process
  -> Session writer lock
  -> load Session JSON + Team SQLite
  -> reconcile Git / checkpoint / inflight task
  -> new TeamStateCoordinator
  -> new runtime_id
  -> hydrate Registry / Scheduler / Mailbox
```

Day6 **不能重写** Day5 已经解决的 Worker loss、restart reservation、终态依赖传播和共享锁一致性。它只负责把可信的 durable facts 转换成一个新的进程内 Runtime。

### 0.4 本日能力定位

Primary：

- Multi-Agent Orchestration：durable Task DAG、ownership 恢复和 Mailbox 恢复。
- Agent Runtime：process crash 后的 reconstruction 与 fencing。

Secondary：

- Observability：state 与 event 同事务提交。
- Workspace & Sandbox：与 Git Worktree/Checkpoint 对账。
- Evaluation：真实 kill-process、CAS 冲突和 crash-window 测试。

这一天最终要证明的不是“会使用 SQLite”，而是：

> 你能定义 durability boundary，能够把旧进程遗留的状态当作待验证事实，并在新进程中 fail-closed 地重建 Multi-Agent Runtime。

## 1. Theory：实施时必须真正理解的五个概念

### 1.1 Durable state 与 ephemeral state

Durable state 在进程退出后仍然有意义，例如 Task 的 `attempt=2`、DAG 边、已完成任务、pending message。Ephemeral state 依赖当前 Python 进程，例如：

- `RLock`、线程、SQLite connection；
- callback、event sink、WorkerAgent 对象；
- 当前 `runtime_id` 下签发的 `WorkerLease` / `TaskClaim`；
- monotonic heartbeat 时间；
- 正在运行的 subprocess/container handle。

关键判断问题是：

```text
把这个值保存后，换一个进程还能安全地继续使用它吗？
```

如果答案是否定的，就只能保存重建它所需的**配方或历史事实**，不能保存对象本身。

### 1.2 Crash consistency 不等于业务恢复正确

SQLite transaction 可以保证同一数据库事务“全有或全无”，但它不会自动知道：

- RUNNING Task 是否已经写过文件；
- Docker 命令是否已经产生外部副作用；
- Session JSON 是否已经跟上 Team SQLite 的 revision。

因此需要两层保证：

```text
SQLite atomic transaction
  保证 Team state + Team event 不拆分

Reconciliation
  判断这个 committed state 与 Git/Session/真实环境是否仍一致
```

### 1.3 CAS / expected_revision

CAS 是 compare-and-swap。调用方读取 revision=7 后提交时必须声明：

```python
store.commit(next_snapshot, expected_revision=7)
```

SQL 更新只有在磁盘仍是 revision=7 时才能成功。如果另一个 writer 已经写到 8，本次必须抛 `TeamStateConflictError`，不能覆盖新状态。

它解决的是“过期写覆盖”，不是代替 Session writer lock。两者作用不同：

- writer lock：限制同一 Session 的活跃进程所有权；
- CAS：防止错误、重入或竞争写入使用过期快照。

### 1.4 WAL 与 sidecar

本项目 V1 可以选择 SQLite WAL，但必须把 `team_state.sqlite3`、`team_state.sqlite3-wal` 和 `team_state.sqlite3-shm` 视为同一 durable state 的组成部分。SQLite 官方明确说明 WAL 文件可能包含已提交事务，复制或移动数据库时不能只拿主文件。参考：[SQLite WAL](https://www.sqlite.org/wal.html) 与 [Atomic Commit](https://www.sqlite.org/atomiccommit.html)。

工程含义：

- 数据库必须位于受控 Session 目录；
- 不能把 DB 放进被 Agent 修改的仓库或 Worktree；
- backup/export 前要 checkpoint 或使用 SQLite backup API；
- 不手工删除 `-wal` / `-shm`；
- Session 目录应为 `0700`，DB 及 sidecar 不向其他用户开放。

### 1.5 Wall clock 与 monotonic clock

Day5 heartbeat 使用 monotonic clock 是正确的，因为它只比较同一进程内的时间间隔。但重启后 monotonic 原点改变，所以：

- `last_heartbeat_monotonic`、`next_restart_monotonic` 不能直接恢复；
- durable event 的 `created_at` 使用 timezone-aware UTC wall clock；
- cooldown 若必须跨进程保持，应单独保存 `restart_not_before_utc`，不能把 monotonic 值换个进程继续比较。

## 2. Industrial Design：公开事实、工程推断与本项目选择

### 2.1 可确认的公开事实

- SQLite 单数据库事务提供原子提交；事务被中断后不会只提交一半数据库修改。
- Python 3.11 的 `sqlite3.Connection` context manager 会在正常退出时 commit、异常时 rollback，但不会自动关闭 connection。参考：[Python 3.11 sqlite3](https://docs.python.org/3.11/library/sqlite3.html)。
- WAL 模式会产生 `-wal` 和 `-shm` sidecar；WAL 是数据库持久状态的一部分。

### 2.2 工程推断

- Local-first Coding Agent 不需要先引入 PostgreSQL/Redis 服务，SQLite 足以提供单机事务与 crash recovery。
- 单一 JSON 文件可以原子替换，却很难让 Task、Mailbox 消费和 event history 在一次事务中提交。
- 纯 Event Sourcing 需要稳定的事件演进、replay 和 projection 机制，超出当前学习阶段。

这些是面向 CodeTeam 当前约束的推断，不代表某一家 Agent 产品的内部实现。

### 2.3 本项目选择

V1 选择：

```text
SQLite current snapshot + append-only Team event history
```

而不是：

| 方案 | 优点 | 当前不选原因 |
| --- | --- | --- |
| memory-only | 最简单 | process crash 后全部丢失 |
| 单独 JSON snapshot | 容易阅读 | CAS、并发写、state/event 原子性弱 |
| pure event sourcing | 历史完整 | replay、迁移、projection 成本过高 |
| SQLite snapshot + events | 本地事务、查询和 crash recovery | 需要 schema、迁移、锁和 reconciliation |

推荐 V1 先把整个 `TeamStateSnapshot` 作为经过 Pydantic 校验的 JSON payload 存在 SQLite 一行中，同时把 Team events 放在独立表；两者同事务提交。这样教学重点是边界正确，而不是先写大量 ORM 映射。若后续性能证据表明 1000 Task 全量快照写入过慢，再按 DD 演进到规范化表，不提前优化。

## 3. 三类状态权威与跨存储 crash window

### 3.1 唯一权威表

| 权威 | 保存什么 | 不保存什么 |
| --- | --- | --- |
| `JsonSessionStore` | Session 生命周期、repo/worktree/checkpoint 引用、provider/model、顶层 resume 入口 | Team Task 队列、Worker live 状态、Mailbox backlog |
| `SQLiteTeamStateStore` | DAG、Task runtime、Agent durable metadata、ready/waiting、Mailbox pending/dedupe、Team event history | Git 文件内容、Python 锁、旧 token、callback |
| GitWorkspace/Checkpoint | 真实代码副作用与恢复点 | Scheduler 的“我认为已完成”状态 |

Session JSON 可以保存 `team_state_revision_hint`，但它只是用于发现错位的提示，不是 Team 状态的第二权威。

### 3.2 为什么两个存储不能假装成一个事务

Session JSON 的 `os.replace()` 与 SQLite `COMMIT` 无法组成单个原子事务。推荐 resume 发布顺序：

```text
1. 持有 Session writer lock
2. load Session + Team snapshot
3. reconcile Session/Git/Team
4. SQLite commit reconciled Team state + TEAM_RUNTIME_PREPARED event
5. hydrate new in-memory Runtime
6. JsonSessionStore.save(RUNNING, team_revision_hint=new_revision)
7. append SESSION_RESUMED correlation event
8. 对外返回 Runtime
```

如果在第 4 步后、第 6 步前 crash：SQLite revision 会领先 Session hint。下次 resume 不能把它当成正常一致，也不能直接回滚 SQLite；应根据 operation/correlation event 识别“已提交 Team、未发布 Session”，重新 reconciliation 后让 Session 追上。反过来若 Session hint 大于 DB revision，说明 durable Team 状态缺失或被回退，应 fail closed 为 `RECOVERY_REQUIRED`。

推荐规则：

```text
db_revision == session_hint
    正常继续

db_revision > session_hint
    允许进入 recovery reconciliation；不得直接运行

db_revision < session_hint
    durable state missing/rollback；拒绝自动 resume
```

## 4. 待逐步实现的参考契约

### 4.1 Durable models

建议新增的模型名称如下。字段可在实现步骤中继续收敛，但不能删掉恢复所需事实。

```python
class DurableWorkerState(BaseModel):
    info: AgentInfo
    previous_generation: int
    previous_revision: int
    previous_status: AgentStatus
    restart_attempts: int
    restart_not_before_utc: datetime | None


class DurableMessageState(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"


class DurableMessage(BaseModel):
    message: AgentMessage
    state: DurableMessageState
    enqueue_seq: int
    delivery_attempt: int = 0
    claimed_by_runtime_id: str | None = None


class DurableEvent(BaseModel):
    event_id: str
    session_id: str
    seq: int
    revision: int
    event_type: str
    timestamp: datetime
    payload: dict[str, object]


class TeamStateSnapshot(BaseModel):
    schema_version: int
    session_id: str
    revision: int
    previous_runtime_id: str | None
    dag_nodes: tuple[TaskNode, ...]
    dependencies: dict[str, frozenset[str]]
    tasks: dict[str, TaskRuntimeRecord]
    workers: dict[str, DurableWorkerState]
    ready_queue: tuple[str, ...]
    waiting_for_worker: frozenset[str]
    worker_ownership: dict[str, str | None]
    mailbox_agents: tuple[AgentIdentity, ...]
    messages: tuple[DurableMessage, ...]
    seen_message_ids: frozenset[str]
    max_attempts: int
    lifecycle_policy: LifecyclePolicy
    last_event_seq: int
    updated_at: datetime
```

这里故意不放 `WorkerAgent`、`RLock`、connection、factory、event sink、旧 `WorkerLease`、旧 `TaskClaim` 和 monotonic 时间。

### 4.2 Store Protocol

```python
class TeamStateStore(Protocol):
    def initialize(self, snapshot: TeamStateSnapshot) -> TeamStateSnapshot: ...

    def load(self, session_id: str) -> TeamStateSnapshot: ...

    def commit(
        self,
        snapshot: TeamStateSnapshot,
        *,
        expected_revision: int,
        events: tuple[DurableEventDraft, ...] = (),
    ) -> TeamStateSnapshot: ...

    def load_events(
        self,
        session_id: str,
        *,
        after_seq: int = 0,
    ) -> tuple[DurableEvent, ...]: ...
```

建议异常：

- `TeamStateNotFoundError`
- `TeamStateAlreadyExistsError`
- `TeamStateCorruptedError`
- `TeamStateSchemaUnsupportedError`
- `TeamStateConflictError`
- `TeamStatePathError`

`commit()` 的成功返回值必须带新 revision。event seq 由 Store 在事务里分配，调用方不能自己猜。

### 4.3 Runtime Factory 与 Reconciler

```python
class TeamRuntimeFactory(Protocol):
    def hydrate(
        self,
        *,
        session: Session,
        snapshot: TeamStateSnapshot,
        store: TeamStateStore,
    ) -> TeamRuntime: ...


class TeamStateReconciler:
    def reconcile(
        self,
        *,
        session: Session,
        snapshot: TeamStateSnapshot,
        git_state: GitRecoveryState,
    ) -> TeamReconciliationReport: ...
```

`TeamRuntime` 是一个新的组合返回值，至少持有新 Coordinator、Registry、Scheduler、Mailbox 和 Lifecycle。它不进入任何 durable model。

`TeamReconciliationReport` 至少包含：

- verdict：`RESUMABLE / RECOVERY_REQUIRED / INVALID`；
- 原 snapshot revision；
- 建议的新 snapshot；
- issues/recovery actions；
- 是否需要人工确认 Git 副作用。

### 4.4 Session integration hook

不要把 Team 逻辑硬塞进现有 `RuntimeFactory = Callable[[Session], Any]`。建议演进为具名 Protocol：

```python
class SessionRuntimeFactory(Protocol):
    def build(self, request: SessionRuntimeBuildRequest) -> object: ...


class SessionRuntimeBuildRequest(BaseModel):
    session: Session
    session_dir: Path
    expected_session_state_version: int
```

Team adapter 在 `build()` 内定位固定文件名 `team_state.sqlite3`，调用 load/reconcile/hydrate。普通 Single-Agent runtime 仍可由另一实现处理。这样 `SessionService` 保持顶层生命周期编排，不变成 TeamStore 本身。

## 5. Implementation：Step 1–13

下面每一步都只完成一个可验证边界。正式编码时一次只做一步，不要先造完整数据库再回头补契约。

### Step 1：建立 Authority Map 与 crash invariants

**目标与原因**

先把“谁能修改什么”写成测试可用的不变量。没有这一步，Session JSON 和 SQLite 很容易同时修改 Task status，形成双 Source of Truth。

**涉及文件（未来）**

- `codeteam/agent_team/persistence_models.py`
- `docs/design_decisions/DD-W5-06.md`
- 暂不修改 Day5 核心类。

**接口与参数**

先定义纯文档/常量层的 authority：Session、Team、Git。此步没有 I/O 返回值。

**Python 知识**

- `Enum`：固定 authority 名称；
- `frozenset`：表达不可变字段集合；
- `ClassVar`：声明不属于 Pydantic 实例字段的规则表。

**参考骨架**

```python
class StateAuthority(str, Enum):
    SESSION = "session"
    TEAM = "team"
    GIT = "git"


TEAM_OWNED_FIELDS: frozenset[str] = frozenset(
    {"tasks", "workers", "ready_queue", "messages"}
)
```

**正常路径 / 失败路径 / 安全边界**

- 正常：每个 durable 字段恰好有一个 authority。
- 失败：同一 `task_status` 同时由 Session 与 Team 独立修改。
- 安全边界：Session 可保存 Team revision hint，但不能覆盖 Team Task 状态。

**本步测试**

写一个表驱动测试，断言关键字段只出现于一个 authority 集合；这不是替代业务测试，而是防止未来设计漂移。

**完成标志**

你能逐项回答 Session、Team、Git 冲突时信谁，以及为什么。

**与下一步关系**

Step 2 才能基于这张表定义 durable contract。

### Step 2：定义完整 Durable Contract

**目标与原因**

实现 `TeamStateSnapshot`、`DurableWorkerState`、`DurableMessage`、`DurableEvent`。先让模型能构造、JSON round-trip 和拒绝非法组合，再写 SQLite。

**涉及文件（未来）**

- `codeteam/agent_team/persistence_models.py`
- `codeteam/agent_team/persistence_errors.py`
- `tests/agent_team/test_team_state_models.py`

**接口参数与返回值**

- `TeamStateSnapshot.model_validate_json(text) -> TeamStateSnapshot`
- `validate_snapshot(snapshot) -> None`

必须验证：

- 所有 DAG 节点恰好有一个 Task record；
- queue 无重复，只引用 READY；
- waiting 只引用可等待状态；
- owner 与 Worker/Task 状态一致；
- message ID 唯一且包含在 dedupe 集合；
- `revision >= 1`，`schema_version` 严格检查；
- datetime 是 timezone-aware。

**Python/Pydantic 知识**

- `BaseModel` 用于 JSON-safe contract；
- `Field(ge=...)` 做数值边界；
- `model_validator(mode="after")` 做跨字段校验；
- `ConfigDict(extra="forbid", frozen=True)` 防止未来字段被静默忽略。

**局部参考实现**

```python
@model_validator(mode="after")
def _queue_matches_ready(self) -> "TeamStateSnapshot":
    if len(self.ready_queue) != len(set(self.ready_queue)):
        raise ValueError("ready_queue must not contain duplicates")
    for node_id in self.ready_queue:
        if self.tasks[node_id].status is not TaskStatus.READY:
            raise ValueError("ready_queue may contain only READY tasks")
    return self
```

**正常路径 / 失败路径 / 安全边界**

- 正常：完整 snapshot JSON round-trip 等价。
- 失败：缺 DAG edge、owner 不匹配、旧 token 混入时 ValidationError。
- 安全：禁止 `Any` 兜底和序列化 Python 对象；payload 继续做 JSON-compatible 校验与敏感字段脱敏。

**本步测试**

- 最小 1 Worker/1 Task snapshot round-trip；
- 每个不变量一项负例；
- `RLock`、callback、connection、WorkerAgent 无法进入模型；
- future schema 不因默认值被接受。

**完成标志**

不连接数据库时，durable contract 已经能独立验收。

**与下一步关系**

Step 3 将 contract 映射到 SQLite schema，而不是让 SQL 反过来决定领域模型。

### Step 3：设计 SQLite schema、路径和 schema gate

**目标与原因**

创建最小两表 schema，并先解决路径与权限。数据库能打开不代表放置位置安全。

**涉及文件（未来）**

- `codeteam/agent_team/team_store.py`
- `tests/agent_team/test_sqlite_team_state_store.py`

**建议 schema**

```sql
CREATE TABLE team_state (
    session_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    previous_runtime_id TEXT,
    snapshot_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE team_events (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (session_id, seq),
    FOREIGN KEY (session_id) REFERENCES team_state(session_id)
);

PRAGMA user_version = 1;
```

**路径契约**

```text
<sessions_root>/<validated-session-id>/
├── session.json
├── events.jsonl
├── writer.lock
├── team_state.sqlite3
├── team_state.sqlite3-wal
└── team_state.sqlite3-shm
```

数据库路径由 `JsonSessionStore.session_dir(session_id)` 加固定文件名产生，调用方不能传任意 repo-relative path。初始化时确认：

- parent 是真实 Session 目录；
- DB 不在 repo/worktree 内；
- parent 目录 mode 尽量收敛到 `0700`；
- 新 DB 文件 mode 为 `0600`；
- symlink 与 path traversal 被拒绝。

**Python/sqlite3 知识**

```python
connection = sqlite3.connect(db_path, timeout=5.0)
connection.row_factory = sqlite3.Row
connection.execute("PRAGMA foreign_keys = ON")
connection.execute("PRAGMA journal_mode = WAL")
connection.execute("PRAGMA synchronous = FULL")
```

注意：Python 3.11 使用现有 transaction API；不要照抄 Python 3.12 才新增的 `autocommit=` 参数。参数值用 SQL placeholders，不拼接用户输入。

**正常路径 / 失败路径 / 安全边界**

- 正常：空 Session 目录中初始化 schema。
- 失败：DB 在 workspace、symlink 指向 workspace 外、未知 `user_version`。
- schema gate 必须在 Pydantic 默认值填充之前；未知未来版本抛 `TeamStateSchemaUnsupportedError`。

**本步测试**

- schema/table/index 存在；
- 文件权限和路径边界；
- unsupported `PRAGMA user_version`；
- DB header 损坏时映射为明确错误；
- WAL sidecar 仍留在受控 Session 目录。

**完成标志**

只有 schema 与路径通过，尚未开始 Runtime hydration。

**与下一步关系**

Step 4 实现最小 initialize/load round-trip。

### Step 4：实现 Store initialize/load

**目标与原因**

先打通创建和读取，不同时实现 commit/CAS，便于定位序列化和数据库错误。

**涉及文件、类和函数**

- `SQLiteTeamStateStore.__init__(db_path: Path)`
- `initialize(snapshot) -> TeamStateSnapshot`
- `load(session_id) -> TeamStateSnapshot`

**Python/sqlite3 知识**

- `with sqlite3.connect(...) as connection:` 负责成功 commit / 异常 rollback，但用完仍要 close；
- 推荐再配合 `contextlib.closing()`；
- `json.loads()` 错误与 Pydantic ValidationError 要映射成不同可诊断原因，外部统一为 `TeamStateCorruptedError`。

**参考骨架**

```python
def load(self, session_id: str) -> TeamStateSnapshot:
    with closing(self._connect(read_only=True)) as connection:
        row = connection.execute(
            "SELECT schema_version, snapshot_json FROM team_state "
            "WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise TeamStateNotFoundError(session_id)
    self._require_supported_schema(row["schema_version"])
    try:
        return TeamStateSnapshot.model_validate_json(row["snapshot_json"])
    except ValidationError as exc:
        raise TeamStateCorruptedError(session_id) from exc
```

**正常路径 / 失败路径 / 安全边界**

- `initialize()` 只接受 revision=1，并拒绝覆盖现有 session_id。
- `load()` 不得因为查询不存在而创建空 DB。
- `snapshot_json` 内 session_id/revision 必须与列值一致。

**本步测试**

- initialize → load 等价；
- duplicate initialize；
- not found；
- malformed JSON；
- 列 revision 与 JSON revision 不同；
- unknown schema。

**完成标志**

静态 snapshot 可可靠 round-trip，错误类型清楚。

**与下一步关系**

Step 5 在此基础上加入真正的原子 commit。

### Step 5：实现 CAS + state/event 原子 commit

**目标与原因**

让一次 Team mutation 的新状态和审计事件同时提交，失败时同时回滚。

**涉及函数**

- `commit(snapshot, expected_revision, events) -> TeamStateSnapshot`
- `load_events(session_id, after_seq=0) -> tuple[DurableEvent, ...]`

**事务边界**

```text
BEGIN IMMEDIATE
  SELECT current revision
  compare expected_revision
  allocate event seq
  UPDATE team_state SET revision = expected + 1, snapshot_json = ...
  INSERT team_events(... same new revision ...)
COMMIT
```

**Python/sqlite3 参考**

```python
connection.execute("BEGIN IMMEDIATE")
row = connection.execute(
    "SELECT revision FROM team_state WHERE session_id = ?",
    (snapshot.session_id,),
).fetchone()
if row["revision"] != expected_revision:
    raise TeamStateConflictError(...)

next_snapshot = snapshot.model_copy(
    update={"revision": expected_revision + 1, "updated_at": utc_now()}
)
# UPDATE state 与 INSERT events 都在此 transaction 内。
connection.commit()
```

不要在已打开事务中使用 `executescript()`；它的隐式 transaction 行为容易模糊边界。异常路径显式 rollback，再把 `sqlite3.IntegrityError` / `OperationalError` 转成领域错误。

**正常路径 / 失败路径 / 安全边界**

- 正常：revision N→N+1，全部 event 指向 N+1。
- CAS 冲突：零状态变化、零新事件。
- event 插入失败：snapshot UPDATE 也回滚。
- event sink 只在 commit 后收到副本；sink 失败不得改变 durable commit，也不得冒充 commit。

**本步测试**

- CAS success / stale conflict；
- 在第 2 条 event 插入时注入异常，断言旧 snapshot 与旧 event history 均不变；
- event seq 严格递增、无重复；
- `after_seq` 正确；
- 两个 connection 竞争同一 revision，只有一个成功。

**完成标志**

可以证明 state/event 不会 split brain。

**与下一步关系**

Step 6 才允许 Day5 Runtime 产生一致快照并提交。

### Step 6：建立公开的一致快照导出边界

**目标与原因**

当前 Scheduler 的 `snapshot()` 是共享锁内的有限视图，但 Mailbox 使用另一把锁，且完整 durable 字段不存在。不能分别读取多个 property 后拼装，那会混合不同时间点。

**涉及文件和接口（未来）**

- `codeteam/agent_team/coordination.py`
- `registry.py`、`scheduler.py`、`mailbox.py`
- 新增 `TeamRuntime.export_snapshot(session_id, expected_revision) -> TeamStateSnapshot`

**关键设计**

V1 推荐把 Mailbox 纳入同一个 `TeamStateCoordinator` 事务域，或由更高层按固定锁顺序获取：

```text
Session writer lock
  -> TeamStateCoordinator.lock
  -> Mailbox lock（若尚未迁移）
  -> 不再获取其他锁
```

更推荐最终只保留一个 Team coordinator lock，减少 snapshot 交叉时刻。无论选择哪种方式，都必须提供公开的 `export_durable_state()`；Store 不能读取 `_records`、`_queue`、`_infos`、`_inboxes`。

**Python 知识**

- context manager 确保锁异常释放；
- 深拷贝避免调用方在锁外修改 live state；
- 不在核心锁内执行 JSON 编码、SQLite I/O 或 event sink。

**安全的两阶段形态**

```python
with coordinator.lock:
    draft = runtime.export_durable_draft_locked()

snapshot = TeamStateSnapshot.model_validate(draft)
store.commit(snapshot, expected_revision=expected_revision, events=events)
```

这仍有“内存 mutation 已发生、SQLite commit 失败”的窗口。因此 Day6 完整接入时，业务 mutation 应演进为：在共享锁内准备 next state，锁外 SQLite commit，成功后发布内存；或者把 durable commit 作为每个 mutation 的 transaction participant。不要仅靠周期性 snapshot 就宣称零数据丢失。

V1 推荐增加一个不暴露给 LLM 的 `TeamMutationGateway`，让所有 durable Team mutation 走同一入口：

```text
acquire durability_gate
  -> acquire coordinator.lock，基于 current state 生成 immutable draft
  -> release coordinator.lock
  -> SQLite CAS commit draft + events
  -> acquire coordinator.lock，重新核对 base in-memory revision
  -> publish committed draft
release durability_gate
```

`durability_gate` 序列化 mutation，但不阻止只读 snapshot；SQLite I/O 不持有 Day5 core lock。锁顺序固定为 `durability_gate -> coordinator.lock`，任何代码不得反向获取。若 SQLite 已 commit、内存发布却失败，当前 Runtime 必须进入 poisoned/recovery-required 状态并停止接受新 mutation，不能继续让内存落后磁盘。这个 gateway 是 V1 为了正确性引入的边界，后续性能只能通过 Benchmark 决定是否演进，不能先删除安全门。

**本步测试**

- 并发 claim/heartbeat/send 时导出的 snapshot 每项 invariant 都成立；
- Barrier/Event 控制线程，不用长 sleep；
- 导出中注入异常，live state 不变；
- snapshot 变更不影响 live objects；
- 不允许读取私有 dict 的测试/代码路径。

**完成标志**

存在一个经过锁与模型校验的完整 snapshot 出口，并明确了“周期性快照”尚未提供的保证。

**与下一步关系**

Step 7/8 将实现相反方向：从 durable contract 重建新对象。

### Step 7：重建 DAG，不恢复旧 runtime status

**目标与原因**

先恢复最稳定的结构：Task 定义与 dependencies。DAG 是调度约束，Task runtime status 则由 Scheduler 权威管理，二者不能混在一起恢复。

**涉及文件和接口（未来）**

- `codeteam/agent_team/dag.py`
- `codeteam/agent_team/runtime_factory.py`
- `TaskDAG.from_durable_definition(nodes, dependencies) -> TaskDAG`

**参数与返回值**

- 输入：snapshot 中的 `dag_nodes` 和 `dependencies`；
- 输出：经过 duplicate、unknown endpoint、self-edge、cycle 校验的新 `TaskDAG`；
- 不把 snapshot 的 live Task status 写回 `TaskDAG._nodes`。

**Python 知识**

- `classmethod` 用于替代构造入口；
- `tuple[tuple[str, str], ...]` 表达稳定 edge 序列；
- 生成器与排序用于确定性恢复。

**参考骨架**

```python
@classmethod
def from_durable_definition(
    cls,
    nodes: tuple[TaskNode, ...],
    dependencies: dict[str, frozenset[str]],
) -> "TaskDAG":
    dag = cls()
    for node in nodes:
        dag.add_task(node.model_copy(update={"status": TaskStatus.PENDING}))
    for dependent_id in sorted(dependencies):
        for prerequisite_id in sorted(dependencies[dependent_id]):
            dag.add_dependency(prerequisite_id, dependent_id)
    dag.validate()
    return dag
```

**正常路径 / 失败路径 / 安全边界**

- 正常：拓扑顺序和依赖关系与持久化前一致。
- 失败：未知 edge/cycle/节点集合不一致时抛 durable corruption，不尝试“修一下再跑”。
- 边界：DAG 的节点 status 只用于 fresh definition；Scheduler 的 durable Task record 才是恢复权威。

**本步测试**

- chain、diamond、disconnected graph round-trip；
- 节点名称改名后只要 edge 映射一致，结果仍确定；
- cycle、missing endpoint、duplicate node 被拒绝；
- topological order 满足全部 edge。

**完成标志**

能从 durable definition 得到一个 fresh、validated DAG，不触碰 Registry/Scheduler/Mailbox。

**与下一步关系**

Step 8 将在这个 DAG 上重建新的 Team Runtime。

### Step 8：hydrate Registry、Scheduler 与 Mailbox

**目标与原因**

创建**新对象**，绝不反序列化旧 Python runtime。hydration 必须生成新 Coordinator/new `runtime_id`，并使所有旧 lease/claim 失效。

**涉及文件和接口（未来）**

- `codeteam/agent_team/runtime_factory.py`
- `registry.py`：`AgentRegistry.from_durable_state(...)`
- `scheduler.py`：`TaskScheduler.from_durable_state(...)`
- `mailbox.py`：`AgentMailbox.from_durable_state(...)`
- `coordination.py`：保持每次构造新 `runtime_id`

**参考调用关系**

```python
coordinator = TeamStateCoordinator()  # 自动生成 NEW runtime_id
dag = TaskDAG.from_durable_definition(...)
registry = AgentRegistry.from_durable_state(
    snapshot.workers,
    coordinator=coordinator,
    worker_factory=worker_factory,
)
scheduler = TaskScheduler.from_durable_state(
    dag,
    registry,
    tasks=snapshot.tasks,
    ready_queue=snapshot.ready_queue,
    waiting=snapshot.waiting_for_worker,
    ownership=snapshot.worker_ownership,
    max_attempts=snapshot.max_attempts,
)
mailbox = AgentMailbox.from_durable_state(
    agents=snapshot.mailbox_agents,
    messages=snapshot.messages,
    seen_message_ids=snapshot.seen_message_ids,
    coordinator=coordinator,
)
```

**Worker 恢复策略**

- `STOPPED` 保持 STOPPED，不能自动复活。
- 旧 `READY/BUSY/RESTARTING` 只表示旧进程最后状态，不能直接恢复 live。
- worker factory 成功后，发布 `generation = previous_generation + 1`；失败则保持 FAILED。
- `restart_attempts` 保留，避免 process restart 绕过预算。
- `next_restart_monotonic` 丢弃；若 policy 要跨进程保留 cooldown，使用 durable UTC deadline。
- runtime revision 重新建立，但 snapshot 必须保留 previous revision 供审计。

**Task/队列恢复策略**

- PENDING：仍 PENDING；
- READY：恢复为 READY，严格按 durable queue 顺序入队；
- COMPLETED/FAILED/BLOCKED：保持终态；
- CLAIMED/RUNNING：本步不直接恢复为可执行，必须由 Step 9 reconciliation 转换；
- waiting set 必须和角色可用性规则一致；
- `attempt` 永不归零。

**Mailbox 恢复策略**

- 恢复 pending message 的 per-recipient FIFO；
- 恢复完整 `seen_message_ids`，防止 process restart 后重复 ID 再次入队；
- 旧 runtime 标记的 `IN_FLIGHT` message 不能直接视作 consumed；由 reconciliation 决定 requeue 或人工恢复；
- `receive()` 必须改为 commit-before-return，禁止先 `popleft()` 再异步保存。

一个适合 V1 的 receive 流程是：

```text
load current snapshot
  -> select first pending message
  -> next snapshot removes/marks consumed
  -> append MAILBOX_MESSAGE_RECEIVED durable event
  -> store.commit(expected_revision=N)
  -> only now return message to caller
```

如果需要处理 caller 收到消息后立即 crash，可进一步做 `claim_message -> ack_message`。这提供 at-least-once control-plane delivery，但仍不等于外部副作用 exactly-once。

**Python 知识**

- `Protocol` 注入 worker factory；
- `dataclass(frozen=True)` 或 Pydantic frozen model 组合 Runtime handle；
- factory/callback/SQLite I/O 不在 Coordinator 核心锁内；返回后重新校验 durable revision。

**正常路径 / 失败路径 / 安全边界**

- 正常：全部组件共享一个新 Coordinator，snapshot invariants 在返回前再验证一次。
- factory/validation 失败：不发布半个 Runtime，也不把 Session 标成 RUNNING。
- hydration 期间 snapshot revision 改变：拒绝过期结果并重新走 resume/reconcile，不在旧对象上补丁式更新。
- 安全边界：hydration API 是可信控制平面能力，不向 Agent/Tool 暴露 raw Store 或私有恢复方法。

**本步测试**

- new runtime_id != previous_runtime_id；
- 旧 WorkerLease 的 heartbeat/claim/stop 被拒；
- 旧 TaskClaim 的 start/complete/fail 被拒；
- generation +1、restart budget 不归零；
- READY queue 顺序、waiting、terminal statuses 恢复；
- message order 与 dedupe 恢复；
- factory 失败不发布伪 READY Worker。

**完成标志**

hydrate 结果是全新的对象图，旧 token 无法影响它，且没有读写任何 Day5 私有 dict。

**与下一步关系**

CLAIMED/RUNNING 和旧 in-flight message 仍未决定，交给 Step 9 reconciliation。

### Step 9：实现 TeamStateReconciler 与 fail-closed 状态矩阵

**目标与原因**

把“磁盘快照记载了什么”与“Git/Checkpoint/新 Runtime 现在能证明什么”对账。process crash 后最危险的错误是把旧 RUNNING 当作可以从断点继续。

**涉及文件和接口（未来）**

- `codeteam/agent_team/reconciliation.py`
- `TeamStateReconciler.reconcile(session, snapshot, git_state)`
- `TeamReconciliationReport`

**核心输入**

- Session repo/worktree/checkpoint refs；
- Team snapshot 与 revision；
- Git current HEAD、dirty diff、checkpoint existence；
- task verification/effect evidence；
- policy：max attempts、可安全重放的 operation 类型。

**CLAIMED/RUNNING 决策表**

| Durable 状态 | 可证明的外部事实 | 建议动作 |
| --- | --- | --- |
| CLAIMED | 无 side effect evidence | 清 owner，保持 attempt，按预算 requeue |
| RUNNING | checkpoint 后 Git 无变化，operation 明确可重放 | 清 owner，按预算 requeue，并记录 recovery event |
| RUNNING | Git 已变化但存在可验证 checkpoint/diff | `RECOVERY_REQUIRED`，先验证/人工选择，不能重复执行 |
| RUNNING | Git 状态未知、worktree missing、checkpoint missing | fail closed 为 `RECOVERY_REQUIRED` |
| RUNNING | 已有明确 completion evidence 且验证通过 | 可转 COMPLETED，但必须有专门证据与事件，不能根据模型文字推断 |
| 任意终态 | 外部状态无关 | 不复活；若 Git 严重矛盾则报告 INVALID/RECOVERY_REQUIRED |

**参考伪代码**

```python
for task in snapshot.tasks.values():
    if task.status not in {TaskStatus.CLAIMED, TaskStatus.RUNNING}:
        continue
    if not evidence.can_replay_safely(task.node_id):
        issues.append(recovery_required(task.node_id, "effect_unknown"))
        continue
    tasks[task.node_id] = requeue_without_owner(task)
```

**超时与 token 语义**

- 旧 `runtime_id`、lease、claim 全部作废，不作为 reconcile 输入授权。
- owner 清理时保留 `attempt`，下一次成功 claim 再 +1，沿用 Day5 语义。
- monotonic heartbeat 一律丢弃；新 Worker 获取新的 heartbeat origin。

**正常路径 / 失败路径 / 安全边界**

- clean PAUSED + 全部非 inflight：RESUMABLE。
- 任何未知 side effect：RECOVERY_REQUIRED，不 fallback 到“当作没执行”。
- repo identity mismatch：INVALID。
- Reconciler 只提出经过校验的新 snapshot，不直接创建 Worker 或选择接任 Worker。

**本步测试**

- PENDING/READY/COMPLETED/FAILED/BLOCKED 恢复矩阵；
- CLAIMED/RUNNING 的无副作用、已有副作用、证据缺失分支；
- retry 未耗尽与耗尽；
- worktree/checkpoint missing、HEAD/dirty drift；
- STOPPED Worker 不复活；
- old IN_FLIGHT message 的 requeue/recovery-required；
- 同一 report 重复应用幂等。

**完成标志**

没有任何 CLAIMED/RUNNING Task 因“数据库里写着 RUNNING”就重新开始执行。

**与下一步关系**

Step 10 把 report 接到 Session 的顶层 writer ownership 与 resume 状态机。

### Step 10：接入 SessionService，而不是创建第二个 Resume 入口

**目标与原因**

让现有 `SessionService.resume()` 继续是唯一顶层入口。Team runtime 作为 runtime factory/hook 被重建，而不是另写一个绕过 Session writer lock 的命令。

**涉及文件（未来）**

- `codeteam/session/models.py`：增加最小 `TeamStateRef` 或 revision hint；
- `codeteam/session/service.py`：升级具名 RuntimeFactory request；
- `codeteam/agent_team/session_integration.py`：Team adapter；
- `tests/session/test_team_runtime_resume.py`。

**建议 Session 字段**

```python
class TeamStateRef(BaseModel):
    db_filename: Literal["team_state.sqlite3"]
    schema_version: int
    acknowledged_revision: int


class Session(BaseModel):
    # existing fields...
    team_state: TeamStateRef | None = None
```

`db_filename` 是固定枚举值，不接受任意路径。真正路径仍由 protected `session_dir()` 组合。

**完整 resume 调用顺序**

```text
JsonSessionStore.load
  -> reject terminal
  -> acquire SessionWriterLock
  -> SessionReconciler(repo/worktree/checkpoint/provider)
  -> TeamStore.load + schema gate
  -> compare Session hint / DB revision
  -> TeamStateReconciler
  -> TeamStore.commit(reconciled snapshot + recovery events, CAS)
  -> TeamRuntimeFactory.hydrate(new coordinator/runtime_id)
  -> JsonSessionStore.save(RUNNING + acknowledged revision)
  -> append SESSION_RESUMED(correlation/revision/runtime_id)
  -> return ResumeOutcome(session, TeamRuntime)
```

**异常语义**

- Team DB not found while Session says it exists：`SessionRecoveryRequiredError`；
- DB corrupted/unsupported：映射为明确 recovery issue，不能创建空 Team；
- CAS conflict：`SessionAlreadyActiveError` 或独立 `TeamStateConflictError`，并释放 writer lock；
- hydrate factory 失败：Session 不发布 RUNNING，writer lock 释放，Team durable event 保留真实失败；
- Session save 失败：下次依据 DB revision ahead 进入 reconciliation；
- 成功后 writer lock 保持，pause/terminal transition 时释放。

**Python 知识**

- `Protocol` 取代 `Callable[[Session], Any]` 可以表达参数含义；
- `try/except BaseException` 只用于保证 lock release 后原样传播，不把 KeyboardInterrupt 伪装成业务成功；
- `dataclass(frozen=True)` 适合 `ResumeOutcome` 这类不可变返回值。

**本步测试**

- Single-Agent Session 无 team_state 时保持兼容；
- Team Session 成功 resume 返回新 TeamRuntime；
- factory 收到 durable Session/snapshot，不收到旧 runtime；
- DB ahead/hint ahead 两类 crash window；
- 每条失败路径释放 writer lock；
- 成功保持 lock，pause 后释放；
- event correlation 包含 session_id/team revision/new runtime_id。

**完成标志**

CLI/上层只调用一个 Session resume，Team 重建完整发生在该安全边界内。

**与下一步关系**

Step 11 用两个真实进程验证 writer ownership 与 CAS，而不是只测两个 Python 对象。

### Step 11：验证双 resume 只有一个 writer

**目标与原因**

证明并发恢复不会创建两个都认为自己拥有 Session 的 Team Runtime。

**涉及测试（未来）**

- `tests/session/test_team_double_resume.py`
- 可新增仅供测试调用的小型 helper module，不把测试 hook 暴露给正常 CLI。

**接口参数与返回值**

测试 helper 接受 `session_dir`、同步 sentinel 路径和有限 timeout 配置；成功进程输出结构化 `session_id/runtime_id/revision`，竞争失败进程输出结构化错误码。不要通过解析 traceback 判断业务结果。

**必要 Python 语法**

- `subprocess.Popen` 启动两个独立解释器；
- `communicate(timeout=...)` 有界回收；
- `pathlib.Path` 创建 tmp sentinel；
- `json.dumps/loads` 传递结构化测试结果。

**测试编排**

使用 `multiprocessing` 或真实 `subprocess.Popen`。推荐真实 subprocess：

```python
process = subprocess.Popen(
    [sys.executable, "-m", "tests.helpers.resume_worker", str(session_dir)],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    shell=False,
)
```

两个进程通过 `tmp_path` 下的 sentinel/Event 协调，同时尝试 acquire，不使用长 `sleep()` 碰运气。所有 `communicate()`/`wait()` 都设置 timeout，失败时 kill 并收集输出。

**断言**

- 只有一个进程得到 Session writer lock 并成功发布 RUNNING；
- 另一个得到 `SessionAlreadyActiveError` 或 CAS conflict；
- Team revision 只按成功事务增加；
- 只有一个 runtime_id 被记录为已发布；
- loser 不产生 Runtime、不改任务、不追加成功事件；
- winner pause 后，新进程才可 resume。

**安全边界**

- 不操作主仓库；Session、Git repo、DB 都位于 function-scoped `tmp_path`；
- subprocess 使用 argv、`shell=False`、timeout 和输出捕获；
- 不通过无限 retry 让测试“偶尔通过”。

**正常路径 / 失败路径**

- 正常：winner 获得 writer ownership、发布新 runtime 并保持 lock。
- 预期竞争失败：loser 明确退出且零副作用，这不是测试失败。
- 非预期失败：两个都成功、两个都修改 revision、子进程超时或出现 traceback，测试必须失败并保留诊断。

**完成标志**

并发重复运行测试稳定，且失败进程没有任何业务副作用。

**与下一步关系**

Step 12 从“并发竞争”升级到“事务中途进程被硬退出”。

### Step 12：真实 kill-process crash test

**目标与原因**

证明 SQLite transaction 中途进程死亡后，不会出现 state/event split brain。graceful shutdown、捕获 SIGTERM 后 save 都不能冒充 crash test。

**涉及测试（未来）**

- `tests/agent_team/test_team_store_process_crash.py`
- `tests/session/test_team_resume_process_crash.py`
- `tests/helpers/team_store_crash_worker.py`

**接口参数与返回值**

crash helper 接受 DB 路径、crash point 枚举和 sentinel 路径，以约定 exit code 退出；父测试随后调用正常 `store.load()` / `SessionService.resume()`，以领域对象或领域异常作为结果。

**测试方案 A：事务中途 `os._exit()`**

子进程：

```text
BEGIN IMMEDIATE
UPDATE team_state
INSERT first event
write sentinel "inside-transaction"
os._exit(91)
```

父进程等待 sentinel 后收集 return code，再用全新 connection load。

预期：

- 旧 revision N 仍完整；
- first event 不存在；
- 数据库可重新打开；
- 没有 state/event split brain。

**测试方案 B：Team commit 后、Session save 前退出**

子进程在 Team commit 成功后写 sentinel，再 `os._exit(92)`。新进程 resume 时应发现：

```text
db_revision > session.acknowledged_revision
```

然后进入 reconciliation，而不是直接开始调度。

**测试方案 C：RUNNING Task 已有 Git 副作用**

在 `tmp_path` 初始化独立 Git repo，设置 local user.name/email，commit baseline。子进程把 Task 标为 RUNNING 并修改文件后 `os._exit()`。新进程必须看到 dirty/head/checkpoint evidence，不能无脑 requeue。

**Python/subprocess 知识**

- `os._exit(code)` 不执行 finally、atexit 或 buffer flush，适合模拟非 graceful process death；
- sentinel 必须先 flush/fsync，父进程才能可靠同步；
- `Popen` 的 stdout/stderr 用 `communicate(timeout=...)` 回收，避免僵尸进程。

**正常路径 / 失败路径 / 安全边界**

- 正常：未 crash 的 control 子进程完成 commit，revision 与 event 一起前进。
- 事务中 crash：新进程只能看到旧完整 revision。
- commit 后 crash：新进程看到完整新 Team revision，并因 Session hint 落后进入 reconciliation。
- 安全边界：只在 tmp Session/仓库上执行 `os._exit()`；绝不对测试主进程、项目仓库或真实用户数据使用该操作。

**本步测试**

- transaction before/after commit 两个 crash 点；
- WAL/rollback recovery 后 `PRAGMA integrity_check`；
- state/event revision 对齐；
- old runtime tokens 在新进程被拒；
- CLAIMED/RUNNING reconciliation 与 Git evidence；
- 测试不访问真实用户目录、主仓库或 fixtures。

**完成标志**

你拥有至少一个真实 `os._exit()` 证据，而不是只 mock `commit()` 被调用。

**与下一步关系**

Step 13 整理可审查证据，并明确哪些实验尚未运行。

### Step 13：整理 DD、Failure Cases、日志和架构证据

**目标与原因**

代码与测试通过后，把选择、限制和失败证据落盘。此步不允许把未跑实验写成结果。

**未来涉及文件**

- `docs/design_decisions/DD-W5-06.md`
- `docs/failure_cases/W5_TASK_STORE_FAILURE.md`
- `docs/benchmark/W5_TASK_STORE.md`
- `test_log/YYYY-MM-DD_week5_day6_task_store_log.md`
- `learning-plan/代码架构.md`
- `learning-plan/设计决策.md`

**接口参数与返回值**

此步不新增 production API。输入是固定 commit 上的测试结果、raw samples 和已登记 Failure Case；输出是可追溯文档。没有证据的字段必须写 `NOT_RUN` / `PENDING`。

**必要 Python/工具知识**

- 用 `.venv/bin/python -m pytest` 保证解释器一致；
- 用 JSON/JSONL 保存 raw samples 时显式写 schema/version；
- 用 `git diff --check` 检查空白错误，但不执行 `git add/commit` 代替用户决策。

**DD-W5-06 计划**

标题建议：`DD-W5-06: SQLite Snapshot + Event History for Durable Team Runtime`。

至少比较：

1. memory-only；
2. JSON snapshot；
3. pure event sourcing；
4. SQLite snapshot + event history（选择）。

记录：

- authority boundary；
- CAS 与 single-writer；
- state/event 同事务；
- Session JSON/SQLite 非原子限制；
- WAL sidecar 与路径权限；
- schema migration/gate；
- external exactly-once 不在保证范围；
- Evidence 状态先写 `IMPLEMENTED_WITH_TESTS` 或 `PROPOSED`，由真实证据决定。

**Failure Case 模板**

```markdown
## F-W5-D6-XX: <name>

- Trigger:
- Expected invariant:
- Actual observation:
- Root cause:
- Fix / containment:
- Regression test:
- Remaining limitation:
- Evidence command:
```

至少登记：lost mailbox message、stale lease accepted、state/event split brain、Session/Team revision mismatch、RUNNING duplicate side effect、schema guessed by defaults、DB placed in workspace、WAL sidecar omitted。

**本步验证**

- 文档中的接口与最终代码一致；
- 所有数字都能追溯到 raw samples；
- test log 区分 passed/failed/skipped；
- Benchmark/Ablation 标记 `NOT_RUN`，等待周末；
- `git diff --check` 与 Markdown 围栏检查通过。

**正常路径 / 失败路径 / 安全边界**

- 正常：每个结论都能链接到命令、测试名或 raw sample。
- 失败：文档接口与代码不一致、复制旧 benchmark 数字、把 capability skip 写成通过。
- 安全边界：日志不写 API key、绝对用户 secret 路径或模型原始敏感输出；历史失败事实只追加纠正，不覆盖删除。

**完成标志**

功能证据、失败证据和未验证范围都可审计，才算 Day6 功能闭环。

**与下一步关系**

周末在固定 commit 上执行 Benchmark/Ablation；不是继续扩展 Day7 功能。

## 6. Test Strategy：从 round-trip 到真实 crash

### 6.1 分层测试地图

| 层级 | 重点 | 是否需要真实子进程/Git |
| --- | --- | --- |
| Model unit | schema、cross-field invariants、JSON round-trip | 否 |
| Store unit | initialize/load/commit/CAS/schema/corruption | 否，使用真实 tmp SQLite |
| Transaction fault injection | UPDATE/event 中途异常与 rollback | 否 |
| Hydration integration | DAG/Registry/Scheduler/Mailbox 新对象重建 | 否 |
| Reconciliation integration | Task matrix + Git/Checkpoint evidence | Git 使用 tmp repo |
| Session integration | writer lock、revision mismatch、pause/resume | 可先同进程 |
| Multi-process | double resume、writer ownership | 是 |
| Crash integration | `os._exit` 于事务中途/跨存储窗口 | 是 |

### 6.2 必须覆盖的 Store 用例

```text
[ ] initialize + load round-trip
[ ] duplicate initialize 不覆盖
[ ] commit revision N -> N+1
[ ] stale expected_revision 冲突
[ ] state 与 event 同事务 rollback
[ ] event seq 严格递增
[ ] schema_version unknown 明确拒绝
[ ] malformed snapshot_json -> corrupted
[ ] SQLite header/表缺失 -> corrupted
[ ] session_id/path traversal/symlink 拒绝
[ ] read-only load 不意外创建 DB
[ ] WAL sidecar 位于 protected session_dir
```

### 6.3 必须覆盖的恢复语义

```text
[ ] DAG nodes/dependencies/确定性拓扑恢复
[ ] Task attempt 不归零
[ ] Worker previous generation 保留，新 live generation 前进
[ ] restart budget/cooldown policy 不因进程重启绕过
[ ] ready queue 顺序、waiting 状态和 membership 一致
[ ] Mailbox per-recipient FIFO 恢复
[ ] seen_message_ids/delivery_attempt 恢复
[ ] new runtime_id 与 previous_runtime_id 不同
[ ] 旧 WorkerLease 全部被拒
[ ] 旧 TaskClaim 全部被拒
```

### 6.4 Task 恢复矩阵

| 状态 | 默认恢复结果 | owner | queue | 关键断言 |
| --- | --- | --- | --- | --- |
| PENDING | PENDING | None | 否 | 依赖满足后才 schedule |
| READY | READY | None | 是，保序 | 不重复入队 |
| CLAIMED | reconciliation | 先清除 | 视预算/证据 | 不继续旧 claim |
| RUNNING | RECOVERY_REQUIRED 或安全 requeue | 先清除 | 不直接入队 | 必查 Git side effect |
| COMPLETED | COMPLETED | None | 否 | 永不复活 |
| FAILED | FAILED | None | 否 | 除非 durable facts 已明确处于 retry READY |
| BLOCKED | BLOCKED | None | 否 | 不因 hydration 自动解锁 |

### 6.5 并发测试规则

- 用 `threading.Barrier`、`Event` 和带 timeout 的 `join()`；
- 多进程用 sentinel 文件或 stdout 行同步；
- 不用长 `sleep()` 或重复直到通过；
- 所有 subprocess 使用 argv list、`shell=False`、timeout、capture output；
- 失败时打印 stdout/stderr，但不泄漏 secrets；
- Git 测试每项在 function-scoped `tmp_path` 自行 `git init`，只设置 repo-local identity；
- 不操作项目主仓库和原始 fixtures。

### 6.6 kill-process 验收不能偷换概念

下面这些都**不算**真实 crash evidence：

- 调用 `pause()` 后正常退出；
- mock `connection.commit()` 抛普通异常；
- 捕获 SIGTERM 后执行 finally save；
- 只杀 Worker 线程但主 Runtime 仍活着；
- 只测试 JSON load。

至少一个用例必须让子进程在事务中执行 `os._exit()`，父进程随后用全新 connection 和全新 Runtime 恢复。

## 7. Benchmark Plan（周末执行，本轮不填数字）

### 7.1 分开测量五段时间

不要只记录一个模糊的“resume latency”。定义：

```text
T_load
  打开 SQLite、schema gate、读取并 Pydantic validate snapshot

T_reconcile
  对账 Task/Worker/Message 与 Git/Checkpoint

T_hydrate
  创建 new Coordinator/Registry/Scheduler/Mailbox/Lifecycle

T_persist
  CAS commit reconciled snapshot + events

T_recovery_ready
  从 resume 开始到 Runtime 可安全接受新 claim
```

校验关系可以近似为：

```text
T_recovery_ready
  ~= T_load + T_reconcile + T_persist + T_hydrate + Session 发布开销
```

但必须分别记录原始区间，不能只根据总时间倒推。

### 7.2 Workload

固定三档：

| 规模 | Tasks | 建议 edges | Messages | Events |
| --- | ---: | ---: | ---: | ---: |
| Small | 100 | 明确记录 | 明确记录 | 明确记录 |
| Medium | 500 | 明确记录 | 明确记录 | 明确记录 |
| Large | 1000 | 明确记录 | 明确记录 | 明确记录 |

每档都要记录状态分布，例如 PENDING/READY/COMPLETED/FAILED/BLOCKED 比例与 inflight 数量，否则两个“1000 Task”并不公平。

### 7.3 统计与复现信息

- warmup 次数与 measured iterations；
- p50/p95，不只平均值；
- 每次 raw sample，不只汇总表；
- cold process / warm filesystem cache 分开；
- Python version、`sqlite3.sqlite_version`、OS、CPU、disk/filesystem；
- journal_mode、synchronous、DB 大小、WAL 大小；
- commit hash、dirty 状态、schema version、seed。

本日功能完成不要求某个预填毫秒门槛。周末先收数据，再决定是否需要规范化表或增量持久化。

## 8. Ablation Plan（独立 adapter，不削弱生产安全路径）

### 8.1 对照组

| 实验 | Full | Ablated | 正确性门禁 |
| --- | --- | --- | --- |
| A1 persistence | SQLite snapshot + event transaction | memory-only adapter | crash 后是否丢全部 Team state |
| A2 storage | SQLite snapshot + events | JSON snapshot adapter | CAS/并发/state-event split 测试 |
| A3 fencing | new runtime_id + reject old tokens | test-only no-runtime-fence adapter | 旧 lease/claim 是否污染新 Runtime |
| A4 mailbox | commit-before-return | test-only pop-before-persist adapter | `os._exit` 后是否 lost message |
| A5 reconciliation | Git-aware fail-closed | test-only blind requeue adapter | 是否重复 RUNNING side effect |

### 8.2 公平性

- Full/Ablated 使用同一 snapshot、DAG、消息和 crash point；
- 只替换被研究的 adapter，不修改 production guard；
- 同一机器、Python、SQLite、次数和 warm/cold 条件；
- 先跑 correctness gate，错误结果不能进入性能排名；
- 无 fencing 对照必须在隔离测试 adapter 中实现，绝不能给生产入口增加关闭安全检查的开关。

### 8.3 证据边界

本教程没有执行任何 ablation，也没有数字。实验状态：

```text
WEEKEND_PLANNED / NOT_RUN
```

## 9. Day6 完整架构与恢复时序

### 9.1 运行时架构

```text
                         SessionService
                               │
                    SessionWriterLock (single writer)
                               │
              ┌────────────────┴────────────────┐
              │                                 │
      JsonSessionStore                 SQLiteTeamStateStore
 Session/repo/model/lifecycle      DAG/tasks/workers/mailbox/events
              │                                 │
              └──────────── revision ───────────┘
                               │
                    TeamStateReconciler
                               │
                   GitWorkspace/Checkpoint
                               │
                    TeamRuntimeFactory
                               │
                 new TeamStateCoordinator
                    new runtime_id = R2
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   AgentRegistry         TaskScheduler        AgentMailbox
          │                    │                    │
          └──────────── AgentLifecycleManager ──────┘
```

### 9.2 Resume 时序图

```text
Caller       SessionService     JsonStore     TeamStore      Reconciler      Factory
  |                |                |             |               |             |
  | resume(id)     |                |             |               |             |
  |--------------->| load           |             |               |             |
  |                |--------------->|             |               |             |
  |                | acquire writer lock          |               |             |
  |                | load team                    |               |             |
  |                |----------------------------->|               |             |
  |                | compare revisions            |               |             |
  |                | reconcile Session/Git/Team   |               |             |
  |                |--------------------------------------------->|             |
  |                | commit reconciled state+event CAS            |             |
  |                |----------------------------->|               |             |
  |                | hydrate NEW runtime_id                       |             |
  |                |----------------------------------------------------------->|
  |                | save RUNNING + acknowledged revision         |             |
  |                |--------------->|             |               |             |
  | ResumeOutcome  |                |             |               |             |
  |<---------------|                |             |               |             |
```

任何箭头失败都必须有明确错误与 lock 行为；不能静默 fallback 到空 Team 或 host-only Runtime。

## 10. 状态持久化 / 重建 / 丢弃矩阵

| 状态 | 持久化 | 新进程重建 | 丢弃/替换原因 |
| --- | --- | --- | --- |
| DAG nodes/dependencies | 是 | 新 TaskDAG | durable scheduling contract |
| Task status/attempt/failure | 是 | 经 reconcile 后导入 Scheduler | retry/terminal 语义必须保留 |
| owner_id/generation | 作为旧历史事实 | inflight 时先清理/对账 | 旧 owner capability 已失效 |
| ready queue/waiting | 是 | 保序恢复并校验 | 防重复/丢任务 |
| Agent identity/role/capabilities | 是 | worker factory 重建 | WorkerAgent 对象不可持久化 |
| Worker generation | 保存 previous | 发布新 Worker 时前进 | 拒绝旧 generation callback |
| restart_attempts | 是 | 保留 | 防重启绕过预算 |
| monotonic heartbeat/cooldown | 否 | 新 origin；必要时用 UTC 配方 | 跨进程数值不可比 |
| runtime_id | 保存 previous 用于审计 | 必须生成新值 | 使旧 lease/claim 失效 |
| WorkerLease/TaskClaim 对象 | 否 | 不重建 | capability 只属于旧 runtime |
| Mailbox pending/inflight/message order | 是 | 恢复并 reconcile | 防 lost/duplicate message |
| seen_message_ids | 是 | 恢复 | process restart 后仍去重 |
| Team events | 是 | 只读历史，不 replay 成 callback | audit/recovery evidence |
| RLock/thread/connection/callback/sink | 否 | 注入新对象 | ephemeral resource |
| Git files | 不进 SQLite | 通过 GitWorkspace 读取 | Git 是副作用权威 |
| checkpoint IDs | Session 引用 | 由 manager/probe 校验 | 只保存引用，不复制文件 |

## 11. 核心 invariants

Day6 实现后至少满足：

1. **Single authority**：Task live status 只由 Scheduler 修改，SQLite 是其 durable 投影；Session JSON 不是第二 Task 权威。
2. **New epoch**：每次 process resume 创建新 `runtime_id`。
3. **Token invalidation**：旧 WorkerLease/TaskClaim 在新 Runtime 的任何 mutating API 都被拒。
4. **Attempt preservation**：process restart 不重置 Task attempt/retry budget。
5. **Generation fencing**：重建 Worker 的 generation 前进，旧 generation callback 不能污染新 Worker。
6. **No blind RUNNING resume**：CLAIMED/RUNNING 必须 reconciliation。
7. **Atomic Team commit**：一个 mutation 的 Team state 与 Team events 全部提交或全部回滚。
8. **CAS**：过期 revision 不覆盖新 durable state。
9. **Mailbox commit-before-return**：message 消费状态持久化成功后才向 caller 返回。
10. **Observer is not commit**：event sink 失败不决定 durable transaction 是否成功。
11. **Controlled path**：SQLite/WAL 只能位于受保护 Session 目录，不在 repo/worktree。
12. **Schema gate**：未知 schema 明确迁移或拒绝，不让 Pydantic 默认值猜测。
13. **Fail closed**：DB/Git/checkpoint/revision 不一致时不创建可调度 Runtime。
14. **One writer**：同一 Session 同时最多一个成功 resume owner。

## 12. P0/P1 风险清单

### P0：会破坏恢复正确性或放大副作用

- 接受旧 runtime_id 的 lease/claim；
- RUNNING Task 未对账就重新执行；
- SQLite state 已更新但 event 未提交，或相反；
- Mailbox 先 pop 后 persist 导致消息永久丢失；
- DB 损坏/缺失时创建空 Team 并继续；
- Session hint 高于 DB revision 仍自动运行；
- SQLite 路径可被 Agent 控制到仓库、symlink 或敏感目录；
- 两个进程同时获得 writer ownership。

### P1：不会立即越权，但会破坏预算、审计或可恢复性

- restart budget/attempt 在 process restart 后归零；
- ready queue 顺序或 waiting membership 漂移；
- seen_message_ids 丢失导致重复入队；
- future schema 被默认值静默加载；
- WAL sidecar 被漏掉、误删或暴露权限；
- factory 失败后 Session 被错误标为 RUNNING；
- reconciliation/event sink 在核心锁内造成死锁；
- SQLite `busy` 被无限重试而没有有界 timeout；
- event history 无 retention，长期增长失控。

## 13. 推荐实现文件清单

这些是后续实现建议，本轮没有创建：

```text
codeteam/agent_team/
├── persistence_models.py       durable Pydantic contracts
├── persistence_errors.py       Store/schema/CAS/path errors
├── team_store.py               Protocol + SQLiteTeamStateStore
├── reconciliation.py           TeamStateReconciler/report
├── runtime_factory.py          TeamRuntime + hydrate
├── session_integration.py      Session RuntimeFactory adapter
├── dag.py                      public durable definition builder
├── registry.py                 validated hydration/export boundary
├── scheduler.py                validated hydration/export boundary
├── mailbox.py                  durable receive + hydration/export
├── coordination.py             snapshot/transaction participation
└── __init__.py                 stable public exports

codeteam/session/
├── models.py                   optional TeamStateRef
└── service.py                  named runtime build hook

tests/agent_team/
├── test_team_state_models.py
├── test_sqlite_team_state_store.py
├── test_team_snapshot.py
├── test_team_hydration.py
├── test_team_reconciliation.py
└── test_team_store_process_crash.py

tests/session/
├── test_team_runtime_resume.py
├── test_team_double_resume.py
└── test_team_resume_process_crash.py
```

若实现时发现必须大幅修改 Day5 mutating transaction，先停下来更新 DD 与测试计划；不要用“退出时保存一次 snapshot”掩盖运行中 crash window。

## 14. 推荐验证命令

所有命令必须使用项目解释器：

```bash
.venv/bin/python -m pytest tests/agent_team/test_team_state_models.py -q
.venv/bin/python -m pytest tests/agent_team/test_sqlite_team_state_store.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_hydration.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_reconciliation.py -q
.venv/bin/python -m pytest tests/session/test_team_runtime_resume.py -q
.venv/bin/python -m pytest tests/session/test_team_double_resume.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_store_process_crash.py -q
.venv/bin/python -m pytest tests/session/test_team_resume_process_crash.py -q
.venv/bin/python -m pytest tests/agent_team tests/session -q
.venv/bin/python -m ruff check codeteam/agent_team codeteam/session tests/agent_team tests/session
.venv/bin/python -m mypy codeteam/agent_team codeteam/session tests/agent_team tests/session
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/sandbox -q -rs
git diff --check
```

历史 mypy 债与 Day6 新增诊断必须分开报告。不得用 skip/xfail、降低断言或重试直到通过隐藏缺陷。只有可选外部能力确实不可用时才允许 capability-based skip，并说明未验证范围。

## 15. 完成标准

### 15.1 Day6 功能完成标准

```text
[ ] Authority map 与 durable contract 已实现并测试
[ ] SQLite schema/path/permission/schema gate 通过
[ ] initialize/load/commit/CAS/event transaction 通过
[ ] 完整一致快照不读取私有 dict
[ ] DAG/Registry/Scheduler/Mailbox 从 durable state 重建
[ ] new runtime_id 与旧 token 失效得到测试证明
[ ] attempt/generation/restart budget/queue/message dedupe 正确恢复
[ ] CLAIMED/RUNNING 经过 Git-aware reconciliation
[ ] SessionService 是唯一顶层 resume 入口
[ ] 两进程双 resume 只有一个 writer
[ ] 至少一个 os._exit transaction crash test
[ ] 至少一个 Team commit/Session save crash-window test
[ ] DD、Failure Cases、test log 与架构文档更新
[ ] focused/full pytest 与触达范围 ruff 通过
[ ] mypy 新增诊断为零，历史债单独列出
```

### 15.2 周末实验完成标准

```text
[ ] 固定 commit 与 clean/dirty manifest
[ ] 100/500/1000 Task workloads
[ ] T_load/T_reconcile/T_hydrate/T_persist/T_recovery_ready 分段
[ ] p50/p95 + raw samples
[ ] Python/SQLite/OS/机器/journal/synchronous 记录
[ ] cold/warm 分开
[ ] Ablation correctness gate 先通过
[ ] Full 与各 adapter 保持同一 crash scenario
[ ] 报告不编造数字、不把模拟说成真实 crash
```

Day6 功能可以在周末数字尚未产生时标记“功能验收通过，实验待周末”；不能写成整个工程证据全部完成。

## 16. 面试表达

### 16.1 30 秒版本

> Week5 Day5 只处理 Runtime 还活着时的 Worker 失效。Day6 我增加了 SQLite TeamStateStore，让 DAG、Task runtime、Worker durable metadata、ready queue、Mailbox pending state 和 Team events 可以跨进程恢复。Resume 不会反序列化旧对象，而是持有 Session writer lock，加载并 reconcile Session、SQLite 与 Git，创建新的 Coordinator 和 runtime_id，再 hydrate Registry、Scheduler 与 Mailbox。旧 lease/claim 自动失效，RUNNING Task 不会盲目重试。

### 16.2 两分钟版本

> 我把状态分成三类权威：JsonSessionStore 管 Session 生命周期、仓库和 provider/model；SQLiteTeamStateStore 管 Team DAG、Task/Worker runtime 投影、队列、Mailbox 和 Team events；GitWorkspace/Checkpoint 管真实代码副作用。Team mutation 使用 expected_revision 做 CAS，并把 snapshot 与 event 放进一个 SQLite transaction，event sink 只是 observer。
>
> Process resume 时必须产生新的 runtime_id。旧 WorkerLease 含旧 runtime_id，旧 TaskClaim 还含旧 attempt/generation，所以无法进入新 Runtime。Task attempt、Worker generation 历史和 restart budget 会保留，但 monotonic heartbeat 被丢弃并在新进程重新建立。CLAIMED/RUNNING 会先与 Git、checkpoint 和操作证据对账；不能证明副作用安全时进入 RECOVERY_REQUIRED。
>
> Session JSON 与 SQLite 不是同一个数据库事务，所以我不声称跨文件原子。我用 Session writer lock、Team revision hint、固定提交顺序和 fail-closed reconciliation 处理 SQLite ahead/Session ahead 两类 crash window，并用两个进程同时 resume 和事务中途 os._exit 的测试证明边界。

### 16.3 深挖追问

**为什么不用 JSON？**

JSON 原子替换适合单快照，但 Task state、Mailbox 消费和 Team event 需要同事务与 CAS。SQLite 更适合 local-first 单机 Runtime；不是因为“数据库一定高级”。

**为什么不用纯 Event Sourcing？**

当前恢复首先需要可靠 current state。纯 replay 会引入 event schema evolution、projection 与长日志恢复成本。V1 选择 snapshot + event history，后续有证据再演进。

**为什么新 runtime_id 还要 generation/attempt？**

runtime_id 拒绝跨进程旧 token；generation 拒绝同一 Runtime 内旧 Worker incarnation；attempt 拒绝同一 Worker/同 generation 的旧 Task 执行结果。三者解决不同迟到问题。

**SQLite transaction 已经原子，为什么还要 reconciliation？**

事务只覆盖 Team DB，不能证明 Git 文件、容器命令或 Session JSON 与它一致。Reconciliation 负责跨 authority 对账。

**Mailbox 如何避免丢消息？**

不能沿用内存版先 `popleft()` 后保存。必须把消费状态和 received event 先提交，再向 caller 返回；更强语义可做 claim/ack，但外部副作用仍不承诺 exactly-once。

**SIGKILL 任意点都能完全恢复吗？**

不能这样宣称。我们证明 SQLite 事务边界、几个明确 crash window 和 fail-closed reconciliation；尚不保证外部工具副作用 exactly-once，也不保证所有任意指令点都可自动恢复。

## 17. 明确不实现的内容

Day6 V1 明确不做：

- 分布式数据库或跨机器共识；
- 多主 Runtime；
- PostgreSQL/Redis backend；
- 真实跨机器 Worker 调度；
- 外部副作用 exactly-once；
- 对任意 SIGKILL 指令点的完全自动恢复；
- 反序列化旧 WorkerAgent、锁、线程、connection 或 callback；
- 让旧 lease/claim 跨进程继续有效；
- 把 event replay 建成完整 pure event-sourced Runtime；
- 在本日执行 Week5 周末 Benchmark/Ablation。

这些不是遗漏，而是 V1 的证据边界。未来扩展时也必须保持 Store Protocol、authority 和 fencing 不变量。

## 18. 实现前需要你确认的设计选择

教程推荐默认采用下面四项；真正开始 Step 1 时请逐项确认：

1. **Snapshot 存储形态**：V1 用一行结构化 JSON snapshot + 独立 events table；达到性能证据阈值后才规范化 Task/Message 表。
2. **Mailbox delivery**：V1 是 commit-before-return 的 destructive receive，还是直接实现 claim/ack？教程推荐 claim/ack 更稳，但实现量更大。
3. **Restart cooldown**：跨进程保持 UTC deadline，还是只保留 restart budget 并在 resume 后重新开始 cooldown？安全优先建议保持 deadline。
4. **Session/Team 发布顺序**：先 Team CAS commit、后 hydrate、最后 Session RUNNING；接受 DB-ahead 窗口并由 reconciliation 收敛。

无论选择哪一项，都不能改变这些硬约束：新 runtime_id、旧 token 失效、RUNNING 不盲目继续、Team state/event 同事务、Session/Team 不伪装成跨文件原子事务。

## 19. 2026-09-01 实施结果

用户已确认四项设计选择，并授权按 Step 1-13 实现：

1. 立即规范化 Task/Message/Worker/queue/ownership/event SQLite 表；
2. Mailbox 使用 durable claim/ack，并提供 matching release；
3. restart cooldown 保存 timezone-aware UTC deadline，hydrate 时换算新 monotonic；
4. 发布顺序固定为 Team CAS commit、hydrate、Session RUNNING save/event。

本轮已实现 durable contract、normalized SQLite Store、state/event transaction、CAS、
一致快照、DAG/Registry/Scheduler/Mailbox hydration、new runtime epoch fencing、
Git-aware reconciliation、Session integration、双进程 writer ownership，以及选定的真实
`os._exit` crash-window tests。完整设计与边界见：

- `docs/design_decisions/DD-W5-06.md`
- `docs/failure_cases/W5_TASK_STORE_FAILURE.md`
- `test_log/2026-09-01_week5_day6_task_store_log.md`

Coder 验证结果为全量 `1836 passed, 9 skipped`；9 项均为当前环境无法访问 Colima
Docker socket 的既有 Docker integration skips，Day6 测试没有 skip。触达范围 Ruff
通过；mypy 本轮新增文件诊断为零，但默认目标命令仍受测试 namespace package 与项目
既有 import-chain/type 债阻塞，详见测试日志。

Benchmark/Ablation 仍按周末统一执行，当前只有
`docs/benchmark/W5_TASK_STORE.md` 计划，没有数字、raw samples 或性能结论。Day6 当前
状态是“功能实现与 Coder 自验通过，独立 tester 和周末实验待完成”，不能写成全部工程
证据闭环。
