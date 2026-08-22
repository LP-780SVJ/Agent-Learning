# 第 4 周 Day 7：15 Task Evaluation + README + `codeteam-single-agent`

今天和前 6 天最大的区别是：**不要继续增加能力，而是开始证明已有能力到底有没有用。**

前 6 天你已经把 Single-Agent Runtime 大体串起来：

```text
Day 1  Task → Plan → Execution State
Day 2  Patch → Test → Repair
Day 3  Failure → Recovery
Day 4  Session → Persistence → Resume
Day 5  Context → Compaction → Model Runtime
Day 6  CLI → Developer-facing Product
```

Day 7 要把研究问题改成：

```text
CodeTeam 到底能完成多少真实 Coding Task？

失败在哪里？

为什么失败？

Plan / Repair / Compaction 到底有没有贡献？

为这些能力付出了多少 Token / Cost / Latency？

换一个模型之后结论是否还成立？
```

所以今天真正进入的是：

# Agent Evaluation Engineering

而不是简单的：

```text
跑 15 次
→ 成功 12 次
→ Success Rate = 80%
→ README 写完
```

一个比较成熟的评测系统应该长成：

```text
                 Eval Dataset
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
      Task Prompt              Hidden Oracle
          │                       │
          ▼                       │
     Clean Repo State              │
          │                       │
          ▼                       │
       CodeTeam                   │
          │                       │
          ▼                       │
     Candidate Patch              │
          │                       │
          ▼                       │
      Eval Harness ────────────────┘
          │
     ┌────┼───────────────────────────┐
     ▼    ▼             ▼             ▼
Acceptance Regression   Safety      Budget
     │    │             │             │
     └────┴──────┬──────┴─────────────┘
                 ▼
             Task Result
                 │
        ┌────────┼─────────┐
        ▼        ▼         ▼
      Metrics  Trace   Failure Case
                 │
                 ▼
             Eval Report
```

今天最重要的一句话是：

> **Agent 说“我完成了”不是评价结果；Evaluation Harness 根据 Agent 看不到的、事先固定的标准判定它是否完成，才是结果。**

---

# 一、先理解：你到底在评测“模型”还是“Agent”？

这是 Day 7 第一个必须弄懂的问题。

假设同一个模型：

```text
Model X
```

分别放到：

```text
Agent A：
没有 RepoMap
没有 Repair Loop
没有 Checkpoint

Agent B：
Context Engine
Plan
Repair Loop
Session
Safe Runtime
```

最终：

```text
Agent A = 6/15

Agent B = 12/15
```

你不能说：

```text
Model X 的能力是 80%
```

因为你测的是：

```text
Model
+
Prompt
+
Context Retrieval
+
Planning
+
Tool Runtime
+
Repair
+
Stopping Policy
+
Sandbox
+
Evaluation Environment
```

也就是：

# Agent System / Harness

OpenAI 对 SWE-bench 的公开评测也明确区分模型和 scaffold：对于较新的模型，OpenAI 使用内部工具 scaffold 提供 Bash 和 Patch 等能力，并让模型在真实软件问题上迭代编辑和 Debug；这说明软件工程 Agent Benchmark 测到的从来不只是裸模型。

所以你的报告中应该写：

```text
CodeTeam Single-Agent Task Success Rate
```

而不是：

```text
Model A Coding Accuracy
```

除非你真的只比较模型本身。

---

# 二、评测为什么必须“固定 Harness 配置”

假设第一次：

```text
B01
Model A
max_steps=20
repair=3
```

第二次：

```text
B02
Model A
max_steps=50
repair=10
```

最后：

```text
13/15
```

这个结果很难解释。

因此每个 Eval Run 应记录：

```text
CodeTeam commit
Prompt version
Model
Provider

max_steps
max_repairs
timeout

Context settings
Compaction settings

Tool set

Sandbox profile
```

也就是：

```text
EvalConfig
```

例如概念模型：

```python
class EvalConfig(BaseModel):
    harness_version: str
    prompt_version: str

    provider_id: str
    model_id: str

    max_steps: int
    max_repairs: int
    task_timeout_seconds: int

    planning_enabled: bool
    repair_enabled: bool
    compaction_mode: str
```

以后你才能真正比较：

```text
Run A
vs
Run B
```

---

# 三、工业 Eval 为什么把 Dataset 和 Grader 明确分开

OpenAI 当前 Evals API 本身就把一个 Eval 建模成：

```text
Data Source
+
Testing Criteria
```

然后可以用不同模型配置运行同一个 Eval。也就是说：

```text
要测试什么
```

和：

```text
拿什么系统去测试
```

必须分开。

对应到 CodeTeam：

```text
EvalTask
=
Task Input


Oracle
=
Testing Criteria


CodeTeam Config
=
System under test
```

这三个千万不要混在一起。

---

# 四、15 个 Task 不是随便准备 15 条 Prompt

你最开始的分类：

```text
Bug Fix        5
Feature         4
Refactor        3
Maintenance     3
```

非常适合作为第一版。

但还应该加入：

# 难度维度

否则可能：

```text
B01 单文件
B02 单文件
B03 单文件
B04 单文件
B05 单文件
```

看起来是五种 Bug，实际上检验的是同一种能力。

---

# 五、建议 15 Task 同时覆盖四种复杂度

例如：

| Complexity | 特征 |
|---|---|
| L1 | 单文件、直接定位 |
| L2 | 多文件，需要搜索 |
| L3 | 跨模块，需要调用关系 |
| L4 | 模糊定位 + Test/Repair + 多步验证 |

你的 15 Task 可以形成：

```text
简单：4
中等：7
较难：4
```

第一版不要搞：

```text
15 个超难 SWE-bench Task
```

否则 MVP 很可能：

```text
2/15
```

你连哪个模块有用都看不出来。

也不能：

```text
15 个一行修改
```

否则：

```text
15/15
```

同样不能证明任何东西。

---

# 六、推荐的 15 Task 设计

可以按照下面这样的难度梯度。

### Bug Fix × 5

```text
B01
单文件 Logic Bug

例：
边界判断写反


B02
跨文件调用 Bug

例：
Service 参数没有正确传到 Client


B03
Configuration Bug

例：
配置默认值没有被真正读取


B04
Exception Handling Bug

例：
特定异常被错误吞掉


B05
Timeout / Resource Bug

例：
timeout 后 retry 状态没有正确恢复
```

B01 偏：

```text
Patch
```

B02：

```text
Retrieval + Dependency
```

B03：

```text
Config understanding
```

B04：

```text
Control Flow
```

B05：

```text
Testing + Repair
```

这样才真正覆盖能力面。

---

# 七、Feature × 4

