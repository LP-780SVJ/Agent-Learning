# 第 4 周 Day 2：Test-Driven Repair Loop

今天开始把昨天的：

```text
Issue
→ TaskSpec
→ Plan
→ READY
```

真正推进到：

```text
Plan
→ 修改代码
→ 验证
→ 发现失败
→ 利用失败信息继续修
→ 再验证
```

也就是第一次让 CodeTeam 形成**闭环执行能力**。

今天最重要的认知不是“TDD 怎么写”，而是：

> **Coding Agent 不能把“生成 Patch”当成任务完成。Patch 只是一个候选解，Test / Build / Lint / Type Check 等外部系统给出的反馈，才决定它是否值得继续保留。**

OpenAI 现在公开描述 Codex 的长任务循环就是：

```text
Plan
→ Edit code
→ Run tests/build/lint
→ Observe results
→ Repair failures
→ Repeat
```

而且明确指出，这种循环的关键价值在于真实反馈、外部化状态以及根据结果持续纠偏。

---

# 一、今天到底解决什么问题

Day 1 以后，你已经有：

```text
TaskSpec
     ↓
Plan
     ↓
PlanStep
     ↓
READY
```

最简单的 Day 2 实现可能是：

```text
Plan Step
↓
LLM
↓
Patch
↓
结束
```

这实际上仍然只是：

> **Code Generation**

而不是：

> **Coding Agent**

因为 Runtime 根本不知道：

```text
Patch 对不对？

Bug 真修了吗？

有没有引入新 Bug？

测试是不是还能通过？

修改是不是把其他模块搞坏了？

如果错了，下一步怎么办？
```

今天要把它升级成：

```text
                 Candidate Patch
                       │
                       ▼
                  Verification
                       │
              ┌────────┴────────┐
              ▼                 ▼
            PASS               FAIL
              │                 │
              ▼                 ▼
         Regression          Diagnose
              │                 │
        ┌─────┴─────┐           ▼
        ▼           ▼       RepairAttempt
      PASS         FAIL          │
        │           │            ▼
        │           └──────→ New Patch
        │                        │
        └─────→ DONE             └──→ Verify again
```

OpenAI 2026 年公开的 Codex iterative repair 示例，甚至直接把这种模式概括为一个 closed-loop workflow：**产出 → 验证 → 把反馈用于下一轮修复**；其三个阶段就是 Review、Repair、Validate，而 Validation 的剩余问题会再次成为下一轮 Repair 输入。

---

# 二、今天真正对应的 Agent 能力

Day 2 主要证明：

```text
Agent Runtime
├── Feedback Loop
├── Retry / Repair Lifecycle
└── Stopping Condition

Tool Runtime
├── Test execution
├── Result normalization
└── Bounded verification

Evaluation
├── Test Oracle
├── Behavioral verification
└── Task success evidence

Agent Harness
├── Observation → Action
└── External feedback grounding
```

所以今天不是：

```text
“写一个 pytest wrapper”
```

而是在实现：

> **Agent 的闭环纠错机制。**

---

# 三、先区分传统 TDD 和今天的 Test-Driven Repair

传统软件工程里的 TDD 常写成：

```text
Red
↓
Green
↓
Refactor
```

今天 Coding Agent 更准确的名字其实是：

> **Verification-Driven Repair**

因为你面对的不一定只有 Unit Test。

反馈可能来自：

```text
pytest

lint

mypy

compiler

build

integration test

CLI output

HTTP response

golden file

behavioral invariant
```

因此今天真正的循环是：

```text
Observe current behavior
        ↓
Propose change
        ↓
Execute verifier
        ↓
Observe verifier result
        ↓
Repair
```

Aider 当前的公开实现就是非常直接的例子：它可以在每次 AI 修改代码之后自动运行 lint/test；测试命令返回非零退出码时，会把 stdout/stderr 中的错误作为反馈，并尝试继续修复。

---

# 四、最重要的概念：Test Failure ≠ Agent Failure

今天这句话一定要彻底理解：

```text
test failed
≠
agent failed
```

假设：

```text
Agent
→ Patch #1

pytest
→ FAILED
```

这不一定意味着：

```text
TaskStatus = FAILED
```

反而可能只是：

```text
Observation:

AssertionError:
expected retry_count == 2
actual retry_count == 1
```

Agent 得到了非常有价值的新信息：

```text
第一次修复方向可能正确，
但 retry 次数仍然不对。
```

于是：

```text
Failure
↓
Diagnosis
↓
Patch #2
```

所以 Coding Agent 中最好区分至少三个层级：

```text
Level 1
CommandResult

命令有没有正常运行？


Level 2
VerificationResult

代码有没有通过验证？


Level 3
TaskResult

整个任务有没有成功？
```

---

# 五、一个非常重要的三层模型

例如：

```bash
pytest tests/auth/test_timeout.py
```

执行结果：

```text
process successfully started
exit code = 1
```

对于 `CommandRunner`：

```text
Runner:
SUCCESSFULLY_EXECUTED
```

因为 Runner 正常启动和管理了 Process。

对于 Verification：

```text
Verification:
FAILED
```

因为：

```text
exit code != expected exit code
```

对于 Task：

```text
Task:
仍然 IMPLEMENTING / VERIFYING
```

因为还有 Repair Budget。

不要写成：

```text
exit code 1
→ CommandRunner failed
→ Task failed
```

这会让 Agent 根本没有自我修复能力。

---

# 六、工业实现：OpenAI Codex 为什么强调 Verification

OpenAI 当前最佳实践明确建议不要停在“让 Codex 修改代码”这一步，而是要求它在需要时编写测试、运行相关检查、确认结果、检查 lint/format/type check，并 Review Diff。官方明确说，Codex 可以自己完成这个循环，但前提是 Runtime/Prompt 必须给出什么叫“正确”。

这背后其实就是：

```text
Generation
≠
Correctness

Validation Evidence
→
Correctness confidence
```

---

# 七、Claude Code 也使用同样模式

Claude Code 当前公开的 Bug Fix 工作流建议给它：

```text
error
reproduction command
reproduction steps
```

然后进行修复。其测试工作流明确写的是：

```text
生成测试
→ 运行新测试
→ 修复失败
```

Refactor 工作流也强调小步、可测试地修改，并最终运行测试验证。

这说明：

> **现代 Coding Agent 的核心不是“模型是不是第一次就写对”，而是 Harness 能否把失败可靠地转成下一轮有用反馈。**

---

# 八、GitHub Copilot Cloud Agent 也是最终以验证收尾

GitHub 当前公开工作流中，Copilot 修复 Merge Conflict 后不会因为“冲突标记消失”就宣布结束，而是继续验证 build、tests 和 linter 都仍然通过，然后才请求用户 Review。

这就是今天非常值得学习的工业思想：

```text
Local fix
≠
Task success

Local fix
+
Verification
+
Regression
→
Task success evidence
```

---

# 九、理论 1：Reproduction

## 什么叫 Reproduction

Reproduction：

> **在修改之前，用确定的输入和验证手段重新观察到用户所描述的问题。**

例如 Issue：

```text
登录偶尔在后端响应慢时直接失败。
```

好的 Reproduction：

```bash
pytest tests/auth/test_timeout.py::test_retry_after_timeout
```

结果：

```text
FAILED

expected:
login succeeds

actual:
TimeoutError
```

此时你拥有：

```text
Before Fix Evidence
```

---

# 十、为什么 Reproduction 非常重要

假设 Agent 没复现，直接：

```text
修改代码
↓
pytest
↓
PASS
```

问题来了：

> 这个测试修改前是不是本来就 PASS？

如果本来就 PASS：

```text
PASS before
PASS after
```

它并不能证明：

```text
Bug fixed
```

真正强的 Bug Fix Evidence 是：

```text
Before:
FAIL

After:
PASS
```

因此：

```text
FAIL → PASS
```

比：

```text
Unknown → PASS
```

强得多。

---

# 十一、Reproduction 不是每个 Task 都一定存在

例如：

```text
给 CLI 增加 --verbose 参数
```

这是 Feature，不一定有：

```text
bug reproduction
```

这时可以：

```text
先新增一个 failing acceptance test
```

例如：

```text
codeteam --verbose
```

目前：

```text
unrecognized argument
```

然后修改以后：

```text
works
```

所以更通用的抽象应该是：

```text
Baseline Verification
```

Bug：

```text
reproduce existing failure
```

Feature：

```text
establish missing behavior
```

---

# 十二、理论 2：Test Oracle

这是今天最值得认真学习的概念之一。

## Oracle 是什么

Test Oracle：

> **一个用来判断当前系统行为“正确还是错误”的外部判定规则。**

例如：

```python
assert login() == SUCCESS
```

这里：

```text
expected == SUCCESS
```

就是 Oracle。

---

# 十三、为什么 Agent 特别需要 Oracle

LLM 自己生成 Patch 后很容易说：

```text
“修改完成，应该能够解决问题。”
```

但这只是：

```text
Model Self-assessment
```

不是可信 Oracle。

更可靠：

```text
pytest
exit 0
```

或者：

```text
HTTP response == expected
```

或者：

```text
output == golden file
```

也就是：

```text
Agent proposal
```

应该被：

```text
External verifier
```

判断。

OpenAI 的 iterative repair 示例也特别强调这个模式只在输出能够用**可信反馈**进行测量时成立。

---

# 十四、常见 Oracle 类型

Coding Agent 以后至少会遇到：

### 1. Existing Unit Test

```text
pytest test_login.py
```

---

### 2. Regression Test

为这个 Bug 新增：

```text
test_timeout_retry
```

---

### 3. Build Oracle

```text
cargo build
```

要求：

```text
exit code = 0
```

---

### 4. Static Analysis

```text
ruff
mypy
eslint
```

---

### 5. Behavioral Oracle

例如：

```text
run CLI

expect:
stdout contains "success"
```

---

### 6. Invariant Oracle

例如：

```text
Main Worktree hash unchanged
```

这种也是验证。

---

# 十五、Oracle ≠ Test Command

