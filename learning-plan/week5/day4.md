# Week5 Day 4：Mailbox 与 Agent Communication

今天进入 **Agent Team Runtime 的通信层设计**。

前面三天解决的问题：

| Day | 问题 | 模块 |
|-|-|-|
| Day1 | 为什么需要多个 Agent？ | Lead / Worker Architecture |
| Day2 | 任务如何组织？ | Task DAG |
| Day3 | 谁执行任务？ | Scheduler |


今天解决：

> **多个 Agent 之间如何可靠交换信息？**

最终形成：

```text
                    Lead Agent

                         |
                         |
                    Task DAG

                         |

                 Task Scheduler

                         |

        +----------------+----------------+

        |                |                |

    Backend Agent   Frontend Agent   Test Agent

        |                |                |

        +----------------+----------------+

                    Mailbox Layer
```

---

# 一、为什么 Agent Team 需要通信系统？

很多初级 Multi-Agent 设计：

认为：

```text
Agent A

完成任务

↓

Agent B
```

直接调用即可。

例如：

```python
worker_b.run(result_from_a)
```


这个设计在 Demo 中可以。


但是工业系统不行。


原因：

---

# 问题1：Agent 生命周期不同

例如：

Backend Agent：

```text
开始修改 API

↓

运行 20 分钟测试
```


Frontend Agent：

可能：

```text
5分钟完成
```


不能要求：

两个 Agent 同步等待。


---

# 问题2：Agent 可能失败


例如：

Backend Agent：

```
数据库迁移失败
```


需要通知：

- Lead Agent
- Test Agent


---

# 问题3：并发执行

Day3：

我们支持：

```text
Worker A

Worker B

Worker C
```

并发。


那么：

同步函数调用：

```python
A.call(B)
```

不适合。


---

# 问题4：需要历史记录


工业 Agent Runtime 需要知道：

> 为什么这个 Agent 做这个决定？


例如：

Reviewer：

发现：

```text
auth.py 存在安全问题
```


需要保存：

```json
{
"from":"reviewer",
"to":"lead",
"type":"finding",
"content":"JWT validation missing"
}
```


这就是：

# Mailbox

---

# 二、什么是 Mailbox？

Mailbox：

字面：

邮箱。


在 Agent Runtime：

表示：

> 每个 Agent 拥有独立消息队列，用于异步接收和发送消息。


结构：

```text
        Agent A

          |
          |
       send()

          |
          v

     +-----------+

     | Mailbox B |

     +-----------+

          |

       receive()

          |

        Agent B
```


---

# 三、工业界类似设计

---

# 1. Actor Model（重点）


Mailbox 最经典来源：

## Actor Model


例如：

Erlang、Akka。


Actor：

包含：

```
State

Behavior

Mailbox
```


一个 Actor：

不直接调用另一个 Actor。


而是：

发送 Message。


例如：

```text
Actor A

send(message)

↓

Actor B Mailbox

↓

Actor B process
```


Agent Team 本质非常接近 Actor System。


---

# 2. Ray Actor


Ray：

AI 分布式计算框架。


结构：

```
Driver

 |

Actor

 |

Mailbox
```


每个 Actor：

有：

- 状态
- 方法
- 生命周期


Multi-Agent Runtime 可以借鉴。


---

# 3. Kubernetes Event Architecture


Kubernetes：

不是组件互相调用。


例如：

Controller：

发现：

```
Pod Failed
```


发布 Event：

```
PodFailed
```


其他组件监听。


Agent Runtime：

也是：

Event Driven。


---

# 4. AutoGen


AutoGen Agent：

通信核心：

Message。


例如：

```
Planner

  |
  | message
  v

Coder

  |
  | message
  v

Reviewer
```


Agent 不共享全部 Context。


通过消息交换。


---

# 四、Event Driven Architecture

今天重点。


传统：

## Request-Response


例如：

HTTP：

```
Client

 |

Request

 |

Server

 |

Response
```


特点：

同步。


---

Agent Team：

更像：

## Event Driven


流程：

```
Agent A

产生 Event

      |

      v

Message Queue

      |

      v

Agent B
```


---

例如：

Backend Agent：

完成 API：

发送：

```json
{
"type":"TASK_COMPLETED",
"task":"backend-api",
"artifact":"commit abc123"
}
```


Test Agent：

收到：

开始测试。


---

# 五、Async Communication

为什么异步？


因为 Agent 是长任务。


例如：

代码修改：

20分钟。


如果同步：

```python
await backend.finish()
```


Lead：

一直阻塞。


---

异步：

```text
Lead:

发送任务

↓

继续管理其他 Agent


Backend:

完成后发送消息
```


---

# 六、AgentMessage 设计

今天实现：

```text
mailbox.py
```


核心：

```python
AgentMessage
```


---

推荐结构：

```python
@dataclass
class AgentMessage:

    id:str

    sender:str

    receiver:str

    message_type:str

    payload:dict

    timestamp:int

    correlation_id:str
```

---

解释：

## id

消息唯一 ID。


用于：

防重复。


---

## sender

发送者。


例如：

```
backend-agent
```


---

## receiver

接收者。


例如：

```
lead-agent
```


---

## message_type


消息类型。


例如：

```text
TASK_ASSIGN

TASK_PROGRESS

TASK_COMPLETED

TASK_FAILED

REQUEST_HELP
```


---

## payload


内容。


例如：

```json
{
"commit":"abc123",
"files":[
"auth.py"
]
}
```


---

## correlation_id


关联任务。


例如：

Task：

```
oauth-feature
```


所有消息：

共享：

```
oauth-feature
```


方便 tracing。


---

# 七、Mailbox 数据结构设计

---

## 方案1：每个 Agent 一个 Queue


推荐第一版。


结构：

```python
mailboxes = {

 "backend":
    asyncio.Queue(),

 "frontend":
    asyncio.Queue(),

 "test":
    asyncio.Queue()

}
```


---

# 八、Mailbox API

---

## 1. send()


发送消息。


接口：

```python
send(
 message:AgentMessage
)
```


流程：

```
Sender

 |

MailboxManager

 |

Receiver Queue

```


---

例：

```python
mailbox.send(
 AgentMessage(
   sender="backend",
   receiver="lead",
   type="TASK_COMPLETED"
 )
)
```


---

# 2. receive()


接收消息。


```python
msg =
mailbox.receive(
 "lead"
)
```


返回：

```json
{
"type":"TASK_COMPLETED"
}
```


---

# 3. broadcast()


广播。


例如：

Lead：

通知所有 Worker：


```
停止当前任务
```


调用：

```python
broadcast(
 message
)
```


结果：

```
backend mailbox

frontend mailbox

test mailbox
```


---

# 九、CodeTeam 架构设计

现在：

```text
codeteam/

agent_team/

    lead.py

    worker.py

    dag.py

    scheduler.py

    mailbox.py
```


完整：

```
             LeadAgent

                 |

          Task Scheduler

                 |

        -----------------

        |       |       |

      Worker Worker Worker


        \       |       /

             Mailbox

```

---

# 十、Agent 如何使用 Mailbox？

例如：

## Backend Worker


执行：

```
Implement API
```


完成：

发送：

```json
{
"type":
"TASK_COMPLETED",

"payload":
{
"commit":
"abc123"
}
}
```


---

Lead 收到：


更新：

```
Task Status

COMPLETED
```


然后：

Scheduler：

释放：

Test Task。


---

# 十一、消息可靠性设计

工业系统重点。


---

## 1. 消息顺序


问题：

发送：

```
A

B

C
```


接收：

必须：

```
A

B

C
```


解决：

Queue FIFO。


---

## 2. 消息丢失


问题：

Worker Crash：

消息怎么办？


例如：

```
Lead

发送任务

↓

Worker crash

↓

消息丢失
```


---

解决：

Persistent Mailbox。


保存：

```
messages/
    msg1.json
    msg2.json
```


或者：

数据库：

SQLite。


---

## 3. 消息重复


例如：

网络 retry：

收到两次：

```
TASK_COMPLETED
```


解决：

Message ID 去重。


例如：

```
processed_messages
```

保存：

已经处理过的 ID。


---

