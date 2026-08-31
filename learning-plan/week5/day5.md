# Week5 Day 5：Agent Lifecycle + Failure Recovery

这次我先按你 **最新 `week5` 分支的真实代码** 来设计教程，而不是沿用之前那版通用计划。

我刚检查了当前公开 `week5/codeteam/agent_team/`，现在已经有：

```text
agent_team/
├── dag.py
├── lead.py
├── mailbox.py
├── models.py
├── scheduler.py
└── worker.py
```

还没有 `lifecycle.py` 和 `registry.py`。更重要的是，你当前 Scheduler 已经不是简单 Demo：它有明确的 Task 状态机 `PENDING → READY → CLAIMED → RUNNING → COMPLETED/FAILED`、`attempt`、原子 claim、role-aware scheduling 和 retry；但 **Worker 的运行状态目前被 Scheduler 自己维护了一份，而 `WorkerRegistry` 又在 `worker.py` 里维护另一份 Worker 身份数据**。这正是 Day5 应该解决的真实问题。

所以今天真正的目标不是简单“写个 heartbeat”。

而是：

> **把 Worker 从“Scheduler 顺便管理的对象”，升级成具有独立生命周期、健康状态和故障恢复语义的 Runtime Entity。**

---

# 一、先理解今天的核心问题

现在你的运行流程大概是：

```text
Task DAG
   ↓
Scheduler
   ↓
Worker A claim T1
   ↓
T1 = CLAIMED
   ↓
Worker A start
   ↓
T1 = RUNNING
```

目前 Scheduler 在 claim 时会同时维护：

```python
_worker_runtime_status[worker_id] = AgentStatus.BUSY
_worker_current_task[worker_id] = node_id
```

完成或失败后再把 Worker 释放。也就是说：

```text
Scheduler
既管理 Task 状态

又管理 Worker 是否 BUSY

又管理 Worker 当前执行哪个 Task
```

这在 Day3 是合理的，因为当时重点是 Scheduler。

但进入 Day5 后，这个边界开始不合理。你需要把两个“真相”分开：

```text
TaskScheduler
负责 Task

AgentRegistry
负责 Agent
```

最终：

```text
Task authority                 Agent authority

TaskScheduler                  AgentRegistry
─────────────                  ─────────────
PENDING                        CREATED
READY                          READY
CLAIMED                        BUSY
RUNNING                        FAILED
FAILED                         STOPPED
COMPLETED                      RESTARTING
attempt                        heartbeat
owner_id                       current_task
                               generation
```

这就是今天最关键的架构调整。

---

# 二、为什么工业级 Agent 要有 Lifecycle？

我们先看一个真实场景。

假设有三个 Worker：

```text
backend-1
frontend-1
test-1
```

Scheduler 给 `backend-1` 分配：

```text
T3: Implement OAuth callback
```

状态：

```text
T3
READY
 ↓
CLAIMED
 ↓
RUNNING

owner = backend-1
attempt = 1
```

然后 Worker 正在：

```text
调用 LLM
↓
修改 auth.py
↓
运行 pytest
```

突然：

```text
进程崩了
```

此时 Scheduler 看到的仍然可能是：

```text
T3 = RUNNING
owner = backend-1
```

如果没有生命周期系统：

> 这个任务可能永远卡在 RUNNING。

所以 Multi-Agent Runtime 需要解决四件事：

```text
1. 怎么知道 Worker 还活着？
        Heartbeat

2. 多久没响应算故障？
        Timeout

3. Worker 挂了怎么办？
        Restart

4. 它的任务怎么办？
        Reassignment
```

这四件事其实形成完整闭环：

```text
Heartbeat
   ↓
Failure Detection
   ↓
Revoke Worker
   ↓
Recover Task
   ↓
Restart / Replace Worker
   ↓
Reassignment
```

---

# 三、Heartbeat 到底是什么？

## 1. 最通俗的理解

Heartbeat 就是 Worker 定期告诉 Runtime：

> “我还活着，而且目前状态正常。”

比如：

```text
backend-1
每 5 秒
    ↓
Registry

I am alive
current_task = T3
```

伪代码：

```python
lifecycle.heartbeat("backend-1")
```

Registry：

```python
last_heartbeat = now
```

仅此而已。

---

# 四、Heartbeat 和普通消息有什么区别？

这个问题对你当前 CodeTeam 很重要，因为你已经有 `mailbox.py`。

当前 Mailbox 已经明确支持：

```text
TASK_ASSIGNED
TASK_PROGRESS
TASK_COMPLETED
TASK_FAILED
REVIEW_FINDING
REQUEST_HELP
INFO
SHUTDOWN_REQUESTED
```

同时每个 Agent 有独立 inbox、message id 和 task/correlation 信息。

所以你可能自然会问：

> Heartbeat 要不要也通过 Mailbox 发？

我建议：

## 不要。

应该区分：

```text
Data / Collaboration Plane

Mailbox
├── TASK_COMPLETED
├── REQUEST_HELP
├── REVIEW_FINDING
└── TASK_PROGRESS
```

和：

```text
Control Plane

Lifecycle / Registry
├── heartbeat
├── health
├── timeout
├── restart
└── failure detection
```

### 为什么？

如果 heartbeat 也经过 Mailbox：

假设 Worker 的 Mailbox 因为大量任务消息堵塞：

```text
Mailbox Backpressure
```

heartbeat 也处理不了。

Runtime 就可能认为：

```text
Worker dead
```

实际上 Worker 明明还活着。

所以：

> **健康检测不应该依赖业务通信路径。**

这和大型分布式系统的设计非常像：

业务请求是一条路径；

健康检查是另一条控制路径。

---

# 五、工业界案例一：Google/Kubernetes 的 Liveness 与 Readiness

这是今天最值得理解的工业设计之一。

Kubernetes 不使用：

```python
pod.alive = True
```

这么简单的状态。

它区分：

### Liveness

> 这个进程是不是仍然健康？

失败：

```text
restart container
```

### Readiness

> 它现在是不是能接任务？

失败：

```text
不再给它流量
```

### Startup

> 它是不是还在启动？

用来避免一个启动很慢的程序被误判成死亡。

Kubernetes 官方还特别强调：如果 liveness 检测设置错误，会造成错误重启甚至级联故障；因此它提供周期、timeout 和 `failureThreshold`，而不是“一次没响应就 kill”。

这对你的 Agent Runtime 有直接启示。

---

## CodeTeam 映射

Kubernetes：

```text
Readiness
```

对应：

```text
AgentStatus.READY
```

表示：

> 可以 claim 新任务。

Kubernetes：

```text
Liveness
```

对应：

```text
heartbeat + timeout
```

表示：

> Worker 是否仍然存活。

所以：

```text
READY != ALIVE
```

这一点特别重要。

例如：

```text
Worker 正在执行 T1
```

状态：

```text
BUSY
```

它不是 READY。

但它：

```text
ALIVE
```

完全正常。

这就是为什么：

```python
alive: bool
```

无法描述 Agent Runtime。

---

# 六、Heartbeat 应该记录什么？

初学者可能会写：

```python
last_heartbeat: float
```

对于 MVP 可以。

但建议你今天至少理解完整结构：

```python
class AgentRuntimeRecord(BaseModel):
    agent_id: str
    status: AgentStatus
    current_task_id: str | None
    last_heartbeat: float
    generation: int
    failure_reason: str | None
```

其中：

### `last_heartbeat`

上次健康信号。

### `status`

当前 Lifecycle 状态。

### `current_task_id`

Worker 当前持有什么任务。

### `generation`

第几代 Worker。

这个以后非常重要。

例如：

```text
worker-1 generation=1
       ↓ crash

worker-1 generation=2
       ↓ restart
```

否则你不知道：

“现在这个 worker-1”

是不是之前那个 Worker。

---

# 七、Heartbeat 时间应该怎么设计？

这里有个很工程化但非常值得你掌握的问题：

## 不要在 timeout 算法里直接依赖 wall clock。

例如：

```python
time.time()
```

系统时间可能：

- NTP 校准
- 手工改时间
- 时间跳变

对于：

```text
elapsed duration
```

更适合：

```python
time.monotonic()
```

也就是：

```python
elapsed =
    monotonic_now
    -
    last_heartbeat_monotonic
```

但：

Event Log 里展示：

```text
2026-08-31 21:20:00
```

仍然应该使用 wall clock。

所以可以理解成：

```text
Timeout calculation
→ monotonic clock

Audit Event timestamp
→ wall clock
```

测试时进一步：

```text
inject FakeClock
```

而不是：

```python
time.sleep(15)
```

后面我会具体讲。

---

# 八、Timeout：多久没 Heartbeat 才算死？

最简单：

```python
if now - last_heartbeat > timeout:
    mark_failed()
```

例如：

```text
heartbeat interval = 5 s
timeout = 15 s
```

表示理论上丢了大约三轮 heartbeat 后才判断异常。

注意：

这里的 `5s / 15s` 只是示例参数，不是工业标准。

---

# 九、为什么不能“一次没收到就判死”？

考虑：

```text
LLM API 暂时卡顿
CPU 高负载
Python event loop 短暂延迟
测试进程占资源
系统调度抖动
```

如果：

```text
5 秒没 heartbeat
→ DEAD
```

系统会产生大量：

```text
false positive
```

然后：

```text
正常 Worker
被认为死亡
↓
任务被重新分配
↓
两个 Worker 同时执行
```

问题反而更大。

所以 Kubernetes 的 `failureThreshold` 思路非常值得学习：

```text
暂时没回应
≠
确认死亡
```

对于 CodeTeam Day5，我反而不建议现在引入过多：

```text
SUSPECT
UNHEALTHY
DEGRADED
ZOMBIE
...
```

状态。

可以保持简单：

```text
正常运行
→ 超过 timeout
→ FAILED
```

但 timeout 本身要有合理容忍窗口。

以后如果需要监控 UI，再增加：

```text
SUSPECT
```

即可。

---

# 十、三个 Timeout 千万不要混在一起

你的项目已经有多层 timeout。

Day5 之后至少会有：

```text
1. Command Timeout
   pytest 跑太久

2. Provider Timeout
   LLM API 不返回

3. Agent Heartbeat Timeout
   整个 Worker 不再健康
```

它们不是一回事。

例如：

```text
pytest timeout
```

可能只是：

```text
Task failure
```

不代表：

```text
Worker dead
```

所以一定不要：

```python
except TimeoutError:
    kill_worker()
```

统一处理。

---

# 十一、工业界案例二：Temporal 的 Heartbeat 思路

Temporal 是长任务可靠执行系统，它强调：

```text
Workflow / Activity
不能因为 Worker crash
就永久消失
```

官方定位就是让执行过程能够跨 crash、网络问题和基础设施故障继续恢复。

它对长时间运行任务采用 heartbeat / timeout / retry 这类机制：

```text
Worker 正在工作
      ↓
周期汇报健康/进度

Worker 消失
      ↓
Runtime 判断执行 attempt 失败

Retry Policy
      ↓
创建新的执行 attempt
```

对 CodeTeam 来说就是：

```text
Worker-1
执行 T3 attempt=1
     ↓
heartbeat timeout
     ↓
attempt=1 abandoned
     ↓
重新 READY
     ↓
Worker-2 claim
     ↓
T3 attempt=2
```

这正是你现在 Scheduler 里的：

```python
attempt
```

开始真正发挥价值的地方。

你的 Scheduler 当前 `TaskRuntimeRecord` 已经有：

```python
attempt: int
```

而 `claim()` 每成功一次就：

```python
attempt = record.attempt + 1
```

这一步已经做好了。

---

# 十二、这里有一个你当前代码非常值得修的地方：stale result

假设：

```text
Worker A
claim T1

attempt = 1
```

然后：

```text
A 心跳超时
```

Runtime：

```text
requeue T1
```

Worker B：

```text
claim T1

attempt = 2
```

此时：

```text
A 没死
只是卡了很久
```

突然回来，说：

```text
T1 completed!
```

那么：

> Runtime 能不能接受它？

当然不能。

这叫：

# Stale Result

---

## 你当前 Scheduler 的风险

当前 `TaskClaim` 已经返回：

```text
node_id
worker_id
attempt
claimed_at
```

但 `start()` / `complete()` / `fail()` 目前主要校验：

```text
node_id
worker_id
```

没有让调用方把 `attempt` 一起带回来。

现在两个不同 Worker 时：

```text
owner_id
```

可以挡住大部分旧结果。

但未来：

```text
同 worker_id restart
```

以后再次认领同一个 Task，就可能出现：

```text
generation 1 old result
vs
generation 2 new result
```

因此 Day5 是非常好的时机补：

```text
attempt fencing
```

例如：

```python
scheduler.complete(
    node_id,
    worker_id,
    attempt,
)
```

然后要求：

```python
record.owner_id == worker_id
and
record.attempt == attempt
```

否则：

```python
raise StaleTaskAttemptError
```

这个设计非常工业化。

---

# 十三、Restart 到底是什么意思？

这里必须结合你现在真实代码。

你当前的 `WorkerAgent` 非常轻：

```text
WorkerAgent
├── AgentInfo
└── supports(role)
```

它目前并不是：

```text
真正独立 OS Process
```

也没有：

```text
worker.run_forever()
process_pid
async task loop
```

`WorkerRegistry` 现在也只是一个内存 dict，用于 register / get / compatible。

所以今天如果教程直接让你实现：

```python
restart_process()
```

其实是假装系统已经具备 Worker Process Runtime。

不应该这么做。

---

# 十四、Day5 的 Restart 应该先做“逻辑重启”

目前建议：

```text
Agent FAILED
   ↓
RESTARTING
   ↓
重新构造 WorkerAgent
   ↓
保留 identity / role / capabilities
   ↓
generation + 1
   ↓
READY
```

即：

```text
worker-1 generation 1
        ↓
FAILED
        ↓
worker-1 generation 2
        ↓
READY
```

实现可以通过注入：

```python
WorkerFactory
```

例如概念接口：

```python
WorkerFactory = Callable[
    [AgentInfo],
    WorkerAgent,
]
```

LifecycleManager 只知道：

> “请创建一个新的 Worker 实例。”

至于将来是：

```text
Python object
asyncio Task
subprocess
Docker Worker
remote process
```

Lifecycle 不需要知道。

这就是好的 abstraction boundary。

---

# 十五、未来为什么这个设计有价值？

Week6 以后 Worker 真正执行代码时：

```text
WorkerAgent
     ↓
CodingAgentRuntime
     ↓
Worktree
     ↓
SafeExecutionService
```

甚至将来 Worker 可能是：

```text
remote runtime
```

但 Lifecycle API 不用改：

```python
restart(agent_id)
```

只需要替换：

```text
WorkerFactory
```

这就是 Runtime abstraction 真正购买的能力。

---

# 十六、Agent Reassignment：不是直接“指定另一个 Worker”

这是另一个非常关键的设计。

错误实现：

```python
if worker_dead:
    task.owner = worker_b
```

这会绕过 Scheduler。

正确流程：

```text
Worker A crash

   ↓

Lifecycle detects failure

   ↓

Registry:
A = FAILED

   ↓

Scheduler:
revoke A's task

   ↓

T1:
RUNNING
  ↓
FAILED
  ↓
READY

   ↓

normal scheduler flow

   ↓

Worker B claim T1
```

也就是说：

> Lifecycle 不应该自己选择 Worker B。

Lifecycle 只做：

```text
worker failure
→ task recovery
```

真正“谁来执行”仍然是：

```text
Scheduler
```

否则你会形成两个调度器：

```text
TaskScheduler
和
LifecycleManager
```

都在决定 task placement。

这是非常危险的。

---

# 十七、你当前 Scheduler 已经为这个设计打好了基础

你现在状态图已经是：

```text
PENDING
  ↓
READY
  ↓
CLAIMED
  ↓
RUNNING
  ↓
FAILED
  ↓
READY
```

`FAILED → READY` 本来就支持 retry。

所以 Worker crash 其实应该复用这条路径，而不是新造：

```text
CRASHED_TASK
REASSIGNED_TASK
...
```

状态。

---

# 十八、但是 crash 可能发生在 CLAIMED 阶段

这一点测试一定要覆盖。

场景：

```text
Task READY

 ↓

Worker A claim

Task = CLAIMED

 ↓

Worker 还没调用 start()

 ↓

Worker crash
```

