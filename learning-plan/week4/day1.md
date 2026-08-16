# 第 4 周 Day 1：Issue → Plan → Execution State

今天开始进入一个非常关键的阶段：**不再单独实现 Runtime Primitive，而是第一次定义“一个 Coding Task 从出生到结束，Agent Runtime 到底如何管理它”。**

你今天不是在做一个“Planner 小功能”，而是在给后面的：

```text
codeteam run "修复登录超时问题"
```

建立真正的生命周期骨架。

今天建议牢牢记住这条主线：

```text
Natural Language
      ↓
   TaskSpec
      ↓
Repository Inspection
      ↓
     Plan
      ↓
Execution State Machine
      ↓
后续 Day 2/3 才继续：
Patch → Verify → Repair → Complete
```

今天只做到：

```text
自然语言任务
→ 理解任务
→ 理解仓库
→ 生成计划
→ Runtime 知道“现在执行到哪一步”
```

就已经达标。

---

# 一、今天到底在解决什么问题

假设用户执行：

```bash
codeteam run "修复登录超时问题"
```

最简陋的 Agent 可以这么干：

```text
"修复登录超时问题"
        ↓
直接塞给 LLM
        ↓
LLM 搜代码
        ↓
LLM 改代码
```

问题是 Runtime 对任务几乎一无所知：

```text
这个任务叫什么？

真正目标是什么？

有哪些限制？

什么算完成？

Agent 现在是在分析还是修改？

已经完成哪些步骤？

计划是否仍然有效？

失败后回到哪里？

什么时候应该结束？
```

所以今天要完成一次非常重要的转换：

```text
用户的一句话
```

从“聊天 Prompt”升级成：

```text
Runtime 可以管理的 Task
```

也就是：

> **把一次模糊的自然语言请求，转化成结构化、可执行、可观察、可恢复的 Agent Task。**

---

# 二、工业界为什么越来越强调 Plan

OpenAI 当前 Codex 的公开最佳实践明确建议：对于复杂、模糊或者难以准确描述的任务，应先使用 Plan Mode，让 Agent 先收集上下文、必要时提出澄清问题，再形成计划后进入实现。官方还建议任务描述最好明确 Goal、Context、Constraints 和 Done when。

GitHub Copilot cloud agent 公开的完整工作流则非常直观：

```text
Research repository
       ↓
Create implementation plan
       ↓
Make code changes
       ↓
Review diff
       ↓
Iterate
```

GitHub 甚至允许只让 Agent 研究仓库和制定计划，暂时完全不修改代码。

Claude Code 的 Plan Mode 采取更强的隔离方式：Plan Mode 中 Agent 可以读取代码、研究问题并提出计划，但在用户批准之前不会进行文件修改。

所以三套系统虽然具体实现不同，但背后的工程思想非常一致：

```text
Understand
→ Plan
→ Act
```

而不是：

```text
Prompt
→ Edit immediately
```

---

# 三、Issue ≠ Prompt

这是今天第一个必须真正理解的概念。

## 1. Prompt 是什么

Prompt 是：

> **某一次给模型的输入。**

例如：

```text
修复登录超时问题
```

这是一个 Prompt。

之后 Agent 还可能产生：

```text
请分析 LoginService 和 HttpClient 的调用关系
```

这也是 Prompt。

再之后：

```text
根据下面的测试失败生成修复 Patch
```

还是 Prompt。

所以一个 Task 生命周期里：

```text
Task 1
├── Prompt 1
├── Prompt 2
├── Prompt 3
├── Prompt 4
└── Prompt ...
```

---

# 四、Issue / Task 是什么

Task 是：

> **Runtime 要完成的一次完整工作目标。**

例如：

```text
Task ID:
task-001

Original Request:
修复登录超时问题

Goal:
登录请求在指定超时场景下能够正确重试并返回结果

Repository:
xxx

Constraints:
不能修改公共 API
遵守项目代码规范

Acceptance:
目标测试通过
相关回归测试通过
```

所以：

```text
Prompt
=
给模型的一次输入


Task
=
需要被 Runtime 管理完整生命周期的一件工作
```

---

# 五、一个 Task 里为什么可能有很多 Prompt

例如真正执行“修复登录超时问题”：

```text
Task-001

Turn 1:
理解任务

Turn 2:
分析仓库

Turn 3:
生成 Plan

Turn 4:
读取目标代码

Turn 5:
生成 Patch

Turn 6:
分析 Test Failure

Turn 7:
生成第二个 Patch

Turn 8:
总结结果
```

如果 Runtime 只有：

```text
messages
```

它只知道发生了很多聊天。

如果 Runtime 有：

```text
Task
```

它知道：

```text
这些所有 Turn
共同服务于 task-001。
```

---

# 六、Task 和 Session 又是什么关系

这是第二个特别容易混淆的概念。

你现在可以暂时理解：

```text
Task
=
要完成什么


Session
=
这次 Agent 工作过程的持久化容器
```

例如：

```text
Session: ses-001

Task:
修复登录超时问题
```

Session 未来还会保存：

```text
Conversation
Plan
Worktree
Checkpoint
Model
Usage
Error
Current State
```

所以：

```text
Task
属于业务/执行语义


Session
属于 Runtime 生命周期/持久化语义
```

今天先定义 Task。

Session Persistence 是后面 Day 4 的重点。

---

# 七、工业系统里也能看到类似分层

Codex App Server 当前公开 API 中已经把持久化 Thread、Turn、Goal 和 Runtime Status 分开：Thread 可以开始、读取、恢复和 fork；同一个 Thread 可以持久化一个 Goal；运行时还有 `active`、`idle`、`systemError` 等状态。

这并不意味着你应该照抄 Codex 的数据结构，但它很好地说明：

> 一个 Coding Agent 产品最终不会只有 `messages[]`，而会逐渐拥有明确的持久化实体、目标和运行状态。

---

# 八、TaskSpec 是什么

你今天真正应该首先编码的，是：

```python
TaskSpec
```

它解决：

> **用户的自然语言任务，在进入 Runtime 后应该被表示成什么？**

我建议第一版至少：

```python
class TaskSpec(BaseModel):
    task_id: str

    original_request: str

    goal: str

    constraints: tuple[str, ...]

    acceptance_criteria: tuple[str, ...]
```

后面再逐步增加：

```text
repository_id
created_at
priority
task_type
```

今天不要过度设计。

---

# 九、为什么必须保存 `original_request`

例如 Runtime 最终解析得到：

```text
goal:
修复 LoginService timeout retry
```

但用户原话：

```text
修复登录超时问题
```

仍然必须保存。

原因是：

```text
TaskSpec
```

属于 Runtime 的解释。

而：

```text
original_request
```

才是用户真正说过的话。

以后如果发现：

```text
Runtime 理解错了
```

你需要能够比较：

```text
Original Request

vs

Normalized TaskSpec
```

这对 Failure Analysis 非常重要。

---

# 十、Goal 到底是什么

Goal 回答：

> **任务最终希望改变什么？**

例如：

```text
错误：

Goal:
修改 login.py
```

为什么错？

因为：

```text
修改 login.py
```

是实现方式。

真正 Goal 应该描述：

```text
用户希望看到的结果
```

例如：

```text
Goal:

登录请求在后端响应延迟的情况下，
能够按照项目定义的 timeout/retry 策略正确处理，
而不是提前失败。
```

---

# 十一、Goal ≠ Implementation

记住：

```text
Goal:
系统最终应该怎样

Implementation:
我们准备怎样修改代码
```

例如：

```text
Goal

用户点击登录后，
暂时性网络超时不应立即导致登录失败。
```

然后 Plan 才可能决定：

```text
Implementation

修改：
src/auth/client.py

增加：
retry handling
```

这样当 Agent 后来发现真正问题不在：

```text
client.py
```

而在：

```text
transport.py
```

Goal 仍然有效。

---

# 十二、OpenAI 对 Goal 的公开建议也很接近

Codex 当前最佳实践建议任务描述至少明确：

```text
Goal
Context
Constraints
Done when
```

目的就是减少假设，让 Agent 保持 Scope，并让最终结果更容易验证。

Codex App Server 当前甚至已经有持久化 `thread goal` API，可以给长运行 Thread 设置 Objective、状态和 Token Budget。

这说明 Goal 不是一个 Prompt 修辞技巧，而可以成为 Runtime 的正式状态。

---

# 十三、Constraint 是什么

Constraint 回答：

> **完成 Goal 的过程中不能违反什么？**

例如：

```text
Goal:

修复 timeout
```

Constraint：

```text
不能修改公开 API

不能添加新的第三方依赖

必须保持 Python 3.12 兼容

只能修改当前 Task Worktree

不能绕过安全执行链
```

Constraint 是：

```text
Solution Space Boundary
```

也就是限制 Agent：

```text
可以怎么解决
```

---

# 十四、为什么 Goal 和 Constraint 必须分开

例如：

