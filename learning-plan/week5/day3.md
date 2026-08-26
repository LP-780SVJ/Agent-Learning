# Week5 Day 3：Scheduler 与任务认领

今天进入 Multi-Agent Runtime 最核心的执行层。

昨天：

> Task DAG 解决了“任务之间如何组织”。

今天：

> Scheduler 解决“哪些任务什么时候执行，由哪个 Agent 执行”。

也就是说：

```text
Day1:
为什么需要多个 Agent？

Day2:
如何表达任务依赖？

Day3:
如何调度 Agent 执行任务？
```

最终形成：

```text
                Lead Agent

                    |

                Task DAG

                    |

              Task Scheduler

                    |

        +-----------+-----------+

        |           |           |

    Worker A    Worker B    Worker C

```

这也是工业级 Agent Harness 的核心能力：

> **Orchestration Runtime**

---

# 一、今天解决什么问题？

假设 Lead Agent 生成：

```text
Task DAG:

        A

      /   \

     B     C

      \   /

        D
```

含义：

- A 必须先完成
- B、C 可以并行
- D 等待 B、C


现在问题：

## 谁执行 B？

## 什么时候执行？

## 如果两个 Worker 同时抢 B 怎么办？

## Worker 崩溃怎么办？

这些不是 Agent 本身负责。

而是：

# Scheduler

---

# 二、为什么 Coding Agent 需要 Scheduler？

很多初级 Multi-Agent：

直接：

```python
asyncio.gather(
    worker1.run(),
    worker2.run(),
    worker3.run()
)
```

看似并行。


但是工业环境会出现问题。

---

# 问题1：任务依赖

例如：

```text
Database Migration

        ↓

Backend API

        ↓

Integration Test
```

不能：

```text
Test Agent

提前执行测试
```


---

# 问题2：资源竞争


例如：

两个 Worker：

```text
Worker A:

修改 auth.py


Worker B:

修改 auth.py
```


产生：

- merge conflict
- overwrite
- 状态污染


---

# 问题3：失败恢复


Worker：

```text
运行测试

↓

Crash
```


谁知道：

任务失败？

谁重新安排？

---

# 问题4：动态变化


执行过程中：

Agent 发现：

需要新增任务：

```text
Add migration test
```


Scheduler 需要：

动态加入 DAG。


---

所以：

工业级 Agent：

不是：

```text
Agent = async function
```


而是：

```text
Agent = Runtime Managed Entity
```

---

# 三、工业界 Scheduler 实践

---

# 1. Kubernetes Scheduler 类比

Kubernetes：

用户提交：

```yaml
Pod
```

Scheduler：

决定：

```text
哪个 Node 运行 Pod
```


流程：

```text
Pod Pending

↓

Scheduler

↓

Node Selection

↓

Running
```


Agent Scheduler 类似：

```text
Task Pending

↓

Scheduler

↓

Worker Selection

↓

Running
```

---

# 2. Celery Task Queue


Celery：

经典任务系统。


结构：

```text
Producer

   |

Message Queue

   |

Worker Pool

   |

Task Result
```


Agent Runtime：

类似：

```text
Lead Agent

   |

Task Queue

   |

Worker Agent

   |

Result
```

---

# 3. Ray Scheduler


Ray：

面向 AI workload。


核心：

```text
Task

↓

Actor

↓

Scheduler

↓

Worker
```


Multi-Agent Runtime 很多设计借鉴：

- Actor
- Task placement
- Failure recovery


---

# 4. LangGraph Runtime


LangGraph：

不是简单调用 Agent。


它维护：

```text
Graph State

↓

Node Execution

↓

State Transition
```


Scheduler 决定：

下一步运行哪个 Node。


---

# 四、Task Queue

## 什么是 Task Queue？

任务队列。

Scheduler 不直接执行任务。

而是：

```text
Task DAG

↓

Ready Queue

↓

Worker Claim
```


---

例如：

DAG：

```text
A

|

+----B

+----C
```


A 完成。


Scheduler：

发现：

```text
B READY

C READY
```


放入：

```text
Queue

[
 B,
 C
]
```

---

Worker：

从 Queue 获取。


---

# 五、Worker Pool

## 什么是 Worker Pool？

一组执行 Agent。


例如：

```text
Worker Pool:

worker-1
worker-2
worker-3
```


每个 Worker：

拥有：

```text
Agent Identity

Role

Context

Workspace

Tools
```


---

## 为什么不是无限创建 Worker？

因为：

成本。


例如：

100 个 Agent：

同时调用 LLM：

结果：

- Token 爆炸
- API 限流
- 文件冲突


所以：

需要：

```text
max_workers=3
```

---

今天：

支持：

```text
3 Worker 并发
```

---

# 六、Scheduler 状态机设计

这是今天最重要内容。


很多初学者：

直接：

```python
task.running=True
```

错误。


工业系统：

使用：

# Task State Machine


---

## Task 生命周期


```text
CREATED

   |

   v

READY

   |

   v

CLAIMED

   |

   v

RUNNING

   |

   +------------+

   |            |

SUCCESS       FAILED

                |

                v

             RETRYING

                |

                v

              READY

```

---

# 为什么需要 CLAIMED？

因为：

防止重复执行。


例如：

Task:

```text
T1
```

两个 Worker：

同时看到：

```text
READY
```


如果没有：

CLAIM：

结果：

```text
Worker A 执行

Worker B 执行
```

---

所以：

必须：

```text
READY

↓

CLAIMED
```

这个过程必须原子。


---

# 七、Scheduler 核心接口设计

今天实现：

```text
scheduler.py
```

---

# 1. schedule()

作用：

扫描 DAG：

寻找：

```text
READY tasks
```

然后：

进入 Queue。


例如：

```python
scheduler.schedule()
```


内部：

```python
ready_tasks =
dag.get_ready_tasks()


for task in ready_tasks:

    queue.put(task)
```


---

# 2. claim()

Worker 获取任务。


流程：

```text
Worker

↓

claim()

↓

Task Queue

↓

Task
```


例如：

```python
task =
scheduler.claim(
    worker_id="worker-1"
)
```


成功：

```text
Task1

owner=worker-1

status=CLAIMED
```


---

# 3. complete()

Worker 完成。


例如：

```python
scheduler.complete(
    task_id="T1"
)
```


状态：