例如：

```text
F01
增加一个小 API

能力：
理解已有 Interface Pattern


F02
增加 CLI option

能力：
CLI + Runtime wiring


F03
增加 Configuration

能力：
config propagation


F04
跨模块小 Feature

能力：
Plan + Multi-file changes
```

注意 Feature Oracle 会比 Bug Fix 更难设计。

Bug：

```text
FAIL
→ PASS
```

Feature：

```text
旧系统压根没有这个行为
```

因此最好：

```text
Hidden acceptance test
```

验证。

---

# 八、Refactor × 3

Refactor 特别值得保留，因为它和 Bug Fix 完全不同。

```text
R01
抽取公共函数

R02
重构 Interface

R03
Rename + downstream updates
```

这里成功标准不能只是：

```text
Tests PASS
```

例如 Agent 完全没 Refactor：

```text
所有 tests 本来也 PASS
```

它就“成功”了。

所以 Refactor Task 要同时有：

```text
Behavior Oracle
+
Structural Oracle
```

例如：

```text
tests pass

AND

旧 class 不再存在

AND

new interface exists
```

---

# 九、Maintenance × 3

```text
M01
补 Regression Test

M02
修 Failing Test Suite

M03
修 Type / Lint
```

这里能够验证：

```text
Agent 是否会处理
非 Feature / Bug 类任务。
```

特别是：

```text
M03
```

可以验证：

```text
Tool Output
→ Diagnose
→ Fix
```

而不一定涉及业务行为。

---

# 十、Task Fixture 的本质是什么

每一个 Eval Task 最好不是：

```text
一段 Prompt
```

而是一个：

```text
Reproducible Environment
```

完整 Task 应该包括：

```text
Task Metadata

Initial Repository State

User Prompt

Acceptance Oracle

Regression Oracle

Budget

Expected Safety Constraints
```

例如：

```yaml
id: B01

type: bug

difficulty: medium

prompt: |
  修复登录请求在首次超时后
  不会执行 retry 的问题。

repo_fixture: fixture-login

base_commit: abc123

acceptance_commands:
  - pytest -q eval_hidden/test_timeout.py

regression_commands:
  - pytest -q tests/auth

limits:
  max_steps: 20
  max_repairs: 3
  timeout_seconds: 900
```

---

# 十一、为什么必须固定 `base_commit`

假设：

```text
今天跑 B01
Repo Version = V1
```

下周：

```text
Repo Version = V7
```

又跑 B01。

然后你说：

```text
Success 从 60% 提升到 80%
```

不一定是 Agent 进步。

可能：

```text
Repository
变简单了。
```

所以每个 Task 必须绑定：

```text
base_commit
```

或者独立 Fixture Repo。

评测开始：

```text
Clean baseline
→ fresh Worktree
→ Agent
```

不能复用上一次 Task 修改后的 Workspace。

---

# 十二、Oracle 是整个评测最容易做坏的地方

你 Day 2 学过：

```text
Test Oracle
```

今天必须把它升级为：

# Evaluation Oracle

Oracle 回答：

> Agent 最终修改是否真正满足 Task？

你最基本的：

```text
acceptance_command
+
regression_command
```

已经很好。

但不要认为：

```text
Test PASS
=
绝对正确
```

---

# 十三、SWE-bench 给你的最大教训其实不是“怎么刷榜”

OpenAI 当初建立 SWE-bench Verified，就是因为原 SWE-bench 存在严重 Eval Quality 问题：

```text
Issue 描述不充分

Test 过于狭窄

Test 与 Issue 不匹配

Evaluation Environment 不稳定
```

OpenAI 当时让专业开发者人工筛选，并要求一个 Solution 同时通过两类测试：

```text
FAIL_TO_PASS
```

验证问题被真正解决；

以及：

```text
PASS_TO_PASS
```

验证没有破坏原有行为。

这与你设计：

```text
Acceptance
+
Regression
```

几乎是完全相同的思想。

---

# 十四、但更重要的是：OpenAI 后来又发现 SWE-bench Verified 本身也不够好

这是你做 Agent Evaluation 时非常值得知道的新情况。

OpenAI 近期重新审计 SWE-bench Verified，认为它已经不适合作为当前 Frontier Coding Capability 的主要指标，其中一个重要原因仍然是：

```text
一些 Test 会拒绝
实际上功能正确的 Solution
```

另外一些 Test 又会要求 Issue 本身没有规定的实现细节。

这告诉你：

> **Oracle 本身也必须被评测。**

所以你的 15 Task 不应该：

```text
测试写完
→ 默认测试绝对正确
```

而应该至少人工 Review：

```text
这个 Prompt 是否清楚？

这个 Acceptance 是否只验证公开需求？

有没有绑定具体实现？

Regression 是否稳定？

环境能否可靠启动？
```

---

# 十五、建议给每个 Eval Task 做一次“人工验题”

每个任务正式进入 Held-out Set 前，手动检查：

```text
Task Specification

[ ] 不存在严重歧义

[ ] 不需要 Agent 知道隐藏事实

[ ] 有合理正确解

[ ] 不强制一种实现


Oracle

[ ] 正确实现能通过

[ ] 错误实现确实失败

[ ] 不依赖偶然环境

[ ] Regression 稳定


Environment

[ ] fresh clone 可复现

[ ] dependency 固定

[ ] tests deterministic

[ ] timeout 合理
```

这相当于你的迷你：

```text
SWE-bench Verified
```

构建流程。

---

# 十六、Hidden Oracle 为什么特别重要

假设 Prompt：

```text
增加 normalize_email()
```

然后 Agent Context 里直接看到：

```python
def test_normalize_email():
    assert normalize_email(
        " A@B.COM "
    ) == "a@b.com"
```

它非常容易：

```text
针对测试写答案
```

所以 Evaluation 中：

```text
Agent-visible Tests
```

和：

```text
Hidden Acceptance Tests
```

最好分开。

Agent 可以看到项目已有 Unit Tests。

但评测额外增加：

```text
eval_hidden/
```

运行时：

```text
Agent 不知道测试内容
```

最后 Harness 执行。

OpenAI 当前介绍 SWE-bench 评测时同样强调，模型只看到 Issue 与 Repository，不看到正确的 Evaluation Tests；测试在最终 Patch 上执行。

---

# 十七、为什么不能泄露“正确修改文件”

假设真实 Task：

```text
修复 Session Resume
```

你给 Agent：

```text
请修改:
session/store.py
中的 load_session()
```

它就不再需要：

```text
RepositoryScanner

SymbolIndex

ripgrep

ImportGraph

RepoMap
```

结果：

```text
Task Success = 100%
```

并不能证明你的 Week 2 Context Engine。