# 十二、Worker Crash 恢复


结合 Day3 Scheduler。


流程：


```
Worker

receive task


↓

execute


↓

crash
```


Heartbeat：

发现：

```
worker dead
```


Scheduler：

重新 claim。


Mailbox：

未确认消息：

重新发送。


---

这就是：

Delivery Guarantee。


---

# 十三、消息语义设计

工业系统常见：

---

## At-most-once


最多一次。


可能丢。


性能高。


---

## At-least-once


至少一次。


可能重复。


需要幂等。


---

## Exactly-once


精确一次。


很难。


---

Agent Runtime：

通常：

选择：

```
At-least-once

+

Message ID Deduplication
```


---

# 十四、测试设计

---

# Test1：消息顺序


发送：

```
M1

M2

M3
```


receive：

验证：

```
M1

M2

M3
```


---

# Test2：Broadcast


三个 Worker：

收到：

同一个消息。


---

# Test3：Worker Crash


模拟：

```
send

↓

worker crash

↓

restart

↓

recover message
```


---

# Test4：重复消息


发送：

相同：

message_id。


系统：

只处理一次。


---

# 十五、Benchmark

目标：

验证 Mailbox 性能。


---

测试：

10000 messages。


---

## 指标1：Throughput


公式：

```
messages / second
```


例如：

```
10000 / time
```


---

## 指标2：Latency


发送：

↓

接收


时间。


记录：

```
p50

p95

p99
```


---

## 指标3：Memory


消息堆积：

```
10000

50000

100000
```


观察。


---

输出：

```
docs/benchmark/W5_MAILBOX.md
```


---

# 十六、Design Decision

## DD-W5-04

标题：

```
Why Mailbox Instead of Direct Agent Calls
```


---

## Alternative 1

直接调用：

```python
agent_b.execute()
```


优点：

简单。


缺点：

- 强耦合
- 无异步
- 无恢复
- 难 tracing


---

## Alternative 2

Mailbox。


优势：

- 解耦
- 异步
- 支持失败恢复
- 支持事件追踪


---

## Decision

选择：

Mailbox。


原因：

Agent 是长期运行实体，不应该通过函数调用连接。


---

# 十七、Failure Cases

记录：

---

## F-W5-D4-01

Message Lost


原因：

Queue 非持久。


改进：

Event Log。


---

## F-W5-D4-02

Duplicate Message


原因：

Retry。


改进：

Message ID。


---

## F-W5-D4-03

Out-of-order Message


原因：

多个 Producer。


改进：

Sequence Number。


---

## F-W5-D4-04

Mailbox Overflow


原因：

Agent 消费慢。


改进：

Backpressure。


---

# 十八、今天产出

代码：

```
codeteam/

agent_team/

    mailbox.py
```


测试：

```
tests/

agent_team/

    test_mailbox.py
```


文档：

```
docs/design_decisions/DD-W5-04.md

docs/benchmark/W5_MAILBOX.md

docs/failure_cases/W5_MAILBOX.md
```


---

# 十九、面试表达

## Q：

> Multi-Agent 如何通信？为什么不用共享 Context？


回答：

> 在 CodeTeam 中，每个 Agent 拥有独立 Context 和执行环境，通过 Mailbox 进行异步消息通信。这样可以避免多个 Agent 共享上下文导致 Token 膨胀和状态污染，同时通过 Event Log 和 Message ID 支持消息追踪、恢复和去重。


---

## Q：

> Mailbox 和普通消息队列有什么区别？


回答：

> 普通消息队列解决任务分发，而 Agent Mailbox 还需要支持 Agent 生命周期管理，包括消息关联 Task、Agent 状态恢复、事件追踪以及 Agent 间协作协议，因此它更接近 Actor Model 中的 Mailbox。


---

完成今天后，CodeTeam Runtime 已经具备：

```text
Lead Agent
      |
Task DAG
      |
Scheduler
      |
Worker Pool
      |
Mailbox Communication
```

这已经接近工业级 Agent Orchestration Runtime 的核心骨架。

下一天进入：

# Day5：Agent Lifecycle、Heartbeat 与故障恢复

解决：

> Agent 挂了怎么办？任务如何恢复？Runtime 如何知道 Agent 还活着？

---

# Week5 Day4 实操教程：Mailbox 与 Agent Communication

## 0. 原计划与当前实现的校正

先把原计划和当前仓库对齐。Day4 的目标不是照搬上面 1614 行里的示例，而是在 Day1-Day3 已经落地的真实接口上，设计下一步可实现的 Mailbox。

1. 当前 `TaskScheduler` 是同步线程模型：`threading.Lock + deque + queued_node_ids`。所以 Day4 第一版 Mailbox 也选择进程内、线程安全的 `deque + Lock`，不直接引入 `asyncio` event loop。
2. “异步通信”在这里指生产者和消费者通过队列解耦：sender 把消息放入 recipient mailbox 后即可返回，recipient 之后自己 `receive()`。它不等于 API 必须写成 `async def`。
3. `AgentMessage` 是 Agent 间结构化消息，不是 `codeteam.schemas.messages.Message`。后者当前只有 `role/content/tool_calls/tool_call_id`，服务于 LLM 对话和工具调用。
4. `AgentMessage` 也不是 `AgentEvent`。`AgentEvent` 是已经发生事实的审计记录；`AgentMessage` 是待消费的通信载体。
5. Mailbox 消息不能绕过 `TaskScheduler.complete()` / `fail()` 的 ownership 和状态检查。Worker 可以发送 “我完成了” 消息，但真正改状态必须仍由 Scheduler API 执行。
6. Day4 不实现 heartbeat、worker crash recovery、ack/nack、retry、durable replay、SQLite mailbox 或 exactly-once。这些分别留给 Day5/Day6。
7. Day4 的诚实语义是：进程内、每收件箱按成功入队线性化顺序 FIFO、非持久化、destructive receive、at-most-once dequeue。多 producer 不承诺发送者墙钟全局顺序。

这几个校正非常关键：Mailbox 是通信层，不是 Scheduler，不是 Event Log，也不是 durable queue。

---

## 1. Today in the System

今天要解决的问题是：多个 Agent 有了任务、身份和 Scheduler ownership 之后，如何交换结构化信息。

Day1 解决了 “谁是 Lead/Worker”；Day2 解决了 “任务之间是什么依赖”；Day3 解决了 “哪个 Worker 可以原子 claim 哪个 node”。但是到 Day3 为止，Worker 完成一个任务后，除了直接调用 Python 函数，没有一个标准通信层可以表达：

- Worker 向 Lead 汇报进度。
- Reviewer 向 Backend Worker 发安全问题。
- Lead 给某个 Worker 发送补充指令。
- 一个 Worker 请求另一个 Worker 提供接口约定。

Mailbox 在系统中的位置：

```text
TaskSpec
  -> LeadAgent
  -> Plan + WorkerAssignment
  -> TaskDAG
  -> TaskScheduler
  -> WorkerAgent
  -> Mailbox
  -> AgentMessage
  -> recipient.receive()
```

更具体地说：

```text
Lead / Worker
     |
     | send(AgentMessage)
     v
MailboxRegistry + per-agent Inbox
     |
     | receive(agent_id)
     v
Lead / Worker consumes message
     |
     | if task state changes
     v
TaskScheduler.start/complete/fail()
```

没有 Mailbox 时，Agent Team 只能靠直接函数调用传递结果。直接调用的问题是强耦合、难审计、难排队、难处理消费者暂时不运行的情况。Mailbox 的价值是把 “发送消息” 和 “处理消息” 分开，让 Agent 通信成为可测试的 Runtime 能力。

---

## 2. 能力映射

Primary:

```text
Multi-Agent Orchestration
├── Mailbox
├── Agent Communication
├── Coordination Protocol
└── Observability
```

Secondary:

```text
Agent Runtime
├── Message Model
├── Queue Semantics
├── State Boundary
└── Failure Semantics
```

今天能证明的 Agent Runtime 工程能力：

- 能把 Agent 间通信建模成结构化消息，而不是自然语言字符串拼接。
- 能区分 message、event、task status、worker status 这些不同状态对象。
- 能设计线程安全、可审计、容量受控的进程内通信队列。
- 能明确 at-most-once、FIFO、broadcast atomicity 等通信语义。
- 能诚实说明当前不是 durable queue，也不是 exactly-once。