例如：

```bash
pytest test_login.py
```

是：

```text
Verification Mechanism
```

真正 Oracle 是：

```text
pytest exit code == 0
```

以及其中 Assertions 所定义的行为。

再比如：

```bash
python app.py
```

如果只是运行：

```text
无 Assertion
```

那 Runtime 很难知道：

```text
输出是正确还是错误
```

所以：

> **能执行 ≠ 能验证。**

---

# 十六、一个错误 Oracle 比没有 Oracle 更危险

例如 Bug：

```text
用户登录失败
```

Agent 写了 Test：

```python
assert login() is None
```

然后：

```text
PASS
```

说明：

```text
Test 跟错误实现达成了一致
```

而不是：

```text
Bug 修好了。
```

这也是今天 Failure Case：

```text
测试本身错误
```

为什么非常危险。

---

# 十七、理论 3：Targeted Test

Targeted Test：

> **尽可能直接验证当前修改所针对行为的最小测试集合。**

例如修改：

```text
auth/client.py
```

Bug：

```text
timeout retry
```

Target：

```bash
pytest \
  tests/auth/test_timeout.py::test_retry
```

而不是一上来：

```bash
pytest
```

---

# 十八、Targeted Test 最大优势：反馈快

假设：

```text
Target Test
1 秒

Full Suite
4 分钟
```

Repair Loop：

```text
Patch #1 → FAIL
Patch #2 → FAIL
Patch #3 → PASS
```

如果每一次：

```text
Full Suite
```

需要：

```text
12 分钟
```

如果每次 Target：

```text
3 秒
```

那么反馈速度完全不同。

所以：

> **Targeted Test 是 Agent Repair Loop 的低延迟 Feedback Channel。**

---

# 十九、Targeted Test 还有第二个价值：反馈更聚焦

Full Test：

```text
32 failures
```

可能包括：

```text
无关 flaky test
platform error
integration environment
```

Target Test：

```text
test_timeout_retry FAILED
```

Diagnosis 更容易：

```text
这个 Patch 没解决当前行为。
```

---

# 二十、但 Targeted Test 有致命弱点

假设：

```text
target:
PASS
```

但修改：

```text
auth.py
```

同时破坏：

```text
registration
refresh token
logout
```

Target Test 看不到。

所以：

```text
Target PASS
≠
Task DONE
```

---

# 二十一、理论 4：Regression Test

Regression Test 的目标：

> **证明你的新修复没有破坏原来已经正确的行为。**

所以推荐验证结构：

```text
                  Patch
                    │
                    ▼
             Targeted Test
                    │
              ┌─────┴─────┐
              ▼           ▼
            FAIL         PASS
              │           │
          Repair          ▼
                   Related Regression
                          │
                    ┌─────┴─────┐
                    ▼           ▼
                  FAIL         PASS
                    │           │
                 Repair         ▼
                         Full Regression
                           where needed
```

---

# 二十二、Related Regression 和 Full Regression 也值得分开

例如：

```text
整个 Repository:
10000 tests
```

修改：

```text
authentication module
```

可以：

```text
Target:
1 test

Related:
tests/auth/
200 tests

Full:
10000 tests
```

最终：

```text
1
↓
200
↓
10000
```

形成由快到慢的验证漏斗。

---

# 二十三、这其实是一种 Verification Escalation

可以把它理解成：

```text
Level 1
Fast / narrow

Level 2
Medium / related

Level 3
Slow / broad
```

代码越接近：

```text
Task completion
```

验证范围越大。

这样既：

```text
保持 Repair Loop 快
```

又：

```text
降低 Regression 风险
```

---

# 二十四、今天 Design Decision 的核心就在这里

方案 A：

```text
Patch
↓
Full Test Suite
↓
Patch
↓
Full Test Suite
↓
Patch
↓
Full Test Suite
```

优点：

```text
每一步都有最宽验证
```

缺点：

```text
慢

贵

反馈噪声多
```

---

# 二十五、方案 B

```text
Patch
↓
Target
↓
Related Regression
↓
Full where necessary
```

优点：

```text
快速反馈
更聚焦
降低迭代成本
```

缺点：

```text
Target 选择错误可能漏掉回归

需要 Test Selection 策略
```

今天推荐：

```text
B
```

但要明确：

> **这是一个工程假设，后面应通过 Benchmark / Ablation 支撑，而不是现在宣布“绝对更优”。**

---

# 二十六、理论 5：Verification

Verification 是一个比 Test 更宽的概念。

可以理解：

```text
Verification
=
执行一个可信检查，
获得结构化 Evidence，
判断当前候选状态是否满足某个条件。
```

因此：

```text
pytest
mypy
ruff
build
CLI smoke test
```

都可以是 Verification。

---

# 二十七、今天推荐正式建立 Verification Layer

以后不要让 RepairLoop 自己：

```python
subprocess.run(...)
```

更不要绕过你 Week 3 的安全链。

应该：

```text
RepairLoop
    │
    ▼
VerificationService
    │
    ▼
SafeExecutor
    │
    ▼
Policy / Sandbox / Runner
```

为什么？

因为：

```text
pytest
```

本质上执行的是：

```text
Repository Code
```

它同样可能：

```text
启动进程
写文件
访问网络
```

所以 Test Runner 也必须受：

```text
CommandPolicy
Sandbox
CommandRunner
```

约束。

---

# 二十八、`VerificationRequest`

建议第一版模型大致是：

```python
class VerificationRequest(BaseModel):
    verification_id: str

    task_id: str
    plan_step_id: str | None

    kind: VerificationKind

    argv: tuple[str, ...]
    cwd: str

    expected_exit_codes: tuple[int, ...] = (0,)

    timeout_seconds: float

    purpose: str
```

其中：

```text
argv
```

继续保持之前的结构化 argv，而不是 Shell String。

---

# 二十九、推荐 `VerificationKind`

例如：

```python
class VerificationKind(str, Enum):
    REPRODUCTION = "reproduction"

    TARGETED_TEST = "targeted_test"

    RELATED_REGRESSION = (
        "related_regression"
    )

    FULL_REGRESSION = (
        "full_regression"
    )

    BUILD = "build"

    LINT = "lint"

    TYPECHECK = "typecheck"
```

为什么值得分类？

因为：

```text
targeted test fail
```

和：

```text
full regression fail
```

Runtime 的语义不同。

---

# 三十、`VerificationStatus`

建议不要只有：

```text
PASS
FAIL
```

第一版至少：

```python
class VerificationStatus(str, Enum):
    PASSED = "passed"

    FAILED = "failed"

    TIMED_OUT = "timed_out"

    START_FAILED = "start_failed"

    BLOCKED = "blocked"

    INCONCLUSIVE = "inconclusive"
```

---

# 三十一、为什么 `TIMED_OUT` 不能算普通 FAILED

例如：

```text
pytest
```

跑了：

```text
60 s
```

被 Runtime 杀掉。

你只知道：

```text
它没有在要求时间内完成。
```

但不知道：

```text
Assertions 会不会通过。
```

所以：

```text
TIMED_OUT
```

和：

```text
FAILED
```

必须分开。

---

# 三十二、为什么 `START_FAILED` 也不同

例如：

```text
pytest
```

根本不存在：

```text
FileNotFoundError
```

这是：

```text
Verification Environment Error
```

而不是：

```text
Code Behavior Failure
```

Agent 不应该看到：

```text
test failed
```

然后开始乱改业务代码。

正确是：

```text
START_FAILED
↓
Environment / Tool Error
```

这会和明天的 Error Classification 直接连接。

---

# 三十三、`BLOCKED`

例如：

```text
Verification command
需要网络

Policy:
REQUIRE_APPROVAL

用户拒绝
```

那：

```text
VerificationStatus
=
BLOCKED
```

不是：

```text
FAILED
```

因为：

```text
代码还没有被真正验证。
```

---

# 三十四、`INCONCLUSIVE` 是什么

例如一个 Test：

```text
第一次 PASS
第二次 FAIL
第三次 PASS
```

可能是：

```text
Flaky
```

这时更合理：

```text
INCONCLUSIVE
```

而不是让 Agent继续反复修改代码。

---

# 三十五、一个非常重要的设计：Output Truncated ≠ Test Failed

Day 5 你已经有：

```text
Output Limit
```

假设：

```text
pytest
输出 20MB

exit_code=0

stdout_truncated=True
```

Verification 应该仍可能是：

```text
PASSED
```

因为：

```text
Oracle:
exit code = 0
```

已经满足。

所以：

```text
truncated
```

应该是：

```text
Result Metadata
```

不是：

```text
VerificationStatus
```

---

# 三十六、推荐 `VerificationResult`

概念上：

```python
class VerificationResult(BaseModel):
    verification_id: str

    status: VerificationStatus

    exit_code: int | None

    duration_ms: float

    stdout: str
    stderr: str

    stdout_truncated: bool
    stderr_truncated: bool

    failure_signature: str | None

    summary: str
```

这里有一个今天很重要的新字段：

```text
failure_signature
```

---

# 三十七、Failure Signature 是什么

例如 Test Output：

```text
AssertionError:
expected retry_count == 2
actual retry_count == 1
```

你可以提取一个稳定签名：

```text
test_timeout_retry
+
AssertionError
+
expected 2 actual 1
```

不一定做复杂哈希。

第一版甚至：

```text
test name
+
exception type
```

就够。

---

# 三十八、为什么 Failure Signature 很重要

因为 RepairLoop 需要识别：

```text
Patch #1
→ same failure

Patch #2
→ same failure

Patch #3
→ same failure
```

这意味着：

```text
没有进展
```

而不是：

```text
“继续多修几次总会好。”
```

---

# 三十九、理论 6：Repair Attempt

一次 Repair Attempt 不应该只理解：

```text
LLM 又生成一次 Patch
```

它应该成为一个 Runtime Entity。

例如：

```text
Attempt #2

Input:
previous failure

Diagnosis:
retry_count configured at wrong layer

Patch:
sha256:...

Changed:
src/http/client.py

Verification:
target_test_003

Outcome:
FAILED
```

