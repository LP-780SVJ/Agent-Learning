# Week5 Day 7：Agent Team MVP + Evaluation

今天不是继续新增一个孤立模块，而是第一次把 Week5 的控制面真正闭合：

```text
User Task
    ↓
LeadAgent
    ↓
Task DAG
    ↓
Scheduler
    ↓
Worker Pool
    ↓
Mailbox
    ↓
Lifecycle / Registry
    ↓
Durable Store
    ↓
Team Result
```

然后回答一个比“跑起来了吗”更重要的问题：

> **Multi-Agent 到底给 CodeTeam 带来了什么？它在哪些任务上比 Single Agent 更好，代价又是什么？**

我先说明当前代码基线。现在 `week5` 已经能确认存在 Lead、DAG、Scheduler、Mailbox、AgentRegistry、Lifecycle、TeamStateCoordinator 以及 worker generation / lease / stale execution 相关契约；`agent_team/__init__.py` 已将这些作为统一公共能力导出。 同时，你现有 Evaluation 也已经非常成熟：`AgentEvalRunner` 接受一个统一 `CodingRuntime` 协议，在独立 Worktree 中运行任务，再交给外部 `AgentGrader`；Grader 的成功不是“Agent 自称完成”，而是同时要求 acceptance、regression、task verification、budget、security 等条件通过。

有一点需要透明说明：你刚 push 后 GitHub 当前公开文件索引仍存在缓存不一致——部分 Day5 新文件已经是今天版本，但目录视图和 Day6 store 文件还没有稳定暴露。因此下面不会编造你 Day6 Store 的具体类名/API，而是把你已经完成的 Durable Store 当作 `TeamStateStore/TaskStore` 能力来使用。

---

# 一、Day7 真正要完成什么？

前六天分别解决的是：

| 模块 | 回答的问题 |
|---|---|
| Lead | 大任务怎么拆？ |
| DAG | 子任务依赖是什么？ |
| Scheduler | 谁什么时候做？ |
| Mailbox | Agent 怎么交流？ |
| Lifecycle | Worker 挂了怎么办？ |
| Durable Store | 整个 Runtime 挂了怎么办？ |
| **Day7** | **这些东西能不能组成一个真正的 Team Runtime？值不值得？** |

所以 Day7 有两个目标：

```text
目标 A：Integration Correctness
证明整个 Agent Team Runtime 能闭环

目标 B：Evaluation
证明/否定 Multi-Agent 的实际收益
```

不要把今天理解成：

> “写一个 Demo 启动三个 Worker。”

---

# 二、工业界的 Multi-Agent 也不是“多开几个模型”

2026 年 OpenAI Codex 的公开产品设计已经非常明确：多个 coding agents 可以同时运行，每个 Agent 拥有自己的 thread 和隔离 Worktree，从而并行处理同一仓库的不同任务；用户最终检查 diff 和测试结果，而不是让多个 Agent 随意共享一个工作目录。

GitHub Copilot Agents 也采用类似产品形态：一个仓库中可以同时启动多个独立 agent session，分别跟踪各自任务和执行过程。

DeepSeek 现在公开的 DeepSeek Harness 更值得你关注，因为它和你的求职方向高度一致。它直接把自己定义成 open-source **agent harness**，核心采用 everything-is-a-plugin 架构；其 unattended JSON-RPC Agent 把 `subagent` 作为模型工具，同时加载 JSONL session persistence 和 context compaction。这种设计反映的不是“模型数量”，而是 Harness 如何提供 delegation、persistence、context、tool runtime 等基础设施。

这些系统共同体现一个思想：

```text
Multi-Agent Capability
≠
N × LLM

Multi-Agent Capability
=
Agent
+
Isolation
+
Scheduling
+
State
+
Communication
+
Observability
+
Evaluation
```

这正是 CodeTeam Week5 在做的事情。

---

# 三、你当前代码里 Day7 最大的一个关键点

你现在的 `WorkerAgent` 本身仍然很轻。

它主要表达：

```text
AgentInfo
Role
Capability
supports(role)
```

而不是一个真正的 Coding Agent execution loop。当前公开实现没有把 `WorkerAgent` 本身设计成“会搜索、修改、测试”的大对象。

我认为这其实是对的。

不要现在写成：

```python
class WorkerAgent:
    def run_llm(...)
    def search_repo(...)
    def apply_patch(...)
    def run_test(...)
    def recover(...)
    def compact(...)
    ...
```

否则你会重新复制 Week1～4 的 Single-Agent Runtime。

今天真正应该建立的是：

```text
WorkerAgent
=
Identity + Role + Runtime Handle

WorkerExecutor
=
把 Worker Task
转交给已有 Coding Runtime
```

---

# 四、最关键的架构原则：Team Worker 必须复用 Single-Agent Runtime

这是 Day7 我最希望你记住的东西。

错误架构：

```text
Single Agent
    ↓
SingleAgentRuntime A


Worker
    ↓
另外重新写一个 AgentLoop B
```

最终就会出现：

```text
两个 Context Engine
两个 Repair Loop
两个 SafeExecutor
两个 Verification 路径
```

然后 Single vs Team Benchmark 完全失去意义。

---

正确：

```text
                       Coding Runtime
                            ↑
                  ┌─────────┴─────────┐
                  │                   │
           SingleAgent           WorkerExecutor
                  │                   │
                  │              Worker A/B/C
                  │
                Eval
```

---

# 五、你仓库已经给这个设计留下了非常好的接口

现在 `AgentEvalRunner` 已经定义：

```python
class CodingRuntime(Protocol):
    def run(
        self,
        request: CodingAgentRunRequest
    ) -> CodingAgentRunResult:
        ...
``` 


这其实是 Week5 一个非常重要的现成 abstraction。

你完全可以让：

```text
SingleCodingRuntime
```

和：

```text
TeamCodingRuntime
```

都满足：

```text
CodingRuntime
```

于是 Evaluation 完全不用重写：

```text
                    AgentEvalRunner
                          │
               ┌──────────┴──────────┐
               │                     │
        SingleCodingRuntime    TeamCodingRuntime
               │                     │
               └──────────┬──────────┘
                          ↓
                    Same Grader
```

这就是工业上非常重要的：

# Controlled Experiment

---

# 六、为什么“同一个 Eval Harness”这么重要？

假设你这样比较：

```text
Single Agent

评测：
pytest


Agent Team

评测：
LLM 说完成了
```

然后说：

```text
Team Success Rate 更高
```

没有任何意义。

必须：

```text
同一任务
同一 repo base
同一 hidden oracle
同一 model
同一 budget
同一 timeout
同一 success definition
```

只有：

```text
orchestration architecture
```

不同。

---

# 七、你当前 Grader 的 Success 定义应该直接继承

现在 CodeTeam 已经定义：

```text
Success
=
Actor Completed

AND Acceptance Passed

AND Regression Passed

AND Task Verification Passed

AND Within Budget

AND Security Passed

AND Pristine Oracle 不是天然通过
``` 


这已经比很多学生项目的：

```text
pytest passed = success
```

严格得多。

所以 Day7：

> **绝对不要再创建一套 TeamSuccess 判定。**

---

# 八、Team Success 和 Scheduler Completed 不是一回事

这是今天非常容易犯的错误。

Scheduler：

```text
Task A COMPLETED
Task B COMPLETED
Task C COMPLETED
```

只能说明：

> Agent Team 的 Runtime workflow 跑完了。

它不能说明：

> 用户的问题真的被修好了。

所以应该区分：

```text
Orchestration Completion
            │
            ▼
所有 DAG nodes terminal


Coding Success
            │
            ▼
External Grader PASS
```

也就是说：

```text
Scheduler COMPLETED
≠
Eval Success
```

---

# 九、工业界为什么强调 external verification？

Codex 的公开设计明确强调 coding agent 最终应通过测试、终端日志、修改记录进行人工/系统验证，而不是信任模型自己的声明；其产品也围绕“issue → code → tests → review-ready change”设计。

最近 OpenAI 对 coding benchmark 的审计甚至指出，评测任务本身如果存在问题，会产生错误能力结论；他们在对 SWE-Bench Pro 的审计中估计约 30% 的任务存在问题。

这也是为什么你已有的：

```text
pristine acceptance check
hidden oracle
regression
security
```

非常重要。

你不是只在评 Agent。

你还需要验证：

> **Eval Task 本身是不是有效。**

---

# 十、Day7 Runtime 应该是什么？

我建议今天增加一个很薄的：

```text
TeamRunner
```

或者：

```text
TeamRuntime
```

不要叫：

```text
MultiAgentMegaOrchestrator
```

它只是 glue。

---

结构：

```text
TeamRuntime
    │
    ├── LeadAgent
    ├── TaskDAG
    ├── TaskScheduler
    ├── AgentRegistry
    ├── AgentMailbox
    ├── AgentLifecycleManager
    ├── TeamStateStore
    └── WorkerExecutor
```

它不：

- 搜代码
- 写 Patch
- 执行 pytest
- 操作 Git
- 调 Provider

这些都应该由现有 Runtime 做。

---

# 十一、完整执行流程

今天最终要把这一条跑通：

```text
User Task

   ↓

TeamRuntime.run()

   ↓

LeadAgent.create_plan()

   ↓

LeadPlanningResult

   ↓

TaskDAG

   ↓

Scheduler.schedule()

   ↓

3 Worker ready

   ↓

claim()

   ↓

WorkerExecutor

   ↓

existing Coding Runtime

   ↓

Worker Result

   ↓

Mailbox

   ↓

Scheduler.complete/fail

   ↓

Durable Store Commit

   ↓

dependent task released

   ↓

all terminal

   ↓

Team Result
```

---

# 十二、Step 1：User Task → Lead

比如：

> 修复 OAuth 登录后 refresh token 失效，并补充测试。

Lead 输出概念上：

```text
T1
分析认证流程

T2
修改 refresh-token logic

T3
补 regression test
```

DAG：

```text
T1
 ↓
T2
 ↓
T3
```

另一个 Feature 可能：

```text
       T1 Contract
       /        \
      ↓          ↓
T2 Backend    T3 Frontend
      \          /
       ↓        ↓
         T4 Test
```

---

# 十三、Lead 的职责到哪里停止？

Lead 负责：

```text
Goal
Decomposition
Role
Dependency
```

不负责：

```text
执行 git
运行 pytest
直接写文件
```

这是 Day1 Supervisor 边界的延续。

---

# 十四、Step 2：Task DAG → Scheduler

你的 Scheduler 已经具备：

```text
PENDING
 ↓
READY
 ↓
CLAIMED
 ↓
RUNNING
 ↓
COMPLETED / FAILED
```

并考虑 retry、worker role、waiting-for-worker 等问题。

所以 Day7 不重新写：

```text
while task...
```

你只需要循环驱动已有 Scheduler。

概念：

```python
scheduler.schedule()

while not all_terminal():

    dispatch_ready_tasks()

    collect_worker_results()

    process_mailbox()

    lifecycle.sweep()

    persist()
```

---

# 十五、这里不要写 Busy Polling 死循环

错误：

```python
while True:
    scheduler.schedule()
```

会：

```text
CPU 100%
```

工业设计一般是：

```text
Event

↓

Wake Scheduler

↓

Process State

↓

Wait
```

Day7 MVP 可以：

```text
asyncio Event / Queue
```

或者合理短 sleep。

但长期应：

```text
Task completed
Heartbeat timeout
Message arrived
Worker available

        ↓

Scheduler wake-up
```

也就是 Event-driven Control Loop。

---

# 十六、Step 3：三 Worker 并发

需要明确：

```text
3 Worker
≠
必须有三个不同模型
```

Worker 可以全部用：

```text
同一个 model
```

差异是：

```text
identity
role
task context
workspace
```

例如：

```text
worker-backend-1
worker-test-1
worker-general-1
```

---

# 十七、工业界为什么隔离 Worker Context？

OpenAI Codex 多 Agent 公开设计中，各 Agent 使用独立 thread，并利用 Worktree 让任务不会污染本地 Git 状态。

CodeTeam 也应该遵循：

```text
Worker A Context
只包含：
T1
相关文件
repo instructions


Worker B Context
只包含：
T2
相关文件
repo instructions
```

而不是：

```text
Lead + A + B + C
所有 Conversation 全部共享
```

否则：

```text
Multi-Agent
```

反而造成：

```text
Context × N
```

爆炸。

---

# 十八、但这里出现 Week5 和 Week6 的一个重要边界

你原计划今天要求：

```text
3 Worker 并发
```

同时又要评：

```text
Bug / Feature / Refactor
```

但真正的 **多 Worker 并发写代码** 还需要：

```text
独立 Worktree
Worker Commit
Integration Branch
Merge
Conflict Handling
Reviewer
Quality Gate
```

这些其实是 Week6。

因此：

> **Week5 Day7 不应该为了“完成 Team Coding Demo”偷偷把 Week6 的 Integration Runtime 全塞进来。**

---

# 十九、所以 Day7 应该分两个层级验证

这是我根据你真实项目给原计划做的最重要修正。

## Level A：Orchestration MVP

必须完成。

使用：

```text
Fake / Deterministic WorkerExecutor
```

完整跑：

```text
Lead
DAG
3 workers
claim
parallel
mailbox
failure recovery
store
resume
result
```

这验证的是：

# Harness Correctness

---

## Level B：Real Coding Runtime Smoke

至少完成：

```text
一个 Worker
↓
真实 Coding Runtime
↓
搜索
修改
测试
结果
```

然后：

```text
两个互不写同一 Workspace 的 Worker
```

验证 WorkerExecutor 确实复用了 Single-Agent Runtime。

---

## Level C：Full Multi-Writer Coding

```text
3 Worker
+
3 Worktree
+
Commit
+
Merge
+
Review
+
Integration test
```

放到：

# Week6

更合理。

---

# 二十、为什么不能现在三个 Worker 共享一个 Worktree？

例如：

```text
Worker A:
auth.py


Worker B:
auth.py
```

同时：

```text
apply_patch
```

你会遇到：

```text
Race
Patch conflict
Git index conflict
test observation mismatch
checkpoint mismatch
```

这是典型的不安全并行。

---

# 二十一、所以 Week5 的 Agent Team MVP 到底证明什么？

证明：

```text
Lead 能拆

DAG 合法

Scheduler 能发现并行任务

3 Worker 能被正确调度

没有 duplicate claim

Mailbox 正确路由

Worker crash 可恢复

old attempt 被 fencing

Process restart 可恢复

最终 Team Runtime 达到 terminal state
```

这已经非常有价值。

不要低估：

> 一个可靠的 orchestration control plane 本身就是 Agent Harness 的核心工作。

---

# 二十二、工业界也把“控制面”和“执行面”拆开

OpenAI Agents SDK 的设计也非常能说明这一点。

它把：

```text
Agent
Handoff
Tool
Guardrail
```

作为基础 primitive，同时内建 tracing；trace 中还会分别记录：

```text
agent span
generation span
function span
handoff span
guardrail span
``` 


这意味着成熟 Agent 平台不会把：

```text
LLM output
```

当作唯一观测对象。

它会观察：

> Runtime trajectory。

CodeTeam 的 Event Log 正应该往这个方向发展。

---

# 二十三、Team Result 应该长什么样？

不要只返回：

```python
True
```

建议有类似概念：

```text
TeamRunResult

task_id
status

plan

task_records

worker_results

events

messages

duration_ms

input_tokens
output_tokens
cost_usd
tool_calls

failure_reason
```

---

# 二十四、Team Runtime Status 建议简单一点

不要再搞十几个状态。

例如：

```text
CREATED
RUNNING
COMPLETED
FAILED
RECOVERY_REQUIRED
```

足够。

最终：

```text
COMPLETED
```

表示：

> orchestration completed。

仍然不是：

```text
coding benchmark success
```

---

# 二十五、Result Aggregator

你需要一个非常轻的：

```text
ResultAggregator
```

或者直接在 `TeamRuntime` 中做。

负责：

```text
Σ worker input_tokens
Σ worker output_tokens
Σ cost
Σ tool calls
max / wall duration
task status counts
```

不要让：

```text
Lead Agent
```

自己总结 Runtime metrics。

Metrics 必须由系统采集。

---

# 二十六、Token Cost 怎么统计才正确？

Single：

```text
Total Token
=
Single Runtime tokens
```

Team：

```text
Team Tokens
=
Lead planning tokens
+
Worker 1 tokens
+
Worker 2 tokens
+
Worker 3 tokens
```

后面 Week6 有 Reviewer：

再加：

```text
Reviewer tokens
```

---

# 二十七、不要只统计 Worker Token

否则你会虚假得到：

```text
Team 比 Single 省 Token
```

因为把 Lead / Communication 成本漏掉了。

工业上这叫：

# Coordination Overhead

---

# 二十八、Tool Calls 同理

Team：

```text
ToolCalls_team
=
Σ all worker tool calls
+
Lead tool calls（如果 Lead 使用工具）
```

Mailbox：

不应该算：

```text
LLM tool call
```

它应该单独作为：

```text
coordination_messages
```

否则概念混乱。

---

# 二十九、Latency 到底测什么？

今天一定不要只记录：

```text
Worker execution time
```

真正用户感知的是：

```text
User Task submitted
        ↓
Lead plan
        ↓
Scheduler
        ↓
Workers
        ↓
Recovery
        ↓
Final Result

= Wall-clock Latency
```

因此：

\[
T_{team}
=
T_{end}-T_{start}
\]

---

# 三十、但还应该拆解

至少：