```text
Goal:
提高接口性能

Constraint:
不能改变返回格式
```

如果没有 Constraint，

Agent 完全可能：

```text
删除部分返回字段
→ 性能提高
```

从：

```text
性能指标
```

看：

```text
Goal 达成
```

但实际：

```text
产品行为破坏
```

所以：

```text
Goal
告诉 Agent：
去哪


Constraint
告诉 Agent：
哪些路不能走
```

---

# 十五、Acceptance Criterion 是什么

它回答：

> **Runtime 怎么知道 Goal 已经完成？**

例如：

```text
Goal:
修复登录 timeout
```

一个非常差的 Acceptance：

```text
代码看起来正确
```

一个更好的：

```text
test_login_timeout_retry
必须通过
```

再例如：

```text
当第一次请求 timeout、
第二次请求成功时，
登录最终返回成功结果。
```

Acceptance Criterion 最好尽量：

```text
Observable
Verifiable
```

---

# 十六、Goal 与 Acceptance Criterion 的区别

可以这样记：

```text
Goal
=
我们想去哪里？


Acceptance
=
怎么证明已经到了？
```

例如：

```text
Goal:

登录 timeout 自动重试。


Acceptance:

pytest tests/auth/test_timeout.py
返回 0。
```

---

# 十七、OpenAI ExecPlan 为什么特别强调 Acceptance

OpenAI 公开的 ExecPlan 指南要求计划必须围绕可观察结果，并明确说明应该运行什么、观察到什么；验证不是可选项，而应包含测试或其他能证明行为生效的方式。

因此你后面设计：

```python
acceptance_criteria
```

不是为了把 TaskSpec 写漂亮。

它最终会进入：

```text
Verification Loop
```

---

# 十八、TaskSpec 第一版如何产生

这里我建议不要第一天就：

```text
用户一句话
↓
LLM 自动补全所有 Acceptance
↓
完全相信
```

因为：

```text
“修复登录超时问题”
```

本身可能没有告诉你：

```text
准确 timeout 时间
预期 retry 次数
现有测试
API constraint
```

第一版可以：

```text
Natural Language
       ↓
TaskNormalizer
       ↓
TaskSpec

original_request:
原样

goal:
LLM 归纳

constraints:
用户明确约束 + Repository Rules

acceptance:
用户明确标准 + Repo inspection 后得到的验证候选
```

要区分：

```text
User-provided facts

vs

Agent inferred facts
```

这很重要。

---

# 十九、今天甚至可以先不实现独立 `TaskNormalizer`

为了避免过度设计，Day 1 可以：

```text
Planner
```

负责：

```text
理解 User Task
+
根据 Repo Context 创建 TaskSpec/Plan
```

等后面逻辑复杂，再拆：

```text
TaskNormalizer
```

今天重点是概念正确，不是 Class 越多越好。

---

# 二十、Planning 到底是什么

Planning 是：

> **根据 Goal + Constraints + Repository Evidence，把工作拆成一组能够逐步执行和验证的步骤。**

输入：

```text
TaskSpec

+

Repository Context
```

输出：

```text
Plan
```

例如：

```text
Goal:
修复 login timeout


Repo Evidence:

src/auth/login_service.py
负责登录流程

src/http/client.py
处理 timeout

tests/auth/test_login.py
已有登录测试
```

然后：

```text
Plan

P1
确认 timeout 的调用链和配置来源

P2
复现当前 timeout failure

P3
修改 timeout/retry 逻辑

P4
运行 targeted test

P5
运行 auth regression
```

---

# 二十一、最重要：Plan 必须基于 Repository Evidence

错误：

```text
用户：
修复登录超时

LLM 凭经验：

P1 修改 LoginController
P2 修改 TimeoutConfig
P3 增加 RetryManager
```

结果仓库里：

```text
根本没有这些东西。
```

这是：

```text
Hallucinated Plan
```

正确：

```text
Task
↓
inspect repo
↓
retrieve files/symbols
↓
collect evidence
↓
Plan
```

也就是你今天规定的：

```text
run(task)
→ inspect repo
→ create plan
```

顺序绝对不能反。

---

# 二十二、GitHub Copilot 为什么把 Research 放在 Plan 前

GitHub 当前官方工作流明确写的是：

```text
Research
→ Plan
→ Iterate on code changes
```

Research 阶段专门用于理解仓库、寻找应该改哪里以及确认假设；然后才让 Copilot 提出 Plan。

这说明一个很重要的工程原则：

> **Planning quality 的上限取决于 Context quality。**

---

# 二十三、Claude Code 也体现了同样的思想

Claude Code Plan Mode 允许：

```text
read files
research
produce plan
```

但在批准之前：

```text
不修改磁盘
```

也就是说：

```text
Investigation
```

和：

```text
Mutation
```

在 Runtime 上可以显式分阶段。

这和你现在的：

```text
INSPECTING
→ PLANNING
→ IMPLEMENTING
```

状态设计非常契合。

---

# 二十四、Plan ≠ Chain of Thought

这是今天必须真正理解的第二个核心区别。

LLM 内部可能存在复杂推理，但你的 Runtime 不应该把“模型私有推理过程”作为产品状态。

你需要的是：

```text
Structured Plan
```

例如：

```text
P1:
检查 Timeout 配置来源

P2:
找到现有失败测试

P3:
修改 Retry Handling
```

不是：

```text
“我首先想到可能是 timeout 参数，
但也可能是 requests，
让我仔细想一下……”
```

前者是：

```text
Execution Contract
```

后者是：

```text
Reasoning Narrative
```

---

# 二十五、为什么工业计划通常强调“外显步骤”

OpenAI 当前 ExecPlan 指南把 Plan 描述成可供 Coding Agent 真正执行的规格，而且强调它是 living document：随着进展、发现和决策发生，应持续更新；甚至要求在 stopping point 更新 Progress 和 next steps。

OpenAI 针对 long-horizon Codex Task 的公开实践也把 Plan 拆为 milestone，并为 milestone 绑定 validation；如果 validation 失败，应先修复再继续，而不是机械推进计划。

这和“把模型思维链存起来”完全不是同一件事。

---

# 二十六、Plan 是 Structured Execution Contract

这句话今天最重要：

> **Plan 是 Task Goal 与 Runtime Execution 之间的契约。**

例如：

```text
TaskSpec

Goal:
修复 timeout


Plan

P1 inspect
P2 reproduce
P3 modify
P4 test
```

然后 Runtime 可以问：

```text
当前 Step 是什么？

是否完成？

是否失败？

下一步是什么？

是否需要 Replan？
```

如果 Plan 只是：

```text
一段 Markdown 作文
```

Runtime 很难可靠回答。

---

# 二十七、推荐的 `PlanStep`

今天第一版建议：

```python
class PlanStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
```

然后：

```python
class PlanStep(BaseModel):
    step_id: str

    title: str
    description: str

    status: PlanStepStatus = (
        PlanStepStatus.PENDING
    )

    relevant_files: tuple[str, ...] = ()

    verification: str | None = None
```

---

# 二十八、为什么需要 `step_id`

不要只靠：

```text
list index
```

例如：

```text
Step 1
Step 2
Step 3
```

Replan 后插入一步：

```text
Step 2.5
```

索引全部变化。

稳定 ID：

```text
plan-001-step-001
```

以后：

```text
Event Log
Session
Benchmark
Replan
```

都可以引用。

第一版简单：

```text
P1
P2
P3
```

也完全可以。

---

# 二十九、`title` 和 `description` 为什么都需要

例如：

```text
title:
Inspect timeout flow
```

适合：

```text
CLI 展示
```

详细：

```text
description:

Inspect LoginService and HTTP client to determine
where the timeout is configured and propagated.
```

适合：

```text
真正执行
```

不要让 CLI 输出 5 段长作文。

---

# 三十、`relevant_files` 为什么只是 Hint

Plan 创建时可能认为：

```text
relevant_files:
auth.py
client.py
```

但后续发现：

```text
transport.py
```

也重要。

所以：

```text
relevant_files
```

应该是：

```text
Current Evidence
```

不是：

```text
Hard Allowlist
```

否则 Plan 一旦漏文件，Agent 永远无法继续探索。

---

# 三十一、`verification` 特别重要

例如：

```text
P3
Implement timeout retry


verification:
pytest tests/auth/test_timeout.py
```

这样一个 Plan Step 不只是：

```text
做什么
```

还知道：

```text
怎样证明完成
```

OpenAI 的 long-horizon Codex 实践特别强调 milestone 要小到单次循环能够完成，并为每个 milestone 定义 acceptance/validation command。

---

# 三十二、Plan 本身建议有什么

```python
class Plan(BaseModel):
    plan_id: str
    task_id: str

    version: int

    steps: tuple[PlanStep, ...]

    created_at: datetime
```

以后可以再有：

```text
updated_at
reason_for_replan
```

---

# 三十三、为什么 Plan 需要 `version`