面试里这一块很有价值，因为它回答的是 Multi-Agent 系统真正困难的一层：多个长任务 Agent 之间如何协作而不污染彼此状态。

---

## 3. 理论

### 3.1 Mailbox 是什么

Mailbox 可以理解为每个 Agent 的 inbox：

```text
Agent A send(message, to=Agent B)
        |
        v
Mailbox[B].append(message)
        |
        v
Agent B receive()
```

Agent A 不直接调用 Agent B 的执行函数。Agent B 什么时候处理、怎么处理，由 Agent B 自己决定。

### 3.2 异步通信不等于 async/await

同步函数调用：

```text
A calls B
A waits for B
B returns result
```

Mailbox 通信：

```text
A sends message
A returns
B later receives message
```

这里的 “异步” 是行为语义，不是 Python API 形态。当前仓库的 Scheduler 是同步核心，所以第一版 Mailbox 也应该是同步 API：

```python
mailbox.send(message)
message = mailbox.receive("worker-backend-1")
```

未来如果 Worker execution 变成 async，可以在同步 Mailbox Core 外面包一层 async adapter，而不是一开始让核心状态依赖 event loop。

### 3.3 Message 和 Event 的区别

`AgentMessage`：

```text
待消费
可影响未来行为
进入 recipient inbox
receive() 后从队列移除
```

`AgentEvent`：

```text
已发生事实
用于审计和 replay
不会被某个 Agent 消费掉
不应该包含完整 payload/secret
```

例子：

```text
AgentMessage:
  "worker-backend-1 -> lead: task A implementation finished"

AgentEvent:
  "message msg-123 enqueued for lead"
```

### 3.4 Delivery 语义

Day4 第一版建议明确：

```text
in-process only
non-durable
per-recipient FIFO
destructive receive
at-most-once dequeue
bounded capacity
no silent drop
```

`at-most-once dequeue` 的意思是：`receive()` 成功返回一条消息后，它已经从 inbox 删除。如果消费者拿到消息后崩溃，Day4 不会自动恢复这条消息。这不是 bug，而是 Day4 明确的范围边界。

### 3.5 线性化点

线性化点就是并发操作在逻辑上 “生效” 的那一瞬间。

对 Mailbox：

```text
send()
  线性化点 = lock 内 append 到 recipient deque 成功

receive()
  线性化点 = lock 内 popleft 成功

broadcast()
  线性化点 = lock 内给所有 recipient append 成功
```

这让测试可以证明：并发 producer 下没有丢消息、没有重复 message_id、每个 recipient inbox 内保持成功入队顺序。

---

## 4. 当前代码审计

### 4.1 Day1 Lead / Worker

当前 `codeteam/agent_team/models.py` 已有：

```text
AgentRole:
  LEAD / BACKEND / FRONTEND / TEST / REVIEW / GENERAL

AgentStatus:
  CREATED / READY / BUSY / FAILED / STOPPED

AgentIdentity:
  agent_id / display_name

AgentInfo:
  identity / role / status / capabilities

WorkerAssignment:
  assignment_id / task_id / source_step_id / role / goal /
  expected_output / relevant_files / verification

LeadPlanningResult:
  task_id / plan / assignments
```

Day4 可以复用 `AgentIdentity.identity.agent_id` 作为 Mailbox 地址，但不能复用 `WorkerRegistry` 当地址簿。原因：Mailbox 需要 Lead 和 Worker 都能注册，而 `WorkerRegistry` 明确拒绝 `AgentRole.LEAD`。

当前 `WorkerAgent.info` 已返回防御性快照，这是 Day3 hardening 后的正确基础。Mailbox 注册 agent 地址时也应复制 identity，避免注册后外部对象突变破坏地址表。

### 4.2 Day2 TaskDAG

当前 `TaskDAG` 已明确：

```text
TaskNode.node_id 是 DAG 权威 ID。
from_lead_planning_result() 当前让 node_id = assignment_id。
source_step_id 是 Planner trace 字段，不是 DAG edge ID。
```

Day4 的 `AgentMessage.node_id` 应使用 Scheduler/DAG 的 `node_id`。因为当前 factory 映射为 `assignment_id`，所以很多消息里 `node_id` 会等于 `assignment_id`，但设计上不要把 `source_step_id` 当 Scheduler key。

### 4.3 Day3 TaskScheduler

当前 `TaskScheduler` 已有：

```text
TaskRuntimeRecord.status 是 runtime 状态权威。
TaskScheduler 构造时调用 TaskDAG.validate()。
TaskScheduler 只接受全 PENDING fresh DAG。
schedule() 幂等 enqueue。
claim() 在线程锁内写 status/owner/queue/worker availability。
complete()/fail() 校验 owner。
event_sink 在锁外投递，sink 异常不回滚状态。
```

Day4 必须继承这个边界：消息只表达通信事实，不能直接把 task 从 `RUNNING` 改成 `COMPLETED`。

### 4.4 Event Log

`codeteam/events.py` 目前已有 scheduler 相关事件：

```text
scheduler.task_scheduled
scheduler.task_claimed
scheduler.task_started
scheduler.task_completed
scheduler.task_failed
scheduler.task_retried
scheduler.task_blocked
scheduler.task_waiting_for_worker
scheduler.event_delivery_failed
```

Day4 应扩展同一个 `AgentEventType`，例如：

```text
mailbox.agent_registered
mailbox.message_sent
mailbox.message_received
mailbox.broadcast_sent
mailbox.delivery_failed
```

不要新增独立日志系统。

### 4.5 `codeteam.schemas.messages.Message`

当前定义是：

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
```

这服务于 LLM chat/tool call schema，不包含 sender、recipient、task_id、node_id、message_id、correlation_id 等 Agent Team 通信字段。Day4 不应修改它，也不应把它塞进 Mailbox。

### 4.6 Session

`codeteam/session/` 已有 durable session snapshot、JSONL event store、pause/resume/reconcile。它属于 Week4 Single-Agent durable state。Day4 第一版 Mailbox 是内存对象，不接入 Session，不做 durable replay。等 Day6 做 Team Task Store / durable queue 时，再考虑如何把 Mailbox projection 持久化。

### 4.7 当前缺失

当前仓库还没有：

```text
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
evals/week5/benchmark_mailbox.py
docs/design_decisions/DD-W5-04.md
docs/benchmark/W5_MAILBOX.md
docs/failure_cases/W5_MAILBOX_FAILURE.md
```

本轮只写教程，不创建这些文件。

---

## 5. 冲突表

| 原 Day4 计划 | 当前实现校正 |
|---|---|
| 用 `asyncio.Queue()` 做 mailbox | 当前 Scheduler 是同步线程模型，第一版用 `deque + threading.Lock`。 |
| `AgentMessage` 用 `dataclass` 且字段较松 | 当前模型体系大量使用 Pydantic `BaseModel`，建议用 `BaseModel` + validator。 |
| `sender/receiver/type` 字段名 | 建议明确为 `sender_id/recipient_id/message_type`。 |
| Worker crash 测试 | Day5/Day6 范围，Day4 只记录 DEFERRED。 |
| Persistent Mailbox / SQLite | Day6 范围，Day4 只做 non-durable in-memory。 |
| Broadcast 类似“一条消息给多人” | 第一版应为每个 recipient 生成独立 `message_id`，共享 `correlation_id`。 |
| Message 可直接表示完成任务 | Message 可以报告完成，但状态推进仍必须走 Scheduler ownership API。 |
| FIFO 简单等同全局顺序 | 只承诺每个 recipient inbox 内成功入队顺序；多 producer 不承诺墙钟全局顺序。 |

---

## 6. 范围 / 非目标

Day4 做：

```text
AgentMessageType
AgentMessage
Mailbox 领域异常
MailboxRegistry / AgentMailbox
register_agent()
send()
receive()
broadcast()
安全审计事件
线程安全和容量控制
防御性快照
测试与 benchmark 计划
DD / Ablation / Failure 计划
```

Day4 不做：

```text
heartbeat
worker crash recovery
ack / nack
message retry
durable replay
SQLite mailbox
exactly-once
cross-process queue
distributed pub-sub
Worker execution loop
Scheduler state bypass
```

一句话边界：

> Day4 证明进程内 Agent 通信模型正确，不证明崩溃后消息可恢复。

---

## 7. 数据模型

### 7.1 AgentMessageType

建议使用 Enum，而不是 magic string：

```python
class AgentMessageType(str, Enum):
    TASK_ASSIGNED = "task_assigned"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    REVIEW_FINDING = "review_finding"
    REQUEST_HELP = "request_help"
    INFO = "info"
    SHUTDOWN_REQUESTED = "shutdown_requested"