```text
planning_ms

scheduler_wait_ms

worker_execution_ms

recovery_ms

total_ms
```

以后你才能回答：

> Team 为什么慢？

可能不是模型慢。

而是：

```text
Worker 等待 dependency
```

---

# 三十一、Success Rate

公式很简单：

\[
SuccessRate =
\frac{SuccessfulTasks}
{TotalTasks}
\]

但关键是：

> 什么叫 Successful？

直接复用当前 Grader。

你已经有非常强的判定。

---

# 三十二、Latency 比较

对于每个 Task：

```text
Single:
T_single

Team:
T_team
```

定义：

\[
Speedup =
\frac{T_{single}}
{T_{team}}
\]

如果：

```text
Speedup > 1
```

Team 更快。

如果：

```text
Speedup < 1
```

Team 更慢。

---

# 三十三、Parallel Efficiency：原计划需要稍微修正

很多人直接写：

\[
E =
\frac{T_{single}}
{N T_{team}}
\]

它可以作为粗略量，但不够科学。

因为：

```text
Single Agent
```

和：

```text
Agent Team
```

做的工作本身可能不同。

---

# 三十四、更合理的实验

做两个 Team 配置：

## Team Sequential

```text
same Lead
same DAG
same Worker logic

max_workers = 1
```

记：

\[
T_{team,serial}
\]

---

## Team Parallel

```text
max_workers = 3
```

记：

\[
T_{team,parallel}
\]

然后：

\[
ParallelSpeedup =
\frac{T_{team,serial}}
{T_{team,parallel}}
\]

\[
ParallelEfficiency =
\frac{T_{team,serial}}
{3T_{team,parallel}}
\]

这才真正测试：

> **Parallel Scheduler 是否有效。**

---

# 三十五、这是一个非常重要的实验设计原则

所以：

```text
Single vs Team
```

回答：

> Multi-Agent 架构整体是否有价值？

而：

```text
Team Sequential vs Team Parallel
```

回答：

> 并行调度是否有价值？

两个问题不能混。

---

# 三十六、再加一个非常实用的 Worker Utilization

公式：

\[
Utilization=
\frac{\sum WorkerBusyTime}
{N\times TeamWallTime}
\]

例如：

```text
3 workers
运行 100s

Worker A busy 80
Worker B busy 60
Worker C busy 40
```

则：

```text
180 / 300 = 60%
```

说明：

> Worker Pool 只有 60% 时间真正有工作。

---

# 三十七、为什么这个指标有用？

如果：

```text
Parallel Efficiency 很差
```

但：

```text
Worker Utilization 也很低
```

可能说明：

```text
DAG 太串行
```

而不是 Scheduler 性能差。

例如：

```text
A → B → C → D
```

你开：

```text
100 Worker
```

也没用。

---

# 三十八、Team 的核心成本模型

你最终可以理解成：

\[
Benefit_{team}
=
ParallelismGain
+
SpecializationGain
-
CoordinationOverhead
-
DuplicationCost
\]

其中：

### ParallelismGain

独立任务同时做。

### SpecializationGain

Tester / Backend 各自 context 更聚焦。

### CoordinationOverhead

Lead + Message + Scheduler。

### DuplicationCost

多个 Worker 都可能：

```text
搜索同一仓库
读取同一个 README
重新理解同一架构
```

---

# 三十九、Multi-Agent 不一定更好

Microsoft AutoGen 官方的 Team 文档也长期强调一个原则：如果一个 Agent 就可以完成任务，没有必要强行使用 Team；Multi-Agent 会增加 orchestration complexity。OpenAI Codex 的实践同样更推荐将**明确、可分解、边界清晰的任务**并行委托给多个 Agent。

所以你希望最终得到的不是：

```text
Team > Single
```

而是：

```text
Bug-small
Single better

Feature-cross-module
Team better

Highly sequential refactor
maybe Single better
```

这种结论。

这才像真正 Benchmark。

---

# 四十、10 个 Task 怎么设计？

原计划：

```text
Bug
Feature
Refactor
```

我建议：

```text
Bug       4
Feature   3
Refactor  3
```

但不能随机选。

要覆盖不同：

# Parallelizability

---

## B01：Single-file Bug

例如：

```text
修正 parse_timeout() 边界
```

特点：

```text
single file
one concern
```

预期：

> Single 可能更好。

---

## B02：Cross-module Bug

例如：

```text
API request field
→ service
→ validator
```

预期：

Team 可能有优势。

---

## B03：Bug + Regression Test

存在：

```text
implementation
和
test
```

一定程度可以分工。

---

## B04：Config + Code Bug

需要：

```text
config
runtime
test
```

---

# 四十一、Feature Task

## F01

新增一个小 API：

```text
contract
service
test
```

---

## F02

新增 CLI 功能：

```text
command
service
test
```

---

## F03

跨模块 Feature：

```text
backend
config
test
docs
```

这是 Team 更可能体现优势的。

---

# 四十二、Refactor Task

## R01

单模块重构。

可能：

Single 更合适。

---

## R02

公共接口迁移。

例如：

```text
interface
↓
3 consumers
↓
tests
```

有明显并行性。

---

## R03

Large Rename / API migration

适合观察：

```text
coordination cost
```

---

# 四十三、建议给 Task 增加一个“实验标签”

不是给 Agent 看。

Eval metadata：

```text
parallelism_class:

low
medium
high
```

以及：

```text
scope:

single_file
cross_module
```

---

这样最终可以分析：

```text
low-parallelism
Single 胜率/成本

high-parallelism
Team 胜率/成本
```

这比单纯：

```text
10 task average
```

有价值很多。

---

# 四十四、不要把这个标签放进 Agent Prompt

否则泄漏：

```text
parallelism_class=high
```

Lead 会被暗示：

> “你应该多拆任务。”

它应该只属于：

```text
Eval metadata
```

---

# 四十五、实验必须 Pairwise

正确：

```text
Task B01

Single run
Team run
```

使用：

```text
same base commit
same model
same prompt
same test oracle
same context limit
same step budget
```

而不是：

```text
Single 跑 B01-B05
Team 跑 F01-F05
```

---

# 四十六、模型要固定

例如：

```text
provider = OpenAI-compatible
model = same model
```

否则：

```text
Single 使用 Model A

Team 使用 Model B
```

你测的是：

```text
Model difference
```

不是：

```text
Architecture difference
```

---

# 四十七、Budget 怎么公平？

这里很有意思。

Single：

```text
max_steps = 20
```

Team 如果：

```text
3 workers × 20
```

理论上给了：

```text
60 worker steps
```

不公平。

---

# 四十八、因此应该报告两个预算维度

## Wall-clock Budget

例如：

```text
900s
```

Single / Team 一样。

---

## Aggregate Compute Budget

例如：

```text
Total model tokens
Total tool calls
Total cost
```

不要强行要求完全一样。

但必须：

> 如实统计。

最终才能回答：

> Team 是否用 3 倍成本换 1.2 倍速度？

---

# 四十九、这比“Team 更快”重要得多

例如：

Single：

```text
Success 70%
Time 300s
Cost $0.10
```

Team：

```text
Success 80%
Time 180s
Cost $0.40
```

应该怎么判断？

不是简单说：

> Team 胜。

而是：

```text
+10pp success
40% latency reduction
4× cost
```

是否值得：

取决于业务。

---

# 五十、你已有 Evaluation 不需要重写

当前 `AgentEvalRunner` 已经：

- 创建 pristine workspace；
- 检查 oracle 是否在 pristine 上错误通过；
- 为每个任务建立独立 Worktree；
- 调用统一 Runtime；
- 运行 Grader；
- 保存 `results.jsonl`、`summary.json`、`manifest.json`；
- 记录 provider/model/budget/environment。

所以今天不要：

```text
evals/team_runner.py
然后复制 1000 行 AgentEvalRunner
```

---

# 五十一、正确改法：Runtime Adapter

当前：

```text
AgentEvalRunner
    ↓
CodingRuntime
```

新增：

```text
SingleCodingRuntime

TeamCodingRuntime
```

TeamRuntime 也实现：

```python
run(
    CodingAgentRunRequest
) -> CodingAgentRunResult
```

或者：

如果 Team 的内部 result 更丰富：

```text
TeamRunResult
      ↓ adapter
CodingAgentRunResult
```

同时额外保存：

```text
team_metrics.json
```

---

# 五十二、这样你的实验才漂亮

```text
                   Same Task Dataset
                         │
                   AgentEvalRunner
                         │
        ┌────────────────┴────────────────┐
        │                                 │
   Single Runtime                    Team Runtime
        │                                 │
        └────────────────┬────────────────┘
                         │
                     Same Grader
                         │
                Acceptance / Regression
                     / Security
```

这在面试里非常有说服力。

---

# 五十三、Team-specific Metrics 不要硬塞进旧模型几十个字段

你当前 `AgentEvalTaskResult` 已经很大，包含：

- duration
- steps
- model/tool/repair duration
- tool calls
- tokens/cost
- failure origin
- completion behavior
- progress metrics 等。

继续往里面加：

```text
50 个 Team 字段
```

会越来越难维护。

---

# 五十四、建议增加结构化子模型

例如：

```text
TeamMetrics

team_size
task_nodes
completed_nodes
failed_nodes
retried_nodes

coordination_messages

max_parallel_workers
worker_busy_ms

scheduler_wait_ms
lead_planning_ms

parallel_efficiency
```

然后：

```text
AgentEvalTaskResult
    team_metrics: TeamMetrics | None
```

Single：

```text
None
```

Team：

有值。

---

# 五十五、今天最重要的 Event Correlation

你现在已经有：

```text
runtime_id
transaction_id
transaction_event_index
```

以及 Mailbox：

```text
task_id
node_id
correlation_id
``` 


这已经非常接近 Trace。

Day7 建议再确保每条核心事件至少能关联：

```text
parent_task_id
node_id
agent_id
attempt
runtime_id
correlation_id
```

---

# 五十六、为什么？

否则你的 Event Log：

```text
Worker completed
Worker completed
Worker failed
```

你不知道：

> 哪个任务？

---

最终应该可以还原：

```text
User Task U1
│
├── T1
│   └── Worker A attempt1
│
├── T2
│   ├── Worker B attempt1 FAIL
│   └── Worker C attempt2 SUCCESS
│
└── T3
    └── Worker A attempt1
```

这就是：

# Execution Trajectory

---

# 五十七、OpenAI Agents SDK 的工业实现正是这样

其 tracing 明确把一次完整 workflow 建模为 Trace，再把 Agent、LLM generation、tool invocation、handoff 等建成不同 Span，并通过 trace ID / parent span 还原因果关系。

你 Week7 才会正式做 OpenTelemetry / tracing。

所以今天：

> 不必实现完整 tracing。

但是必须保证：

```text
Event Metadata 足够
```

未来才能升级。

---

# 五十八、Day7 测试应该分四类

## A. Happy Path Integration

DAG：

```text
    A
   / \
  B   C
   \ /
    D
```

3 Workers。

验证：

```text
A 完成

B/C 同时 RUNNING

D 只能等 B/C

最终全部 COMPLETED
```

---

# 五十九、B. Failure Integration

例如：

```text
Worker B crash
```

验证：

```text
Heartbeat timeout
 ↓
attempt 1 invalidated
 ↓
task READY
 ↓
Worker C claim
 ↓
attempt 2
```

最终：

```text
Team completes
```

---

# 六十、C. Process Restart Integration

执行：

```text
A COMPLETED

B RUNNING

C READY
```

kill。

restart。

验证：

```text
A 不重复运行

B 进入 recovery

C 仍可调度

old lease invalid

runtime epoch changed
```

这复用了 Day6。

---

# 六十一、D. Three-worker concurrency

设计三个完全独立的 Fake Task：

```text
A 200ms
B 200ms
C 200ms
```

Serial 理论：

```text
~600ms
```

Parallel：

```text
~200ms + overhead
```

不要断言精确 200ms。

测试只验证：

```text
max_running_workers >= 2 / 3
```

以及：

```text
没有 duplicate claim
```

比 wall-clock 脆弱断言更稳定。

---

# 六十二、不要用真正 LLM 测 Scheduler 单元正确性

为什么？

LLM：

- 慢
- 随机
- API 抖动
- 成本
- 可能 provider timeout

所以：

```text
Scheduler / DAG / Lifecycle
```

测试：

```text
Fake Worker
```

---

真实模型只用于：

```text
Integration Smoke
Benchmark
```

这是工业测试分层。

---

# 六十三、建议今天的 Test Pyramid

```text
              Real LLM Team Smoke
                    少量

              Process Restart
                  少量

            Team Integration
                 中等

          Unit / Deterministic
                  大量
```

不要反过来。

---

# 六十四、真实 LLM MVP 推荐分三步

## Smoke 1

```text
1 Worker
1 Task
```

目的：

> WorkerExecutor → CodingRuntime 接线正确。

---

## Smoke 2

```text
2 independent Workers
```

只做不会相互写同一 Workspace 的任务。

---

## Smoke 3

```text
dependent DAG
A → B
```

目的：

> Worker output 能进入下一阶段。

---

完整：

```text
multi-writer DAG
```

等 Week6。

---

# 六十五、今天的 10-task Benchmark 我建议如何执行？

建议拆成：

## Phase 1：Single baseline

10 个全部跑。

得到：

```text
single_results.jsonl
```

---

## Phase 2：Team orchestration-safe configuration

同 10 个任务。

但是 Day7 没有 IntegrationManager 前：

> **不要允许三个 Worker 同时对同一最终 workspace 任意写。**

可以使用：

```text
single-writer + auxiliary workers
```

或者只把 Team coding comparison 标为：

```text
preliminary
```

---

# 六十六、我更推荐第二种

Day7 报告明确写：

> Week5 evaluation primarily validates orchestration correctness and preliminary cost/latency behavior. A fair multi-writer coding-quality comparison is deferred until Week6 provides isolated worker worktrees and deterministic integration.

这是一句非常专业的话。

---

# 六十七、不要为了“今天一定得到 Team 成功率”牺牲实验可信度

如果今天强行：

```text
3 Worker 共用 worktree
```

得到：

```text
Team Success 80%
```

这个数字没有作品价值。

反而面试官问：

> “你们的 workspace consistency 怎么保证？”

就会暴露问题。

---

# 六十八、Week5 应该输出两类结果

## 1. Harness Correctness Report

例如：

```text
DAG scheduling
PASS

3-worker concurrency
PASS

duplicate claim
PASS

worker crash recovery
PASS

stale attempt fencing
PASS

process restart
PASS

mailbox delivery
PASS
```

---

## 2. Preliminary Agent Evaluation

```text
Single
vs
Team

Success
Latency
Token
Cost
Tool Calls
```

并注明当前限制。

---

# 六十九、Parallel Efficiency 报告应该来自确定性 Benchmark

比如：

```text
100 DAGs
```

而不是只看：

```text
10 次真实 LLM
```

因为模型响应延迟噪声非常大。

所以：

```text
Scheduler Parallel Efficiency
→ Fake Worker benchmark

End-to-end Latency
→ Real agent benchmark
```

这两个分开。

---

# 七十、Benchmark 1：Scheduler 并行能力

准备：

```text
100 DAGs
```

不同结构：

```text
chain
fan-out
fan-in
layered
```

对比：

```text
workers=1

workers=3
```

指标：

```text
wall time
worker utilization
parallel efficiency
scheduler wait
```

---

# 七十一、Benchmark 2：Single vs Team Coding

10 Tasks。

指标：

```text
Success Rate

Latency

Input Tokens

Output Tokens

Cost

Tool Calls
```

你原计划只有 Token Cost。

你现有框架已经能够记录：

```text
input_tokens
output_tokens
cost_usd
tool_calls
```

所以全部保留。

---

# 七十二、推荐最终表

| Task | Type | Parallelism | Single Success | Team Success | Single Time | Team Time | Single Cost | Team Cost |
|---|---|---|---:|---:|---:|---:|---:|---:|
| B01 | Bug | Low | | | | | | |
| B02 | Bug | Medium | | | | | | |
| … | | | | | | | | |

不要预填。

---

# 七十三、第二张表：Team Runtime

| Metric | workers=1 | workers=3 |
|---|---:|---:|
| Wall time | pending | pending |
| Parallel speedup | — | pending |
| Parallel efficiency | — | pending |
| Worker utilization | pending | pending |
| Messages | pending | pending |
| Retries | pending | pending |

---

# 七十四、Failure Taxonomy

今天不仅记录：

```text
task failed
```

而要回答：

> 为什么 Team 失败？

建议 Week5 Failure categories：

```text
PLANNING

DAG

SCHEDULING

WORKER

COMMUNICATION

RECOVERY

PERSISTENCE

AGENT_EXECUTION

VERIFICATION
```

---

# 七十五、例如 Planning Failure

Lead：

```text
把必须串行的两个任务判断成并行
```

或者：

```text
漏掉测试任务
```

---

# 七十六、DAG Failure

例如：

```text
A → B
B → A
```

被 validation 拒绝。

这是：

```text
plan_invalid
```

不应该归：

```text
worker_failed
```

---

# 七十七、Scheduling Failure

例如：

```text
Backend Task
```

但没有 Backend Worker。

结果：

```text
waiting_for_worker
```

这不是 LLM failure。

---

# 七十八、Communication Failure

例如：

```text
TASK_COMPLETED
```

消息丢失。

Task 永远 RUNNING。

---

# 七十九、Recovery Failure

例如：

```text
stale Worker result
```

被错误接受。

这是非常严重的 correctness bug。