假设：

```text
Plan v1

P1 auth.py
P2 client.py
```

研究后发现：

```text
Plan 错了
```

生成：

```text
Plan v2

P1 transport.py
P2 auth regression
```

不要：

```text
直接覆盖旧 Plan
```

否则以后你不知道：

```text
Agent 为什么改方向？
```

第一版可以保存：

```text
version
```

后面 Session Event：

```text
plan.created
plan.replanned
```

---

# 三十四、Replanning 到底是什么

Replanning：

> **当新 Evidence 使当前 Plan 的核心假设失效时，重新生成后续执行步骤。**

不是：

```text
执行一个 Step 后
每次都重新规划整个任务
```

否则 Cost 很大，还容易振荡。

---

# 三十五、什么时候应该 Replan

推荐第一版只在明确事件触发：

```text
关键文件不存在

Plan 基于的假设被代码证伪

目标测试不存在

发现修改范围明显不同

Step 连续失败达到阈值

用户改变 Goal/Constraint
```

例如：

```text
Plan:
修改 auth/client.py
```

Inspection：

```text
auth/client.py
没有 timeout 逻辑
```

并发现：

```text
timeout
实际在 transport/http.py
```

这就是：

```text
PLAN_INVALIDATED
```

应该 Replan。

---

# 三十六、什么情况不需要 Replan

例如：

```text
计划：
修改 auth.py
```

Patch 第一次因为 Context Mismatch 失败。

这可能只是：

```text
Patch Failure
```

正确：

```text
重新读取文件
→ 重新生成 Patch
```

而不是：

```text
整个 Task Replan
```

所以以后要区分：

```text
Execution Failure

vs

Plan Failure
```

---

# 三十七、Plan 的最大工业价值之一：防止 Agent 漂移

长 Task 里模型非常容易：

```text
开始：
修 timeout

后来：
顺手 refactor HTTP layer

后来：
顺手改 logging

后来：
顺手升级 dependency
```

Plan 让 Runtime 可以持续问：

```text
这个 Tool Call
是否服务于当前 Plan Step？
```

并让用户看到：

```text
为什么 Agent 现在在做这件事？
```

所以 Plan 也是：

```text
Scope Control
```

的一部分。

---

# 三十八、OpenAI ExecPlan 如何处理长任务漂移

OpenAI 的公开 ExecPlan 方法明确强调 Plan 是 living document，并要求持续维护 Progress、记录决策、保持计划自包含；long-horizon 实践还要求保持 diff scoped，并在 validation 失败时先修复，不要继续扩展范围。

这实际上就是：

```text
Plan
+
Progress
+
Validation
+
Decision Log
```

共同抵抗长任务漂移。

---

# 三十九、State Machine 是什么

现在进入今天最重要的 Runtime 部分。

State Machine 可以理解成：

> **明确规定 Task 当前处于哪个阶段，以及哪些状态可以合法地跳到哪些状态。**

没有 State Machine：

```python
task.status = "whatever"
```

任何地方都可以随意：

```text
created
→ completed

failed
→ planning

completed
→ running
```

系统行为很快失控。

---

# 四十、推荐第一版 `TaskStatus`

今天先不要把 Day 2/3 全做完，但状态最好提前留好：

```python
class TaskStatus(str, Enum):
    CREATED = "created"

    INSPECTING = "inspecting"

    PLANNING = "planning"

    READY = "ready"

    RUNNING = "running"

    PAUSED = "paused"

    COMPLETED = "completed"

    FAILED = "failed"
```

你也可以使用：

```text
IMPLEMENTING
VERIFYING
REPLANNING
```

更细的状态。

但 Day 1 不要陷入状态数量争论。

---

# 四十一、我更推荐 Day 1 用稍细一点的版本

因为后面你确实需要 Verification：

```python
class TaskStatus(str, Enum):
    CREATED = "created"

    INSPECTING = "inspecting"

    PLANNING = "planning"

    READY = "ready"

    IMPLEMENTING = "implementing"

    VERIFYING = "verifying"

    PAUSED = "paused"

    COMPLETED = "completed"

    FAILED = "failed"
```

以后需要：

```text
FAILURE_ANALYSIS
```

再增加。

---

# 四十二、今天实际只走前半段

第一版：

```text
CREATED
   ↓
INSPECTING
   ↓
PLANNING
   ↓
READY
```

今天：

```text
READY
```

就是终点。

也就是说：

```bash
codeteam run "task"
```

今天暂时可以输出：

```text
Task: task-001

✓ Repository inspected
✓ Plan created

Plan:
1. ...
2. ...
3. ...

Status:
READY
```

暂时：

```text
不修改代码
```

非常合理。

---

# 四十三、为什么我建议加 `READY`

如果没有：

```text
READY
```

可能变成：

```text
PLANNING
↓
IMPLEMENTING
```

但 Day 1 的 Planner 和后面的 Executor 就粘得太紧。

有：

```text
READY
```

意味着：

```text
Plan 已经生成
Runtime 已经准备执行
但还没有 Side Effect
```

这个状态以后特别适合：

```text
Human Plan Review
```

---

# 四十四、State Transition 必须集中管理

不要项目里到处：

```python
task.status = TaskStatus.COMPLETED
```

更合理：

```python
task.transition_to(
    TaskStatus.PLANNING
)
```

内部：

```text
检查：
当前状态能不能 → 目标状态
```

---

# 四十五、第一版 Transition Table

例如：

```text
CREATED
→ INSPECTING
→ FAILED


INSPECTING
→ PLANNING
→ FAILED


PLANNING
→ READY
→ FAILED


READY
→ IMPLEMENTING
→ PAUSED
→ FAILED


IMPLEMENTING
→ VERIFYING
→ PAUSED
→ FAILED


VERIFYING
→ COMPLETED
→ IMPLEMENTING
→ FAILED


PAUSED
→ READY / IMPLEMENTING


COMPLETED
→ 无


FAILED
→ 无
```

后面 Resume 时再完善 PAUSED。

---

# 四十六、什么叫 Terminal State

Terminal State：

> **Task 生命周期正常情况下不再继续向其他执行状态转换的状态。**

第一版：

```text
COMPLETED
FAILED
```

都是 Terminal。

也就是：

```python
status.is_terminal
```

应该：

```text
True
```

---

# 四十七、为什么 `FAILED` 是 Terminal

这里你可能会问：

```text
失败以后不能 Retry 吗？
```

当然可以。

但更好的设计通常是：

```text
在真正进入 FAILED 前
Runtime 已经完成可用 Retry / Recovery
```

比如：

```text
VERIFYING
→ repair
→ IMPLEMENTING

VERIFYING
→ replan
→ PLANNING

达到 budget
→ FAILED
```

所以：

```text
FAILED
```

代表：

```text
本 Task Runtime 决定不再自动继续。
```

不是：

```text
任何一次 Tool Failure。
```

---

# 四十八、这就是为什么 Tool Failure ≠ Task Failure

例如：

```text
pytest
exit 1
```

不应该：

```text
TaskStatus = FAILED
```

因为：

```text
Agent
可能需要修代码
```

应该：

```text
VERIFYING
↓
test failure
↓
后续 Day 2:
repair
↓
IMPLEMENTING
```

Task 的 Terminal Failure 应该发生在：

```text
Retry exhausted

Unrecoverable error

Security hard failure

User cancellation with terminate semantics
```

等更高层情况。

---

# 四十九、Codex 的工业状态模型给我们的启发

Codex App Server 当前明确区分了 Thread Runtime Status，并通过 `thread/status/changed` 通知状态变化；Turn 结束则产生明确的 `turn/completed` 事件。

这并不是你的 Task State Machine 模板，但说明工业 Agent Runtime 通常不会靠：

```text
“最后一条聊天消息是什么”
```

来判断当前状态，而是有独立 Runtime Status。

---

# 五十、`Planner` 的职责边界

建议：

```text
Planner
```

只负责：

```text
TaskSpec
+
RepoContext
↓
Plan
```

它不应该负责：

```text
apply patch

run tests

change worktree

create checkpoint
```

Planner 是：

```text
Decision / Planning Component
```

不是：

```text
Execution Engine
```

---

# 五十一、Planner 输入建议

第一版：

```python
planner.create_plan(
    task=task_spec,
    repo_context=context,
)
```

其中：

```text
repo_context
```

最好包含：

```text
Repository summary

Relevant files

Relevant symbols

Instructions

Test commands
```

而不要：

```text
整个 Repository
```

重新塞进 LLM。

---

# 五十二、Planner 输出必须结构化

你已经在 Week 1 做过 Structured Output 思路。

这里尽量让模型输出：

```text
Plan Schema
```

而不是：

```text
Markdown
↓
Runtime 再用正则解析
```

因为你后面需要：

```text
PlanStepStatus

Step ID

Verification

Replan
```

都依赖结构化数据。

---

# 五十三、Planning Prompt 应该强调什么

