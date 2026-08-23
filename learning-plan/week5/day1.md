# Week5 Day 1：Multi-Agent Architecture 与 Supervisor

今天是 Week5 的第一天，也是 CodeTeam 从 **Single-Agent Runtime → Multi-Agent Runtime** 的关键转折点。

今天不要急着写多个 Agent。

核心目标：

> 理解为什么工业级 Coding Agent 需要 Supervisor / Lead Agent 架构，以及如何设计 Agent 之间的边界。

最终你要回答面试问题：

> “为什么 Claude Code Agent Teams 不是简单启动多个 Agent，而需要一个 Agent Runtime 来管理协作？”

---

# 一、今天解决什么问题？

## Week4 的 Single Agent

当前 CodeTeam：

```text
User Task

    ↓

SingleAgentOrchestrator

    ↓

Agent Loop

    ↓

Tools

    ↓

Patch

    ↓

Test

    ↓

Result
```

一个 Agent 负责：

- 理解需求
- 搜索代码
- 修改代码
- 执行测试
- 修复错误


对于简单 Bug：

很好。


例如：

```
修复 login.py 中 token 过期异常
```

一个 Agent：

```
搜索
 ↓
修改
 ↓
测试
```

足够。

---

但是复杂任务：

例如：

```
增加 OAuth 登录系统

要求：
1. 后端增加接口
2. 前端增加登录页面
3. 数据库增加字段
4. 添加测试
5. 保证兼容旧用户
```

Single Agent 会遇到：

---

## 问题1：任务复杂度爆炸


一个 Agent Context：

```
backend/
frontend/
database/
tests/
docs/
```

全部塞进去：

Token 爆炸。


---

## 问题2：角色能力不同


后端任务：

需要：

```
API设计
数据库
服务逻辑
```

测试任务：

需要：

```
测试覆盖
mock
fixture
```

安全任务：

需要：

```
漏洞分析
权限检查
```

一个 Agent 很难同时保持所有专业视角。


---

## 问题3：无法并行


例如：

```
修改 backend/auth.py

修改 frontend/Login.tsx

新增 tests/oauth.py
```

实际上可以并行。


Single Agent：

只能：

```
backend

↓

frontend

↓

test
```

浪费时间。

---

因此工业界开始研究：

# Multi-Agent Coding Runtime

---

# 二、Single Agent vs Multi Agent

---

# 1. Single Agent

结构：

```
          User

           |

        Agent

           |

     Tool Runtime

           |

       Workspace
```


特点：

优点：

- 简单
- Token 少
- 调试容易


缺点：

- 长任务容易迷失
- Context 越来越大
- 无法并行
- 专业能力不足


---

# 2. Multi Agent


结构：

```
                 User

                  |

             Lead Agent

                  |

              Task DAG

        /          |          \

       /           |           \

Backend       Frontend       Test

 Agent          Agent        Agent
```

---

区别：

Single Agent：

> 一个大脑解决所有问题。


Multi Agent：

> 一个团队协作完成任务。


---

# 三、工业界为什么需要 Supervisor Pattern？

Supervisor Pattern 是 Multi-Agent 最重要架构。

---

## 什么是 Supervisor？

Supervisor：

也叫：

- Lead Agent
- Manager Agent
- Coordinator Agent


它不负责具体工作。


它负责：

```
理解目标

↓

拆解任务

↓

分配任务

↓

监控执行

↓

处理异常

↓

汇总结果
```


---

Worker：

负责：

```
执行具体任务
```


---

类比软件团队：

```
             Tech Lead

                |

    -------------------------

    |            |          |

 Backend     Frontend     QA

 Engineer    Engineer   Engineer
```

Lead 不写所有代码。

Lead 管：

- 谁负责什么
- 任务顺序
- 是否完成
- 是否需要调整


---

# 四、工业实践案例

---

# 1. LangGraph Supervisor


LangGraph 是目前工业界 Agent Workflow 常见框架。


典型结构：

```
             Supervisor

                  |

        +---------+---------+

        |         |         |

    Research   Coding    Testing

      Agent     Agent     Agent
```


Supervisor：

根据任务：

决定调用哪个 Agent。


例如：

用户：

```
分析 GitHub Issue 并修复
```


Supervisor：

```
先 Research Agent

↓

Coding Agent

↓

Testing Agent
```


---

核心思想：

Agent 不是平级聊天。

而是：

```
Supervisor 控制 Workflow
```

---

# 2. AutoGen GroupChat


Microsoft AutoGen：

典型：

```
        GroupChatManager


              |

 --------------------------------

 |              |              |

Planner       Coder        Reviewer
```


Manager：

负责：

- 选择下一个 Agent
- 控制对话


---

# 3. OpenHands


OpenHands（原 OpenDevin）：

Coding Agent 设计：

```
Agent

 |

Planner

 |

Executor

 |

Environment
```


虽然公开版本主要是 Single Agent，但是架构天然支持：

- Delegate
- Specialized Agent


---

# 4. Claude Code Agent Teams（概念）


Claude Code Agent Teams 思路：

```
Main Agent

     |

Task Delegation

     |

Sub Agents
```


关键：

不是复制多个 Claude。


而是：

```
一个协调者

+
多个拥有独立上下文的执行者
```

---

# 五、为什么不是多个平级 Agent？

这是今天最重要的 Design Decision。

---

## 方案A：平级 Agent


例如：

```
Agent A

Agent B

Agent C
```


大家自己决定。


问题：

---

## 问题1：没有统一目标


Agent A：

```
修改数据库
```


Agent B：

```
重构 API
```


可能：

方向冲突。


---

## 问题2：资源竞争


两个 Agent：

同时修改：

```
auth.py
```


产生冲突。


---

## 问题3：无法判断完成状态


谁宣布：

```
任务完成？
```

---

# 方案B：Lead + Worker


```
             Lead

              |

        Task Assignment

              |

 Worker1 Worker2 Worker3
```


Lead 统一：

- 目标
- 任务
- 依赖
- 状态


---

因此：

CodeTeam 选择：

```
Lead + Worker
```

---

# 六、Planner-Executor Architecture

Supervisor 通常结合：

Planner-Executor。


---

## Planner

回答：

> What should be done?


例如：

输入：

```
修复支付失败问题
```


Planner 输出：

```json
{
 "tasks":[
   {
    "id":"T1",
    "goal":"Analyze payment flow"
   },
   {
    "id":"T2",
    "goal":"Fix retry logic"
   },
   {
    "id":"T3",
    "goal":"Add regression test"
   }
 ]
}
```


---

## Executor


回答：

> How to do it?


Executor：

执行：

```
搜索文件

读取代码

修改

测试
```

---

为什么分离？


因为：

Planner：

需要：

- 全局视角


Executor：

需要：

- 局部执行


类似：

软件工程：

```
架构设计

↓

代码实现
```


---

# 七、Agent Role 设计

今天实现：

```python
class AgentRole(Enum):

    LEAD = "lead"

    BACKEND = "backend"

    FRONTEND = "frontend"

    TEST = "test"
```

---

为什么需要 Role？


因为 Agent 需要：

不同：

- Prompt
- Tool Permission
- Context
- Evaluation


---

例如：

Backend Agent：

```
可以修改：

backend/

禁止：

frontend/
```

---

Test Agent：

```
只读代码

可以运行测试
```

---

Reviewer：

```
只读

不能修改
```

---

# 八、Agent Boundary（边界）

这是 Agent Infra 面试重点。


一个成熟 Agent Runtime 必须定义：

## Context Boundary


Worker 不应该看到：

其他 Worker 全部历史。


---

## Tool Boundary


例如：

Test Agent：

允许：

```
pytest
```

禁止：

```
git reset --hard
```

---

## Workspace Boundary


Backend Agent：

自己的：

```
worktree/backend
```


---

## Ownership Boundary


任务：

```
auth.py
```

只能：

一个 Worker 修改。

---

# 九、今天 CodeTeam 设计

新增：

```
codeteam/

agent_team/

    models.py

    lead.py

    worker.py
```


---

# models.py


定义 Domain Model。


## AgentRole


```python
from enum import Enum


class AgentRole(Enum):

    LEAD="lead"

    BACKEND="backend"

    FRONTEND="frontend"

    TEST="test"
```


---

## AgentStatus


新增：

```python
class AgentStatus(Enum):

    CREATED="created"

    READY="ready"

    RUNNING="running"

    WAITING="waiting"

    COMPLETED="completed"

    FAILED="failed"
```

---

## AgentInfo


```python
@dataclass
class AgentInfo:

    id:str

    role:AgentRole

    status:AgentStatus
```


---

# worker.py


Worker 是执行者。


第一版：

不要接真实 LLM。


先：

```python
class WorkerAgent:


    def execute(task):

        pass
```


原因：

先验证：

Runtime。

---

# lead.py


核心：

```python
class LeadAgent:


    def create_plan(
        self,
        task_spec
    ):

        return TaskPlan()
```


---

第一版：

可以：

规则生成。


例如：

输入：

```
add login feature
```


输出：

```
Backend Task

Frontend Task

Test Task
```

---

后续：

替换：

```
Rule Planner

↓

LLM Planner
```

---

# 十、今日测试设计


## Test 1

Lead 创建任务


输入：

```
增加登录功能
```


期待：

至少：

```
backend task

test task
```


---

## Test 2

Worker 注册


```python
registry.register(worker)
```


检查：

```
worker exists
```


---

## Test 3

Role 正确


例如：

```python
worker.role
```

必须：

```
BACKEND
```


---

# 十一、Design Decision

## DD-W5-01

标题：

```
Why Lead-Worker Architecture Instead of Peer Agents
```

---

## Problem


Multi-Agent 中：

多个 Agent 需要协作。

如果平级：

- 冲突
- 无统一状态
- 难恢复


---

## Alternatives


### A

Peer-to-peer Agents


优点：

灵活。


缺点：

协调复杂。


---

### B

Lead + Worker


优点：

- 中央协调
- 状态清晰
- 容易调度


缺点：

Lead 可能成为瓶颈。


---

## Decision


选择：

```
Lead + Worker
```


原因：

Coding Agent 任务：

天然具有：

- 主任务
- 子任务
- 依赖关系


---

# 十二、Benchmark

今天不测代码质量。

测：

Planner 能力。


准备：

10 个任务：

例如：

```
修复登录bug

增加缓存

添加API

重构数据库层
```


记录：

---

## 1. Task Decomposition Latency


公式：

```
plan_end_time
-
plan_start_time
```


---

## 2. Task Number


统计：

```
平均拆成多少子任务
```


---

## 3. Role Accuracy


例如：

Backend任务：

是否分配 Backend Agent。


---

# 十三、Failure Case


建立：

```
docs/failure_cases/week5/
```


---

## F-W5-D1-01

### Empty Plan


现象：

Planner：

```json
{
"tasks":[]
}
```


原因：

任务无法理解。


改进：

增加：

fallback planner。


---

## F-W5-D1-02

### Wrong Role


例如：

数据库任务：

分配：

Frontend。


原因：

Role classifier 错误。


---

## F-W5-D1-03

### Cannot Decompose