```text
RUNNING

↓

COMPLETED
```


然后：

触发：

```text
重新调度
```


因为：

新的 Task 可能 ready。


---

# 4. fail()

任务失败。


例如：

```python
scheduler.fail(
    task_id="T1",
    reason="test failed"
)
```


状态：

```text
RUNNING

↓

FAILED
```


如果允许 retry：

```text
FAILED

↓

READY
```


---

# 八、CodeTeam Scheduler 设计

目录：

```text
codeteam/

agent_team/

    scheduler.py
```

---

## TaskScheduler

```python
class TaskScheduler:


    def schedule(self):
        ...


    def claim(
        self,
        worker_id:str
    ):
        ...


    def complete(
        self,
        task_id:str
    ):
        ...


    def fail(
        self,
        task_id:str,
        reason:str
    ):
        ...
```

---

# 九、内部数据结构

---

## Task Queue

第一版：

使用：

```python
asyncio.Queue
```


例如：

```python
queue.put(task)
```


---

## Worker Registry


保存：

```python
{
 worker_id:
 {
  role:"backend",
  status:"running"
 }
}
```


---

## Task Ownership


Task:

增加：

```python
owner
```


例如：

```json
{
"id":"T1",
"owner":"worker-1",
"status":"RUNNING"
}
```

---

# 十、完整执行流程


假设：

3 Worker。


---

## Step1

Lead:

生成 DAG。


```text
A

|

B C

|

D
```


---

## Step2

Scheduler:

发现：

```text
A READY
```


Queue:

```text
[A]
```


---

## Step3

Worker1:

claim A。


状态：

```text
A

READY

↓

CLAIMED

↓

RUNNING
```


---

## Step4

Worker1 完成。


```text
A

↓

COMPLETED
```


---

## Step5

Scheduler:

重新计算。


发现：

```text
B READY

C READY
```


Queue:

```text
[B,C]
```


---

## Step6

Worker1:

claim B


Worker2:

claim C


并行。


---

# 十一、为什么选择 State Machine Scheduler？

今天 Design Decision。

---

# DD-W5-03

## 问题

如何管理 Agent Task Execution？


---

## 方案A：

简单 asyncio.gather


例如：

```python
await asyncio.gather(
 worker1(),
 worker2()
)
```


优点：

简单。


缺点：

没有：

- 状态
- 恢复
- ownership
- retry


---

## 方案B：

State Machine Scheduler


任务：

```text
READY

↓

CLAIMED

↓

RUNNING

↓

COMPLETED
```


优点：

- 可恢复
- 可追踪
- 可扩展


缺点：

复杂。


---

## Decision

选择：

State Machine Scheduler。


原因：

Coding Agent 是长任务系统。

必须支持：

- crash recovery
- resume
- retry


---

# 十二、测试设计

---

# Test 1：正常 Claim


初始：

```text
Task A

READY
```


Worker1:

claim。


结果：

```text
owner=worker1

status=CLAIMED
```


---

# Test 2：重复 Claim


场景：

Worker1:

claim T1


Worker2:

同时 claim T1


期望：

只有一个成功。


结果：

```text
Worker1 SUCCESS

Worker2 FAIL
```


---

# Test 3：并发 Claim


三个 Worker：

同时：

claim 10 tasks。


验证：

没有重复。


---

# Test 4：Fail Retry


流程：

```text
Task

READY

↓

RUNNING

↓

FAILED

↓

READY

↓

RUNNING

↓

SUCCESS
```


---

# 十三、Benchmark

今天测试 Scheduler 性能。


---

## 规模


任务：

```text
100 tasks

500 tasks

1000 tasks
```


---

## 指标1：

Scheduling Latency


定义：

```text
task ready

↓

worker receive
```


---

## 指标2：

Claim Throughput


例如：

```text
1000 claim / sec
```


---

## 指标3：

Recovery Latency


失败：

```text
Worker crash

↓

Task reassign
```


时间。


---

结果：

保存：

```text
docs/benchmark/W5_SCHEDULER.md
```


---

# 十四、Failure Cases


目录：

```text
docs/failure_cases/week5/
```


---

## F-W5-D3-01

## Duplicate Claim


现象：

两个 Worker 执行同一个 Task。


原因：

claim 非原子。


解决：

Task Lock。


---

## F-W5-D3-02

## Worker Crash


现象：

任务永久 RUNNING。


原因：

没有 heartbeat。


下一步：

Day5解决。


---

## F-W5-D3-03

## Lost Task


现象：

Queue 中任务消失。


原因：

Queue 没持久化。


解决：

TaskStore。


---

# 十五、今天代码产出


新增：

```text
codeteam/

agent_team/

    scheduler.py
```


测试：

```text
tests/

agent_team/

    test_scheduler.py
```


文档：

```text
docs/

design_decisions/

DD-W5-03.md


docs/

benchmark/

W5_SCHEDULER.md
```


---

# 十六、面试表达

面试问题：

> “Multi-Agent 系统如何避免多个 Agent 重复执行同一个任务？”


回答：

> 我没有直接使用 asyncio 并发调用，而是设计了基于状态机的 Task Scheduler。任务经过 CREATED、READY、CLAIMED、RUNNING、COMPLETED 等状态迁移，Worker 获取任务时通过原子 claim 保证唯一 ownership。同时 Scheduler 根据 Task DAG 动态发现 Ready Task，并通过 Worker Pool 控制并发规模。


---

# 今日完成后，你的 Agent Runtime 增加：

昨天：

```text
Task DAG
```

解决：

> 做什么？


今天：

```text
Scheduler
```

解决：

> 谁来做？什么时候做？失败怎么办？


明天进入：

# Day4：Mailbox 与 Agent Communication

解决：

> Agent 之间如何可靠协作和传递信息？

---

# Week5 Day3 实操教程：从 Ready Resolution 到原子任务认领

本节是在当前仓库真实状态之上追加的 Day3 实操教程。它不是替代上面的原计划，而是把原计划适配到 Week5 Day1/Day2 已经完成的代码边界：`LeadAgent` 产生结构化 assignment，`TaskDAG` 表达依赖和 ready resolution，今天才开始设计 Scheduler。

本轮教程只讲设计和实现步骤，不创建 `scheduler.py`，不创建测试文件，不修改生产代码。

---

## 1. Today in the System