你后面写 Planner Prompt 时，核心要求是：

```text
1.
只基于提供的 Repository Evidence

2.
不要假设不存在的文件或 Symbol

3.
步骤应该可执行

4.
步骤大小适中

5.
需要包含验证

6.
不要开始写代码

7.
不确定事实明确标记

8.
Plan 服务 Task Goal 和 Constraints
```

而不是：

```text
“请仔细思考并写一个优秀的计划。”
```

---

# 五十四、一个好的 Plan Step 应该多大

错误极端 A：

```text
P1
实现整个功能
```

太大。

错误极端 B：

```text
P1
打开文件

P2
读第一行

P3
找到函数

P4
看参数
```

太碎。

比较合理：

```text
P1
Trace timeout configuration from LoginService
through the HTTP client and identify the
actual failure point.
```

这个 Step：

```text
有明确目标
可以在一次 Agent Loop 内完成
执行结果可以总结
```

---

# 五十五、OpenAI long-horizon 实践给了非常好的尺度

OpenAI 当前公开的 long-horizon Codex 实践建议把 Milestone 拆到“足够小，可以在一次 loop 中完成和验证”，并为每个 Milestone 明确 Validation。

这就是你 Plan Step 大小非常好的参考标准：

> **一个 Step ≈ 一次有明确产物和验证方式的工作单元。**

---

# 五十六、`SingleAgentOrchestrator` 到底负责什么

这是今天另一个非常关键的 Class。

Planner：

```text
负责制定 Plan
```

而：

```text
SingleAgentOrchestrator
```

负责：

> **推动 Task 从一个状态进入另一个状态。**

第一版：

```text
run(task)
   │
   ▼
create TaskSpec
   │
   ▼
status=INSPECTING
   │
   ▼
Context Engine
   │
   ▼
status=PLANNING
   │
   ▼
Planner
   │
   ▼
validate Plan
   │
   ▼
status=READY
   │
   ▼
return result
```

---

# 五十七、Orchestrator 不应该做底层实现

错误：

```python
class SingleAgentOrchestrator:

    def run(...):
        os.walk(...)
        subprocess.run(...)
        git ...
        call_openai(...)
```

正确：

```text
Orchestrator
协调：

ContextEngine
Planner
State
EventLog
```

而不是自己成为：

```text
God Object
```

---

# 五十八、今天第一版 `run()` 最好停在哪

建议明确：

```text
run()
→ inspect repo
→ create plan
→ status READY
→ return
```

不进入：

```text
Patch
Command
Verification
```

原因是你今天需要先把：

```text
Task Lifecycle
```

搭稳定。

如果同时接：

```text
AgentLoop
Patch
Test
```

一旦出问题你根本不知道：

```text
Task State 错？
Planner 错？
AgentLoop 错？
Patch 错？
```

---

# 五十九、今天完整数据流

建议画在你的设计笔记里：

```text
User

"修复登录超时问题"

        │
        ▼

SingleAgentOrchestrator

        │
        ▼

TaskSpec

goal
constraints
acceptance

        │
        ▼

TaskStatus
CREATED
        │
        ▼
INSPECTING

        │
        ▼

Week2 Context Engine

Repo Map
Symbols
Relevant Files
Instructions

        │
        ▼

PLANNING

        │
        ▼

Planner / ModelClient

        │
        ▼

Structured Plan

P1
P2
P3
P4

        │
        ▼

Plan Validation

        │
        ▼

READY
```

---

# 六十、Plan Validation 不能省

Planner 是模型驱动的。

模型可能返回：

```text
steps=[]
```

或者：

```text
Step ID 重复
```

甚至：

```text
所有 Step 都是 SKIPPED
```

所以 Runtime 必须验证：

```text
至少一个 Step

Step ID 唯一

初始状态合法

不能一开始 COMPLETED

每一步非空

Task ID 匹配
```

不能：

```text
模型返回什么
Runtime 就接受什么。
```

---

# 六十一、今天要求的测试怎么理解

你列的测试全部有明确目的。

## Test 1：普通自然语言任务

输入：

```text
修复登录超时问题
```

验证：

```text
TaskSpec 创建成功

Plan 创建成功

TaskStatus == READY
```

---

# 六十二、Test 2：空 Task

例如：

```text
""
```

或者：

```text
"    "
```

应该：

```text
在进入 LLM 前失败
```

不要浪费：

```text
Token
Latency
```

然后让模型回答：

```text
“请提供任务。”
```

---

# 六十三、Test 3：Plan 至少一个 Step

这是 Runtime Invariant：

```text
len(plan.steps) >= 1
```

如果 Planner：

```text
[]
```

返回：

```text
PLAN_INVALID
```

不能：

```text
status = READY
```

---

# 六十四、Test 4：Step 状态转换

例如：

```text
PENDING
→ RUNNING
→ COMPLETED
```

必须成功。

---

# 六十五、Test 5：无效状态转换

例如：

```text
PENDING
→ COMPLETED
```

你可以选择允许还是禁止。

我建议禁止直接：

```text
PENDING
→ COMPLETED
```

至少第一版保持：

```text
PENDING
→ RUNNING
→ COMPLETED
```

更方便 Audit。

再例如：

```text
COMPLETED
→ RUNNING
```

一定非法。

---

# 六十六、Test 6：Plan 完成

假设：

```text
P1 COMPLETED
P2 COMPLETED
P3 COMPLETED
```

则：

```text
plan.is_complete()
```

应该：

```text
True
```

---

# 六十七、Test 7：Plan 失败

例如：

```text
P1 COMPLETED
P2 FAILED
P3 PENDING
```

Plan：

```text
不能被认为 complete
```

至于：

```text
是否整体 FAILED
```

取决于以后是否允许 Replan。

第一版可以：

```text
plan.has_failed_step()
=
True
```

---

# 六十八、Test 8：Replan

初始：

```text
Plan v1

P1
P2
P3
```

Replan：

```text
Plan v2
```

至少检查：

```text
version == 2

task_id unchanged

old plan not mutated

new steps valid
```

---

# 六十九、我建议额外增加 5 个测试

### T9：重复 Step ID

必须拒绝。

### T10：TaskStatus 非法跳转

例如：

```text
CREATED → COMPLETED
```

拒绝。

### T11：Terminal State 不能继续

```text
COMPLETED → PLANNING
```

拒绝。

### T12：Planner 返回不存在文件

不要立刻 DENY 整个 Plan，

但至少：

```text
标记 unverified reference
```

或 Validation Warning。

### T13：Planner Exception

应该：

```text
TaskStatus = FAILED
```

或产生明确 Planner Failure，

不能停在：

```text
PLANNING
```

永久卡死。

---

# 七十、Plan 是否应该允许 COMPLETED → Replan？

一般不建议。

如果 Task：

```text
COMPLETED
```

之后用户：

```text
“再修改一下”
```

这更接近：

```text
新的 Turn / 新 Task continuation
```

而不是：

```text
偷偷把 Terminal Task 改回 PLANNING
```

这关系到后面 Session 模型。

第一版保持：

```text
Terminal
=
immutable terminal
```

最清晰。

---

# 七十一、Design Decision：Free-form Plan vs Structured Plan

这是今天必须正式记录的 Design Decision。

## 方案 A：Free-form Plan

例如：

```text
首先我会查看登录相关代码，
然后检查 timeout，
接着修改...
```

### 优点

```text
模型容易生成

人类阅读自然

Prompt 简单
```

### 缺点

```text
Runtime 无法可靠知道：

有几步？
当前哪一步？
哪一步失败？
怎么恢复？
怎么 Replan？
怎么计算 Step Completion？
```

---

# 七十二、方案 B：Structured Plan

例如：

```text
Plan

P1
status=PENDING
title=Trace timeout flow

P2
status=PENDING
title=Reproduce failure

P3
status=PENDING
title=Implement fix
```

### 优点

```text
状态可追踪

可以恢复

可以 Event Log

可以 Replan

可以 CLI 展示

可以 Evaluation

可以 Persist
```

### 缺点

```text
Schema 更复杂

模型输出需要验证

可能限制模型表达
```

---

# 七十三、今天推荐的 Decision

```text
Decision:

Structured Plan is Runtime source of truth.
```

同时：

```text
Human-readable explanation
```

可以作为字段或 UI 输出。

也就是说：

```text
Structure
用于机器


Natural Language
用于人
```

不是二选一。

---

# 七十四、这个 Decision 与工业实现有什么对应

Claude Code 当前提供可显示 pending / in-progress / complete 的 Task List，并指出这些 Task 可以在较长工作中用于追踪多步骤进展。

OpenAI 的 ExecPlan 则要求 Progress、Milestone、Validation 和 Decision 持续更新，把 Plan 明确当作“living document”。

它们具体数据结构未必与你相同，但都说明：

> **长任务 Plan 最终需要成为可管理状态，而不是一次性散文。**

---

# 七十五、Benchmark：今天应该怎么设计