所以 Eval Prompt 应该尽量像真实 Issue：

```text
描述行为
描述错误
描述预期
```

但不告诉：

```text
正确文件

正确 Symbol

正确 Patch
```

这叫避免：

# Evaluation Leakage

---

# 十八、Dev Set 和 Held-out Set 为什么一定要分

这是你今天最重要的实验方法概念之一。

假设：

```text
B01
失败
```

你发现：

```text
RepoMap 召回不好
```

于是修改 Ranking。

重新：

```text
B01
PASS
```

你又发现：

```text
Planning 太长
```

修改 Prompt。

再跑：

```text
B01
PASS
```

这个 Task 已经深度影响了：

```text
你的设计
```

所以它不能继续作为独立证据证明：

```text
泛化能力。
```

它已经变成：

# Development Set

---

# 十九、建议你第一版怎么拆

你提出：

```text
Dev 5
Held-out 10
```

我非常赞成。

例如：

```text
Dev

B01
B02
F01
R01
M01
```

用来：

```text
debug
调 Prompt
调 Ranking
调 Repair
调 Budget
```

然后冻结：

```text
Harness
```

再运行：

```text
Held-out 10
```

一次性获得正式结果。

---

# 二十、如果还能再做一步，最好再准备 5 个 Final Holdout

也就是：

```text
Development       5
Main Evaluation  10
Final Unseen      5
```

但这已经属于 Stretch。

如果时间紧：

```text
5 + 10
```

足够。

最重要的是：

```text
不要反复看 Held-out
然后继续针对它调系统。
```

否则它迟早也会变 Dev Set。

---

# 二十一、Evaluation Contamination 不只来自直接调 Prompt

还有很多隐性方式：

```text
你记住了答案

你人工修过那个 Repo

Agent Prompt 中出现文件名

README 泄露 Implementation

Fixture 中留下 TODO

Test 名本身暴露 Root Cause
```

例如：

```text
test_fix_retry_count_in_http_client
```

虽然 Agent 看不到代码，

文件名已经告诉它：

```text
HTTP Client
+
retry_count
```

所以 Hidden Evaluation 要尽量减少这种信息泄漏。

---

# 二十二、Task Success 必须严格定义

你现在的：

```text
Task Success
=
Acceptance Test PASS

AND

Required Regression PASS

AND

Within limits

AND

No security violation
```

非常正确。

我建议正式定义成：

\[
Success_i =
A_i \land R_i \land B_i \land S_i
\]

其中：

```text
A = Acceptance passed

R = Regression passed

B = Within budget

S = Security constraints respected
```

然后：

\[
TaskSuccessRate =
\frac{\sum_i Success_i}{N}
\]

不要：

```text
Agent final message contains "done"
```

作为任何成功判断条件。

---

# 二十三、为什么 Budget 也属于 Success

假设 Task：

```text
最终 PASS
```

但用了：

```text
4 小时

800 tool calls

2M tokens
```

而你的产品限制：

```text
15 分钟
20 steps
```

那么从 Runtime Evaluation 来说：

```text
应该失败。
```

因为 Task Contract 包含：

```text
resource boundary
```

否则：

```text
无限时间
无限 Token
无限 Repair
```

几乎任何 Agent 都可能最终偶然撞到正确答案。

---

# 二十四、Security 为什么必须进入 Success Definition

比如 Agent：

```text
测试通过
```

但期间：

```text
读取 ~/.ssh

绕过 Sandbox

修改 Main Worktree
```

不能：

```text
Success=True
```

所以：

```text
Functional correctness
```

只是成功的一部分。

你的 Week 3 已经给出了非常好的：

```text
Security Invariants
```

Day 7 应直接纳入 Eval Harness：

```text
main worktree unchanged

no denied command executed

no sandbox bypass

no outside-workspace mutation
```

因此：

# Safety Failure = Task Failure

即使 Test 100% PASS。

---

# 二十五、这也是 Agent Eval 和普通 Unit Test 最大区别之一

普通 Unit Test：

```text
input
→ function
→ output
```

Agent Evaluation：

```text
Task
→ hundreds of decisions
→ search
→ file reads
→ commands
→ patch
→ repair
→ final workspace
```

不仅需要检查：

```text
Final Output
```

还要检查：

```text
Execution Trajectory
```

例如：

```text
有没有越权？

用了多少 Step？

是不是重复搜索 20 次？

是不是一直 Repair 同一 Failure？
```

所以你前几周保存：

```text
Events
Trace
Metrics
```

现在全部变成 Evaluation Evidence。

---

# 二十六、核心指标 1：Task Success Rate

最重要。

但建议同时报告：

```text
Overall

By Task Type

By Difficulty
```

例如：

```text
Overall
12 / 15


Bug
5 / 5


Feature
3 / 4


Refactor
2 / 3


Maintenance
2 / 3
```

这样你才能看到：

```text
Refactor
明显弱于 Bug Fix。
```

---

# 二十七、最好还报告 Confidence / 样本量限制

15 Task 是：

```text
工程项目小型 Eval Suite
```

而不是统计意义上特别强的 Benchmark。

所以 README 里不要：

```text
CodeTeam has 80% coding accuracy.
```

更准确：

```text
CodeTeam solved 8/10 held-out tasks
in our current evaluation suite.
```

这非常重要。

尤其：

```text
N=10
```

一次 Task 成败就改变：

```text
10 percentage points
```

所以不要假装精确到：

```text
83.7%
```

---

# 二十八、Agent 的非确定性怎么办

假设同一个 Task：

```text
Run 1
PASS

Run 2
FAIL
```

到底算什么？

你第一版为了控制 Cost，可以：

```text
每个 Task 一次正式 Run
```

这没问题。

但必须固定并记录：

```text
Model configuration

reasoning effort

temperature（如果有）

Harness version
```

如果以后资源允许：

```text
每 Task × 3 Runs
```

可以计算：

```text
Task-level success probability
```

但 Day 7 第一版不用把实验规模炸得太大。

---

# 二十九、Wall-clock Duration

定义：

```text
从 Task Runtime 正式开始

到：

COMPLETED / FAILED
```

不要只记录：

```text
Model latency。
```

因为 Coding Agent 的真实耗时包括：

```text
Retrieval

Model

Tools

Tests

Docker Startup

Repair

Compaction
```

所以：

# Wall Clock

是最接近用户感受的指标。

建议：

```text
Median

P95
```

不要只平均。

---

# 三十、为什么 P95 很重要

假设：

```text
14 Task
2 min

1 Task
40 min
```

平均：

```text
4.53 min
```

看起来还不错。

但用户会遇到：

```text
极慢的 Long Tail
```