---

# 四十、为什么 RepairAttempt 应该被记录

以后你要回答：

```text
这个 Task 为什么用了 4 次修复？

第 2 次做了什么？

为什么第 3 次换了文件？

它是不是一直重复同样错误？
```

如果只有：

```text
conversation messages
```

很难分析。

如果有：

```text
RepairAttempt
```

就可以做：

```text
Evaluation
Failure Analysis
Resume
Benchmark
```

---

# 四十一、推荐 `RepairAttempt`

例如：

```python
class RepairAttempt(BaseModel):
    attempt_no: int

    task_id: str
    plan_step_id: str

    checkpoint_id: str | None

    failure_signature: str | None

    diagnosis_summary: str

    patch_hash: str | None

    changed_files: tuple[str, ...]

    verification_ids: tuple[str, ...]

    outcome: RepairOutcome
```

---

# 四十二、RepairAttempt 为什么要关联 Checkpoint

假设：

```text
Attempt 1
修改 A

Attempt 2
继续修改 A+B

Attempt 3
完全走错方向
```

你可能决定：

```text
rollback Attempt 2 前
```

所以：

```text
RepairAttempt
↔
Checkpoint
```

关系很有价值。

今天第一版不用把复杂 rollback strategy 全自动化，但至少应该保存：

```text
attempt_before_checkpoint
```

---

# 四十三、一个重要设计问题：每次失败都 Rollback 吗？

答案：

> 不一定。

例如：

```text
Patch #1
```

解决了 80%，Test：

```text
expected retry_count 2
actual 1
```

这个状态非常适合：

```text
在 Patch #1 上增量修复
```

没必要 Rollback。

---

# 四十四、什么时候适合 Rollback

例如：

```text
Patch #2
```

导致：

```text
20 个原本通过的 auth tests
全部失败
```

或者 Agent 判断：

```text
修改方向基于错误假设
```

这时可以：

```text
rollback last_good_checkpoint
↓
换策略
```

所以：

```text
Test Failure
≠
Automatic Rollback
```

更合理：

```text
Failure
↓
Diagnosis
↓
CONTINUE
or
ROLLBACK
or
REPLAN
```

这是很重要的 Runtime 思想。

---

# 四十五、理论 7：Diagnosis

今天的：

```text
Diagnose
```

不是要求保存模型私有 Chain-of-Thought。

Runtime 要的是一个简洁、外显：

```text
Diagnosis Summary
```

例如：

```text
Target test still fails because
retry_count is decremented before
the retry loop rather than after
the failed request.
```

这是：

```text
Actionable explanation
```

不是模型所有内部推理步骤。

---

# 四十六、为什么 Diagnosis 不能直接把完整 Test Log 塞回模型

假设：

```text
pytest output
5MB
```

直接：

```text
全部塞 Context
```

会：

```text
Token 爆炸

关键信息被淹没

Context 污染
```

建议：

```text
VerificationResult
↓
FailureExtractor
↓
RepairContext
```

---

# 四十七、RepairContext 应该包含什么

例如：

```text
Current Goal

Current Plan Step

Changed Files

Current Diff

Target Test

Failure Summary

Failure Tail

Relevant Stack Trace

Previous Attempt Summary

Important Constraints
```

而不是：

```text
整个 Session
+
5MB stdout
```

这也是 Context Engineering。

---

# 四十八、推荐 Repair Pipeline

完整一点：

```text
                   Current Workspace
                         │
                         ▼
                  Verification
                         │
               ┌─────────┴──────────┐
               ▼                    ▼
             PASS                  FAIL
               │                    │
               │                    ▼
               │           Failure Normalizer
               │                    │
               │                    ▼
               │            Failure Signature
               │                    │
               │                    ▼
               │             Repair Context
               │                    │
               │                    ▼
               │                  Agent
               │                    │
               │                    ▼
               │              Patch Proposal
               │                    │
               │                    ▼
               │            PatchValidator
               │                    │
               │                    ▼
               │             GitWorkspace
               │                    │
               └────────────────────┘
```

然后重新 Verification。

---

# 四十九、`RepairLoop` 应该负责什么

它负责：

```text
组织验证和修复循环
```

不负责：

```text
subprocess

git apply

model HTTP

sandbox
```

具体应该依赖：

```text
VerificationService

RepairAgent / AgentLoop

CheckpointManager

PatchRuntime
```

---

# 五十、第一版 RepairLoop

可以理解成：

```text
verify
│
├── PASS
│     → success
│
└── FAIL
      │
      ▼
attempt < max?
      │
   ┌──┴──┐
   │     │
  no    yes
   │     │
   ▼     ▼
 STOP  create repair context
         │
         ▼
       agent
         │
         ▼
       patch
         │
         ▼
       apply
         │
         └────→ verify
```

---

# 五十一、`max_repair_attempts`

这是今天最简单但最重要的 Stopping Condition。

例如：

```python
max_repair_attempts = 3
```

含义最好明确：

```text
Initial Patch
+
最多 3 次 Repair
```

还是：

```text
总共最多 3 个 Patch
```

必须定义清楚。

我更建议：

```text
initial candidate
+
max_repair_attempts additional repairs
```

语义更清晰。

---

# 五十二、为什么必须限制 Attempt

否则：

```text
FAIL
→ Repair
→ FAIL
→ Repair
→ FAIL
→ Repair
...
```

会导致：

```text
Token 无限

Cost 无限

时间无限

Diff 不断膨胀

代码越来越乱
```

Agent Harness 的职责之一就是：

> **约束模型的自主循环。**

---

# 五十三、真正的 Stopping Condition 不应只有 Attempt Count

以后至少应该逐渐支持：

### 1. Success

```text
Required verification passed
```

---

### 2. Repair Budget Exhausted

```text
attempt >= max
```

---

### 3. Wall-clock Budget

例如：

```text
20 min
```

---

### 4. Token / Cost Budget

例如：

```text
token limit reached
```

---

### 5. Repeated Failure

例如：

```text
same failure_signature
连续 3 次
```

---

### 6. No Progress

例如：

```text
Attempt 1:
same diff

Attempt 2:
same diff

Attempt 3:
same diff
```

---

### 7. Security Block

```text
Policy DENY
```

不能 Repair 绕过。

---

### 8. Environment Failure

```text
pytest executable missing
```

不能靠改业务代码解决。

---

### 9. User Interrupt

```text
Ctrl+C
```

进入后续：

```text
PAUSED
```

---

# 五十四、这一点和 OpenAI 长任务实践高度一致

OpenAI 当前对长时间 Codex Task 的公开实践强调，Agent 不应只是不断生成代码，而应在每个 milestone 进行 validation；失败时先修复，不要继续扩大工作范围。

也就是说：

```text
Validation
```

不仅用来：

```text
最终验收
```

还用来：

```text
控制下一步是否允许继续
```

---

# 五十五、Target PASS + Regression FAIL 怎么处理

这是你今天明确要求的测试。

例如：

```text
Target:
test_timeout_retry
PASS
```

但是：

```text
Related regression:
15 passed
2 failed
```

Task：

```text
绝对不能 COMPLETED
```

而应该：

```text
Regression Failure
↓
Repair Context
↓
继续 Repair
```

这非常重要，因为：

```text
Bug fixed
```

和：

```text
Software still correct
```

是两件事。

---

# 五十六、这叫局部正确 vs 全局正确

可以理解：

```text
Target Test
证明：

“你修的那个行为对了。”


Regression
证明：

“你没有把附近其他行为弄坏。”
```

两者缺一不可。

---

# 五十七、但 Regression Failure 也不一定都是你的 Patch 导致的

例如全量测试本来就有：

```text
3 个已知 flaky test
```

你修改之前：

```text
它们也失败
```

这时修改以后：

```text
还是失败
```

不能直接说：

```text
Agent 引入 regression
```

所以工业上非常重要的是：

```text
Baseline
```

---

# 五十八、理想情况下记录 Pre-change Baseline

例如：

```text
Before Patch:

Target:
FAIL

Related Regression:
100 PASS
```

After：

```text
Target:
PASS

Regression:
98 PASS
2 FAIL
```

你可以明确：

```text
introduced regression
```

但如果 Before：

```text
98 PASS
2 FAIL
```

After：

```text
98 PASS
2 FAIL
```

那是：

```text
pre-existing failure
```

这会让 Evaluation 更可靠。

---

# 五十九、第一版不需要每次跑完整 Baseline

大型 Repo 全量 baseline 很贵。

可以先：

```text
Target reproduction before fix
```

并对关键 Related Test 做 baseline。

后续再增加：

```text
Known baseline failures
```

缓存。

---

# 六十、今天测试 1：第一次 Patch 成功

流程：

```text
Initial candidate
↓
Target Test
↓
PASS
↓
Related Regression
↓
PASS
```

预期：

```text
RepairAttempt count
=
0
```

最终：

```text
Verification outcome:
SUCCESS
```

不要强行：

```text
明明第一次成功
也让 LLM 再“优化一次”。
```

---

# 六十一、测试 2：第一次失败，第二次成功

```text
Patch #1
↓
Target FAILED
↓
RepairAttempt #1
↓
Patch #2
↓
Target PASS
↓
Regression PASS
```

断言：

```text
repair_attempts == 1
```

并且：

```text
第一次 failure
确实进入第二次 Repair Context
```

这比只检查最后 PASS 更重要。

---

# 六十二、测试 3：连续失败达到上限

例如：

```text
initial
FAIL

repair 1
FAIL

repair 2
FAIL

repair 3
FAIL
```

如果：

```text
max_repair_attempts=3
```

必须停止。

断言：

```text
agent/model
不再被调用第 4 次修复
```

以及：

```text
final status
=
REPAIR_EXHAUSTED
```

或类似明确结果。

---

# 六十三、测试 4：Target PASS / Regression FAIL

必须：

```text
Task not completed
```

并产生：

```text
RepairAttempt
```

针对：

```text
Regression Failure
```

而不是重新修 Target Test。

---

