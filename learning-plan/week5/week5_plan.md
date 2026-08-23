# Week 5：Task DAG 与 Agent Team 编排 —— 学习路线（工业级 Agent Harness 方向）

## 本周定位

经过 Week1～4，你的 CodeTeam 已经具备：

```text
Single Agent Runtime

Task
 ↓
Plan
 ↓
Context Engine
 ↓
Tool Runtime
 ↓
Patch
 ↓
Verification
 ↓
Repair
 ↓
Session
```

Week5 的目标不是“增加几个 Agent”。

真正目标：

> **将 Single-Agent Runtime 演进为 Multi-Agent Orchestration Runtime。**

对应工业界：

- Claude Code Agent Teams
- OpenAI Codex 多 Agent 工作流
- OpenHands Agent Delegation
- AutoGen GroupChat
- LangGraph Supervisor
- CrewAI Flow

核心能力：

```
Task Understanding
        ↓
Task Decomposition
        ↓
Task Scheduling
        ↓
Agent Coordination
        ↓
State Management
        ↓
Failure Recovery
```

这也是 DeepSeek Agent Harness / Agent Infra 岗位最关注的能力之一。

---

# 一、本周核心架构变化

## Week4 架构

当前：

```
User

 ↓

SingleAgentOrchestrator

 ↓

Agent Loop

 ↓

Tools

 ↓

Result
```

特点：

一个 Agent：

- 自己理解任务
- 自己搜索
- 自己修改
- 自己测试


---

## Week5 架构

升级：

```
                     User Task

                         |

                         v

                    Lead Agent
                         |
                         |
                  Task DAG Planner

                         |

        +----------------+----------------+

        |                |                |

   Worker Agent    Worker Agent    Worker Agent

        |                |                |

   Context A       Context B       Context C

        |

      Mailbox

        |

   Task Store / Event Log
```

---

# 二、为什么 Coding Agent 需要 Multi-Agent？

很多人认为：

> 一个更强的模型不就够了吗？

但是复杂软件任务存在天然分解：

例如：

用户：

> 增加 OAuth 登录功能，并修复测试问题。


实际上包含：

```
Task 1:
理解现有认证架构


Task 2:
实现 OAuth Provider


Task 3:
修改 API


Task 4:
补测试


Task 5:
Review 安全问题
```

这些任务：

- 依赖不同文件
- 需要不同技能
- 可以并行


所以问题从：

```
How smart is one Agent?
```

变成：

```
How effectively can multiple Agents collaborate?
```

---

# 三、工业界 Multi-Agent 核心模式

---

# 1. Supervisor Pattern

## 概念

Supervisor：

也叫：

- Lead Agent
- Manager Agent
- Coordinator Agent


负责：

```
理解目标

↓

拆任务

↓

分配任务

↓

监控进度

↓

处理异常
```


Worker：

负责：

```
执行具体任务
```


---

## 类比

软件团队：

```
Tech Lead

 |
 +------ Backend Engineer

 |
 +------ Frontend Engineer

 |
 +------ QA Engineer
```


Lead 不写全部代码。

Lead 管理：

- 谁做什么
- 顺序是什么
- 什么时候合并

---

## 工业实践

### LangGraph Supervisor

典型：

```
Supervisor Agent

       |
 ----------------
 |       |       |

Research Code Test
Agent   Agent Agent
```

Supervisor 根据任务动态路由。


---

### AutoGen

GroupChat：

```
Manager Agent

       |

Conversation Routing

       |

Multiple Agents
```

---

## CodeTeam 对应

新增：

```
LeadAgent
```

替代：

```
SingleAgentOrchestrator
```


---

# 2. Planner-Executor Pattern

这是 Coding Agent 最核心模式。


## 错误设计

很多初级 Agent：

```
User Prompt

↓

LLM

↓

直接写代码
```

问题：

- 修改方向错误
- 漏文件
- 无法恢复


---

## 工业设计


```
User Request

↓

Planner

↓

Structured Plan

↓

Executor

↓

Verification
```


---

Planner 输出：

不是：

```
我要先分析一下……
```

这种自然语言。


而是：

```json
{
 "tasks":[
   {
    "id":"T1",
    "goal":"Analyze auth flow",
    "role":"backend"
   },
   {
    "id":"T2",
    "goal":"Add OAuth endpoint",
    "role":"backend"
   }
 ]
}
```

---

## 为什么必须结构化？

因为后续：

Scheduler：

需要读取：

```
task.id

dependency

status

owner
```


LLM 输出自然语言：

```
第一步先看看代码
第二步修改接口
```

机器无法可靠调度。