准备 10 个不同 Task Prompt。

不要都：

```text
修复 xxx bug
```

建议：

```text
T01
修复登录 timeout

T02
给 CLI 增加 --verbose

T03
修复一个 failing unit test

T04
给 UserService 增加参数校验

T05
重构重复 parser logic

T06
新增配置项

T07
修改异常处理行为

T08
补一个 regression test

T09
修复 type check

T10
修改两个模块之间的接口
```

---

# 七十六、Benchmark 流程

每个 Task：

```text
Repository Inspection
↓
Planner
↓
Plan
```

记录：

```text
Planning Latency

Plan Step Count

Input Tokens

Output Tokens
```

---

# 七十七、Planning Latency

定义：

```text
开始 Planner Model Call
→
成功解析 Valid Plan
```

不要把：

```text
Repository Scan
```

也算进去。

否则你测到的是：

```text
Planning Pipeline
```

不是：

```text
Planner latency
```

最好两个指标都保存：

```text
repo_inspection_ms

planner_ms

total_planning_pipeline_ms
```

---

# 七十八、Plan Step Count 为什么值得测

因为你以后会发现两种问题：

```text
平均：
2 steps
```

可能：

```text
计划过粗
```

如果：

```text
平均：
25 steps
```

可能：

```text
过度规划
```

所以 Step Count 虽不是“越低越好”，但能观察 Planner 行为。

---

# 七十九、Token Usage

记录：

```text
planner_input_tokens

planner_output_tokens

planner_total_tokens
```

以后 Ablation：

```text
Plan-first
```

一定会比：

```text
Direct-edit
```

多一部分 Planning Token。

最终要回答：

> **这些额外 Planning Cost 是否换来了更高 Task Success？**

---

# 八十、Day 1 Benchmark 不应该得出什么结论

今天不要说：

```text
Plan-first 更好。
```

因为你只测了：

```text
Planning Latency
Step Count
Token
```

还没有测：

```text
Task Success
```

所以今天只能得到：

```text
Planning Cost
```

不能得到：

```text
Planning Value
```

非常重要。

---

# 八十一、真正证明 Plan 价值要靠 Week 4 最终 Ablation

后面在相同 Task 上：

```text
Group A
Plan-first


Group B
Direct-edit
```

比较：

```text
Task Success Rate

Tool Calls

Tokens

Duration

Repair Attempts

Wrong-file edits
```

这才能回答：

```text
Planning
到底是否有价值？
```

---

# 八十二、Ablation 需要控制变量

同一个：

```text
Repository version

Task prompt

Model

Temperature / reasoning config

Tool set

Budget
```

只改变：

```text
Planning enabled
```

否则：

```text
Provider A + Plan
```

和：

```text
Provider B + No Plan
```

比较没有意义。

---

# 八十三、Failure Case 1：Plan 与 Repository 事实不一致

例如：

```text
Plan:

修改 LoginController
```

但是：

```text
仓库根本不存在 LoginController。
```

Root Cause 可能：

```text
Context Retrieval 不足

Planner 幻觉

旧 RepoMap

Prompt 暗示错误架构
```

---

# 八十四、解决思路

不要只：

```text
让 Prompt 更严格
```

Runtime 还应该进行：

```text
Plan Grounding Validation
```

例如：

```text
Plan relevant_files
↓
检查文件是否真实存在

Symbol reference
↓
SymbolIndex 验证
```

最后：

```text
Verified

Unverified

Invalid
```

---

# 八十五、Failure Case 2：Plan 过度细碎

例如：

```text
P1 read file
P2 find class
P3 read function
P4 inspect parameter
P5 inspect caller
...
```

问题：

```text
Runtime overhead

Plan maintenance cost

Token cost

频繁状态切换
```

Root Cause：

```text
Planner 把 Tool Call
误当成 Plan Step
```

---

# 八十六、Plan Step 应该是工作单元，不是 Tool Call

正确关系：

```text
PlanStep

Trace timeout flow
        │
        ├── rg
        ├── read_file
        ├── symbols
        └── read_file
```

也就是：

```text
一个 Plan Step
内部可以包含多个 Agent Tool Calls
```

不要：

```text
PlanStep == ToolCall
```

---

# 八十七、Failure Case 3：Plan 一步过大

例如：

```text
P1
实现登录模块完整修复并运行所有测试
```

问题：

```text
失败以后不知道哪里失败

Checkpoint 粒度太粗

无法衡量 Progress

难 Replan
```

解决：

```text
拆成：
investigate
reproduce
modify
verify
```

但也别拆成 30 步。

---

# 八十八、Failure Case 4：Plan 已失效仍继续执行

这是最危险的一个。

例如：

```text
P1 假设 timeout 在 auth.py
```

检查发现：

```text
实际在 network.py
```

但 Agent：

```text
继续 P2 修改 auth.py
```

这叫：

```text
Stale Plan Execution
```

---

# 八十九、怎么防止 Stale Plan

建议未来每个 Step 结束时判断：

```text
Did this step invalidate
any plan assumption?
```

如果：

```text
YES
```

就：

```text
REPLAN
```

而不是：

```text
next step
```

---

# 九十、推荐 Replan 数据模型

不一定今天实现完整，但可以预留：

```python
class ReplanReason(str, Enum):
    NEW_EVIDENCE = "new_evidence"

    INVALID_ASSUMPTION = (
        "invalid_assumption"
    )

    STEP_FAILED = "step_failed"

    USER_CHANGED_SCOPE = (
        "user_changed_scope"
    )
```

然后：

```text
Plan v1
↓
replan reason
↓
Plan v2
```

---

# 九十一、Failure Case 5：Plan Oscillation

例如：

```text
Plan v1:
改 auth.py

Plan v2:
改 client.py

Plan v3:
改 auth.py

Plan v4:
改 client.py
```

这叫：

```text
Planning Oscillation
```

以后应该：

```text
记录 Decision / Failed Attempt
```

避免模型反复走已经失败的路线。

OpenAI long-horizon 实践同样建议维护 Decision Notes，目的之一就是避免任务在长时间执行中来回摇摆。

---

# 九十二、今天的 Event Log 应该出现什么

如果你现有 Event 系统已经存在，建议 Day 1 开始产生：

```text
task.created

task.status_changed

repository.inspection_started

repository.inspection_completed

plan.started

plan.created

plan.validation_failed

plan.replanned

plan.step_started

plan.step_completed

task.ready

task.failed
```

今天不用全部使用，

但 Event Schema 要开始朝：

```text
Task Runtime Trace
```

发展。

---

# 九十三、Status Change Event 最好记录

```text
task_id

from_status

to_status

timestamp

reason
```

例如：

```text
task-001

PLANNING
→
READY

reason:
valid_plan_created
```

以后 Debug：

```text
为什么 Task 没有执行？
```

可以直接查看 Timeline。

---

# 九十四、Planner Metrics 也应该进入 Event

例如：

```text
plan.created

plan_id
task_id
version

step_count

input_tokens
output_tokens

latency_ms
```

这让 Day 7 Evaluation 不需要重新从日志文本里 Regex。

---

# 九十五、今天建议的代码结构

不要为了今天创建太多目录。

可以先：

```text
codeteam/
├── task/
│   ├── models.py
│   └── state.py
│
├── planning/
│   └── planner.py
│
└── agent/
    └── orchestrator.py
```

如果项目目前已有：

```text
state.py
```

也可以复用。

关键是职责：

```text
Task models
→ Task 生命周期数据

Planner
→ TaskSpec + Context → Plan

Orchestrator
→ 推动状态
```

---

# 九十六、我建议你今天分成 7 个实现 Step

## Step 1：先只实现枚举和状态规则

实现：

```text
TaskStatus
PlanStepStatus
```

以及：

```text
legal transitions
```

今天最适合从这里开始。

---

## Step 2：`TaskSpec`

实现：

```text
original_request
goal
constraints
acceptance
```

先不用 LLM。

手动构造测试。

---

## Step 3：`PlanStep` + `Plan`

实现：

```text
plan validation

step transitions

is_complete

has_failure
```

---

## Step 4：Planner Interface

先定义：

```text
Planner
```

接口。

然后：

```text
MockPlanner
```

先接通测试。

不要一上来依赖真实 Provider。

---

## Step 5：Repository Context → Planner

接入已有 Context Engine：

```text
Task
↓
context query
↓
Repo context
↓
Planner
```

---

## Step 6：SingleAgentOrchestrator

完成：

```text
CREATED
→ INSPECTING
→ PLANNING
→ READY
```

---

## Step 7：真实 Planner + Benchmark

最后才：

```text
10 Task prompts
```

跑真实模型。

记录：

```text
latency
steps
tokens
```

---

# 九十七、为什么 MockPlanner 应该先做

如果真实 Planner 一开始就参与：

```text
测试会：

慢
贵
不确定
依赖网络
```

而今天主要测试：