# 六十四、测试 5：测试命令不存在

例如：

```text
argv=
("definitely-no-pytest",)
```

应该：

```text
VerificationStatus.START_FAILED
```

不应该：

```text
RepairAgent
收到 “tests failed”
→ 修改代码
```

这个 Case 是为了防止：

> **Environment Problem 被误诊成 Code Problem。**

---

# 六十五、测试 6：Test Timeout

例如：

```text
test process
sleep forever
```

Day 5 的 CommandRunner 应该：

```text
timeout
→ kill process group
```

然后 Verification：

```text
TIMED_OUT
```

今天 RepairLoop 怎么处理？

第一版建议：

```text
不要默认修改代码
```

因为它可能是：

```text
Code Hang
```

也可能是：

```text
Test infrastructure slow
```

今天先记录：

```text
TIMED_OUT
```

明天 ErrorClassifier 再决定：

```text
repair?
retry?
environment?
```

---

# 六十六、测试 7：Output Truncated

运行：

```text
产生巨大 stdout/stderr
```

CommandRunner：

```text
truncated=True
```

RepairLoop 应该能够：

```text
不崩溃

仍读取 head/tail

仍根据 exit code 判断 verification
```

比如：

```text
exit 1
stderr truncated
```

仍是：

```text
FAILED
```

只是：

```text
failure evidence incomplete
```

---

# 六十七、我建议额外增加 8 个测试

## T8：Verification BLOCKED

例如：

```text
Policy denied
```

必须：

```text
Repair Agent calls = 0
```

---

## T9：Regression PASS 但 Target FAIL

依然：

```text
FAIL
```

---

## T10：同 Failure Signature 连续出现

记录：

```text
repeat_count
```

以后支持 No-progress Stop。

---

## T11：Repair Agent 返回 No-op Patch

不能：

```text
apply empty patch
→ test
→ 无限循环
```

---

## T12：Repair Patch 无法 Apply

这是：

```text
PATCH FAILURE
```

不是：

```text
TEST FAILURE
```

以后交给 Day 3 ErrorClassifier。

---

## T13：Attempt Checkpoint 正确关联

确保每次 attempt 有：

```text
checkpoint_id
```

---

## T14：Target PASS 后 Regression 才执行

Target FAIL：

```text
RegressionRunner calls = 0
```

避免浪费。

---

## T15：达到 Attempt Limit 不再调用 Model

这是 Stopping Condition 的强不变量。

---

# 六十八、今天的推荐数据模型关系

整体：

```text
Task
 │
 ▼
PlanStep
 │
 ▼
RepairLoop
 │
 ├── VerificationRequest
 │        │
 │        ▼
 │   VerificationResult
 │
 ├── RepairAttempt
 │        │
 │        ├── failure
 │        ├── diagnosis
 │        ├── patch
 │        └── checkpoint
 │
 └── Final Verification
```

---

# 六十九、VerificationRequest 和 CommandRequest 不要合并

虽然它们都执行命令。

但：

```text
CommandRequest
```

描述：

```text
我要执行什么 OS command？
```

而：

```text
VerificationRequest
```

描述：

```text
我为什么要执行这个检查，
它在 Task 中代表什么验证语义？
```

可以：

```text
VerificationRequest
        ↓
convert
        ↓
CommandRequest
```

而不是：

```text
两个类型完全合并
```

---

# 七十、例如

```text
VerificationRequest

kind:
TARGETED_TEST

purpose:
verify timeout retry behavior

expected_exit_codes:
[0]

argv:
pytest ...
```

转换为：

```text
CommandRequest

argv:
pytest ...
cwd:
task worktree
```

然后进入：

```text
SafeExecutor
```

最终 CommandResult 再转换：

```text
VerificationResult
```

这是非常清晰的 Layering。

---

# 七十一、建议增加 `VerificationService`

关系：

```text
RepairLoop
    │
    ▼
VerificationService
    │
    ├── builds CommandRequest
    │
    ├── SafeExecutor
    │
    ├── interprets exit code
    │
    └── creates VerificationResult
```

这样 RepairLoop 不需要理解：

```text
SIGTERM
Docker
stdout limit
```

那些都是 Week 3 Runtime 已经解决的问题。

---

# 七十二、今天 `RepairLoop` 的正确职责

它只应该关心：

```text
What verification should run?

Did it pass?

If failed:
Can we repair?

How many attempts remain?

What feedback should go to next attempt?

When should we stop?
```

而不是：

```text
How to run subprocess?
```

---

# 七十三、工业案例：Aider 具体怎么发挥作用

Aider 当前允许配置：

```text
--test-cmd
--auto-test
```

AI 修改之后自动执行测试；Test Command 输出错误到 stdout/stderr 并返回非零时，Aider 会尝试修复这些错误。

抽象出来就是：

```text
AI Edit
   ↓
Test Process
   ↓
Exit Code
   │
 ┌─┴────┐
 │      │
0     non-zero
 │      │
done    ▼
     Failure Output
          │
          ▼
         LLM
          │
          ▼
       New Edit
```

你今天是在把这个思想：

```text
工程化
结构化
可评测化
```

---

# 七十四、你的版本应该比简单 Aider Loop 多什么

你的 CodeTeam 至少应该有：

```text
VerificationRequest

VerificationResult

RepairAttempt

Attempt budget

Checkpoint linkage

Target / Regression distinction

Failure classification hook

Metrics

Event log
```

也就是说不是：

```text
test command fails
→ throw output back to LLM
```

而是：

```text
Test Result
→ Runtime State
→ Repair Decision
```

---

# 七十五、工业案例：OpenAI Codex iterative repair

OpenAI 2026 年公开的 iterative repair cookbook 明确采用：

```text
Review
→ Repair
→ Validate
```

Validation 产生的问题成为下一轮 Repair 的输入。

而在 long-horizon Codex 实践中，OpenAI 进一步把：

```text
Plan
Edit
Tests/build/lint
Observe
Repair
Repeat
```

作为完整 Harness Loop，并强调每个 milestone 都进行 tests、lint、typecheck 等验证。

这与你现在要实现的：

```text
RepairLoop
```

高度一致。

---

# 七十六、今天的 Event Log 应该开始记录什么

建议：

```text
verification.started

verification.completed

verification.failed

verification.timed_out

repair.started

repair.patch_proposed

repair.patch_applied

repair.completed

repair.exhausted
```

例如：

```text
repair.started

task_id
plan_step_id
attempt=2

failure_signature
checkpoint_id
```

以后 Evaluation 很方便。

---

# 七十七、推荐的 Verification Event

至少：

```text
verification_id

kind

task_id

command

duration_ms

exit_code

status

output_truncated

failure_signature
```

注意 Command 要：

```text
sanitized
```

不要把可能的 Secret 直接写日志。

---

# 七十八、Plan Step 和 RepairLoop 怎么关联

昨天有：

```text
PlanStep:

P3
Implement timeout fix
```

执行：

```text
P3
RUNNING
```

然后：

```text
Patch
→ FAIL
→ repair
→ PASS
```

此时：

```text
P3
COMPLETED
```

然后：

```text
P4
Run regression
```

---

# 七十九、不要因为一次 Test FAIL 就把 PlanStep 标 FAILED

例如：

```text
P3
RUNNING

Patch #1
Test FAILED
```

P3 仍然：

```text
RUNNING
```

因为：

```text
RepairLoop still active
```

只有：

```text
repair budget exhausted
```

才可能：

```text
P3 → FAILED
```

这和前面：

```text
Test Failure
≠
Task Failure
```

是同一个思想。

---

# 八十、Stopping Condition：今天建议先实现 4 个

不要第一天 RepairLoop 就做十几种复杂策略。

第一版：

```text
S1
Required verification PASS


S2
max_repair_attempts exhausted


S3
unrecoverable execution error


S4
user/runtime interruption
```

后面再扩：

```text
same failure repeatedly

no-progress

token budget

cost budget
```

---

# 八十一、为什么 Same Failure Stop 很值得后续增加

例如：

```text
Attempt 1
AssertionError X

Attempt 2
AssertionError X

Attempt 3
AssertionError X
```

且：

```text
Patch hash
几乎一样
```

这通常意味着：

```text
Agent 没理解问题
```

继续 Attempt 4/5：

```text
大概率只是在烧 Token
```

以后可以：

```text
trigger REPLAN
```

而不是直接 FAILED。

---

# 八十二、Replan 和 Repair 仍然要区分

Repair：

```text
计划方向仍然正确，
实现细节有问题。
```

例如：

```text
正确文件找到了
逻辑差一点。
```

---

Replan：

```text
计划的基本假设错了。
```

例如：

```text
以为 timeout 在 auth.py

实际 timeout 在 proxy layer。
```

所以：

```text
Test Failure
↓
Diagnosis
↓
Repair
or
Replan
```

Day 2 可以只留接口，

Day 3 ErrorClassifier 再正式决定。

---

# 八十三、Design Decision：为什么推荐 Target → Related → Full

正式可以记录：

```text
DD-W4-D2-01

Title:
Tiered Verification Strategy
```

Problem：

```text
How should CodeTeam verify
each candidate repair?
```

Alternatives：

```text
A:
Full suite after every patch

B:
Targeted
→ related regression
→ full suite where required
```

Decision：

```text
B
```

---

# 八十四、选择 B 的理由

### 1. Feedback Latency

Repair 的价值高度依赖：

```text
快速获得结果
```

---

### 2. Diagnostic Precision

一个明确 Target Failure：

```text
更容易生成 RepairContext
```

---

### 3. Resource Efficiency

减少：

```text
每个 Patch
都全量跑测试
```

---

### 4. Regression Safety

最后仍然：

```text
逐级扩大验证范围
```

所以不是：

```text
只跑 Target
```

---

# 八十五、Trade-off

最大风险：

```text
Target Selection 错
```

例如 Agent 认为：

```text
test_auth
```

足够。

但真正受影响：

```text
test_sessions
```

没被选择。

所以后续可以发展：

```text
Changed Files
+
Import Graph
+
Test Mapping
```