---

# 八十、Persistence Failure

例如：

```text
restart 后 COMPLETED Task 又执行
```

属于 Durable Runtime bug。

---

# 八十一、Agent Execution Failure

例如：

```text
LLM provider timeout

no patch

test failure

context exhaustion
```

这是 Single-Agent Runtime 自己的问题。

---

# 八十二、这就是为什么 Failure Origin 很重要

你的现有 EvalResult 已经有：

```text
failure_category
failure_origin
``` 


Week5 Team 继续扩大这个思想：

```text
Team failure
≠
Model failure
```

否则：

Scheduler bug

最后会被统计成：

```text
LLM failed
```

得不到有效结论。

---

# 八十三、DD-W5 应该不是 7 个小文档简单拼接

最终 `DD-W5.md` 应该给出一个整体架构判断：

# Why CodeTeam Uses a Durable Supervisor-Based Agent Team Runtime

核心：

```text
Lead
→ global planning

DAG
→ dependency contract

Scheduler
→ execution authority

Registry
→ worker authority

Mailbox
→ communication

Lifecycle
→ liveness/recovery

Store
→ cross-process durability
```

---

# 八十四、核心 Invariants 建议汇总

## I1

Lead 只能：

```text
propose work
```

不能直接改变 Task Runtime 状态。

---

## I2

TaskScheduler：

```text
Task state authority
```

---

## I3

AgentRegistry：

```text
Worker state authority
```

---

## I4

Mailbox：

```text
Message delivery authority
```

但消息不能直接偷偷改 Scheduler state。

---

## I5

旧：

```text
attempt / generation / runtime lease
```

永远不能 settle 新 execution。

---

## I6

Process restart：

必须：

```text
new runtime epoch
```

---

## I7

Orchestration Completed：

不等于：

```text
Coding Success
```

必须 External Grader。

---

# 八十五、Design Trade-off：为什么不是 AutoGen/LangGraph？

这是面试很可能问的。

你的回答不应该：

> 因为我想自己造轮子。

应该：

> 项目目标是学习 Agent Harness / Runtime，因此 DAG、Scheduler、Lifecycle、Durable State 和 Recovery 是我刻意实现的核心学习对象。如果直接使用 AutoGen/LangGraph，这些关键 runtime invariant 会被框架隐藏。但模型 Provider、Pydantic、SQLite 等非核心基础能力仍使用成熟组件，不重复实现。

这个回答会合理很多。

---

# 八十六、Design Trade-off：为什么 Lead + Worker？

不是：

```text
peer-to-peer agents
```

因为 Coding Task：

天然存在：

```text
global user objective
dependency
completion criteria
```

中央 Supervisor 更容易提供：

```text
determinism
audit
recovery
```

代价：

```text
Lead bottleneck
single coordination point
```

这也应该记录。

---

# 八十七、Ablation：Day7 至少做两个

## A1：Single vs Team

回答：

> Multi-Agent scaffolding 是否值得？

---

## A2：Team sequential vs Team parallel

回答：

> 并行 Scheduler 是否真的贡献 latency gain？

---

如果有时间：

## A3：No Mailbox

不是把 Mailbox 删除后系统直接不能跑。

定义一个合理替代：

```text
Workers 只能通过 TaskStore 结果轮询
```

比较：

```text
messages
latency
recovery behavior
```

不过正式做这个更适合 Week7。

---

# 八十八、今天不要做的几个 Ablation

暂时不要：

```text
No Reviewer
```

因为 Reviewer 是 Week6。

不要：

```text
No Merge
```

因为 Integration 也是 Week6。

实验必须基于已存在能力。

---

# 八十九、`W5_REPORT.md` 应该包含什么？

建议：

```text
1. Goal

2. Architecture

3. Runtime Invariants

4. Test Matrix

5. Orchestration Benchmark

6. Single vs Team Preliminary Evaluation

7. Cost / Latency Analysis

8. Failure Cases

9. Limitations

10. Week6 Handoff
```

---

# 九十、Limitations 一定要写

至少包括：

```text
10-task sample is small

full multi-writer integration not implemented

Reviewer/QualityGate not included

merge conflicts not covered

real provider variance

team role specialization still simple
```

这不是“项目不好”。

而是：

> 科学地定义结论边界。

---

# 九十一、`W5_FAILURES.md`

建议每个 failure：

```text
ID

Task

Layer

Observed Behavior

Expected Behavior

Root Cause

Mitigation

Regression Test

Status
```

例如：

```text
W5-F03

Layer:
Scheduler

Observed:
old attempt completed retry task

Root Cause:
attempt not fenced

Mitigation:
OwnedTaskToken

Regression:
test_stale_attempt_cannot_complete
```

---

# 九十二、Week5 Day7 最终代码产出

原计划：

```text
codeteam/agent_team/

lead.py
worker.py
dag.py
scheduler.py
mailbox.py
registry.py
store.py
```

基于你现在真实仓库，我建议最终逻辑上还需要一个薄的：

```text
team_runtime.py
```

或：

```text
runner.py
```

来整合这些模块。

否则你会被迫把 Team orchestration 塞进：

```text
lead.py
```

或：

```text
scheduler.py
```

这是错误边界。

---

# 九十三、以及一个 Worker execution adapter

可以是：

```text
worker_executor.py
```

但如果实现很薄，也可以放在：

```text
team_runtime.py
```

第一版。

它只负责：

```text
WorkerAssignment
       ↓
CodingAgentRunRequest
       ↓
existing CodingRuntime.run()
       ↓
WorkerTaskResult
```

---

# 九十四、为什么这个新 abstraction 合理？

你之前给项目定过规则：

> 新 abstraction 必须购买一种能力。

`WorkerExecutor` 购买的是：

```text
Agent Team task contract

        ↕

Single-Agent coding runtime contract
```

也就是：

# Adapter Boundary

所以值得存在。

---

# 九十五、今天不要写新的 Coding Agent

最关键验收：

```text
WorkerExecutor
必须复用 existing Coding Runtime
```

如果你的 Day7 PR 新增：

```text
worker_llm_loop.py
```

几百行，

大概率方向错了。

---

# 九十六、测试数量建议

今天至少：

```text
8~12 个 integration tests
```

重点不是增加大量 trivial tests。

覆盖：

1. linear DAG
2. parallel DAG
3. dependency release
4. 3-worker concurrency
5. role mismatch
6. worker crash
7. stale attempt
8. process resume
9. mailbox result
10. terminal failure
11. event correlation
12. single real worker smoke

---

# 九十七、最终 Week5 Mechanical Gate

完成 Day7 后至少跑：

```text
full pytest

Ruff touched files

tests/agent_team

week4 runtime regression

week4 safety regression

week4 sandbox regression

week4 evaluation regression
```

因为：

> Multi-Agent 不能把你刚合并进来的 Single-Agent Runtime 搞坏。

---

# 九十八、今天的最终验收标准

我建议把 Day7 原验收升级成：

```text
[ ] User Task 可以进入 TeamRuntime

[ ] Lead 生成合法任务计划

[ ] Task DAG validate

[ ] Scheduler 自动释放 dependency

[ ] 3 Worker 可以真实并发被调度

[ ] 没有 duplicate claim

[ ] WorkerExecutor 复用现有 Coding Runtime

[ ] Worker 结果可通过 Mailbox 回到 control plane

[ ] Runtime 状态会进入 Durable Store

[ ] Worker crash 可以恢复

[ ] stale attempt / generation 被拒绝

[ ] process restart 可以恢复 Team

[ ] 所有 Task 可以到 terminal state

[ ] 输出结构化 TeamRunResult

[ ] Team events 可按 parent task/node/worker/attempt 关联

[ ] 原有 Single-Agent EvalRunner 不重写

[ ] Single / Team 使用同一 Grader

[ ] 10 个 Bug/Feature/Refactor 任务跑 preliminary eval

[ ] 统计 Success Rate
[ ] 统计 Wall-clock Latency
[ ] 统计 Tokens
[ ] 统计 Cost
[ ] 统计 Tool Calls

[ ] Team sequential vs parallel
[ ] 统计 Parallel Efficiency
[ ] 统计 Worker Utilization

[ ] 不编造 Benchmark 数字

[ ] 明确 Week5 尚无 full multi-writer integration
```

---

# 九十九、Week5 完成后你真正拥有的是什么？

不是：

```text
三个 Agent
```

而是：

```text
                     CodeTeam

                 Agent Team Runtime

                        │
           ┌────────────┴────────────┐
           │                         │
      Control Plane            Coding Runtime
           │                         │
    Lead / DAG                       │
    Scheduler                  Context Engine
    Registry                   Agent Loop
    Lifecycle                  Tool Runtime
    Mailbox                    Safe Execution
    Durable State              Verification
           │                         │
           └────────────┬────────────┘
                        │
                   Evaluation
                        │
                External Grader
```

这个架构方向和当前头部 Coding Agent 产品逐渐形成的模式是一致的：Codex 把多个 agent、独立工作区、长任务和监督作为一等能力；OpenAI Agents SDK 把 handoff、trace 和 tool execution 做成 Runtime primitive；DeepSeek Harness 也把 subagent、session persistence 和 agent runtime 作为 Harness 能力，而不是单纯 Prompt 技巧。

---

# 一百、今天最重要的三条结论

如果 Day7 只记住三件事，我希望是：

### 1. Worker 不是第二套 Coding Agent

```text
Worker
↓
Adapter
↓
reuse Single-Agent Runtime
```

### 2. Team COMPLETED 不是 Coding SUCCESS

```text
Runtime completion
↓
External Grader
↓
Task success
```

### 3. Single vs Team 和 Parallelism Ablation 是两个不同实验

```text
Single vs Team
→ 架构价值

Team 1-worker vs 3-worker
→ 并行价值
```

做到这三点，你 Week5 最终得到的就不是一个“Multi-Agent Demo”，而是一套**可以被测试、恢复、比较和证伪的 Multi-Agent Coding Runtime 基座**。

而且这里有一个很重要的 Week6 交接点：

> **Week5 证明 Agent Team 控制面可靠；Week6 才允许多个真实 Coding Worker 在独立 Worktree 中并行地产生代码，并通过 Reviewer、Integration Branch 和 Quality Gate 形成一个真正可交付的统一 Patch。**

这会是后续 Week6 计划贴合你当前仓库的主线。
# 基于当前 week5 代码的 Day7 实施教程

> 本节是建立在当前 `week5` 分支真实代码之上的实施教程。前文保留为理论、工业调研与早期设计记录；如果前文描述与本节的“事实校正表”冲突，应以本节和当前代码为准。
>
> 本轮只编写教程。下面出现的文件名、类名和代码均是“待你逐步实现的参考设计”，不是已经存在的生产接口。

## 0. 当前事实校正与能力边界

### 0.1 先校正原稿中的过期假设

| 原稿或早期草案中的说法 | 当前仓库事实 | Day7 应采用的结论 |
|---|---|---|
| Day6 API 暂时不可见，因此只能写抽象接口 | Day6 代码已可在本地完整检查；`DurableTeamRuntime`、`SQLiteTeamStateStore`、`TeamSessionRuntimeBuilder` 均已存在并通过独立验收 | Day7 必须复用这些真实接口，不再猜测 Day6 API |
| Team Runtime 可以同时表示持久化控制面和 Coding 执行器 | `DurableTeamRuntime` 当前只负责 Registry、Scheduler、Mailbox、Lifecycle 的持久化状态变更 | 新增的执行编排层确定命名为 `TeamCodingRuntime`，避免与 `DurableTeamRuntime` 混淆 |
| DAG 全部终态就代表编码任务成功 | Scheduler 只知道节点状态，不知道最终补丁是否通过可见测试、回归、安全检查和隐藏验收 | DAG 终态只是控制面完成；最终成功必须由现有 `AgentGrader` 判定 |
| Day7 应立即让三个真实 Agent 并发修改同一个 Worktree | 当前没有 per-worker Worktree、补丁合并、冲突解决和 reviewer gate | Week5 只验证控制面并发；真实 LLM smoke 限制为一个 Worker、一个 Task，完整并行编码留到 Week6 |
| 可以为 Team 再写一套 Coding Loop | 当前已有 `CodingAgentRuntime.run(CodingAgentRunRequest)`，并通过 `CodingRuntime` Protocol 接入 `AgentEvalRunner` | `WorkerExecutor` 必须适配现有 Runtime，不得复制 Agent Loop |
| Week4 评测集是 held-out benchmark | 当前 `evals/week4/agent_task_suite_v1.jsonl` 有 11 个 `dev` task，不是 held-out 集 | 可将其用于初步架构对照，但不能把结果包装成正式泛化结论 |
| Mailbox 的 observer/event sink 可以替代持久化提交 | Day6 已明确 SQLite CAS commit 才是 durable truth，event sink 只是观察者 | Day7 的任务结果、claim/ack 与 Scheduler 迁移必须通过 `DurableTeamRuntime` 的持久化入口 |

### 0.2 两个 Runtime 的名字必须分清

#### 已存在：`DurableTeamRuntime`

位置：`codeteam/agent_team/runtime_factory.py`

它是 **durable control state gateway**，负责：

- 暴露 `registry`、`scheduler`、`mailbox`、`lifecycle` 的只读 facade；
- 用 `WorkerLease`、`TaskClaim`、`runtime_id`、`generation`、`attempt` 做 fencing；
- 把 `schedule()`、`claim()`、`start()`、`complete()`、`fail()` 等变更通过 SQLite CAS 持久化；
- 在 persistence failure 后 poison 当前 runtime，阻止继续产生不可信状态；
- 从 Day6 durable snapshot 中重建控制面。

它**不负责**：

- 调用 LLM；
- 执行 Coding Agent；
- 创建 `CodingAgentRunRequest`；
- 聚合 token/cost；
- 判定补丁是否通过最终验收。

#### Day7 拟新增：`TeamCodingRuntime`

建议位置：`codeteam/agent_team/team_runtime.py`

它是 **execution orchestrator**，负责：

- 接收一个顶层 `CodingAgentRunRequest`；
- 让 `LeadAgent` 生成 Plan、Assignments 和 DAG；
- 创建/恢复 Day6 的 `DurableTeamRuntime`；
- 让 Scheduler claim ready task；
- 将 claim 交给 `WorkerExecutor`；
- 有界并发等待 Worker 完成；
- 把结果通过 Mailbox 和 durable control state 提交；
- 聚合为独立 `TeamRunArtifact`，构造 `TeamCodingRunResult`，再向通用接口返回其中的 `CodingAgentRunResult`；
- 让 `AgentEvalRunner` 和 `AgentGrader` 使用与 Single Runtime 相同的外部接口和评分标准。

### 0.3 Day7 在能力树中的位置

Day7 位于以下能力交叉点：

```text
Agent Architecture
├── Planning: LeadAgent -> TaskPlan -> TaskDAG
├── Scheduling: ready/claim/start/complete/fail/block
├── Worker Runtime: WorkerExecutor -> CodingRuntime
├── Coordination: Mailbox claim/ack/release
├── Reliability: fencing/retry/recovery/durable commit
└── Evaluation: AgentEvalRunner -> AgentGrader
```

完成 Day7 后，你要能证明的不是“我写了一个多 Agent 类”，而是：

1. 能把已有单 Agent Coding Runtime 作为可替换执行能力复用；
2. 能把 DAG、Scheduler、Mailbox、Lifecycle 和 Durable Store 组合成一个闭环；
3. 能保证同一节点不会被重复 claim，迟到结果不会污染新 attempt；
4. 能区分控制面完成、执行器完成和外部 grader 成功；
5. 能用公平实验比较顺序 Team、并行 Team 和 Single Runtime。

### 0.4 Day7 与 Week6 的边界

**Week5 Day7 要完成：**

- Team control-plane MVP；
- `WorkerExecutor` 对现有 `CodingRuntime` 的适配；
- 有界、确定性的 ThreadPool 编排；
- scripted/fake runtime 下的完整状态机和失败恢复；
- 单 Worker、单 Task 的真实 LLM smoke 设计；
- 初步 Benchmark/Ablation 方案与公平性门禁。

**Week6 才完成：**

- per-worker Worktree；
- Worker patch 的隔离、导出与集成；
- 冲突检测与冲突解决；
- Reviewer/Quality Gate；
- 多 Worker 对同一代码库的真实并行写入；
- 更正式的 Team coding benchmark。

因此，Week5 的 Team 并发实验可以证明调度和控制面能力，但不能称为“完整多 Agent 并行编码 benchmark”。

### 0.5 推荐的总体架构

```text
CodingAgentRunRequest
        |
        v
TeamCodingRuntime
        |
        +--> LeadAgent.create_plan(task, repo_context)
        |          |
        |          v
        |      TaskDAG + WorkerAssignments
        |
        +--> TeamSessionRuntimeBuilder / DurableTeamRuntime
        |          |
        |          +--> AgentRegistry
        |          +--> TaskScheduler
        |          +--> DurableMailbox
        |          +--> AgentLifecycleManager
        |          +--> SQLiteTeamStateStore
        |
        +--> bounded ThreadPoolExecutor
                   |
                   v
              WorkerExecutor
                   |
                   v
              CodingRuntime.run()
                   |
                   v
          CodingAgentRunResult / failure
                   |
                   v
        Mailbox result envelope -> claim -> state transition -> ack
                   |
                   v
          TeamCodingRunResult
          /                 \
CodingAgentRunResult    TeamRunArtifact
                   |
                   v
        common result + artifact reference
                   |
                   v
          AgentEvalRunner -> AgentGrader
```