今天的 Scheduler 位于这条链路中间：

```text
TaskSpec
  -> LeadAgent
  -> Plan / WorkerAssignment
  -> TaskDAG
  -> TaskScheduler
  -> WorkerAgent
```

Day2 的 `TaskDAG.get_ready_tasks()` 只能回答：

```text
哪些 PENDING 节点的所有 prerequisite 已经 COMPLETED？
```

它不能回答：

```text
这个 ready task 是否已经入队？
谁认领了它？
两个 Worker 同时 claim 时谁赢？
Worker 已经 busy 时还能不能 claim？
complete/fail 的调用者是不是 owner？
失败后是否允许 retry？
```

这些都是 Day3 Scheduler 的职责。

今天 Scheduler 要解决的问题：

- 把 DAG 中 dependency-ready 的节点幂等放入调度队列。
- 根据 Worker role 和 availability 做 claim。
- 保证同一个 task 只能被一个 Worker 原子认领。
- 维护 task runtime ownership、attempt、failure reason。
- 提供 `schedule / claim / start / complete / fail` 的受控状态机入口。
- 记录 Scheduler 事件，给 Day5 recovery 和 Day6 durable store 留证据。

今天 Scheduler 不负责：

- 真实执行 Worker 的工具调用。
- Mailbox 通信。
- Worktree ownership / merge。
- Worker crash 自动恢复。
- heartbeat。
- durable queue。
- 跨进程或分布式 claim。
- 动态 DAG 事务修改。
- 证明 Multi-Agent 端到端加速。

---

## 2. Capability Mapping

今天主要映射到能力树：

```text
Multi-Agent Orchestration
├── Scheduling
├── Dependency Resolution
├── Worker Lifecycle
├── Ownership
├── Concurrency Control
└── Failure Recovery foundation
```

它能证明的 Agent Runtime 工程能力不是“会写一个队列”，而是：

- 能把 planning-time contract 和 runtime state 分开。
- 能把 DAG ready query 变成可认领的 Scheduler 协议。
- 能用状态机限制非法生命周期跳转。
- 能在线程并发下保证唯一 ownership。
- 能把失败、retry、blocked 设计成可审计的状态，而不是散落的 bool 字段。

---

## 3. 当前仓库真实状态

### 3.1 Day1 可复用

当前 `codeteam/agent_team/models.py` 已有：

- `AgentRole`：`LEAD / BACKEND / FRONTEND / TEST / REVIEW / GENERAL`。
- `AgentStatus`：`CREATED / READY / BUSY / FAILED / STOPPED`。
- `AgentIdentity`：`agent_id / display_name`。
- `AgentInfo`：identity、role、status、capabilities。
- `WorkerAssignment`：Lead 产生的计划契约。
- `LeadPlanningResult`：Plan 加 assignments。

当前 `codeteam/agent_team/worker.py` 已有：

- `WorkerAgent`：包装 `AgentInfo`，拒绝 `AgentRole.LEAD`。
- `WorkerRegistry`：注册、按 worker_id 获取、按 role 做 `compatible(role)` 查询。

注意：`WorkerAgent.info` 当前返回内部 `AgentInfo` 引用。如果注册后外部把 `worker.info.identity.agent_id` 改掉，会让 Registry key 和 Worker 自报身份不一致。Day3 要么让 `info` 返回防御性快照，要么让 `AgentInfo`/`AgentIdentity` frozen；教程推荐先做防御性快照。

### 3.2 Day2 可复用

当前 `codeteam/agent_team/dag.py` 已有：

- `TaskStatus`：`PENDING / READY / RUNNING / COMPLETED / FAILED / BLOCKED`。
- `TaskNode`：`node_id / assignment / status`。
- `TaskDAG.from_lead_planning_result()`：用 `assignment_id` 生成 `node_id`。
- `dependencies=None` 多节点 fail closed。
- `dependencies=()` 明确表示所有节点独立。
- `nodes / topological_sort / get_ready_tasks` 返回防御性节点快照。
- `topological_sort()` 使用 heap，顺序稳定。
- `replace_task_status()` 只做类型检查，不验证合法转移。

Day3 可以复用 `TaskDAG.get_ready_tasks()` 作为 ready source，但不能直接把 `replace_task_status()` 当 Scheduler 状态机。它缺少：

- expected current status。
- owner 校验。
- attempt 更新。
- queue membership 同步。
- stale state / compare-and-set 失败信号。
- transition table。

### 3.3 不能混用的状态

当前仓库至少有三类状态：

```text
codeteam.agent_team.dag.TaskStatus
  DAG runtime node status

codeteam.agent_team.models.AgentStatus
  Worker lifecycle / availability status

codeteam.task.state.TaskStatus
  Single-Agent top-level coding task lifecycle
```

今天只设计 `codeteam.agent_team.dag.TaskStatus` 这一套 DAG node 状态，不创建第二套 `TaskState` 或 `TaskStatus`。

### 3.4 Event Log / Session / Worktree

`codeteam/events.py` 已有 `AgentEventType` 和 `make_event()`。Week5 Scheduler 事件应扩展这个事件系统，例如：

```text
scheduler.scheduled
scheduler.claimed
scheduler.started
scheduler.completed
scheduler.failed
scheduler.retried
scheduler.blocked
```

不要新增独立日志系统。

`codeteam/session/` 已经有 durable Session，但它记录的是单 Agent runtime/session 状态。Day3 先做进程内 Scheduler，不把 Scheduler queue 写进 Session。

`codeteam/git/worktree.py` 和 checkpoint 能力已经存在，但 Worker 的 workspace ownership 不是 Day3 要解决的问题。Day3 只做 task ownership，不做 file ownership。

### 3.5 当前测试基线

当前 `tests/agent_team` 已覆盖 Day1 Lead/Worker 和 Day2 DAG，基线应保持通过。今天教程完成后只跑：

```bash
.venv/bin/python -m pytest tests/agent_team -q
```

---

## 4. 原 Day3 计划适配

原计划里有几个地方需要按当前仓库修正。