```

为什么用 Enum：

- 拼写错误会被 Pydantic 校验拦住。
- 测试可以明确断言类型。
- 后续 event data 可以统一记录 `message_type.value`。

### 7.2 AgentMessage

建议用 Pydantic `BaseModel`：

```python
class AgentMessage(BaseModel):
    message_id: str
    sender_id: str
    recipient_id: str
    message_type: AgentMessageType
    task_id: str
    node_id: str | None = None
    correlation_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
```

字段语义：

```text
message_id
  消息唯一 ID，用于去重。

sender_id
  发送方 AgentIdentity.agent_id。

recipient_id
  接收方 AgentIdentity.agent_id。

message_type
  结构化消息类型。

task_id
  用户任务 ID。

node_id
  Scheduler/DAG 权威 node_id，当前通常等于 assignment_id。

correlation_id
  一组相关消息的 trace ID。broadcast 中多个独立 message_id 共享它。

payload
  业务内容，但不进入审计事件。

created_at
  创建时间。第一版可用 time.time()，未来如持久化再考虑 timezone-aware datetime。
```

校验建议：

```text
message_id / sender_id / recipient_id / task_id / correlation_id 非空。
sender_id 可以等于 recipient_id 吗？
  第一版建议允许，用于 self-note 或 loopback 测试。

payload 必须是 dict。
  Pydantic 会校验外层类型；内部值建议保持 JSON-like。
```

### 7.3 ID namespace

Day4 继续保持四类 ID 分离：

```text
agent_id
  AgentIdentity.identity.agent_id，Mailbox address。

task_id
  用户任务 ID，跨 Lead/Plan/DAG/Scheduler/Mailbox。

node_id
  DAG/Scheduler runtime key，当前 factory 映射为 assignment_id。

source_step_id
  Planner trace 字段，不是 Mailbox routing key，不是 Scheduler key。
```

不要写这种代码：

```python
message = AgentMessage(node_id=assignment.source_step_id, ...)
```

正确思路是：

```text
WorkerAssignment.assignment_id -> TaskNode.node_id -> AgentMessage.node_id
WorkerAssignment.source_step_id -> 只用于 trace/display
```

---

## 8. API 契约

### 8.1 领域异常

建议在 `mailbox.py` 定义：

```python
class MailboxError(Exception): ...
class UnknownAgentError(MailboxError): ...
class DuplicateAgentError(MailboxError): ...
class DuplicateMessageError(MailboxError): ...
class MailboxFullError(MailboxError): ...
class InvalidMessageError(MailboxError): ...
```

### 8.2 地址注册

Mailbox 要有独立注册地址：

```python
mailbox.register_agent(identity: AgentIdentity) -> None
```

为什么不用 `WorkerRegistry`：

- Lead 也需要 inbox。
- WorkerRegistry 的职责是 role compatibility，不是通信地址簿。
- `AgentStatus.BUSY` 不应影响收件能力。Busy Worker 也可以收到 Lead 的取消、提示或 review finding。

注册时建议保存 `AgentIdentity` 的 deep copy。公开查询时也返回 copy。

### 8.3 send()

接口骨架：

```python
def send(self, message: AgentMessage) -> AgentMessage:
    ...
```

契约：

```text
校验 sender 已注册。
校验 recipient 已注册。
校验 message_id 未出现过。
校验 recipient inbox 未超过容量。
成功后在 lock 内 append。
返回 AgentMessage 防御性快照。
失败不产生半写入。
```

容量语义：

```text
capacity 是每个 inbox 的最大积压消息数。
满了抛 MailboxFullError。
禁止静默丢弃。
```

### 8.4 receive()

接口骨架：

```python
def receive(self, agent_id: str) -> AgentMessage | None:
    ...
```

契约：

```text
校验 agent_id 已注册。
非阻塞。
空队列返回 None。
成功则 popleft，并从 inbox 删除。
返回防御性快照。
```

注意：Day4 是 destructive receive。消息被取出后，如果消费者崩溃，内存 Mailbox 不会自动恢复。

### 8.5 broadcast()

接口骨架：

```python
def broadcast(
    self,
    *,
    sender_id: str,
    recipient_ids: tuple[str, ...],
    message_type: AgentMessageType,
    task_id: str,
    node_id: str | None = None,
    payload: dict[str, object] | None = None,
    correlation_id: str | None = None,
) -> tuple[AgentMessage, ...]:
    ...
```

推荐契约：

```text
recipient_ids 必须显式传入。
不提供 topic/pub-sub。
每个 recipient 生成独立 message_id。
所有消息共享 correlation_id。
同一把锁内先预检 sender、所有 recipient、所有容量。
预检通过后再全部 append。
如果任何一个 recipient 不存在或容量不足，整体失败，任何 inbox 都不写入。
```

为什么 all-or-nothing：

如果广播到 3 个 Worker，第 1 个成功、第 2 个满了、第 3 个没收到，那么 Lead 以为 “大家都知道”，实际团队状态已经分裂。第一版用同一锁内预检和写入，避免部分广播。

### 8.6 审计事件

Day4 继续复用 `codeteam.events.AgentEventType`。建议事件：

```text
MAILBOX_AGENT_REGISTERED = "mailbox.agent_registered"
MAILBOX_MESSAGE_SENT = "mailbox.message_sent"
MAILBOX_MESSAGE_RECEIVED = "mailbox.message_received"
MAILBOX_BROADCAST_SENT = "mailbox.broadcast_sent"
MAILBOX_EVENT_DELIVERY_FAILED = "mailbox.event_delivery_failed"
```

事件 data 只记录安全 metadata：

```text
message_id
sender_id
recipient_id
message_type
task_id
node_id
queue_size
reason_code
correlation_id
recipient_count
failed_event_type
error_type
```

不要记录完整 `payload`，因为 payload 未来可能包含代码片段、日志、测试输出、用户内容，甚至 secret。

事件事务边界参考 Day3 Scheduler：

```text
lock 内：
  更新 inbox / message_id set / queue size
  追加内部 AgentEvent
  准备待投递事件副本

lock 外：
  调用 event_sink
  sink 普通 Exception 被隔离
  记录 delivery_failed，不回滚成功 send/receive
```

---

## 9. 并发与线性化点

第一版建议内部结构：

```python
class AgentMailbox:
    def __init__(self, *, capacity_per_inbox: int, event_sink: EventSink | None = None):
        self._lock = Lock()
        self._agents: dict[str, AgentIdentity] = {}
        self._inboxes: dict[str, deque[AgentMessage]] = {}
        self._seen_message_ids: set[str] = set()
        self._events: list[AgentEvent] = []
```

线性化点：

| API | 线性化点 | 失败时状态 |
|---|---|---|
| `register_agent()` | lock 内创建 `_agents[id]` 和 `_inboxes[id]` | 重复 id 不覆盖 |
| `send()` | lock 内 append 到 recipient deque | 未知/重复/满时不写入 |
| `receive()` | lock 内 popleft | 空队列无副作用 |
| `broadcast()` | lock 内所有 recipient append 完成 | 任一预检失败则全不写 |

两个 producer 并发发给同一个 recipient：

```text
Producer A                    Producer B
    |                              |
    | send(M1)                     | send(M2)
    | acquire lock                 |
    | append M1                    |
    | release lock                 |
                                   | acquire lock
                                   | append M2
                                   | release lock