### 0.6 本日建议的文件地图

以下文件是后续实现时的建议，不在本轮创建：

| 文件 | 主要职责 |
|---|---|
| `codeteam/agent_team/team_runtime.py` | Team 顶层编排、状态机、有界并发、结果聚合 |
| `codeteam/agent_team/worker_executor.py` | `WorkerAssignment + TaskClaim` 到 `CodingAgentRunRequest` 的适配 |
| `codeteam/agent_team/team_models.py` | `TeamCodingRunResult`、`TeamRunArtifact`、`NodeExecutionResult`、`TeamMetrics` 等结构模型 |
| `codeteam/agent_team/worker_pool.py` | 三个静态本地 Worker 的注册、capability 规范化和匹配策略 |
| `codeteam/agent/runtime_models.py` | 只增加 Runtime 中性的 artifact 引用；不加入 Team 调度专属字段 |
| `tests/agent_team/test_worker_executor.py` | Worker 请求映射、异常、fencing 元数据测试 |
| `tests/agent_team/test_team_runtime.py` | 线性/菱形/扇出汇合 DAG 与并发状态机测试 |
| `tests/agent_team/test_team_runtime_recovery.py` | interruption、retry、stale result、process resume 测试 |
| `tests/evaluation/test_team_runtime_integration.py` | Team Runtime 接入 `AgentEvalRunner/AgentGrader` 的统一评分测试 |
| `evals/week5/benchmark_team_runtime.py` | 1 Worker 与 3 Worker 的确定性 benchmark |
| `evals/week5/compare_single_team.py` | Single 与 Team 的初步架构对照 |
| `evals/week5/smoke_team_runtime.py` | 由学习者手动执行的 B01 真实 LLM 单节点 smoke；Coder/Test 自动验收不调用真实 API |
| `docs/design_decisions/DD-W5-07.md` | Day7 核心设计决策 |
| `docs/design_decisions/DD-W5.md` | Week5 汇总设计决策 |
| `docs/failure_cases/W5_FAILURES.md` | Week5 失败案例汇总 |
| `docs/reports/W5_REPORT.md` | Week5 证据与未验证范围 |

### 0.7 已确认的 Day7 V1 设计选择

以下四项已由学习者确认，不再作为开放问题：

| 设计项 | Day7 V1 决策 |
|---|---|
| Team 详细结果 | 独立 `TeamRunArtifact`；通用 `CodingAgentRunResult` 只保存公共结果和中性 artifact 引用 |
| 节点预算 | Lead 提供 `1..5` 相对权重，Runtime 在全局硬预算、20% 预留和节点上下限内归一化分配 |
| Worker 注册 | 静态本地注册 3 个 Worker；capability 子集是硬门禁，同 role 优先，`GENERAL` 只在兼容时兜底 |
| 真实 LLM smoke | B01、单 Worker、确定性单节点 DAG、沿用 `secrets.local.env` 中已验证的 OpenAI-compatible 模型 |

这些选择形成新的不变量：

```text
I11. Team scheduling details live in TeamRunArtifact, not in common result fields.
I12. Lead proposes relative weights; Runtime owns absolute budgets and the ledger.
I13. Role fallback never bypasses required-capability checks.
I14. Week5 real LLM smoke uses deterministic one-node planning and max concurrency 1.
```

#### 静态本地 Worker Pool

初始配置固定为：

```yaml
worker-general-1:
  role: GENERAL
  capabilities: [read, search, patch, test, git_diff]

worker-backend-1:
  role: BACKEND
  capabilities: [python, api, database, read, search, patch, test, git_diff]

worker-test-1:
  role: TEST
  capabilities: [pytest, regression, review, read, search, patch, git_diff]
```

Lead 独立存在，不计入这三个 Worker。上述 `capabilities` 表示 Worker 的能力上限，不代表每个 assignment 都能使用全部能力。只读 TEST/REVIEW assignment 应通过 assignment execution scope 禁止 patch，即使选中的 Worker 本身具有 `patch` capability。

#### 已确认的 B01 smoke 配置

```yaml
task: B01
suite: evals/week4/agent_task_suite_v1.jsonl
provider: openai-compatible
model: secrets.local.env 中 CODETEAM_LLM_MODEL
temperature: 0
response_mode: auto
worker_count: 1
max_concurrency: 1
dag: deterministic-single-node
context_budget: 4096
max_output_tokens: 4096
model_context_window: 32768
max_steps: 20
max_tool_calls: 40
max_repairs: 3
max_protocol_repairs: 2
timeout_seconds: 900
```

B01 是 L1 小型 bug，目标是修复 expired refresh token 被映射为通用服务器错误的问题。其 public verification、task verification、hidden acceptance 和 pristine oracle 已存在，适合隔离“Team 接线错误”与“模型能力不足”。这个 smoke 只能证明执行链贯通，不能证明并行加速或 Team 优于 Single Runtime。

---

## Step 0：冻结事实、能力边界与 Invariants

### 本步目标

先把 Day7 允许做什么、禁止做什么和必须保持的安全不变量写清楚，再创建类。这样可以防止实现过程中不知不觉重写 Day5/Day6，或把 Week6 的 patch integration 偷渡进来。

### 为什么先做

多 Agent 编排最容易出现的错误不是语法错误，而是职责重叠：Scheduler 也调 LLM、Worker 也改任务状态、Mailbox 也当数据库、Evaluator 也参与执行。职责重叠会制造多个 Source of Truth。

### 当前可复用接口

- `LeadAgent.create_plan(task, repo_context) -> LeadPlanningResult`
- `TaskDAG.from_lead_planning_result(...)`
- `DurableTeamRuntime.schedule()`
- `DurableTeamRuntime.claim(lease)`
- `DurableTeamRuntime.start(claim)`
- `DurableTeamRuntime.complete(claim)`
- `DurableTeamRuntime.fail(claim, retryable=...)`
- `DurableTeamRuntime.send_message(...)`
- `DurableTeamRuntime.claim_message(recipient_id)`
- `DurableTeamRuntime.ack_message(message_claim)`
- `CodingRuntime.run(request) -> CodingAgentRunResult`
- `AgentGrader.grade(...) -> GradeResult`

### 建议先写下的核心 Invariants

```text
I1. Only the coordinator mutates DurableTeamRuntime during a live run.
I2. Worker threads execute CodingRuntime but do not mutate Scheduler directly.
I3. Every completion/failure is fenced by runtime_id + worker_generation + attempt.
I4. A node has at most one active future for its current attempt.
I5. Every durable result message is acked only after its scheduler transition commits.
I6. DAG terminal does not imply grader success.
I7. Team parallelism must never share a writable Worktree in Week5.
I8. Interruption must leave enough durable state for Day6 reconciliation.
I9. Token/cost totals are sums, not wall-clock-normalized values.
I10. No retry may silently increase the configured global budget.
```

### Python 初学知识

这里暂时不写代码，但要理解“invariant”不是普通注释。它是一条在每个公开操作前后都必须成立的条件。测试会从不同入口反复攻击这些条件。

### 本步测试设计

先建立一张 invariant-to-test 表。例如：

| Invariant | 未来测试 |
|---|---|
| I3 | attempt1 的迟到结果不能完成 attempt2 |
| I4 | 三个 Worker 并发 claim 时，同一 node 只返回一个 claim |
| I5 | Scheduler transition 失败时 message 不 ack，可在恢复后重放 |
| I7 | `max_workers > 1` 且 shared writable workspace 时构造请求被拒绝 |

### 常见错误

- 把“线程安全”误认为“业务状态一定正确”；
- 把 `Future` 当 durable state；
- 把 `TaskStatus.COMPLETED` 当最终评测通过；
- 为了演示并发，提前允许多个真实 Agent 写同一目录。

### 完成标志

- 你能口头解释十条 invariants；
- 你能指出每条 invariant 由哪个组件负责；
- Day7/Week6 边界没有模糊项。

### 与下一步关系

Step 1 会把这些不变量落实到 Team Runtime 的输入、输出和终态契约中。

---

## Step 1：定义 Team Runtime 输入、输出与完成契约

### 本步目标

先定义 Team Runtime 的公共边界，尤其是“完成”到底是什么意思。

### 为什么现在做

如果先写执行循环，再考虑返回值，往往会把 Scheduler 的 `COMPLETED` 直接映射成任务成功。正确顺序是先定义三层结果：

1. **Node execution result**：某个节点的一次 attempt 执行结果；
2. **Team control result**：DAG 是否终态、哪些节点失败或阻塞；
3. **Evaluation result**：补丁是否通过 grader。

### 涉及的当前文件与接口

- `codeteam/agent/runtime_models.py`
  - `CodingAgentRunRequest`
  - `CodingAgentRunResult`
  - `RuntimeStatus`
- `codeteam/evaluation/agent_runner.py`
  - `CodingRuntime` Protocol
  - `AgentEvalRunner`
- `codeteam/evaluation/agent_grader.py`
  - `AgentGrader`

### 已确认的结果模型

建议放在 `codeteam/agent_team/team_models.py`：

```python
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from codeteam.agent.runtime_models import CodingAgentRunResult


class TeamControlStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class RuntimeArtifactRef(BaseModel):
    kind: str
    path: Path  # Session 目录内的相对路径，例如 artifacts/team_run.json
    schema_version: int = Field(ge=1)
    sha256: str


# 对现有 CodingAgentRunResult 的唯一中性扩展：
# artifacts: tuple[RuntimeArtifactRef, ...] = ()


class NodeExecutionResult(BaseModel):
    node_id: str
    worker_id: str
    runtime_id: str
    worker_generation: int
    attempt: int
    status: str
    runtime_result: CodingAgentRunResult | None = None
    failure_type: str | None = None
    failure_message: str | None = None


class TeamRunArtifact(BaseModel):
    schema_version: int = 1
    task_id: str
    control_status: TeamControlStatus
    node_results: tuple[NodeExecutionResult, ...]
    dag: dict[str, object]
    worker_assignments: tuple[dict[str, object], ...]
    mailbox_messages: tuple[dict[str, object], ...]
    metrics: "TeamMetrics"
    event_timeline: tuple[dict[str, object], ...]
    blocked_nodes: tuple[str, ...] = ()
    failure_reason: str | None = None


class TeamCodingRunResult(BaseModel):
    runtime_result: CodingAgentRunResult
    artifact: TeamRunArtifact
```

这个模型落实了已确认的职责划分：

- `runtime_result` 只承载最终状态、summary、diff、changed files、verification、usage、duration、failure category 和 artifact reference；
- `artifact` 承载 DAG、Worker 分配、每个节点的结果、Mailbox、并发指标、retry/block 传播和 Team event timeline；
- `artifact` 单独写入 Session 受控目录中的 `team_run.json`；
- 通用 Result 只增加 Runtime 中性的 artifact 引用，例如 `RuntimeArtifactRef(kind, path, schema_version, sha256)`；
- 不把 `TeamMetrics`、Worker ID、Mailbox message 等 Team 专属可选字段塞进单 Agent Result。

`Path` 只是参考代码中的 artifact 路径类型。正式持久化时必须拒绝绝对路径和 `..`，只保存相对于 Session 目录的受控路径，写入后记录哈希；不得接受模型提供的任意路径。

持久化发布顺序固定为：先用 temp + flush + fsync + replace 原子写入 `artifacts/team_run.json`，计算 SHA-256，再保存带 `RuntimeArtifactRef` 的公共结果。这样 crash 最多留下一个未被引用的完整 artifact，不会让已发布的公共结果指向缺失或半写文件。

### 推荐公共调用契约

为了直接接入 `AgentEvalRunner`，建议：

```python
class TeamCodingRuntime:
    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        team_result = self.run_team(request)
        return team_result.runtime_result

    def run_team(self, request: CodingAgentRunRequest) -> TeamCodingRunResult:
        ...
```

`run()` 满足现有 `CodingRuntime` Protocol；`run_team()` 为 Team 专属调试、报告与测试提供完整结果。

### 为什么不直接修改 `CodingAgentRunResult`

当前 Single Runtime 和 grader 已稳定依赖这个模型。Day7 若向它塞入大量 Team 专属字段，会扩大回归面。更稳妥的 V1 是：

- Team 内部返回 `TeamCodingRunResult`；
- 对外只返回其中的 `runtime_result`；
- Team 详细指标写入独立 `team_run.json`；
- 通用模型只提升 `RuntimeArtifactRef` 这类跨 Single/Team/Reviewer 都成立的概念；
- Week6 后再根据真实使用证据决定哪些指标值得提升为公共字段。

### 完成语义

```text
TeamControlStatus.COMPLETED
    = 所有 DAG 节点均处于 COMPLETED，且没有未处理 Future/Message

CodingAgentRunResult.status == RuntimeStatus.COMPLETED
    = Team 执行器成功产出可供 grader 检查的 workspace/result

GradeResult.success == True
    = visible verification + regression + hidden acceptance + security 等最终通过
```

前两项不能替代第三项。

### Python 初学知识

- `Protocol` 是结构化接口：不要求继承，只要方法签名匹配即可；
- Pydantic `BaseModel` 会在构造时校验字段，并能稳定输出 JSON；
- `tuple[...]` 比可变列表更适合作为最终结果快照；
- `A | None` 表示值可以是 `A` 或 `None`。

### 本步测试

1. `TeamCodingRuntime` 可被赋给声明为 `CodingRuntime` 的变量；
2. 空 DAG 不应被静默视为成功；
3. 有 `BLOCKED` 节点时 control status 为 failed；
4. 全部 node completed 时只表示 control completed；
5. grader 仍可把 actor completed 判为 acceptance failed；
6. `team_run.json` round-trip 后保留 DAG、attempt、Mailbox 和 metrics；
7. common result 只有 artifact reference，没有 Team 专属调度字段；
8. artifact path 越出 Session 目录时拒绝持久化；
9. artifact hash 与写入内容匹配。

### 常见错误

- 在 `TeamRunArtifact` 里保存线程、Future 或 SQLite connection；
- 把 `failure_message` 当异常对象持久化；
- 用 `last_team_result` 这种可变全局属性向 evaluator 传指标，导致并发 run 互相覆盖。

### 完成标志

- 输入仍是现有 `CodingAgentRunRequest`；
- `run()` 返回现有 `CodingAgentRunResult`；
- Team 专属结果使用 `TeamCodingRunResult + TeamRunArtifact`；
- artifact 独立写入，common result 只有引用；
- 三层完成语义有测试。

### 与下一步关系

Step 2 将实现最小适配器，把 Scheduler 给出的 assignment/claim 转换成单 Agent Runtime 能理解的请求。

---

## Step 2：实现 `WorkerExecutor` 适配器

### 本步目标

让一个 Worker 能执行一个已 claim 的 DAG 节点，但不让 Worker 自己管理 Scheduler 状态。

### 为什么现在做

`WorkerAssignment` 描述“团队要做什么”，`CodingAgentRunRequest` 描述“单 Agent Runtime 怎么运行”。两者含义不同，需要一个显式适配层，而不是在 Team 主循环里到处拼字段。

### 当前真实输入

`WorkerAssignment` 当前包含：

- `assignment_id`
- `task_id`
- `source_step_id`
- `role`
- `goal`
- `expected_output`
- `relevant_files`
- `verification`

`TaskClaim` 当前至少携带：

- `node_id`
- `worker_id`
- `attempt`
- `claimed_at`
- `runtime_id`
- `worker_generation`

### 建议文件与接口

文件：`codeteam/agent_team/worker_executor.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from codeteam.agent.runtime_models import (
    CodingAgentRunRequest,
    CodingAgentRunResult,
)
from codeteam.evaluation.agent_runner import CodingRuntime


@dataclass(frozen=True)
class WorkerExecutionRequest:
    parent_request: CodingAgentRunRequest
    assignment: WorkerAssignment
    claim: TaskClaim
    workspace_root: Path


class WorkerExecutor:
    def __init__(self, runtime: CodingRuntime) -> None:
        self._runtime = runtime

    def execute(
        self,
        request: WorkerExecutionRequest,
    ) -> NodeExecutionResult:
        child_request = self._build_runtime_request(request)
        result = self._runtime.run(child_request)
        return self._to_node_result(request, result)
```

### `_build_runtime_request()` 要做什么

建议明确映射：

```text
child task_id
  = <parent-task-id>:<node-id>:attempt-<attempt>

child task
  = assignment.goal
    + expected_output
    + relevant_files
    + verification
    + “只完成当前节点，不擅自扩展其他 DAG 节点”

workspace_root
  = Week5 scripted test 的虚拟 workspace
  = Week5 real smoke 的单一 workspace（同时 max_workers 必须为 1）

provider/model/context settings
  = 从 parent_request 继承，不在 turn 中偷偷切换
```

### Worker 注册与兼容匹配

Day7 V1 不允许 Lead 动态创建 Worker。启动时由本地 bootstrap 注册固定三人池：

```python
STATIC_WORKERS = (
    AgentInfo(
        identity=AgentIdentity(
            agent_id="worker-general-1",
            display_name="General Worker",
        ),
        role=AgentRole.GENERAL,
        capabilities=("read", "search", "patch", "test", "git_diff"),
    ),
    AgentInfo(
        identity=AgentIdentity(
            agent_id="worker-backend-1",
            display_name="Backend Worker",
        ),
        role=AgentRole.BACKEND,
        capabilities=(
            "python", "api", "database", "read", "search",
            "patch", "test", "git_diff",
        ),
    ),
    AgentInfo(
        identity=AgentIdentity(
            agent_id="worker-test-1",
            display_name="Test Worker",
        ),
        role=AgentRole.TEST,
        capabilities=(
            "pytest", "regression", "review", "read", "search",
            "patch", "git_diff",
        ),
    ),
)
```