| 原计划 | 当前仓库适配 |
|---|---|
| `CREATED` task state | DAG node 初始态使用 `PENDING`，不再引入 `CREATED`。 |
| `SUCCESS` | 统一使用 `COMPLETED`。 |
| `CLAIMED` | Day3 应新增到现有 `TaskStatus`，不是新建第二个 enum。 |
| `RETRYING` | 第一版不建议做独立状态，用 `FAILED + attempt + retry decision` 表达；需要重新入队时转回 `READY`。 |
| `asyncio.Queue` | 原计划接口是同步函数，和 `asyncio.Queue` 冲突；第一版推荐同步 Scheduler Core。 |
| Worker Registry 保存 status | 当前 `WorkerRegistry` 只保存 `WorkerAgent` 并按 role 查 compatible，不表示 available。 |
| Task 增加 owner 字段 | 不要污染 `WorkerAssignment`；owner 属于 runtime record。 |
| Recovery Latency benchmark | Worker crash recovery 留给 Day5，Day3 benchmark 只能测 schedule/claim。 |

---

## 5. 核心领域模型

### 5.1 唯一正式状态词表

Day3 后建议把现有 `TaskStatus` 扩展为：

```text
PENDING
READY
CLAIMED
RUNNING
COMPLETED
FAILED
BLOCKED
```

映射规则：

- 原计划 `CREATED` -> `PENDING`。
- 原计划 `SUCCESS` -> `COMPLETED`。
- 原计划 `CLAIMED` -> 新增到现有 `TaskStatus`。
- 原计划 `RETRYING` -> 不作为第一版独立状态；用 `FAILED + attempt + retry decision`，通过 Scheduler 决策转回 `READY`。

为什么需要 `CLAIMED`？

`READY` 只表示“可被认领”。`CLAIMED` 表示“某个 Worker 已经拿到任务，但还没正式进入执行”。没有 `CLAIMED`，两个 Worker 可能同时从 ready queue 看见同一个 node 并都开始执行。

### 5.2 正式状态图

```text
PENDING
  |
  | schedule() sees dependency-ready
  v
READY
  |
  | claim(worker)
  v
CLAIMED
  |
  | start(worker)
  v
RUNNING
  | \
  |  \ fail(worker)
  |   v
  |  FAILED -- retry decision under max_attempts --> READY
  |
  | complete(worker)
  v
COMPLETED

PENDING / READY
  |
  | dependency failed or impossible role
  v
BLOCKED
```

Terminal states:

```text
COMPLETED
BLOCKED
FAILED when retry budget is exhausted
```

可重试状态：

```text
FAILED
```

但只有满足：

```text
attempt < max_attempts
failure category is retryable
prerequisites still valid
```

才允许重新进入 `READY`。

### 5.3 合法状态转移表

| From | To | API | 必要条件 |
|---|---|---|---|
| `PENDING` | `READY` | `schedule()` | DAG 依赖已满足，未入队 |
| `READY` | `CLAIMED` | `claim()` | worker known、role match、available、CAS 成功 |
| `CLAIMED` | `RUNNING` | `start()` | caller 是 owner |
| `RUNNING` | `COMPLETED` | `complete()` | caller 是 owner |
| `RUNNING` | `FAILED` | `fail()` | caller 是 owner |
| `FAILED` | `READY` | `retry()` 或 `fail(retry=True)` | attempt 未超限 |
| `PENDING` | `BLOCKED` | `schedule()` | prerequisite failed 且不可继续 |
| `READY` | `BLOCKED` | `schedule()` | role 永久不可满足或外部取消 |

非法跳转示例：

- `PENDING -> COMPLETED`：绕过 claim、owner、execution evidence。
- `COMPLETED -> RUNNING`：终态不应回退，否则审计和 dependent 解锁都会混乱。
- `READY -> RUNNING`：绕过 `CLAIMED`，无法证明唯一 ownership。
- `FAILED -> COMPLETED`：失败任务必须先 retry/run，不能直接成功。
- `BLOCKED -> RUNNING`：blocked 需要显式 unblock/retry/replan。

### 5.4 BLOCKED 的语义

`BLOCKED` 是 task runtime 状态，不是 Worker 状态。

适合写 `BLOCKED` 的情况：

- prerequisite 已经 terminal failed，dependent 永远无法满足。
- 所需 role 在本次 team 配置中根本不存在，并且系统决定 fail closed。
- 外部 policy/cancel 决定该节点不可执行。

不建议写 `BLOCKED` 的情况：

- 暂时没有空闲 Worker。
- compatible worker 当前 `BUSY`。
- 队列暂时为空。

这些是 Scheduler availability 问题，不是 task 自身不可执行。

### 5.5 Runtime Record，不污染 Assignment

`WorkerAssignment` 是 Lead 产生的计划契约。不要把 `owner_id`、`attempt`、`failure_reason` 写进去。

推荐新增运行时模型：

```python
class TaskRuntimeRecord(BaseModel):
    node_id: str
    status: TaskStatus
    owner_id: str | None = None
    attempt: int = 0
    failure_reason: str | None = None
    claimed_at: float | None = None
```

四种 ID 不能混用：

```text
node_id
  DAG 权威 ID，用于 Scheduler queue / owner / transition。

assignment_id
  WorkerAssignment 身份；当前 factory 映射为 node_id。

source_step_id
  Planner trace 字段，不是 DAG edge ID。

owner_id
  Worker identity.agent_id，不是 role，不是 display_name。
```

`TaskRuntimeRecord` 与 `TaskDAG.status` 不能各自独立变化。Day3 要选择唯一 source of truth：

推荐：

```text
TaskRuntimeRecord.status 是 Scheduler 状态权威。
TaskDAG 继续负责 topology / prerequisites。
```

如果为了兼容 Day2 暂时需要回写 `TaskDAG.replace_task_status()`，也必须只由 Scheduler 在同一锁内调用，不能让外部同时修改 DAG status。

---

## 6. Scheduler Architecture

推荐第一版：

```text
同步 TaskScheduler Core
+ threading.Lock
+ collections.deque
+ WorkerRegistry
+ runtime_records: dict[node_id, TaskRuntimeRecord]
+ queued_node_ids: set[node_id]
```

核心数据流：

```text
TaskDAG.get_ready_tasks()
        |
        v
TaskScheduler.schedule()
        |
  idempotent enqueue
        |
        v
TaskScheduler.claim(worker_id)
        |
 lock + role + availability + CAS + ownership
        |
        v
CLAIMED -> RUNNING -> COMPLETED/FAILED
```

为什么不用 `asyncio.Queue`？