recipient receive -> M1, then M2
```

如果 B 先拿到锁，那顺序就是 M2, M1。Mailbox 承诺的是 “成功入队线性化顺序 FIFO”，不是 “墙钟上谁先创建消息谁先收到”。

广播原子性：

```text
broadcast to A/B/C
  acquire lock
  precheck A/B/C exist
  precheck A/B/C capacity
  append A message
  append B message
  append C message
  release lock
```

不要写成：

```python
for recipient in recipients:
    self.send(message_for(recipient))
```

因为这样第 2 个失败时第 1 个已经收到，破坏 all-or-nothing。

---

## 10. 数据流

### 10.1 Worker 汇报完成

```text
Worker executes claimed node
        |
        | send AgentMessage(TASK_COMPLETED)
        v
Lead inbox
        |
        | receive()
        v
Lead checks message
        |
        | calls TaskScheduler.complete(node_id, owner_id)
        v
Scheduler validates owner + status
        |
        v
COMPLETED, dependents may become READY
```

注意：消息本身不完成任务。它只是触发 Lead 或 runtime 调用 Scheduler。

### 10.2 Review finding

```text
Review Worker
  -> AgentMessage(REVIEW_FINDING, recipient_id="worker-backend-1")
  -> Backend inbox
  -> Backend receives finding
  -> Backend decides patch/follow-up
```

### 10.3 Broadcast stop request

```text
Lead
  -> broadcast(SHUTDOWN_REQUESTED, recipients=(backend, frontend, test))
  -> each inbox receives one unique message_id
  -> all messages share one correlation_id
```

---

## 11. 分步教学

### Step0：冻结 Day4 语义边界

目标：写清楚 Mailbox 的 delivery guarantee。

原因：如果一开始说不清 at-most-once、FIFO、durability，后面测试会乱。

涉及文件：

```text
learning-plan/week5/day4.md
docs/design_decisions/DD-W5-04.md
```

Python 知识：无复杂语法，主要是工程契约。

接口骨架：

```text
in-process
non-durable
per-inbox FIFO
destructive receive
bounded capacity
event sink best-effort
```

验证方式：先写测试名，不急着实现。

常见错误：把 Mailbox 说成 exactly-once。

完成标志：你能一句话解释 Day4 Mailbox 会丢什么、不会丢什么。

### Step1：定义 AgentMessageType 与 AgentMessage

目标：建立结构化消息模型。

原因：消息不能是裸 dict，否则字段、类型、ID namespace 全靠约定。

涉及文件：

```text
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
```

Python 知识：

- `Enum`：固定消息类型。
- `BaseModel`：字段校验与 JSON 序列化。
- `Field(default_factory=...)`：每条消息独立默认值。

接口骨架：

```python
class AgentMessageType(str, Enum):
    TASK_COMPLETED = "task_completed"


class AgentMessage(BaseModel):
    message_id: str
    sender_id: str
    recipient_id: str
    message_type: AgentMessageType
    task_id: str
    node_id: str | None = None
    correlation_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
```

验证方式：模型 round-trip、空 ID 拒绝、非法 message_type 拒绝、payload snapshot。

常见错误：用 mutable `{}` 当默认值。

完成标志：模型能表达点对点任务消息，并能 JSON round-trip。

### Step2：定义 Mailbox 异常与地址簿

目标：明确 unknown/duplicate/full 等失败类型。

原因：Agent Runtime 需要可诊断失败，不能只抛 `ValueError`。

涉及文件：

```text
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
```

Python 知识：

- 自定义异常类。
- `dict[str, AgentIdentity]`。
- 防御性 `model_copy(deep=True)`。

接口骨架：

```python
class MailboxError(Exception): ...
class UnknownAgentError(MailboxError): ...
class DuplicateAgentError(MailboxError): ...


def register_agent(self, identity: AgentIdentity) -> AgentIdentity:
    ...
```

验证方式：注册 Lead 和 Worker；重复 agent_id 抛错且不覆盖；未知 agent receive 抛错。

常见错误：直接复用 `WorkerRegistry`，导致 Lead 没法注册。

完成标志：Mailbox 有自己的地址簿，Lead/Worker 都能注册。

### Step3：实现 send()

目标：把消息安全放入 recipient inbox。

原因：这是通信层最小闭环。

涉及文件：

```text
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
```

Python 知识：

- `threading.Lock`。
- `collections.deque`。
- `with self._lock:` 上下文管理器。

伪代码：

```python
def send(self, message: AgentMessage) -> AgentMessage:
    pending_events = []
    with self._lock:
        self._require_agent(message.sender_id)
        self._require_agent(message.recipient_id)
        self._require_new_message_id(message.message_id)
        self._require_capacity(message.recipient_id)
        snapshot = message.model_copy(deep=True)
        self._inboxes[message.recipient_id].append(snapshot)
        self._seen_message_ids.add(message.message_id)
        self._record_event_locked(pending_events, ...)
        result = snapshot.model_copy(deep=True)
    self._deliver_events(pending_events)
    return result
```

验证方式：点对点发送后 recipient 收件箱 size 增加；返回值 mutation 不影响内部。

常见错误：event_sink 在锁内调用。

完成标志：send 成功、失败都无半写入。

### Step4：实现 receive()

目标：非阻塞消费一条消息。

原因：Worker/Lead 需要轮询自己的 inbox。

涉及文件：

```text
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
```

Python 知识：

- `deque.popleft()`。
- `None` 返回值。
- 防御性复制。

伪代码：

```python
def receive(self, agent_id: str) -> AgentMessage | None:
    pending_events = []
    with self._lock:
        self._require_agent(agent_id)
        if not self._inboxes[agent_id]:
            return None
        message = self._inboxes[agent_id].popleft()
        self._record_event_locked(pending_events, ...)
        result = message.model_copy(deep=True)
    self._deliver_events(pending_events)
    return result
```

验证方式：空 inbox 返回 None；发送 M1/M2/M3 后 receive 顺序一致；收到后再次 receive 不返回同一条。

常见错误：把 receive 写成阻塞等待，导致测试和 Agent loop 卡住。

完成标志：非阻塞 destructive FIFO receive。

### Step5：实现容量与重复 message_id

目标：限制 inbox backlog，降低慢消费者导致的瞬时积压，并防止重复消息污染。

原因：Agent 输出可能很大，慢消费者会导致积压。

涉及文件：

```text
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
```

Python 知识：

- `set[str]` 去重。
- 容量判断。

验证方式：

```text
capacity=1
send M1 success
send M2 -> MailboxFullError
receive M1
send M2 success

send M1 twice -> DuplicateMessageError
```

常见错误：满了就丢旧消息或新消息，但不报错。

完成标志：容量满和重复 ID 都 fail closed。

### Step6：实现 broadcast()

目标：给多个明确 recipient 发送相关消息。

原因：Lead 需要通知一组 Worker，但 Day4 不做 topic/pub-sub。

涉及文件：

```text
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
```

Python 知识：

- tuple 遍历。
- UUID 生成。
- all-or-nothing 事务思维。

伪代码：

```python
def broadcast(..., recipient_ids: tuple[str, ...]) -> tuple[AgentMessage, ...]:
    pending_events = []
    with self._lock:
        self._precheck_sender_and_all_recipients(...)
        self._precheck_all_capacity(...)
        messages = tuple(self._new_message_for(recipient) for recipient in recipient_ids)
        for message in messages:
            self._inboxes[message.recipient_id].append(message)
            self._seen_message_ids.add(message.message_id)
        self._record_event_locked(pending_events, ...)
        result = tuple(message.model_copy(deep=True) for message in messages)
    self._deliver_events(pending_events)
    return result