选择 Related Regression。

这正好又可以复用 Week 2：

```text
ImportGraph
SymbolIndex
```

---

# 八十六、这是一个很漂亮的跨模块连接

以后：

```text
Patch changes:

src/auth/client.py
```

Context Engine 已有：

```text
dependents_of(client.py)

references

related test files
```

就可以生成：

```text
Related Tests
```

也就是说 Week 2 不只用于：

```text
给 LLM 找代码
```

还可以用于：

```text
Test Selection
```

这是非常值得你后面实现的方向。

---

# 八十七、今天 Benchmark：平均 Repair Attempts

定义要明确。

建议：

```text
Mean Repair Attempts per Task
```

并同时报告：

```text
successful tasks only

all tasks
```

因为如果一个任务：

```text
失败到上限 3 次
```

也应该计入总体。

---

# 八十八、为什么仅平均值还不够

以后最好记录：

```text
Median

P95

Max
```

因为可能：

```text
80% 任务 0 次 repair

20% 任务 3 次 repair
```

平均：

```text
0.6
```

看不出尾部问题。

Day 2 至少把 Raw Data 保存下来。

---

# 八十九、Benchmark：Target Test Latency

记录：

```text
target_verification_ms
```

之后统计：

```text
P50
P95
```

它直接决定：

```text
Repair Loop
有多快。
```

---

# 九十、Benchmark：Total Verification Latency

定义：

```text
所有：

Target
+
Related Regression
+
Full Regression
```

耗时之和。

例如：

```text
Target:
1s × 3

Related:
20s

Full:
180s

Total:
203s
```

这比：

```text
Agent 总耗时
```

更能看出 Verification 占比。

---

# 九十一、Benchmark：Tool Calls

记录：

```text
search
read
patch
test
git
```

总 Tool Calls。

RepairLoop 开启后：

```text
Tool Calls
```

一定可能增加。

后面 Ablation 要回答：

> 增加这些 Tool Calls 是否换来更高 Success？

---

# 九十二、我建议额外增加 4 个指标

虽然原任务没有要求，但非常有价值。

### 1. Task Success Rate

最终核心。

---

### 2. First-Pass Success Rate

```text
无需 repair
就成功的任务比例。
```

它可以衡量初始 Patch 质量。

---

### 3. Regression Failure Rate After Target Pass

例如：

```text
Target PASS
但 Regression FAIL
```

发生多少？

这个指标会告诉你：

```text
Targeted verification
到底漏多少局部回归。
```

---

### 4. Time to First Green

从：

```text
首次 Patch
```

到：

```text
Target 第一次 PASS
```

耗时。

非常能反映 Repair Loop 效率。

---

# 九十三、Benchmark 表建议

以后真实运行：

| Task | First Pass | Repairs | Target ms | Verify Total ms | Tool Calls | Success |
|---|---:|---:|---:|---:|---:|---:|
| T01 | | | | | | |
| T02 | | | | | | |
| ... | | | | | | |

现在不要预填结果。

---

# 九十四、Ablation：Repair Loop vs Single-shot

这是 Week 4 非常关键的实验。

## Group A

```text
Single-shot
```

流程：

```text
Issue
→ Plan
→ one Patch
→ Verification
→ stop
```

即使失败：

```text
不 repair
```

---

## Group B

```text
Repair Loop
```

流程：

```text
Issue
→ Plan
→ Patch
→ Verification
→ Repair
→ Verification
```

例如：

```text
max_repair_attempts=3
```

---

# 九十五、Ablation 核心指标

最重要：

```text
Task Success Rate
```

其次：

```text
Tokens

Cost

Wall Time

Tool Calls

Attempts
```

你最终可能发现：

```text
Repair Loop
Success ↑

但：
Cost ↑
Latency ↑
```

这才是真实 Engineering Trade-off。

---

# 九十六、Ablation 最大的实验陷阱：计算预算不公平

假设：

```text
Single-shot:
只能调用模型一次

Repair Loop:
最多调用四次
```

最后 Repair Loop 更强，很可能部分原因只是：

```text
它获得更多 Model Compute。
```

所以更严格可以做两个实验。

### Experiment A：真实产品设置

```text
Single-shot:
1 attempt

Repair:
1 + 3 repairs
```

回答：

```text
实际产品中哪个更成功？
```

---

### Experiment B：近似等预算

例如控制：

```text
总 Token Budget
```

接近。

回答：

```text
在相似资源预算下，
闭环 Feedback 本身有没有价值？
```

第二个实验会更有研究味道。

---

# 九十七、Failure Case 1：测试本身错误

这是今天最危险的问题之一。

场景：

```text
User behavior:
retry 2 times
```

但 Test：

```text
assert retry == 1
```

Agent 面临：

```text
代码符合真实需求

Test FAILED
```

如果它盲目相信 Test：

```text
会把正确代码改错。
```

---

# 九十八、Test Oracle Problem

这说明：

```text
Test
```

不是天然真理。

Test Oracle 也可能：

```text
错误

过时

与用户需求冲突

只覆盖局部行为
```

因此优先级应该类似：

```text
Explicit User Requirement

Formal Acceptance Criterion

Repository Contract

Trusted Tests

Implementation
```

而不是：

```text
任何 Test
都是绝对真理。
```

---

# 九十九、遇到疑似错误 Test 怎么处理

例如：

```text
Test
和
TaskSpec.goal
明显冲突
```

建议：

```text
do not silently change production
```

进入：

```text
INCONCLUSIVE
```

或：

```text
NEEDS_REVIEW
```

以后 Day 3 Error Classifier 可以决定：

```text
需要用户澄清
```

---

# 一百、Failure Case 2：Flaky Test

例如：

```text
Run 1:
FAIL

Run 2:
PASS

Run 3:
FAIL
```

Agent 如果每次都：

```text
根据最新 Test Result 改代码
```

会发生：

```text
Oscillation
```

---

# 一百零一、Flaky Test 怎么识别

不要：

```text
失败后一直 rerun
直到 pass
```

这是典型错误。

可以在疑似 Flaky 情况：

```text
固定次数重复
```

例如：

```text
3 runs
```

记录：

```text
2 fail / 1 pass
```

状态：

```text
INCONCLUSIVE
```

并保存：

```text
Flakiness Evidence
```

---

# 一百零二、为什么不应该“重跑直到通过”

因为：

```text
10% 概率通过
```

你只要跑足够多次：

```text
总能拿到一次 PASS
```

然后 Agent 宣布：

```text
fixed
```

完全错误。

所以必须保存：

```text
pass / run ratio
```

而不是：

```text
最后一次结果
```

---

# 一百零三、Failure Case 3：Agent 为了通过 Test 破坏正确行为

这是：

> **Test Hacking / Overfitting to the Oracle**

例如测试：

```python
assert calculate(2, 2) == 4
```

Agent 为了 PASS：

```python
if a == 2 and b == 2:
    return 4
```

Test：

```text
PASS
```

但实现：

```text
完全错误。
```

---

# 一百零四、怎么降低 Test Hacking

### 第一层

```text
Related Regression
```

---

### 第二层

```text
Full Regression
```

---

### 第三层

```text
Diff Review
```

检查：

```text
有没有 hard-code

有没有删除 assertion

有没有 skip test
```

---

### 第四层

Evaluation 中使用：

```text
Held-out Tests
```

不要把所有 Oracle 全部暴露给 Agent。

这在你最终 15 Task Evaluation 会非常重要。

---

# 一百零五、一个重要 Policy：Agent 能不能修改 Tests

不要简单规定：

```text
永远不能
```

因为 Feature Task：

```text
需要新增 Test
```

Bug Fix：

```text
可能要新增 Regression Test
```

更合理：

```text
允许修改 tests

但是：
Test changes 单独显示

Verification 不能只依赖
Agent 自己修改的测试
```

最好还有：

```text
existing regression
或
held-out acceptance
```

---

# 一百零六、Failure Case 4：反复修同一处

例如：

```text
Attempt 1:
修改 line 20

Attempt 2:
又修改 line 20

Attempt 3:
改回 Attempt 1
```

这叫：

```text
Repair Oscillation
```

---

# 一百零七、如何检测 Repair Oscillation

可以记录：

```text
failure_signature

patch_hash

changed_files

diff similarity
```

第一版甚至：

```text
same failure_signature
+
same changed_files
```

连续出现：

```text
3 次
```

就可以：

```text
STOP / REPLAN
```

---

# 一百零八、Failure Case 5：Test Output 太大

例如：

```text
pytest
```

生成：

```text
100 MB log
```

Day 5 CommandRunner 已经做：

```text
bounded head + tail
```

所以 RepairLoop 不应该：

```text
重新读取原始无限 Output
```

而应该：

```text
CommandResult
↓
bounded VerificationResult
↓
RepairContext
```

---

# 一百零九、但是 Output 截断可能把关键错误截掉

例如：

```text
100 MB output
```

关键 Stack Trace：

```text
位于中间
```

Head+Tail 都没保存。

这就是一个明确 Known Limitation。

以后可以改善：

```text
Failure Pattern Extractor

pytest structured output

JUnit XML

compiler diagnostic parser
```

而不是单纯无限提高：

```text
Output Limit
```

---

# 一百一十、这其实是很重要的工业方向：Structured Tool Feedback

最理想的 Agent Tool Result 不是：

```text
一大坨 stdout
```

而是：

```text
failed_tests

exception

stack_trace

duration

exit_code
```

也就是：

```text
unstructured process output
↓
structured observation
```

今天 `VerificationResult` 就是在走这条路。

---

# 一百一十一、Failure Case 6：测试环境错误

例如：

```text
ModuleNotFoundError:
dependency missing
```

Agent 如果误认为：

```text
业务代码有 Bug
```

然后开始：

```text
修改 import
删除依赖
```

可能越修越错。

因此 VerificationResult 必须保留：

```text
START_FAILED
TIMED_OUT
FAILED
```

不同类型。

明天 Day 3：

```text
ErrorClassifier
```

正式负责这些情况。