原计划里的 API 是同步：

```python
def schedule()
def claim()
def complete()
def fail()
```

但 `asyncio.Queue` 需要 event loop，并且 `put/get` 通常是 async 场景。把同步 API 和 `asyncio.Queue` 混在一起，会让测试、锁、event loop ownership 都变复杂。

对比：

| 方案 | 优点 | 问题 | Day3 选择 |
|---|---|---|---|
| `asyncio.Queue + asyncio.Lock + async API` | 适合 async Worker | 当前仓库核心测试和接口多为同步；状态正确性绑定 event loop | 以后外层 adapter 可用 |
| `queue.Queue + threading.Lock` | 内置线程安全队列 | queue 自己的锁和 Scheduler 状态锁容易双重协调 | 可选但不首选 |
| `deque + threading.Lock` | 队列、owner、status、attempt 可在一个锁内维护 | 需要自己写边界 | Day3 推荐 |
| 外部并发执行器 + 同步 Core | 核心简单，可被 async/thread 调用 | 需要 adapter 层 | 推荐架构方向 |

关键点：Scheduler 状态正确性不应该依赖 event loop。未来可以在同步核心外包一层 async Worker execution：

```python
async def async_worker_loop(core: TaskScheduler):
    claim = core.claim(worker_id)
    if claim is None:
        await asyncio.sleep(backoff)
```

但原子 claim 仍发生在同步 Core 的锁里。

---

## 7. 并发时序

两个 Worker 同时 claim 同一个 task：

```text
Worker A                      Scheduler                      Worker B
   |                              |                              |
   | claim("worker-a")            |                              |
   |----------------------------->|                              |
   |                              | lock acquired                |
   |                              | pop node_id=T1               |
   |                              | status READY -> CLAIMED      |
   |                              | owner_id = worker-a          |
   |                              | queued_node_ids remove T1    |
   |                              | lock released                |
   |<-----------------------------|                              |
   | Claim(T1)                    |                              |
   |                              |<-----------------------------|
   |                              | claim("worker-b")            |
   |                              | lock acquired                |
   |                              | queue empty or T1 not READY  |
   |                              | lock released                |
   |                              |----------------------------->|
   |                              | None                         |
```

线性化点是：

```text
锁内 READY -> CLAIMED + owner_id 写入 + queued_node_ids 更新
```

不能只说“有 Lock 就原子”。真正要在同一临界区保持一致的是：

- status
- owner_id
- queue membership
- attempt
- worker availability

如果 claim 失败，不能留下：

```text
owner_id 已写，但 status 还是 READY
status 已 CLAIMED，但队列里还有 node_id
worker 已 BUSY，但没有任务 owner
attempt 增加，但任务未被认领
```

---

## 8. 分步骤学习与实现指南

### Step0：冻结状态词表和 source of truth

目标：明确 Day3 只扩展现有 `TaskStatus`，不新建第二套状态。

原因：两个状态 enum 会让 DAG、Scheduler、测试各说各话。

涉及文件：

```text
codeteam/agent_team/dag.py
learning-plan/week5/day3.md
```

Python 知识：

- `Enum` 是有限词表。
- `TaskStatus.CLAIMED` 是枚举成员，不是裸字符串 `"claimed"`。

接口骨架：

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
```

验证方式：

- 非法字符串状态被 Pydantic 拒绝。
- `SUCCESS` 不出现在 Week5 DAG/Scheduler 代码里。

常见错误：

- 新建 `TaskState` enum。
- 把 `AgentStatus.READY` 当 task ready。

完成标志：你能说明 `CREATED -> PENDING`、`SUCCESS -> COMPLETED`、`RETRYING` 为什么暂不作为独立状态。

### Step1：补充 Scheduler 模型、异常、transition table

目标：建立 Scheduler 的领域语言。

原因：Scheduler 不能靠 `ValueError` 和 bool 表达所有失败。

涉及文件：

```text
codeteam/agent_team/scheduler.py
codeteam/agent_team/__init__.py
```

Python 知识：

- `BaseModel` 适合做可序列化运行时记录。
- 自定义异常方便测试精确断言。
- `dict[TaskStatus, tuple[TaskStatus, ...]]` 可以表达 transition table。

接口骨架：

```python
TASK_TRANSITIONS = {
    TaskStatus.PENDING: (TaskStatus.READY, TaskStatus.BLOCKED),
    TaskStatus.READY: (TaskStatus.CLAIMED, TaskStatus.BLOCKED),
    TaskStatus.CLAIMED: (TaskStatus.RUNNING, TaskStatus.FAILED),
    TaskStatus.RUNNING: (TaskStatus.COMPLETED, TaskStatus.FAILED),
    TaskStatus.FAILED: (TaskStatus.READY,),
    TaskStatus.COMPLETED: (),
    TaskStatus.BLOCKED: (),
}

class SchedulerError(Exception):
    pass

class InvalidSchedulerTransitionError(SchedulerError):
    pass

class StaleTaskStateError(SchedulerError):
    pass

class TaskOwnershipError(SchedulerError):
    pass
```

验证方式：

- 合法转移通过。
- `PENDING -> COMPLETED` 抛异常。
- terminal state 没有出口。

常见错误：

- 用 if/else 散落在各个方法里，不集中成表。
- 允许裸字符串状态进入。

完成标志：所有状态转移都能从表里解释。

### Step2：加固 Worker identity/info 和 availability 契约

目标：区分 Worker 身份、role compatibility 和 runtime availability。

原因：当前 `WorkerRegistry.compatible(role)` 只表示 role 匹配，不表示 Worker 空闲。

涉及文件：

```text
codeteam/agent_team/worker.py
codeteam/agent_team/scheduler.py
tests/agent_team/test_worker.py
tests/agent_team/test_scheduler.py
```

Python 知识：

- Pydantic `model_copy(deep=True)` 可以返回防御性快照。
- Registry key 必须稳定。

推荐契约：

```python
class WorkerAgent:
    @property
    def info(self) -> AgentInfo:
        return self._info.model_copy(deep=True)