```

验证方式：3 个 recipients 都收到；任一 unknown/full 时无人收到；每条 message_id 不同，correlation_id 相同。

常见错误：循环调用 `send()` 造成部分广播。

完成标志：broadcast 原子性被测试覆盖。

### Step7：接入 Event Log

目标：让通信行为可审计。

原因：Day5/Day6 的恢复和排障要知道哪些消息曾经入队/出队。

涉及文件：

```text
codeteam/events.py
codeteam/agent_team/mailbox.py
tests/agent_team/test_mailbox.py
```

Python 知识：

- `Callable[[AgentEvent], None]`。
- `try/except Exception` 隔离 observer 普通异常。

验证方式：

- sent/received/broadcast 都产生事件。
- event data 不包含 payload。
- sink 可重入读取 mailbox state，不死锁。
- sink 抛 RuntimeError 不回滚已成功 send。

常见错误：把完整 payload 放进 event data。

完成标志：事件安全字段与 sink 隔离都有测试。

### Step8：公共 API 导出

目标：让 Day4 对象从 `codeteam.agent_team` 统一导入。

原因：Day1-Day3 都把公共对象导出到 `__init__.py`。

涉及文件：

```text
codeteam/agent_team/__init__.py
tests/agent_team/test_mailbox.py
```

接口骨架：

```python
from codeteam.agent_team.mailbox import (
    AgentMailbox,
    AgentMessage,
    AgentMessageType,
    MailboxError,
)
```

验证方式：测试从 `codeteam.agent_team` import 公共对象。

常见错误：只实现模块，忘记公共 API。

完成标志：API 导出测试通过。

### Step9：测试、DD、Benchmark、Ablation、Failure

目标：形成完整工程证据。

原因：这是学习项目，不只是写功能。

涉及文件：

```text
tests/agent_team/test_mailbox.py
docs/design_decisions/DD-W5-04.md
docs/benchmark/W5_MAILBOX.md
docs/failure_cases/W5_MAILBOX_FAILURE.md
evals/week5/benchmark_mailbox.py
```

验证方式：

```bash
.venv/bin/python -m ruff check codeteam/agent_team tests/agent_team evals/week5/benchmark_mailbox.py
.venv/bin/python -m pytest tests/agent_team/test_mailbox.py -q
.venv/bin/python evals/week5/benchmark_mailbox.py
```

常见错误：Benchmark 没跑就写结论。

完成标志：测试通过，DD/Benchmark/Failure 文档可追踪。

---

## 12. 测试策略

Day4 测试地图至少覆盖：

### 模型校验

- `AgentMessage` JSON round-trip。
- 空 `message_id/sender_id/recipient_id/task_id/correlation_id` 拒绝。
- 非法 `message_type` 被 Pydantic 拒绝。
- `payload` 默认值每条消息独立。

证明：消息模型不是裸 dict。

### 地址簿

- Lead 和 Worker 都能注册。
- 重复地址抛 `DuplicateAgentError`，不覆盖旧 identity。
- 未知 sender 不能 send。
- 未知 recipient 不能 send。
- 未知 agent 不能 receive。

证明：Mailbox 独立于 WorkerRegistry。

### 点对点收发

- A 发给 B，B receive 到同一业务消息。
- A 发给 B，C 收不到。
- 空 inbox 返回 None。

证明：routing 正确且 receive 非阻塞。

### FIFO

- 同一 sender 连续发送 M1/M2/M3 给同一 recipient。
- receive 顺序为 M1/M2/M3。

证明：每收件箱 FIFO。

### 重复 message_id

- 第二次发送同一 message_id 抛 `DuplicateMessageError`。
- 失败后 inbox 不增加。

证明：去重 fail closed。

### 防御性副本

- send 后修改原始 message.payload，不影响 inbox。
- receive 返回后修改 payload，不影响内部 event。
- events 返回后修改 data，不污染内部。

证明：外部引用不能破坏 Mailbox 状态。

### 容量满

- `capacity_per_inbox=1`。
- 第 2 条发送给同一 recipient 抛 `MailboxFullError`。
- receive 后容量释放，可以再 send。

证明：不会静默丢弃，不会无限增长。

### Broadcast 原子性

- 多 recipient 都收到独立 message_id。
- correlation_id 相同。
- 任一 recipient unknown 时，所有 inbox 都不写。
- 任一 recipient full 时，所有 inbox 都不写。

证明：没有部分广播。

### 并发生产者

- 多线程 producer 同时发送不同 message_id。
- 使用 `Barrier` 同步起跑。
- join 使用 timeout。
- 最终消息数等于发送数，无重复、无丢失。

证明：lock 保护 send 线性化点。

### 审计字段安全

- `mailbox.message_sent` 不包含 payload。
- 只包含 `message_id/sender_id/recipient_id/message_type/task_id/node_id/queue_size/reason_code/correlation_id` 等 metadata。

证明：observability 不泄露业务 payload。

### sink 重入和异常隔离

- sink 内读取 `mailbox.events` 或 `queue_size()` 不死锁。
- sink 抛 `RuntimeError` 不回滚已成功入队/出队。
- delivery failure event 不递归投递给同一个失败 sink。

证明：复用 Day3 事件事务边界。

### Deferred

这些测试本日不写成通过项：

```text
worker crash 后消息恢复
ack/nack
durable replay
SQLite mailbox
exactly-once
cross-process producers
```

只在 Failure Cases 中记录当前内存实现的失败边界。

---

## 13. Design Decision

计划创建：

```text
docs/design_decisions/DD-W5-04.md
```

标题建议：

```text
DD-W5-04: In-Process Mailbox Instead of Direct Agent Calls
```

必须比较：

### A. Direct Agent Calls

优点：

- 简单。
- 调试直观。

缺点：

- sender 和 receiver 强耦合。
- 难排队。
- 难审计。
- receiver 不运行时无法自然表达待处理消息。

### B. In-Memory deque + Lock Mailbox

优点：

- 和 Day3 同步 Scheduler 一致。
- 易测试。
- 无新增依赖。
- 可以证明 FIFO、容量、原子 broadcast。

缺点：

- 进程崩溃后消息丢失。
- 不支持跨进程。
- 没有 ack/retry。

### C. asyncio.Queue

优点：

- 适合 async worker loop。
- 可自然 await。

缺点：

- 当前核心 API 是同步。
- 会把 event loop ownership 引入核心状态。
- 仍要额外处理地址簿、去重、event sink 和 broadcast 原子性。

### D. SQLite / Durable Queue

优点：

- 支持 crash recovery。
- 支持 replay 和 resume。

缺点：

- 实现复杂。
- 需要事务和 migration。
- Day4 过早，会混入 Day6 持久化问题。

Decision：

```text
Day4 选择进程内 deque + Lock Mailbox。
```

Hypothesis：

```text
它足以证明进程内 Agent communication correctness，并保持与 Day3 Scheduler 同步核心一致。
```

需要 Benchmark 验证：

```text
setup cost
send latency
receive latency
broadcast fan-out latency
throughput under producer contention
memory under backlog
```

---

## 14. Benchmark

计划文件：

```text
evals/week5/benchmark_mailbox.py
docs/benchmark/W5_MAILBOX.md
```

Benchmark 问题：

```text
在进程内实现下，Mailbox 的 send/receive/broadcast 热路径成本是多少？
并发 producer 是否带来明显 lock contention？
队列积压时内存如何增长？
```

必须区分：

```text
setup latency
send hot path latency
receive hot path latency
broadcast fan-out latency
```

工作负载：

```text
messages: 100 / 1000 / 10000
producers: 1 / 4 / 8
broadcast fan-out: 1 / 4 / 16 / 64
payload sizes: small metadata, medium JSON-like payload
```

指标：

```text
p50_ms
p95_ms
throughput_messages_per_second
broadcast_messages_per_second
max_backlog_messages
approx_memory_bytes
contention_error_count
```

复现性记录：

```text
HEAD
dirty status
Python version
OS
random seed
warmup runs
measured runs >= 30
mailbox.py SHA-256
benchmark_mailbox.py SHA-256
```

报告必须写明：

```text
这些数据只证明 Mailbox 本地操作成本。
不证明 Multi-Agent 端到端加速。
不证明 crash recovery。
不证明 exactly-once。
```

---

## 15. Ablation

计划：

```text
DD-W5-04 对应 ablation 先标记 PLANNED / NOT_RUN。
```

可做的 ablation：

### A. Mailbox vs Direct Function Call

Full：

```text
Worker -> Mailbox -> Lead receive -> Scheduler complete
```

Ablated：

```text
Worker directly calls Lead/Scheduler helper
```

比较：

```text
coupling
audit event coverage
ability to queue while receiver idle
testability
latency overhead
```

### B. Bounded Queue vs Unbounded Queue

Full：

```text
capacity_per_inbox + MailboxFullError
```

Ablated：

```text
unbounded deque
```

比较：

```text
memory growth
failure diagnosability
producer backpressure
```

### C. Atomic Broadcast vs Loop send()

Full：

```text
precheck all recipients/capacity, then append all
```

Ablated：

```text
for recipient: send()
```

比较：

```text
partial broadcast frequency
state consistency
failure recovery cost
```

当前不运行 ablation，因为生产实现还不存在。本轮只规划。

---

## 16. Failure Cases

计划文件：

```text
docs/failure_cases/W5_MAILBOX_FAILURE.md
```

至少记录：

### F-W5-D4-01 Unknown Sender / Recipient

输入：未注册 agent 发送或接收。

期望：抛 `UnknownAgentError`，不写入任何 inbox。

### F-W5-D4-02 Duplicate Message ID

输入：重复发送同一 `message_id`。

期望：抛 `DuplicateMessageError`，不覆盖、不重复入队。

### F-W5-D4-03 Mailbox Overflow

输入：recipient inbox 达到容量。

期望：抛 `MailboxFullError`，禁止静默丢弃。

### F-W5-D4-04 Partial Broadcast

输入：广播给 A/B/C，其中 B 不存在或已满。

期望：A/B/C 都不收到新消息。

### F-W5-D4-05 Payload Mutation Leak

输入：发送后修改原始 payload，或 receive 后修改返回消息。

期望：内部状态和 events 不变。

### F-W5-D4-06 Event Sink Deadlock

输入：sink 内读取 `mailbox.events`。

期望：不死锁，因为 sink 在锁外调用。

### F-W5-D4-07 Event Sink Exception

输入：sink 抛普通异常。

期望：send/receive 成功结果仍返回，内部记录 delivery_failed。

### F-W5-D4-08 Worker Crash Message Loss

输入：receive 成功后 worker crash。

期望：Day4 标记 known limitation。当前内存 destructive receive 无法恢复，Day5/Day6 处理。

---

## 17. 工业对照

这里只使用官方公开资料，并严格区分事实、推断和 CodeTeam 选择。

### Claude Code Agent Teams

官方事实：

- Claude Code 官方 Agent Teams 文档说明，agent team 由 team lead、teammates、task list、Mailbox 组成。
- Teammates 是独立 Claude Code sessions，各自有 context window。
- Teammates 可以彼此直接 message。
- Shared task list 支持 pending / in progress / completed，以及 dependencies；claim 使用 file locking 防 race。

来源：

- https://code.claude.com/docs/en/agent-teams
- https://code.claude.com/docs/en/agents

工程推断：

- 公开的 Mailbox 说明支持 Agent 间直接通信，但不等于我们知道其内部存储、delivery guarantee、锁粒度或恢复机制。
- Shared task list 和 Mailbox 是两个概念：一个管理 work items，一个传递 communication。

CodeTeam 选择：

- Day4 只复刻公开概念层的 “Mailbox as communication layer”，不声称复刻 Claude Code 内部实现。
- CodeTeam 的任务状态仍由 `TaskScheduler` 管，Mailbox 只传递 `AgentMessage`。

### AutoGen

官方事实：

- AutoGen Core 说明 agent 通过 messages 通信，messages 是可序列化对象，可以用 Pydantic `BaseModel` 或 dataclass。
- AutoGen 直接区分 Direct Messaging 和 Broadcast/topic pub-sub。
- AutoGen 文档明确 messages 是纯数据，不应包含逻辑。

来源：

- https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/message-and-communication.html
- https://microsoft.github.io/autogen/0.4.6/user-guide/core-user-guide/core-concepts/topic-and-subscription.html

工程推断：

- CodeTeam 的 `AgentMessage` 应保持纯数据，不把执行函数、回调、Scheduler mutation 放进 message。
- Direct messaging 和 topic pub-sub 是不同层次；Day4 选择显式 recipient broadcast，而不做 topic subscription。

CodeTeam 选择：

- 第一版用 Pydantic `BaseModel` 定义 message。
- broadcast 接收显式 `recipient_ids`，不做 topic/subscription registry。

### Ray Actor

官方事实：

- Ray Actor 是 stateful worker/service。
- Ray 文档说明同一 actor 的任务顺序存在条件限制；同一 submitter 到同步单线程 actor 可保持提交顺序，但不同 submitter、async/threaded actor 或 retry 下不保证简单全局顺序。

来源：

- https://docs.ray.io/en/latest/ray-core/actors.html
- https://docs.ray.io/en/latest/ray-core/actors/task-orders.html

工程推断：

- “有队列” 不自动意味着多 producer 全局墙钟顺序。
- CodeTeam 应清楚定义 per-inbox FIFO 的线性化顺序，而不是承诺不可证明的全局顺序。

CodeTeam 选择：

- 每个 recipient inbox 按成功 append 的顺序 FIFO。
- 多 producer 场景只承诺 lock 线性化顺序。

### OpenAI Codex

官方事实：

- OpenAI 公开资料描述 Codex 可以运行并行 coding agents / cloud tasks，并支持 isolated worktrees、progress、decisions、skills、automations 等能力。
- 公开资料没有说明 Codex 内部 Mailbox delivery semantics。

来源：

- https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
- https://help.openai.com/en/articles/11390924
- https://help.openai.com/en/articles/11391654-chatgpt-business-release-notes

工程推断：

- 可以把 “并行 agents 需要通信/协调层” 作为架构推断，但不能声称 Codex 内部一定使用本教程这种 Mailbox。

CodeTeam 选择：

- 使用公开可解释的 in-process Mailbox 证明学习项目的通信能力。
- 不把微基准包装成 OpenAI/Codex 级别的生产结论。

---

## 18. 验收标准

教程阶段完成标准：

```text
[x] 只读审计当前 Day1-Day3 真实实现。
[x] 明确原计划与当前同步 Scheduler 的冲突。
[x] 明确 AgentMessage / AgentEvent / schemas.Message 的边界。
[x] 明确 Mailbox 不绕过 Scheduler ownership。
[x] 给出 Pydantic 模型和同步 deque + Lock API 骨架。
[x] 给出测试地图、DD、Benchmark、Ablation、Failure 计划。
[x] 明确 Day5/Day6 deferred 范围。
```

未来实现阶段完成标准：

```text
[x] codeteam/agent_team/mailbox.py 实现。
[x] codeteam/agent_team/__init__.py 导出公共 API。
[x] codeteam/events.py 扩展 mailbox 事件。
[x] tests/agent_team/test_mailbox.py 覆盖模型/收发/FIFO/broadcast/并发/sink。
[x] evals/week5/benchmark_mailbox.py 可复现运行。
[x] docs/design_decisions/DD-W5-04.md 记录决策。
[x] docs/benchmark/W5_MAILBOX.md 记录真实 benchmark。
[x] docs/failure_cases/W5_MAILBOX_FAILURE.md 记录失败案例。
```

---

## 19. 面试表达

### 30 秒版本

> Day4 我设计的是 Multi-Agent Runtime 的通信层。它不是直接让 Worker 调另一个 Worker 的函数，而是给每个 Agent 一个进程内 mailbox，用结构化 `AgentMessage` 做点对点通信。它和 `AgentEvent` 分开：message 是待消费通信，event 是已发生审计事实。第一版采用 `deque + Lock`，和 Day3 同步 Scheduler 保持一致，承诺每个 inbox 的 FIFO、容量上限、at-most-once destructive receive，但不声称 durable 或 exactly-once。

### 2 分钟版本

> 在 CodeTeam 里，Day1 有 Lead/Worker，Day2 有 Task DAG，Day3 有原子 claim 的 Scheduler。Day4 需要解决的是 Agent 之间如何交流结果、进度和 review finding。我的设计是新增 `AgentMessageType` 和 `AgentMessage`，字段包括 `message_id/sender_id/recipient_id/task_id/node_id/correlation_id/payload`。Mailbox 有独立地址簿，Lead 和 Worker 都能注册，不能复用只面向 Worker role 查询的 `WorkerRegistry`。`send()` 和 `receive()` 都在锁内完成状态更新，event sink 在锁外调用；broadcast 先在同一锁内预检所有 recipient 和容量，再 all-or-nothing 入队。这个设计故意不做 crash recovery 和 durable replay，因为那是 Day5/Day6 的范围。它证明的是进程内通信正确性和可审计性，不是分布式消息系统。

### 面试官追问

Q：为什么不用直接函数调用？

A：直接函数调用会把 sender 和 receiver 生命周期绑在一起，也没有 inbox、排队、容量、审计和 receiver 暂时不可用的表达。Mailbox 让 Agent 之间通过结构化消息解耦。

Q：Mailbox 和 Event Log 有什么区别？

A：Mailbox 里的消息是待消费的通信载体，`receive()` 后会删除；Event Log 是已经发生的事实，用于审计，不被某个 Agent 消费掉。

Q：为什么不用 `asyncio.Queue`？

A：当前 Scheduler 是同步线程核心，状态正确性不依赖 event loop。Day4 先用 `deque + Lock` 把线性化点、容量、broadcast 原子性测清楚；未来可以在外层加 async adapter。

Q：你能保证 exactly-once 吗？

A：不能，Day4 明确是进程内、非持久化、destructive receive、at-most-once dequeue。Exactly-once 需要 durable store、ack/nack、去重和恢复协议，留给 Day6 之后。

Q：Worker 发了 TASK_COMPLETED 消息，任务就完成了吗？

A：没有。消息只是通信。真正修改任务状态必须调用 `TaskScheduler.complete(node_id, owner_id)`，并通过 owner 和状态机校验。

---

## 20. 进入 Step1 前你必须能回答

1. `AgentMessage`、`AgentEvent`、`codeteam.schemas.messages.Message` 三者有什么区别？
2. 为什么 Mailbox 不能复用 `WorkerRegistry` 当地址簿？
3. Day4 的 FIFO 到底承诺什么，不承诺什么？
4. 为什么 broadcast 不能简单循环调用 `send()`？
5. 为什么 Mailbox 消息不能直接改 Scheduler 状态？
6. 当前 `node_id`、`assignment_id`、`source_step_id`、`agent_id` 分别是什么 namespace？
7. 为什么 Day4 不做 worker crash recovery？

---

## 21. Day4 实现证据记录

本轮已按 Step0-Step9 落地：

- Step0：冻结 Day4 语义为进程内、非持久化、每 inbox FIFO、destructive receive、at-most-once dequeue、bounded capacity。
- Step1：新增 `AgentMessageType` 和 `AgentMessage`，使用 Pydantic 校验必填 ID、消息类型和 payload。
- Step2：新增 Mailbox 领域异常和独立地址簿，Lead/Worker 都可以注册；没有复用 `WorkerRegistry`。
- Step3：实现 `AgentMailbox.send()`，校验 sender、recipient、重复 `message_id` 和容量，成功后返回防御性快照。
- Step4：实现非阻塞 `receive()`，空 inbox 返回 `None`，成功消费后从队列删除。
- Step5：实现全局已接受 `message_id` 去重和 `capacity_per_inbox`，容量满抛 `MailboxFullError`，不静默丢弃。
- Step6：实现显式 recipient `broadcast()`，每个 recipient 独立 `message_id`，共享 `correlation_id`，同一锁内预检并 all-or-nothing 入队。
- Step7：Mailbox 事件接入 `codeteam.events.AgentEventType`，只记录安全 metadata；event sink 在锁外投递，sink 普通异常被隔离并记录 `mailbox.event_delivery_failed`。
- Step8：在 `codeteam/agent_team/__init__.py` 导出 Day4 公共 API。
- Step9：新增 `tests/agent_team/test_mailbox.py`、`DD-W5-04`、`W5_MAILBOX.md`、`W5_MAILBOX_FAILURE.md` 和 `benchmark_mailbox.py`。

当前边界仍然成立：

- Mailbox 消息不会直接推进 Scheduler 状态；任务完成/失败仍必须走 `TaskScheduler.complete()` / `fail()` 的 owner 与状态机校验。
- Day4 不证明 crash recovery、heartbeat、ack/nack、durable replay、SQLite mailbox、exactly-once、cross-process delivery 或端到端 Multi-Agent 加速。
- Benchmark 只测本地 `AgentMailbox` 操作成本：setup、send、receive、concurrent producer send、broadcast fan-out 和近似 backlog bytes。

---

## 22. Day4 Hardening 收尾记录

本轮修复的是 Day4 验收里暴露的最小闭环问题，不扩展到 Day5 heartbeat 或 Day6 durable mailbox。

### 22.1 Broadcast 批内 message_id 碰撞

原实现只检查生成的 `message_id` 是否已经存在于历史 `_seen_message_ids`。如果 UUID 工厂在同一批 broadcast 内返回相同值，多个 recipient 可能收到相同 `message_id`。

修复后的契约：

```text
构造整批 AgentMessage
  -> 检查批内 message_id 唯一
  -> 检查历史 _seen_message_ids
  -> 检查 recipient 和 capacity
  -> 同一锁内 all-or-nothing append