当前 `WorkerAssignment` 只有 `role`，Scheduler 主要按 role 精确匹配。Day7 需要把下面三个字段加入 assignment 的正式契约：

```python
required_capabilities: tuple[str, ...] = ()
allow_workspace_write: bool = True
budget_weight: int | None = None
```

为了满足“Lead 未给合法权重时退回平均分配”，不能简单使用 `Field(ge=1, le=5)` 后让整个 Plan 构造失败。建议用 `field_validator("budget_weight", mode="before")` 把缺失、布尔值、不可解析值和范围外整数规范化为 `None`，同时在 planning evidence 中保留原始值，并在 `TeamRunArtifact` 记录 `weight_fallback_reason`。Runtime 看到任一节点为 `None` 时，对该批节点统一使用平均权重 `1`，避免一半使用 Lead 权重、一半使用默认值造成难以解释的分配。

```python
@field_validator("budget_weight", mode="before")
@classmethod
def _normalize_budget_weight(cls, value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if 1 <= parsed <= 5 else None
```

这里的 `isinstance()` 先把 `object` 收窄为 `int` 或 `str`，因此不需要 `Any` 或 `type: ignore`。`mode="before"` 会在 Pydantic 正式类型转换前看到原始模型输出。

还需要让 Scheduler 使用一个明确的 compatibility policy。不能由 TeamCodingRuntime 绕过 Scheduler 私自把任务塞给某个 Worker，否则会形成第二个调度权威。

```python
def compatibility_rank(
    assignment: WorkerAssignment,
    worker: AgentInfo,
) -> int | None:
    required = set(assignment.required_capabilities)
    available = set(worker.capabilities)
    if not required.issubset(available):
        return None
    if worker.role is assignment.role:
        return 0
    if worker.role is AgentRole.GENERAL:
        return 1
    return None
```

匹配顺序固定为：

1. `required_capabilities <= worker.capabilities` 是不可绕过的硬条件；
2. capability 合法时，相同 role 优先；
3. 没有同 role specialist 时，`GENERAL` 可以兜底；
4. 同一级候选按 `worker_id` 稳定排序；
5. 没有兼容 Worker 时返回结构化 `NO_COMPATIBLE_WORKER` 并暂停 Team；这属于可修复的资源/配置缺口，不把节点伪装成依赖失败的 `BLOCKED`，也不得悄悄跨 role 执行。

`allow_workspace_write=False` 是本次 assignment 的权限收窄。即使 TEST Worker 具备 `patch` 能力，WorkerExecutor 也必须在 child request/tool policy 中关闭 patch；Worker 的能力上限不能扩大 assignment 授权。

### Budget 不能简单复制

如果每个节点都复制顶层完整 token/tool budget，三个节点可能消耗三倍预算。建议引入显式的 `TeamBudgetPolicy`：

```python
class TeamBudgetPolicy(Protocol):
    def allocate(
        self,
        *,
        parent: CodingAgentRunRequest,
        assignments: tuple[WorkerAssignment, ...],
    ) -> "TeamBudgetAllocation":
        ...
```

`WorkerAssignment.budget_weight` 是 Lead 权重建议的唯一来源，不再并行传入第二份 `weights` 字典。Runtime 读取、校验后生成 `TeamBudgetAllocation`；后续调度只读取 allocation，不能再回头修改 Lead 原值。

这里要先校正一个当前接口事实：现有 `CodingAgentRunRequest` 有 `max_steps`、`max_tool_calls`、`max_repairs`、`context_budget` 和 `max_output_tokens`，但没有 Team 级 `max_total_tokens` 或 `max_cost_usd`。其中 `context_budget=4096` 是**单次模型输入上下文上限**，不是整个 Team 只能消耗 4096 tokens。

因此 Day7 应新增 Team 层的预算配置和运行账本，而不是假装当前 request 已经提供全部总账字段：

```python
from pydantic import BaseModel, Field


class TeamBudgetLimits(BaseModel):
    max_steps: int = Field(gt=0)
    max_tool_calls: int = Field(gt=0)
    max_repairs: int = Field(ge=0)
    reserve_ratio: float = Field(default=0.20, ge=0.0, lt=1.0)
    min_steps_per_node: int = Field(default=1, gt=0)
    max_steps_per_node: int = Field(gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


class TeamBudgetLedger(BaseModel):
    limits: TeamBudgetLimits
    allocated_steps: dict[str, int]
    used_steps: int = 0
    used_tool_calls: int = 0
    used_repairs: int = 0
    used_input_tokens: int = 0
    used_output_tokens: int = 0
    used_cost_usd: float = 0.0
```

V1 至少把 steps、tool calls 和 repairs 作为硬预算。tokens/cost 必须完整聚合；一旦 `max_total_tokens/max_cost_usd` 被配置，也必须在 dispatch/retry 前进行硬门禁。未配置 token/cost cap 时不得声称“已有 token/cost 硬门禁”，只能报告实际消耗和由 step/context 上限形成的理论边界。

Day7 V1 确定采用“受约束的 Lead 权重分配”，而不是在平均和权重之间继续摇摆：

1. `TeamBudgetLimits` 根据顶层 request 和 Team 配置确定全局硬预算；
2. Team Runtime 预留 20% 给最终验证、集成和失败恢复；
3. Lead 只为节点建议 `1..5` 的相对权重，不允许给绝对 steps/tokens；
4. Runtime 校验并归一化权重；
5. 每个节点应用配置中的最低和最高配额；
6. 权重缺失、越界或无法解析时，所有节点退回平均权重 `1`；
7. 若最低配额之和已经超过可分配预算，配置无解并 fail closed，不能超配；
8. retry 从该节点及 Team 剩余 ledger 扣减，不创建新预算；
9. 所有 attempts 的实际消耗汇总后不得超过已配置的 Team 全局硬预算。

参考计算：

```text
global max_steps = 60
20% finalization/recovery reserve = 12
allocatable = 48

weights:
  implementation = 3
  tests = 2
  review = 1

normalized allocation:
  implementation = 48 * 3/6 = 24
  tests = 48 * 2/6 = 16
  review = 48 * 1/6 = 8
```

上下限调整不能简单逐项 clamp 后结束，因为 clamp 后总和可能不再等于 48。正确思路是：先满足所有 minimum，再按权重分剩余量；碰到 maximum 的节点停止分配，把余额重新分给仍可增长的节点。循环最多使一个节点到达上限，因此是有界算法。

Team 层的 20% reserve 与现有单 Worker Runtime 的 `finalization_reserve_steps` 必须来自同一份预算，不能重复计算成额外预算。例如 B01 的 `max_steps=20` 中，4 steps 是最终化预留，整个 child request 仍然最多 20 steps，不是 24。

每个节点和总账必须记录：

- allocated budget；
- actual consumption；
- unused budget；
- retries consumed；
- Team remaining hard budget；
- finalization/recovery reserve consumed；
- wall-clock 与 aggregate compute。

### 异常边界

`WorkerExecutor.execute()` 可以捕获普通 `Exception` 并转换为 `NodeExecutionResult.failure_*`，但要注意：

- 不吞 `KeyboardInterrupt`、`SystemExit`；
- 不在这里调用 `scheduler.fail()`；
- 不在这里 ack Mailbox；
- 不伪造 `CodingAgentRunResult` completed；
- 原始异常只用于当前进程诊断，持久化时保存分类和脱敏消息。

### Python 初学知识

- 构造函数注入 `CodingRuntime` 让测试能传入 Fake；
- “Adapter” 是把一种接口翻译成另一种接口的对象；
- `try/except Exception` 不会捕获 `KeyboardInterrupt`，这是终止信号处理的重要边界；
- 不要使用可变默认参数，例如 `items=[]`。

### 本步测试

1. assignment 的 goal/expected output/verification 被正确写入 child request；
2. provider/model 和安全配置正确继承；
3. child task_id 包含 node/attempt，便于审计；
4. runtime completed/failed/paused 能映射到 node result；
5. runtime 抛普通异常时得到结构化 failure；
6. `KeyboardInterrupt` 不被吞；
7. WorkerExecutor 不调用 Scheduler、Mailbox 或 SQLite；
8. budget policy 不允许节点总预算超过 parent budget；
9. assignment 要求的 capability 在 Worker 中缺失时不 claim；
10. 同 role specialist 优先于 GENERAL；
11. specialist 缺失时兼容 GENERAL 能兜底；
12. GENERAL capability 不足时不能兜底；
13. 只读 assignment 即使匹配有 patch capability 的 Worker 也不能写；
14. 非法 Lead 权重回退平均分配；
15. min/max 重分配后总和不超过可分配预算；
16. retry 不重置节点或 Team ledger。

### 常见错误

- 把完整 Team plan 放入每个 Worker，造成上下文浪费和越权；
- 让 Worker 根据结果直接修改 TaskNode；
- 在异常路径丢失 `runtime_id/generation/attempt`；
- 用 Worker role 代替 assignment role，而不校验二者一致。
- 为了避免任务等待而忽略 capability，随便选一个 Worker；
- `GENERAL` fallback 绕过 capability 门禁；
- 将 Lead 的权重当成绝对预算；
- 对每个节点分别向上取整，最终总和突破全局预算。

### 完成标志

- Fake `CodingRuntime` 可以接收一个节点请求并返回结构化结果；
- WorkerExecutor 是纯执行适配器；
- 所有结果带完整 fencing 元数据；
- 三 Worker 静态注册和兼容匹配可解释、可测试；
- budget 行为可解释、可测试，且有全局硬账本。

### 与下一步关系

Step 3 会把多个 node result 聚合为 Team 级使用量和调度指标。

---

## Step 3：定义 `TeamRunArtifact`、Node Result、Usage 与 Metrics

### 本步目标

建立一个既能回答“任务结果是什么”，又能回答“并行是否真的有效”的指标模型。

### 为什么现在做

如果等执行循环写完后再补指标，很多关键时间点已经丢失。例如节点何时 ready、等待 Worker 多久、何时真正开始执行，这些无法从最终状态反推。

### 建议模型

```python
@dataclass(frozen=True)
class NodeTiming:
    ready_at_monotonic: float
    claimed_at_monotonic: float
    started_at_monotonic: float
    finished_at_monotonic: float

    @property
    def scheduler_wait_seconds(self) -> float:
        return self.started_at_monotonic - self.ready_at_monotonic

    @property
    def busy_seconds(self) -> float:
        return self.finished_at_monotonic - self.started_at_monotonic


@dataclass(frozen=True)
class TeamUsage:
    input_tokens: int
    output_tokens: int
    total_cost: float
    tool_calls: int


@dataclass(frozen=True)
class TeamMetrics:
    wall_seconds: float
    aggregate_worker_seconds: float
    scheduler_wait_seconds: float
    max_parallelism: int
    retries: int
    messages_sent: int
    messages_acked: int
    usage: TeamUsage
```

这些指标最终放入 `TeamRunArtifact.metrics`。每个节点的完整 `CodingAgentRunResult` 放在 artifact 的 node result 中；公共 `CodingAgentRunResult` 只汇总公共 usage/duration/failure，并保存 `team_run.json` 的中性引用。

### 指标公式

```text
wall time
  = team_finished_at - team_started_at

aggregate worker time
  = sum(each attempt busy_seconds)

utilization
  = aggregate_worker_time / (configured_workers * wall_time)

speedup for 3 workers
  = T_1_worker / T_3_workers

parallel efficiency
  = speedup / 3

aggregate tokens/cost/tool calls
  = sum(all attempts, including failed/retried attempts)
```

失败 attempt 的消耗不能删除，否则 Team 看起来会比实际便宜。

### 时间选择

- 延迟和持续时间：使用可注入 monotonic clock；
- 审计时间：使用 UTC wall clock；
- 不要用 wall clock 做 duration 相减，因为系统时间可能跳变。

### Team 结果至少回答的问题

- DAG 是否全部完成？
- 哪些节点 failed/blocked？
- 每个节点执行了几次？
- 哪个 attempt 被最终接受？
- 最大并行度是多少？
- 等待调度和真正执行分别多久？
- token/cost/tool calls 总量是多少？
- 结果属于 provider、environment、protocol 还是 agent failure？

### Failure taxonomy

建议从 Day7 开始统一：

```text
planning_failure
scheduler_failure
worker_unavailable
worker_runtime_failure
provider_failure
environment_failure
protocol_failure
verification_failure
regression_failure
security_failure
durability_failure
interrupted
```

这些分类用于统计，不能替代原始可读 failure message。

### Python 初学知识

- `@property` 让方法像只读属性一样访问；
- 聚合时优先使用生成器：`sum(item.cost for item in results)`；
- 除法前检查 `wall_seconds > 0`，防止 `ZeroDivisionError`；
- 金额若要长期记账应考虑 `Decimal`，当前若沿用项目 `float` 必须保持一致。

### 本步测试

1. 两个成功 attempt 的 token/cost 正确求和；
2. 失败后 retry 的两次 usage 都计入；
3. scheduler wait 与 busy time 不混淆；
4. 零时长不会除零；
5. max parallelism 由 overlap 计算，而不是简单等于 worker 数；
6. Team control completed 但 grader failed 时两个字段同时保留。

### 常见错误

- 用 `max(worker duration)` 代替真实 wall time；
- 只统计最终成功 attempt；
- 把配置的 Worker 数当实际最大并行数；
- token 并发后取最大值而不是求和。

### 完成标志

- 每个指标有明确定义和测试；
- Single/Team 对照可以使用同一组质量和成本字段；
- `TeamRunArtifact` 可独立序列化、哈希和回读；
- wall latency 与 aggregate compute 被明确分开。

### 与下一步关系

Step 4 将用这些模型搭建 Team 执行状态机。

---

## Step 4：实现 Team 执行状态机

### 本步目标

先完成单线程协调器版本：能够从 plan 一直运行到 DAG 终态，不追求并行。

### 为什么先单线程

并发会放大状态机错误。先证明 claim/start/result/message/complete/fail 的顺序正确，再把 Worker 执行放进线程池。

### 建议的状态机

```text
INITIALIZING
  -> PLANNING
  -> HYDRATING_CONTROL_STATE
  -> SCHEDULING
  -> RUNNING
  -> COMPLETED | FAILED | PAUSED
```

节点状态继续使用现有 Scheduler 的 `TaskStatus`，不要另建一套节点状态枚举。

### 核心循环伪代码

```python
def run_team(self, request: CodingAgentRunRequest) -> TeamCodingRunResult:
    planning = self._lead.create_plan(task_spec, repo_context)
    durable = self._runtime_builder.build(...).runtime

    while True:
        durable.schedule()
        self._dispatch_ready_work(durable, request)
        self._consume_finished_work(durable)

        if self._is_terminal(durable):
            break
        if self._is_interrupted():
            return self._pause(durable)
        if self._no_progress_possible(durable):
            return self._fail_closed(durable)

    return self._aggregate(durable)
```

真实实现不能使用无条件 `while True` 加 sleep。单线程 V1 每轮必须发生下列之一：

- 新 claim；
- 一个执行结果返回；
- 一个状态改变；
- 到达 terminal/paused/fail-closed。

否则立即判定 no progress，避免无限循环。

### 推荐的 result 提交流程

即使单线程，也按未来 durable 流程实现：

```text
WorkerExecutor returns NodeExecutionResult
  -> create compact NodeResultEnvelope
  -> DurableTeamRuntime.send_message(to coordinator)
  -> claim_message(coordinator)
  -> validate envelope fencing
  -> complete(claim) or fail(claim)
  -> ack_message(message_claim)
```

为什么不是直接 `complete()`？因为 Day7 要验证 Mailbox 的 durable claim/ack 语义，并为进程中断恢复保留未处理结果。

### Ack 顺序

必须是：

```text
claim result message
-> validate runtime/generation/attempt
-> commit scheduler transition
-> ack message
```

如果先 ack 后 complete，而 complete 时进程崩溃，结果消息已经消失，任务却仍 RUNNING，形成 lost-result window。

如果 complete 成功、ack 前崩溃，恢复后会重放消息；fencing 和幂等状态检查应让它成为安全重复，而不是重复完成。

### Python 初学知识

- 状态机是“允许的状态 + 允许的迁移”；
- `match` 可读性很好，但要确保 Python 版本兼容；
- 私有辅助函数用于缩短主循环，每个函数只处理一个边界；
- `finally` 适合确保资源释放，但不能在里面覆盖原异常。

### 本步测试

先只用 scripted runtime：

1. 单节点成功；
2. 线性 DAG `A -> B -> C` 按顺序执行；
3. B 失败后 C blocked；
4. retryable failure 重试成功；
5. no progress fail closed；
6. result message 在状态提交后才 ack；
7. 重放已处理结果不产生重复 complete event；
8. stale attempt result 被拒绝。

### 常见错误

- Team 主循环直接修改 `TaskNode.status`；
- 读取 Scheduler 私有 dict 拼快照；
- ack 在状态迁移前；
- 没有终止条件；
- 同时把 Future 返回值和 Mailbox message 当两份独立结果权威。

### 完成标志

- 单线程 scripted runtime 能走完整 DAG；
- 结果提交经过 durable Mailbox；
- retry、block、stale result 行为正确；
- 主循环不存在 busy polling。

### 与下一步关系