```

Scheduler 内部维护：

```python
worker_runtime_status: dict[str, AgentStatus]
worker_current_task: dict[str, str | None]
```

`compatible(role)`：

```text
这个 Worker 能做这种角色。
```

`available(role)`：

```text
这个 Worker 能做这种角色，并且当前 READY/空闲。
```

一个 Worker 第一版默认只能 claim 一个任务。Worker `BUSY / FAILED / STOPPED` 时不能继续 claim。

常见错误：

- 把 `AgentRole` 当权限系统。role 只是调度条件，工具权限仍由 Week3/Day5 的 Policy/Sandbox 决定。
- 注册后允许修改 `agent_id`，导致 registry key 和 identity 不一致。

完成标志：能解释 unknown worker、role mismatch、busy/stopped/failed worker 的不同错误。

### Step3：实现幂等 schedule

目标：把 DAG ready tasks 放入 ready queue，重复调用不重复入队。

原因：Scheduler 可能在 complete/fail 后多次调用 `schedule()`。

涉及文件：

```text
codeteam/agent_team/scheduler.py
tests/agent_team/test_scheduler.py
```

Python 知识：

- `deque` 适合 FIFO queue。
- `set` 适合记录 queue membership。
- `with lock:` 保证临界区退出时释放锁。

接口骨架：

```python
def schedule(self) -> SchedulerResult:
    with self._lock:
        for node in self._dag.get_ready_tasks():
            record = self._records[node.node_id]
            if record.status is not TaskStatus.PENDING:
                continue
            if node.node_id in self._queued_node_ids:
                continue
            self._transition(node.node_id, TaskStatus.PENDING, TaskStatus.READY)
            self._queue.append(node.node_id)
            self._queued_node_ids.add(node.node_id)
```

验证方式：

- ready task 只入队一次。
- `schedule()` 调两次，queue 长度不变。

常见错误：

- 每次 schedule 都 append。
- `get_ready_tasks()` 返回快照后直接改 snapshot.status。

完成标志：重复 schedule 幂等。

### Step4：实现原子 claim 和唯一 ownership

目标：并发 Worker claim 时，一个 task 只能有一个 owner。

原因：这是 Day3 的核心正确性。

涉及文件：

```text
codeteam/agent_team/scheduler.py
tests/agent_team/test_scheduler.py
```

Python 知识：

- `threading.Lock` 保护共享内存。
- compare-and-set 是“检查当前值仍是 expected，然后写入 target”。
- `threading.Barrier` 可以让多个线程同时开始，不要用 `sleep` 假装并发。

接口骨架：

```python
def claim(self, worker_id: str) -> TaskClaim | None:
    with self._lock:
        worker = self._registry.get(worker_id)
        if not self._is_worker_available(worker_id):
            raise WorkerUnavailableError(worker_id)

        while self._queue:
            node_id = self._queue.popleft()
            self._queued_node_ids.discard(node_id)
            record = self._records[node_id]
            if record.status is not TaskStatus.READY:
                continue
            if not worker.supports(self._node_role(node_id)):
                continue

            self._compare_and_set(node_id, TaskStatus.READY, TaskStatus.CLAIMED)
            self._records[node_id] = record.model_copy(update={
                "status": TaskStatus.CLAIMED,
                "owner_id": worker_id,
                "claimed_at": now(),
            })
            self._worker_runtime_status[worker_id] = AgentStatus.BUSY
            self._worker_current_task[worker_id] = node_id
            return TaskClaim(node_id=node_id, worker_id=worker_id)

        return None
```

空队列返回 `None` 比抛异常更适合 Worker polling；unknown worker、role mismatch、worker unavailable 才抛领域错误。

常见错误：

- 先设置 owner，后检查 role。
- 从 queue pop 出后失败，忘记恢复 membership。
- Worker `BUSY` 仍继续 claim 第二个任务。

完成标志：两个线程竞争一个 task，只有一个获得 claim。

### Step5：实现 start / complete / fail

目标：让 owner 推进任务生命周期。

原因：claim 只是拿到任务；真正执行要进入 `RUNNING`。

涉及文件：

```text
codeteam/agent_team/scheduler.py
tests/agent_team/test_scheduler.py
```

Python 知识：

- 方法参数应该显式传 `worker_id`，不要相信调用方口头说“我是 owner”。
- owner 校验是状态机的一部分。

接口骨架：

```python
def start(self, node_id: str, worker_id: str) -> None:
    with self._lock:
        self._require_owner(node_id, worker_id)
        self._compare_and_set(node_id, TaskStatus.CLAIMED, TaskStatus.RUNNING)

def complete(self, node_id: str, worker_id: str) -> None:
    with self._lock:
        self._require_owner(node_id, worker_id)
        self._compare_and_set(node_id, TaskStatus.RUNNING, TaskStatus.COMPLETED)
        self._release_worker(worker_id)
        self.schedule()

def fail(self, node_id: str, worker_id: str, reason: str) -> None:
    with self._lock:
        self._require_owner(node_id, worker_id)
        self._compare_and_set(node_id, TaskStatus.RUNNING, TaskStatus.FAILED)
        self._release_worker(worker_id)
```

注意：如果 `complete()` 在锁内调用 `schedule()`，需要避免普通 `Lock` 重入死锁。两种做法：

1. 把 `_schedule_locked()` 拆成内部方法，要求调用前已经持锁。
2. 使用 `RLock`，但第一版推荐内部 locked helper，更清楚。

常见错误：

- 非 owner 可以 complete/fail。
- complete 后没有释放 Worker。
- complete 后 dependent 没有进入下一轮 schedule。

完成标志：owner 一致性被测试覆盖。

### Step6：实现有上限 retry

目标：失败后可控地重新调度，而不是无限循环。

原因：Agent 工程里 retry 没上限就是成本黑洞。

涉及文件：

```text
codeteam/agent_team/scheduler.py
tests/agent_team/test_scheduler.py
```

Python 知识：

- `attempt` 是整数计数。
- `max_attempts` 是配置，不要散落硬编码。

推荐语义：

```text
claim 成功时 attempt += 1
fail 后：
  if attempt < max_attempts and retryable:
      status -> READY
      owner_id -> None
      requeue
  else:
      status -> FAILED terminal