```text
Task State Machine

Plan Validation

Orchestration
```

这些都应该 deterministic。

所以：

```text
Unit / Integration
→ MockPlanner

Benchmark
→ Real Planner
```

这个职责划分很重要。

---

# 九十八、MockPlanner 不是“过度 Mock”

你不是 Mock：

```text
Task State
Plan Validation
Orchestrator
```

这些真正被测逻辑。

只是把：

```text
External nondeterministic Model
```

替换掉。

例如：

```python
MockPlanner(
    result=Plan(
        ...
    )
)
```

然后测试：

```text
Orchestrator
是否正确进入 READY
```

非常合理。

---

# 九十九、今日 Design Decision 建议正式记录

可以写成：

```text
DD-W4-D1-01

Title:
Structured Execution Plan

Problem:
How should CodeTeam represent
multi-step coding work?

Alternatives:
1. Free-form natural-language plan
2. Structured Plan / PlanStep

Decision:
Use structured Plan as Runtime state,
while preserving natural-language
description for human readability.

Reasons:
- explicit progress tracking
- persistence
- replanning
- validation
- evaluation
- observability

Trade-offs:
- schema complexity
- validation overhead
- model output constraints

Evidence status:
PROPOSED
```

注意：

```text
Evidence status:
PROPOSED
```

现在还不能：

```text
SUPPORTED
```

因为 Ablation 还没跑。

---

# 一百、Day 1 Benchmark 建议结果表

真正跑完后：

| Task | Planner ms | Steps | Input Tokens | Output Tokens |
|---|---:|---:|---:|---:|
| T01 | | | | |
| T02 | | | | |
| ... | | | | |
| T10 | | | | |

汇总：

```text
Planning Latency
P50
P95

Plan Step Count
Median
Min
Max

Token
Median Input
Median Output
```

不要现在提前填写数据。

---

# 一百零一、建议额外记录 Plan Grounding

虽然原任务没有要求，但非常值得增加：

```text
Referenced files

Existing files

Non-existing files
```

得到：

```text
File Reference Validity
```

例如：

```text
Planner 提到 12 个文件
11 个真实存在
```

这只是一个探索性指标。

未来可以发展为：

```text
Plan Grounding Quality
```

---

# 一百零二、为什么这个指标有价值

因为：

```text
Planning latency
```

快不代表好。

```text
step count
```

适中也不代表好。

一个 Plan：

```text
5 steps
100ms
```

但是：

```text
全部基于不存在的文件
```

毫无价值。

所以以后真正评价 Planner，至少要逐渐考虑：

```text
Grounding
Completeness
Executability
```

Day 1 暂时不用复杂评分模型。

---

# 一百零三、今天最终不要完成什么

为了避免 Day 1 膨胀，明确**今天不做**：

```text
自动 Patch

自动测试

Repair Loop

错误分类完整系统

Session Persistence

Context Compaction

Model Switch

完整 CLI
```

这些属于后续几天。

---

# 一百零四、今天真正完成应该是什么

用户：

```bash
codeteam run "修复登录超时问题"
```

第一版甚至可以只输出：

```text
Task
────────────────────────

ID:
task-001

Goal:
修复登录请求的 timeout 行为。

Constraints:
- follow repository instructions
- keep changes scoped

Status:
READY


Repository inspection
────────────────────────

Relevant files:
- src/auth/login_service.py
- src/http/client.py
- tests/auth/test_login.py


Plan
────────────────────────

P1
Inspect timeout configuration and call flow

P2
Identify/reproduce the failing scenario

P3
Modify timeout/retry behavior

P4
Run targeted verification

P5
Run related regression
```

然后：

```text
不执行 P1
```

今天已经合格。

---

# 一百零五、今天最终验收 Checklist

### Theory

```text
[ ] Task vs Session

[ ] Issue vs Prompt

[ ] Goal

[ ] Constraint

[ ] Acceptance Criterion

[ ] Planning

[ ] Plan Step

[ ] State Machine

[ ] Replanning

[ ] Terminal State

[ ] Plan ≠ Chain of Thought

[ ] Plan = Structured Execution Contract
```

### Implementation

```text
[ ] TaskSpec

[ ] TaskStatus

[ ] PlanStepStatus

[ ] PlanStep

[ ] Plan

[ ] Planner

[ ] SingleAgentOrchestrator
```

### Pipeline

```text
[ ] Natural Language

→ TaskSpec

→ Repository Inspection

→ Structured Plan

→ READY
```

### Tests

```text
[ ] 普通任务

[ ] 空任务

[ ] Plan 至少一个 Step

[ ] Valid Step Transition

[ ] Invalid Step Transition

[ ] Plan Complete

[ ] Plan Failure

[ ] Replan

[ ] Invalid Task Transition

[ ] Terminal State
```

### Evaluation

```text
[ ] 10 Task Prompts

[ ] Planning Latency

[ ] Step Count

[ ] Token Usage
```

### Evidence

```text
[ ] Design Decision

[ ] Benchmark raw results

[ ] Failure Cases

[ ] Ablation specification
```

---

# 一百零六、今天最终必须自己回答出的面试问题

### Task

1. Issue、Prompt、Task 有什么区别？
2. Task 和 Session 有什么区别？
3. 为什么不能直接把自然语言 Prompt 当 Runtime State？
4. TaskSpec 为什么需要保存 original request？

### Goal

5. Goal 和 Implementation 有什么区别？
6. Constraint 的作用是什么？
7. Goal 和 Acceptance Criterion 有什么区别？
8. 怎么判断 Acceptance Criterion 是否合理？

### Plan

9. 为什么复杂 Coding Task 需要 Plan？
10. Plan 为什么不能建立在模型猜测上？
11. 为什么 Repository Inspection 必须发生在 Plan 前？
12. Plan 与 Chain-of-Thought 有什么区别？
13. 为什么 Plan 应该结构化？
14. Plan Step 应该多大？
15. Plan Step 和 Tool Call 有什么区别？

### State

16. 为什么 Coding Agent 需要 State Machine？
17. Tool Failure 为什么不等于 Task Failed？
18. Terminal State 是什么？
19. 为什么 Completed 不应该随便回到 Running？
20. 什么情况下应该 Replan？

### Evaluation

21. 怎么证明 Planning 真正有价值？
22. Planning Latency 能证明 Planning 质量吗？
23. 为什么需要 Plan-first vs Direct-edit Ablation？
24. 怎样判断 Plan 是否基于真实 Repo Evidence？
25. 如何识别 Plan Over-fragmentation？

---

# 一百零七、如果面试官问：“不就是让 LLM 先列个 TODO 吗？”

你最终应该能回答：

> 我没有把 Plan 当成一段给人看的 TODO 文本，而是把它作为 Agent Runtime 的显式执行状态。自然语言请求首先规范化成带 Goal、Constraints 和 Acceptance Criteria 的 TaskSpec；Planner 只能基于 Repository Inspection 提供的证据生成结构化 Plan，每个 PlanStep 有稳定 ID、执行状态、相关文件和验证方式。Orchestrator 通过显式 Task State Machine 推动 CREATED、INSPECTING、PLANNING、READY 等状态，非法状态转移会被 Runtime 阻止。当新的代码事实推翻 Plan 假设时，不是继续机械执行，而是产生新版本 Plan。后续还会通过 Plan-first vs Direct-edit Ablation 判断 Planning 增加的 Token 成本是否真正换来了 Task Success 提升。

这时你讲的已经不是：

```text
Prompt Engineering
```

而是：

```text
Agent Task Model
+
Planning Runtime
+
Execution State Machine
+
Repository Grounding
+
Observability
+
Evaluation
```

---

# 一百零八、今天在整个项目中的真正位置

今天其实是在搭未来 Single-Agent MVP 的“骨架”：

```text
                 TaskSpec
                    │
              Goal / Constraint
                    │
                    ▼
                Planning
                    │
                    ▼
              Execution State
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
       Current Step       Current Status
          │                   │
          └─────────┬─────────┘
                    ▼
                Orchestrator
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
     Context       Tools       Session
```

后面 Day 2 的：

```text
Verification / Repair
```

Day 3 的：

```text
Error Classification
```

Day 4 的：

```text
Session Persistence
```

全部都会依赖今天建立的：

```text
Task
Plan
State
```

因此 Day 1 最值得花时间理解的，并不是某几个 Pydantic Class，而是这个核心转变：

> **Coding Agent 不是“模型收到 Prompt 后调用几个 Tool”，而是一个 Runtime 在管理具有 Goal、Constraint、Plan、状态和终止条件的长期 Task。**

---

# 教练教程：Day 1 教学地图

> 以下内容由 Coder Agent 教练根据 `prompt/coder_Agent.md` 第六节规范生成（15 节结构），基于只读核实的仓库实际状态。

---

## 1. 今天在整个 Coding Agent 中做什么