所以：

```text
Median
+
P95 / Max
```

更完整。

不过 N=15 时 P95 非常粗，可以同时直接报告 Max。

---

# 三十一、Cost 不应该只报告“总花了多少”

真正有价值的是：

```text
Cost per Task

Cost per Successful Task
```

尤其：

\[
MedianCostPerSuccessfulTask
\]

因为一个便宜但经常失败的系统：

```text
$0.05
成功率 20%
```

和：

```text
$0.20
成功率 90%
```

不能只比较平均 Cost。

---

# 三十二、Token 应拆 Input / Output

你已经计划：

```text
Input Tokens
Output Tokens
```

很好。

还可以以后继续拆：

```text
planning tokens

repair tokens

compaction tokens
```

这可以回答：

```text
钱到底花在哪？
```

例如：

```text
Planning
占 10%

Repair
占 50%
```

说明最值得优化：

```text
First-pass patch quality
```

---

# 三十三、Tool Calls 也不是单纯“越少越好”

一个 Agent：

```text
2 tool calls
→ 失败
```

不比：

```text
15 tool calls
→ 成功
```

更好。

Tool Calls 主要用来理解：

```text
Execution Efficiency
```

比如两个都成功：

```text
Agent A
35 calls

Agent B
12 calls
```

B 可能更高效。

建议分类：

```text
search

read

patch

command

test

git
```

不要只存总数。

---

# 三十四、Repair Attempts 是非常好的 Agent 指标

例如：

```text
Success
```

但：

```text
repairs=3
```

说明：

```text
Agent 最终能纠错
```

但：

```text
First-pass quality
```

较弱。

所以最好同时算：

# First-Pass Success Rate

\[
FPSR =
\frac{\text{无需 Repair 成功 Task}}
{\text{全部 Task}}
\]

它和：

```text
Final Success Rate
```

组合起来很有解释力。

---

# 三十五、Context Compactions 也应该进入 Task Record

例如：

```text
Task R03

compactions=4

duration=15m

tokens=150K
```

你可以开始研究：

```text
长任务为什么这么贵？
```

并观察：

```text
Compaction 后
是否发生 Lost Constraint / Repeat Retrieval。
```

---

# 三十六、GitHub 当前生产指标给你的启示

GitHub 现在对 Copilot 的生产 Usage Metrics 不只是记录“有没有产生代码”。其指标包括 CLI Session Count、Request Count、Prompt/Output Token Usage；对于 Copilot cloud agent，还会跟踪其 PR 创建、合并以及 Copilot-authored PR 的 median time-to-merge 等生命周期数据。

GitHub 的 Agent Session 管理界面也允许观察 Session Progress、Token Usage 和 Session Length。

这说明工业 Agent Evaluation 往往是：

```text
Quality
+
Cost
+
Latency
+
Lifecycle
+
Usage
```

而不是：

```text
代码有没有生成。
```

你现在统计：

```text
Success
Cost
Tokens
Duration
Repair
```

方向是完全正确的。

---

# 三十七、我建议你的 Eval Result 数据模型

例如：

```python
class EvalTaskResult(BaseModel):
    run_id: str
    task_id: str

    task_type: str
    difficulty: str

    provider_id: str
    model_id: str

    success: bool

    acceptance_passed: bool
    regression_passed: bool
    within_budget: bool
    security_passed: bool

    duration_ms: int

    input_tokens: int
    output_tokens: int
    cost_usd: Decimal

    tool_calls: int
    repair_attempts: int
    compaction_count: int

    files_changed: tuple[str, ...]

    final_status: str

    failure_category: str | None
    failure_case_id: str | None
```

以后：

```text
CSV

JSON

Markdown Report
```

全部从它生成。

---

# 三十八、不要手工填结果表

建议：

```text
EvalRunner
↓
results.jsonl
↓
ReportGenerator
↓
evaluation.md
```

而不是：

```text
跑一个
→ 手写 Excel

跑一个
→ 手写 README
```

因为：

```text
容易录错

难重新跑

难做 Ablation
```

---

# 三十九、推荐 Eval 目录

可以逐渐形成：

```text
evals/
├── tasks/
│   ├── B01.yaml
│   ├── B02.yaml
│   ├── ...
│   └── M03.yaml
│
├── fixtures/
│   ├── repo-a/
│   └── repo-b/
│
├── hidden_tests/
│
├── runner.py
├── grader.py
├── metrics.py
└── report.py

eval_results/
├── baseline/
│   └── results.jsonl
├── plan_ablation/
├── repair_ablation/
└── compaction_ablation/
```

不要为了今天一定改成这个目录。

重点是：

```text
Dataset
Runner
Grader
Result
```

四层分开。

---

# 四十、EvalRunner 应该怎么工作

大致：

```text
for task in eval_suite:
        │
        ▼
create clean worktree
        │
        ▼
reset to base_commit
        │
        ▼
run CodeTeam with EvalConfig
        │
        ▼
capture runtime trace
        │
        ▼
stop agent
        │
        ▼
run hidden acceptance
        │
        ▼
run regression
        │
        ▼
check security invariants
        │
        ▼
collect metrics
        │
        ▼
save result
        │
        ▼
destroy eval worktree
```

Eval Harness 必须独立于 Agent。

不能：

```text
Agent 自己运行 Oracle
Agent 自己说 Oracle PASS
```

最终 Grading 最好：

```text
由外层 Harness
再执行一次。
```

---

# 四十一、为什么要“Agent 完成后再独立 Grade 一次”

假设 Agent 内部说：

```text
pytest
42 passed
```

但之后：

```text
又修改了文件
```

最终 Workspace：

```text
实际上 test FAIL
```

如果 Eval 只看：

```text
Agent 当时的 Test Result
```

就会错误判定成功。

所以最终：

```text
Agent terminates
        ↓
freeze final workspace
        ↓
Eval Harness
重新跑 Acceptance/Regression
```

这个 Grading 才是权威。

---

# 四十二、这是一个很重要的“Actor / Judge 分离”

可以理解：

```text
CodeTeam
=
Actor


EvalHarness
=
Judge
```

Actor：

```text
不知道 hidden oracle
```

Judge：

```text
不相信 Actor 自我报告
```

这是非常重要的 Evaluation Architecture。

---

# 四十三、Ablation 到底是什么

很多人会把 Ablation 理解成：

```text
删除一个模块
看看数字
```

更准确：

> **控制其他条件基本不变，仅关闭或替换某个设计，观察 Evaluation 指标发生什么变化。**

目的是回答：

```text
这个模块
究竟贡献了什么？
```

而不仅仅证明：

```text
整个 Agent 能工作。
```

---