你当前普通：

```python
fail()
```

主要处理的是：

```text
RUNNING → FAILED
```

但 `_TASK_TRANSITIONS` 实际已经允许：

```text
CLAIMED → FAILED
```

只是需要一个专门的 recovery API 把它用起来。

所以推荐 Day5 增加：

```python
scheduler.recover_worker_loss(...)
```

而不是强行调用：

```python
scheduler.fail()
```

---

# 十九、我建议的 Scheduler recovery contract

例如：

```python
recover_worker_loss(
    worker_id: str,
    *,
    reason: str,
) -> TaskRuntimeRecord | None
```

内部：

```text
find worker's current task

IF CLAIMED:
    CLAIMED → FAILED

IF RUNNING:
    RUNNING → FAILED

clear owner

IF retry budget remains:
    FAILED → READY
    enqueue

ELSE:
    remain FAILED
```

这样语义非常清楚：

```text
fail()
=
Worker 主动报告任务执行失败

recover_worker_loss()
=
Runtime 因 Worker 丢失而恢复任务
```

这两个 failure source 不一样。

---

# 二十、今天最重要的重构：Registry 成为 Agent Source of Truth

你现在：

```text
worker.py
```

里有：

```text
WorkerAgent
WorkerRegistry
```

而 Scheduler 又有：

```python
_worker_runtime_status
_worker_current_task
```

形成：

```text
WorkerRegistry
知道 Worker 身份

Scheduler
知道 Worker runtime 状态
```

Day5 以后建议正式变成：

```text
worker.py
    ↓
Worker behavior / capability


registry.py
    ↓
Agent runtime state authority


scheduler.py
    ↓
Task state authority
```

---

# 二十一、最终边界应该非常明确

## `worker.py`

负责：

```text
Who am I?
What can I do?
```

例如：

```python
worker.supports(AgentRole.BACKEND)
```

---

## `registry.py`

负责：

```text
Where is this Agent now?
Is it healthy?
What task does it own?
```

---

## `lifecycle.py`

负责：

```text
What should Runtime do
when health changes?
```

---

## `scheduler.py`

负责：

```text
What should happen
to the Task?
```

---

## `mailbox.py`

负责：

```text
What should Agents tell
each other?
```

这五个概念一定不要混。

---

# 二十二、`registry.py` 推荐设计

今天不要新建一个：

```text
AgentRegistry
```

然后同时保留原来的：

```text
WorkerRegistry
```

长期共存。

那会变成重复抽象。

应该：

> **演进现有 WorkerRegistry。**

第一阶段可以保留名字：

```python
WorkerRegistry
```

减少 Day3 Scheduler API 改动。

等 Reviewer/Test/Lead 全部进入 Lifecycle 后，再考虑：

```text
WorkerRegistry
    ↓
AgentRegistry
```

或者现在直接迁移成 `AgentRegistry`，并给旧 import 一个兼容 alias。

---

# 二十三、Registry 中应该有什么？

建议核心 Runtime Record：

```python
class AgentRuntimeRecord(BaseModel):
    agent_id: str
    role: AgentRole
    status: AgentStatus
    current_task_id: str | None = None
    last_heartbeat: float
    generation: int = 0
    failure_reason: str | None = None
```

不过请注意一个重要原则：

> 不要让 `AgentInfo.status`、Registry status 和 Scheduler `_worker_runtime_status` 三份状态同时存在。

你的 `AgentInfo` 当前已经含有：

```python
status: AgentStatus
```

而 AgentStatus 目前是：

```text
CREATED
READY
BUSY
FAILED
STOPPED
``` 


今天需要选定：

```text
Registry
=
Agent runtime status authority
```

Scheduler 不再维护自己的 `_worker_runtime_status`。

---

# 二十四、建议 AgentStatus 怎么调整？

你现在已有：

```text
CREATED
READY
BUSY
FAILED
STOPPED
```

我不建议今天突然扩成：

```text
CREATED
STARTING
READY
IDLE
BUSY
WAITING
SUSPECT
UNHEALTHY
DEAD
RECOVERING
RESTARTING
PAUSING
STOPPING
STOPPED
...
```

那是典型过度设计。

今天只建议增加：

```text
RESTARTING
```

形成：

```text
             ┌───────────┐
             │           │
             v           │
CREATED → READY ←──── BUSY
            │            │
            └─────┬──────┘
                  ↓
               FAILED
                  ↓
             RESTARTING
                  ↓
                READY

READY / BUSY → STOPPED
```

`FAILED` 在 Day5 可以代表：

> Worker 已被 Runtime 判定不可用。

以后如果真的需要：

```text
SUSPECT / DEAD
```

再根据 Observability 需求增加。

---

# 二十五、为什么 State Machine 比 boolean alive 强？

这就是今天的 DD-W5-05 核心。

假设：

```python
alive = True
```

它能告诉你：

```text
Worker 没死
```

但是完全无法回答：

### 问题1

它能接任务吗？

```text
READY？
BUSY？
```

---

### 问题2

它是正常退出还是故障？

```text
STOPPED？
FAILED？
```

---

### 问题3

它正在恢复吗？

```text
RESTARTING？
```

---

### 问题4

为什么不能 claim？

```text
BUSY？
FAILED？
STOPPED？
```

boolean 全部回答不了。

---

# 二十六、工业界案例：Kubernetes 为什么也不用单一 alive

Kubernetes 正是把：

```text
能不能服务请求
```

和：

```text
是不是活着
```

拆开。

这说明工业系统中的 Runtime Entity 通常需要多个状态维度，而不是一个布尔值。

CodeTeam 也是：

```text
Worker alive + BUSY
```

完全合法。

所以：

```text
alive=True
```

根本不是完整运行状态。

---

# 二十七、Microsoft AutoGen 给你的另一个启示

Microsoft AutoGen 的 Team 也不是“几个无状态函数”。

其官方接口对 Team/Agent 有：

```text
pause()
resume()
save_state()
load_state()
```

并且 `save_state()` 会保存每个 participant 和 group-chat manager 的内部状态；官方还提醒运行中的 Team 直接 save state 可能得到不一致状态。

这说明 Multi-Agent Runtime 有一个非常重要的观点：

> **Agent 是有生命周期和运行状态的实体。**

这也解释了为什么你当前：

```text
AgentStatus
Registry
LifecycleManager
```

是合理方向，而不是“为了架构漂亮多加几个类”。

---

# 二十八、Alibaba AgentScope 的启示

AgentScope 最新公开设计中，`AgentStateStore` 会保存恢复 Agent 所需要的状态，包括 context、summary、permission/tool state 等，使 Agent 可以在后续 invocation 中恢复。

你今天做的是：

```text
live runtime recovery
```

Day6 会做：

```text
durable recovery
```

两者区别：

```text
Day5

同一个 Runtime 活着
但 Worker 挂了
→ heartbeat recovery
```

```text
Day6

整个 CodeTeam process 挂了
→ TaskStore / Session recovery
```

一定不要混。

---

# 二十九、`lifecycle.py` 应该是什么角色？

LifecycleManager 本身不要保存一套 Agent dict。

它应该是：

# Policy / Coordinator

依赖：

```text
AgentRegistry
TaskScheduler
Clock
WorkerFactory
EventSink
```

概念结构：

```python
class AgentLifecycleManager:
    def __init__(
        self,
        registry,
        scheduler,
        *,
        heartbeat_timeout,
        clock,
        worker_factory=None,
        event_sink=None,
    ):
        ...
```

---

# 三十、核心 API

建议：

```python
heartbeat(agent_id)
```

```python
detect_dead_agents()
```

```python
recover_agent(agent_id)
```

```python
sweep()
```

其中：

### `heartbeat()`

只是：

```text
更新 Registry
```

### `detect_dead_agents()`

只是：

```text
识别 timeout
```

### `recover_agent()`

完成：

```text
invalidate Agent
+
recover Task
+
restart
```

### `sweep()`

相当于：

```text
periodic control loop
```

---

# 三十一、完整 Worker crash 恢复流程

今天必须把下面这条链真正理解透。

假设：

```text
backend-1
claim T3
attempt=1
```

当前状态：

```text
Registry

backend-1
status = BUSY
current_task = T3
heartbeat = 100
```

```text
Scheduler

T3
status = RUNNING
owner = backend-1
attempt = 1
```

---

## Step 1：Worker crash

之后：

```text
没有 heartbeat
```

---

## Step 2：Lifecycle Detector

时间：

```text
now = 120
timeout = 15
```

计算：

```text
120 - 100 > 15
```

判断：

```text
backend-1 unhealthy
```

---

## Step 3：先让 Worker 不可调度

Registry：

```text
BUSY
 ↓
FAILED
```

为什么先做这一步？

因为不能：

```text
task requeue
```

以后，Scheduler 又把任务重新给已经死掉的 Worker。

---

## Step 4：撤销 Task ownership

调用：

```python
scheduler.recover_worker_loss(
    "backend-1",
    reason="heartbeat_timeout",
)
```

---

Scheduler：

```text
T3

RUNNING
  ↓
FAILED
```

然后如果：

```text
attempt < max_attempts
```

则：

```text
FAILED
  ↓
READY
```

并：

```text
owner = None
```

---

## Step 5：Restart Worker

Registry：

```text
FAILED
 ↓
RESTARTING
```

WorkerFactory：

```text
create worker
```

generation：

```text
1 → 2
```

然后：

```text
READY
```

---

## Step 6：普通 Scheduler 再分配

可能：

```text
backend-2
```

或者：

```text
backend-1 generation2
```

claim：

```text
T3 attempt=2
```

---

最终：

```text
Task 没丢
Worker 可恢复
旧 attempt 不再有效
```

这才是完整 failure recovery。

---

# 三十二、为什么 Reassignment 不应该立即指定同 Role 的 Worker？

例如：

```python
for worker in registry.compatible(BACKEND):
    assign(worker)
```

看起来容易。

但这样 Lifecycle 自己开始实现：

- role matching
- availability
- fairness
- queue
- concurrency limit

也就是重新造 Scheduler。

正确：

```text
Lifecycle

只负责：

Task → READY
```

Scheduler：

```text
READY → CLAIMED
```

继续由它决定。

---

# 三十三、当前 Scheduler 哪些东西应该移出去？

目前 Scheduler 维护：

```python
_worker_runtime_status
_worker_current_task
```

同时 claim 时：

```python
_worker_runtime_status[worker_id] = BUSY
_worker_current_task[worker_id] = node_id
``` 


Day5 之后应该变：

```text
TaskScheduler
      ↓
registry.mark_busy(
    worker_id,
    node_id
)
```

complete：

```text
registry.mark_ready(worker_id)
```

fail：

```text
registry.release_task(worker_id)
```

最终删除：

```text
TaskScheduler._worker_runtime_status
TaskScheduler._worker_current_task
```

这是今天对现有仓库最有价值的架构改动之一。

---

# 三十四、为什么这么拆？

因为以后 Day6：

```text
SQLite TaskStore
```

需要持久化。

如果 Scheduler 有：

```text
worker_status=A
```

Registry 有：

```text
worker_status=B
```

TaskStore 又有：

```text
worker_status=C
```

你会陷入：

> 到底谁才是真相？

所以今天提前建立 invariant：

> **Agent lifecycle state has exactly one authority: AgentRegistry.**

---

# 三十五、Heartbeat 不要直接修改 Scheduler

另一个 invariant：

```python
heartbeat()
```

绝对不要：

```text
heartbeat
 ↓
scheduler complete/fail task
```

Heartbeat 只影响：

```text
Agent health
```

只有：

```text
Failure Detector
```

真正确认 Worker failure 后，

Lifecycle Manager 才协调：

```text
Registry + Scheduler
```

---

# 三十六、推荐新增 Event

你现在 EventType 已有大量：

```text
scheduler.task_scheduled
scheduler.task_claimed
scheduler.task_started
scheduler.task_completed
scheduler.task_failed
scheduler.task_retried
mailbox.*
```

但目前还没有 Lifecycle 专属事件。

建议加入：

```text
lifecycle.heartbeat_recorded
lifecycle.agent_failed
lifecycle.restart_started
lifecycle.restart_completed
scheduler.worker_task_recovered
```

不过注意：

### Heartbeat Event 可能很多

如果：

```text
3 workers
每5秒一次
```

问题不大。

以后：

```text
1000 workers
```

就会产生巨大 event volume。

所以工业系统经常：

```text
heartbeat state
高频更新

failure/recovery
完整记录
```

你今天可以：

- heartbeat event 可配置
- failure / restart 必须 audit

---

# 三十七、今天建议的代码变化

不是只新增两个文件。

按你当前真实代码，我建议：

```text
codeteam/agent_team/models.py
    ↓
补 RESTARTING / runtime contract

codeteam/agent_team/worker.py
    ↓
只保留 WorkerAgent

codeteam/agent_team/registry.py
    ↓
迁移并增强 WorkerRegistry

codeteam/agent_team/scheduler.py
    ↓
移除 duplicated worker runtime state
    ↓
增加 recover_worker_loss()
    ↓
最好增加 attempt fencing

codeteam/agent_team/lifecycle.py
    ↓
Heartbeat / Timeout / Restart

codeteam/events.py
    ↓
Lifecycle Events
```

测试：

```text
tests/agent_team/
├── test_registry.py
├── test_lifecycle.py
└── test_scheduler.py
```

---

# 三十八、Registry 建议接口

第一版不要做太多。

支持：

```python
register(worker)
```

```python
get(worker_id)
```

```python
compatible(role)
```

保留现有能力。

新增：

```python
mark_ready(worker_id)
```

```python
mark_busy(
    worker_id,
    task_id,
)
```

```python
heartbeat(
    worker_id,
    observed_at,
)
```

```python
mark_failed(
    worker_id,
    reason,
)
```

```python
begin_restart(worker_id)
```

```python
finish_restart(worker)
```

```python
timed_out(
    now,
    timeout,
)
```

这样已经足够 Day5。

---

# 三十九、推荐引入 Clock abstraction

不要测试：

```python
time.sleep(16)
```

这种测试又慢又不稳定。

定义：

```python
Clock = Callable[[], float]
```

默认：

```python
time.monotonic
```

测试：

```python
class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
```

然后：

```text
heartbeat at 0

advance 14
→ not dead

advance 2
→ dead
```

测试瞬间完成。

这是一种非常重要的 infrastructure testability 技巧。

---

# 四十、今天测试不要只测“Worker crash”

至少应该有下面这些。

## Test 1：Heartbeat 更新

```text
worker READY
 ↓
heartbeat
 ↓
last_heartbeat updated
```

验证：

状态不乱变。

---

## Test 2：没超过 timeout

```text
timeout = 15

elapsed = 14
```

结果：

```text
worker still healthy
```

---

## Test 3：超过 timeout

```text
elapsed = 16
```

结果：

```text
worker FAILED
```

---

## Test 4：BUSY Worker crash

```text
Worker A
T1 RUNNING
```

crash：

```text
T1 → READY
owner=None
```

---

## Test 5：CLAIMED 阶段 crash

非常重要：

```text
Worker A claim T1
但没 start
```

crash 后：

```text
T1
CLAIMED → FAILED → READY
```

---

## Test 6：新 Worker 重新认领

例如：

```text
backend-1 dead
backend-2 READY
```

最后：

```text
backend-2 claim T1
attempt=2
```

---

## Test 7：Retry budget exhausted

例如：

```text
max_attempts=1
```

第一次已经用了。

Worker crash：

Task 应：

```text
FAILED
```

而不是无限：

```text
READY
```

---

## Test 8：Role 不匹配

Backend task crash。

只有：

```text
frontend worker
```

结果：

```text
Task READY / waiting_for_worker
```

而不是错误交给 Frontend。

---

## Test 9：STOPPED Agent

用户主动 shutdown：

```text
STOPPED
```

不应该被 Failure Detector：

```text
自动 restart
```

因为：

```text
intentional stop
≠
crash
```

---

# 四十一、我强烈建议补一个 Test 10：Stale attempt

流程：

```text
A claim T1 attempt1

↓

A timeout

↓

B claim T1 attempt2

↓

A sends complete(attempt1)
```

期望：

```text
Rejected
```

然后：

```text
B complete(attempt2)
```

成功。

这个 test 非常有作品价值。