前三周你在造**零件**：Agent Loop（W1）、Context Engine（W2）、Git/Policy/Sandbox（W3）。今天第一次定义**"一个 Coding Task 从出生到结束，Runtime 如何管理它"**。

**解决的问题：** 用户说"修复登录超时问题" —— Runtime 目前对这串字符一无所知：目标是什么？限制是什么？什么算完成？现在走到哪一步了？失败后回哪里？

**没有它的后果：** Task 只是一堆聊天消息的容器。模型开始"顺手重构 HTTP 层"时 Runtime 无法察觉；失败后不知道从哪恢复；CLI 无法展示进度；评测无法回答"哪一步失败了"。

**今天的转换：** 把"用户的一句话"从聊天 Prompt 升级成 **Runtime 可以管理的 Task**：

```
Natural Language → TaskSpec → Repository Inspection → Structured Plan → READY
```

今天 **READY 就是终点** —— 不写代码、不跑测试、磁盘零变更。

## 2. Capability Mapping

```
Primary:   Agent Harness（Task 生命周期模型 + 执行状态机）
Secondary: Context Engineering（Planning 前的 Repository Grounding）

能力树位置：
Agent Harness
├── Agent Loop          ← Week 1 已有
├── Tool Calling        ← Week 1 已有
├── State               ← 今天：Task 生命周期状态机
├── Stop Conditions     ← 今天：Terminal State 定义
└── Error Handling      ← 今天：任何异常 → FAILED 绝不卡死
```

**面试价值：** 这不是"调了个 LLM 列 TODO"，而是在证明你理解 **Agent Runtime 的核心问题——长期任务的显式状态管理**。工业系统（Codex Thread/Goal/Status、Claude Code Plan Mode、Copilot research→plan→iterate）全部把"计划"和"状态"做成 Runtime 一等公民，而不是留在消息流里。

## 3. Theory

今天必须理解的核心概念：

| 概念 | 一句话定义 | 为什么重要 |
|---|---|---|
| **Issue ≠ Prompt** | Prompt 是一次模型输入；Task 是需要完整生命周期管理的一件工作 | 一个 Task 内有 N 个 Prompt |
| **Task ≠ Session** | Task = 完成什么（业务语义）；Session = 持久化容器（Runtime 语义） | 今天只做 Task，Session 是 Day 4 |
| **Goal ≠ Implementation** | Goal = 最终系统应该怎样；Implementation = 准备改什么 | Goal 不随实现变化而失效 |
| **Constraint** | 完成 Goal 过程中不能违反什么（Solution Space Boundary） | 防止"性能提高了但产品行为破坏" |
| **Acceptance** | Runtime 怎么知道 Goal 已完成（Observable + Verifiable） | 最终进入 Day 2 的 Verification Loop |
| **Plan ≠ CoT** | Plan 是 Structured Execution Contract；CoT 是模型私有推理叙事 | Runtime 不能把推理过程当产品状态 |
| **PlanStep ≠ ToolCall** | 一个 Step 是工作单元，内部可含多个 Tool Call | 防止过度细碎规划 |
| **State Machine** | 明确规定合法状态转移的集合 | 没有它，`status="whatever"` 随处可写 |
| **Terminal State** | COMPLETED / FAILED 不可再转移 | 失败后 Retry 应在 FAILED 前完成 |
| **Tool Failure ≠ Task Failure** | pytest exit 1 不是 FAILED，是要进 Repair | FAILED = Runtime 决定不再自动继续 |

## 4. Industrial Design

| 系统 | 方案 | 与 CodeTeam 的关系 |
|---|---|---|
| **OpenAI Codex** | Plan Mode 先行收集上下文；任务描述明确 Goal/Context/Constraints/Done when；ExecPlan 是 living document，milestone 绑定 validation | 今天 TaskSpec 的四个字段直接对应 Goal/Constraints/Acceptance |
| **GitHub Copilot cloud** | 公开流程：Research → Plan → Iterate on code changes，可只研究不修改 | 今天规定 **Inspection 必须在 Planning 前** |
| **Claude Code Plan Mode** | 计划阶段可读代码/研究，批准前不改磁盘 | 今天 READY 状态 = "Plan 已生成、Runtime 就绪、零 Side Effect" |
| **Codex App Server** | Thread/Goal/Runtime Status 分层持久化，有 `thread/status/changed` 事件 | 今天 Status Change Event 设计直接借鉴 |

**统一工程思想：Understand → Plan → Act**，而不是 Prompt → Edit immediately。

## 5. 当前仓库检查（已核实）

| 项 | 状态 |
|---|---|
| `codeteam/task/`、`codeteam/planning/`、`codeteam/agent/` | ❌ 不存在（需新建） |
| `ContextApplicationService` | ✅ 存在于 `codeteam/application/build_context.py:476`，接口 `execute(query, repository_root, top_k=5, budget_tokens=1024) -> ContextBuildReport` |
| `codeteam/state.py` | ✅ 是 `AgentLoopState`（循环计数 + StopReason），**与 Task 状态机职责不同，不动它** |
| `codeteam/events.py` | ✅ 有 `AgentEventType` 枚举（step/model/tool/approval 事件），今天扩展 task 事件 |
| `codeteam/llm/mock.py` | ✅ `MockModelClient.complete(*args, **kwargs) -> str`，duck typing，无结构化输出支持 |
| `ContextBuildReport` | ✅ 含 top_files/repo_map/code_context/instructions/test_commands —— 可直接作为 Planner 的 repo evidence |
| 测试约定 | ✅ tests/ 分模块目录 + `__init__.py`；pytest.ini 排除 fixtures；682 passed |

## 6. 涉及文件

```
codeteam/task/                    ← [新建]
├── __init__.py
├── models.py                     ← TaskSpec（用户任务的结构化表示）
└── state.py                      ← TaskStatus 枚举 + 转移表 + TaskState（生命周期状态机）

codeteam/planning/                ← [新建]
├── __init__.py
├── models.py                     ← PlanStep / PlanStepStatus / Plan / Plan validation
└── planner.py                    ← Planner Protocol + MockPlanner（真实 LLMPlanner 放 Step 7）

codeteam/agent/                   ← [新建]
├── __init__.py
└── orchestrator.py               ← SingleAgentOrchestrator（推动 CREATED→INSPECTING→PLANNING→READY）

codeteam/events.py                ← [扩展] 新增 task.* / plan.* 事件类型

tests/task/                       ← [新建] test_models.py / test_state.py
tests/planning/                   ← [新建] test_models.py / test_planner.py
tests/agent/                      ← [新建] test_orchestrator.py
```

职责分层（不能违反）：

```
task/models.py      → Task 生命周期数据（不知道 Planner 存在）
task/state.py       → 状态转移规则（不知道 LLM 存在）
planning/models.py  → Plan 结构与验证（不知道 Orchestrator 存在）
planning/planner.py → TaskSpec + RepoContext → Plan（不知道执行引擎存在）
agent/orchestrator.py → 协调 ContextEngine + Planner + State + Events（不自己 os.walk/subprocess/git）
```

## 7. Architecture / Data Flow

```
User: "修复登录超时问题"
        │
        ▼
SingleAgentOrchestrator.run(request)
        │
        ├─ ① 空输入检查（空串/纯空白 → 早失败，不进 LLM）
        │
        ▼
TaskSpec(task_id, original_request, goal, constraints, acceptance_criteria)
        │
        ├─ ② transition CREATED → INSPECTING（发 task.status_changed 事件）
        │
        ▼
ContextApplicationService.execute(query, repository_root)
        │   ← Week 2 全套：QueryAnalyzer → CandidateGenerator → FileRanker → RepoMap
        │
        ▼
RepositoryContext(top_files, repo_map, symbols, instructions, test_commands)
        │
        ├─ ③ transition INSPECTING → PLANNING（发 repository.inspection_completed 事件）
        │
        ▼
Planner.create_plan(task=task_spec, repo_context=repo_context)
        │   ← Step 4-6 用 MockPlanner；Step 7 换真实 LLMPlanner
        │
        ▼
Plan(plan_id, task_id, version, steps=[P1, P2, P3...])
        │
        ├─ ④ Plan Validation（≥1 step / ID 唯一 / 初始状态合法 / 无非法跳转）
        │     失败 → plan.validation_failed 事件 → Task FAILED
        │
        ▼
transition PLANNING → READY（发 task.ready 事件）
        │
        ▼
返回 OrchestrationResult（含 TaskSpec + RepositoryContext + Plan + EventList）

任何未捕获异常 → transition → FAILED（绝不卡在中间状态）
READY 时磁盘零变更 —— 今天不执行 P1
```

## 8. 今日步骤拆分（7 步）