# 四十四、A1：Plan-first vs Direct Execute

Full：

```text
Task
→ Repo Inspection
→ Plan
→ Execute
```

Ablation：

```text
Task
→ Repo Inspection
→ Direct Execute
```

注意：

```text
Repo Inspection
```

应该两边都有。

否则你同时移除了：

```text
Planning
+
Context
```

不知道是谁造成差异。

---

# 四十五、Plan Ablation 选哪 5 Task

不要：

```text
五个单文件 one-line bug
```

因为 Planning 对简单任务可能只增加负担。

更适合：

```text
B02 cross-file

B05 timeout

F04 cross-module feature

R02 interface refactor

R03 rename/downstream
```

也就是：

```text
中等、多步骤任务。
```

这才能真正检验 Planning。

---

# 四十六、Plan Ablation 应看什么

不只是：

```text
Success
```

还看：

```text
Wrong-file edits

Tool calls

Tokens

Duration

Repair attempts

Replan count
```

可能得到：

```text
Plan
Success ↑
Wrong-file edit ↓

但：
Token ↑
Latency ↑
```

这才是真正 Design Trade-off。

---

# 四十七、A2：Repair Loop vs Single Shot

Full：

```text
Initial Patch
→ Test
→ Repair × up to 3
```

Ablation：

```text
Initial Patch
→ Test
→ STOP
```

最直观指标：

```text
Final Task Success Rate
```

再报告：

```text
First-pass Success
```

因为 Single-shot 的成功率本质接近：

```text
First-pass quality
```

而 Repair Full 展现的是：

```text
Runtime Recovery Ability。
```

---

# 四十八、Repair Ablation 最能证明什么

假设：

```text
Single Shot:
3/5

Repair:
5/5
```

而：

```text
Repair 多用了
30% tokens
```

你就可以非常具体地说：

> 在这 5 个任务上，Repair Loop 用额外计算成本换来了两个额外成功任务。

这比：

```text
Repair Loop 很有用
```

有说服力得多。

---

# 四十九、A3：Compaction 实验我建议改成三组

你原本：

```text
No Compaction
vs
Structured Compaction
```

很好。

但更有解释力：

```text
A
Raw History / No Compaction

B
Naive Truncation

C
Structured Compaction
```

因为 No Compaction 最后很可能：

```text
直接 context overflow
```

这只能证明：

```text
Context Window 有限。
```

而：

```text
Naive Truncation
vs
Structured Compaction
```

才能证明：

```text
你的 Context Engineering
有没有作用。
```

---

# 五十、Compaction 实验看什么

除了：

```text
Task Success
Token
Cost
```

特别推荐：

# Lost Constraint Error

例如任务开头明确：

```text
禁止修改 Public API
```

任务很长以后：

```text
Agent 有没有忘？
```

再加：

# Repeated Retrieval

如果 Compaction 丢了重要事实，

Agent 很可能：

```text
重新搜索
重新读同一文件
```

因此：

```text
Repeated File Reads

Repeated Searches
```

也能反映 Context Loss。

---

# 五十一、Ablation 最大实验错误：Full 和 Ablation Budget 不同

例如：

```text
Plan:
max_steps=30

No Plan:
max_steps=10
```

最后 Plan 更成功。

没有意义。

必须尽量固定：

```text
Model
Provider
Repo state
Task prompt
Time budget
Step budget
Repair budget
Tool set
Sandbox
```

只改一个核心 Variable。

---

# 五十二、还要警惕 Model Nondeterminism

如果：

```text
Full
跑一次

Ablation
跑一次
```

某个 Task 的差异可能只是随机性。

第一版资源有限，可以接受。

但要在报告明确：

```text
single-run exploratory ablation
```

如果后面时间允许：

```text
每组每任务 3 runs
```

会更可靠。

---

# 五十三、Failure Case Database 不是“失败任务列表”

这是今天另一个非常重要的概念。

错误：

```text
B02 FAIL
R01 FAIL
M03 FAIL
```

这只是：

```text
Failed Tasks
```

不是：

# Failure Case Database

Failure Case 应该描述：

```text
发生了什么失败模式？

如何观察到？

根因是什么？

如何复现？

怎样防止再次发生？
```

---

# 五十四、推荐 FailureCase Schema

例如：

```python
class FailureCase(BaseModel):
    failure_id: str

    title: str

    category: str
    component: str

    trigger: str

    observed_behavior: str

    root_cause: str | None

    affected_tasks: tuple[str, ...]

    detection_signal: str

    mitigation: str | None

    regression_test: str | None

    status: str
```

Status：

```text
OPEN

MITIGATED

FIXED

ACCEPTED
```

---

# 五十五、例如 F001：错误 Plan 导致错误文件

不是简单：

```text
F001:
Wrong plan
```

而是：

```text
Failure:
F001

Title:
Planner generated ungrounded file target

Task:
B02

Observed:
Plan referenced src/login/controller.py

Repository:
file does not exist

Root Cause:
Planner treated semantic guess as repository fact

Detection:
Plan grounding validation

Mitigation:
Verify file references against RepositoryIndex

Regression:
test_plan_references_existing_paths
```

这才叫 Failure Case。

---

# 五十六、F002：检索不到关键文件

例如：

```text
Prompt:
timeout

Correct:
transport/retry.py

Top-5 Retrieval:
完全没有 transport/retry.py
```

Root Cause：

```text
QueryAnalyzer
只提取 timeout

没有从 stack trace
提取 RetryError
```

Mitigation：

```text
Error message entity extraction
```

这就会反哺 Week 2。

---

# 五十七、F003：Patch 不适用

例如：

```text
PATCH_CONTEXT_MISMATCH
```

可能因为：

```text
Context 太旧

上一 Repair 修改了同一行

Planner 读取的不是当前 Worktree
```

然后 Day 3：

```text
REREAD_AND_REGENERATE
```

就是 Failure Mitigation。

---

# 五十八、F004：Repeated Repair Loop

记录：

```text
failure_signature
重复 3 次

changed_files
没有变化

patch similarity
很高
```

Root Cause：

```text
Repair Agent
没有吸收失败证据
```

Mitigation：

```text
No-progress detector
→ REPLAN
```

---

# 五十九、F005：Flaky Test

这类 Failure 特别重要：

```text
Agent Code
可能没错

Oracle
却不稳定。
```

需要记录：

```text
Test
Pass/Fail history

Environment

Rerun policy
```

不要把它都归：

```text
Agent capability failure
```

---

# 六十、F006：Compaction 丢 Constraint

这是 Day 5 非常有代表性的 Failure。

记录：

```text
Original:
不能添加 dependency

After compaction:
summary missing constraint

Later:
Agent modifies pyproject
```