Step 5 只替换“如何等待 Worker”，不改变状态机和持久化顺序。

---

## Step 5：加入有界并发与确定性调度

### 本步目标

使用标准库 `ThreadPoolExecutor` 并行执行互不依赖的 scripted Worker，同时保持所有控制面变更由协调器串行提交。

### 为什么选择线程池

当前 `CodingRuntime.run()` 是同步接口。Day7 V1 使用线程池可以：

- 不改现有 Runtime Protocol；
- 不引入 Celery、Ray、Redis；
- 不把整个项目改成 async；
- 用 `max_workers` 明确限制并发。

这不是说线程池永远是最佳生产方案，而是当前仓库最小、可验证的选择。

### 推荐并发所有权

```text
Coordinator thread:
  schedule / claim / start
  submit Future
  wait FIRST_COMPLETED
  send/claim result message
  complete/fail/ack

Worker thread:
  WorkerExecutor.execute()
  return NodeExecutionResult
  NEVER mutate DurableTeamRuntime
```

这样可以避免多个 Worker 同时争用 SQLite CAS 和 TeamStateCoordinator 锁，也让事件顺序更容易复现。

### 建议实现骨架

```python
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)


with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
    active: dict[Future[NodeExecutionResult], ActiveAttempt] = {}

    while not terminal:
        for work in self._next_claims(durable, capacity=self._capacity(active)):
            durable.start(work.claim)
            future = pool.submit(self._worker_executor.execute, work.request)
            active[future] = work.active_attempt

        if not active:
            if self._has_ready_or_retryable_work(durable):
                continue
            break

        done, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
        for future in self._stable_future_order(done, active):
            attempt = active.pop(future)
            result = self._resolve_future(future, attempt)
            self._submit_result(durable, result)
```

### 确定性规则

线程完成顺序天然不稳定。为便于测试和审计，建议：

- ready nodes 按 Scheduler 现有确定性顺序 claim；
- Worker 先按 capability 硬门禁过滤，再按“同 role、GENERAL fallback、worker_id”稳定排序；
- 同一轮多个 done Future 按 `(node_id, attempt, worker_id)` 排序提交；
- event seq 仍由 durable store 分配；
- 不要求 wall-clock 完成顺序完全一致，但要求状态和最终结果一致。

### 不允许 busy polling

错误示例：

```python
while active:
    for future in active:
        if future.done():
            ...
    time.sleep(0.01)
```

正确方向是 `wait(..., return_when=FIRST_COMPLETED)`。若还要响应 interruption，可使用有界 timeout 配合 `threading.Event`，但 timeout 不是轮询业务状态的借口。

### Workspace 安全门禁

Week5 必须有显式检查：

```text
if max_workers > 1 and workers_share_writable_workspace:
    reject configuration
```

scripted runtime 不做真实文件写入，可以跑 3 Worker。真实 Coding Runtime smoke 必须 `max_workers=1`。不要靠“任务大概改不同文件”来保证安全。

### Python 初学知识

- `Future[T]` 表示将来会产生一个 `T`；
- `ThreadPoolExecutor` 的 `with` 会在离开时关闭线程池；
- `dict[Future, ActiveAttempt]` 用来把异步结果对应回 claim；
- 多线程下 `list.append()` 某些实现细节安全不等于完整业务事务安全；
- `threading.Event` 用于通知，不持有业务数据权威。

### 本步测试

必须使用 `Event`/`Barrier` 和有界等待，不用长 sleep：

1. fan-out `A -> {B,C,D}` 在 3 Worker 下实际 overlap；
2. fan-in `{B,C,D} -> E` 只有三个前驱都完成后才执行；
3. 1 Worker 与 3 Worker 最终节点状态一致；
4. 同一 node 不会产生两个 active Future；
5. capability 不满足时不 claim，同 role 优先，兼容 `GENERAL` 可兜底；
6. 一个 Future 抛异常不导致其他 Future 状态丢失；
7. interruption 后不再提交新任务；
8. shared writable workspace + 3 Worker 被拒绝。

### 常见错误

- 在 Worker 线程中调用 `durable.complete()`；
- executor shutdown 时无限等卡死 Worker；
- Future cancel 成功就假设外部副作用已停止；
- 依赖测试中的 sleep 判断“已经并发”；
- 用不同 Worker 数时改变 task、预算或 grader。

### 完成标志

- 线性 DAG 在 3 Worker 时仍只有并行度 1；
- fan-out/fan-in 可达到预期最大并行度；
- 没有重复 claim；
- 三 Worker 静态池的 specialist/GENERAL 匹配顺序稳定；
- 控制面提交仍由一个协调器完成；
- 真实写 Workspace 的多 Worker 配置被 fail closed。

### 与下一步关系

Step 6 将线程内执行状态与 Day6 的 Session/SQLite 恢复入口正式连接起来。

---

## Step 6：接入 `DurableTeamRuntime`、SQLite 与 Session

### 本步目标

让 TeamCodingRuntime 的每个控制面变化都经过 Day6 durable gateway，并能从 Session resume 得到一个新的运行时实例。

### 为什么现在做

前几步先用进程内控制流证明执行顺序；现在才能安全接持久化。否则 persistence bug 和并发 bug 会混在一起，定位困难。

### 当前真实接口

- `TeamSessionRuntimeBuilder.build(SessionRuntimeBuildRequest) -> SessionRuntimeBuildResult`
- `SessionRuntimeBuildResult` 提供重建后的 runtime 和 TeamStateRef；
- `DurableTeamRuntime` 提供 mutation gateway；
- `SQLiteTeamStateStore.commit(... expected_revision ...)` 提供 CAS；
- Day6 resume 会创建新的 `runtime_id`，旧 lease/claim 失效。

### 建议 TeamCodingRuntime 依赖注入

```python
class TeamCodingRuntime:
    def __init__(
        self,
        *,
        lead: LeadAgent,
        runtime_builder: TeamSessionRuntimeBuilder,
        worker_executor: WorkerExecutor,
        worker_pool_factory: WorkerPoolFactory,
        clock: Clock,
        max_workers: int,
        result_sink: TeamRunArtifactSink,
    ) -> None:
        ...
```

不要把 SQLite 路径、Session 目录和 Worker 列表硬编码在 `run()` 中。

### 新 run 与 resume 的区别

```text
new run:
  Lead plan
  -> initialize Team SQLite state
  -> create fresh runtime_id
  -> schedule

resume:
  SessionService owns writer lock
  -> TeamSessionRuntimeBuilder load/reconcile/hydrate
  -> create new coordinator + new runtime_id
  -> invalidate old lease/claim/monotonic heartbeat
  -> reconcile CLAIMED/RUNNING
  -> TeamCodingRuntime continues schedulable work
```

Day7 不得绕过 Session writer lock 自己打开第二个 active runtime。

### 结果消息的 durable payload

不要把完整 `CodingAgentRunResult` 直接塞进 Mailbox JSON。建议保存：

```python
@dataclass(frozen=True)
class NodeResultEnvelope:
    message_id: str
    task_id: str
    node_id: str
    worker_id: str
    runtime_id: str
    worker_generation: int
    attempt: int
    status: str
    artifact_path: str | None
    input_tokens: int
    output_tokens: int
    cost: float
    failure_type: str | None
    failure_message: str | None
```

完整 stdout/messages/evidence 写入受控 artifact；Mailbox 只保存恢复决策所需摘要和引用。artifact path 必须受 Session 目录边界保护。

### CAS 与 poison 行为

Day7 不应重写 CAS。调用 durable mutation 时：

- 成功：得到新 revision；
- no-op：revision 不变；
- conflict：重新 load/reconcile 或 fail closed，不能覆盖；
- persistence failure：runtime poisoned，此轮停止调度；
- event observer failure：按 Day6 既有事务语义处理，不把 observer 当 commit。

### Python 初学知识

- dependency injection 让对象不负责创建所有依赖；
- CAS 是“只有 revision 仍等于我读到的值才写”；
- `Path.resolve()` 适合边界校验，但 macOS alias/symlink 需遵循项目已有 path policy；
- JSON 只能稳定保存基本类型，不适合保存任意 Python 对象。

### 本步测试

1. 所有 Scheduler 迁移都使 durable revision 单调增加；
2. no-op 不制造假 revision/event；
3. result message 与 state transition 的 crash window 可恢复；
4. CAS conflict 不覆盖新状态；
5. persistence failure 后不再 dispatch；
6. resume 后 runtime_id 改变；
7. 旧 lease/claim/result envelope 被拒绝；
8. 两个进程 resume 只允许一个 writer；
9. artifact path traversal 被拒绝。

### 常见错误

- TeamCodingRuntime 直接调用 Store 私有 SQL；
- 保存 ThreadPoolExecutor/Future；
- resume 后继续使用旧 monotonic timestamp；
- 为了方便，把完整 Python result pickle 到数据库；
- persistence failure 后继续在内存推进 DAG。

### 完成标志

- 新 run 和 resume 均通过 Day6 builder；
- 新进程一定得到新 runtime_id；
- durable revision/event/message 一致；
- 旧执行结果无法污染恢复后的任务。

### 与下一步关系

Step 7 会系统处理 Worker、provider、进程 interruption 等失败路径。

---

## Step 7：失败、重试、阻塞、中断与恢复

### 本步目标

把失败恢复做成状态机的一部分，而不是主循环外层一个宽泛 `except Exception`。

### 为什么现在做

Happy path 只证明系统能跑。Agent Runtime 真正的工程价值在于失败时仍保持可解释状态、预算约束和可恢复性。

### 失败处理矩阵

| 情况 | 当前 attempt | Task 状态 | 后继 | 是否重试 | 关键证据 |
|---|---|---|---|---|---|
| provider transient error，预算未耗尽 | failed | READY/PENDING for retry | 不阻塞 | 是 | attempt+1、usage 保留 |
| deterministic validation failure | failed | FAILED | 全部可达后继 BLOCKED | 否 | failure taxonomy |
| Worker heartbeat timeout | stale | 由 Lifecycle 回收 CLAIMED/RUNNING | 暂不阻塞或按 retry 结果 | 受预算约束 | old generation fenced |
| stale attempt completion | 不接受 | 当前新 attempt 不变 | 不变 | 否 | rejected event |
| stale runtime completion | 不接受 | resume 后状态不变 | 不变 | 否 | runtime_id mismatch |
| process interruption | 未知 | durable reconciliation 决定 | fail closed | 不盲目继续 | Session paused/recovery required |
| persistence failure | 不可信 | runtime poisoned | 停止 | 否 | durability failure |
| terminal node failure | exhausted | FAILED | 多级传播 BLOCKED | 否 | 每节点一次 transition |

### retry 的三个预算

不要只有一个 `max_retries`：

1. Scheduler task attempt budget；
2. Worker restart budget；
3. Team global token/cost/time budget。

三者相互独立。Worker 重启不应偷偷重置 task attempt，task retry 也不应重置 global token budget。

### interruption 流程

```text
SIGINT / cancellation requested
-> stop claiming new work
-> mark coordinator interrupted
-> request cancellation of not-yet-started Futures
-> do not claim cancellation stopped external side effects
-> persist known active attempts and pending messages
-> let SessionService pause/reconcile
-> return PAUSED or propagate controlled interruption
```

`Future.cancel()` 对已经运行的线程通常不会强制停止函数。fencing 能阻止迟到结果写入新状态，但不能撤回已经发生的文件或网络副作用。这一点必须写进 Failure Case。

### Worker generation 与 task attempt

必须重复确认：

- `generation`：同一个 worker_id 的运行实例版本；
- `attempt`：同一个 task node 的执行尝试次数；
- `runtime_id`：整个 Team runtime 实例；
- 三者都要校验，不能互相替代。

攻击示例：

```text
runtime-R1 / worker-W1 generation-2 / task-A attempt-1 starts
task-A retries -> attempt-2
worker restarts -> generation-3
process resumes -> runtime-R2

旧结果 R1/W1-gen2/A-attempt1 返回
=> 三层 fencing 均不匹配，必须拒绝
```

### Python 初学知识

- 自定义异常用于表达可恢复/不可恢复分类；
- `BaseException` 包含 `KeyboardInterrupt` 和 `SystemExit`，通常不能全局吞掉；
- `ExceptionGroup` 可表达多个并发失败，但 V1 也可以逐项结构化聚合；
- 幂等表示重复调用不会制造额外业务变化，不只是“没有抛异常”。

### 本步测试

1. fail once then retry success；
2. retry exhausted 后节点 FAILED、下游多级 BLOCKED；
3. 分叉/汇合 DAG 只阻塞依赖失败节点的分支；
4. repeated fail/complete message 不产生重复 event；
5. attempt1 迟到结果不能完成 attempt2；
6. old generation 回调在 restart 后被拒绝；
7. old runtime 回调在 process resume 后被拒绝；
8. Worker timeout 回收 CLAIMED 和 RUNNING；
9. STOPPED Worker 不被恢复成 READY；
10. interruption 后无新 claim，durable state 可 load；
11. persistence failure poison 后所有 dispatch 停止；
12. global budget exhausted 即使 task retry 尚有次数也停止。

### 常见错误

- 宽泛捕获后把所有错误都标 retryable；
- retry 时清空历史 usage；
- stale result 只检查 worker_id；
- 中断后等待线程无限结束；
- 把 fencing 宣称成 exactly-once side effect。

### 完成标志

- 失败矩阵的每一行都有测试；
- 三层 fencing 均生效；
- retry 和 restart 预算不会重置全局预算；
- interruption 后可恢复，且不虚假声称旧副作用已停止。

### 与下一步关系

Step 8 会把 Team Runtime 放入现有 EvalRunner，验证“同一评分标准”而不是 Team 自评成功。

---

## Step 8：接入 `CodingRuntime`、`AgentEvalRunner` 与 `AgentGrader`

### 本步目标

让 Single Runtime 和 Team Runtime 通过同一个 Protocol、同一个任务、同一个 grader 接受评测。

### 为什么现在做

如果 Team 使用单独的“宽松评分”，任何性能或成功率对比都失去意义。架构对照的第一原则是外部 oracle 相同。

### 当前真实链路

```text
AgentEvalRunner
  -> runtime.run(CodingAgentRunRequest)
  -> CodingAgentRunResult
  -> _runtime_to_actor_result(...)
  -> AgentGrader.grade(...)
  -> GradeResult
```

`AgentGrader` 的最终 success 不是只看 runtime status，它还要求：

- actor result completed；
- acceptance checks；
- regression checks；
- task verification；
- budget；
- security；
- pristine visible/acceptance oracle 原本必须失败，避免坏任务或泄漏答案。

### 推荐接入方式

```python
single_runner = AgentEvalRunner(
    project_root=project_root,
    runtime=single_runtime,
    grader=grader,
    ...,
)

team_runner = AgentEvalRunner(
    project_root=project_root,
    runtime=team_coding_runtime,  # same CodingRuntime Protocol
    grader=grader,                # exact same grader instance/config
    ...,
)
```

### Team 到 Coding result 的投影原则

- `status`：由 Team control outcome 映射，但不伪造 grader success；
- `workspace_root/diff/changed_files`：必须对应真实最终 workspace；
- `verification`：只放实际执行的验证，不根据 worker 文本声称；
- `input/output tokens/cost/tool calls`：所有 attempts 求和；
- `failure_type/message`：保留主失败分类；
- `events/evidence`：保留可审计引用，避免塞入不可序列化对象。

### 当前 Week5 的真实限制

由于没有 patch merge，Team 多 Worker 的真实 Coding result 无法可靠产生单一最终 diff。因此：

- scripted Team tests 可完整跑多 Worker，但不进入真实 patch grader；
- real LLM smoke 只跑一 Worker、一 Task；
- Single vs Team 初步对照可测编排 overhead 和接口一致性；
- 多 Worker coding quality 对照标记为 Week6 BLOCKED，不填虚假数字。

### Python 初学知识

- structural typing 让 Single/Team 不需要共同父类；
- composition 是“对象持有并调用另一个对象”，这里优于复制 grader；
- adapter 的输出必须保留语义，不只是字段类型匹配。

### 本步测试

1. `AgentEvalRunner` 能接受 fake TeamCodingRuntime；
2. Single 和 Team 使用同一 grader/config；
3. Team DAG completed 但 acceptance failed 时 final success 为 false；
4. Team aggregate usage 正确进入 budget grader；
5. security failure 不能被 Team status 覆盖；
6. pristine oracle 已通过时任务被拒绝；
7. Team runtime exception 被归类，不暴露 traceback 给结果文件。

### 常见错误

- Team 自己把“测试看起来通过”写成 success；
- 修改 grader 让 Team 更容易通过；
- Single 与 Team 使用不同总 token budget；
- 不统计 Lead 和协调消息的 token/cost。

### 完成标志

- Team 满足现有 `CodingRuntime`；
- 外部 grader 未被复制或降级；
- control completion 和 final success 可同时呈现不同值；
- Week5 真实评测限制被显式记录。

### 与下一步关系

Step 9 将建立无需真实 LLM 的确定性测试矩阵，先证明控制面正确。

---

## Step 9：建立 Scripted/Fake Runtime 确定性测试

### 本步目标

用可编程 Fake Runtime 覆盖所有 DAG、并发、failure、Mailbox 和 durable recovery 行为。

### 为什么 Fake 比真实 LLM 更适合这里

状态机测试需要精确制造：第几次失败、何时阻塞、哪个 Future 先完成、哪个旧结果迟到。真实模型既昂贵又不可重复，不能作为这些边界的首要证据。

### 建议 Fake 接口