---

# 一百一十二、Failure Case 7：Target Test 选错

例如 Bug：

```text
login timeout
```

Agent 选择：

```text
test_logout
```

然后：

```text
PASS
```

它可能宣布完成。

所以：

```text
Target Test Selection
```

本身也是一个需要 Evaluation 的模块。

以后可以通过：

```text
Issue terms

SymbolIndex

changed files

ImportGraph

existing tests
```

生成候选 Target Test。

---

# 一百一十三、今日建议的完整架构

到今天结束，我希望你脑中是：

```text
                     TaskSpec
                        │
                        ▼
                       Plan
                        │
                        ▼
                 Current PlanStep
                        │
                        ▼
                    AgentLoop
                        │
                        ▼
                  Patch Proposal
                        │
                        ▼
                  PatchValidator
                        │
                        ▼
                   GitWorkspace
                        │
                        ▼
               VerificationService
                        │
                        ▼
                     Target
                        │
                ┌───────┴────────┐
                ▼                ▼
              PASS              FAIL
                │                │
                ▼                ▼
          Regression       FailureResult
                │                │
        ┌───────┴─────┐          ▼
        ▼             ▼      RepairContext
      PASS           FAIL         │
        │             │           ▼
        │             └────── RepairAttempt
        │                         │
        ▼                         ▼
 PlanStep COMPLETED          AgentLoop
                                  │
                                  └──→ Patch
```

---

# 一百一十四、今天建议的目录

不要过度拆。

例如：

```text
codeteam/
├── verification/
│   ├── models.py
│   └── service.py
│
├── repair/
│   ├── models.py
│   └── loop.py
│
└── agent/
    └── orchestrator.py
```

如果项目还小，也可以：

```text
verification.py
repair.py
```

重点是职责，不是目录数量。

---

# 一百一十五、今天建议 7 个实现 Step

## Step 1：Verification 数据模型

实现：

```text
VerificationKind

VerificationStatus

VerificationRequest

VerificationResult
```

先不接 LLM。

---

## Step 2：VerificationService

接入：

```text
SafeExecutor
```

做到：

```text
VerificationRequest
↓
CommandRequest
↓
CommandResult
↓
VerificationResult
```

---

## Step 3：先跑 Target Test

第一版只实现：

```text
Patch
→ Target
```

先证明：

```text
PASS / FAIL
```

语义正确。

---

## Step 4：`RepairAttempt`

建立：

```text
Attempt
Failure
Patch
Verification
```

的记录结构。

---

## Step 5：`RepairLoop`

实现：

```text
FAIL
→ repair
→ verify
```

以及：

```text
max_repair_attempts
```

---

## Step 6：Regression Cascade

升级：

```text
Target PASS
→ Related Regression
```

最后预留：

```text
Full Regression
```

---

## Step 7：Benchmark + Failure Injection

最后：

```text
真实/Mock Model
+
固定任务
```

统计指标。

---

# 一百一十六、为什么今天还是应该优先 Fake/Mock Agent

RepairLoop 的核心逻辑必须 deterministic 测试。

例如：

```text
Attempt 0:
verification FAILED

MockRepairAgent:
return Patch B

Attempt 1:
verification PASSED
```

这样可以可靠验证：

```text
RepairLoop
确实只调用一次 Repair
```

真实模型应该放到：

```text
Integration
Benchmark
```

而不是每个 Unit Test。

---

# 一百一十七、Test Agent 今天最应该验证的不变量

至少：

```text
Target FAIL
→ task not complete


Target PASS
+
Regression FAIL
→ task not complete


Required verifications PASS
→ step complete


attempt exhausted
→ no further model calls


START_FAILED
→ don't treat as code test failure


DENY/BLOCK
→ runner bypass impossible
```

---

# 一百一十八、Benchmark Plan

今天可以准备：

```text
10 个小 Bug Task
```

每个都有：

```text
initial failing test

acceptance

related regression
```

记录：

```text
repairs

target latency

verification latency

tool calls

tokens

success
```

---

# 一百一十九、Design Decision 文档建议

```text
DD-W4-D2-01

Title:
Tiered Verification Repair Loop

Problem:
How should CodeTeam validate
candidate patches during iterative repair?

Alternatives:

A.
Run the complete test suite
after every candidate patch.

B.
Run targeted verification first,
then related regression,
then broader regression
when required.

Decision:
Use B.

Reasoning:
- lower feedback latency
- focused failure evidence
- reduced repeated verification cost
- retain broader regression safety
  before completion

Risks:
- target selection may miss regressions
- related-test selection can be wrong

Mitigations:
- broader final regression
- changed-file/test mapping
- ImportGraph-based test selection
- held-out evaluation

Evidence Status:
PROPOSED
```

等 Week 4 Ablation 跑完以后，再改成：

```text
SUPPORTED
PARTIALLY_SUPPORTED
NOT_SUPPORTED
```

---

# 一百二十、今天完成以后必须能够解释的 5 个核心区别

## 1.

```text
Test Failure
≠
Agent Failure
```

---

## 2.

```text
CommandResult
≠
VerificationResult
```

---

## 3.

```text
Target PASS
≠
Task Success
```

---

## 4.

```text
Repair
≠
Replan
```

---

## 5.

```text
Test
≠
Perfect Oracle
```

如果这五个区别你真正理解了，今天最重要的理论基本已经掌握。

---

# 一百二十一、今天的最终验收 Checklist

### Theory

```text
[ ] Reproduction

[ ] Baseline

[ ] Test Oracle

[ ] Targeted Test

[ ] Related Regression

[ ] Full Regression

[ ] Verification

[ ] Test Failure as Observation

[ ] Repair Attempt

[ ] Stopping Condition

[ ] Flaky Test

[ ] Test Hacking
```

### Implementation

```text
[ ] VerificationKind

[ ] VerificationRequest

[ ] VerificationStatus

[ ] VerificationResult

[ ] RepairAttempt

[ ] RepairLoop
```

### Pipeline

```text
[ ] Patch

→ Target Verification

→ FAIL

→ Repair Context

→ New Patch

→ Verification
```

### Required Tests

```text
[ ] First patch passes

[ ] First patch fails,
    repair succeeds

[ ] Repair budget exhausted

[ ] Target PASS /
    Regression FAIL

[ ] Test command missing

[ ] Test timeout

[ ] Output truncated
```

### Recommended Extra Tests

```text
[ ] BLOCKED verification

[ ] same failure repeated

[ ] no-op repair

[ ] failed patch apply

[ ] regression only after target pass

[ ] attempt limit prevents further model call
```

### Evaluation

```text
[ ] Mean Repair Attempts

[ ] Target Test P50/P95

[ ] Total Verification Latency

[ ] Tool Calls

[ ] First-pass Success

[ ] Final Task Success
```

### Evidence

```text
[ ] Design Decision

[ ] Benchmark raw data

[ ] Repair-loop Ablation spec

[ ] Failure Case records
```

---

# 一百二十二、今天应该能回答的 Interview Questions

### Verification

1. Coding Agent 为什么一定需要 Verification Loop？
2. 为什么 Test Failure 不等于 Agent Failure？
3. CommandResult 和 VerificationResult 有什么区别？
4. Test Oracle 是什么？
5. 为什么 Test 也可能是错误的 Oracle？
6. 为什么最好先 Reproduce Bug？

### Tests

7. Targeted Test 和 Regression Test 有什么区别？
8. 为什么不应该每次 Patch 都运行整个 Test Suite？
9. 为什么 Target PASS 还不能宣布 Task Success？
10. Related Regression 怎么选？
11. 怎样利用 ImportGraph 帮助选择 Regression Test？

### Repair

12. RepairAttempt 为什么应该成为 Runtime Entity？
13. Repair 和 Replan 有什么区别？
14. 每次 Test FAIL 都应该 Rollback 吗？
15. 怎么防止无限 Repair？
16. 怎么识别 Repair Oscillation？
17. Failure Signature 有什么用？

### Reliability

18. Test Command 不存在为什么不能当成业务 Test Failure？
19. Timeout 应该怎么分类？
20. Output Truncated 为什么不一定意味着 Test Failure？
21. Flaky Test 怎么处理？
22. 为什么不能 rerun until pass？
23. 如何防止 Agent 为了通过测试破坏正确行为？

### Evaluation

24. 怎么证明 Repair Loop 真有价值？
25. Single-shot vs Repair Loop Ablation 怎么做才公平？
26. Repair Loop 成功率提高但 Cost 翻倍，该怎么评价？
27. First-pass Success Rate 有什么意义？
28. Time-to-first-green 能说明什么？

---

# 一百二十三、如果面试官问：“这不就是失败了把错误再喂给 LLM 吗？”

你最终应该能够回答：

> 我没有把 Repair Loop 实现成简单的“非零退出码 → 把整段 stderr 重新塞给模型”。执行命令首先被转换成结构化 `VerificationRequest`，经过安全执行链产生 `CommandResult`，再由 Verification 层解释为 `PASSED`、`FAILED`、`TIMED_OUT`、`START_FAILED` 或 `BLOCKED` 等语义。对于真实的行为失败，我会提取 Failure Signature 和有界 Repair Context，建立可审计的 `RepairAttempt`，关联 Patch、Checkpoint、Changed Files 和 Verification Evidence，再生成下一次候选修改。验证采用 Targeted → Related Regression → Broader Regression 的分层策略，并由 Repair Budget、重复 Failure、无进展和安全失败等 Stopping Conditions 防止无限循环。最终 Task Success 必须由外部 Oracle 和 Regression Evidence 决定，而不是模型自己宣称完成。

这就已经从：

```text
“把报错扔回 ChatGPT”
```

上升到了：

```text
Closed-loop Agent Runtime
+
External Verification
+
Repair State Management
+
Recovery
+
Evaluation
```

---

# 一百二十四、Day 2 在 Single-Agent MVP 中的位置

昨天：

```text
Natural Language
      ↓
TaskSpec
      ↓
Plan
      ↓
READY
```

今天加上：