Root Cause：

```text
Task Constraint
只存在于 Conversation

没有 authoritative reinjection
```

Mitigation：

```text
TaskSpec constraints
每 Turn重新注入
```

这会成为非常好的 Context Engineering 案例。

---

# 六十一、F007～F012 也应该全部这样记录

例如：

```text
F007
Resume worktree missing
→ Session / Workspace reconciliation

F008
Corrupted session
→ Atomic persistence

F009
Provider timeout
→ Typed retry policy

F010
Model switch behavior drift
→ model attribution / switch boundary

F011
CLI interrupted while persisting
→ crash-consistent write

F012
Checkpoint ownership mismatch
→ cross-task rollback rejection
```

注意这些不全是：

```text
LLM 能力 Failure
```

很多是：

```text
Agent Runtime Failure
```

这正是你这个项目的价值所在。

---

# 六十二、Failure Taxonomy 可以再聚合一次

以后你甚至可以出一张：

| Failure Area | Count |
|---|---:|
| Planning | |
| Retrieval | |
| Patch | |
| Verification | |
| Context | |
| Model | |
| Session | |
| Safety | |

这可以回答：

> **提高 CodeTeam Success Rate 最值得优化哪一层？**

例如：

```text
15 Task

5 failures

3 Retrieval
1 Test
1 Model
```

那么下周应该重点：

```text
Context Engine
```

而不是：

```text
继续改 Planner Prompt。
```

---

# 六十三、这就是 Evaluation 驱动研发

健康流程：

```text
Eval
 ↓
Failure Cluster
 ↓
Root Cause
 ↓
Runtime Change
 ↓
Regression Test
 ↓
Re-run Eval
```

而不是：

```text
感觉效果不好
↓
改 Prompt
↓
感觉好像好了
```

这正是 Agent Engineering 与“Prompt 玩具”的巨大区别。

---

# 六十四、README 到底承担什么作用

Day 7 README 不是项目说明书那么简单。

它应该同时服务三种人：

```text
Recruiter / interviewer

Developer

Future yourself
```

Recruiter：

```text
30 秒知道你做了什么。
```

Developer：

```text
5 分钟跑起来。
```

Interview：

```text
看到架构、指标、设计证据。
```

---

# 六十五、README 第一屏最重要

不要开头：

```text
随着大语言模型的快速发展，
AI Agent 逐渐成为……
```

两屏过去还不知道项目干嘛。

建议一开始：

```text
# CodeTeam

A local-first, provider-neutral coding agent runtime
that can inspect a repository, plan changes,
edit code, verify fixes, recover from failures,
resume interrupted sessions, and rollback safely.
```

接着直接：

```bash
codeteam run "修复登录超时问题"
```

Demo。

---

# 六十六、README 首页 Demo 为什么特别重要

招聘方通常不会：

```text
从第 1 行读到第 900 行
```

他需要立刻知道：

```text
这个项目能不能真实工作？
```

所以你规划的 Demo 很正确：

```text
$ codeteam run ...

Session: ...
✓ inspected
✓ planned
✓ reproduced
✓ patched
✓ verified

Status: COMPLETED
```

然后：

```text
codeteam diff

codeteam resume

codeteam rollback
```

它一下子把：

```text
Coding
Session
Git
Recovery
```

都展示出来。

---

# 六十七、README Architecture 图应该画什么

不要再画：

```text
LLM
→ Tools
```

这么简单。

建议体现真正项目能力：

```text
                    CLI
                     │
                     ▼
             Session Service
                     │
                     ▼
          SingleAgentOrchestrator
                     │
         ┌───────────┼──────────────┐
         ▼           ▼              ▼
      Context      Planner        Model
      Engine                      Runtime
         │           │              │
         └──────┬────┴──────────────┘
                ▼
             AgentLoop
                │
       ┌────────┴──────────┐
       ▼                   ▼
    Patch Lane         Command Lane
       │                   │
       ▼                   ▼
 Git / Checkpoint       SafeExecutor
                           │
                     Policy/Approval
                           │
                        Sandbox
                           │
                         Runner
       │
       └────────────┬────────────
                    ▼
               Verification
                    │
              Repair / Replan
                    │
                    ▼
                Session
```

这张图才是：

```text
Agent Runtime / Harness
```

项目。

---

# 六十八、README Evaluation 绝对不要隐藏失败

假设结果：

```text
10/15
```

就写：

```text
10/15
```

然后：

```text
Known weaknesses:
- cross-module refactoring
- context recovery after long repair loops
```

这比：

```text
Accuracy up to 95%
```

但没有 Dataset 和定义要专业得多。

---

# 六十九、README Evaluation Section 推荐包含

例如：

```text
## Evaluation

Dataset
- 15 repository tasks
- 5 bug fixes
- 4 features
- 3 refactors
- 3 maintenance tasks

Protocol
- fresh worktree per task
- fixed budgets
- hidden acceptance oracle
- regression verification
- security invariants

Results
- overall success
- by category
- median time
- P95/max time
- median cost/success

Ablations
- no planning
- no repair loop
- naive context handling

Known limitations
...
```

这样别人能够：

```text
复现并理解你的数字。
```

---

# 七十、工业生产 Metrics 也不会只展示“Agent 生成多少代码”

GitHub 当前 Copilot Usage Metrics 同时覆盖模型使用、Agent 使用、Token、CLI Session/Request 数，以及 PR 创建、合并与 time-to-merge 等工程生命周期指标。

这给 README 一个很好的启示：

不要只放：

```text
Success Rate
```

还应该：

```text
Cost
Latency
Tool Calls
Repairs
```

从而展示：

# Quality / Efficiency Trade-off

---

# 七十一、README 的 Benchmark 表不要写得像论文吹榜

更推荐：

| Metric | Result |
|---|---:|
| Held-out tasks | 10 |
| Solved | 实测 |
| Median duration | 实测 |
| Max/P95 duration | 实测 |
| Median successful-task cost | 实测 |
| Median tool calls | 实测 |

并写：

```text
These results describe the current
small internal evaluation suite;
they are not a general coding benchmark.
```

这样更严谨。

---

# 七十二、为什么今天不要继续堆 Feature

假设现在你发现：

```text
还没有漂亮 status command
```

又想做。

然后：

```text
想加 Web UI
```

然后：

```text
想加 GitHub PR
```

Day 7 永远做不完。

今天应采用：

# Feature Freeze

除了：

```text
阻塞 Evaluation 的 Bug
```

不要添加新 Product Feature。

因为你今天真正需要知道：

```text
前六天写的东西
到底有没有工作。
```

---

# 七十三、什么 Bug 可以 Day 7 修

例如：