---

# 3. Task DAG

## 什么是 DAG？

Directed Acyclic Graph：

有向无环图。


例如：

```
        Design

          |

    +-----+-----+

    |           |

Backend     Frontend

    |           |

    +-----+-----+

          |

        Test
```


表示：

```
Design完成

↓

Backend和Frontend可以并行

↓

Test等待两者
```


---

# 为什么不用 List？

简单任务：

```
Step1
Step2
Step3
```

可以。


但是 Coding Task：

```
修改数据库

修改API

修改前端

补测试
```


存在：

- 并行
- 依赖
- 动态变化


所以需要 DAG。


---

# DAG 核心概念


## Node

任务：

```
TaskNode
```


例如：

```json
{
"id":"backend_api",
"status":"READY"
}
```


---

## Edge

依赖：

```
backend_api

      ↓

integration_test
```


---

## Ready Task

满足：

```
所有 dependency completed
```

即可执行。


---

# DAG 必备算法

## Topological Sort

作用：

确定执行顺序。


例如：

```
A → B → C
```


排序：

```
A,B,C
```


---

## Cycle Detection

检测：

```
A → B → C → A
```

必须拒绝。


否则 Scheduler 永远等待。

---

# 4. Agent Lifecycle

Agent 不是函数。

不是：

```
call()
return()
```


Agent 是长期运行实体。


状态：

```
CREATED

 ↓

READY

 ↓

RUNNING

 ↓

WAITING

 ↓

COMPLETED


FAILED

 ↓

RECOVERING
```


---

## 为什么需要状态机？


因为：

Worker 可能：

- crash
- timeout
- 等待消息
- 重试


没有状态：

无法恢复。

---

# 5. Agent 独立 Context

这是 Multi-Agent 最容易设计错的地方。


错误：

```
所有 Agent

共享整个 Conversation
```


问题：

Token 爆炸：

```
Lead Context
+
Worker1
+
Worker2
+
Worker3
```


同时：

信息污染。


---

正确：

```
                Lead Context


              Task Assignment


      +-------------+-------------+

      |             |             |

 Worker A     Worker B      Worker C


Context A     Context B     Context C
```


---

Worker Context 包含：

```
System Prompt

Role

Assigned Task

Relevant Files

Tool Permission

Local History
```


不包含：

其他 Worker 全部过程。

---

# 6. Agent Mailbox

## 为什么不用直接调用？

错误：

```
Worker A

call()

Worker B
```


问题：

强耦合。


---

工业模式：

```
Agent A

send(message)

↓

Mailbox

↓

Agent B

receive()
```


类似：

微服务消息队列。

---

消息：

```json
{
"type":"TASK_RESULT",
"from":"worker1",
"to":"lead",
"payload":{
 "status":"success"
}
}
```


---

优点：

- 异步
- 解耦
- 可恢复
- 可记录


---

# 7. Task Claiming

问题：

多个 Worker 抢任务。


例如：

Scheduler：

发现：

```
Task A READY
```


两个 Worker：

```
Worker1:

我要执行


Worker2:

我要执行
```


导致：

重复修改。


---

解决：

状态：

```
READY

↓

CLAIMED

↓

RUNNING
```


Claim 必须原子。


类似：

数据库：

```sql
UPDATE tasks
SET status='CLAIMED'
WHERE id='A'
AND status='READY'
```

---

# 8. Heartbeat 与 Timeout


Agent 会死亡。


例如：

Worker:

```
执行测试

卡死
```


Lead 不知道。


---

Heartbeat：

Worker：

每隔：

10s


发送：

```json
{
"type":"HEARTBEAT",
"agent":"worker1",
"time":xxx
}
```


Scheduler：

检测：

```
now-last_seen > timeout
```


执行：

```
FAILED

↓

REQUEUE
```

---

# 9. Dynamic Role Creation


固定：

```
Worker1
Worker2
Worker3
```


不够。


复杂任务：

需要：

```
Frontend Agent

Backend Agent

Security Agent

Test Agent
```


动态创建：

```
Task Analysis

↓

Required Capability

↓

Spawn Agent
```


---

# 三、Week5 每日学习安排


---

# Day 1：Multi-Agent Architecture 与 Supervisor

## 学习

理论：

- Single Agent vs Multi Agent
- Supervisor Pattern
- Planner-Executor
- Agent Role
- Agent Boundary


阅读：

- LangGraph Supervisor
- AutoGen Architecture
- OpenHands Agent Design


---

## 编码

实现：

```
agent_team/

lead.py

worker.py

models.py
```


创建：