它说明你考虑的不只是：

```text
“worker 挂了以后重试”
```

而是：

> **并发恢复后的 fencing / stale execution 问题。**

---

# 四十二、Crash test 怎么模拟？

今天不要真：

```bash
kill -9
```

作为单元测试。

应该先：

```text
Fake Worker
+
Fake Clock
```

模拟：

```text
不再 heartbeat
```

Runtime 就把它视作 crash。

这测试的是：

```text
Lifecycle semantics
```

而不是操作系统。

以后做 Integration Test 时再：

```text
启动 Worker process
kill process
检测恢复
```

---

# 四十三、Benchmark 设计

虽然 Day5 原计划没有明确 Benchmark，但按照你的项目标准，我建议保留。

## Benchmark 1：Heartbeat Update Throughput

例如：

```text
1,000
10,000
heartbeats
```

测：

```text
updates/sec
```

---

## Benchmark 2：Failure Scan Latency

Registry：

```text
100
500
1000
agents
```

调用：

```python
detect_dead_agents()
```

记录：

```text
scan latency
```

结果先不要写数字。

---

## Benchmark 3：Recovery Latency

定义：

```text
failure detected
        ↓
task becomes READY
```

不是：

```text
crash发生
↓
检测
```

因为 heartbeat timeout 本身是人为配置的。

可以分：

```text
Detection latency
Recovery processing latency
```

两个指标。

---

# 四十四、推荐报告表

```text
| Agents | Heartbeat ops/s | Failure scan p50 | Failure scan p95 |
|--------|-----------------|------------------|------------------|
| 100    | pending         | pending          | pending          |
| 500    | pending         | pending          | pending          |
| 1000   | pending         | pending          | pending          |
```

不要编造。

---

# 四十五、Ablation：今天其实非常适合做

## Ablation A：boolean alive

实现最简单 baseline：

```python
alive: bool
```

然后设计：

```text
READY
BUSY
FAILED
STOPPED
RESTARTING
```

五个场景。

看看 boolean 是否能正确表达。

答案会非常明显。

这属于：

```text
architecture correctness ablation
```

而不是 performance benchmark。

---

## Ablation B：No attempt fencing

运行：

```text
Worker A stale result
Worker B valid result
```

观察：

是否可能错误完成 Task。

然后：

```text
attempt fencing ON
```

再比较。

这个 Ablation 对面试非常有价值。

---

# 四十六、Failure Cases 今天应该记录什么？

## F-W5-D5-01：Zombie Task

现象：

```text
Worker 已死
Task 永久 RUNNING
```

原因：

没有 Heartbeat / Timeout。

---

## F-W5-D5-02：False Worker Death

现象：

正常 Worker 被判 FAILED。

原因：

timeout 过短。

改进：

```text
heartbeat interval
+
grace threshold
```

---

## F-W5-D5-03：Duplicate Execution

```text
old Worker recovered
+
new Worker retry
```

同时执行。

原因：

没有 attempt fencing。

---

## F-W5-D5-04：Restart Storm

Worker：

```text
restart
↓
马上 crash
↓
restart
↓
crash
```

无限循环。

解决：

以后需要：

```text
restart budget
backoff
```

Day5 可以只记录 limitation。

---

## F-W5-D5-05：Wrong-role Reassignment

Backend task：

重新分给 Frontend Agent。

原因：

Lifecycle 绕过 Scheduler 自行选择 Worker。

解决：

```text
requeue only
Scheduler reclaims
```

---

# 四十七、DD-W5-05 应该怎么写

标题我建议：

> **Agent Lifecycle State Machine and Failure Recovery Ownership**

## Problem

Multi-Agent Worker 会：

- busy
- fail
- timeout
- restart
- stop

并且失败时其 Task 不能永久失去 owner。

---

## Alternatives

### A. boolean `alive`

简单：

```python
alive = True
```

不足：

无法表达 ready/busy/failed/stopped/restarting。

### B. Scheduler owns everything

当前 Day3 接近这个状态。

问题：

Task 和 Agent 两种状态耦合。

### C. Registry + Lifecycle + Scheduler

选择。

```text
Registry
→ Agent authority

Lifecycle
→ health/recovery coordination

Scheduler
→ Task authority
```

---

## Decision

采用：

```text
Agent state machine
+
heartbeat timeout
+
Scheduler-mediated task recovery
```

---

## Invariants

这部分很重要：

### I1

```text
Agent runtime state
only owned by Registry
```

### I2

```text
Task state / ownership
only owned by Scheduler
```

### I3

```text
Heartbeat never directly
changes Task state
```

### I4

```text
Dead Worker becomes unavailable
before Task is requeued
```

### I5

```text
Task reassignment must consume
a new attempt
```

### I6

如果实现 fencing：

```text
Old attempt result
must never settle new attempt
```

---

## Trade-offs

代价：

- 状态模型更复杂
- Registry/Scheduler 需要协调
- 测试更多

收益：

- crash recovery
- no zombie task
- observability
- future persistence
- multi-process extensibility

---

## Limitation

这里一定诚实写：

> 当前 WorkerAgent 仍是进程内 Runtime Object，因此 Day5 的 Restart 是逻辑重建，而非真实 OS/remote Worker process restart。

这个不丢人。

反而说明你清楚：

```text
implemented semantics
vs
future deployment runtime
```

的边界。

---

# 四十八、Day5 和 Day6 的边界

今天：

```text
Worker crash
CodeTeam process still alive
```

恢复。

明天：

```text
整个 CodeTeam process crash
```

恢复。

所以：

```text
Day5

volatile lifecycle state
+
worker failure recovery
```

```text
Day6

SQLite
+
durable task/agent state
+
process restart reconciliation
```

AgentScope 公开设计中也把 Agent State persistence 作为独立存储抽象，使状态可以跨 invocation 恢复；这正好对应你 Day6 要进入的 Durable State 问题。

---

# 四十九、今天的推荐实际编码顺序

不要先写 `lifecycle.py`。

建议：

```text
Step 1
models.py
确定 AgentStatus transition

↓

Step 2
registry.py
把 Worker runtime authority 搬进去

↓

Step 3
scheduler.py
删除重复 Worker runtime state

↓

Step 4
scheduler.py
增加 recover_worker_loss()

↓

Step 5
attempt fencing

↓

Step 6
lifecycle.py
Heartbeat / Timeout

↓

Step 7
restart hook

↓

Step 8
events.py

↓

Step 9
test_registry.py

↓

Step 10
test_lifecycle.py

↓

Step 11
scheduler regression
```

这样最稳定。

---

# 五十、今天完成后的真实架构

之前：

```text
                    Scheduler
                   /         \
                  /           \
             Task State     Worker State
```

Day5 后：

```text
                  LifecycleManager
                    /          \
                   /            \
            AgentRegistry     TaskScheduler
                 |                 |
          Agent Lifecycle      Task State
                 |                 |
            WorkerAgent          DAG
```

再加 Mailbox：

```text
             Multi-Agent Runtime

        ┌──────────┬──────────┐
        │          │          │
        ▼          ▼          ▼
    Registry   Scheduler   Mailbox
        │          │          │
        └──── Lifecycle ──────┘
```

这已经开始出现比较清晰的 **Control Plane**。

---

# 五十一、今天你真正要掌握的工业思想

不要把今天理解成：

> “写一个定时器检测 Worker。”

真正需要掌握的是四层思想：

```text
1. Health Detection
Heartbeat / Timeout

2. Explicit Runtime State
State Machine

3. Recovery Ownership
Registry vs Scheduler

4. Fencing
Old execution cannot corrupt
new execution
```

其中第 4 个尤其重要。

很多 Multi-Agent Demo 只能做到：

```text
Agent挂了
→ 再启动一个
```

真正 Runtime 需要解决：

> “旧 Agent 如果回来怎么办？”

这就是从 Demo 走向基础设施的重要分界线。

---

# 五十二、今天的验收标准

我建议你把 Day5 验收最终定成：

```text
[ ] 新增 registry.py
[ ] 新增 lifecycle.py

[ ] Registry 成为 Agent runtime status 的唯一 authority
[ ] Scheduler 不再维护重复 worker status/current_task

[ ] Worker 可以 heartbeat
[ ] Timeout 可以检测失活 Worker

[ ] READY/BUSY Worker 超时可进入 FAILED
[ ] STOPPED Worker 不被自动恢复

[ ] Worker loss 可以恢复 CLAIMED Task
[ ] Worker loss 可以恢复 RUNNING Task

[ ] Task 可以重新进入 READY
[ ] Compatible Worker 可以重新 claim
[ ] attempt 单调增加

[ ] 超过 retry budget 不继续 reassignment

[ ] 最好实现 stale attempt rejection

[ ] Lifecycle failure/restart 有 Event Log

[ ] 测试不使用真实 sleep
[ ] 使用 FakeClock

[ ] 有 Worker crash integration scenario
```

---

# 五十三、面试时你应该怎么讲

如果面试官问：

> 你的 Multi-Agent 系统里 Worker 崩了怎么办？

你不要只回答：

> “我有 heartbeat。”

更完整的表达应该是：

> 我把 Agent 和 Task 的运行状态分开建模。AgentRegistry 是 Worker 生命周期状态的唯一 authority，TaskScheduler 维护 Task 状态和 ownership。Worker 周期性发送 heartbeat，LifecycleManager 根据 timeout 判断 Worker failure；故障 Worker 会先从可调度集合中移除，再由 Scheduler 撤销其 CLAIMED/RUNNING Task，并在 retry budget 允许时重新进入 READY，由正常 Scheduler 流程重新分配。Task claim 带有递增 attempt，用于防止恢复过程中旧 Worker 的 stale result 覆盖新的执行结果。

如果再追问：

> 为什么不用 `alive=True/False`？

回答：

> 因为 liveness 和 readiness 不是一回事。Worker 可能存活但正在 BUSY，或者正常 STOPPED，也可能处于 FAILED/RESTARTING。Boolean 无法表达合法状态迁移，也无法为 Scheduler、Recovery 和 Persistence 提供稳定 contract，所以我使用显式 Agent state machine。

这就已经非常接近真正的 Agent Runtime / distributed scheduler 面试表达了。

---

## 今天最值得优先实现的三个点

如果你时间有限，Day5 先保证这三个：

```text
① Registry 成为唯一 Agent State authority

② Worker Timeout → Task READY → 新 Worker claim

③ attempt fencing 防 stale result
```

其中 **① 是架构正确性，② 是功能闭环，③ 是工业可靠性**。

做好这三个之后，再补 Restart、Lifecycle Events 和 Benchmark。

---

# 基于当前 Week5 代码的实施教程

> 编写基线：2026-08-31，`week5`，HEAD `25dc4c70ac433e0924a65cd2f3a43a320a812b63`。
> 本节是实施计划和教学参考，不是完成记录。生产实现、正式测试、DD 落盘和实验均待后续任务执行。
> 上文初步安排原样保留；其中建议接口与本节冲突时，后续实现以本节明确的契约为准。
> 本轮只追加本文件，没有修改 Python 文件、测试、配置或其他文档，也没有执行真实 API 或 Benchmark。

## 0. 先对齐事实，不从计划反推代码

### 0.1 现有事实

以下位置是本次只读检查的导航锚点。实现时行号会变化，应同时按类名、函数名定位。

| 当前文件与位置 | 已存在的事实 | Day5 如何使用 |
| --- | --- | --- |
| `codeteam/agent_team/models.py`：`AgentStatus`、`AgentInfo` | 状态为 CREATED / READY / BUSY / FAILED / STOPPED；尚无 RESTARTING | 扩展现有枚举，不创建另一套 WorkerStatus |
| `codeteam/agent_team/worker.py:28`：`WorkerRegistry` | 保存 Worker 对象，提供 register/get/compatible；没有 heartbeat、generation 或锁 | 演进为动态 Registry 的唯一实现，保留旧 import |
| `codeteam/agent_team/worker.py`：`WorkerAgent.info` | 构造和返回时已有防御性深拷贝 | 保持身份不被外部快照修改 |
| `codeteam/agent_team/scheduler.py:64`：`TaskRuntimeRecord` | 有 status、owner_id、attempt、failure_reason、claimed_at | 继续作为 Task 运行态权威，增加 owner generation |
| `codeteam/agent_team/scheduler.py:81`：`TaskClaim` | 已带 node_id、worker_id、attempt、claimed_at | 必须把返回的 claim 用作后续操作凭据 |
| `codeteam/agent_team/scheduler.py`：`start/complete/fail` | 当前参数主要是 node_id、worker_id；只校验 owner 和状态 | 尚不能拒绝同一 Worker 上旧 attempt 的迟到结果 |
| `codeteam/agent_team/scheduler.py`：`_worker_runtime_status`、`_worker_current_task` | Scheduler 维护 availability 与任务占用；单 Lock 保护自身状态 | 迁移 Agent 动态状态，但 Task ownership 仍归 Scheduler |
| `codeteam/agent_team/scheduler.py`：`_deliver_events` | 已在锁外调用 sink，并隔离普通 observer 异常 | 不退回旧版锁内回调设计 |
| `codeteam/agent_team/dag.py` | 七态 TaskStatus、拓扑快照、防御性复制、显式 dependency 校验 | 不再从原始 DAG.status 读取调度运行态 |
| `codeteam/agent_team/mailbox.py` | 同步、线程安全、非持久化、destructive receive；消息不会直接推进 Scheduler | 心跳另走控制通道，不接入 inbox backlog |
| `codeteam/events.py` | 已有 Scheduler、Mailbox、Week4 recovery/session 事件；尚无 Day5 Worker lifecycle 事件 | 后续扩展同一个 AgentEventType |
| `codeteam/agent/runtime.py:58` | `CodingAgentRuntime.run(CodingAgentRunRequest)` 已存在，是 CLI/eval 的统一执行内核 | Day5 不再创建第二套 Coding Loop |
| `codeteam/session/service.py:196` | resume 会 load、writer lock、reconcile、runtime_factory、save RUNNING、event | 不能把 Day5 内存 Registry 当成已接入 Session |
| `codeteam/execution/safe_execution_service.py` | execute_command 和 execute_patch 都已实现；后者先 checkpoint | 类注释中“Patch Lane 未实现”已落后于方法实现，不能照抄 |

**特别澄清：当前 WorkerRegistry 身份数据与 Scheduler 动态状态，是 Day3 有意做的职责拆分，不是已经存在两套动态 Agent 状态权威。**

为什么 Day5 还要演进？因为 heartbeat、timeout、restart 是任务认领之外的生命周期操作。如果 Lifecycle 再自己保存一份 alive/status，就会真正产生多写源。今天把这些动态字段集中到 Registry，并让 Scheduler 在同一事务边界内使用它。

### 0.2 原稿需澄清之处

| 原稿或早期教程的表达 | 本节采用的明确解释 |
| --- | --- |
| 先 timeout/requeue，再“最好补” attempt fencing | fencing 是前置必做项；验证通过前，不开放自动失活恢复链 |
| 只传 worker_id 的 heartbeat/recovery | 调用必须绑定 Worker generation；扫描结果还要带 revision，提交前重新验证 |
| `start(node_id, worker_id)` 足够 | 同一 worker_id 可以先后拿到同一 node 的两次 attempt，身份相同不代表执行批次相同 |
| Registry 与 Scheduler 各加一把锁 | 两把锁各自安全，不代表跨对象事务安全；本节采用共享协调锁 |
| timeout 等于 Worker 已死 | 只是控制面决定不再信任其当前执行资格，不能证明进程已经退出 |
| restart 后一律 READY | 只有匹配的 restart reservation、成功 factory、合法身份能力和未过期状态才能发布 READY |
| fail() 可直接处理所有 Worker loss | 当前 fail 只接受 RUNNING；失活恢复必须另覆盖 CLAIMED |
| 把所有 current_task 字段迁到 Registry | Task ownership 仍归 Scheduler；Registry 不保存第二份可写 Task owner |
| `AgentInfo.status` 也是实时状态 | 本节选择它仅为 bootstrap 初始化输入；注册后的实时查询走 Registry.runtime() |
| AgentScope 的 AgentStateStore 自动解决恢复 | 本次官方核对支持的是 StateModule / SessionBase / JSONSession；不把未核实的类名和恢复保证当事实 |
| 有 Session 就已经支持 Team resume | 当前 Session 没有 Team DAG/claim/generation 的 durable contract；Day6 另做 |