```text
EvalRunner 根本跑不起来

Resume 必崩

Metrics 没记录

Oracle 无法执行
```

这些属于：

```text
Evaluation blocker
```

可以修。

但是：

```text
“顺便支持第三 Provider”
```

不行。

---

# 七十四、Day 7 最推荐的执行流程

今天你可以按照这个顺序真正做。

第一阶段是 **冻结系统**。记录当前 Git Commit、Prompt Version、Provider/Model 和所有 Budget，形成 `EvalConfig`。

第二阶段是 **验题**。人工检查 15 个 Task 的 Prompt、Base Commit、Acceptance、Regression 和环境可靠性，然后划分 5 Dev + 10 Held-out。

第三阶段是 **跑 Baseline**。每个 Held-out Task 创建 Fresh Worktree，由 EvalRunner 执行 CodeTeam；Agent 结束后再由独立 Grader 执行 Hidden Acceptance、Regression 和 Security Checks，自动输出 `results.jsonl`。

第四阶段是 **分析失败**。不是立即改代码，而是先给每个 Failed Task 建 Failure Case，按照 Planning / Retrieval / Patch / Verification / Context / Model / Session / Safety 归因。

第五阶段是 **三个 Ablation**。选 5 个中等 Task 分别运行 Plan vs No Plan、Repair vs Single Shot；选择 Long Task 运行 Structured Compaction vs Naive/No Compaction。

第六阶段才是 **生成最终报告和 README**。结果必须从 Raw Eval Results 自动汇总，禁止手工“优化数字”。

---

# 七十五、我建议再建立 `EvalRun`

例如：

```python
class EvalRun(BaseModel):
    eval_run_id: str

    harness_version: str
    prompt_version: str

    provider_id: str
    model_id: str

    started_at: datetime

    task_ids: tuple[str, ...]

    results_path: str
```

为什么？

因为半年以后：

```text
eval-001
10/15

eval-027
14/15
```

你必须知道：

```text
到底改变了什么？
```

---

# 七十六、最好给每次实验写 Version Fingerprint

例如：

```text
CodeTeam Commit:
af29ec

Prompt:
planner-v4
repair-v2

Provider:
A

Model:
X

Eval Dataset:
suite-v1
```

这样你的 Eval 是：

# Reproducible Experiment

而不是：

```text
“我记得上个月跑过一次，大概 70%。”
```

---

# 七十七、OpenAI 对软件 Eval 的历史也说明 Benchmark 本身要版本化

SWE-bench Verified 最初就是为了修正原 Benchmark 的问题而建立；而随着前沿系统能力提升，OpenAI 又重新审计并认为其中残留的 Oracle 问题已经足以影响其继续作为 Frontier Benchmark。

这告诉你一个非常成熟的观点：

> **Evaluation Suite 本身也是软件产品，需要版本、质量控制和持续维护。**

所以以后：

```text
eval-suite-v1
eval-suite-v2
```

很合理。

---

# 七十八、今天最重要的 Evaluation Invariants

建议把下面这些直接写成 Test：

```text
E01
Agent does not see hidden oracle.

E02
Every task starts from the exact
configured base repository state.

E03
Failed/previous task changes
cannot contaminate next task.

E04
Agent final message never determines success.

E05
Acceptance and regression are
rerun after agent termination.

E06
Security violation forces failure.

E07
Budget exhaustion forces failure.

E08
Metrics come from structured runtime events,
not log regex where avoidable.

E09
Held-out tasks are not used for prompt tuning.

E10
Ablation changes only the intended component.
```

这些比：

```text
assert success_rate > 80%
```

更基础。

---

# 七十九、今天最值得做的 Design Decision

我建议正式写：

```text
DD-W4-D7-01
Oracle-driven Agent Evaluation
```

核心内容可以是：

```text
Problem:
How should CodeTeam determine whether
an autonomous coding task succeeded?

Alternatives:

A.
Use the agent's final self-reported result.

B.
Use an external evaluation harness with
hidden acceptance tests, regression tests,
budget constraints, and safety invariants.

Decision:
B.

Reasons:
- prevents self-grading
- supports reproducible evaluation
- detects regressions
- captures runtime/safety failures
- enables model/harness comparison

Trade-offs:
- test-suite maintenance
- oracle quality can itself be flawed
- fixture construction cost

Mitigation:
- manual task validation
- hidden tests
- held-out tasks
- benchmark versioning
- failure-case review
```

---

# 八十、第二个 Design Decision 也值得写

```text
DD-W4-D7-02
Development / Held-out Evaluation Split
```

Decision：

```text
Use 5 development tasks for system tuning
and freeze the harness before evaluating
on 10 held-out tasks.
```

目的：

```text
减少 Evaluation Overfitting。
```

---

# 八十一、今天最终应该形成的项目产物

到 Day 7 结束，你的成果不应该只有：

```text
README.md
```

而最好是一整套：

```text
codeteam-single-agent/

Architecture

Code

Tests

evals/
  tasks
  runner
  grader

eval_results/
  baseline
  ablations

failure_cases/

design_decisions/

README.md
```

逻辑上形成：

```text
Code
+
Evidence
```

而不是只有：

```text
Code。
```

---

# 八十二、最终 Evaluation 表建议升级成这样

你原来的表很好，可以稍微增强：

| Task | Type | Diff. | Model | Success | Repairs | Time | Tokens | Cost | Failure |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| B01 | Bug | L1 | A | | | | | | |
| B02 | Bug | L3 | A | | | | | | |
| … | | | | | | | | | |
| M03 | Maint. | L2 | A | | | | | | |

其中：

```text
Failure
```

不是写完整描述，

而是：

```text
F002
```

链接到 Failure Database。

---

# 八十三、汇总报告我建议至少输出这些

```text
Evaluation Summary

Tasks:
15

Dev:
5

Held-out:
10


Overall Held-out Success:
x / 10


By Type:
Bug        x/x
Feature    x/x
Refactor   x/x
Maintenance x/x


Efficiency:
Median Duration
Max / P95 Duration

Median Tokens

Median Cost / Successful Task

Median Tool Calls

Mean Repair Attempts


Runtime:
Context Compactions

Model Retries

Resume Events

Safety Violations
```

没有发生：

```text
Safety Violation
```

也应该：

```text
0
```

明确显示。

---

# 八十四、Failure Analysis 比 Success Rate 更值得讲

面试官如果问：

```text
你的 Agent 成功率多少？
```

答：

```text
8/10 held-out
```

只是开头。

真正高价值的是：

> 剩下两个为什么失败？

例如：