复杂任务：

无法拆分。


原因：

Planner 能力不足。


---

# 十四、面试问题

## Q1：

为什么 Coding Agent 需要 Multi-Agent？


回答：

> 单 Agent 在复杂 Coding Task 中会受到 Context 长度、专业能力和执行并行性的限制。Multi-Agent 通过 Supervisor 将任务拆解为多个具有独立 Context 和 Workspace 的 Worker，提高复杂任务处理能力。


---

## Q2：

为什么不用多个平级 Agent？


回答：

> Coding Task 存在明确目标和依赖关系，需要统一调度和状态管理。因此采用 Lead-Worker 架构，由 Lead 负责规划和协调，Worker 负责执行，降低冲突并提升可恢复性。


---

## Q3：

Multi-Agent 最大挑战是什么？


回答：

> 不是创建多个 Agent，而是设计 Agent Runtime，包括任务分解、状态管理、通信机制、上下文隔离、资源边界以及失败恢复。


---

# 今日完成标准

完成：

代码：

```
codeteam/agent_team/

models.py

lead.py

worker.py
```


测试：

```
tests/agent_team/

test_lead.py

test_worker.py

test_role.py
```


文档：

```
docs/design_decisions/DD-W5-01.md
docs/failure_cases/week5/
```

---

完成今天后，你真正开始进入：

> **Agent Harness / Agent Runtime 开发领域**

因为从今天开始，你实现的不再是“调用 LLM 的 Agent”，而是“管理 Agent 的 Runtime”。这正是 DeepSeek AgentHarness、阿里 Agent Infra、字节 Dev AI 等岗位核心关注方向。

---

# Week5 Day1 实操教程：从 Single-Agent Runtime 到 Lead-Worker 架构

> 本教程基于 2026-08-24 当前 CodeTeam 仓库的真实接口编写。它是今天逐步学习和手动实现的路线，不代表下文中的 `codeteam/agent_team/` 已经存在，也不代表 Multi-Agent 并行执行已经完成。

## 1. Today in the System

### 1.1 今天真正要解决的问题

Week1～Week4 已经让 CodeTeam 拥有一条可工作的 Single-Agent Runtime 基础链：

```text
用户请求
  -> TaskSpec
  -> RepositoryInspector
  -> Planner
  -> Plan
  -> SingleAgentOrchestrator
  -> Patch / Verification / Repair
  -> Session / Events / Evaluation
```

这条链的优点是责任集中、行为容易复现，适合单点 Bug、单模块修改和短任务。它的限制不是“模型不够多”，而是一个运行实体同时承担了太多不同层次的责任：

- 它既要维持任务全局目标，又要阅读局部实现细节。
- 它既要决定先做什么，又要亲自完成每一项操作。
- 它的上下文同时混入规划证据、代码细节、测试日志和修复历史。
- 即使多个子任务彼此独立，当前主链也没有团队级分配边界。

Week5 的演进目标是：在现有 Single-Agent Runtime 外增加一层团队控制平面，让它可以作为 Worker 的执行能力被复用。

```text
当前：

User Task
  -> SingleAgentOrchestrator
  -> Existing Runtime Capabilities
  -> Result

Week5 目标：

User Task
  -> Lead Agent
  -> Structured Plan / Worker Assignment
  -> Worker Agent
  -> Existing Single-Agent Runtime Capabilities
       Context / Patch / Verification / Repair / Safety / Session
  -> Worker Result
  -> Lead Synthesis
```

这里最重要的变化是：

```text
Single-Agent Runtime 没有被删除
而是从“整个产品的唯一控制者”
变成“一个 Worker 可以复用的可靠执行内核”
```

### 1.2 Day1 到底完成什么

Day1 的目标是建立 Lead-Worker 的领域语言和接口边界：

- Agent 有稳定身份，而不是临时字符串。
- Agent 有角色，但角色不直接等于权限。
- Agent 有显式状态，而不是几个布尔变量。
- Worker 可以被描述、注册和查找。
- Lead 输出结构化计划与 Worker Assignment，不直接执行工具。
- 第一版规划和角色分配可以是 deterministic/rule-based，便于测试。

Day1 只定义这些东西，不实现：

- Day2 的 Task DAG、拓扑排序和依赖解析。
- Day3 的 Scheduler、并发认领和 Worker Pool。
- Day4 的 Mailbox 与 Agent 间消息传递。
- Day5 的 heartbeat、超时、死亡检测和重新分配。
- Day6 的团队状态持久化与跨进程恢复。
- Day7 的完整 Agent Team MVP 和 Single-Agent 对照评测。

所以今天结束时，准确表述应当是：

> CodeTeam 已建立 Lead-Worker 的领域模型、注册边界和结构化分配契约；尚未具备真正并行、可恢复的 Multi-Agent Runtime。

不能表述成：

> CodeTeam 已经实现多个 Agent 并行协作。

因为没有 Scheduler、Mailbox、Task DAG 和团队生命周期时，“创建几个对象”还不是完整的 Multi-Agent Orchestration。

## 2. Capability Mapping

### 2.1 今天映射到能力树的哪里

Primary：

```text
Multi-Agent Orchestration
├── Agent Identity
├── Role Boundary
├── Lead-Worker Responsibility
└── Structured Worker Assignment
```

Secondary：

```text
Agent Runtime
├── 可复用执行内核
├── 显式生命周期状态
└── 依赖注入

Task Decomposition
├── 用户目标 -> 工作单元
└── 工作单元 -> 推荐角色

Observability
└── 可序列化、可审计的 Agent/Assignment 状态
```

### 2.2 这些能力能证明什么

今天的价值不是证明“会调用多个模型”，而是证明你能做以下工程判断：

- 把控制平面和执行平面拆开。
- 用结构化契约连接不同时期实现的模块。
- 复用已有 Runtime，而不是重复实现 Context、Patch、Sandbox 和 Session。
- 为未来调度、持久化和评测提前设计稳定标识符。
- 让系统在没有真实 LLM 和并行机制时仍可确定性测试。

在 Agent Harness / Agent Infra 面试中，这比“我开了三个聊天窗口”更有价值。面试官通常会继续追问：谁负责分配、如何避免重复执行、状态存在哪里、Worker 失败后谁接管、多个 Worker 如何隔离工作区。Day1 的模型就是后续回答这些问题的地基。

## 3. 当前仓库真实状态

### 3.1 当前 Single-Agent 主链路

当前核心入口是 `codeteam.agent.orchestrator.SingleAgentOrchestrator`：

```python
SingleAgentOrchestrator(
    *,
    inspector: RepositoryInspector,
    planner: Planner,
    repository_root: Path,
    verification_service: VerificationService | None = None,
    workspace: GitWorkspace | None = None,
    ...
)
```

它的规划入口为：

```python
run(
    *,
    request: str,
    task_id: str,
) -> OrchestrationResult
```

当前 `run()` 的真实状态流是：

```text
TaskState(CREATED)
  -> create_task_spec()
  -> INSPECTING
  -> RepositoryInspector.inspect()
  -> PLANNING
  -> Planner.create_plan()
  -> validate_plan()
  -> READY
  -> OrchestrationResult
```

它不会在 `run()` 中执行 PlanStep。执行期由另一个入口承接：

```python
execute_plan_step(
    *,
    task: TaskSpec,
    plan_step: PlanStep,
    task_state: TaskState,
    initial_patch: str,
    repair_agent: RepairAgent,
    target_request: VerificationRequest,
    related_regression_request: VerificationRequest | None = None,
    max_repair_attempts: int = 3,
    workspace_root: Path,
) -> StepExecutionResult
```

这对 Week5 很重要：Lead 不应该重写这条执行链。未来 Worker 可以把已有 orchestrator 或更窄的 execution service 当作自己的执行后端。

### 3.2 当前已有可复用模型

#### `codeteam/task/models.py`

已有：

```python
class TaskSpec(BaseModel):
    task_id: str
    original_request: str
    goal: str
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
```

以及工厂函数：

```python
create_task_spec(
    *,
    task_id: str,
    original_request: str,
) -> TaskSpec
```

Week5 不应该再定义 `TeamTaskSpec` 来复制这些字段。Lead 接收的用户任务仍然是 `TaskSpec`。

#### `codeteam/task/state.py`

已有 `TaskStatus`、`TASK_TRANSITIONS` 和 `TaskState.transition_to()`。它描述的是整个 Coding Task 的状态，不是某个 Worker 自身的生命周期。

因此：

```text
TaskStatus  != AgentStatus
任务 READY   != Worker READY
任务 FAILED  != 某个 Worker 一定永久 FAILED
```

一个 Worker 失败后，Day5 可能把任务重新分配给另一个 Worker，所以不能复用 `TaskStatus` 冒充 Agent 状态。

#### `codeteam/planning/models.py`

已有：

```python
class PlanStep(BaseModel):
    step_id: str
    title: str
    description: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    relevant_files: tuple[str, ...] = ()
    verification: str | None = None

class Plan(BaseModel):
    plan_id: str
    task_id: str
    version: int = 1
    steps: tuple[PlanStep, ...]
```

已有 `validate_plan()`、`create_plan()`、`replan()`。Day1 应复用 `Plan`，不要定义另一份只有 `tasks` 字段的自然语言计划。

但当前 `PlanStep` 没有：

- Worker role。
- Worker identity。
- dependency。
- ownership。

今天只在新的 `WorkerAssignment` 中表达角色分配；dependency 留给 Day2 的 DAG，不提前塞进 `PlanStep`。

#### `codeteam/planning/planner.py`

真实 Planner 协议是：

```python
class Planner(Protocol):
    def create_plan(
        self,
        *,
        task: TaskSpec,
        repo_context: RepositoryContext,
    ) -> Plan:
        ...
```

已经存在：

- `MockPlanner`：测试用固定计划。
- `FailingPlanner`：测试失败路径。
- `LLMPlanner`：把模型 JSON 输出解析成现有 `Plan`。
- `RepositoryContext`：Planner 所需的精选仓库证据。

因此 Day1 的 Lead 可以依赖这个 `Planner` 协议，不需要直接依赖具体模型客户端。

### 3.3 当前 Context、Session、Events 和执行能力

当前项目没有 `codeteam/runtime/` 目录。Runtime 能力分布在多个明确模块中：

```text
codeteam/agent/        orchestration
codeteam/context/      context selection / compaction
codeteam/execution/    policy / approval / safe execution
codeteam/sandbox/      Docker boundary
codeteam/git/          worktree / patch / checkpoint
codeteam/session/      durable state / pause / resume
codeteam/evaluation/   external actor/judge evaluation
```

当前也没有 `codeteam/events/` 包；真实实现是单文件 `codeteam/events.py`，其中已有 `AgentEventType`、`AgentEvent` 和 `make_event()`。目前事件类型面向单任务、恢复、Session 和模型切换，还没有 Week5 team/worker 事件。

`codeteam/session/` 已能持久化 `TaskSpec`、`Plan`、仓库、worktree、checkpoint、usage 和 active operation，但当前 `Session` 模型没有团队成员、Assignment、Mailbox 或 DAG 状态。团队持久化必须留到 Day6 设计，今天只要求新模型可序列化。