```

如果要保留失败原因：

```python
failure_reason="pytest failed"
```

常见错误：

- retry 时不清 owner。
- retry 时不增加 attempt。
- failed dependency 的 dependent 仍被 ready。

完成标志：未超限重新 ready，超限保持 failed。

### Step7：接入现有 Event Log

目标：Scheduler 行为可审计。

原因：Day5 recovery 和 Day6 resume 都需要知道发生过什么。

涉及文件：

```text
codeteam/events.py
codeteam/agent_team/scheduler.py
tests/agent_team/test_scheduler.py
```

事件建议：

```text
SCHEDULER_TASK_SCHEDULED = "scheduler.task_scheduled"
SCHEDULER_TASK_CLAIMED = "scheduler.task_claimed"
SCHEDULER_TASK_STARTED = "scheduler.task_started"
SCHEDULER_TASK_COMPLETED = "scheduler.task_completed"
SCHEDULER_TASK_FAILED = "scheduler.task_failed"
SCHEDULER_TASK_RETRIED = "scheduler.task_retried"
SCHEDULER_TASK_BLOCKED = "scheduler.task_blocked"
```

事件 data 只记录安全字段：

```text
node_id
worker_id
from_status
to_status
attempt
reason_code
```

不要记录完整 prompt、完整 argv、secret、环境变量。

完成标志：状态变化都能从事件重放中看懂。

### Step8：补并发、状态机和回归测试

目标：证明 Scheduler 不重复 claim、不半写入、不非法跳转。

原因：状态机没有测试就是注释。

涉及文件：

```text
tests/agent_team/test_scheduler.py
tests/agent_team/test_worker.py
tests/agent_team/test_dag.py
```

Python 知识：

- `threading.Thread` 启动线程。
- `threading.Barrier` 让多个线程同时开始。
- `threading.Event` 控制线程释放。
- 测试并发不要依赖 `time.sleep()`。

完成标志：测试能稳定复现并发竞争，而且不 flaky。

### Step9：形成 DD-W5-03、Benchmark、Ablation、Failure Cases

目标：把工程取舍和证据留下。

涉及文件：

```text
docs/design_decisions/DD-W5-03.md
docs/benchmark/W5_SCHEDULER.md
docs/failure_cases/W5_SCHEDULER_FAILURE.md
evals/week5/benchmark_scheduler.py
```

注意：这是 Day3 实现阶段要做的，不是本轮教程写作要创建的文件。

完成标志：你能区分已测数据和未来待测假设。

---

## 9. Python 知识讲解

### threading.Lock

`Lock` 用来保护共享数据：

```python
with self._lock:
    # 这里是临界区
    ...
```

`with` 的意义是：进入时 acquire，退出时 release，即使中间抛异常也会释放。

### deque

`collections.deque` 是双端队列：

```python
queue.append(node_id)
node_id = queue.popleft()
```

Day3 用它做 FIFO ready queue。它本身不是完整 Scheduler；必须配合 lock 和 membership set。

### Enum 状态机

`TaskStatus.READY` 比 `"ready"` 安全，因为类型和候选值固定。状态机就是一张合法迁移表：

```python
allowed = TASK_TRANSITIONS[current]
if target not in allowed:
    raise InvalidSchedulerTransitionError
```

### dataclass / BaseModel

`dataclass` 轻量，适合内部小结构。

`BaseModel` 带验证和 JSON 序列化，适合以后进入 Session/TaskStore 的 runtime record。

Day3 的 `TaskRuntimeRecord` 推荐用 `BaseModel`，因为 Day6 可能持久化。

### 不可变快照

Day2 已经证明外部直接修改 `TaskNode` 会破坏 DAG。所以 Day3 的 claim/result 也应该返回快照，不返回内部 record 引用。

### compare-and-set

CAS 的核心是：

```text
只有当前状态仍等于 expected，才允许写 target。
```

伪代码：

```python
def _compare_and_set(node_id, expected, target):
    record = self._records[node_id]
    if record.status is not expected:
        raise StaleTaskStateError
    if target not in TASK_TRANSITIONS[expected]:
        raise InvalidSchedulerTransitionError
    self._records[node_id] = record.model_copy(update={"status": target})
```

### Barrier

并发测试里不要写：

```python
time.sleep(0.1)
```

推荐：

```python
barrier = threading.Barrier(2)

def worker():
    barrier.wait()
    scheduler.claim(worker_id)