### 0.3 今日拟实现内容与证据边界

后续编码任务拟新增 `registry.py`、`lifecycle.py`，以及小型 `contracts.py`、`coordination.py`，修改 Scheduler 的 claim 协议和事件。后两个文件分别承载共享数据类型与共享锁，避免 Registry/Scheduler/Lifecycle 互相循环导入；它们不是第二个运行时或状态仓库。

本节阅读依据包括 Day2–Day4 教程、对应验收日志、2026-08-31 合并日志、`learning-plan/代码架构.md` 的控制面/Runtime 链路、`learning-plan/设计决策.md` 的 W5-D29–W5-D32，以及 DD-W5-01 至 DD-W5-04。

历史证据不要混为本次结果：

- Day3 早期验收记录过锁内 sink、可变 transition table 等问题；当前实现和 DD 已体现后续 hardening。
- Day4 早期日志记录的 broadcast 批内 ID、JSON payload 等缺口，当前代码已有对应修正和测试。
- 合并日志记录 Foundation 165 passed、授权 Docker 环境全量 1583 passed，属于该日志对应版本的历史证据，不是本教程重新运行的结果。
- 同一合并日志记录 agent_team 范围 mypy 既有 5 项诊断：dag 的类型推导、scheduler 测试未标注列表、模型/DAG 测试故意传字符串等；不能统称为 import-chain 问题。
- 当前本节不宣称任何 Day5 测试已经通过。

## 1. Today in the System 与 Capability Mapping

今天补的是 **Multi-Agent Orchestration 的 Worker Lifecycle / Failure Recovery / Ownership Fencing / Concurrency Consistency**。底层依赖 Agent Runtime 的结构化结果和安全执行边界，但不替代它们。

此前 Scheduler 能回答“谁认领了任务”。Day5 要进一步回答：

1. 这个 Worker 最近还有没有上报存活？
2. 原执行资格已经撤销，旧回调还能不能修改状态？
3. Worker 失联后，CLAIMED/RUNNING 的任务如何安全退回队列或终止？
4. 新 Worker 对象建好时，原重启申请是否仍然有效？
5. 一次操作结束后，两边状态与审计是否一致？

面试价值在于能讲清楚“不可靠执行者 + 可靠控制面”的设计，不是只会定时检查一个时间戳。今天交付的是进程内控制面协议及其测试计划；真正执行工具、进程终止和持久化是其他边界。

## 2. Theory：只补今天必须用到的概念

### 2.1 两个计数器，解决两类迟到问题

`attempt` 是某个 Task node 成功 claim 的次数；`generation` 是某个 Worker 身份成功发布的新对象代数。它们不能互相代替。

```text
同一 worker-id=w1，同一 generation=1：
  node=A, attempt=1 -> 失败 -> READY
  node=A, attempt=2 -> RUNNING
  attempt=1 的迟到 complete 到达
  只查 owner_id==w1 会误完成 attempt=2

同一 worker-id=w1，发生逻辑重启：
  generation=1 -> FAILED -> RESTARTING -> generation=2 READY
  generation=1 的 heartbeat / factory 回调到达
  只查 worker_id==w1 会污染新对象
```

所以 Task 操作校验完整 claim；Worker 操作校验 generation。timeout 候选再携带 revision，以识别“仍是同一 generation，但心跳或任务状态已经更新”的情况。

### 2.2 Fencing 不是杀进程，也不是 exactly-once

Fencing 是提交资格检查：旧 token 不能提交到新状态。它不会终止已经在执行的 Python 函数，也不会撤回已经发出的 HTTP 请求、文件写入或 Docker 命令。

因此今天只能证明：**旧执行结果不能污染新的 Scheduler/Registry 状态**。未来接入真实 Worker 时，还需要受控执行入口、取消机制、独立 worktree、提交前再次校验、外部操作幂等或去重。不能把一次锁内检查解释成跨工具执行全程的独占保证。

### 2.3 Liveness、readiness、progress 是三个问题

- Liveness：是否及时收到当前 generation 的心跳。
- Readiness：当前能不能接受新 claim，例如 READY 且未占用。
- Progress：任务是否产生了有效进展；周期心跳并不证明工作有进展。

BUSY 可以持续心跳；READY 也必须能被检测为失活。心跳线程活着但执行线程卡住时，heartbeat timeout 不会解决任务无进展，未来需独立 Task execution/progress timeout。

### 2.4 锁、原子性和线性化点

锁让其他遵守同一把锁的线程暂时不能读取或修改中间态。它不会自动撤销你已经做过的一半写入，也不会保护不拿这把锁的调用方。

一次 claim 的逻辑提交必须同时满足：

```text
Task: READY -> CLAIMED，owner/attempt/generation 写入
Queue: node 从 deque 和 membership set 同时移除
Worker: READY -> BUSY
Ownership index: worker -> claim 同步更新
Audit: 成功事实记录
```

任何一项漏更新都不算原子 claim。今天的线性化点，是共享锁内提交完整的新状态，而不是“调用了 lock.acquire()”。

## 3. Industrial Design：官方事实、推断、项目选择

只核对与本日取舍有关的官方资料，核对日期为 2026-08-31；不引入这些框架作为依赖。

| 对照 | 官方公开事实 | 工程推断 | CodeTeam 本日选择 |
| --- | --- | --- | --- |
| Kubernetes probes | liveness 失败可触发容器重启；readiness 失败影响接收流量；startup probe 可在初始化阶段抑制其他探测。官方警告错误探测会导致级联故障。 | “还能工作”和“允许接新任务”应分开；初始化阶段应有明确语义。 | 借鉴状态区分，但不实现 kubelet、Pod 调度或 failureThreshold 算法；采用显式超时策略。 |
| Temporal Activity heartbeat | Heartbeat Timeout 后 Activity 可按 Retry Policy 再调度；Activity 重试需要考虑幂等。 | 没收到心跳不能作为外部副作用未发生的证明。 | Scheduler 有界 retry + claim fencing；不声称有 Temporal durable history。 |
| AutoGen BaseGroupChat | 提供 pause/resume/save_state/load_state；pause/resume 依赖 participant hooks，默认可无操作；运行时 save_state 可能不一致。 | 生命周期控制和一致快照不能用函数名代替实际协议。 | 逻辑重启只重建 Worker facade；一致状态需共同事务，持久化留 Day6。 |
| AgentScope State/Session | StateModule 提供状态注册、state_dict/load_state_dict；SessionBase 抽象与 JSONSession 管理 Session 状态。 | 可重建数据与运行对象应该分开，但存储 API 本身不证明故障检测和旧回调隔离。 | 不沿用原稿未经核实的 AgentStateStore 权限恢复保证；今天不保存 runtime 对象。 |