```text
READY
  ↓
PlanStep
  ↓
Patch
  ↓
Verify
  │
  ├── PASS
  │
  └── FAIL
       ↓
     Repair
       ↓
     Patch
       ↓
     Verify
```

明天 Day 3 才正式解决：

```text
为什么失败？

这个 Failure：
应该 Retry？
Repair？
Replan？
Stop？
还是 Ask User？
```

所以 Day 2 与 Day 3 的分界非常清楚：

> **Day 2 建立 Feedback Loop；Day 3 建立 Failure Intelligence。**

只要今天能够把“**Patch once**”真正升级成“**Produce → Verify → Observe → Repair → Verify**”，你的 Single-Agent Runtime 就第一次具备了真正意义上的**自我纠错能力**。

---

# 教练教程：Day 2 教学地图

> 以下内容由 Coder Agent 教练根据 `prompt/coder_Agent.md` 第六节规范生成（Benchmark/Ablation 按用户决定改为周度集中评测，两节合并为「周度评测预留」），基于只读核实的仓库实际状态。

---

## 1. 今天在整个 Coding Agent 中做什么

Day 1 的管线停在 **READY**（有 Plan、无执行）。今天把终点推进为**闭环执行能力**：

```
READY → PlanStep(RUNNING) → Patch → Verification
       → FAIL → RepairAttempt → 新 Patch → Verification
       → PASS → Regression → PlanStep(COMPLETED)
```

**核心转换**：从「生成 Patch 就结束」升级为「Patch 是候选解，外部验证反馈决定它是否值得保留」。

没有它的后果：Runtime 对"Patch 对不对、Bug 修没修、有没有引入新 Bug、失败后怎么办"一无所知——那只是 Code Generation，不是 Coding Agent。

## 2. Capability Mapping

```
Primary:   Agent Runtime
           ├── Feedback Loop（Observation → Action）
           ├── Retry-Repair Lifecycle
           └── Stopping Condition（约束模型自主循环）

Secondary: Tool Runtime —— Verification 分层走 Week 3 安全链
           Evaluation —— Test Oracle / 行为验证 / Task success evidence
```

**今天证明的核心**（day2.md 第七节）：*「现代 Coding Agent 的核心不是模型第一次写没写对，而是 Harness 能否把失败可靠地转成下一轮有用反馈。」* 面试时这句话就是今天的全部价值主张。

## 3. Theory

### 3.1 五个必须讲透的核心区别（day2.md 一百二十节）

| # | 区别 | 一句话 |
|---|---|---|
| 1 | **Test Failure ≠ Agent Failure** | pytest exit 1 不是 TaskStatus.FAILED，是"还有 Repair Budget 可用的 Observation" |
| 2 | **CommandResult ≠ VerificationResult** | Runner 说 SUCCESSFULLY_EXECUTED（进程正常管理）；Verification 说 FAILED（exit code 不符合预期） |
| 3 | **Target PASS ≠ Task Success** | 局部行为对了 ≠ 附近行为没被破坏，还需要 Regression Evidence |
| 4 | **Repair ≠ Replan** | 计划方向对、实现细节错 → Repair；计划基本假设错（以为 timeout 在 auth.py 实际在 proxy）→ Replan |
| 5 | **Test ≠ Perfect Oracle** | Oracle 可能错误/过时/与需求冲突；错误 Oracle 比没有 Oracle 更危险 |

### 3.2 三层结果模型

```
Level 1  CommandResult       命令有没有正常运行？（Runner 视角）
Level 2  VerificationResult  代码有没有通过验证？（Oracle 视角）
Level 3  TaskResult          整个任务有没有成功？（Runtime 视角）

pytest exit 1:
  Runner:       SUCCESSFULLY_EXECUTED（进程正常启动管理）
  Verification: FAILED（exit code != 0）
  Task:         仍 IMPLEMENTING/VERIFYING（还有 Repair Budget）
```

### 3.3 关键理论

- **Reproduction / Baseline**：FAIL→PASS 的修复证据远强于 Unknown→PASS。修改前用确定输入复现问题
- **Test Oracle**：判断"正确还是错误"的外部判定规则（pytest exit 0 / golden file / HTTP 响应）；模型自评不是 Oracle
- **Targeted Test**：低延迟、聚焦的反馈通道（1 秒 vs 4 分钟全量）
- **Verification Escalation**：Target（快/窄）→ Related（中/相关）→ Full（慢/宽），代码越接近完成验证范围越大
- **Failure Signature**：test name + exception type 级别的稳定指纹——识别"Patch #1/2/3 全是同一失败 = 没有进展"
- **RepairAttempt**：Runtime Entity（failure/diagnosis/patch/checkpoint/verification 全关联），不是"LLM 又生成一次 Patch"

## 4. Industrial Design

| 系统 | 方案 | 与 CodeTeam 的关系 |
|---|---|---|
| **OpenAI Codex** | 长任务循环：Plan → Edit → Run tests/build/lint → Observe → Repair → Repeat；每个 milestone 必须 validation，失败先修复不扩范围 | 今天 RepairLoop 的 S1-S4 Stopping Condition 直接对应"失败先修复" |
| **OpenAI iterative repair cookbook** | Review → Repair → Validate 三阶段；Validation 剩余问题成为下一轮 Repair 输入 | RepairContext → Agent → Patch → Verify 的闭环结构 |
| **Claude Code** | Bug fix 工作流：error + reproduction command/steps → 修复；测试工作流：生成测试 → 运行 → 修失败 | Reproduction/Baseline 理论（day2.md 第九节） |
| **GitHub Copilot cloud** | 修复 Merge Conflict 后继续验证 build/tests/linter 全过才请求 Review | Local fix ≠ Task success——Regression 收尾的思想 |
| **Aider** | `--test-cmd` + `--auto-test`：AI 修改后自动跑测试，非零退出码的 stdout/stderr 作为反馈继续修 | 今天是在把这个思想工程化/结构化/可评测化 |

## 5. 当前仓库检查（已核实）

| 资产 | 状态 | 接口要点 |
|---|---|---|
| `execution/models.py` | ✅ Week 3 | `CommandRequest(argv: tuple[str,...], cwd, workspace_root, task_id, timeout_seconds)` |
| `execution/safe_executor.py` | ✅ | `SafeCommandExecutor(*, policy, approval_manager, runner)` 全可选默认；`execute(request, *, approval_grant=None) -> CommandResult` |
| `CommandResult` | ✅ | `status: CommandStatus`（SUCCESS/NONZERO_EXIT/TIMED_OUT/START_FAILED/POLICY_DENIED/APPROVAL_DENIED/APPROVAL_REQUIRED）+ exit_code/stdout/stderr/truncated/duration_ms |
| `git/patch.py` + `git/workspace.py` | ✅ Week 3 | PatchValidator（validate → PatchResult）、GitWorkspace（check_patch/apply_patch/diff） |
| `git/checkpoint.py` | ✅ Week 3 | CheckpointManager（RepairAttempt 要关联 checkpoint_id） |
| `codeteam/verification/`、`codeteam/repair/` | ❌ 不存在 | 今天新建 |
| Day 1 状态机 | ✅ | `TaskStatus.IMPLEMENTING/VERIFYING` 转移表已允许；`PlanStepStatus` 的 RUNNING/COMPLETED/FAILED 已就绪 |

**CommandStatus → VerificationStatus 的天然映射**（Step 2 核心）：

```
SUCCESS + exit in expected → PASSED
NONZERO_EXIT / exit not expected → FAILED
TIMED_OUT → TIMED_OUT
START_FAILED → START_FAILED
POLICY_DENIED / APPROVAL_DENIED / APPROVAL_REQUIRED → BLOCKED
```

## 6. 涉及文件

```
codeteam/verification/           ← [新建]
├── __init__.py
├── models.py                    ← VerificationKind/Status/Request/Result + failure_signature 提取
└── service.py                   ← VerificationService（Request→CommandRequest→SafeCommandExecutor→Result）

codeteam/repair/                 ← [新建]
├── __init__.py
├── models.py                    ← RepairAttempt / RepairOutcome / RepairContext
└── loop.py                      ← RepairLoop（max_repair_attempts + S1-S4）

codeteam/agent/orchestrator.py   ← [扩展] READY 之后接执行：IMPLEMENTING → RepairLoop → VERIFYING → COMPLETED
codeteam/events.py               ← [扩展] verification.* / repair.* 事件（day2.md 七十六节）

tests/verification/              ← [新建] test_models.py / test_service.py
tests/repair/                    ← [新建] test_models.py / test_loop.py
```

**禁止修改**：`codeteam/execution/`、`codeteam/git/`（只读复用）、Day 1 已验收行为（805 基线不得破坏）。

## 7. Architecture / Data Flow

```
PlanStep P3: RUNNING
        │
        ▼
RepairLoop.run()
        │
        ├─ ① VerificationService.verify(TargetedRequest)     ← 走 SafeCommandExecutor
        │      └─ VerificationRequest → CommandRequest → CommandResult → VerificationResult
        │
        ├─ ② PASS？
        │      ├─ 是 → Related Regression verify
        │      │        ├─ PASS → PlanStep COMPLETED（S1: success）
        │      │        └─ FAIL → 进 Repair（针对 Regression Failure，不重修 Target）
        │      └─ 否 → 判定 status：
        │             ├─ FAILED → 提取 failure_signature → RepairContext
        │             ├─ TIMED_OUT / START_FAILED → 不默认修代码（S3 观察/记录）
        │             └─ BLOCKED → 不调 RepairAgent（S4 语义）
        │
        ├─ ③ attempt < max_repair_attempts？
        │      ├─ 否 → PlanStep FAILED + RepairOutcome=REPAIR_EXHAUSTED（S2）
        │      └─ 是 → RepairContext(failure tail + diagnosis) → RepairAgent
        │             → 新 Patch → PatchValidator → GitWorkspace.apply_patch
        │             → RepairAttempt 记录（checkpoint 关联）→ 回到 ①
        │
        └─ 事件全程记录：verification.started/completed/failed/timed_out、
           repair.started/patch_proposed/patch_applied/completed/exhausted

关键不变量：
- Test FAIL 不把 PlanStep 标 FAILED —— 只有 budget exhausted 才标（day2.md 七十九节）
- Verification 绝不绕过 Week 3 安全链（day2.md 二十七节）
- VerificationRequest ≠ CommandRequest（六十九节：语义分层，转换而非合并）
- Target FAIL 时 Regression 不执行（避免浪费，T14）
```