```python
@dataclass(frozen=True)
class ScriptedOutcome:
    status: RuntimeStatus
    wait_for: threading.Event | None = None
    release: threading.Event | None = None
    exception: Exception | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class ScriptedCodingRuntime:
    def __init__(self, scripts: dict[str, deque[ScriptedOutcome]]) -> None:
        self._scripts = scripts
        self.calls: list[CodingAgentRunRequest] = []

    def run(self, request: CodingAgentRunRequest) -> CodingAgentRunResult:
        ...
```

key 可以使用 child task_id 或 node_id，但要避免测试通过解析自然语言 task prompt 猜节点。

### 必须覆盖的 DAG 形状

1. **Linear**：`A -> B -> C`
2. **Diamond**：`A -> {B,C} -> D`
3. **Fan-out/Fan-in**：`A -> {B,C,D,E} -> F`
4. **Layered**：多层多节点，验证每层 barrier
5. **Disconnected branch**：一个分支失败不误伤无关分支

每种至少在 1 Worker 和 3 Worker 下验证最终状态；可并行的形状还要验证 overlap 和 max parallelism。

### 完整测试地图

#### Scheduling

- ready 顺序稳定；
- 同一节点不重复 claim；
- required capability 不满足时不 claim；
- 同 role specialist 优先，缺失时兼容 `GENERAL` fallback；
- 无兼容 Worker 时暂停 Team，并产生明确 `NO_COMPATIBLE_WORKER` reason；
- capacity 满时不额外 claim；
- fan-in 必须等全部前驱；
- 重复 schedule 不产生重复 ready/event。

#### Failure and retry

- retryable fail then success；
- retry exhausted；
- terminal failure 多级 BLOCKED；
- 分叉/汇合传播正确；
- provider/environment/protocol 分类保留。

#### Fencing

- same worker attempt1 late result cannot complete attempt2；
- old worker generation result after restart rejected；
- old runtime result after resume rejected；
- owner mismatch rejected。

#### Mailbox

- send -> claim -> transition -> ack；
- transition failure 后 release 或保留 claim；
- ack token/claim 不匹配被拒绝；
- duplicate delivery 不重复完成；
- pending message 能从 SQLite 恢复；
- message order 和去重状态恢复。

#### Durability and interruption

- revision 单调；
- state/event 不 split brain；
- coordinator interruption 不丢 active/pending state；
- 子进程 `os._exit()` 后 resume 使用新 runtime_id；
- 两个 resume 只有一个 writer；
- poison 后不 dispatch。

#### Result and grading

- node results 全量聚合；
- retry usage 不丢；
- scheduler wait/busy/max parallelism 正确；
- Team completed 不覆盖 grader failed；
- Single/Team 走同一 AgentGrader。

#### Budget allocation

- Lead 权重 `3:2:1` 按硬预算正确归一化；
- 非法/缺失权重退回平均分配；
- minimum/maximum 约束后余额被重新分配；
- minimum 总和不可满足时 fail closed；
- 20% reserve 不与 Worker finalization reserve 重复增加；
- retry 和失败 attempt 都从同一 Team ledger 扣减；
- artifact 记录 allocated/actual/unused/aggregate compute。

### 并发测试方法

使用：

- `threading.Barrier`：证明多个 Worker 都到达同一点；
- `threading.Event`：测试控制何时释放；
- `join(timeout=...)` 或 Future timeout：保证失败时测试不会永久挂起；
- function-scoped `tmp_path`：隔离 Session/SQLite/Workspace。

不要使用长 `sleep()` 等待“应该发生的事情”。短 timeout 只用于防止测试挂死，不作为同步事实。

### 子进程 crash 测试

```text
parent creates tmp session/repo
-> subprocess starts Team Runtime
-> child writes sentinel after durable STARTED commit
-> parent observes sentinel
-> child os._exit(17) during controlled crash window
-> new subprocess resumes
-> assert new runtime_id and reconciled task/message state
```

命令必须：argv list、`shell=False`、timeout、capture output。不能用 graceful shutdown 冒充进程 crash。

### Python 初学知识

- `deque.popleft()` 适合按脚本顺序取 outcome；
- `Barrier(parties=3)` 只有三个线程都到达后才放行；
- 测试 fixture 默认应 function scope，避免状态泄漏；
- Fake 的价值是控制依赖，不是复制生产实现。

### 推荐未来测试命令

```bash
.venv/bin/python -m pytest tests/agent_team/test_worker_executor.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_runtime.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_runtime_recovery.py -q
.venv/bin/python -m pytest tests/evaluation/test_team_runtime_integration.py -q
```

### 完成标志

- 四种 DAG 形状、两种 Worker 数均有测试；
- concurrency 由 Event/Barrier 证明；
- fencing/Mailbox/durable recovery 不是只测 happy path；
- 测试无需真实 LLM 和网络。

### 与下一步关系

Step 10 才允许做一个极小真实 LLM smoke，用来验证 adapter 边界，不验证完整多 Worker coding。

---

## Step 10：真实 LLM 单 Task、单 Worker Smoke

### 本步目标

用 B01 验证 TeamCodingRuntime 可以真正调用现有 CodingAgentRuntime，并把结果交给相同 grader。所有真实 LLM 命令由学习者亲自执行；Coder/Test 自动验收只准备脚本、dry-run 和断言，不发送真实 API 请求。

### 为什么只做一个 Worker

当前没有 per-worker Worktree 和 patch merge。让多个真实 Worker 写同一目录会引入竞态、覆盖和不可审计副作用。因此 Day7 real smoke 固定使用一 Worker、确定性单节点 DAG，目标只是证明调用链贯通：

```text
DeterministicSingleNodePlanner(B01)
-> TeamCodingRuntime
-> one BACKEND assignment
-> one WorkerExecutor
-> CodingAgentRuntime
-> Patch + visible verification
-> TeamCodingRunResult
-> CodingAgentRunResult + TeamRunArtifact
-> AgentGrader
-> hidden acceptance
```

### 为什么固定选择 B01

B01 的任务是修复 expired refresh token 被错误映射为 generic server error。选择它的原因是：

- L1 小型 bug，修改面窄；
- public verification、task verification 与 hidden acceptance 已建立；
- pristine oracle 已验证；
- 历史单 Agent 运行稳定，可降低“模型本身偶然不会做”的干扰；
- 很适合区分 Team wiring failure 与 Worker coding failure。

第一次 smoke 不调用真实 Lead 自由拆分。使用 `DeterministicSingleNodePlanner` 产生唯一节点，把不确定性限制在真实 Worker LLM。

### 固定配置

```yaml
task: B01
suite: evals/week4/agent_task_suite_v1.jsonl
provider: openai-compatible
model: secrets.local.env 中已验证的 CODETEAM_LLM_MODEL
temperature: 0
response_mode: auto
worker_count: 1
max_concurrency: 1
dag: deterministic-single-node
context_budget: 4096
max_output_tokens: 4096
model_context_window: 32768
max_steps: 20
max_tool_calls: 40
max_repairs: 3
max_protocol_repairs: 2
timeout_seconds: 900
```

`CODETEAM_LLM_TEMPERATURE=0` 和 `CODETEAM_LLM_RESPONSE_MODE=auto` 可由命令行环境变量覆盖本地配置，但不要在终端输出 API key。模型名继续由 `secrets.local.env` 中已经验证的 `CODETEAM_LLM_MODEL` 提供。

### 建议配置门禁

```python
if use_real_coding_runtime and (
    max_workers != 1
    or max_concurrency != 1
    or planner_mode != "deterministic-single-node"
):
    raise UnsafeTeamWorkspaceConfigurationError(
        "Week5 real coding smoke requires one worker and one DAG node; "
        "per-worker worktrees arrive in Week6"
    )
```

### 真实 API 权限

教程不代表自动授权。实际执行前必须由你单独确认 provider、模型、预算和网络调用。本轮教程任务不运行真实 API。

### 先理解现有命令与 Day7 命令的区别

当前仓库已有的命令：

```bash
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --task-id B01 \
  --actor llm \
  --mode baseline \
  --context-budget 4096 \
  --max-output-tokens 4096 \
  --model-context-window 32768 \
  --max-steps 20 \
  --native-tools \
  --no-reasoning \
  --output evals/week5/agent_runs/b01-single-baseline
```

它当前固定构造 `CodingAgentRuntime`，属于 **Single Runtime baseline**，不能当作 Team smoke。当前 CLI 还没有 `--runtime team`，也不能把它写成已经支持 Team。

此外，当前 `AgentEvalRunner` 会按 `max_steps * 3` 推导 `max_tool_calls`，上面的 20 steps 实际对应 60 tool calls，不是本次 Team smoke 固定的 40。因此它可以用于确认 B01 的 Single 链路，但不能直接作为严格公平的 Single/Team 数值对照。周末 comparison 应让后续 smoke/experiment adapter 同时支持 `--runtime single|team`，并为两组显式设置相同的 40 tool-call hard cap。

### Day7 实现后先执行无 API dry-run

Day7 应新增计划中的 `evals/week5/smoke_team_runtime.py`。脚本必须先支持 `--dry-run`，验证 task、pristine oracle、配置、Worker、DAG、预算和输出路径，但不构造会发网络请求的真实 turn：

```bash
CODETEAM_LLM_TEMPERATURE=0 \
CODETEAM_LLM_RESPONSE_MODE=auto \
.venv/bin/python evals/week5/smoke_team_runtime.py \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --task-id B01 \
  --runtime team \
  --provider openai-compatible \
  --plan deterministic-single-node \
  --worker-count 1 \
  --max-concurrency 1 \
  --context-budget 4096 \
  --max-output-tokens 4096 \
  --model-context-window 32768 \
  --max-steps 20 \
  --max-tool-calls 40 \
  --max-repairs 3 \
  --max-protocol-repairs 2 \
  --timeout-seconds 900 \
  --output evals/week5/agent_runs/day7-b01-team-smoke \
  --dry-run
```

dry-run 必须输出脱敏 manifest，至少确认：

- selected task 是 B01；
- model 只显示模型名，不显示 API key；
- planner 是 deterministic single node；
- assignment role 是 BACKEND，required capabilities 至少包含 `python/api/read/search/patch/test/git_diff`；
- 首选 Worker 是 `worker-backend-1`；只有 specialist 不可用且 GENERAL 满足全部 required capabilities 时才允许 fallback；
- global/node/finalization budget 总和合法；
- `network_call_performed=false`。

### 由你亲自执行的真实 Team smoke 命令

只有 Step 0–9 测试、dry-run 和全量回归通过后，才去掉 `--dry-run`：

```bash
CODETEAM_LLM_TEMPERATURE=0 \
CODETEAM_LLM_RESPONSE_MODE=auto \
.venv/bin/python evals/week5/smoke_team_runtime.py \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --task-id B01 \
  --runtime team \
  --provider openai-compatible \
  --plan deterministic-single-node \
  --worker-count 1 \
  --max-concurrency 1 \
  --context-budget 4096 \
  --max-output-tokens 4096 \
  --model-context-window 32768 \
  --max-steps 20 \
  --max-tool-calls 40 \
  --max-repairs 3 \
  --max-protocol-repairs 2 \
  --timeout-seconds 900 \
  --output evals/week5/agent_runs/day7-b01-team-smoke
```

这条命令是 **Day7 后续实现的验收契约**。在 `smoke_team_runtime.py` 尚未实现前执行会得到“文件不存在”，这不是当前 CLI 已有能力。实现任务不得悄悄改用现有 Single Runtime 来伪装 Team smoke。

为了避免把偶然结果当结论，首次 smoke 只运行一次并保留原始证据；失败后先分类和修复，不使用循环重跑直到通过。

### 验证内容

1. deterministic planner 输出单个 BACKEND assignment；
2. WorkerExecutor 正确构造 child request；
3. Session/SQLite revision 正常推进；
4. CodingRuntime 返回真实 result；
5. `runtime_result` 不丢 diff/verification/usage，并引用 `team_run.json`；
6. `TeamRunArtifact` 保留 node result、attempt、Mailbox、预算和 timeline；
7. AgentGrader 使用现有标准；
8. public verification、task verification 和 hidden acceptance 有真实结果；
9. 无 traceback/secrets 泄漏；
10. manifest 标明这不是 multi-worker benchmark。

### Python 初学知识

- smoke test 只验证主链路能否工作，不替代系统性单元测试；
- fixture 是测试输入，不应被原地修改；
- reproducibility manifest 是运行元数据，不是测试结果本身。

### 常见错误

- smoke 成功一次就宣称 Team 更好；
- 使用 3 Worker 共享 Worktree；
- Team 给每个节点完整顶层预算；
- 失败后更换模型或预算却仍放入同一对照组。
- 用现有 Single `agent-eval` 命令冒充 Team smoke；
- 让真实 Lead 把 B01 拆成多个共享写节点。

### 完成标志

- 单 Worker Team 链路能调用真实 Runtime；
- grader 给出可审计结果；
- `runtime_result + team_run.json` 均成功持久化；
- 没有共享写并发；
- 报告明确其证据范围。

### 与下一步关系

Step 11 会设计 Week5 周末实验；其中确定性 benchmark 可以完整执行，真实 Team coding 只能作为 preliminary comparison。

---

## Step 11：Week5 Benchmark 与 Ablation

### 本步目标

定义公平、可复现的实验，周末统一执行。本教程不运行实验、不填写数字。

### Benchmark A：确定性 1 Worker vs 3 Workers

**目的：**测量 Team control plane 在已知 DAG workload 下的并行收益与开销。

**workload：**

- linear；
- diamond；
- fan-out/fan-in；
- layered；
- 相同 scripted work units；
- 相同 DAG、retry、message payload 和 persistence 配置。

**对照：**

```text
A1: TeamCodingRuntime, max_workers=1
A2: TeamCodingRuntime, max_workers=3
```

**指标：**

- wall latency p50/p95；
- aggregate worker time；
- scheduler wait；
- max parallelism；
- utilization；
- speedup；
- efficiency；
- retries/messages/events；
- SQLite commits/revision conflicts；
- 每节点 allocated/actual/unused budget；
- Team remaining budget 与 finalization/recovery reserve consumption；
- state correctness gate。

状态正确性必须先通过，速度更快但有重复 claim 的结果无效。

### Benchmark B：Single Runtime vs Team Runtime 初步编码对照

**目的：**验证架构接入、质量门禁和协调 overhead，而不是证明多 Worker 编码优势。

当前最多使用 Week4 的 11 个 `dev` task。不能描述为 held-out，也不能凭空写“10 task benchmark”。

**对照：**

```text
B1: existing CodingAgentRuntime
B2: TeamCodingRuntime with max_workers=1
```

由于 B2 只有一个 Worker，这主要测 Team control-plane overhead 和接口一致性。完整多 Worker coding comparison 留 Week6。

**共同门禁：**

- 相同 pristine task；
- 相同 base SHA；
- 相同 provider/model/reasoning；
- 相同 context；
- 相同总 token/tool/cost/time budget；
- 相同 grader；
- 相同 visible/hidden acceptance；
- 相同 security policy；
- 每次从干净 Worktree 开始。

### Ablation A：Team Sequential vs Team Parallel

这是合理的 ablation，因为只改变 `max_workers`，其他组件相同：

```text
Full: max_workers=3
Ablated: max_workers=1
```

主要在 scripted DAG 上执行。

### Single vs Team 不是严格纯 Ablation

Single Runtime 与 Team Runtime 同时改变了 planning、scheduler、mailbox、durability 和执行结构，因此它是**architecture comparison**，不能写成“只移除了 Team 的单一变量”。

### No-Mailbox Ablation 的门禁

只有先实现一个功能等价、可工作的 polling/queue adapter，才能比较：

```text
durable mailbox vs alternative result transport
```

如果替代 adapter 不存在，则标记 `NOT_RUN`。不能把 Mailbox 删除后让系统坏掉，再声称 Mailbox 带来 100% 提升。

### 公平预算

并行并不意味着预算乘以 Worker 数：

```text
Single total token budget = X
Team aggregate token budget = X

Single total cost cap = C
Team aggregate cost cap = C
```

Lead planning 和协调消息的 token/cost 也属于 Team 总成本。

Team 组还必须保存 Lead 原始权重、Runtime 归一化结果、每节点上下限、实际消耗和未使用预算。只有这样才能判断“某个节点更快”来自调度改进，还是来自偷偷给了更多预算。

### 重复运行与统计

- 每组多次运行；
- 保存 raw samples；
- 报告均值、标准差或合理区间；
- 报告 p50/p95；
- 固定 warm/cold 条件；
- 记录 Python、OS、CPU、SQLite、provider/model、commit、dirty state；
- provider failure 与 agent failure 分开统计。

### 成功指标

每个 coding task 至少报告：

- task success；
- visible acceptance；
- regression；
- security；
- DAG completion；
- scheduler wait；
- worker busy/utilization；
- max parallelism；
- retry/message count；
- aggregate tokens/cost/tool calls；
- wall time；
- failure taxonomy。

### Python 初学知识

- benchmark 测性能，test 测正确性；
- p95 是 95% 样本不超过的延迟；
- speedup 大于 1 表示并行更快；
- efficiency 衡量增加 Worker 后资源利用是否合理；
- 样本太少时不要给过度精确的结论。

### 完成标志

- Benchmark A/B 的 workload、基线、指标和门禁都明确；
- Ablation 与 architecture comparison 被区分；
- 没有编造 task 数或结果；
- Week6 BLOCKED 项被标出。

### 与下一步关系