副作用能力已经存在：

- `WorktreeManager.create(task_id, base_ref) -> WorktreeInfo`：任务级 Git 隔离。
- `SafeExecutionService.execute_command()`：Policy、Approval、Docker Sandbox 的统一命令入口。
- `SafeExecutionService.execute_patch()`：Checkpoint、Patch、Diff 的安全入口。
- `VerificationService.verify()`：结构化验证请求。
- `RepairLoop`：由验证证据驱动的有限修复。

这些都不应该在 `WorkerAgent` 里重新手写。

### 3.4 `agent_team` 当前状态

只读检查结果：

```text
codeteam/agent_team/   不存在
tests/agent_team/      不存在
```

所以 Day1 是新模块的开始。计划文档中的 `agent_team/models.py`、`lead.py`、`worker.py` 是目标结构，不是已经完成的代码。

### 3.5 计划文档需要适配的地方

原计划写到“LeadAgent 替代 SingleAgentOrchestrator”。结合当前仓库，更准确的适配是：

```text
LeadAgent 位于 SingleAgentOrchestrator 之上
而不是删除或继承它
```

原因是现有 orchestrator 已经拥有状态推进、错误分类、恢复和执行期边界。Lead 应管理团队级目标和 Assignment；Worker 才调用单 Agent 执行能力。

第二个适配点是 `LeadAgent.create_plan()` 的返回值。现有 `Plan` 没有角色分配字段，因此推荐返回一个组合对象，而不是修改旧模型：

```text
LeadPlanningResult
├── plan: Plan
└── assignments: tuple[WorkerAssignment, ...]
```

这能同时复用现有 Plan，并为 Day2 DAG 提供稳定输入。

## 4. 核心理论

### 4.1 Single Agent 与 Multi Agent 的真正边界

判断一个系统是否是 Multi-Agent Runtime，不能只数 LLM 调用了几次。更可靠的判断标准是：

- 是否存在多个可区分的执行主体。
- 每个主体是否有独立身份和状态。
- 工作是否通过结构化契约分配。
- 是否有统一的协调、冲突和完成判定机制。
- 每个主体的上下文、工具和 workspace 边界是否可控制。
- 失败后是否知道由谁恢复、重试或接管。

下面这个仍然可能只是 Single Agent：

```text
一个 Python 对象
  -> 连续调用三次 LLM
  -> 三次共享同一状态
  -> 没有身份、分配、生命周期
```

而下面才开始具备 Multi-Agent Runtime 的特征：

```text
Lead identity
  -> Assignment A -> Worker backend-1
  -> Assignment B -> Worker test-1
  -> 独立状态、上下文与执行边界
  -> 结构化结果回到 Lead
```

### 4.2 Supervisor Pattern

Supervisor 是团队控制平面。它负责：

- 理解总目标。
- 生成或审核结构化计划。
- 判断任务需要哪些角色。
- 产生 Worker Assignment。
- 汇总执行结果并决定下一步。

Supervisor 不应默认承担：

- 读取每个实现文件的全部细节。
- 直接调用 Worker 的文件和 shell 工具。
- 在多个 workspace 中亲自执行修改。
- 用自己的内存替代 Scheduler、Mailbox 和 Store。

Lead 可以在极小任务上选择不拆分，但这仍是一个显式决策，而不是悄悄自己做完所有工作。

### 4.3 Planner-Executor Pattern

Planner 回答：

```text
What should be done?
```

Executor 回答：

```text
How should this assigned unit be completed safely?
```

在当前 CodeTeam 中：

```text
Planner
  TaskSpec + RepositoryContext -> Plan

Lead role assignment
  PlanStep -> WorkerAssignment

Worker execution（后续）
  WorkerAssignment -> existing runtime -> WorkerResult
```

这种分离让规划输出可以独立校验。即使未来换成 LLM Planner，Runtime 仍然可以拒绝空 Plan、重复 ID、非法角色和无法映射的 Assignment。

### 4.4 Control Plane 与 Execution Plane

Control Plane 决定：

- 谁做。
- 做什么。
- 何时可以做。
- 当前状态是什么。
- 失败后如何处理。

Execution Plane 负责：

- 搜索和读取代码。
- 生成或应用 Patch。
- 运行测试。
- 返回结果和证据。

映射到 CodeTeam：

```text
Control Plane
  LeadAgent
  WorkerRegistry
  WorkerAssignment
  Day2 TaskDAG
  Day3 Scheduler
  Day4 Mailbox

Execution Plane
  WorkerAgent facade
  SingleAgentOrchestrator
  RepositoryInspector
  SafeExecutionService
  GitWorkspace / WorktreeManager
  VerificationService / RepairLoop
```

控制平面不能绕过执行平面的安全边界；执行平面也不能自己改写全局计划。

### 4.5 Agent Role

Role 表示职责类别，例如：

```text
LEAD
BACKEND
FRONTEND
TEST
REVIEW
GENERAL
```

它主要影响：

- Lead 如何分配任务。
- Worker 使用什么提示词和上下文。
- 评测时什么算角色分配正确。

Role 不是权限。`TEST` 角色并不自动意味着“只能运行 pytest”，`BACKEND` 也不自动意味着“可以修改任意后端文件”。真实权限仍应由：

```text
Assignment scope
  + Worktree ownership
  + CommandPolicy
  + Approval
  + SandboxProfile
```

共同决定。

### 4.6 Agent Identity

Identity 回答“到底是哪一个 Agent 实例”。它应该是稳定标识，例如：

```text
agent_id = "worker-backend-001"
```

下面三个概念不能混在一起：

```text
agent_id       谁
role           擅长/负责什么
assignment_id  这一次被派了什么工作
```

同一个 BACKEND Worker 可以先后接多个 Assignment；同一个 Assignment 在失败重分配后也可能由另一个 Worker 接手。没有稳定 identity，就无法审计“谁产生了这个 Patch”。

### 4.7 Agent Lifecycle

Day1 只需要最小状态词汇，例如：

```text
CREATED -> READY -> BUSY -> READY
                    └----> FAILED
READY -> STOPPED
```

今天不需要把所有转移规则做完，因为 Day5 会实现 heartbeat、timeout、recovering 和 reassignment。Day1 只要避免裸字符串，并让非法状态在模型构造时被拒绝。

### 4.8 Agent Boundary

Agent Boundary 至少有五种：

1. Identity Boundary：结果必须能关联具体 agent_id。
2. Context Boundary：Worker 只收到 Assignment 所需证据，不继承 Lead 全部历史。
3. Workspace Boundary：副作用最终绑定 task/worktree，而不是相信 LLM 给出的 cwd。
4. Tool Boundary：Worker 只能通过统一安全入口执行动作。
5. Ownership Boundary：一个 Assignment 或文件范围在同一时刻只能有明确 owner。

Day1 只把这些边界表达在模型和接口中；原子认领和冲突检测留给 Day3。

### 4.9 为什么结构化计划优于自然语言转发

自然语言转发：

```text
“你去看看后端，大概修一下登录，再提醒测试 Agent 测一测。”
```

机器无法稳定回答：

- Assignment ID 是什么？
- 预期产物是什么？
- 分配给哪个角色？
- 关联哪个 PlanStep？
- 验证条件是什么？
- 是否能序列化和恢复？

结构化分配则可以是：

```json
{
  "assignment_id": "A1",
  "task_id": "task-001",
  "source_step_id": "P1",
  "role": "backend",
  "goal": "修复登录超时处理",
  "expected_output": "可应用的 patch 和验证结果",
  "relevant_files": ["src/auth/service.py"],
  "verification": "pytest tests/auth -q"
}
```

它可以被校验、排序、持久化、调度和评测。

### 4.10 必须避免的错误设计

#### 错误一：多个平级 Agent 同时修改同一工作区

```text
Worker A -> repo/src/auth.py
Worker B -> repo/src/auth.py
```

没有 ownership 和 worktree 时，后写入者覆盖前者，测试结果也无法归因。正确方向是 Day3 ownership + Week3 `WorktreeManager`，而不是共享 cwd 后靠提示词约束。

#### 错误二：Lead 直接完成所有代码任务

如果 `LeadAgent` 同时有 `apply_patch()`、`run_tests()`、`repair()`，Lead 会再次变成 Single Agent，只是改了名字。Day1 应让 Lead 的 public API 只暴露规划、分配和查询。

#### 错误三：Worker 自行更改全局计划

Worker 可以报告“Assignment 无法完成”或提出新证据，但不能直接替换全局 Plan。计划版本变化应由 Lead/Replanner 统一产生，继续复用现有 `replan()` 的版本语义。

#### 错误四：只用字符串表示状态

```python
worker.status = "reday"  # 拼写错误直到运行很久后才暴露
```

使用 Enum/Pydantic 后，非法值在构造边界就会失败。

#### 错误五：Day1 把 DAG、Scheduler、Mailbox 都塞进 LeadAgent

这样会形成一个巨大类：既存图、又调度、又通信、又执行。它很难独立测试，也会让 Day2～Day4 没有清晰边界。Day1 的 Lead 只依赖 Planner、RoleAssigner 和 WorkerRegistry。

## 5. Industrial Design

### 5.1 方案比较

| 方案 | 优点 | 缺点 | 适用场景 | 对 CodeTeam 的影响 |
|---|---|---|---|---|
| 单 Agent | 架构简单；上下文和状态集中；调试成本低 | 长任务上下文膨胀；不能自然表达角色和并行 | 单点 Bug、短解释、强依赖顺序的小任务 | 保留为 Worker 执行内核和 baseline |
| 多个平级 Agent | 去中心化；局部自主性高 | 全局完成判定、冲突、资源竞争和恢复更复杂 | 对等讨论、独立研究假设 | Day1 不选作默认控制结构 |
| Lead-Worker | 全局目标和责任边界清楚；容易审计与调度 | Lead 可能成为瓶颈；错误分解会影响所有 Worker | 具有主目标和可分工作单元的 Coding Task | CodeTeam Week5 主架构 |
| Planner-Executor | 决策与副作用分开；Plan 可先校验 | 需要结构化契约；规划可能过时 | 需要安全执行和验证闸门的任务 | 复用现有 `Planner`/`Plan`，Worker 执行 |
| 共享上下文 | 信息同步简单 | Token 成本高；污染严重；容易泄露无关细节 | 小团队、短对话、信息高度耦合 | 不作为默认 Worker context |
| 独立上下文 | 隔离噪声；可专业化；成本可归因 | 需要明确 delegation packet；可能缺少关键事实 | 可分解的研究、实现和测试任务 | Worker 默认方向，Day4 用 Mailbox 补信息交换 |

### 5.2 官方公开事实

以下内容来自公开官方资料，不代表厂商未公开的内部实现：