来源：[Kubernetes probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/)、[Temporal 官方 timeout 文档源](https://github.com/temporalio/documentation/blob/main/docs/develop/typescript/activities/timeouts.mdx)、[Temporal Activity 重试与幂等](https://docs.temporal.io/develop/python/best-practices/error-handling)、[AutoGen Team API](https://microsoft.github.io/autogen/stable/reference/python/autogen_agentchat.teams.html)、[AgentScope State/Session](https://doc.agentscope.io/tutorial/task_state.html)。

本项目的备选方案：boolean alive 太弱；各组件独立可写 status 难以对账；直接采用分布式 Actor/Workflow 框架超出本日范围。选择 **单进程同步状态机 + 共享协调锁 + 显式 token + 逻辑重启**，先把可证明的范围做好。

## 4. Architecture / Data Flow 与文件地图

### 4.1 三类权威，不是三个互相同步的状态副本

```text
TaskDAG                         topology authority
TaskScheduler                   Task status / claim / retry / ownership authority
AgentRegistry                   Worker status / generation / heartbeat / restart authority
AgentLifecycleManager           扫描和恢复协调，无额外 Agent/Task 状态表
TeamStateCoordinator            共享锁、runtime_id、事务序号；不拥有业务状态
AgentMailbox                    通信，不是 heartbeat 通道或状态写入口
```

Registry 不保存独立可写 `current_task_id`。Scheduler 可以保留 `_worker_current_task` 作为 ownership 的内部索引，但它必须由 TaskRecord 推导并在同一事务维护；公共 API 不可单独改索引。若界面需要 Worker 当前任务，调用 Scheduler 的组合快照，不再给 AgentInfo 塞一份可写任务状态。

`AgentInfo.status` 本节选择 **初始化输入**：register 时读取一次，之后即使 Worker.info 中还显示旧值，也不得拿它调度。实时状态只读 `registry.runtime(worker_id)`。若将来选择把 info 做只读实时投影，需单独迁移，不要同时支持两套含义。

### 4.2 正常链与恢复链

```text
正常：
Registry 注册 -> 返回 WorkerLease(runtime_id, worker_id, generation)
Scheduler.schedule()
Scheduler.claim(lease) -> TaskClaim(..., attempt, worker_generation)
Scheduler.start(claim)
可信调用方提交结果 -> complete(claim) / fail(claim, reason)

失活：
Lifecycle.detect_timeouts() -> 不可变 TimeoutCandidate 快照
Scheduler.recover_worker_loss(candidate)
  -> 共享锁内重新验证 generation/revision/heartbeat/claim
  -> Worker FAILED + 撤销 Task ownership + 有界 READY/FAILED
  -> 锁外投递事件
Lifecycle.restart_worker(lease)
  -> 锁内 reserve -> 锁外 factory -> 锁内校验并 publish
正常 Scheduler.claim(新 lease 或其他兼容 Worker lease)
```

Lifecycle **不调用 claim 来替你选接任者**，也不调用 Worker.execute。重排只是让 Task 再具备被正常认领的资格。

### 4.3 后续实施涉及的文件

下表是未来修改地图，本轮未创建或修改这些文件。

| 文件 | 职责 / 变化 |
| --- | --- |
| `codeteam/agent_team/models.py` | 仅扩展现有 AgentStatus，加 RESTARTING；说明 AgentInfo.status 的 bootstrap 语义 |
| `codeteam/agent_team/contracts.py`（拟新增） | WorkerLease、WorkerRuntimeRecord、TimeoutCandidate、RestartTicket、恢复结果等共享纯数据；Clock Protocol |
| `codeteam/agent_team/coordination.py`（拟新增） | TeamStateCoordinator，共享 RLock 和 runtime_id；非第二个 Scheduler |
| `codeteam/agent_team/registry.py`（拟新增） | 唯一 AgentRegistry，身份注册、动态状态、heartbeat、restart reservation/publication |
| `codeteam/agent_team/worker.py` | WorkerAgent 保留；旧 WorkerRegistry/errors import 改为重导出，不保留旧实现 |
| `codeteam/agent_team/scheduler.py` | 强制 claim fencing、改用 Registry 动态状态、组合事务、recover_worker_loss、组合快照 |
| `codeteam/agent_team/lifecycle.py`（拟新增） | detect_timeouts / sweep / restart_worker / stop_worker 的协调 |
| `codeteam/agent_team/__init__.py` | 导出新对象和旧兼容名称 |
| `codeteam/events.py` | 同一事件系统内新增 Worker lifecycle 与 stale rejection 事件 |
| `tests/agent_team/test_registry.py`、`test_lifecycle.py`（拟新增） | FakeClock、状态、扫描、重启、失败与竞态 |
| `tests/agent_team/test_scheduler.py`、`test_mailbox.py` | 迁移显式 claim 调用；保留所有原语义断言，增加 fencing/recovery |
| `docs/design_decisions/DD-W5-05.md`（以后单独创建） | 本节 DD 草案落位、证据状态更新 |

### 4.4 真实 Runtime / Session / SafeExecution 的接入边界

已有 `CodingAgentRunRequest` 包含 task_id、workspace_root、provider/model、预算和 resume evidence，但**没有 TaskClaim/Worker generation**。`CodingAgentRuntime` 当前也不会验证 Team claim。不能因为 run() 已存在，就写成 Worker 已经自动复用它。

未来 adapter 应把 assignment 映射到统一 Runtime 请求，绑定可信 task/worktree，持有完整 claim；Runtime 结果返回后再调用 Scheduler fenced API。现有 state_callback/operation_callback 可作为后续集成点，不在今天伪装成已有 heartbeat agent。

SafeExecution 当前有 policy/approval/sandbox 和 checkpoint 边界，但不识别 Team attempt。今天 fencing 不自动延伸到 patch/command 执行中。未来必须讨论执行前授权、在途撤销、隔离 workspace 与提交/合并边界，不能拿 Scheduler 锁包住整个模型或 Docker 调用。

Session 继续只保存 durable facts，不能把 Registry、RLock、WorkerAgent 或 monotonic 绝对读数塞进 `runtime_state`。Day6 的 Team restore 需要新的 schema、对账及新 runtime epoch，不能将旧内存 generation 当跨进程租约。

## 5. Implementation：十个小步骤

### Step 1：先定义数据契约，讲清谁持有什么凭据

**目标与原因。** 先定义纯数据，再写状态方法。否则实现一半才发现 heartbeat 和 complete 都缺少代数参数，只能反复改接口。

**当前正确 / 待改。** 当前 TaskClaim 已有 attempt，Worker 身份有防御性快照；缺少强制 claim 输入、Worker generation 和 timeout 候选版本。位置：`models.py` 的 AgentStatus、`scheduler.py` 的 TaskClaim/TaskRuntimeRecord，拟新增 `contracts.py`。

**参数与返回契约。** 所有 token 都由可信 Registry/Scheduler 发出，不让 LLM 自己从状态表拼出“当前 token”。建议最小字段：

| 模型 | 必要字段 |
| --- | --- |
| WorkerLease | runtime_id、worker_id、generation（>=1） |
| TaskClaim（保留当前 scheduler.py 归属） | 原四字段 + runtime_id、worker_generation；attempt >=1；全部为必填 |
| TaskRuntimeRecord | 增加 owner_generation；无 owner 时为 None，已占用时须与 claim 一致 |
| WorkerRuntimeRecord | worker_id、status、generation、revision、last_heartbeat_monotonic、restart_attempts、next_restart_monotonic、restart_id |
| WorkerTimeoutCandidate | lease、worker_revision、observed_status、observed_at、last_heartbeat_monotonic、active_task（OwnedTaskToken 或 None） |
| RestartTicket | lease、restart_id、expected_revision、restart_attempt、用于 factory 的身份快照 |

为避免 `contracts.py -> scheduler.py -> contracts.py` 循环，TimeoutCandidate 的 task token 摘要定义为独立纯数据 `OwnedTaskToken(node_id, attempt, worker_generation)`，不从 contracts 导入 TaskClaim。公共结果需要 TaskRuntimeRecord 时放在 scheduler.py 定义。

**Python 知识。** `BaseModel` 做数据校验；`Field(ge=1)` 表示最小值 1；`str | None` 表示可能没有值。`frozen=True` 防止普通属性赋值，但含可变对象时不等于深度不可变，快照仍需防御性复制。`None` 不表示“自动采用当前 generation”。

局部参考，仅展示一个完整 token 模型：

```python
from pydantic import BaseModel, ConfigDict, Field


class WorkerLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    generation: int = Field(ge=1, strict=True)
```

`extra="forbid"` 拒绝拼错的额外字段；`strict=True` 避免把布尔值当代数。ID 继续沿用现有 strip/reject blank validator 的写法，单有 min_length 不会拒绝纯空格。

TaskClaim 的 future API 固定为：

```python
def claim(self, lease: WorkerLease) -> TaskClaim | None: ...
def start(self, claim: TaskClaim) -> TaskRuntimeRecord: ...
def complete(self, claim: TaskClaim) -> TaskRuntimeRecord: ...
def fail(
    self, claim: TaskClaim, reason: str, *, retryable: bool = True
) -> TaskRuntimeRecord: ...
```

这里 `...` 是接口示意，不是可交付函数体。`*` 之后的 retryable 必须用关键字传，减少参数位置误用。

**快速验证。** 计划测试 token JSON round-trip；缺 generation/attempt、零/负数/bool、空 ID 拒绝；快照修改不影响内部。此时不运行 timeout，也不执行任何工具。

**常见错误。** `attempt=None` 时查当前值；重启把 attempt 清零；把新 generation 写进旧 claim；把 TaskStatus 和 AgentStatus 混用。

**完成标志与 DD 关系。** 能用 w1/A 的两次认领解释两个计数器；所有必填 token 参数已确定。这是 DD 的“拒绝旧提交”契约，不是性能优化。

### Step 2：迁移 Registry，并建立跨对象事务边界

**目标与原因。** 把动态 Agent 状态统一起来，同时保证 Scheduler 和 Registry 的更新对外不可分割。先完成这一步，后面才能安全写 heartbeat 和 recovery。

**位置。** 拟新增 `registry.py`、`coordination.py`；迁移 `worker.py` 的 Registry 实现；替换 `scheduler.py` 的 `_worker_runtime_status`。已有 `_worker_current_task` 仅保留为 Scheduler ownership 索引，不迁成另一个状态权威。

**API。** `AgentRegistry(coordinator=None, clock=None)` 可自行创建默认协调域；`register(worker) -> WorkerLease`；`get(worker_id) -> WorkerAgent` 保持对象查询；`runtime(worker_id) -> WorkerRuntimeRecord` 返回复制快照；`compatible(role)` 继续只回答角色兼容。TaskScheduler 必须使用 Registry 的同一 coordinator，不另造锁。V1 一个 Registry 只绑定一个 Scheduler，第二次绑定不同 Scheduler 明确拒绝。

**初始化语义。** AgentInfo.status 只读一次。CREATED 暂不参与调度；READY 获得从注册时刻开始的一段心跳宽限；FAILED/STOPPED 不可调度。为保留已有 unavailable 测试，bootstrap BUSY 可以表示“预先保留、不可认领”，但不能据此捏造 Task owner。新运行中的 BUSY 只能由 claim 产生。

**Python 知识。** `RLock` 允许同一线程重入；`with` 保证退出时释放锁，但不负责业务回滚。共享的是**同一个锁对象**，不是两个类型相同的 RLock。初始化代码局部示例：

```python
from threading import RLock
from uuid import uuid4


class TeamStateCoordinator:
    def __init__(self) -> None:
        self.lock = RLock()
        self.runtime_id = f"team-runtime-{uuid4().hex}"
        self.transaction_seq = 0
```

协调域只存锁、epoch 与事务序号，没有 `_agents` 或 `_tasks`。不同 Registry 的 runtime_id 不同，即使 worker_id/node_id 恰好一样，旧 token 也不能跨域使用。

**原子性方案，不能省略。**

1. 所有 Registry 状态访问和 Scheduler 状态访问使用 coordinator.lock；公开快照也一样。
2. 跨对象操作由 Scheduler 的内部事务 helper 编排；Registry 只暴露包内的 `_..._locked` 状态校验/准备/发布 helper，Lifecycle 不直接改字典。
3. 在锁内先验证全部前置条件，再构造局部 draft：新 TaskRecords、queue、queued set、ownership index、Registry record、返回模型、待写 events。
4. 所有 Pydantic 校验、可能失败的领域计算、成功事件构造完成后，才发布 draft。提交阶段只替换已构造好的内部引用，不执行 validator、用户 callback、factory、I/O 或新的业务判断。
5. 采用 copy-on-write：draft 不修改旧 record 的嵌套字段。常规异常发生在发布前时，直接丢弃 draft，原快照不变。若提交封装仍保留可能抛异常的步骤，必须在锁内恢复保存的旧引用再重新抛出，不能解锁后补偿。
6. 跨两个对象的引用替换对遵守共同锁的读者不可见中间态。它不是进程崩溃事务，也不承诺从 OOM、强制 kill 中恢复；这些留给 durable store。
7. 释放最外层锁后才调用 event sink。不能在 RLock 内调用一个“自己会解锁投递”的公共方法，因为外层仍持锁。

不需要先写通用数据库事务框架。V1 可在 scheduler.py 写一两个明确的 prepare/commit helper；先用复制的小型 dict/deque 实现，周末再量化复制成本。Registry 的单 record heartbeat 更新同样先校验后替换，不必复制整个 DAG。

锁顺序固定：**唯一 core lock -> 包内无回调 helpers -> 解锁 -> observer/factory**。Mailbox、Session writer lock、Git/Docker 的锁不允许在 core lock 内获取；本日根本不调用这些执行路径。需要跨对象一致读时增加 `scheduler.snapshot()`，在同一锁内一次复制 Task/Worker/queue，不能把两次独立 snapshot 的拼接当作一致快照。

**兼容 import，不兼容不安全调用。** `worker.py` 保留 `WorkerRegistry` 的旧 import 名称，重导出 `AgentRegistry as WorkerRegistry`；公共包也同样导出。不要复制原类或写一个独立子类存另一份字典。DuplicateWorkerError/WorkerNotFoundError 也保留同一异常类型 identity。

为避免循环导入，registry.py 只在 `TYPE_CHECKING` 下导入 WorkerAgent，运行时不在模块顶层从 worker.py 导入它；registry 不负责构造 WorkerAgent。worker.py 可正常从 registry 重导出旧名称。`TYPE_CHECKING` 仅供类型检查，不会在普通执行时运行该块。

**快速验证。** register/get identity 保持、重复注册不覆盖；新旧 import `is` 相同；Scheduler/Registry coordinator `is` 相同；修改 runtime() 快照不污染状态；任一 prepare 校验失败时两边快照/queue/events 完全不变；第二 Scheduler 绑定被拒绝。

**常见错误。** Registry 增加 status 后还让 Scheduler 缓存 status；外部直接 `registry.runtime(...).status = ...`；`RLock` 被当作允许执行慢 callback 的理由；拿两份不同时间的快照误报不一致。

**完成标志与 DD 关系。** 唯一动态 Agent 权威、唯一 Task ownership 权威及一个共享原子更新域已经成立；测试能证明失败无半写，而不仅证明用了锁。

### Step 3：先完成强制 attempt fencing，再允许任何自动 recovery

**目标与原因。** 先用现有 fail/retry 就能构造同 Worker 的迟到结果，不必等 timeout 写完才测。此步是后面 Step 4–8 的安全前置门。

**位置。** `scheduler.py` 的 claim/start/complete/fail、`_require_owner_locked`、`_require_available_worker_locked`、`_release_worker_locked`；对应既有 Scheduler 与 Mailbox 测试调用点。

**API 与错误语义。** 使用 Step 1 的完整 claim 参数；新增 `StaleTaskClaimError`、`StaleWorkerGenerationError`，保留 TaskOwnershipError、StaleTaskStateError。不同 owner 报 ownership，代数或 attempt 过期报 stale，正确 claim 但阶段错误报 state。非法请求不修改状态、不产生成功事件。

claim 前校验 lease.runtime_id/generation、Worker READY、角色、未占用；成功 claim 才 `attempt += 1`，记录 owner_generation，生成必填字段齐全的 TaskClaim。Worker generation 不因 Task retry 增加。

局部参考：以下是 fenced helper 的关键比较，不是完整 Scheduler。

```python
def _require_claim_locked(self, claim: TaskClaim) -> TaskRuntimeRecord:
    self._require_record_locked(claim.node_id)
    record = self._records[claim.node_id]
    if claim.runtime_id != self._coordinator.runtime_id:
        raise StaleTaskClaimError("claim belongs to another runtime")
    if record.owner_id != claim.worker_id:
        raise TaskOwnershipError("claim owner no longer matches")
    if (
        record.attempt != claim.attempt
        or record.owner_generation != claim.worker_generation
    ):
        raise StaleTaskClaimError("claim attempt or generation is stale")
    worker = self._registry._runtime_locked(claim.worker_id)
    if worker.generation != claim.worker_generation:
        raise StaleWorkerGenerationError("worker was replaced")
    if worker.status is not AgentStatus.BUSY:
        raise WorkerUnavailableError(claim.worker_id)
    return record
```

helper 返回内部 record 仅供已持锁的内部逻辑读取，公开方法必须返回快照。之后仍须做 CLAIMED/RUNNING 的 expected-state 检查与原子提交，不能只执行 helper 就直接写 COMPLETED。

**Python 知识。** 多行 `if (...)` 用括号续行；`or` 任一不匹配就拒绝；`raise` 终止当前操作并向调用方传播领域错误。类型标注不会阻止别人 `model_construct()` 绕过校验，因此公开入口仍校验实例/字段和权威状态，不把 Pydantic 当认证系统。

**关键学习例子。** 后续测试必须使用实际返回的 claim，不查询内部“最新 attempt”补齐旧请求：

```python
first = scheduler.claim(lease)
assert first is not None
scheduler.start(first)
scheduler.fail(first, "transient failure", retryable=True)
second = scheduler.claim(lease)
assert second is not None
scheduler.start(second)

with pytest.raises(StaleTaskClaimError):
    scheduler.complete(first)

record = scheduler.runtime_records[second.node_id]
assert record.status is TaskStatus.RUNNING
assert record.attempt == second.attempt
scheduler.complete(second)
```

这个局部片段假定测试 helper 已创建 max_attempts=2、仅一个 node 和同一 READY Worker；不依赖 Docker/API。还要分别让旧 first 调 start、fail，验证不能破坏 second。

**迁移方式。** 既有 tests 使用 `start("A", "worker-1")`；后续实现任务须保存 claim 并改成 `start(claim)`，原 ownership/status/queue 断言全部保留。非 owner 测试用显式错误 worker 的完整 token，不能删掉。事件安全字段 allowlist 以后显式加入 generation/runtime/transaction metadata，不改成任意字段皆可。

只保留 import 兼容，**不保留**以下入口：`complete(node_id, worker_id, attempt=None)`、通过 overload 接受裸 worker_id、传字符串时自动查当前 claim。旧调用应明确失败，而不是静默兼容。

**快速验证。** 同 worker 同 generation attempt1 迟到 complete/start/fail；异 Worker owner mismatch；异 runtime token；缺 claim 调用拒绝；重复完成不能释放后来任务；既有 retry/dependency/role/sink 测试保持语义。

**常见错误。** 只测不同 Worker；以 claimed_at 的 float 相等代替 token；把 frozen claim 当不可伪造安全凭证。此协议面向可信控制面，raw Scheduler 不直接交给不可信模型。

**完成标志与 DD 关系。** attempt1 不能影响 attempt2，旧入口不存在；此门未通过时，不进入自动 timeout/retry。这是无 fencing ablation 的统一实验场景。

### Step 4：实现 Clock 与 generation-aware heartbeat

**目标与原因。** 时间由依赖注入控制，测试不用等 15 秒；heartbeat 只能更新当前 Worker，不能复活失效或停止的 Worker。

**位置。** contracts.py 的 Clock、registry.py 的 heartbeat / activation；models.py 的 RESTARTING。不修改 mailbox.py，也不发送 HEARTBEAT 业务消息。

**时间契约。** Clock 只提供本进程 monotonic 秒数。`AgentEvent.timestamp` 继续使用 make_event 的 wall clock。monotonic 用于超时/冷却，wall clock 用于人类审计，不能混算，也不持久化 monotonic 绝对值后跨进程比较。

**Python 知识与局部参考。** Protocol 是“对象须提供什么方法”的约定，FakeClock 不必继承它；dataclass 自动生成初始化；`-> float` 声明返回数字秒数。

```python
from dataclasses import dataclass
from math import isfinite
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float: ...


@dataclass
class FakeClock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not isfinite(seconds) or seconds < 0:
            raise ValueError("advance must be finite and non-negative")
        self.now += seconds
```

FakeClock 放后续 tests/agent_team 的 helper，生产 SystemClock 调 `time.monotonic()`。生产参数验证不能依赖 FakeClock 帮忙：timeout 必须 finite 且 >0；restart cooldown finite 且 >=0；max_restarts 为非 bool 的非负整数。Clock 返回 NaN/inf、负值或逆行时，抛明确 `InvalidClockError`，不当作“所有 Worker 正常/超时”。同一读数重复合法。

**API。** `registry.heartbeat(lease: WorkerLease) -> WorkerRuntimeRecord`；`activate(lease) -> WorkerRuntimeRecord` 仅用于 CREATED -> READY。两个方法都先校验 runtime_id/generation。heartbeat 仅接受 READY/BUSY，不把 FAILED/STOPPED/RESTARTING/CREATED 自动变 READY。

收到心跳时，用 Registry 自己读取的 Clock 值更新 last_heartbeat_monotonic，revision 加一。不要信任调用方上报的远端时间，不让它发送未来时间延长租约。先读时间还是先加锁须一致：本节选择锁内读取短小、无 I/O、无回调的 Clock；Clock adapter 的契约不允许重入业务逻辑。

同一协调域只有一份 Clock，由 Registry 注入并供 Scheduler/Lifecycle 读取，不分别使用三个 FakeClock。Registry 的内部 `_checked_now_locked()` 记录上次已接受的 Clock 读数，拒绝比它更小的新读数；这只用于检测坏 Clock，不是另一份 Worker 心跳状态。这样即使时间仍大于某个 Worker 的 last_seen，也能发现相对上一次扫描发生的逆行。

首次心跳：register 为 READY/BUSY，或 activate/publish READY 时，记录本地当前时间作为起点。它是**初始宽限**，不是伪造“收到了 heartbeat”事件；真正 heartbeat 另发接收事实。不能用 0 作初始上次心跳而让新注册立即超时。

有效心跳也不延长 Task retry budget，不改变 TaskStatus，不证明任务取得进展。收到当前 generation 但早于最近心跳的客户端消息时间不影响计算，因为客户端时间不参与 API。

**快速验证。** FakeClock 从 0 开始合法；advance 后 heartbeat 时间变化；READY/BUSY 均可心跳；旧 generation、异 runtime、STOPPED/FAILED/RESTARTING 拒绝且 revision 不变；非法时间参数拒绝；wall clock 跳动不影响超时判断。

**常见错误。** 默认参数写成 `clock=SystemClock()` 共享实例；用 time.time 算 deadline；factory 新对象发布后允许旧 lease 心跳；把模型输出文本当 heartbeat。

**完成标志与 DD 关系。** 时间可控、代数校验生效；Mailbox 堆积不影响直接 heartbeat。后续 benchmark 才衡量心跳更新成本，此处只证明语义。

### Step 5：只读扫描 timeout 候选，不边扫描边撤销

**目标与原因。** 扫描发现“可能过期”，提交时才决定是否真的撤销。两步之间 Worker 可以心跳、完成或重启，旧扫描不能直接当命令。

**位置与接口。** lifecycle.py 的 `detect_timeouts() -> tuple[WorkerTimeoutCandidate, ...]`，使用同一协调锁读取 Registry 和 Scheduler ownership 摘要。它返回稳定按 worker_id 排序的快照，不改状态、不改 queue，也不发“已死亡”成功事件。

**临界值明确选择。** 本节采用 `elapsed >= heartbeat_timeout_seconds` 即过期。原稿的 `>` 不继续作为第二种行为。示例 T=15：14.999 不过期、15 正好过期、15.001 过期；配置不是行业通用常数。

只扫描 READY/BUSY。CREATED 尚未激活；FAILED 已被撤销；STOPPED 是主动停止；RESTARTING 正在由 reservation 管理。后三者不能因这次 heartbeat sweep 被反复恢复。RESTARTING 的 factory 阻塞问题在 Step 7 单独说明，不套 heartbeat deadline。

纯判断局部参考：

```python
def is_expired(last_seen: float, now: float, timeout: float) -> bool:
    if not all(isfinite(value) for value in (last_seen, now, timeout)):
        raise ValueError("time values must be finite")
    if last_seen < 0 or now < last_seen or timeout <= 0:
        raise ValueError("invalid monotonic deadline")
    return now - last_seen >= timeout
```

这是内部已解析为 float 后的纯函数；公共配置入口仍要拒绝 bool 和错误类型。`all()` 表示每一项都满足；生成器表达式不用先构造一个列表；函数无对象状态，特别适合参数化测试。

候选至少保存 lease、Worker revision、观测状态、last_seen、observed_at，以及当时的 OwnedTaskToken 或 None。每次 heartbeat、claim、start、complete、fail、stop、restart 状态变化都更新对应 Worker revision；即使 FakeClock 两次读数相等，也能识别刷新。

**快速验证。** 临界值三组；READY/BUSY 扫描；重复 scan 结果稳定且所有状态不变；STOPPED/RESTARTING 不出现；生成候选后补一次 heartbeat，保留旧候选交给下一步测试拒绝。

**常见错误。** scan 返回 Worker 内部引用；只保存 worker_id；超时名单得到后不再检查；把检测结果命名成已证实的 ProcessDead。

**完成标志与 DD 关系。** 得到的是候选，不是撤销事实；为 detection latency 和 recovery processing latency 的分账建立两个明确时点。

### Step 6：原子 recover_worker_loss，覆盖 CLAIMED 和 RUNNING

**目标与原因。** 失联可能发生在 claim 后、start 前。不能强行 start 一个未执行的任务来迁就现有 fail()，也不能先标 Worker FAILED、解锁后才改 Task。

**位置。** scheduler.py 新增 `recover_worker_loss`，复用现有 `_TASK_TRANSITIONS` 中 CLAIMED -> FAILED 和 RUNNING -> FAILED，以及有限 retry 的逻辑；registry.py 提供锁内 Worker 状态准备 helper。

**接口与返回值。**

```python
def recover_worker_loss(
    self,
    candidate: WorkerTimeoutCandidate,
    *,
    heartbeat_timeout_seconds: float,
) -> WorkerRecoveryResult: ...
```

`WorkerRecoveryResult` 放 scheduler.py，字段建议为 lease、outcome、task_record、reason_code。outcome 用 Enum：STALE_CANDIDATE / WORKER_ONLY / TASK_REQUEUED / TASK_FAILED。task_record 可以为 None，表示失活 READY Worker 没有任务，不代表方法未执行。配置来自受信 LifecyclePolicy，不允许模型临时指定 timeout=0 来撤销别人的工作。

**提交前必须重新检查。** 在同一 coordinator.lock 下：

1. candidate.runtime_id 与当前一致，worker_id 存在，generation 一致。
2. 当前 Worker revision 与候选一致，仍是观测到的 READY/BUSY 状态。
3. 用**新的 monotonic now** 再算超时；不能只比较旧 observed_at。
4. 当前 ownership 摘要与 candidate.active_task 一致；有任务时 owner_id、attempt、owner_generation 必须全部匹配。
5. 当前 Task 仍为 CLAIMED 或 RUNNING。已完成、已重排或终态失败不能被这张候选重新拉回 READY。

任一过期条件成立，返回 STALE_CANDIDATE，不改变 Task、Worker、queue 或 restart budget。可以记录明确的 rejected metadata，但不能发 worker_failed/task_retried 成功事件。未知身份/结构损坏抛领域错误，不用宽泛 `except Exception: continue` 掩盖。

**原子提交内容。** 先准备再提交：

```text
Worker -> FAILED，revision + 1，旧 generation 暂不改变
Task（如果存在）：
  CLAIMED/RUNNING -> FAILED，清 owner_id/owner_generation/claimed_at
  retryable 且 attempt < max_attempts -> READY，入队一次
  否则保持终态 FAILED，下游按既有规则 BLOCKED
Ownership index -> 清除旧 claim
Audit -> worker failure + task failure + optional task retry
```

`attempt` 在恢复/重新入队时**不增加**，只在下一次成功 claim 时增加。`max_attempts=2` 表示最多认领两次，不是“初次执行加两次 retry”。失活是本日定义的可重试原因，但仍受同一预算限制；无任务的 READY 超时不消耗 Task attempt。

在局部失败处理里，retry 判断可以抽成：

```python
def may_retry(attempt: int, max_attempts: int, *, retryable: bool) -> bool:
    return retryable and attempt < max_attempts
```

参数合法性在配置/record 边界已校验。这个小函数只回答预算，不能自己更改 queue 或 Worker 状态。普通任务 fail 和 worker loss 都复用它，但两者释放 Worker 的语义不同：

- 普通有效 claim 的 complete/fail：当前 generation 的 BUSY Worker 可以回 READY。
- Worker loss：Worker 必须保持 FAILED，不能调用当前“一律设 READY”的 `_release_worker_locked`。
- STOPPED 或已重启 Worker：任何旧 release 都无权修改它。

**Python 知识。** `Enum` 返回值比 bool 更能解释“没任务”“候选已过期”“预算耗尽”；`dict.pop(key, None)` 可以幂等删除索引，但删除前仍须验证 token，不能因为 pop 不抛错就跳过 ownership 检查。

**两条竞态时序。**

```text
scan 拿到 BUSY / attempt1 / revision7
complete 先提交 -> Task COMPLETED，Worker READY，revision8
旧 recovery 获取锁 -> revision 不同 -> STALE_CANDIDATE
结果：不撤销、不复活已完成任务

scan 拿到 BUSY / attempt1 / revision7
recovery 先提交 -> Worker FAILED，Task READY 或 FAILED
旧 complete 获取锁 -> claim 不再有效 -> 拒绝
结果：不把新状态改成 COMPLETED
```

第一种情况下，Worker 仍可能很久没心跳，下一次新扫描可把空闲 Worker 判为失活，但绝不能把已经完成的 Task 重排。这是两个不同事实。

**快速验证。** CLAIMED 与 RUNNING 参数化；max_attempts=1/2；READY 空闲超时；同候选重复调用只提交一次；candidate 后 heartbeat/complete/retry/new claim/restart/stop 均导致旧候选无效；失败 Worker 不被 release 成 READY；重新入队后 role gate 仍生效。

**常见错误。** 直接调用 fail() 导致 CLAIMED 恢复失败；requeue 时同时递增 attempt；每次 sweep 重新 append；把 Task FAILED 都当作还能重试而复活已终止失败；先改 Worker 再校验 Task。

**完成标志与 DD 关系。** 恢复是一个有 token、有 CAS、有 budget、幂等的事务。Lifecycle 只调用这个事务，不写 Task 字段，不选替代 Worker。

### Step 7：实现有界逻辑 restart，factory 回来后仍要检查

**目标与原因。** 恢复 Task ownership 与重建 Worker 对象是不同操作。前者已经在 Step 6 提交成功，后者即使失败，也不能把旧 claim 再交还给失活对象。

**位置与接口。** lifecycle.py 的 `restart_worker(lease: WorkerLease) -> RestartResult`；registry.py 的 reserve/publish/fail 内部方法；`WorkerFactory = Callable[[AgentInfo], WorkerAgent]`。RestartResult 用 Enum 区分 RESTARTED、NOT_ELIGIBLE、COOLDOWN、EXHAUSTED、FACTORY_FAILED、STALE_TICKET，成功时携带新 WorkerLease。

**重启策略。** 本节选择每个 worker_id、每个 runtime 生命周期最多 `max_restarts` 次 factory 调用，默认为教学示例 2；`restart_cooldown_seconds` 示例 2.0，可配置。0 次表示禁用重启。预算在成功 reserve 时消耗，factory 失败也消耗；成功不会自动清零累计次数。reserve 时设置 `next_restart_monotonic = now + cooldown`，冷却从预留开始计算；`now >= next_restart_monotonic` 才可再次预留，RESTARTING 期间仍禁止重复预留。这样持续失活不产生无界重启风暴，具体参数不宣称为工业最佳值。

**三段式协议。**

| 阶段 | 锁 | 必须做什么 |
| --- | --- | --- |
| Reserve | core lock 内 | 校验 lease、FAILED、无有效 owned Task、预算/冷却；生成唯一 restart_id；FAILED -> RESTARTING；计数和 revision 增加；得到 RestartTicket |
| Build | core lock 外 | 把身份快照交给 factory，仅逻辑构造 WorkerAgent，不执行模型/工具/进程；读取返回对象信息也在锁外 |
| Publish | core lock 内 | 重查 runtime/generation、RESTARTING、restart_id、expected_revision、未 STOPPED；验证身份能力后发布新对象、generation+1、READY、新心跳宽限、清 ticket |

身份保持至少包括 agent_id、display_name、role、capabilities。factory 返回别的 Worker、改变角色或能力、返回原对象，都应视为构建失败；不要为了让 claim 成功临时把 BACKEND 改成 TEST。AgentInfo.status 是初始化描述，不授权 factory 自己决定 live status，READY 由 publish 产生。

Registry 不提供能绕开 Scheduler 的公开 `mark_failed()` / `mark_busy()` / `release()`：涉及任务占用的变化只从 Step 2/6 的跨对象事务进入。因此合法 FAILED 状态必定已无有效 Task ownership，reserve 可以依赖此不变量；组合快照若发现 FAILED 仍带有效 claim，应抛一致性错误并停止，不靠 restart 顺手清理来掩盖半写。

`generation` **只在成功 publish 时增加**。factory 失败时保持 FAILED 和原 generation，但旧 lease 仍不能 heartbeat，因为状态不是 READY/BUSY。新一次 restart reservation 必须有新 restart_id，所以同一 generation 内的旧失败回调也不能覆盖新 reservation。

**局部参考，展示锁外 factory 与过期回调。** 下列 helper 属于拟实现 Registry；每个 helper 自己管理共享锁，Lifecycle 不在外层再包一次锁：

```python
ticket = registry.reserve_restart(lease, policy=policy)
try:
    replacement = worker_factory(ticket.info.model_copy(deep=True))
    replacement_info = replacement.info
except Exception as exc:
    return registry.finish_restart_failure(
        ticket, reason_code="factory_failed", error_type=type(exc).__name__
    )
return registry.publish_restart(ticket, replacement, replacement_info)
```

这是编排核心片段，不是完整异常处理模块。reserve 未成功时不调用 factory；普通 factory 异常转成明确 RestartResult，并记录安全 error_type，不静默吞掉。KeyboardInterrupt/SystemExit 不转换成“成功”；先尝试以同一 ticket 标记中断，再继续传播，中断清理也不能覆盖新状态。

**Python 知识。** `Callable[[AgentInfo], WorkerAgent]` 表示“输入 AgentInfo、输出 WorkerAgent 的函数”；`try/except` 只包不可信 factory 阶段，避免把 Scheduler 事务 bug 也归成 factory failure；异常日志不直接 dump 任意消息或对象。

factory 或 observer 可能重入 `stop_worker()`。返回之后，即使对象构造成功，只要 ticket 已过期，就返回 STALE_TICKET 丢弃新对象，不发布 READY，不增加 generation，不发 restarted 成功事件。

**RESTARTING 的明确处理。** 普通 heartbeat scan 跳过 RESTARTING；同 worker 再次 restart 返回 NOT_ELIGIBLE，不重复调用 factory。V1 factory 合约为短时、同步、无 I/O 的对象构造，不实现抢占式取消或工厂执行超时。若恶意/错误 factory 永不返回，该调用仍可能阻塞，但不会持 core lock；别的线程可以 stop 使其未来回调失效。**次数有界不等于耗时有界**，此限制需写 Failure Case，不虚构“进程已被杀掉”。真实 spawn/超时终止留未来执行管理器。

**快速验证。** 成功新对象、同身份同 role/capabilities、generation+1；factory 抛错保留 FAILED；预算耗尽 factory 0 次；冷却临界值；RESTARTING 重复调用 factory 总计一次；factory 内可读 Registry/Scheduler；factory 阻塞时另线程 stop，再释放 factory，其回调必须 stale。

**常见错误。** 在锁内 factory；先把 generation+1 发布再构建对象；失败重启不计预算；factory 异常后把 FAILED 改 READY；回调回来不查 ticket；用同一个 Worker 对象冒充重建。

**完成标志与 DD 关系。** 重启次数有界、旧回调隔离、身份能力不漂移。它只证明逻辑对象重建，不证明真实进程 crash recovery 或持久上下文恢复。

### Step 8：组装 Lifecycle sweep 与 stop，不创建第二个 Scheduler

**目标与原因。** 把前面的纯判断与事务串起来，仍保持每个状态写入只有一个责任组件。

**位置与 API。** lifecycle.py：

```python
class AgentLifecycleManager:
    def heartbeat(self, lease: WorkerLease) -> WorkerRuntimeRecord: ...
    def detect_timeouts(self) -> tuple[WorkerTimeoutCandidate, ...]: ...
    def sweep(self) -> LifecycleSweepResult: ...
    def restart_worker(self, lease: WorkerLease) -> RestartResult: ...
    def stop_worker(self, lease: WorkerLease) -> WorkerStopResult: ...
```

构造时显式注入 Registry、Scheduler、LifecyclePolicy、WorkerFactory。验证二者处于同一协调域；heartbeat 只是委托 Registry，没有新 dict 保存 alive/status。SweepResult 包含恢复与重启结果 tuple，方便调用方观察部分失败，不能只返回“sweep succeeded”。

**sweep 顺序。**

1. 检查 Clock/配置有效。
2. 获取 timeout 候选快照。
3. 对每个候选调用 Scheduler.recover_worker_loss，由它重新验证并原子提交。
4. 对本次真实失活及之前 factory 失败、仍 FAILED 的 Worker，尝试有界 restart。先取得最新 lease，再 reserve；reserve 再校验资格，不信任早先快照。
5. 每个 Worker 在一个 sweep 最多尝试一次 factory；重复输入先按 worker_id 去重。
6. 返回结构化汇总。重排成功但重启失败，两个结果分别记录；其他兼容 Worker 仍可正常 claim，Lifecycle 不主动给它派单。

这是显式调用的同步 sweep，不启动守护线程、不写无限 `while True`。未来驱动器以 `Event.wait(interval)` 等方式调度扫描，但本日不创建执行器。

**STOPPED 必须定义为控制面操作。** `stop_worker(lease)` 只表示撤销调度资格，不证明 OS 线程已经停止。它通过 Scheduler 的包内事务准备逻辑原子完成：

- Worker 转 STOPPED、revision+1、作废 pending restart ticket。
- 有 CLAIMED/RUNNING 时撤销 ownership，按受控的 stop 原因策略重排或终态失败。本节 MVP 选择“可重试但仍受 max_attempts 限制”，方便其他 Worker 接手；安全/取消任务的业务失败不能被改成可重试。
- 无任务则只停 Worker。重复 stop 同 generation 返回幂等结果，不重复 event。
- STOPPED 不参与 heartbeat、自动 sweep restart 或 claim；需要新一轮人工授权/团队重建，不设置默认自动复活入口。

该事务可在 scheduler.py 设 `_prepare_worker_unavailability_locked(...)`，由 loss/stop 复用。Registry 仍决定 Agent 状态迁移是否合法，Scheduler 仍决定 Task/queue 如何变化；Lifecycle 不直接碰 `_records`。

**Python 知识。** `tuple[Result, ...]` 表示任意长度的不可变结果序列；`None` factory 配置可表示禁用自动重启，但不能表示绕过失活恢复；委托是调用另一个对象负责的方法，不再复制实现。

局部参考，展示“不选接任者”：

```python
outcomes = []
for candidate in self.detect_timeouts():
    outcome = self._scheduler.recover_worker_loss(
        candidate,
        heartbeat_timeout_seconds=self._policy.heartbeat_timeout_seconds,
    )
    outcomes.append(outcome)
# 此处汇总/尝试 restart，不调用 scheduler.claim()。
```

**快速验证。** 同步 sweep 可手动执行；两次 sweep 不重复重排/消耗 restart budget；无兼容角色时 Task 等待而非被 Lifecycle 强行交给错误角色；STOPPED 即使时钟前进很久也不复活；重启旧 lease stop 新 generation 被拒绝。

**常见错误。** Lifecycle 保存 `_agents`；从兼容列表选第一个 Worker 直接 execute；把 Mailbox TASK_COMPLETED 当 complete 授权；把 restart 成功当整个 Task 已恢复完成。

**完成标志与 DD 关系。** Lifecycle 只有协调职责，所有副作用仍为内存控制面状态改变。自动恢复链现在才开放，且 Step 3 fencing 测试必须已通过。

### Step 9：补齐审计语义、公共导出与旧调用迁移

**目标与原因。** 状态正确却不知道为什么被撤销，无法排查误超时；观察者抛异常也不能让调用方误以为已提交 claim 没成功。

**位置。** events.py、registry.py、scheduler.py、lifecycle.py、agent_team/__init__.py，以及后续授权的测试调用点。复用现有 AgentEvent，不新建一个相似的日志系统。

**事件计划。** 后续新增枚举建议如下，名称是拟实现而不是已有 API：

| 事件 | 触发时点 |
| --- | --- |
| WORKER_HEARTBEAT_RECEIVED | 当前 generation 心跳提交成功；高频保留策略见下文 |
| WORKER_FAILED | 超时经重新验证并真正提交 FAILED，不在 scan 时发 |
| WORKER_RESTARTING | 成功 reserve 且已扣重启次数 |
| WORKER_RESTARTED | 新对象/generation 成功 publish |
| WORKER_RESTART_FAILED | 当前 ticket factory 失败；旧 ticket 只能发 rejected |
| WORKER_RESTART_REJECTED | cooldown/exhausted/stale ticket，reason_code 明确 |
| WORKER_STOPPED | 主动停止事务真正提交 |
| SCHEDULER_STALE_CLAIM_REJECTED | 旧 claim 被拒，不发 task_completed/task_failed 成功迁移事件 |
| WORKER_EVENT_DELIVERY_FAILED | Registry/Lifecycle observer 失败，不回滚领域提交 |

事件值建议统一 `worker.*` / `scheduler.*`，保留已有 Scheduler failure/retried 事件。不要复用 Week4 的 TASK_FAILED 来表示 Worker 死亡，也不要把“Task 已重新入队”叫作“Task 已完成”。

**payload。** 只保留 runtime_id、worker_id、generation、node_id、attempt、from/to status、reason_code、restart_id、restart_attempt、elapsed_seconds、timeout_seconds、transaction_id、transaction_event_index 等安全标量。reason_code 使用固定词表，禁止完整 prompt、工具输出、env、factory repr 或异常堆栈进入公共事件。

在 core lock 内分配递增 transaction_seq；同一跨对象事务用同一个 transaction_id，按操作顺序编号 transaction_event_index。Registry/Scheduler 可各持自己负责的 events，但合并审计按事务号与事件索引排序，不按 wall clock 排序。序号、事件列表也属于 Step 2 draft 提交内容。

**Python 知识。** `dataclass(frozen=True)` 的 AgentEvent 仍含可变 data dict；现有 `_copy_event` 是浅拷贝，因此本日 payload 保持标量。如果将来加入嵌套 dict/list，必须升级防御性复制策略，不假设 frozen 能保护嵌套对象。

局部参考，沿用当前已验证的边界：

```python
pending_delivery: list[AgentEvent] = []
with self._coordinator.lock:
    result, pending_delivery = self._prepare_and_commit_locked(...)
self._deliver_events(pending_delivery)
return result
```

`...` 表示具体领域参数，不能当完整可运行实现。最外层调用才投递；sink 抛普通 Exception 时只记录 delivery_failed，不向调用方隐藏已提交结果，不递归再投递同一个失败 sink。

observer 可重入读取，甚至调用受控 stop；这可能使返回给原调用者的 claim/ticket 在投递期间过期，所以每个后续使用点都必须再 fenced 校验。不要为了“保证返回后永远有效”而把 callback 塞回锁内。

**保留成本。** 本节学习版可记录每次心跳事件，但应按 team/runtime 生命周期释放；事件总量不是有界的，Mailbox capacity 也不会限制它。Heartbeat hot path 的审计开销与累计内存列入周末指标；采样/归档是以后决策，不能通过悄悄丢失恢复事件控制内存。

**快速验证。** 成功/失败/拒绝事件不混淆；一次 recovery 的 transaction_id 一致；旧回调无 restarted 事件；sink 重入读取/stop 不死锁；sink 异常不回滚；公共新旧 Registry/errors import identity；测试中的旧 claim 调用全部迁移且保留断言。

**常见错误。** 一个最终失败 recovery 先发 RECOVERY_COMPLETED；用扫描时间排序并发提交；旧 factory failure 回调把新 Worker 写 FAILED；为避免 lint 给一切标 Any。

**完成标志与 DD 关系。** 能从安全 metadata 解释一次 attempt 撤销和 generation 替换；observability 测试与状态不变量一起验收。

### Step 10：跑通可控恢复演练，再整理工程证据

**目标与原因。** 最后才把十几条局部契约放进同一个场景。不是等到这里才写所有测试：Step 1–9 每一步均先局部验证，再往前推进。

**位置。** 后续 `tests/agent_team/test_registry.py`、`test_lifecycle.py`、`test_scheduler.py`、`test_mailbox.py`；DD/Failure 文档另按授权创建。本轮仅在这里给测试设计。

**演练接口。** FakeClock + AgentRegistry + TaskScheduler + LifecycleManager + FakeFactory，不调用 CodingAgentRuntime，不访问 provider，不写真实 workspace。返回值检查 TaskClaim、WorkerRecoveryResult、RestartResult 和组合快照。

推荐按三个独立测试组织，不用一条巨长测试掩盖失败定位：

1. CLAIMED 失活：只 claim 不 start，advance 到边界，sweep 后 Task READY/FAILED，原 Worker 不再拥有它。
2. 同 Worker 两次执行：attempt1 RUNNING，超时恢复，逻辑重启返回新 lease，同 worker_id claim attempt2；attempt1 迟到 complete/start/fail 全拒绝。
3. 重启回调迟到：factory 在 Event 上等待；另一线程 stop；释放 factory；返回 STALE_TICKET、Worker 保持 STOPPED，generation 不错误增加。

第二个测试还不能替代 Step 3 的“同 generation、仅 attempt 变化”测试。否则实现只检查 generation，也可能误通过所有新测试。

**Python 并发知识与局部参考。** Event 用于明确发生顺序，Barrier 用于同时竞争；join(timeout) 是测试防挂，不是靠 sleep 猜先后：

```python
from threading import Event as ThreadEvent
from threading import Thread


entered = ThreadEvent()
release = ThreadEvent()
results: list[RestartResult] = []
errors: list[BaseException] = []

def factory(info: AgentInfo) -> WorkerAgent:
    entered.set()
    if not release.wait(timeout=2.0):
        raise AssertionError("test did not release factory")
    return WorkerAgent(info)

def run_restart() -> None:
    try:
        results.append(lifecycle.restart_worker(old_lease))
    except BaseException as exc:
        errors.append(exc)

thread = Thread(target=run_restart)
thread.start()
try:
    assert entered.wait(timeout=2.0)
    lifecycle.stop_worker(old_lease)
finally:
    release.set()
    thread.join(timeout=2.0)
assert not thread.is_alive()
assert errors == []
assert len(results) == 1
```

此片段假定 helper 已把上面的 factory 注入 lifecycle，并准备好了 FAILED 的 old_lease；随后必须继续断言 results[0] 为 STALE_TICKET、Worker 为 STOPPED。测试中的 BaseException 只用于把线程失败带回主线程，不是生产代码吞异常。不能把线程里的 AssertionError 当作测试天然会失败。Barrier 也设置 timeout；清理放 finally，避免主断言失败后留等待线程。时间推进先于竞态起跑，或给 FakeClock 自身加受控同步，避免测试时钟产生非目标竞态。

**快速验证。** 先单测每条场景，再执行整个 agent_team，再检查 Runtime/Session 回归和全量。状态一致性用 `scheduler.snapshot()` 同时读取 Worker/Task/queue，不能分别读取之后要求它们跨时间相等。

**常见错误。** 用真实 sleep(15) 测超时；只断言最终 READY 不验证 owner/attempt/queue；只断言 factory 被调用不检查新旧 generation；用 skip/xfail 隐藏竞态；把 FakeClock 演练命名为真实 process crash recovery。

**完成标志与 DD 关系。** 功能、失败和竞态测试均通过后，才能交正式 tester。Benchmark/Ablation 仍按周末统一执行，此时只写计划与未验证范围。

## 6. Tests：验收地图与后续命令

### 6.1 必须覆盖的行为矩阵

下面的测试名是建议名称，尚未创建。每项不仅看异常，还要比较操作前后 Task/Worker/queue/事件和 factory 调用次数。

| 组别 | 建议测试与核心断言 | 对应步骤 |
| --- | --- | --- |
| 数据契约 | `test_lease_and_claim_require_explicit_versions`：缺版本/非法 ID/错误代数拒绝；round-trip 与防御性复制 | 1 |
| 单一权威 | `test_scheduler_reads_registry_runtime_not_bootstrap_status`：不再读取 Worker.info 的旧 status；无第二动态 map | 2 |
| 兼容 | `test_worker_registry_legacy_import_is_alias`：包与旧 worker 路径引用同一个实现/异常类型 | 2 |
| 原子性 | `test_prepare_failure_leaves_both_states_unchanged`：准备第 2 个状态失败后两边、queue、events 不变 | 2 |
| 协调域 | `test_second_scheduler_binding_is_rejected`；`test_cross_runtime_claim_is_rejected` | 2–3 |
| 核心 fencing | `test_same_worker_same_generation_old_attempt_cannot_complete_new_attempt`，并参数化 start/fail | 3 |
| 无兼容绕过 | `test_start_complete_fail_require_claim`：裸 node/worker 或缺 attempt 无法执行 | 3 |
| owner/role | 原 owner mismatch、BACKEND 不能认领 TEST、BUSY 不可二次 claim；未注册/无匹配角色保持既有语义 | 3 |
| Clock | `test_invalid_time_configuration_is_rejected`：0/负 timeout、NaN/inf、bool、Clock 逆行；wall clock 跳变不影响 deadline | 4 |
| 心跳起点 | `test_registered_ready_worker_gets_initial_grace`；activate 和 restart publish 也有宽限，不伪造 heartbeat received | 4 |
| 心跳与代数 | `test_old_generation_heartbeat_is_rejected`：旧 heartbeat 不改变新状态/时间/revision | 4 |
| 时间边界 | `test_timeout_boundary`：T-epsilon / T / T+epsilon；READY/BUSY 均覆盖 | 5 |
| 扫描纯度 | `test_detect_timeouts_has_no_state_side_effects`；STOPPED/RESTARTING/CREATED/FAILED 不被普通扫描判失活 | 5 |
| CLAIMED/RUNNING | `test_worker_loss_recovers_owned_task` 参数化两个状态，不通过伪造 start 绕过 | 6 |
| READY 超时 | `test_idle_ready_timeout_changes_only_worker`：Task attempt 不增加 | 6 |
| retry 耗尽 | `test_worker_loss_respects_max_attempts`：终态 FAILED 不再入队，依赖保持/转 BLOCKED | 6 |
| 重复 sweep | `test_repeated_sweep_does_not_duplicate_requeue`：队列一次、失败事件一次、预算不重复扣 | 6、8 |
| 旧候选 | `test_heartbeat_after_scan_invalidates_recovery`：即使同一 clock 数值，revision 也识别心跳 | 6 |
| 完成竞争 | `test_completion_before_recovery_is_not_revoked`；反序 recovery 赢则 complete 拒绝 | 6 |
| 新任务竞争 | `test_old_candidate_cannot_revoke_later_claim_on_same_worker`：同代 Worker 已完成 A 又认领 B，旧候选不能撤销 B | 6 |
| 不释放失败者 | `test_loss_does_not_release_failed_worker_to_ready`；STOPPED 同样不能被旧 release 复活 | 6、8 |
| 重启 | `test_restart_preserves_identity_and_capabilities`：新对象、generation+1、Task attempt 不因 restart 增加 | 7 |
| factory 失败 | `test_factory_failure_keeps_failed_and_consumes_budget`；错误身份/角色/能力/同对象返回都拒绝 | 7 |
| 重启上限 | `test_restart_budget_and_cooldown`：0 次禁用、次数耗尽、冷却临界值、无无限循环 | 7 |
| 重复恢复 | `test_only_one_restart_factory_for_same_reservation`：并发 restart 一次 reserve、factory 一次 | 7 |
| 旧回调 | `test_restart_callback_after_stop_is_stale`；旧 generation 成功/失败回调不能覆盖新 generation | 7–8 |
| 主动停止 | `test_stopped_worker_never_auto_revives`：长时间 advance、多次 sweep、旧 heartbeat 后仍 STOPPED | 8 |
| 通信边界 | 保留 `test_task_completed_message_does_not_change_scheduler_state` 与 failed 版本；inbox 满仍能 heartbeat | 4、9 |
| 回调重入 | factory/sink 可读组合快照；sink 抛错不隐藏已提交结果；慢 factory 不阻塞其他 Worker 的状态操作 | 7、9 |
| 审计 | 无假 task_completed/restarted；transaction_id 可关联；payload 无 secret/大对象 | 9 |
| 并发一致性 | `test_claim_vs_recovery_keeps_combined_snapshot_consistent`：Barrier/Event、有界 join、收集线程异常 | 10 |

还要保留原有 topology snapshot、immutable transition table、missing-role waiting、有限 retry、sink 隔离等断言。迁移测试 API 是为了强制显式 token，不能借迁移删除有效失败覆盖。

### 6.2 所谓“一致”具体断言什么

- CLAIMED/RUNNING Task 恰有一个 owner_id/owner_generation，与 Scheduler ownership 索引和 Registry 当前 generation 相同，Worker 为 BUSY。
- READY/COMPLETED/终态 FAILED/BLOCKED Task 无 active owner；READY 在 queue 中最多一次，其他终态不在 queue。
- READY Worker 不占有有效 claim；bootstrap BUSY 未绑定 Task 的特殊初始化状态只代表不可调度，不伪造 owner。
- FAILED/STOPPED/RESTARTING Worker 不占有可接受 start/complete/fail 的 claim。
- generation、attempt、restart_attempts 均不倒退，各自在定义好的提交点增长。
- 旧 token 拒绝后，新 Task/Worker 状态和 queue 不变；审计只能增加拒绝事实。

只有这种跨对象断言才能暴露“两个方法分别通过单测，组合起来却写半截”的缺陷。

### 6.3 后续实际验收命令（本轮未执行）

从 `/Users/root/workspace/Agent-Learning` 执行；新增测试文件落地后再运行对应命令。所有 Python 命令均使用项目解释器：

```bash
.venv/bin/python -m pytest tests/agent_team/test_worker.py tests/agent_team/test_registry.py -q
.venv/bin/python -m pytest tests/agent_team/test_scheduler.py -q
.venv/bin/python -m pytest tests/agent_team/test_lifecycle.py -q
.venv/bin/python -m pytest tests/agent_team/test_mailbox.py -q
.venv/bin/python -m pytest tests/agent_team -q
.venv/bin/python -m pytest tests/agent tests/session tests/execution -q
.venv/bin/python -m ruff check codeteam/agent_team codeteam/events.py tests/agent_team
.venv/bin/python -m mypy codeteam/agent_team tests/agent_team
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/sandbox -q -rs
```

每小步可先用 `-k` 选择刚写的测试，再跑该文件。正式验收记录命令、退出码、passed/failed/skipped、具体失败位置和原因，不仅记录“看起来成功”。

Ruff/mypy 要区分当前基线债、本轮新增诊断、本轮触达但已存在的问题。合并日志提到的 5 个 agent_team 类型问题属于该范围既有债，并非全是无关依赖；实现时重新确认位置，不在教程里假定永远相同。不得新增 Any/ignore、skip/xfail 或降低断言来掩盖缺陷。

Day5 控制面测试无需 Docker；全量若因 Docker socket 权限或镜像缺失条件 skip，必须记录未验证真实容器边界，不写成 Docker 已通过。

本日无需 Git mutation 测试；未来 adapter 如需 Git，所有仓库都在 function-scoped tmp_path 内 git init，仅 local user 配置。subprocess 用 argv list、shell=False、timeout、capture_output，不操作主仓库或原始 fixtures。

## 7. DD-W5-05 草案（PLANNED，未单独落盘）

格式对齐现有 DD-W5-03/04；后续创建 `docs/design_decisions/DD-W5-05.md`，本轮不创建。

### Title / Status / Evidence Status

**DD-W5-05: Fenced Agent Lifecycle and Atomic Worker Loss Recovery**

Status: PROPOSED / IMPLEMENTATION_PLANNED。

Evidence Status: PROPOSED；本节是设计，Day5 tests 未执行；Benchmark/Ablation 为 WEEKEND_PLANNED / NOT_RUN。

### Context / Problem

已有 TaskScheduler 线程级 claim、bounded retry 与 Mailbox 通信，但状态推进只校验 owner；同 worker 的旧 attempt 可以污染新执行。引入 heartbeat/restart 后，单独依赖 worker_id 会进一步产生旧 generation 心跳、扫描候选和 factory 回调污染。

### Requirements

强制 claim fencing；Agent 动态状态与 Task ownership 各有唯一权威；跨对象更新原子；失活 Task 从 CLAIMED/RUNNING 受 budget 约束恢复；STOPPED 不复活；factory/sink 锁外且回调再校验；测试不依赖真实 sleep/API。

### Decision

采用 AgentRegistry + TaskScheduler 的职责拆分，共享 TeamStateCoordinator 锁域；同域同步 prepare/commit，锁外外部回调；Task 操作必传完整 TaskClaim，Worker 操作必传 WorkerLease，异步阶段必带 revision/reservation；monotonic timeout 与 wall-clock audit 分离；restart 只做有上限的进程内对象重建。

保留 WorkerRegistry public import 为同实现 alias；不保留无 attempt 的状态修改入口。AgentInfo.status 仅 bootstrap 输入，实时状态查 Registry。Lifecycle 只协调恢复，不选择接任 Worker。

### Alternatives

| 方案 | 优点 | 不选或延期的原因 |
| --- | --- | --- |
| alive bool + owner_id | 简单 | 无法表达重启/主动停止，无法区分旧 attempt/generation |
| Registry/Scheduler 独立锁 | 模块看起来独立 | 需要一致锁序与跨对象事务，单独加锁不解决半写；V1 不增加此复杂度 |
| 共享协调锁 | 状态事务容易审查、同步测试可控 | 复制和锁竞争成本需量化，不能承诺高吞吐 |
| 单一巨型 LifecycleManager | 所有数据近在一处 | 调度与恢复耦合，成为第二个 Scheduler，责任不清 |
| 每次重启新 worker_id | 可避开部分身份复用问题 | 不能解决同代 Task retry 的迟到结果；仍需要 attempt fencing |
| SQLite / Actor / Workflow backend | 可扩展持久化和部署 | 需要事务、租约、进程身份和恢复协议，留 Day6/未来 |

### Consequences / Limitations

得到可测试的提交资格边界，不得到外部 exactly-once。同步 factory 不可抢占；失活可能误判；内存审计持续增长；runtime_id 与 monotonic 时间只属于当前进程。完整 WorkerExecutor、Team Session resume、worktree integration 尚未实现。

### Current Evidence / Evidence Still Missing

当前只有代码审计与本节设计；后续单测通过后可标 IMPLEMENTED_WITH_TESTS，但不得因此标实测性能优势。周末需保留 workload、raw samples、manifest、失败轨迹以及无 fencing 的同场景对照，才评价相关假设。正式 supported 状态由独立验收决定。

## 8. Benchmark Plan（周末统一执行）

**本轮状态：PLANNED / NOT_RUN。不创建脚本、不运行真实 API，也不填写预测数字。**

### 8.1 工作负载与基线

使用同一代码版本的 Fake Worker / FakeFactory，不模拟成真实模型执行：

- Worker 数 100/500/1000；READY/BUSY 比例和活跃 Task 数固定记录。
- 超时比例 0%/10%/100%，包含 CLAIMED/RUNNING；角色匹配与缺少兼容角色各一组。
- 单线程及 4/8 线程 contention；重复 sweep 与一次性新候选分开。
- 每轮从相同初态构造，setup 与测量操作分离。
- 微基线为“只读 snapshot/纯 deadline scan”；完整系统增加 fenced transaction、requeue、audit。它仅用于解释各阶段开销，不把无恢复基线说成同等功能更快。

### 8.2 指标与计时定义

| 指标 | 定义 |
| --- | --- |
| heartbeat latency P50/P95 / ops per second | 当前 generation 接收并提交一次心跳的热路径成本 |
| scan latency P50/P95 | N 个 Worker 生成候选快照，不包含 factory |
| detection latency | 从最后心跳 t_last 到首次扫描发现过期 t_detect：t_detect - t_last |
| detection overshoot | t_detect - (t_last + timeout)，反映扫描周期/竞争，不能只报接近零的提交成本 |
| recovery processing latency | t_recovery_commit - t_recovery_start，单独测 revalidation + 原子撤销/重排 |
| logical restart latency | reserve 到成功 publish，分别列 factory 和核心状态操作时间 |
| scheduling wait | requeue 到下一个合法 claim；由 Scheduler/可用 Worker 决定，不归 Lifecycle 处理耗时 |
| correctness metrics | stale acceptance、duplicate requeue、ownership divergence、terminal resurrection、restart budget violation |
| retention metrics | 累计 events 数、serialized bytes / tracemalloc bytes，注明不是 RSS；heartbeat 审计成本独立列出 |

测试语义用 FakeClock，测 CPU/墙钟性能用 `time.perf_counter()`；不可把 FakeClock 人工 advance 的 15 秒当真实处理耗时，也不可把 t_recovery_commit - t_detect 称为“从失活到恢复的全部延迟”。

### 8.3 公平性与可复现性

计划 warmup 5 轮、measured 30 轮，这是实验参数而非结果。保存代码 HEAD/dirty、涉及文件 hash、Python/依赖/OS、seed、Worker/Task 数、角色、timeout、retry/restart budget、线程数、事件策略、工厂行为、计时区间和 raw per-run samples。

Full 与基线使用相同事件记录策略、初始队列、失败注入顺序与计算资源；若某组移除事件，只在专门 ablation 中声明。吞吐的低分位与延迟高分位意义相反，不能用乐观 throughput P95 代表最差体验。

拟报告 `docs/benchmark/W5_LIFECYCLE.md`；脚本和 manifest 名称后续实现任务再确定。本日不宣称端到端 Team 加速或真实 process crash 恢复。

## 9. Ablation Plan（周末统一执行）

状态全部为 PLANNED / NOT_RUN；弱化实现仅存在实验 adapter，不降低生产 fencing。

| 对照 | 完全相同的输入场景 | 观察指标 |
| --- | --- | --- |
| Full vs no attempt fencing | 同 worker_id、同 generation，A attempt1 fail/retry 后 attempt2 RUNNING，再交 attempt1 的迟到 complete/start/fail | stale_result_accept_count、attempt2_state_corruption_count |
| Full vs no generation fencing | w1 generation1 重启到 generation2 后，送旧 heartbeat 和旧成功/失败回调 | new_generation_corruption_count、false_heartbeat_refresh_count |
| Full vs no candidate revalidation | scan 后 heartbeat/complete/new claim，再提交相同旧 candidate | false_revocation_count、terminal_resurrection_count |
| Full vs split non-atomic updates | Barrier 在 Worker/Task 两次写入之间放行观察者或注入失败 | ownership_divergence_count、partial_write_count |
| Full vs no timeout recovery | 相同 FakeClock 失活轨迹 | stranded_claimed/running_count，而非把无操作零延迟算性能优势 |
| Full vs no restart budget | 相同 factory 连续失败轨迹，实验驱动最多发起固定次数调用 | factory_call_count、budget_violation_count；不运行无界循环 |

**关键公平性要求：** 无 fencing 组不能改成“另一个 Worker 来完成”，否则 owner mismatch 就会拒绝，错误地证明 fencing 没价值。attempt 与 generation 两组分别隔离变量，不把两种防护一次全删再宣称因果明确。

实验输出保留输入序列、每次操作返回值和前后状态，不仅保留最后一个 bool。没有实验数据之前，不写“Full 降低了 100% 故障”之类结论。

## 10. Failure Cases to Watch（模板与计划）

后续拟记录在 `docs/failure_cases/W5_LIFECYCLE_FAILURE.md`，本轮只提供模板：

```text
ID: F-W5-D5-XX
Status: PLANNED / NOT_REPRODUCED
Capability / Invariant:
Code SHA / Dirty / Environment:
Initial Worker / Task / Queue / Token:
Injected operation order (FakeClock / Barrier / Event):
Expected result and zero-side-effect assertions:
Actual result: NOT_RUN
Events and state snapshots:
Root cause hypothesis:
Minimal reproduction command:
Fix and regression test:
Limitations / What this does not prove:
```

优先准备这些案例，尚未声称已复现：

| ID | 失败模式 | 必须观察的证据 |
| --- | --- | --- |
| F-W5-D5-01 | 只支持 RUNNING 恢复，CLAIMED 永久占用 | claimed token、恢复后 owner/queue |
| F-W5-D5-02 | 同 Worker 旧 attempt 完成新 attempt | 两个完整 claim、旧调用被拒、新 record 不变 |
| F-W5-D5-03 | 老 heartbeat 延长新 generation 存活 | generation 与 last_seen/revision 前后值 |
| F-W5-D5-04 | 扫描后已心跳/完成，仍被旧候选撤销 | candidate revision 与提交时 revision |
| F-W5-D5-05 | Task 已重排而 Worker 被 release 回 READY | Worker FAILED/STOPPED 不变量及 claim gate |
| F-W5-D5-06 | factory 失败或长期阻塞 | reservation、预算、调用线程和其他状态操作可继续；不伪称已抢占 |
| F-W5-D5-07 | stop 与 factory 返回竞争，STOPPED 被复活 | stop event 在前、旧 ticket 被拒、无 restarted |
| F-W5-D5-08 | 两边更新分离，读到半写状态 | 一致快照、失败注入点、无成功事件 |
| F-W5-D5-09 | 重复 sweep 产生重复 queue/restart 风暴 | queue multiplicity、attempt/restart_attempts、factory 计数 |
| F-W5-D5-10 | 心跳“正常”但任务不进展 | 明确区分 liveness 与 progress；本日不宣称解决 |
| F-W5-D5-11 | wall clock 回拨引发误判 | monotonic 与审计时间独立记录 |
| F-W5-D5-12 | fencing 有效但旧工具仍写了外部文件 | 记录为未来执行层边界缺口，不以状态拒绝冒充副作用 exactly-once |

Failure Case 可以记录未支持的边界，但不能把 known limitation 用作掩盖本日必做 fencing/原子性失败的借口。

## 11. Interview Questions 与表达练习

完成实现与测试以后再用完成时表述；目前以下回答均为设计目标。

### 基础原理

1. 为什么 Worker 活着仍可能不 READY？为什么 heartbeat 不证明 progress？
2. timeout 正好等于临界值时如何判定？为什么不用 wall clock 算 elapsed？
3. `WorkerLease`、`TaskClaim`、`RestartTicket` 各自保护什么？
4. Task attempt 为什么只能在成功 claim 时增加？Worker restart 为什么不清空它？

### Runtime 与并发

5. 两边分别加锁为什么不够？你的一次 recovery 线性化点在哪里？
6. 扫描与撤销之间发生 heartbeat 或 complete 怎么办？只校验 generation 为什么仍不够？
7. `RLock` 为什么不能成为锁内调用 factory 的借口？
8. factory 失败、observer 重入 stop、旧 factory 回调回来，各自如何处理？
9. 一个原本 FAILED 的 Task 何时能重排，何时是不可复活终态？
10. 同一个 worker_id 的 attempt1 迟到结果，怎样证明不会完成 attempt2？

### 设计、证据与局限

11. Registry 成为 Agent 权威之后，为什么 Scheduler 仍保留 ownership？
12. 为什么保留旧 import，却不保留裸 worker_id 的 complete API？
13. Fencing 为什么不等于恰好一次外部执行？SafeExecution 还缺哪层 Team token 绑定？
14. detection latency 与 processing latency 的起止点分别是什么？
15. 无 fencing ablation 若换成不同 Worker，会掩盖什么？
16. Day5 逻辑重启与 Day6 durable resume 的本质区别是什么？

**30 秒版本（设计阶段）。**

> 我准备在已有 Scheduler 上增加显式 claim fencing，并将 Worker 动态状态集中到 Registry。两者通过同一个进程内协调锁提交 claim 和失活恢复；Lifecycle 用 monotonic 心跳候选做扫描，提交前重新检查 generation、revision 和当前 claim。逻辑重启采用锁内预留、锁外构建、锁内校验发布。这样能拒绝旧 attempt 和旧 generation 的回调，但不声称已经终止旧进程或保证工具副作用 exactly-once。

**2 分钟版本补充。**

> 重点不是“发现超时就重试”。当前同 worker_id 可以先后执行一个 node 的多次 attempt，因此 owner 相同不能证明结果仍有效。我先要求 start/complete/fail 必须携带 Scheduler 发出的完整 claim，拒绝省略 attempt 的兼容入口。然后把 Task ownership 和 Agent 生命周期分开，但放在共同事务边界内，使 CLAIMED/RUNNING 的撤销、有限重排和 Worker FAILED 同时生效。扫描不是最终裁决，重新验证防止撤销已经心跳或完成的任务。重启 factory 失败也消耗有限预算，返回时通过 reservation 防止 STOPPED 被复活。测试用 FakeClock、Barrier/Event，专门测同 Worker 的旧 attempt 和重启后的旧 generation；周末实验才量化开销和对照收益。

不要加上本轮未发生的“真实 kill 后恢复”“成功率提升”“分布式 exactly-once”等结论。

## 12. 今日最终完成标准与待确认选择

### 教程交付标准（本轮）

- 原安排保留，新增事实/澄清/拟实现三类说明。
- 每一步有目标、理由、文件、接口、Python 知识、局部参考、验证、常见错误和完成标志。
- fencing 在 timeout/recovery 前完成；attempt、generation、revision、restart ticket 责任分开。
- 共享事务、回调锁边界、时钟与终态语义没有前后矛盾。
- Tests/DD/Benchmark/Ablation/Failure/Interview 都有计划，但不冒充实测。

### 后续 Day5 功能验收（全部待实现/待验证）

- [ ] AgentRegistry 为唯一 Worker 动态状态权威，旧 WorkerRegistry import 指向同实现。
- [ ] TaskScheduler 为唯一 Task/ownership 权威，强制完整 claim，旧入口明确拒绝。
- [ ] 同 worker 同 generation 的 attempt1 不能影响 attempt2。
- [ ] generation 变化后旧 heartbeat/recovery/restart callback 被拒绝。
- [ ] CLAIMED/RUNNING/READY 失活各有正确恢复语义，重复 sweep 幂等。
- [ ] retry/restart 有上限，终态不复活，STOPPED 不自动重启。
- [ ] 共享事务可证明无半写；factory/sink 不持 core lock；回调重入不死锁。
- [ ] FakeClock 边界、并发、角色、Mailbox 不越权及全部旧回归通过。
- [ ] 实际验收日志分类记录 Ruff/mypy 债与新增问题，外部环境 skip 如实披露。

### 周末工程证据（待执行，不包装成已完成）

- [ ] DD-W5-05 单独落盘并由证据更新状态。
- [ ] Benchmark 保存 workload、manifest、raw samples，分离检测/处理/重启/等待延迟。
- [ ] 同场景 no-fencing 与其他 ablation 可复现，失败轨迹归档。
- [ ] Failure Cases 记录真实观察，而非只抄本节预期。

### 实现前需要确认的产品选择

本节已给出一致的 V1 推荐值，开始编码不需要重新发明协议：

| 选择 | 本节推荐 | 后续什么情况下重议 |
| --- | --- | --- |
| timeout 边界 | `elapsed >= timeout` | 需要对接外部协议时统一变更并重测，不两种混用 |
| 默认时间/次数 | 示例 heartbeat 5s、timeout 15s、cooldown 2s、max_restarts 2 | 真实 workload 测出误判/成本，再调参数；本日无自动 heartbeat 驱动器 |
| stop 持有任务 | 撤销 Worker，Task 受相同 retry budget 控制重排 | 产品需要“停止整个任务”时新增明确 cancel 语义 |
| AgentInfo.status | bootstrap 初始化输入 | UI 需要统一实时 info 时迁为只读投影，不增加写源 |
| Registry 与 Scheduler | 一个 Registry 绑定一个 Scheduler、共享 RLock | 多 Scheduler 或跨进程时改成真正 store transaction/lease 协议 |
| factory 范围 | 同步、短时、无 I/O 的 Worker facade 重建 | 真正进程/容器/Runtime 生命周期由未来执行管理器处理 |
| heartbeat 审计 | 学习版逐次记录，按团队生命周期释放 | 周末量化保留成本后决定采样/归档，关键恢复事件不可丢 |

无论上述参数如何选择，**强制 fencing、唯一状态权威、跨对象原子性、STOPPED 不复活、外部回调锁外执行**都不是可选项。

建议下一轮从 **Step 1：数据契约** 开始。正式改代码前重新读取当前文件和 git 状态，不假定今天记录的行号与接口永远不变。