Step 12 将这些选择、失败和证据状态落入工程文档。

---

## Step 12：DD、Failure Cases 与 Week5 报告

### 本步目标

让未来读者能够回答：为什么这样设计、哪里失败过、证据是什么、哪些没有验证。

### 计划中的文档

本轮不创建，后续实现完成后更新：

1. `docs/design_decisions/DD-W5-07.md`
2. `docs/design_decisions/DD-W5.md`
3. `docs/failure_cases/W5_FAILURES.md`
4. `docs/reports/W5_REPORT.md`
5. Day7 test log / experiment manifest

### `DD-W5-07` 建议主题

**Decision 1：TeamCodingRuntime 适配现有 CodingRuntime，不复制 Coding Loop**

备选：

- 复制一套 Team 专用 Agent Loop；
- 修改现有 CodingAgentRuntime 直接内嵌 Scheduler；
- 使用 Adapter 组合现有 Runtime。

建议选择第三项，因为职责清晰、回归面小、Single/Team 可走同一 EvalRunner。

**Decision 2：协调器单写 durable control state，Worker 线程只执行**

备选：Worker 直接并发写 Scheduler/SQLite。建议拒绝，因为会扩大 CAS 冲突和业务事务复杂度。

**Decision 3：有界 ThreadPoolExecutor 作为同步 Runtime 的 V1 backend**

备选：asyncio、process pool、Celery/Ray。当前选择线程池是最小兼容方案，不宣称适合所有生产部署。

**Decision 4：Week5 禁止多个真实 Worker 共享可写 Worktree**

这是安全门禁，不是性能优化。per-worker Worktree 与 patch merge 留 Week6。

**Decision 5：最终成功由外部 AgentGrader 判定**

DAG 和 Worker 文本都不具有自证成功的权威。

### Evidence 状态

文档创建初期应标 `PROPOSED`。只有：

- focused tests；
- full regression；
- deterministic benchmark；
- preliminary comparison；
- failure analysis

均有真实日志后，才能升级为 `ACCEPTED` 或项目现有对应状态。

### Failure Case 模板

```markdown
## Failure ID

- Date / commit / dirty state
- Scenario
- Expected invariant
- Actual behavior
- Blast radius
- Root cause
- Fix
- Regression test
- Remaining limitation
- Evidence command/result
```

### Day7 必须记录的 Failure Cases

- duplicate claim；
- stale attempt completion；
- stale worker generation callback；
- stale runtime callback after resume；
- ack-before-state lost result；
- complete-before-ack duplicate replay；
- retry budget reset；
- shared writable workspace rejected；
- persistence failure poison；
- interruption leaves active Future；
- DAG terminal but grader failed；
- provider/environment/protocol failure misclassification。

### Week5 报告不得夸大的内容

- scripted concurrency 不等于真实多 Agent coding；
- logical Worker recovery 不等于真实进程管理；
- fencing 不等于 external side-effect exactly-once；
- 11 个 dev tasks 不等于 held-out benchmark；
- preliminary Single/Team comparison 不等于统计显著结论。

### Python 初学知识

工程文档的核心不是“写了多少”，而是让 Decision、Evidence、Limitation 一一对应。没有执行的数据必须标 `NOT_RUN`，不能填估计值。

### 本步验证

- 文档中的类名与实际代码一致；
- 每个 DD 有至少一个备选方案；
- 每个 Failure Case 有复现测试；
- report 中命令与日志真实存在；
- Benchmark/Ablation 未运行时明确标 `NOT_RUN`。

### 完成标志

- 设计、失败、测试和实验形成可追溯链；
- 没有把未执行内容写成完成；
- Week6 接手者能明确看到阻塞项。

### 与下一步关系

Step 13 会进行机械验收，并决定是否具备进入 Week6 的资格。

---

## Step 13：机械验收与 Week6 Gate

### 本步目标

用固定命令和证据清单验收 Day7，而不是凭“模块看起来完整”判断。

### 推荐验收顺序

全部使用项目虚拟环境：

```bash
.venv/bin/python -m pytest tests/agent_team/test_worker_executor.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_runtime.py -q
.venv/bin/python -m pytest tests/agent_team/test_team_runtime_recovery.py -q
.venv/bin/python -m pytest tests/evaluation/test_team_runtime_integration.py -q
.venv/bin/python -m pytest tests/agent_team tests/session tests/evaluation -q
.venv/bin/python -m ruff check codeteam/agent_team tests/agent_team tests/evaluation
.venv/bin/python -m mypy codeteam/agent_team tests/agent_team
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/sandbox -q -rs
git diff --check
```

如果 Docker integration 因 daemon/image/权限 skip，只能记录为“该环境下未验证真实 Docker boundary”，不能把 skip 说成通过。

### 机械验收清单

#### Functional

- [ ] TeamCodingRuntime 满足现有 CodingRuntime Protocol
- [ ] WorkerExecutor 复用 CodingAgentRuntime，不存在第二套 loop
- [ ] linear/diamond/fan-out/fan-in/layered DAG 正确
- [ ] 1 Worker / 3 Worker 最终控制状态一致
- [ ] retry、exhaustion、BLOCKED 传播正确
- [ ] `TeamCodingRunResult` 与 `TeamRunArtifact` 聚合完整

#### Concurrency

- [ ] bounded executor
- [ ] no duplicate claim
- [ ] no busy polling
- [ ] coordinator is sole durable control-state writer
- [ ] max parallelism 有真实 overlap 证据
- [ ] interruption 使用 Event/Barrier 与有界等待验证

#### Durability and fencing

- [ ] runtime_id + generation + attempt 全部校验
- [ ] Mailbox claim/ack/release 顺序正确
- [ ] durable event revision 单调
- [ ] process crash 后新 runtime_id
- [ ] old result rejected
- [ ] two-resume writer ownership 正确
- [ ] persistence failure fail closed

#### Evaluation

- [ ] Single/Team 使用同一 AgentGrader
- [ ] DAG terminal 不等于 final success
- [ ] visible/regression/security/hidden acceptance 均保留
- [ ] aggregate budget 未膨胀
- [ ] failure taxonomy 可观察

#### Evidence

- [ ] DD-W5-07
- [ ] W5 failure cases
- [ ] test log
- [ ] benchmark manifest/raw samples
- [ ] Benchmark/Ablation 未运行项标 NOT_RUN
- [ ] Week5 report 明确 Week6 边界

### Week6 Gate

只有满足以下条件，才建议进入 per-worker Worktree 和 patch integration：

1. scripted Team control plane 全部通过；
2. stale attempt/generation/runtime 攻击均被拒绝；
3. process interruption 可恢复；
4. global budget 能跨 Worker/Retry 聚合；
5. real single-worker smoke 通过或有清晰外部阻塞；
6. 没有多个真实 Worker 共享可写 Worktree；
7. full regression 无新增失败；
8. DD 和 Failure Cases 已记录。

### 完成标志

Day7 功能完成与 Week5 实验完成要分开报告：

```text
Day7 functional acceptance:
  deterministic orchestration + durability + evaluation integration

Week5 experiment acceptance:
  benchmark/ablation actually run with manifests and raw samples

Week6 entry:
  functional gate passed and unsafe shared-write path remains disabled
```

---

## Design Decisions（计划）

### DD1：复用 `CodingRuntime`，不创建第二套 Coding Loop

`WorkerExecutor` 只做 assignment/claim 到 request/result 的适配。这样 Single 与 Team 共用执行语义，也能直接复用 `AgentEvalRunner`。

### DD2：`DurableTeamRuntime` 是控制面，`TeamCodingRuntime` 是编排面

前者拥有 Registry/Scheduler/Mailbox/Lifecycle 的 durable mutation；后者拥有执行顺序和 Future。两个对象不能互相复制状态。

### DD3：协调器单写 durable state

Worker 线程只调用 Coding Runtime 并返回结构化结果。所有 schedule/claim/start/complete/fail/message ack 由协调器提交，降低跨线程事务复杂度。

### DD4：同步 Runtime 使用 bounded ThreadPoolExecutor

V1 不引入分布式队列或 async 大改。并发上限是构造参数和安全配置，不接受无限提交。

### DD5：结果通过 durable Mailbox 进入状态迁移

状态提交成功后才 ack。重复投递通过 fencing 和幂等迁移安全处理。

### DD6：最终成功由外部 Grader 判定

Lead、Worker、Scheduler 和 Team Runtime 都不能自证代码正确。最终 success 必须使用现有 visible/regression/hidden/security gate。

### DD7：Week5 禁止真实多 Worker 共享可写 Worktree

多 Worker scripted concurrency 可以执行；真实编码 smoke 限制为一 Worker。per-worker Worktree 和 patch merge 是 Week6 前置能力。

### DD8：Team 详情使用独立 `TeamRunArtifact`

`CodingAgentRunResult` 只增加中性的 artifact reference。DAG、Worker、attempt、Mailbox、并发与调度指标写入 `team_run.json`，避免 Single Runtime 出现大量无意义的 Team 可选字段。

### DD9：Lead 权重建议，Runtime 掌握绝对预算

Lead 只能给 `1..5` 相对权重。Runtime 预留 20%，应用节点 min/max，维护全局 hard ledger；非法权重退回平均值，预算不可满足则 fail closed。

### DD10：三 Worker 静态注册，capability 硬门禁优先

V1 固定 GENERAL、BACKEND、TEST 三个本地 Worker。相同 role 优先，GENERAL 可兜底，但 required capabilities 必须始终是 Worker capabilities 的子集。assignment scope 还可以进一步禁止 patch。

### DD11：真实 LLM smoke 固定 B01 单节点

使用 deterministic single-node planner、一个 Worker 和现有 OpenAI-compatible 模型。该实验只证明 Team 执行链，不证明并行收益；真实命令由学习者手动执行。

---

## 实验公平性约束

1. 相同 task 和 pristine base SHA；
2. 相同 provider、model、reasoning effort；
3. 相同 context 构建方式；
4. 相同总 token/tool/cost/time budget；
5. 相同 visible/hidden grader；
6. 相同安全策略；
7. 每次使用干净、隔离的 Worktree；
8. Lead 和协调成本计入 Team 总成本；
9. retry 的失败 attempt 计入 usage；
10. 报告 wall time 与 aggregate worker time；
11. 固定 cold/warm 条件和运行顺序；
12. 保存 raw samples，不只保存平均值；
13. provider/environment/protocol/agent failure 分开统计；
14. correctness gate 未过的性能样本不得进入速度结论；
15. 不把 11 个 dev task 说成 held-out benchmark；
16. 保存每节点权重、allocated/actual/unused budget 和 Team reserve；
17. Single/Team 的 hard budget 相同，Team 不按 Worker 数放大；
18. 真实 API 命令只由学习者手动运行，自动测试使用 Fake/Scripted Runtime。

---

## Failure Taxonomy

| 分类 | 示例 | Team Runtime 应做什么 |
|---|---|---|
| Planning | Lead 输出非法 DAG | fail closed，不初始化错误 DAG |
| Scheduling | 无 ready、无 active，但仍有非终态节点 | no-progress failure，保留快照 |
| Worker availability | role 不匹配、Worker STOPPED | 不错误 claim，等待/失败按策略 |
| Worker runtime | Runtime 返回 FAILED 或抛异常 | 结构化 fail，遵守 attempt budget |
| Provider | 429、timeout、API auth | 沿用现有分类与 retry 语义，不盲目重试 auth |
| Environment | Docker/Git/file system 不可用 | 不降级到不安全 host path |
| Protocol | result 缺字段、错误 claim token | 拒绝结果，不推进任务 |
| Fencing | stale runtime/generation/attempt | 记录 rejected，不覆盖当前状态 |
| Durability | CAS conflict、SQLite commit failure | reload/reconcile 或 poison/fail closed |
| Verification | Worker 声称成功但测试失败 | grader 拒绝成功 |
| Regression | 新功能通过但旧测试失败 | grader 拒绝成功 |
| Security | 危险命令、越界路径、sandbox 缺失 | deny/fail closed |
| Interruption | SIGINT/process crash | 停止新 dispatch，依靠 Session/SQLite reconcile |

---

## Interview Answer

### 30 秒版本

Week5 Day7 把前六天的 Lead、DAG、Scheduler、Mailbox、Lifecycle 和 SQLite 持久化组合成 `TeamCodingRuntime`。它不重写 Agent Loop，而是通过 `WorkerExecutor` 调用现有 `CodingRuntime`。协调器用有界线程池执行独立节点，所有控制面状态由 `DurableTeamRuntime` 串行、带 fencing 地提交。DAG 完成只代表编排结束，最终代码成功仍由同一个 `AgentGrader` 的验收、回归和安全检查决定。

### 2 分钟版本

系统有两个容易混淆的 Runtime。`DurableTeamRuntime` 是 Day6 的持久化控制面，它负责 Registry、Scheduler、Mailbox、Lifecycle 和 SQLite CAS；Day7 的 `TeamCodingRuntime` 是执行编排层，负责 Lead planning、claim ready task、把任务交给 `WorkerExecutor`、等待 Future，并把结果通过 durable Mailbox 提交回 Scheduler。

因为现有 `CodingAgentRuntime` 已实现 `CodingRuntime.run()`，WorkerExecutor 只做结构化适配，不创建第二套 loop。并发使用 bounded `ThreadPoolExecutor`，Worker 线程不直接修改 Scheduler，协调器是 durable state 的单写者。每个结果都校验 `runtime_id + worker_generation + attempt`，所以旧进程、旧 Worker 或旧 attempt 的迟到结果无法污染新状态。

Week5 只在 scripted runtime 下验证多 Worker 并发；真实 LLM smoke 限制为一 Worker，因为 per-worker Worktree、patch merge 和冲突解决属于 Week6。最后，Team 的 DAG terminal 不等于任务成功，仍然交给现有 AgentGrader 检查 visible acceptance、regression、hidden checks、budget 和 security。

### 深挖版要点

面试官继续追问时，应展开：

- 为什么 complete 后、ack 前 crash 可以安全重放；
- 为什么 ack 后、complete 前会形成 lost-result window；
- 为什么 Future 不能持久化；
- `runtime_id/generation/attempt` 分别防哪类 ABA/迟到写；
- 为什么 coordinator single-writer 降低业务事务复杂度；
- 为什么 ThreadPoolExecutor 是当前同步 Protocol 的 V1 选择；
- 为什么 aggregate token/cost 必须求和而 latency 取 wall time；
- 为什么 Single vs Team 是架构对照，不是纯 ablation；
- 为什么 fencing 不能保证文件/网络 side effect exactly-once；
- 为什么 Week5 禁止共享可写 Worktree。

---

## Week5 完成标准

### 功能完成

- TeamCodingRuntime 与 WorkerExecutor 实现；
- DAG 全路径、retry、block、Mailbox、fencing、resume 工作；
- Team 可作为 `CodingRuntime` 接入 AgentEvalRunner；
- `TeamCodingRunResult`、`TeamRunArtifact`、Usage 和 Metrics 可审计；
- 三 Worker 静态池、capability 匹配和 GENERAL fallback 生效；
- Lead 权重预算受全局 hard ledger 与节点上下限约束。

### 测试完成

- deterministic DAG/concurrency/failure/recovery tests 全部通过；
- full regression 无新增失败；
- sandbox skip 如实记录；
- ruff/mypy 的新增错误清零，历史债单独列出。

### 证据完成

- DD-W5-07、Week5 汇总 DD；
- Day7/Week5 Failure Cases；
- 测试日志；
- benchmark/ablation manifest 和 raw samples；
- Week5 report 明确限制。

### 周末实验完成

- Benchmark A 确定性 1/3 Worker 已执行；
- Ablation A sequential/parallel 已执行；
- Benchmark B preliminary Single/Team 若获真实 API 授权则执行，否则明确 BLOCKED；
- 未实现 No-Mailbox adapter 时对应 ablation 标 `NOT_RUN`。

---

## Week6 进入条件

1. Team control plane 在 scripted 多 Worker 下可靠；
2. durable resume 与三层 fencing 有进程级证据；
3. shared writable workspace 路径保持关闭；
4. 单 Worker real smoke 证明现有 CodingRuntime 接入可行；
5. grader 接口和预算聚合稳定；
6. 开始设计 per-worker Worktree ownership；
7. 开始设计 patch artifact、integration order 和 conflict policy；
8. reviewer/quality gate 在 patch 合并前有明确位置。

---

## 当前明确未实现

截至本教程编写时，以下内容仍是计划，不是现有事实：

- `TeamCodingRuntime` 生产实现；
- `WorkerExecutor` 生产实现；
- Team 专属结果和指标模型；
- 通用 Runtime artifact reference 与独立 `team_run.json` 持久化；
- 三 Worker 静态注册和 capability/GENERAL 匹配策略；
- Lead 权重预算分配器与全局 hard ledger；
- TeamCodingRuntime 对 `CodingRuntime` 的正式适配；
- scripted 多 Worker 的 Day7 测试；
- real LLM Team smoke；
- Week5 Day7 benchmark/ablation 数据；
- per-worker Worktree；
- patch merge、冲突解决和 reviewer gate；
- 多 Worker 共享代码库的安全并行写入；
- 外部副作用 exactly-once；
- 分布式 Worker、跨机器调度和远程队列；
- 完整真实进程管理；
- 正式 held-out 多 Agent coding benchmark。

这些未实现项必须在后续日志中继续保持 `PLANNED`、`NOT_RUN` 或 `BLOCKED`，直到出现真实代码、测试和实验凭证。