```

如果批内 ID 重复，抛 `DuplicateMessageError`，并且不写 inbox、不写 `_seen_message_ids`、不产生 `MAILBOX_BROADCAST_SENT` 成功事件。不要用无限循环重新生成 UUID，因为那会把可测试的故障变成不可控等待。

### 22.2 AgentMessage 序列化契约

`AgentMessage.payload` 是 Agent 间纯数据通信载体，因此必须在模型构造时就是 JSON-compatible：

```text
支持：
None
str / bool / int / finite float
list
dict[str, JSON-compatible value]

拒绝：
callable
自定义 object
set / tuple 等非 JSON 稳定类型
非字符串 dict key
NaN / infinity / -infinity
```

`created_at` 必须是有限且非负的 `float`。`model_dump_json()` 到 `model_validate_json()` 必须 round-trip 一致。

### 22.3 Mailbox 不写 Scheduler 状态

新增回归测试证明：即使 Worker 通过 Mailbox 发送并且 Lead 消费了 `TASK_COMPLETED` 或 `TASK_FAILED` 消息，`TaskScheduler` 的 runtime record、owner、queue 和 scheduler events 都不会自动变化。

正式边界仍然是：

```text
AgentMessage = 通信事实
TaskScheduler.complete()/fail() = 唯一状态写入口
```

完成/失败必须显式调用 Scheduler API，并通过 owner/status gate。

### 22.4 内存保留权衡

`capacity_per_inbox` 只限制当前排队消息数量，不代表整个 `AgentMailbox` 内存有界：

- `_seen_message_ids` 会随累计接受消息数增长；
- `_events` 会随注册、发送、接收和投递失败事件增长；
- 全局生命周期去重需要保留 seen IDs，这是正确性与内存之间的取舍；
- 第一版 `AgentMailbox` 应按 team/task/session 生命周期使用，并在生命周期结束后释放；
- 去重窗口、事件归档、持久化和恢复策略留给 Day6。

所以 Day4 不能再说 “避免无限内存增长”。更准确的说法是：限制 inbox backlog，降低慢消费者导致的瞬时积压。

### 22.5 Safety Ablation 证据

本轮新增 `evals/week5/ablation_mailbox.py`，只做 correctness/safety ablation，不做性能 benchmark。

对照：

```text
Full:
  当前 AgentMailbox.broadcast()
  预检所有 recipient/message_id/capacity
  失败时 0 partial delivery

Ablated:
  实验代码 for recipient: send(...)
  前面的 recipient 成功后，后面的 recipient 因未知地址或容量满失败
  会产生 partial delivery，需要清理
```

记录指标：

```text
partial_delivery_count
inbox_divergence_count
cleanup_required_count
```

报告路径：

```text
docs/benchmark/W5_MAILBOX_ABLATION.md
```

由于 `mailbox.py` hardening 后文件 hash 已变化，旧 `docs/benchmark/W5_MAILBOX.md` 标记为 `STALE_AFTER_HARDENING / RERUN_DEFERRED_UNTIL_WEEK5_COMPLETION`。本轮没有运行 Mailbox 性能 benchmark，也不能把 safety ablation 当性能结果。