| Step | 目标 | 为什么先做 | 涉及文件 | 前置知识 | 完成标志 |
|---|---|---|---|---|---|
| **1** | TaskStatus/PlanStepStatus 枚举 + 合法转移表 + `transition_to()` + `is_terminal` | 状态机是全部后续逻辑的地基；纯数据结构最容易先保证正确 | `task/state.py` | str Enum、dict 转移表、异常 | 非法转移抛异常，Terminal 不可转移 |
| **2** | TaskSpec（original_request/goal/constraints/acceptance_criteria） | Planner 和 Orchestrator 都消费它；先手动构造，不需要 LLM | `task/models.py` | BaseModel、tuple 不可变、str \| None | 手动构造的 TaskSpec 通过校验 |
| **3** | PlanStep + Plan + Plan Validation（禁 PENDING→COMPLETED 直跳、is_complete、has_failed_step、Plan 不可变） | Plan 是 Runtime source of truth，验证规则先于 Planner 存在 | `planning/models.py` | Enum 默认值、@property、tuple[PlanStep, ...] | Plan 验证拒绝空 steps/重复 ID |
| **4** | Planner Protocol（duck typing）+ MockPlanner | 先 Mock 后真实：Unit/Integration 用 Mock 保确定性，Benchmark 才用真实模型 | `planning/planner.py` | Protocol、依赖注入 | MockPlanner 可注入任意 Plan/异常 |
| **5** | 接入 ContextApplicationService 作为 INSPECTING 阶段 grounding | 证明 Plan 建立在 Repo Evidence 而非模型猜测上 | `agent/orchestrator.py`（半成品） | 依赖注入、ContextBuildReport 字段 | 从真实 fixture 拿到 repo context |
| **6** | SingleAgentOrchestrator 完整实现 | 今天验收主体：状态推进 + 事件 + 失败不卡死 | `agent/orchestrator.py`、`events.py` | try/except 分层、事件发送 | 完整管线 CREATED→READY，磁盘零变更 |
| **7** | 真实 LLMPlanner + 10 个 Task Prompt Benchmark | 最后才碰真实模型；只测 Planning Cost 不测 Value | `planning/llm_planner.py`、`evals/` 脚本 | 结构化输出解析 | Benchmark 表格 + 原始结果持久化 |

## 9. Test Strategy

| 测试 | 对应验收 | 证明什么 |
|---|---|---|
| 普通任务 → READY | 管线走通 | TaskSpec→Inspection→Plan→READY 全链路 |
| 空任务早失败 | 不浪费 Token | 空串/纯空白在进 LLM 前 FAILED |
| Plan ≥1 step | Runtime Invariant | 空 Plan 拒绝，不进入 READY |
| 合法 Step 转移 PENDING→RUNNING→COMPLETED | 状态机正确性 | 转移表允许的路径成功 |
| 非法 Step 转移 PENDING→COMPLETED / COMPLETED→RUNNING | 状态机安全性 | 非法转移抛异常 |
| Plan is_complete / has_failed_step | Plan 状态查询 | 全 COMPLETED → True；含 FAILED → 不 complete |
| Replan v1→v2 | version 语义 | version+1、task_id 不变、旧 Plan 不被 mutate |
| 非法 Task 转移 CREATED→COMPLETED | 状态机安全性 | 拒绝跳跃 |
| Terminal 不可转移 COMPLETED→PLANNING | Terminal 语义 | immutable terminal |
| Planner 异常 → FAILED | 绝不卡死 | 异常被捕获，状态到 FAILED，不卡在 PLANNING |
| Planner 引用不存在文件 | Grounding 观察 | 软警告不拒绝（Day 1 只记录） |
| 事件序列断言 | Observability | task.created → status_changed ×3 → task.ready 顺序正确 |
| READY 后磁盘零变更 | 今日核心验收 | 运行前后仓库文件 SHA256 一致 |

每条测试都必须能回答"对应哪条验收、为什么能证明它"。

## 10. Design Decision Plan

今天正式记录 **DD-W4-D1-01：Structured Execution Plan**：

```
Problem:    CodeTeam 如何表示多步 coding work？
Alternatives:
  A. Free-form natural-language plan（模型易生成，但 Runtime 无法追踪进度/恢复/Replan）
  B. Structured Plan/PlanStep（可追踪/可恢复/可评测，但 Schema 复杂、需验证）
Decision:   Structured Plan 是 Runtime source of truth；
            natural-language description 保留给人读。
Evidence status: PROPOSED（Ablation 未跑，不得标 SUPPORTED）
Validation: Week 4 末 Plan-first vs Direct-edit Ablation
```

建议记录位置：先提议 `docs/design_decisions/`，经用户确认后写入。

## 11. Benchmark Plan

**问题：** Planning 的成本是多少？（今天只能答成本，不能答价值）

**数据集：** T01-T10 十个不同形态的 Task Prompt（修复 bug / 加 CLI flag / 修 failing test / 加校验 / 重构 / 加配置 / 改异常 / 补回归 / 修 type check / 改接口）

**指标（分开记录）：**

```
repo_inspection_ms         ← Context Engine 耗时
planner_ms                 ← 纯 Planner 模型调用耗时
total_planning_pipeline_ms ← 两者之和
step_count                 ← 观察过粗/过碎
planner_input_tokens / output_tokens / total
file_reference_validity    ← 探索性指标：Planner 提到的文件真实存在比例
```

**结论限制：** 只允许写 "Planning Cost"，禁止写 "Planning Value"（Task Success 未测）。

## 12. Ablation Plan（今天只写规格，Week 4 末执行）

```
Hypothesis:  Plan-first 换来的 Task Success 提升 > Planning Token 成本
Full:        Plan-first pipeline
Ablated:     Direct-edit（跳过 Planning，直接进入执行）
受控变量:     相同 Repo commit / 相同 10 prompts / 相同模型与温度 /
             相同工具集 / 相同 Budget —— 唯一变量是 planning enabled
指标:        Task Success Rate / Tool Calls / Tokens / Duration /
             Repair Attempts / Wrong-file edits
状态:        规格定稿，执行推迟到 Week 4 末
```

## 13. Failure Cases to Watch

| # | 场景 | Day 1 处理 |
|---|---|---|
| FC-1 | Plan 引用不存在的文件（幻觉计划） | 软警告（unverified reference），不拒绝整个 Plan |
| FC-2 | Plan 过度细碎（PlanStep == ToolCall） | 观察 step_count 分布，不强制 |
| FC-3 | Plan 一步过大（"实现整个功能"） | 观察 step_count 分布，不强制 |
| FC-4 | Planner 异常卡死 | **必须 FAILED** —— orchestrator 捕获一切异常 |
| FC-5 | 非法状态跳转（CREATED→COMPLETED） | **必须拒绝** —— transition_to 抛异常 |
| FC-6 | TaskState 与 AgentLoopState 职责混淆 | 命名空间分离：`codeteam/task/state.py` vs 旧 `codeteam/state.py`，互不引用 |

## 14. Interview Focus

**必答问题（25 个）**：分 Task/Goal/Plan/State/Evaluation 五组，见 day1.md 一百零六节。

**关键追问场景——"这不就是让 LLM 先列个 TODO 吗？"**

标准回答：

> 我没有把 Plan 当成一段给人看的 TODO 文本，而是把它作为 Agent Runtime 的显式执行状态。自然语言请求首先规范化成带 Goal、Constraints 和 Acceptance Criteria 的 TaskSpec；Planner 只能基于 Repository Inspection 提供的证据生成结构化 Plan，每个 PlanStep 有稳定 ID、执行状态、相关文件和验证方式。Orchestrator 通过显式 Task State Machine 推动状态，非法转移被 Runtime 阻止。当新代码事实推翻 Plan 假设时产生新版本 Plan。后续通过 Ablation 判断 Planning 成本是否换来了 Task Success 提升。

另一个高频追问："`FAILED` 之后不能 retry 吗？" —— 回答要点：Retry/Recovery 应该在进入 FAILED **之前**完成（VERIFYING→repair→IMPLEMENTING）；FAILED 代表"本 Task Runtime 决定不再自动继续"，不是"任何一次 Tool Failure"。

## 15. 今日最终完成标准

```
[ ] 管线走通：NL → TaskSpec → Inspection（ContextApplicationService）→ READY，不执行 P1，磁盘零变更
[ ] TaskStatus/PlanStepStatus 状态机：合法转移成功、非法转移拒绝、Terminal 不可转移
[ ] Plan Validation：≥1 step、ID 唯一、初始状态合法、Replan version 递增
[ ] MockPlanner 先行，真实 LLMPlanner 最后（Benchmark 专用）
[ ] 任何异常 → FAILED，绝不卡在中间状态
[ ] 事件序列完整：task.created → status_changed×N → task.ready
[ ] 测试全绿，每条测试可对应到验收
[ ] DD-W4-D1-01 已记录，Evidence status = PROPOSED
[ ] Benchmark 已运行（真实 LLM），只报告 Planning Cost
[ ] Ablation 规格定稿（执行推迟）
[ ] Failure Cases 已记录
[ ] 25 个面试问题可独立回答
[ ] 明确不做：Patch / Repair / Session / Compaction / Model Switch / 完整 CLI
```