- LangChain/LangGraph 官方 Multi-agent 文档把 subagents、handoffs、router 和 custom workflow 列为不同协调模式，并提醒并非所有复杂任务都需要 Multi-Agent；单 Agent 配合合适工具也可能足够。[官方文档](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/multi-agent-collaboration/)
- AutoGen 官方 AgentChat 提供 Teams 和多种团队模式；AutoGen Core 将 Agent Runtime 描述为负责通信、生命周期、安全边界、监控和调试的执行环境。[AgentChat](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/index.html) / [Agent Runtime](https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/framework/agent-and-agent-runtime.html)
- OpenHands 公开架构将 Agent、AgentController、State、EventStream 和 Runtime 分开；Runtime 执行 Action 并返回 Observation。这可以作为“决策与执行环境分层”的公开参考。[Runtime Architecture](https://github.com/OpenHands/docs/blob/main/openhands/usage/architecture/runtime.mdx)
- Claude Code 官方 Agent Teams 文档公开描述 team lead、独立 teammate context、shared task list 和 mailbox；同时明确 Agent Teams 仍是 experimental，并存在协调、恢复和关闭方面的已知限制。[官方文档](https://code.claude.com/docs/en/agent-teams)
- Claude Code 官方并行 Agent 文档还明确提醒：Agent Teams 本身不自动把每个 teammate 放入 worktree，因此同文件修改需要额外隔离或工作划分。[官方文档](https://code.claude.com/docs/en/agents)

### 5.3 基于公开资料的工程推断

下面是合理工程推断，不是上述项目的内部事实：

- 中央 Lead 更容易建立任务级 source of truth，但会增加单点瓶颈风险。
- 独立上下文能减少噪声，却会把“如何构造高质量 delegation packet”变成新的 Context Engineering 问题。
- 共享任务列表如果没有原子 claim，仍会产生重复执行。
- 团队并行只有在子任务相对独立时才可能抵消额外 Token 和协调成本。

### 5.4 CodeTeam 的设计选择

CodeTeam Day1 选择：

```text
Lead-Worker control structure
+
existing Planner-Executor boundary
+
structured assignments
+
independent Worker identity
+
deterministic first implementation
```

理由：

- 当前已有结构化 Task、Plan 和安全执行链，适合向上组合。
- 学习项目需要每个阶段可独立测试，不适合一开始引入异步和分布式状态。
- Day2～Day6 已为 DAG、Scheduler、Mailbox、Lifecycle、Store 分配了明确职责。
- Single Agent 仍是必须保留的 baseline；Multi-Agent 不是默认更优。

## 6. Day1 架构与数据流

### 6.1 推荐目标结构

今天建议最终形成：

```text
codeteam/agent_team/
├── __init__.py    # 只导出稳定 public API
├── models.py      # Role / Status / Identity / Assignment / PlanningResult
├── worker.py      # WorkerAgent 最小 facade + WorkerRegistry
└── lead.py        # LeadAgent + deterministic RoleAssigner

tests/agent_team/
├── __init__.py
├── test_models.py
├── test_worker.py
└── test_lead.py
```

本教程只指导你后续逐步创建；当前任务没有创建这些文件。

### 6.2 推荐领域模型

```text
AgentIdentity
├── agent_id
└── display_name

AgentInfo
├── identity: AgentIdentity
├── role: AgentRole
├── status: AgentStatus
└── capabilities: tuple[str, ...]

WorkerAssignment
├── assignment_id
├── task_id
├── source_step_id
├── role
├── goal
├── expected_output
├── relevant_files
└── verification

LeadPlanningResult
├── task_id
├── plan: existing Plan
└── assignments: tuple[WorkerAssignment, ...]
```

这里故意不加入：

- `dependencies`：Day2 Task DAG。
- `claimed_by`：Day3 Scheduler/Claim。
- `mailbox`：Day4 Communication。
- `last_heartbeat`：Day5 Lifecycle。
- `runtime_object`：永远不应进入 durable domain model。

### 6.3 数据流

```text
User Request
  -> create_task_spec()
  -> TaskSpec
  -> RepositoryInspector.inspect()
  -> RepositoryContext
  -> LeadAgent.create_plan(task, repo_context)
       -> existing Planner.create_plan()
       -> existing Plan
       -> deterministic RoleAssigner.assign(step)
       -> tuple[WorkerAssignment, ...]
  -> LeadPlanningResult
  -> WorkerRegistry.find_compatible(role)
  -> Day2 TaskDAG input
  -> Day3 Scheduler claim
  -> WorkerAgent execution facade
  -> existing Single-Agent Runtime capabilities
```

### 6.4 领域模型、服务和副作用的边界

```text
models.py
  只表达事实，不调用模型、不访问文件、不执行命令

lead.py
  只规划和分配，不 apply patch、不 run tests

worker.py
  Day1 只描述/注册 Worker；后续把 Assignment 交给执行后端

existing execution modules
  承担真实 Context、Patch、Command、Verification、Repair 副作用
```

### 6.5 deterministic 第一版与未来 LLM Planner

第一版可以使用规则映射：

```text
title/description/relevant_files 包含 test/pytest -> TEST
包含 frontend/ui/tsx                   -> FRONTEND
包含 api/service/database/backend      -> BACKEND
其他                                   -> GENERAL
```

同一个输入必须得到同一个角色。规则匹配不要依赖 set 的随机遍历顺序，应使用固定优先级。

未来替换方式：

```text
DeterministicRoleAssigner
          ↓ 实现同一个 Protocol
LLMRoleAssigner
```

Lead 不需要知道角色来自规则还是模型。这就是依赖倒置。

## 7. 分步骤学习与实现指南

> 以下代码均是后续你手动实现时的参考，不是当前仓库已完成代码。每次只做一个 Step，完成并验证后再进入下一步。

### Step 1：确定复用边界

#### 目标

先写一张“复用/新增/后续”的边界表，避免一开始创建重复模型。

#### 为什么先做

当前仓库已经有 `TaskSpec`、`Plan`、`Planner`、`TaskState`。如果直接照计划文档再写 `TeamTask`、`TeamPlan`，后面会出现两套 source of truth。

#### 涉及文件

只读：

- `codeteam/task/models.py`
- `codeteam/task/state.py`
- `codeteam/planning/models.py`
- `codeteam/planning/planner.py`
- `codeteam/agent/orchestrator.py`

计划新增：

- `codeteam/agent_team/models.py`

#### 需要掌握的 Python 知识

- import：从已有 package 引用类型。
- 类型标注：看懂函数输入输出。
- 组合优于继承：`LeadPlanningResult` 持有 `Plan`，而不是继承 `Plan`。

#### 推荐边界表

| 概念 | 处理方式 | 原因 |
|---|---|---|
| 用户任务 | 复用 `TaskSpec` | 已有校验和 Session 支持 |
| 单步计划 | 复用 `PlanStep` | 已有状态与验证字段 |
| 完整计划 | 复用 `Plan` | 已有版本和 validate gate |
| Agent role/status/identity | 新增 | 当前不存在 |
| Worker Assignment | 新增 | PlanStep 不表达角色与执行归属 |
| dependency | Day2 | 今天不实现 DAG |
| claim/owner | Day3 | 今天不实现 Scheduler |

#### 如何验证

执行只读搜索：

```bash
rg "class (TaskSpec|Plan|PlanStep|Planner|AgentRole|AgentStatus)" codeteam
```

确认没有同名 Agent Team 模型后再开始 Step2。

#### 常见错误

- 把 `TaskStatus` 当 `AgentStatus`。
- 修改已有 `PlanStep` 加十几个未来字段。
- 让 `LeadAgent` 继承 `SingleAgentOrchestrator`。

#### 完成标志

- 你能口头说明哪些类型复用、哪些新增、哪些延期。
- 没有生产文件被误改。

#### 与后续关系

这张边界表决定 Day2 DAG 的输入模型，也决定 Day6 持久化时不会出现重复 task/plan 状态。

### Step 2：设计 AgentRole、AgentStatus、AgentIdentity、AgentInfo

#### 目标

建立 Worker 可识别、可校验、可序列化的最小领域模型。

#### 为什么现在做

没有身份和状态，就无法注册 Worker；没有 Role，就无法表达 Lead 的分配结果。

#### 涉及文件

- 新增 `codeteam/agent_team/__init__.py`
- 新增 `codeteam/agent_team/models.py`

#### 需要掌握的 Python 知识

- `Enum` 与 `str, Enum`。
- Pydantic `BaseModel`。
- `Field(default_factory=...)`。
- `tuple[str, ...]`。
- `field_validator`。

#### 推荐接口

```python
from enum import Enum

from pydantic import BaseModel, field_validator


class AgentRole(str, Enum):
    LEAD = "lead"
    BACKEND = "backend"
    FRONTEND = "frontend"
    TEST = "test"
    REVIEW = "review"
    GENERAL = "general"


class AgentStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    BUSY = "busy"
    FAILED = "failed"
    STOPPED = "stopped"


class AgentIdentity(BaseModel):
    agent_id: str
    display_name: str

    @field_validator("agent_id", "display_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("identity fields must not be blank")
        return stripped


class AgentInfo(BaseModel):
    identity: AgentIdentity
    role: AgentRole
    status: AgentStatus = AgentStatus.CREATED
    capabilities: tuple[str, ...] = ()
```

#### 语法解释

`class AgentRole(str, Enum)` 同时继承 `str` 和 `Enum`：成员是固定集合，又能自然序列化成 JSON 字符串。Pydantic 构造 `AgentInfo(role="backend")` 时可以把合法字符串解析成 `AgentRole.BACKEND`；`role="database-wizard"` 会被拒绝。

`tuple[str, ...]` 表示包含任意数量字符串的元组。Capabilities 是 Agent 的描述性事实，创建后通常整体替换，不适合被某段代码悄悄 `append()`，所以 tuple 比 list 更稳。

#### 如何验证

后续测试至少检查：

```python
info = AgentInfo(
    identity=AgentIdentity(
        agent_id="worker-backend-001",
        display_name="Backend Worker 1",
    ),
    role=AgentRole.BACKEND,
)

assert info.role is AgentRole.BACKEND
assert info.model_dump(mode="json")["role"] == "backend"
```

并检查空 ID、非法 role 和非法 status 构造失败。

#### 常见错误

- `role: str` 导致任意拼写都能进入系统。
- 用 `alive: bool` 和 `busy: bool` 组合状态，产生 `alive=False, busy=True` 的矛盾。
- 在 Identity 中保存 ModelClient、Lock 或 subprocess 对象。
- capabilities 使用 `[]` 作为可变默认值。

#### 完成标志

- 四个模型可以构造、JSON 序列化和反序列化。
- 非法固定值在构造时被拒绝。
- 没有 DAG、Mailbox、heartbeat 字段。

#### 与后续关系

Day3 Scheduler 用 AgentStatus 判断 Worker 是否可分配；Day5 扩展生命周期；Day6 将 AgentInfo 作为 durable projection，而不是保存 WorkerAgent 对象。

### Step 3：设计 WorkerAssignment 与 LeadPlanningResult

#### 目标

把“计划步骤”和“由哪类 Worker 完成”连接起来，同时保留已有 `Plan` 为 source of truth。

#### 为什么现在做

只有 AgentInfo 仍然没有工作契约。自然语言派活无法被 Day2 DAG 和 Day3 Scheduler消费。

#### 涉及文件

- 修改 `codeteam/agent_team/models.py`

#### 需要掌握的 Python 知识

- 模型嵌套。
- `tuple` 不可变容器。
- 结构化返回值。
- Pydantic `model_validator`，如确实需要跨字段校验。

#### 推荐接口

```python
from codeteam.planning.models import Plan


class WorkerAssignment(BaseModel):
    assignment_id: str
    task_id: str
    source_step_id: str
    role: AgentRole
    goal: str
    expected_output: str
    relevant_files: tuple[str, ...] = ()
    verification: str | None = None


class LeadPlanningResult(BaseModel):
    task_id: str
    plan: Plan
    assignments: tuple[WorkerAssignment, ...]
```

建议的 Day1 不变量：

- assignments 非空。
- assignment_id 唯一。
- 每个 Assignment 的 `task_id` 等于 result.task_id。
- 每个 `source_step_id` 能在 `plan.steps` 中找到。
- 每个 PlanStep 恰好产生一个 Assignment。

最后一条是 Day1 的简单假设。Day2 如果需要一个 Step 拆成多个 DAG Node，再通过显式转换扩展，不要今天提前做复杂映射。

#### 参考跨字段校验思路

```python
from pydantic import model_validator


class LeadPlanningResult(BaseModel):
    task_id: str
    plan: Plan
    assignments: tuple[WorkerAssignment, ...]

    @model_validator(mode="after")
    def _check_consistency(self) -> "LeadPlanningResult":
        step_ids = {step.step_id for step in self.plan.steps}
        assignment_step_ids = {
            item.source_step_id for item in self.assignments
        }

        if self.plan.task_id != self.task_id:
            raise ValueError("plan.task_id must match result.task_id")
        if not self.assignments:
            raise ValueError("assignments must not be empty")
        if assignment_step_ids != step_ids:
            raise ValueError("assignments must cover every plan step")
        return self
```

这里返回 `self`，因为 `mode="after"` 表示对象字段已经解析完成，validator 检查整个对象后把它返回。

#### 如何验证

- 合法 Plan + 完整 assignments 可构造。
- 空 assignments 被拒绝。
- 错误 task_id 被拒绝。
- 指向不存在 PlanStep 的 assignment 被拒绝。
- 重复 assignment_id 被拒绝。

#### 常见错误

- 在 Assignment 中存 `WorkerAgent` 对象。
- 直接在 PlanStep 上写 `worker_id`，把 Planner 输出和运行时 claim 混在一起。
- Day1 加 dependencies，提前复制 Day2 的职责。

#### 完成标志

- 一个 `LeadPlanningResult` 完整表达“已有 Plan + 每步推荐角色”。
- 它可以 `model_dump_json()`。

#### 与后续关系

Day2 将 Assignment 转成 DAG Node；Day3 才把具体 worker_id 写入 claim/ownership 状态。

### Step 4：设计 WorkerAgent 最小接口和注册语义

#### 目标

让 Worker 能被注册、查找和描述，但 Day1 不执行真实任务。

#### 为什么现在做

Lead 有 Assignment 后，需要知道系统有哪些 Worker。注册表是最小发现机制；Scheduler 尚未实现，所以注册表不能顺便 claim 任务。

#### 涉及文件

- 新增 `codeteam/agent_team/worker.py`

#### 需要掌握的 Python 知识

- class、实例和构造函数。
- `dict[str, WorkerAgent]`。
- property。
- 自定义异常。
- 依赖注入的最小概念。

#### 推荐接口

```python
class DuplicateWorkerError(ValueError):
    pass


class WorkerNotFoundError(LookupError):
    pass


class WorkerAgent:
    def __init__(self, info: AgentInfo) -> None:
        if info.role is AgentRole.LEAD:
            raise ValueError("WorkerAgent cannot use the lead role")
        self._info = info

    @property
    def info(self) -> AgentInfo:
        return self._info

    def supports(self, role: AgentRole) -> bool:
        return self._info.role is role


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerAgent] = {}

    def register(self, worker: WorkerAgent) -> None:
        worker_id = worker.info.identity.agent_id
        if worker_id in self._workers:
            raise DuplicateWorkerError(worker_id)
        self._workers[worker_id] = worker

    def get(self, worker_id: str) -> WorkerAgent:
        try:
            return self._workers[worker_id]
        except KeyError as exc:
            raise WorkerNotFoundError(worker_id) from exc

    def compatible(self, role: AgentRole) -> tuple[WorkerAgent, ...]:
        return tuple(
            worker
            for worker in self._workers.values()
            if worker.supports(role)
        )
```

#### 语法解释

`dict[str, WorkerAgent]` 用 agent_id 做键，因此查找平均是 O(1)。注册前先判断 key 是否存在，可以明确拒绝重复 ID。不要默默覆盖，因为覆盖会让旧 Worker 的 Assignment 和审计记录突然指向另一个对象。

`raise ... from exc` 保留原始 KeyError 作为异常链，同时向上层提供更符合领域语义的错误。

#### Day1 为什么不写 `execute()`

可以保留未来执行协议的设计草图，但不要用 `pass` 假装已实现：

```python
class WorkerExecutor(Protocol):
    def execute(self, assignment: WorkerAssignment) -> WorkerResult:
        ...
```

Day1 的 `WorkerAgent` 只承担 identity/role facade。Day3 以后再注入 executor，executor 内部复用现有 Single-Agent Runtime 和 SafeExecutionService。

#### 如何验证

- 注册一个 Worker 后 `get()` 返回同一个对象。
- 重复 ID 抛 `DuplicateWorkerError`。
- 未知 ID 抛 `WorkerNotFoundError`。
- `compatible(AgentRole.TEST)` 只返回 TEST Worker。
- LEAD role 不能注册成 Worker。

#### 常见错误

- 重复 ID 时覆盖旧 Worker。
- Registry 顺便做 Scheduler 的 claim 和状态机。
- Worker 直接暴露 `subprocess.run`、`DockerRunner` 或 `GitWorkspace`。

#### 完成标志

- Worker 可以注册、按 ID 查找、按角色过滤。
- Registry 不执行 Assignment。

#### 与后续关系

Day3 Scheduler 消费 Registry 的可用 Worker；Day5 Lifecycle Registry 可能扩展 heartbeat，但今天不实现。

### Step 5：设计 LeadAgent 的结构化 `create_plan()` 契约

#### 目标

让 Lead 复用现有 Planner 生成 Plan，再为每个 PlanStep 生成 WorkerAssignment。

#### 为什么现在做

领域模型和 Worker 注册边界稳定后，Lead 才有可靠输入输出。否则 Lead 会被迫返回临时 dict 或自然语言。

#### 涉及文件

- 新增 `codeteam/agent_team/lead.py`

#### 需要掌握的 Python 知识

- `Protocol`。
- 构造函数依赖注入。
- 组合对象。
- 纯函数式映射。

#### 推荐接口

```python
from typing import Protocol

from codeteam.planning.models import PlanStep
from codeteam.planning.planner import Planner, RepositoryContext
from codeteam.task.models import TaskSpec


class RoleAssigner(Protocol):
    def assign(self, step: PlanStep) -> AgentRole:
        ...


class LeadAgent:
    def __init__(
        self,
        *,
        info: AgentInfo,
        planner: Planner,
        role_assigner: RoleAssigner,
    ) -> None:
        if info.role is not AgentRole.LEAD:
            raise ValueError("LeadAgent requires the lead role")
        self._info = info
        self._planner = planner
        self._role_assigner = role_assigner

    def create_plan(
        self,
        *,
        task: TaskSpec,
        repo_context: RepositoryContext,
    ) -> LeadPlanningResult:
        plan = self._planner.create_plan(
            task=task,
            repo_context=repo_context,
        )
        assignments = tuple(
            self._assignment_for(task, step)
            for step in plan.steps
        )
        return LeadPlanningResult(
            task_id=task.task_id,
            plan=plan,
            assignments=assignments,
        )
```

`_assignment_for()` 应是 Lead 内部 helper：根据 `RoleAssigner` 的结果，把已有 PlanStep 字段投影成 WorkerAssignment。它不能调用 Worker 工具。

#### 为什么不让 Lead 继承 Planner

Lead 不只是 Plan 生成器，它还负责团队级分配；Planner 只是 Lead 的一个依赖。使用组合关系：

```text
LeadAgent has a Planner
```

比下面更准确：

```text
LeadAgent is a Planner
```

#### 如何验证

- 注入 `MockPlanner`，Lead 返回相同 Plan。
- 每个 PlanStep 对应一个 Assignment。
- Lead identity 不是 LEAD 时构造失败。
- Fake RoleAssigner 的调用次数等于 step 数量。
- `LeadAgent` 没有 `execute`、`apply_patch`、`run_command` 等 public method。

#### 常见错误

- Lead 直接构造模型 prompt，绕过已有 Planner 协议。
- Lead 自己调用 RepositoryInspector；这样职责可行但测试耦合更大。Day1 推荐由上层先提供 `RepositoryContext`，保持 create_plan 纯净。
- Lead 在 create_plan 时提前选择具体 worker_id。具体选择属于 Scheduler。

#### 完成标志

- `create_plan()` 返回 `LeadPlanningResult`。
- Lead 不产生副作用。
- 现有 Planner 可无修改注入。

#### 与后续关系

Day2 读取 `LeadPlanningResult.assignments` 构造 DAG；Day7 上层应用服务再把 RepositoryInspector、Lead、DAG 和 Scheduler 串起来。

### Step 6：实现 deterministic/rule-based RoleAssigner

#### 目标

建立一个不调用真实 LLM、同输入同输出、可作为 baseline 的角色分配器。

#### 为什么现在做

如果 Day1 就接真实模型，失败时难以区分是领域模型、Lead 编排还是模型输出问题。确定性规则先验证 Runtime 契约。

#### 涉及文件

- 修改 `codeteam/agent_team/lead.py`

#### 需要掌握的 Python 知识

- 字符串标准化 `casefold()`。
- tuple 常量。
- 固定优先级循环。
- `any()`。

#### 参考实现

```python
class DeterministicRoleAssigner:
    _RULES: tuple[tuple[AgentRole, tuple[str, ...]], ...] = (
        (AgentRole.TEST, ("test", "pytest", "fixture", "regression")),
        (AgentRole.FRONTEND, ("frontend", "ui", ".tsx", ".jsx")),
        (
            AgentRole.BACKEND,
            ("backend", "api", "service", "database", "repository"),
        ),
        (AgentRole.REVIEW, ("review", "audit", "security")),
    )

    def assign(self, step: PlanStep) -> AgentRole:
        evidence = " ".join(
            (
                step.title,
                step.description,
                *step.relevant_files,
                step.verification or "",
            )
        ).casefold()

        for role, keywords in self._RULES:
            if any(keyword in evidence for keyword in keywords):
                return role

        return AgentRole.GENERAL
```

#### 语法解释

`*step.relevant_files` 是 iterable unpacking：把元组里的每个路径作为独立字符串放进外层 tuple。

`casefold()` 比 `lower()` 更适合不区分大小写的文本匹配。它仍然不是语义分类器，所以中文关键词要么显式加入规则，要么在 Failure Case 中承认覆盖不足。

规则顺序就是冲突优先级。例如一个步骤既包含 `api` 又包含 `pytest`，当前规则会分给 TEST。这个选择必须进入测试和 DD，不应依赖 dict/set 的偶然顺序。

#### 如何验证

- 同一个 PlanStep 连续调用 100 次结果相同。
- 测试步骤 -> TEST。
- `.tsx` -> FRONTEND。
- API/service -> BACKEND。
- 无关键词 -> GENERAL。
- 冲突关键词遵循固定优先级。

#### 常见错误

- 用 set 保存规则后假设顺序稳定。
- 没有 GENERAL fallback，遇到未知任务返回 None。
- 把 role classifier 结果直接当权限 grant。

#### 完成标志

- 不调用模型、不访问文件。
- 对所有 PlanStep 总能返回合法 AgentRole。
- 行为确定、优先级有测试。

#### 与后续关系

它是周末 Benchmark 的 deterministic baseline；未来 `LLMRoleAssigner` 必须在相同任务集和相同指标下比较。

### Step 7：补充 Day1 测试

#### 目标

用测试证明领域模型、注册语义、Lead 边界和确定性规划成立。

#### 为什么现在做

没有测试，Day2 在这些模型上构建 DAG 后，一旦失败很难判断根因来自 Day1 还是 Day2。

#### 涉及文件

- 新增 `tests/agent_team/__init__.py`
- 新增 `tests/agent_team/test_models.py`
- 新增 `tests/agent_team/test_worker.py`
- 新增 `tests/agent_team/test_lead.py`

#### 需要掌握的 Python 知识

- pytest 普通测试函数。
- `pytest.raises()`。
- Fake/Stub 依赖。
- 参数化 `@pytest.mark.parametrize`。

#### 推荐验证命令

```bash
.venv/bin/python -m pytest tests/agent_team -q
.venv/bin/python -m pytest tests/task tests/planning tests/agent -q
.venv/bin/python -m pytest -q
```

静态检查命令应根据仓库当前 gate 使用：

```bash
.venv/bin/python -m ruff check codeteam/agent_team tests/agent_team
.venv/bin/python -m mypy codeteam/agent_team tests/agent_team
```

如果全项目 mypy 因历史 import-chain 债务失败，要区分本次文件错误和历史错误，不能声称完全通过。

#### 常见错误

- 只测 happy path。
- 为了测试方便给 Lead 增加执行方法。
- Mock 所有东西，连纯领域模型都不真正构造。
- 测试断言自然语言完整句子，导致无意义脆弱性。

#### 完成标志

- 测试地图第9节的 Day1 必须项都有证据。
- 现有 Single-Agent 测试不回归。

#### 与后续关系

Day2 可以把 Day1 测试作为前置 gate；任何 DAG 失败先确认 `tests/agent_team` 仍是绿色。

### Step 8：记录 DD、Failure Cases 和周末实验计划

#### 目标

把今天的判断和未验证假设持久化，而不是只留在聊天中。

#### 为什么现在做

Lead-Worker 是架构选择，不是语法选择。它必须记录备选方案、风险和未来证据，否则面试时容易只剩“因为常见所以选它”。

#### 涉及文件

后续经你确认再创建：

- `docs/design_decisions/DD-W5-01.md`
- 建议沿用项目文档风格记录 Failure Cases；当前仓库没有独立 `docs/failure_cases/` 目录，不要未经确认擅自创建。
- 建议周末结果放入 `evals/week5/`；当前该目录尚不存在。

#### 需要掌握的知识

- 设计决策与实现事实的区别。
- Tests、Benchmark、Ablation、Failure Case 的区别。
- 可复现性 manifest。

#### 如何验证

检查 DD 中 Evidence 是否诚实标为 `PROPOSED`，Benchmark/Ablation 是否标为 `PLANNED / NOT_RUN`。

#### 常见错误

- 测试通过就写成“Lead-Worker 性能更高”。
- 没跑实验却填写虚构延迟。
- 把 Peer Agents 描述成完全错误；它只是当前 CodeTeam 不选的 trade-off。

#### 完成标志

- DD 草案字段完整。
- 三个必选 Failure Case 有最小复现和预期信号。
- 周末实验已定义任务集、指标和 manifest 字段，但没有伪造结果。

#### 与后续关系

Day7 使用这些记录解释完整 Agent Team 的收益与局限。

## 8. Python 知识讲解

### 8.1 Enum：固定词汇表

`Enum` 适合角色和状态，因为它把可选值收窄成有限集合：

```python
class AgentRole(str, Enum):
    LEAD = "lead"
    TEST = "test"
```

代码内部比较推荐：

```python
if info.role is AgentRole.TEST:
    ...
```

序列化或展示时使用：

```python
info.role.value  # "test"
```

不要在 Runtime 内到处比较 `"test"`，否则拼写错误无法被类型和模型校验及时发现。

### 8.2 dataclass 还是 BaseModel

当前仓库的选择规律很清楚：

- 外部输入、模型输出、需要 JSON 持久化的数据，多数使用 Pydantic `BaseModel`，例如 `TaskSpec`、`Plan`、`Session`。
- 纯内部、由可信代码构造的轻量对象，可能使用 `@dataclass`，例如 `RepositoryContext`、`AgentEvent`。

Day1 的 `AgentInfo`、`WorkerAssignment` 和 `LeadPlanningResult` 将来要进入 Session/Event/Eval，因此推荐 `BaseModel`。`WorkerAgent` 和 `WorkerRegistry` 是带行为的运行时对象，用普通 class 更合适。

### 8.3 类型标注

```python
def compatible(self, role: AgentRole) -> tuple[WorkerAgent, ...]:
```

含义：

- `role: AgentRole`：调用方必须传角色枚举。
- `-> tuple[WorkerAgent, ...]`：返回任意数量 WorkerAgent 组成的元组。

类型标注本身不会自动阻止所有运行时错误，但 ruff/mypy、IDE 和读代码的人都能利用它。外部数据仍需要 Pydantic 运行时校验。

### 8.4 Protocol：按行为依赖

```python
class RoleAssigner(Protocol):
    def assign(self, step: PlanStep) -> AgentRole:
        ...
```

任何具有相同 `assign()` 方法形状的对象都可注入 Lead，无需显式继承：

```python
LeadAgent(role_assigner=DeterministicRoleAssigner(), ...)
LeadAgent(role_assigner=LLMRoleAssigner(...), ...)
```

这与当前 `Planner(Protocol)` 的写法一致。Protocol 适合表达依赖边界，不适合拿来存运行状态。

### 8.5 list、dict、tuple 和不可变集合

- `dict[str, WorkerAgent]`：按 ID 高频查找，适合 Registry 内部。
- `tuple[WorkerAssignment, ...]`：输出快照，顺序稳定，不希望原地 append。
- `list[AgentEvent]`：运行时不断追加事件，适合可变序列。
- `frozenset[str]`：如果只关心 membership、不关心顺序且创建后不变，可以用于 capability key；但 JSON 展示和稳定顺序不如 tuple 直观。

### 8.6 默认值与 default_factory

错误：

```python
class Registry:
    def __init__(self, workers: dict = {}):
        self.workers = workers
```

这个 dict 会被多个实例共享。

普通 class 应在构造函数中创建：

```python
self._workers: dict[str, WorkerAgent] = {}
```

dataclass 使用：

```python
workers: dict[str, WorkerAgent] = field(default_factory=dict)
```

Pydantic 使用：

```python
items: list[str] = Field(default_factory=list)
```

### 8.7 标识符与状态枚举

标识符是稳定关联键，不是显示名称：

```text
agent_id="worker-test-001"     稳定、机器使用
display_name="Test Worker 1"  可展示、允许改变
```

状态枚举表达当前事实。不要把状态编码进 ID，例如 `running-worker-1`，因为状态变化后 ID 不应变化。

### 8.8 结构化返回值

返回 dict：

```python
return {"plan": plan, "assignments": assignments}
```

短期方便，但调用方可以拼错 key，也不清楚字段是否必需。

返回 `LeadPlanningResult`：

```python
return LeadPlanningResult(
    task_id=task.task_id,
    plan=plan,
    assignments=assignments,
)
```

能在构造时检查跨字段一致性，并生成 JSON Schema，为未来模型输出和持久化提供契约。

### 8.9 依赖注入

依赖注入不是复杂框架。最简单的含义是：对象不在内部写死依赖，而是由外部传入。

```python
lead = LeadAgent(
    info=lead_info,
    planner=MockPlanner(plan=plan),
    role_assigner=DeterministicRoleAssigner(),
)
```

测试可注入 MockPlanner，生产可注入 LLMPlanner，Lead 代码不需要改。

### 8.10 同步接口与未来异步接口

Day1 推荐同步：

```python
def create_plan(...) -> LeadPlanningResult:
```

因为今天没有并发 I/O，异步只会增加教学和测试复杂度。Day3 Scheduler 出现并发 Worker 后，再决定哪些边界需要 `async def`。不要为了“Multi-Agent 看起来应该异步”就提前让所有模型变成 coroutine。

未来同步到异步的关键是保持领域模型不变：`WorkerAssignment`、`AgentInfo` 和 `LeadPlanningResult` 不依赖调用方式。

## 9. Test Strategy

本节只给测试地图，当前教程任务不创建测试文件。

| 测试场景 | 推荐断言 | 证明的验收要求 |
|---|---|---|
| Lead 生成非空结构化计划 | `result.plan.steps` 和 `result.assignments` 非空 | Lead 能产生机器可消费输出 |
| 相同输入产生确定性结果 | 连续多次结果 `model_dump()` 相等 | deterministic baseline 可复现 |
| Worker 注册成功 | `registry.get(id) is worker` | Worker identity 可发现 |
| 重复 worker id | 抛 `DuplicateWorkerError`，旧对象仍保留 | identity 唯一且不被静默覆盖 |
| Role 保存/读取 | JSON round-trip 后仍是同一枚举 | role 可持久化 |
| 非法 role/status | Pydantic 构造失败 | 固定状态不能被任意字符串污染 |
| 空任务 | `TaskSpec` 在 Lead 前拒绝；Planner 调用数为0 | 坏输入不消耗规划资源 |
| 空 Plan | `LeadPlanningResult` 或现有 `validate_plan` 拒绝 | F-W5-D1-01 可观测 |
| 无法分解 | 返回结构化 failure/抛专用错误，不返回空成功 | F-W5-D1-03 fail closed |
| 错误角色分配 | gold role 与 assignment.role 对比失败 | F-W5-D1-02 可评测 |
| Assignment 指向不存在步骤 | 模型构造失败 | Plan 与分配不漂移 |
| Lead 不执行工具 | Fake executor invocation count 为0；Lead 无执行 API | 控制平面不穿透执行平面 |
| Worker 使用 LEAD role | 构造或注册拒绝 | Lead/Worker 边界明确 |
| 模型可序列化 | JSON round-trip 等价 | 为 Day6 durable state 做准备 |
| 现有 Single-Agent 回归 | `tests/task tests/planning tests/agent` 全通过 | 新模块没有破坏旧执行内核 |

### 9.1 为什么不能只测类能实例化

“能实例化”只证明语法没错，不能证明系统边界。Day1 最重要的测试反而是负向断言：

- 重复 ID 不覆盖。
- 空 Plan 不被当成功。
- Lead 不调用执行后端。
- 非法角色不能进入系统。
- Assignment 与 Plan 不一致时拒绝。

### 9.2 当前不适用的测试类别

- 并发 claim：Day3。
- Mailbox 顺序与丢失：Day4。
- heartbeat 超时：Day5。
- 跨进程 team resume：Day6。
- 真实 Agent Team task success：Day7。

今天不应为了“测试全面”而先实现这些能力。

## 10. Design Decision

### DD-W5-01: Why Lead-Worker Architecture Instead of Peer Agents

后续文档建议沿用 `docs/design_decisions/DD-W4-D4-01.md` 的结构。

#### Context

CodeTeam 已有可靠 Single-Agent Runtime，但复杂任务需要多个独立执行主体。系统需要决定由谁维护全局目标、生成分配、处理结果和判断完成。

#### Problem

多个 Worker 如果完全平级，会带来：

- 没有单一计划 source of truth。
- 任务和文件 ownership 冲突。
- 完成与失败无法统一判定。
- 恢复和审计链路复杂。

#### Requirements

- 复用现有 `TaskSpec`、`Plan` 和 Single-Agent Runtime。
- 分配必须结构化、可校验、可序列化。
- Lead 不直接拥有 Worker 的副作用能力。
- 后续可接 DAG、Scheduler、Mailbox 和 Store。
- 保留 Single-Agent baseline。

#### Alternatives

Option A：继续使用 Single Agent。

- 优点：简单、便宜、容易调试。
- 缺点：不能表达多 Worker identity、角色与并行。

Option B：Peer Agents。

- 优点：局部自主、去中心化、适合对等讨论。
- 缺点：全局状态、冲突、终止和恢复更复杂。

Option C：Lead-Worker。

- 优点：全局目标、任务分配和审计边界清楚。
- 缺点：Lead 可能成为瓶颈；错误分解会放大影响。

Option D：纯静态 Planner-Executor workflow。

- 优点：最确定，容易执行固定流程。
- 缺点：运行中动态调整和 Worker 生命周期表达较弱。

#### Decision

选择 Lead-Worker 作为 Week5 默认控制结构，同时：

- 复用现有 Planner-Executor 作为规划/执行边界。
- Day1 使用 deterministic RoleAssigner。
- Single-Agent 保留为简单任务路径和评测 baseline。
- Peer-agent routing 作为 Ablation 对照，不描述为错误方案。

#### Consequences

正面：

- 责任和审计更清楚。
- 可以逐步接入 Day2～Day6 的基础设施。
- Lead 和 Worker 可以独立测试。

代价：

- 多一层结构化模型和协调开销。
- 角色分配可能错误。
- Lead 需要避免成为执行和状态的“大泥球”。

#### Risks

- Lead 过度拆分，导致子任务太细、Token 和调度成本上升。
- Lead 欠拆分，Multi-Agent 没有收益。
- Rule-based role assignment 对中文和跨层任务识别不足。
- 一个 Lead 可能成为单点失败和吞吐瓶颈。

#### Rejected alternatives

当前拒绝“无中央 source of truth 的 Peer Agents”作为默认架构，但不否认未来在 review、辩论或独立假设验证中局部使用。

当前不选择“Day1 一次性实现完整 team runtime”，因为这会把 DAG、调度、通信、恢复耦合在一起，无法分阶段验证。

#### Evidence currently available

- 当前 Single-Agent 模块和测试证明了执行内核可被复用。
- 当前 Worktree、SafeExecution、Session、Events 提供未来团队运行所需基础原语。
- 公开系统表明 Lead/Subagent、Team、Selector、Graph 等是常见但不同的协调模式。

#### Evidence still missing

- Lead-Worker 是否提升 CodeTeam 的 task success。
- 额外 Token/cost 是否值得。
- Role-aware decomposition 是否优于 role-unaware。
- Lead 是否成为 latency bottleneck。
- Peer routing 在特定任务上是否更优。

因此 DD 初始应写：

```text
Evidence status: PROPOSED
```

不能在 Day1 写成 `SUPPORTED`。

## 11. Benchmark 与 Ablation 计划

### 11.1 Benchmark 要回答的问题

Day1 Benchmark 不是测“多个 Worker 最终写代码多快”，因为 Day1 还没有 Scheduler 和执行链。它只回答规划层问题：

1. Lead 能否稳定产生非空、合法的结构化分配？
2. deterministic planner/assigner 的延迟和输出规模是多少？
3. 角色分配对人工标注任务是否正确？
4. 同一输入是否可复现？

### 11.2 deterministic baseline

Baseline：

```text
existing deterministic/fixed Plan
+
DeterministicRoleAssigner
```

它不调用真实模型，目的不是追求高语义准确率，而是提供可复现的 Runtime baseline。

### 11.3 任务集构成

建议准备至少 20 个任务，而不是只用 3 个示例：

- 5 个后端/API/数据库任务。
- 4 个前端/UI 任务。
- 5 个测试/回归任务。
- 3 个 review/security 任务。
- 3 个跨层或无法明确分类的任务。

每条数据至少包含：

```json
{
  "case_id": "w5d1-001",
  "request": "为登录超时增加回归测试",
  "expected_roles": ["test"],
  "expected_min_steps": 1,
  "notes": "测试角色优先于 backend 关键词"
}
```

### 11.4 指标

```text
task_decomposition_latency_ms
subtask_count
role_assignment_accuracy
empty_plan_rate
invalid_plan_rate
determinism_rate
```

定义：

- role_assignment_accuracy = 正确角色 Assignment 数 / 有 gold role 的 Assignment 数。
- empty_plan_rate = 空 Plan case 数 / 总 case 数。
- invalid_plan_rate = 未通过领域校验 case 数 / 总 case 数。
- determinism_rate = 同一输入重复 N 次后完全一致的 case 数 / 总 case 数。

Latency 至少记录 P50/P95，而不是只报平均值。

### 11.5 可复现性字段

Manifest 建议记录：

```text
git_commit
dirty
python_version
dataset_path
dataset_sha256
planner_name
role_assigner_name
rule_version
random_seed
warmup_runs
iterations
started_at
```

### 11.6 结果位置建议

当前仓库已有 `evals/week4/` 的 dataset/raw result/report 风格。经你确认后，Week5 可沿用：

```text
evals/week5/day1/
├── decomposition_cases.jsonl
├── deterministic_baseline.jsonl
├── manifest.json
└── REPORT.md
```

当前状态必须标记：

```text
Benchmark: PLANNED / NOT_RUN
```

### 11.7 Ablation 计划

#### A1：Lead-Worker vs peer-agent routing

- Full：Lead 统一生成 Assignment。
- Ablated：每个 Peer 自行选择是否接任务，再汇总。
- 控制变量：相同任务集、模型、上下文、预算和角色集合。
- 指标：invalid assignment、duplicate ownership、completion rate、Token、latency。
- 当前：`PLANNED / NOT_RUN`。

#### A2：structured plan vs free-text plan

- Full：`LeadPlanningResult`。
- Ablated：自然语言步骤，经额外 parser 转换。
- 控制变量：相同 planner output budget 和任务集。
- 指标：parse failure、missing field、invalid-plan rate、repair-to-valid 次数。
- 当前：`PLANNED / NOT_RUN`。

#### A3：role-aware vs role-unaware decomposition

- Full：每个 Assignment 含 AgentRole。
- Ablated：统一分给 GENERAL Worker。
- 指标：role accuracy、后续任务成功率、context tokens、工具拒绝率。
- 当前：`PLANNED / NOT_RUN`。

#### A4：deterministic planner vs LLM planner

- Full/Variant 的命名要在实验前固定，避免把预期更好的方案默认叫 Full。
- 控制变量：相同 repository context、TaskSpec、schema 和评测集。
- 指标：valid plan rate、role accuracy、latency、input/output tokens、cost。
- 当前：`PLANNED / NOT_RUN`。

### 11.8 为什么今天不运行这些实验

Day1 生产模型、Lead 和测试尚未由你逐步实现。现在执行只能测教程里的伪代码，没有工程意义。正确顺序是：

```text
Correctness
  -> Reliability
  -> Observability
  -> Benchmark
  -> Ablation
```

## 12. Failure Cases

### F-W5-D1-01 Empty Plan

#### 触发条件

Planner 返回 `steps=()`，或 Lead 生成零个 Assignment。

#### 最小复现输入

```text
任务：修复登录问题
Planner output：{"steps": []}
```

#### 预期行为

- 现有 `validate_plan()` 或 `create_plan()` 拒绝。
- Lead 不返回成功的 `LeadPlanningResult`。
- 不进入 WorkerRegistry、Scheduler 或执行后端。
- 事件/错误中有稳定失败类型或 reason。

#### 错误行为

- 把空 Plan 当成“没有工作，所以已完成”。
- 返回 `READY`。

#### 可观测信号

```text
plan_step_count = 0
assignment_count = 0
failure_code = empty_plan
executor_invocations = 0
```

#### 初步原因

- Planner 无法理解任务。
- 模型 JSON 虽合法但语义为空。
- Lead 过滤 Assignment 时误删全部步骤。

#### 处理策略

Day1 fail closed，返回专用规划失败。未来可以触发 clarification 或 replan，但不能自动宣布成功。

#### 后续测试/评测

- 单元测试注入空 Plan。
- Benchmark 记录 `empty_plan_rate`。

### F-W5-D1-02 Wrong Role

#### 触发条件

RoleAssigner 把测试步骤分给 FRONTEND，或把 UI 步骤分给 BACKEND。

#### 最小复现输入

```text
PlanStep.title = "Add regression test for API timeout"
expected_role = TEST
actual_role = BACKEND
```

#### 预期行为

- Assignment 结构仍合法，但 Evaluation 判为角色错误。
- 不应因为 Role 是合法枚举就把语义判断成正确。
- 后续 Scheduler 可选择 GENERAL fallback 或请求 Lead 重新分配。

#### 错误行为

- 仅检查 role 字段存在，就宣称分配正确。
- Role 直接提升权限，错误 Worker 获得越界能力。

#### 可观测信号

```text
assignment_id
source_step_id
assigned_role
expected_role
matched_rule
```

#### 初步原因

- 关键词冲突优先级错误。
- 中文任务未被规则覆盖。
- relevant_files 缺失导致证据不足。

#### 处理策略

Day1 使用 GENERAL fallback，保留 matched rule 以便评测；Role 不直接映射权限。

#### 后续测试/评测

- 参数化 role cases。
- 人工 gold role 数据集计算 accuracy/confusion matrix。

### F-W5-D1-03 Cannot Decompose

#### 触发条件

任务过于含糊，或所有可用证据不足以形成可执行步骤。

#### 最小复现输入

```text
“把项目弄好一点”
```

#### 预期行为

- 不伪造具体文件和步骤。
- 返回结构化 cannot-decompose failure，或后续 `needs_user_input`。
- Worker 调用次数为0。

#### 错误行为

- 随机选择文件并开始修改。
- 生成看似完整但无验证标准的计划。

#### 可观测信号

```text
decomposition_status = failed
reason = insufficient_goal_or_evidence
worker_invocations = 0
```

#### 初步原因

- TaskSpec.goal 太宽泛。
- RepositoryContext 没有相关证据。
- deterministic planner 没有 fallback contract。

#### 处理策略

Day1 明确失败；未来 Lead 可以产生用户澄清请求。不要把 Ask User、Mailbox 或 Replan 逻辑提前塞入 Day1。

#### 后续测试/评测

- 模糊任务 corpus。
- 统计 cannot-decompose rate 和错误自信计划率。

### F-W5-D1-04 Duplicate Worker Identity

#### 触发条件

两个 Worker 使用同一个 `agent_id` 注册。

#### 最小复现输入

```text
worker A id = worker-test-001
worker B id = worker-test-001
```

#### 预期行为

- 第二次注册抛 `DuplicateWorkerError`。
- 第一个 Worker 保持不变。
- 不产生覆盖副作用。

#### 错误行为

- dict 赋值静默覆盖。
- 旧 Assignment 的审计归属被改写。

#### 可观测信号

```text
duplicate_agent_id
registry_size_before
registry_size_after
```

#### 初步原因

- 缺少唯一性检查。
- 把 display_name 当稳定 ID。

#### 处理策略

注册阶段 fail fast；Day6 持久化时同样校验唯一 ID。

#### 后续测试/评测

Registry 回归测试，并断言旧对象仍可读取。

### F-W5-D1-05 Lead Executes Worker Side Effects

#### 触发条件

Lead 的 `create_plan()` 直接调用 Patch、CommandRunner 或 Worker executor。

#### 最小复现输入

给 Lead 注入一个带调用计数的 FakeExecutor，调用 `create_plan()`。

#### 预期行为

```text
executor.calls == 0
workspace unchanged
```

#### 错误行为

规划期间文件已经被修改，Plan 尚未校验就发生副作用。

#### 可观测信号

```text
phase = planning
backend_invocations
changed_files
```

#### 初步原因

Control Plane 与 Execution Plane 耦合。

#### 处理策略

Lead public API 只返回结构化结果；执行能力通过后续 Scheduler/Worker 注入，Lead 不持有 raw runner。

#### 后续测试/评测

Fake backend invocation count + git diff 零变化测试。

## 13. Interview Questions 与 Interview Story

### 13.1 基础原理问题

#### Q1：多个 LLM 调用为什么不等于 Multi-Agent？

因为 Multi-Agent 的关键是独立 identity、state、assignment、context boundary、lifecycle 和 coordination。一个对象连续调用多个模型但共享同一状态，仍可能只是单 Agent 的多次推理。

#### Q2：Role 和 Identity 有什么区别？

Identity 表示“谁”，Role 表示“负责什么”。多个 Worker 可以拥有相同 Role，但 agent_id 必须唯一。

#### Q3：Role 和权限为什么不能绑定成一个字段？

Role 是规划语义，权限是安全决策。实际能力还取决于 task scope、worktree ownership、CommandPolicy、Approval 和 Sandbox。错误 role assignment 不应自动带来越权。

### 13.2 架构设计问题

#### Q4：为什么 Lead 不能直接执行所有任务？

如果 Lead 同时规划和执行，它会重新承担所有局部上下文、副作用和恢复责任，Lead-Worker 只剩命名差异。Lead 应管理全局目标，Worker 复用受控执行内核。

#### Q5：为什么不让 LeadAgent 继承 SingleAgentOrchestrator？

它们不是 is-a 关系。Lead 是团队控制平面，SingleAgentOrchestrator 是单任务执行/编排能力。使用组合和依赖注入更容易复用、替换和测试。

#### Q6：为什么今天不直接实现 DAG？

Day1 先稳定节点所需的 identity、role 和 assignment 契约。若领域模型和 DAG 同时开发，失败难以归因，也容易把依赖字段耦合进不合适的旧 PlanStep。

### 13.3 Trade-off 问题

#### Q7：Lead-Worker 的主要代价是什么？

额外 Token、规划延迟、协调复杂度和 Lead 瓶颈。错误分解还可能系统性影响多个 Worker。因此必须保留 Single-Agent baseline 并通过实验判断何时值得启用团队。

#### Q8：什么时候 Peer Agents 更合适？

多个独立假设的研究、对等 review 或辩论场景，可能从去中心化交流中获益。CodeTeam 选择 Lead-Worker 是默认 Coding Task 控制结构，不是否定所有 Peer 模式。

#### Q9：共享上下文和独立上下文如何选？

高度耦合、短任务共享上下文更简单；可分解、输出噪声大的工作适合独立上下文。独立上下文需要高质量 Assignment 和后续 Mailbox 补充信息。

### 13.4 测试与评测问题

#### Q10：如何证明 Lead 没有越过执行边界？

给执行后端注入带计数器的 Fake，调用 Lead.create_plan 后断言 invocation count 为0，同时检查 workspace diff 为空。

#### Q11：如何评估角色分配？

建立带人工 gold role 的任务集，计算 assignment-level accuracy 和 confusion matrix，同时记录 GENERAL fallback、空 Plan 和 invalid Plan rate。

#### Q12：为什么单元测试不能证明 Multi-Agent 更有效？

单元测试证明契约正确；收益需要在相同任务、模型、预算和安全条件下比较 Single Agent 与 Agent Team 的成功率、成本、延迟和冲突率。

### 13.5 Failure / Debug 问题

#### Q13：最危险的 Day1 失败是什么？

不是普通分类错，而是控制平面在 Plan 校验前执行副作用，或重复 Worker ID 静默覆盖，导致结果无法归因。这两类必须 fail fast。

#### Q14：空 Plan 为什么不能视为完成？

“没有步骤”只说明 Planner 没提供可执行方案，不证明用户目标已满足。Runtime 必须把模型输出和系统完成事实分开。

### 13.6 30 秒项目表达

> Week1～4 我先实现了一个可验证的 Single-Agent Runtime，包括 Context、Patch、Sandbox、Recovery、Session 和 Evaluation。Week5 我没有简单启动多个模型，而是在现有执行内核之上增加 Lead-Worker 控制平面。Day1 先定义稳定 Agent identity、role、status 和结构化 assignment，并让 Lead 只做规划分配、Worker 复用已有安全执行链。这样后续 DAG、Scheduler、Mailbox 和恢复都有清晰契约。目前完成度只到领域模型设计与确定性规划阶段，不宣称已经并行执行。

### 13.7 2 分钟项目表达

> CodeTeam 当前的 SingleAgentOrchestrator 已能把 TaskSpec、RepositoryInspector、Planner、Plan、Verification 和 Repair 串起来，但复杂任务会让一个 Agent 同时承担全局规划和局部执行。我的 Week5 设计是把它保留为 Worker 可复用的执行内核，在上面建立 Lead-Worker 控制平面。Lead 接收已有 TaskSpec 和 RepositoryContext，复用 Planner 产生现有 Plan，再输出带 AgentRole 的 WorkerAssignment；Worker 有稳定 AgentIdentity 和独立 AgentStatus，通过 Registry 被发现，但 Day1 不直接执行工具。这样 Task、Plan、Context、Worktree、Sandbox、Session 和 Evaluation 都可以复用，而不会出现第二套 source of truth。
>
> 我选择 Lead-Worker 而不是默认 Peer Agents，是因为 Coding Task 需要统一目标、ownership 和完成判定。但我没有把这写成已被性能数据证明的结论：Day1 只完成结构和测试，周末会用 deterministic baseline、角色标注任务集和 ablation 比较 structured/free-text、role-aware/unaware、Lead/Peer routing。DAG、Scheduler、Mailbox、heartbeat 和 team resume 分别留给 Day2～Day6，Day7 才进行完整 Single-Agent vs Agent Team 评测。

### 13.8 可继续深挖的问题

- Lead 崩溃后如何选举或恢复？
- 一个 Assignment 能否由多个 Worker 协作？
- 如何避免 Worker 获得超出 Assignment 的上下文？
- role assignment 和 capability matching 有什么区别？
- Scheduler 如何原子 claim？
- Worker 修改重叠文件时如何处理 merge conflict？
- 团队事件如何与现有 Session event sequence 对齐？
- 如何把每个 Worker 的 Token/cost 归因到 task 和 assignment？

## 14. 今日完成标准

### 14.1 理论理解完成

- [ ] 能解释 Single-Agent 到 Multi-Agent 的边界不是“模型数量”。
- [ ] 能解释 Lead、Worker、Planner、Scheduler 四者职责。
- [ ] 能解释 Control Plane 与 Execution Plane。
- [ ] 能解释 Role、Identity、Status、Permission 的区别。
- [ ] 能说明为什么 Day1 不实现 DAG、Scheduler、Mailbox。

### 14.2 教程学习完成

- [ ] 已读完本实操教程。
- [ ] 能画出 Lead -> Assignment -> Worker -> Existing Runtime 数据流。
- [ ] 能指出当前没有 `codeteam/runtime/`、`codeteam/events/` 和 `codeteam/agent_team/`。
- [ ] 能说出当前真实 `Planner.create_plan()` 和 `SingleAgentOrchestrator.run()` 契约。

### 14.3 生产代码待逐步实现

- [ ] Step1 复用边界已确认。
- [ ] Step2 AgentRole/Status/Identity/Info 待实现。
- [ ] Step3 WorkerAssignment/LeadPlanningResult 待实现。
- [ ] Step4 WorkerAgent/Registry 待实现。
- [ ] Step5 LeadAgent 契约待实现。
- [ ] Step6 deterministic RoleAssigner 待实现。

### 14.4 测试与工程证据

- [ ] `tests/agent_team/` 待创建并补齐 Day1 测试地图。
- [ ] 现有 Single-Agent 回归待运行。
- [ ] `DD-W5-01` 待形成，Evidence 初始为 `PROPOSED`。
- [ ] F-W5-D1-01/02/03 待按项目最终目录约定落盘。
- [ ] Benchmark 方案已设计，状态为 `PLANNED / NOT_RUN`。
- [ ] Ablation 方案已设计，状态为 `PLANNED / NOT_RUN`。

### 14.5 Day1 最终功能验收边界

只有当后续代码和测试真正完成时，Day1 才可宣称：

```text
Lead 可以生成非空结构化 Plan + Assignment
Worker 可以被唯一注册和按角色发现
角色和状态模型可以校验、序列化
相同输入的 deterministic baseline 可复现
Lead 不进入 Worker 的工具执行路径
现有 Single-Agent 测试零回归
```

即使全部满足，仍只能表述为：

```text
Lead-Worker domain foundation completed
```

不能表述为：

```text
parallel Multi-Agent Runtime completed
```

后者必须等到 Day2 DAG、Day3 Scheduler、Day4 Mailbox、Day5 Lifecycle、Day6 Persistence 和 Day7 端到端 Evaluation 提供共同证据。