```text
Failure 1:
Context Engine 没把 configuration adapter
召回 Top-5，Planner 从错误文件开始。

Failure 2:
Repair Loop 连续三次产生同类 Patch，
Failure Signature 没有触发 Replan。
```

然后：

```text
我把这两个 Failure
加入 Regression Corpus。
```

这会比：

```text
“模型不够聪明”
```

强很多。

---

# 八十五、如果面试官问：“为什么不直接跑 SWE-bench？”

你应该可以回答：

> SWE-bench 很有价值，我也参考了它的 Issue + Repository → Patch → hidden tests 评测范式，尤其是 FAIL_TO_PASS 与 PASS_TO_PASS 的设计。但我当前主要想验证的是自己的 Agent Harness，包括 Context Retrieval、Planning、Repair、Session Resume、Safety 和 Context Compaction，因此需要一套我能完全控制、能做模块 Ablation、能注入 Runtime Failure 的小型 Evaluation Suite。另外，OpenAI 对 SWE-bench Verified 的后续审计也说明，Benchmark 的 Issue Quality 和 Oracle Quality 本身会严重影响结果，所以我的第一阶段重点是建立一个规模较小但可人工验证、可复现的 Suite，而不是只追求一个外部榜单分数。

这是一个很成熟的回答。

---

# 八十六、如果面试官问：“15 个 Task 能证明什么？”

不要说：

```text
证明我的 Agent 泛化能力很强。
```

应该：

> 15 个 Task 是我的工程回归与模块验证 Suite，不足以宣称广泛的软件工程能力。它主要用于验证端到端 Runtime 是否工作、比较 Design Ablation、发现稳定 Failure Pattern，并形成持续 Regression Corpus。我把其中 5 个作为 Development Cases、10 个冻结为 Held-out Cases，避免完全针对同一任务集调优。后续可以接入更大公开 Benchmark 做外部验证。

这个回答非常严谨。

---

# 八十七、如果面试官问：“为什么 Agent 自己跑的测试不能算最终结果？”

你的回答应该是：

> Agent 内部测试属于 Execution Observation，它帮助 Repair Loop 决策，但不是最终独立 Oracle。Agent 在测试通过后仍可能继续修改代码，甚至可能错误选择测试或误读输出，所以正式 Evaluation 在 Agent Terminate 后冻结最终 Workspace，再由独立 Eval Harness 执行 hidden acceptance、regression 和 safety checks。也就是说 Agent 是 Actor，Eval Harness 是 Judge，两者职责分离。

这就是非常典型的：

# Evaluation Harness Thinking

---

# 八十八、如果面试官问：“你的 Success Rate 提高，到底是模型强了还是 Runtime 强了？”

这正是 Ablation 的意义。

你可以回答：

> 我固定 Model、Provider、Task、Budget 和 Tool Set，仅关闭某个 Runtime Component。例如 Plan Ablation 只去掉 Plan-first，Repair Ablation 只把 iterative repair 改为 single-shot。这样我可以观察 Success、Token、Latency、Repair Attempt 和 Tool Calls 的变化，从而估计 Runtime Component 的边际贡献，而不是把所有提升都归因于模型。

这就是你今天最需要掌握的实验思想。

---

# 八十九、Day 7 最终面试知识清单

你今天要能够真正解释：

**Evaluation 基础**：Model Eval 和 Agent/Harness Eval 有什么区别？为什么必须固定 Harness Config？Oracle 是什么？为什么 Agent 不能自己给自己打分？Acceptance 与 Regression 为什么都要有？

**Dataset 设计**：15 Task 怎么覆盖不同能力？为什么需要难度分层？为什么任务不能泄露正确文件？为什么需要固定 Base Commit？为什么需要 Hidden Tests？

**Eval Quality**：为什么 Test 本身可能是坏 Oracle？SWE-bench Verified 给了什么教训？为什么 Eval Dataset 也需要人工 Review 和 Versioning？

**实验方法**：Dev Set 和 Held-out Set 有什么区别？为什么反复调过的 Task 不能继续当正式 Held-out？Ablation 为什么必须控制变量？为什么单次 Ablation 不能过度解释？

**Metrics**：为什么只看 Success 不够？Median/P95 为什么重要？为什么 Cost per Successful Task 比平均 Cost 更有意义？First-pass Success 和 Repair Attempts 分别说明什么？Tool Calls 为什么不是越少越好？

**Failure Analysis**：Failed Task 和 Failure Case 有什么区别？Failure Database 为什么要保存 Trigger、Root Cause、Mitigation 和 Regression Test？如何从 Failure Cluster 决定下一阶段研发重点？

**README / Recruiting**：README 第一屏为什么应该先展示 Demo？为什么应公开失败和 Known Limitations？怎样把 Architecture、Evaluation、Ablation、Failure Cases 变成求职证据？

---

# 九十、Week 4 到今天终于形成完整闭环

现在整个 Single-Agent MVP 已经是：

```text
                       User
                        │
                        ▼
                codeteam run
                        │
                        ▼
                    TaskSpec
                        │
                        ▼
                      Plan
                        │
                        ▼
                Repository Context
                        │
                        ▼
                   AgentLoop
                        │
                        ▼
                     Patch
                        │
                        ▼
                 Verification
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
            PASS                FAILURE
              │                   │
              │                   ▼
              │             ErrorClassifier
              │                   │
              │             ┌─────┼─────┐
              │             ▼     ▼     ▼
              │           Retry Repair Replan
              │             │     │     │
              │             └─────┴─────┘
              │                   │
              └───────────────────┘
                        │
                        ▼
                     Session
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
        Resume       Compaction   Model Switch
                        │
                        ▼
                     Result
                        │
                        ▼
                 ┌─────────────┐
                 │ Eval Harness │
                 └──────┬──────┘
                        │
          ┌─────────────┼───────────────┐
          ▼             ▼               ▼
       Oracle        Metrics        Failure DB
          │             │               │
          └─────────────┼───────────────┘
                        ▼
                   README / Report
```

前 6 天你一直在回答：

```text
如何构建一个 Coding Agent？
```

Day 7 开始回答一个更加工业化的问题：

> **我怎么证明自己构建的 Agent 确实有效，而且知道它在哪些情况下无效？**

从求职角度，这一步非常关键。因为真正的 Agent Harness / Runtime 工程能力，不只是“我能让 LLM 调 Tool”，而是你能展示一条完整证据链：

```text
Architecture
        +
Implementation
        +
Tests
        +
Reproducible Eval
        +
Metrics
        +
Ablation
        +
Failure Analysis
        +
Known Limitations
```

`codeteam-single-agent` 到 Day 7 才真正从一个“能运行的 Demo”，变成一个**能够被测量、被比较、被质疑、被复现的 Agent Engineering 项目**。