## 8. 今日步骤拆分（6 步，去除原 Step 7）

| Step | 目标 | 为什么先做 | 涉及文件 | 前置知识 | 完成标志 |
|---|---|---|---|---|---|
| **1** | Verification 数据模型：VerificationKind/Status/Request/Result + failure_signature 提取（不接 LLM） | 全部后续代码的公共语言；纯数据最容易保证正确 | `verification/models.py` | str Enum、BaseModel、tuple 标注 | 6 种 Status 齐全；signature 提取可测 |
| **2** | VerificationService：Request → CommandRequest → SafeCommandExecutor → Result | 先读清 Week 3 真实接口再设计；安全链是硬约束 | `verification/service.py` | CommandRequest/CommandResult 字段、依赖注入 | 全部 7 种 CommandStatus 正确映射为 VerificationStatus |
| **3** | 先跑通 Target Test（Patch → Target 的 PASS/FAIL 语义） | 最小闭环先验证语义正确，再接 Repair | `repair/loop.py`（雏形） | VerificationService | Target PASS→成功 / FAIL→失败语义正确 |
| **4** | RepairAttempt 记录结构（failure/diagnosis/patch/checkpoint 关联） | Repair 的可审计性是后续 Evaluation 的地基 | `repair/models.py` | BaseModel 嵌套、attempt_no 语义 | 一次 attempt 全字段可构造 |
| **5** | RepairLoop（FAIL → RepairContext → 新 Patch → 再 Verify；max_repair_attempts + S1-S4） | 今天的核心：把失败可靠转成下一轮反馈 | `repair/loop.py` | 依赖注入（RepairAgent Protocol + Mock）、循环边界 | 4 个 Stopping Condition 全部可测 |
| **6** | Regression Cascade（Target PASS → Related Regression，预留 Full）+ 集成进 Orchestrator/PlanStep 状态推进 | 局部正确 ≠ 全局正确；Day 1 状态机今天真正启用 | `repair/loop.py`、`agent/orchestrator.py`、`events.py` | TaskStatus 转移表、事件系统 | Target PASS+Regression FAIL 不 COMPLETED；只有 budget exhausted 才标 PlanStep FAILED |

## 9. Test Strategy

### Required Tests（7 项，day2.md 一百二十一节）

| 测试 | 断言核心 | 对应验收 |
|---|---|---|
| 首次成功 | repair_attempts == 0，不强行"再优化一次" | S1 成功后立即停 |
| 一次失败二次成功 | repair_attempts == 1；第一次 failure 确实进入第二次 RepairContext | FAIL→Repair→PASS 闭环 |
| 连续失败到上限 | max=3 时第 4 次**不再调模型**；outcome == REPAIR_EXHAUSTED | S2 预算耗尽 |
| Target PASS + Regression FAIL | Task 不 COMPLETED；Repair 针对 Regression 而非重修 Target | 局部≠全局 |
| 命令不存在 | VerificationStatus == START_FAILED；**RepairAgent 不被调用** | 环境错误 ≠ 代码错误 |
| Test Timeout | TIMED_OUT（不是 FAILED）；不默认改代码 | CommandStatus 映射 |
| Output Truncated | 不崩溃；仍按 exit code 判定；truncated 只是 metadata | exit 0 + truncated → 仍 PASSED |

### Recommended Extra Tests（8 项）

BLOCKED 不调 RepairAgent / 同 signature 重复计数 / no-op patch 防死循环 / patch 无法 apply 是 PATCH FAILURE 不是 TEST FAILURE / Target FAIL 时 RegressionRunner 零调用 / attempt limit 强不变量 / attempt 与 checkpoint 正确关联 / Regression PASS 但 Target FAIL 仍 FAIL。

**原则**：真实临时环境优先（tmp_path 小仓库 + 真实 pytest 命令），只 Mock 外部模型（Fake/Mock RepairAgent，day2.md 一百一十六节）。每条测试注明对应哪条验收。

## 10. Design Decision Plan

**DD-W4-D2-01：Tiered Verification Strategy**

```
Problem:   每个候选 Patch 应该怎样验证？
Alternatives:
  A. 每次 Patch 后跑完整测试套件（最宽验证，但慢/贵/噪声多）
  B. Targeted → Related Regression → Full where required（快反馈/聚焦/降迭代成本，
     但 Target 选错可能漏回归）
Decision:   B
Reasons:    Feedback Latency / Diagnostic Precision / Resource Efficiency / 最终仍逐级扩到回归
Risks:      Target Selection 错、Related 选错
Mitigations: 最终 Broad Regression + 未来 changed-files/ImportGraph 测试选择 + held-out eval
Evidence status: PROPOSED —— 这是工程假设，待周度 Ablation 验证，不得标 SUPPORTED
```

记录位置：`docs/design_decisions/DD-W4-D2-01.md`（沿用 Day 1 目录）。

## 11. 周度评测预留（替代 Benchmark/Ablation Plan）

今天**不写 benchmark 脚本、不跑 benchmark**。但实现必须为周度集中评测留好数据出口：

| 预留字段/事件 | 落到哪里 | 周度指标 |
|---|---|---|
| RepairAttempt.attempt_no / outcome | repair.models | Mean Repair Attempts（成功任务 + 全体分开） |
| VerificationResult.duration_ms | verification.completed 事件 data | Target P50/P95、Total Verification Latency |
| RepairLoop 返回的 attempts tuple | RepairLoopResult | First-pass Success Rate |
| repair.patch_proposed / applied 事件 | events | Tool Calls 计数 |
| failure_signature 序列 | RepairAttempt | Repair Oscillation / 同签名重复率 |
| Target PASS + Regression FAIL 计数 | RepairOutcome | Regression Failure Rate After Target Pass |

原则：**Raw data 全部落对象/事件，评测脚本以后只读不重复测量**（与 Day 1 的 planner_ms 模式一致）。

## 12. Failure Cases to Watch

| # | 场景 | Day 2 处理 |
|---|---|---|
| FC-1 | 测试本身错误（Oracle 冲突） | 不静默改生产代码；留 INCONCLUSIVE/NEEDS_REVIEW 钩子，Day 3 分类 |
| FC-2 | Flaky Test | 固定次数重跑记录 pass/run ratio；**禁止 rerun-until-pass** |
| FC-3 | Test Hacking（硬编码过测试） | 靠 Regression + Diff Review 兜底；Day 2 只记录 |
| FC-4 | Repair Oscillation | 同 failure_signature + 同 changed_files 连续 3 次 → STOP/REPLAN 钩子 |
| FC-5 | 输出过大截断丢关键错误 | bounded head+tail；Known Limitation 如实记录 |
| FC-6 | 环境错误误诊为代码错误 | START_FAILED/TIMED_OUT 与 FAILED 分离，不触发 Repair |
| FC-7 | Target Test 选错 | Target 选择本身是待 Evaluation 的模块；周度评测观察 |

## 13. Interview Focus

**关键追问——"这不就是失败了把错误再喂给 LLM 吗？"** 标准回答（day2.md 一百二十三节）：

> 我没有把 Repair Loop 实现成简单的"非零退出码 → 把整段 stderr 重新塞给模型"。执行命令首先被转换成结构化 VerificationRequest，经过安全执行链产生 CommandResult，再由 Verification 层解释为 PASSED/FAILED/TIMED_OUT/START_FAILED/BLOCKED 等语义。对真实行为失败，提取 Failure Signature 和有界 Repair Context，建立可审计的 RepairAttempt（关联 Patch/Checkpoint/Changed Files/Verification Evidence），再生成下一次候选修改。验证采用 Targeted → Related → Full 分层策略，由 Repair Budget、重复 Failure、无进展和安全失败等 Stopping Conditions 防止无限循环。最终 Task Success 由外部 Oracle 和 Regression Evidence 决定，而不是模型自己宣称完成。

**其余 28 问**（day2.md 一百二十二节）分五组：Verification（6）/ Tests（5）/ Repair（6）/ Reliability（6）/ Evaluation（5）。特别准备：**为什么不能 rerun until pass**（10% 通过率重跑总有一次 PASS，但那是假证据）、**Single-shot vs Repair Loop 公平对比的预算陷阱**（周度 Ablation 要控制模型调用预算）。

## 14. 今日最终完成标准

```
[ ] VerificationKind 7 种 / VerificationStatus 6 种 / Request / Result 模型完成
[ ] failure_signature 提取完成（test name + exception type，第一版）
[ ] VerificationService 走 SafeCommandExecutor，7 种 CommandStatus 映射正确
[ ] VerificationRequest ≠ CommandRequest（转换而非合并，不绕过安全链）
[ ] RepairAttempt 是 Runtime Entity（checkpoint_id 关联）
[ ] RepairLoop：max_repair_attempts + S1(成功) S2(预算耗尽) S3(不可恢复执行错误) S4(中断/BLOCKED)
[ ] Test FAIL 不标 PlanStep FAILED；只有 budget exhausted 才标
[ ] Target PASS + Regression FAIL → 不 COMPLETED，Repair 针对 Regression
[ ] 7 项 Required + 8 项 Recommended 测试全绿，每条对应验收
[ ] 全量 pytest 不低于 805 基线
[ ] DD-W4-D2-01 落盘，Evidence = PROPOSED
[ ] 周度评测预留字段/事件就位（不写评测脚本）
[ ] Failure Cases 已记录
[ ] 28 个面试问题 + 关键追问可独立回答
[ ] 明确不做：ErrorClassifier（Day 3）、Session 持久化（Day 4）、完整 CLI、Benchmark/Ablation 执行（周度集中）
```