```python
class AgentRole(Enum):

    LEAD
    BACKEND
    FRONTEND
    TEST
```


实现：

```python
class LeadAgent:

    def create_plan():
        ...
```


---

## 测试

验证：

- Lead 创建任务
- Worker 注册
- Role 正确


---

## Design Decision

DD-W5-01

为什么：

```
Lead + Worker
```

而不是：

```
多个平级 Agent
```


---

## Benchmark

10 个任务：

统计：

- task decomposition latency
- task number


---

## Failure

记录：

- plan 空
- role 错误
- 无法拆解


---

# Day 2：Task DAG 实现


## 学习

- DAG
- dependency graph
- topological sort
- cycle detection


---

## 编码


实现：

```
dag.py
```


类：

```python
TaskNode

TaskDAG
```


支持：

```python
add_task()

add_dependency()

get_ready_tasks()

validate()
```


---

## 测试


覆盖：

```
A→B

A→B,C

cycle

missing dependency
```


---

## Benchmark

测试：

100/500/1000 task DAG

统计：

- build time
- resolve latency


---

# Day 3：Scheduler 与任务认领


## 学习

- Task Queue
- Worker Pool
- Scheduling


---

## 编码


实现：

```
scheduler.py
```


接口：

```python
schedule()

claim()

complete()

fail()
```


---

支持：

3 Worker 并发。


---

测试：

- 重复 claim
- 并发 claim
- fail retry


---

Design：

为什么：

```
state machine scheduler
```

而不是：

```
简单 asyncio gather
```


---

# Day 4：Mailbox 与 Agent Communication


## 学习

- Message Queue
- Event Driven Architecture
- Async Communication


---

## 编码


实现：

```
mailbox.py
```


接口：

```python
send()

receive()

broadcast()
```


消息：

```python
AgentMessage
```


---

测试：

- 消息顺序
- 丢失恢复
- worker crash


---

Benchmark：

10000 messages:

- throughput
- latency


---

# Day 5：Agent Lifecycle + Failure Recovery


## 学习

- Heartbeat
- Timeout
- Restart
- Reassignment


---

## 编码


实现：

```
lifecycle.py

registry.py
```


支持：

```
agent heartbeat

detect dead agent

reassign task
```


---

测试：

模拟：

Worker crash。


验证：

任务重新分配。


---

Design：

为什么：

```
Agent state machine
```

而不是：

```
boolean alive
```


---

# Day 6：TaskStore + Session Integration


## 学习

- Durable Agent State
- Event Sourcing
- Recovery


---

## 编码


实现：

```
task_store.py
```


保存：

```
Task

DAG

Agent

Message

Event
```


存储：

SQLite。


---

测试：

模拟：

```
kill process

restart

resume
```


---

Benchmark：

1000 tasks:

- load latency
- recovery time


---

# Day 7：Agent Team MVP + Evaluation


## 整合流程


完整：

```
User Task

↓

LeadAgent

↓

Task DAG

↓

Scheduler

↓

3 Worker

↓

Mailbox

↓

TaskStore

↓

Result
```


---

## 评测


比较：

### Single Agent

vs


### Agent Team


任务：

10 个：

- Bug
- Feature
- Refactor


指标：

```
Success Rate

Latency

Token Cost

Tool Calls

Parallel Efficiency
```


---

# 最终产出


代码：

```
codeteam/agent_team/

lead.py

worker.py

dag.py

scheduler.py

mailbox.py

registry.py

store.py
```


文档：

```
docs/design_decisions/DD-W5.md

docs/benchmark/W5_REPORT.md

docs/failure_cases/W5_FAILURES.md
```


---

# Week5 完成后面试能力

你应该能回答：

> “如何设计一个类似 Claude Code Agent Teams 的系统？”

标准答案：

> 我不会简单创建多个 LLM 实例，而是设计一个 Multi-Agent Runtime。由 Lead Agent 负责任务理解和 DAG 规划，Scheduler 根据依赖关系调度 Worker，Worker 使用独立 Context 和 Workspace 执行任务，通过 Mailbox 异步通信，并通过 TaskStore 和 Event Log 保存状态。为了保证可靠性，我设计了 Agent Lifecycle、Heartbeat 和 Failure Recovery 机制，并通过 Single Agent 与 Agent Team 对比实验验证多 Agent 架构在复杂 Coding Task 上的收益。

---

这就是 Week5 的完整学习路线。后续每天学习时，我会按照：

**Theory → Industrial Design → CodeTeam Mapping → Implementation → Tests → Design Decision → Benchmark → Ablation → Failure Cases → Interview Questions**

继续展开。