```

这样两个线程尽量同时冲进 claim，更容易测试原子性。

---

## 10. Test Strategy

Day3 至少设计这些测试：

| 场景 | 断言 |
|---|---|
| ready task 只入队一次 | 重复 `schedule()` 后 queue 中无重复 node_id |
| schedule 幂等 | 第二次 schedule 不改变 queue / status |
| 正常 claim | `READY -> CLAIMED`，owner 写入 worker_id |
| unknown worker | 抛 `WorkerNotFoundError` 或 Scheduler 包装错误 |
| role mismatch | Worker role 与 assignment role 不匹配，不能 claim |
| busy worker 拒绝 | 一个 Worker 已有 task 时不能再 claim |
| stopped/failed worker 拒绝 | `AgentStatus.STOPPED/FAILED` 不能 claim |
| 两个 Worker 竞争一个任务 | 只有一个返回 `TaskClaim` |
| 多 Worker claim 多任务 | 无重复、无丢失 |
| 非 owner complete | 抛 `TaskOwnershipError` |
| 非 owner fail | 抛 `TaskOwnershipError` |
| 非法状态跳转 | `PENDING -> COMPLETED` 拒绝 |
| complete 后解锁 dependent | A complete 后 schedule 让 B ready |
| retry 未超限 | failed task 清 owner 后重新 ready |
| retry 超限 | 保持 `FAILED`，不重新入队 |
| queue/status/owner 半写入 | 失败后 record、queue、worker availability 一致 |
| no sleep concurrency | 使用 `Barrier/Event`，测试稳定 |

不要伪造：

- 跨进程 claim。
- Worker crash recovery。
- durable queue resume。
- mailbox 通信。

---

## 11. Scope Boundary

Day3 只证明：

```text
进程内 Scheduler
线程级原子 claim
唯一 ownership
状态机合法转移
幂等 schedule
有限 retry foundation
```

Day3 不宣称：

- 跨进程/分布式 claim。
- Worker crash 自动恢复。
- heartbeat。
- durable queue。
- TaskStore resume。
- 动态 DAG 事务修改。
- Multi-Agent 端到端加速。

Worker crash 留给 Day5，持久化和 lost task recovery 留给 Day6。

---

## 12. DD / Benchmark / Ablation / Failure Plan

### DD-W5-03

主题：

```text
State Machine Scheduler vs Direct asyncio.gather
```

至少比较：

- 直接 `asyncio.gather`：简单，但没有 ownership、retry、状态、恢复边界。
- 状态机 Scheduler：复杂，但可测试、可审计、可恢复。
- 同步 Core：状态正确性不依赖 event loop。
- async Core：更贴近 async Worker，但当前仓库会引入更多 event loop 复杂度。

推荐结论：

```text
Day3 选择同步 Scheduler Core + threading.Lock + deque。
未来 async Worker execution 作为外层 adapter。
```

### Benchmark Plan

Day3 benchmark 只测 Scheduler 操作成本：

```text
schedule_latency_ms
claim_throughput_ops_per_sec
contention_failure_rate
queue_depth
task_count
worker_count
```

测试规模：

```text
100 / 500 / 1000 tasks
1 / 4 / 8 / 16 workers
low contention / high contention
```

Recovery Latency 必须标记：

```text
DEFERRED / NOT_RUN
```

原因：Worker crash、heartbeat、lost task recovery 是 Day5 之后的能力。

### Ablation Plan

| Ablation | 预期风险 |
|---|---|
| 移除 `CLAIMED` | ready task 可能被重复执行 |
| 移除 lock | 并发 claim 出现重复 owner |
| 移除 queued set | schedule 重复入队 |
| 不校验 owner | 非 owner complete/fail |
| 不限制 max_attempts | retry loop 无限消耗 |

### Failure Cases

至少记录：

- Duplicate claim。
- Duplicate enqueue。
- Non-owner completion。
- Worker busy claim。
- Retry loop。
- Partial ownership write。

---

## 13. Interview Focus

可以这样回答：

> 我没有把多个 Worker 简单丢进 `asyncio.gather`，因为 coding task 有依赖、owner、失败和 retry。我的设计是：Lead 生成 `WorkerAssignment`，Day2 转成 `TaskDAG`，Day3 Scheduler 从 DAG 查询 dependency-ready 的节点，并用同步状态机完成 `READY -> CLAIMED -> RUNNING -> COMPLETED/FAILED`。claim 在一个锁内同时检查 Worker role、availability、当前 task status、queue membership，并写入唯一 owner，所以两个 Worker 竞争同一任务时只有一个成功。这个设计目前只保证单进程线程级原子性，不声称分布式调度；Worker crash、heartbeat 和 durable recovery 留给后续天实现。

面试追问时要能答：

- 为什么需要 `CLAIMED`？
- 为什么 `PENDING -> COMPLETED` 非法？
- 为什么 role compatibility 不等于权限？
- 为什么 `WorkerAssignment` 不能保存 owner？
- 为什么同步 Scheduler Core 比直接 async queue 更适合第一版？
- 如果两个线程同时 claim，线性化点在哪里？
- Day3 的原子性边界是什么，不能证明什么？

---

## 14. 今日完成标准

### 教程完成标准

- 已说明 Scheduler 在 Lead / DAG / Worker 之间的位置。
- 已统一 Day3 正式状态词表。
- 已给出合法状态图和转移表。
- 已说明 `replace_task_status()` 为什么不足以支撑 Scheduler。
- 已比较 async queue 与同步 Scheduler Core。
- 已明确 Worker identity / role / availability 边界。
- 已选择独立 runtime ownership，不污染 `WorkerAssignment`。
- 已给出并发 claim 时序和测试策略。

### 生产代码待实现标准

进入实现时应新增：

```text
codeteam/agent_team/scheduler.py
```

并按需修改：

```text
codeteam/agent_team/dag.py
codeteam/agent_team/worker.py
codeteam/agent_team/__init__.py
codeteam/events.py
```

### 测试待实现标准

进入实现时应新增：

```text
tests/agent_team/test_scheduler.py
```

并补充 Worker identity/info 防御测试。

### 文档证据待实现标准

进入实现验收前应新增：

```text
docs/design_decisions/DD-W5-03.md
docs/benchmark/W5_SCHEDULER.md
docs/failure_cases/W5_SCHEDULER_FAILURE.md
```

### Day3 最终功能验收边界

Day3 最终应能证明：

- ready task 幂等入队。
- 原子 claim。
- 唯一 ownership。
- owner-only complete/fail。
- retry 有上限。
- Worker role 和 availability 被检查。
- 并发测试稳定通过。

Day3 不需要证明：

- Worker crash recovery。
- durable queue。
- distributed lock。
- mailbox。
- end-to-end Multi-Agent speedup。

---

## 15. Day3 实现证据记录

本轮实现已按上面的 Step0-Step9 落地：

- Step0：扩展现有 `codeteam.agent_team.dag.TaskStatus`，新增 `CLAIMED`，没有创建第二套状态词表。
- Step1：新增 `codeteam/agent_team/scheduler.py`，包含 `TaskRuntimeRecord`、`TaskClaim`、`SchedulerResult`、`TASK_TRANSITIONS` 和 Scheduler 领域异常。
- Step2：`WorkerAgent` 对输入 `AgentInfo` 和公开 `info` 返回做防御性快照；availability 由 Scheduler runtime state 维护。
- Step3：`TaskScheduler.schedule()` 幂等入队，使用 `queued_node_ids` 防止重复 enqueue。
- Step4：`TaskScheduler.claim()` 在 `threading.Lock` 内完成 status、owner、queue membership、worker availability 的一致更新。
- Step5：`start()`、`complete()`、`fail()` 都校验 owner；`complete()` 会触发 dependent 下一轮 schedule。
- Step6：`fail()` 支持 `max_attempts` 限制下的 retry，超限保持 `FAILED`。
- Step7：Scheduler 事件接入 `codeteam.events.AgentEventType`，未新增独立日志系统。
- Step8：新增 `tests/agent_team/test_scheduler.py`，覆盖并发 claim、状态机、ownership、retry、事件和半写入风险。
- Step9：新增 `DD-W5-03`、`W5_SCHEDULER_FAILURE`、`W5_SCHEDULER.md` 和 `benchmark_scheduler.py`。

当前边界仍然成立：

- 只证明进程内线程级原子 claim。
- 不证明跨进程/分布式调度。
- 不实现 Worker crash recovery、heartbeat、durable queue、Mailbox、Worktree ownership 或端到端 Multi-Agent 加速。
