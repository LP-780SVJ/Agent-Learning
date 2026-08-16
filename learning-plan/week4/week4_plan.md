# 第 4 周：完成 Single-Agent Coding MVP

第 4 周和前三周的性质有明显变化。

前三周主要是在造 **Agent Runtime 的基础设施零件**：

```text
Week 1
Agent Loop / Tool Calling / State

Week 2
Repository Understanding / Context Engine

Week 3
Git / Workspace / Recovery / Policy / Approval / Sandbox
```

第 4 周要第一次把这些零件真正接起来，让用户能够在仓库根目录直接输入：

```bash
codeteam run "修复登录超时问题"
```

然后 CodeTeam 自己完成：

```text
理解自然语言任务
        ↓
理解 Repository
        ↓
制定实现计划
        ↓
定位相关文件
        ↓
修改代码
        ↓
运行测试
        ↓
失败 → 分析 → 再修
        ↓
成功
        ↓
保存 Session
        ↓
输出 Diff / Result
```

因此我建议把第 4 周定位成：

> **Single-Agent Coding Runtime Integration Week**

最终产物 `codeteam-single-agent` 不应该只是“CLI 可以启动”，而应该第一次成为一个完整、可测量、可中断恢复的 Coding Agent。

当前 OpenAI Codex CLI 本身也把终端工作流描述为“探索陌生仓库 → 规划变更 → 编辑文件 → 运行本地开发工具 → 在同一 Session 继续工作”，并支持恢复保存的会话。([OpenAI Developers][1]) GitHub Copilot cloud agent 的公开流程同样明确包含 repository research、implementation plan、branch 上的 code changes、test/lint 和 diff review。([GitHub Docs][2])

---

# 一、第 4 周最终应该长成什么样

我建议你的目标架构从：

```text
AgentLoop
+
一堆独立 Runtime 模块
```

升级成：

```text
                        User
                         │
                         ▼
              codeteam CLI / API
                         │
                         ▼
                 SessionService
                         │
                         ▼
              SingleAgentOrchestrator
                         │
          ┌──────────────┼───────────────┐
          │              │               │
          ▼              ▼               ▼
    Task Normalizer   SessionStore   ModelRegistry
          │                              │
          ▼                              ▼
    Repository Context                ModelClient
          │
          ▼
       Planner
          │
          ▼
   Execution Plan
          │
          ▼
       AgentLoop
          │
    ┌─────┴─────────────────┐
    ▼                       ▼
Context Engine          Tool Runtime
Week 2                   Week 1/3
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
          Patch          Command         Git/Files
            │               │
            ▼               ▼
       Safe Patch       SafeExecutor
                            │
                            ▼
                         Sandbox
            │
            └───────────────┬───────────────
                            ▼
                     Verification Loop
                            │
                    ┌───────┴────────┐
                    ▼                ▼
                  PASS              FAIL
                    │                │
                    │          Error Classifier
                    │                │
                    │          Retry / Replan
                    │                │
                    └────────────────┘
                            │
                            ▼
                       Final Result
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          Session          Diff         Metrics
```

这就是第 4 周最核心的变化：

> **从“有 Agent Runtime 组件”变成“Runtime 真正驱动一个 Coding Task 完成”。**

---

# 二、第一块知识：Issue → Plan → Patch

这是 Single-Agent Coding 最核心的主流程。

## 1. Issue 到底是什么

这里的 Issue 不一定真的来自 GitHub Issue。

例如：

```bash
codeteam run "修复登录超时问题"
```

这句话就是：

```text
Raw User Task
```

但 Agent Runtime 不应该永远拿着这一行字符串工作。

第一步应该把它转成内部：

```text
TaskSpec
```

例如：

```text
Task ID:
task-001

Original Request:
修复登录超时问题

Repository:
xxx

Goal:
修复登录过程中的 timeout bug

Constraints:
遵守 repository instructions
不得修改 workspace 外文件

Acceptance:
相关测试通过
Regression 通过
没有越权副作用
```

因此：

```text
Issue
```

在你的 Runtime 中应该理解为：

> **Agent 要完成的外部任务契约。**

---

# 三、Issue 不应该直接进入“开始改代码”

一个弱 Coding Agent：

```text
User
↓
“修复登录超时”

LLM
↓
grep login

LLM
↓
改文件
```

一个成熟一些的 Coding Agent：

```text
Issue
↓
Repository inspection
↓
Evidence gathering
↓
Plan
↓
Patch
↓
Verification
```

OpenAI 当前 Codex 的官方最佳实践也明确建议复杂、模糊或难描述的任务先进入 Plan Mode，由 Agent 获取上下文、提出必要问题，再生成实现计划。([OpenAI Developers][3])

GitHub Copilot cloud agent 同样把：

```text
research repository
→ create plan
→ code changes
```

作为公开工作流。([GitHub Docs][2])

---

# 四、Plan 在 Coding Agent 中究竟是什么

这里有一个很重要的边界：

**不要试图保存或要求模型输出其私有思维链。**

你的 Runtime 需要的是一个**外显、结构化的执行计划**。

例如：

```text
Plan

P1
定位 LoginService timeout 来源

P2
检查 timeout 配置的调用链

P3
复现失败场景

P4
增加/确认 regression test

P5
修改 timeout handling

P6
运行 targeted tests

P7
运行 related regression
```

这叫：

```text
Execution Plan
```

而不是：

```text
模型内部为什么一步一步想到这些事情的私人推理过程
```

这一点非常重要。

---

# 五、Plan 应该有什么字段

我建议后面实现类似：

```python
PlanStep

step_id
title
description

status

relevant_files

verification

depends_on
```

状态例如：

```text
PENDING
RUNNING
COMPLETED
FAILED
SKIPPED
```

于是 Session 可以显示：

```text
Plan

✓ P1 Locate timeout implementation
✓ P2 Reproduce bug
→ P3 Modify timeout logic
○ P4 Run tests
○ P5 Regression
```

这开始有真正 Coding Agent 产品的感觉。

---

# 六、为什么 Plan 不能是一次性的作文

错误：

```text
LLM 生成一个五百字 Plan
↓
之后完全不再看
```

Plan 在 Runtime 中应该是：

```text
Execution State
```

也就是说：

```text
计划
→ 执行
→ 发现假设错误
→ 更新计划
```

例如：

```text
Plan v1:

修改 auth/client.py
```

结果检查代码发现：

```text
真正 timeout 在
transport/http.py
```

那应该：

```text
Replan
```

而不是硬着头皮继续执行原计划。

---

# 七、推荐第 4 周的 Task 状态机

```text
CREATED
   │
   ▼
INSPECTING
   │
   ▼
PLANNING
   │
   ▼
IMPLEMENTING
   │
   ▼
VERIFYING
   │
   ├──────── PASS ────────→ COMPLETED
   │
   ▼
FAILURE_ANALYSIS
   │
   ├── retry ─────────────→ IMPLEMENTING
   │
   ├── replan ────────────→ PLANNING
   │
   ├── user needed ───────→ PAUSED
   │
   └── unrecoverable ─────→ FAILED
```

这实际上就是 Single-Agent Runtime 的主状态机。

---

# 八、Plan → Patch

Plan 不应该直接让模型：

```text
重写整个文件
```

而应该：

```text
Plan Step
↓
Context Selection
↓
Patch Proposal
↓
PatchValidator
↓
GitWorkspace
↓
Diff
```

这恰好把 Week 2 和 Week 3 接起来：

```text
Plan says:
修改 LoginService

        ↓

Context Engine:
召回：
login_service.py
http_client.py
test_login.py

        ↓

LLM proposes patch

        ↓

Week3 PatchValidator

        ↓

Worktree
```

---

# 九、工业上为什么 “Plan → Diff” 非常重要

GitHub Copilot cloud agent 当前支持先 research、plan，再在 branch 上做代码修改，然后让开发者 review diff、继续迭代，再决定是否创建 PR。([GitHub Docs][4])

OpenAI Codex CLI 同样把：

```text
plan
edit
run tools
inspect diff
review
```

作为一个连续终端开发流程。([OpenAI Developers][1])

这说明现代 Coding Agent 的核心产物不是：

```text
“一段代码”
```

而是：

```text
一个基于 Repository State 的受控 Change Set。
```

---

# 十、第二块知识：测试驱动修复

你第 4 周列出的：

```text
测试驱动修复
```

我建议不要狭义理解成：

> 每次必须严格执行传统 TDD 的 Red-Green-Refactor。

对于 Coding Agent，最重要的是：

```text
Reproduce
→ Change
→ Verify
```

---

# 十一、Bug Repair 的黄金流程

以后：

```bash
codeteam run "修复登录超时问题"
```

应该优先尝试：

```text
1. 理解 Bug

2. 找相关测试

3. 找复现方式

4. 运行测试 / 命令

5. 确认问题真的存在

6. 保存 Failure Evidence

7. 修改代码

8. 运行最小 Target Test

9. Target PASS

10. 运行 Related Regression

11. 全部满足才 COMPLETED
```

这和：

```text
模型感觉代码应该没问题了
```

完全不同。

---

# 十二、为什么先复现再修

假如原测试：

```text
全部 PASS
```

Agent直接改一堆东西，

最后测试仍：

```text
PASS
```

你根本不知道：

```text
Bug 是否真的修复？
```

因此需要：

```text
Failure Before
+
Success After
```

形成证据。

---

# 十三、一个标准 Repair Record

例如：

```text
Failure Before:

test_login_timeout
FAILED

Expected:
retry once

Actual:
TimeoutError


Patch:
auth/client.py


Verification After:

test_login_timeout
PASSED


Regression:

tests/auth/
42 passed
```

以后 Evaluation 才能知道：

```text
Task Success
```

到底是不是事实。

---

# 十四、工业界怎么做

Aider 当前支持在每次代码修改后自动 lint/test；测试命令返回非零退出码时，它会把失败作为反馈，再尝试修复问题。([Aider][5])

GitHub Copilot cloud agent 可以在自己的 ephemeral development environment 中执行测试和 lint；当 GitHub Actions workflow 失败时，也可以启动 Agent 分析并修复该失败。([GitHub Docs][2])

所以：

> **Test output 是 Agent 的 Observation，而不仅是最终 QA。**

---

# 十五、Repair Loop 应该是什么

```text
Patch
  │
  ▼
Target Test
  │
  ├── PASS
  │     │
  │     ▼
  │  Regression
  │     │
  │     ├── PASS → DONE
  │     │
  │     └── FAIL
  │
  └── FAIL
        │
        ▼
 Error Classifier
        │
        ▼
Diagnosis
        │
        ▼
new context
        │
        ▼
new patch
```

这就是 Single-Agent Coding 的第一个真正 Feedback Loop。

---

# 十六、这里必须限制 Retry

否则：

```text
Patch
→ fail
→ patch
→ fail
→ patch
→ fail
...
```

会无限循环。

因此需要：

```text
max_repair_attempts
```

比如：

```text
3
```

或根据现有 Agent Budget 统一控制。

达到上限：

```text
FAILED
```

并保存：

```text
Last Failure
Attempts
Diff
Tests
```

---

# 十七、第三块知识：错误分类

到了 Week 4，“异常”不能全部都是：

```python
except Exception as e:
```

然后：

```text
Agent failed
```

因为不同 Failure 的恢复策略完全不同。

---

# 十八、我建议建立 Agent Runtime Error Taxonomy

至少分九类：

| Category     | 示例                                        | 是否可能 Retry    |
| ------------ | ----------------------------------------- | ------------- |
| TASK         | 输入缺失、需求矛盾                                 | 通常需要用户        |
| CONTEXT      | 找不到相关代码                                   | 可以扩大检索        |
| MODEL        | timeout/rate limit/provider unavailable   | 经常可 retry     |
| TOOL         | executable missing/tool returned failure  | 视情况           |
| SECURITY     | policy deny/approval deny/sandbox failure | 通常不可自动绕过      |
| PATCH        | patch context mismatch/invalid patch      | 可以重新生成        |
| GIT          | dirty state/worktree conflict             | 视情况           |
| VERIFICATION | test fail/lint fail                       | 可以 repair     |
| SESSION      | session corrupted/storage error           | 通常需要 recovery |

---

# 十九、Error Category 为什么重要

例如：

```text
MODEL_RATE_LIMIT
```

合理：

```text
Backoff
→ Retry
```

而：

```text
POLICY_DENIED
```

如果也：

```text
Retry 3 次
```

没有意义。

再比如：

```text
PATCH_CONTEXT_MISMATCH
```

应该：

```text
重新读取文件
→ 重新生成 patch
```

不是：

```text
直接重发同一 Patch
```

所以：

```text
Error Class
→ Recovery Policy
```

---

# 二十、建议 Error Record 至少有

```text
category
code
message

stage

retryable

attempt

task_id
session_id

tool_name

cause

suggested_recovery
```

不要只存：

```text
str(exception)
```

---

# 二十一、工业系统已经在做这种区分

OpenAI Codex app-server 对过载会返回明确的 overloaded error，并要求客户端使用指数退避和 jitter 重试；Turn Failure 也有独立事件。([OpenAI Developers][6])

Claude Code Tool Failure 事件会区分正常 Tool Error 和 Interrupt，并记录错误文本与执行时间。([Claude Platform Docs][7])

GitHub Copilot SDK 也提供 `onErrorOccurred` 一类 Hook，可根据 `tool_execution` 等错误上下文提供不同恢复信息。([GitHub Docs][8])

这说明：

> **Failure 不是一个 Boolean，而是 Runtime State。**

---

# 二十二、推荐 Error Recovery Matrix

例如：

```text
MODEL_TIMEOUT
→ retry with backoff

MODEL_RATE_LIMIT
→ retry later

CONTEXT_INSUFFICIENT
→ expand retrieval

PATCH_CONTEXT_MISMATCH
→ reread file + regenerate

TEST_FAILED
→ diagnosis + repair

APPROVAL_DENIED
→ stop action

POLICY_DENIED
→ hard stop action

SANDBOX_UNAVAILABLE
→ fail closed

SESSION_CORRUPTED
→ reject resume / recovery procedure

USER_INTERRUPT
→ persist + PAUSED
```

这会直接影响 Day 3 的实现。

---

# 二十三、第四块知识：Session Persistence

这是 Week 4 最重要的新 Runtime 能力之一。

用户要求：

```bash
codeteam resume <session-id>
```

意味着你的 Agent 不再是：

```text
process memory
=
all state
```

---

# 二十四、Session 与 Conversation 不完全相同

一个 Coding Agent Session 至少包括：

```text
Conversation

+
Task

+
Plan

+
Repository State

+
Worktree

+
Checkpoint

+
Model

+
Usage

+
Errors

+
Execution State
```

所以 Session Persistence 不是：

```text
messages.json
```

这么简单。

---

# 二十五、Session 应该保存什么

我建议：

```text
Session

identity
├── session_id
├── task_id
└── repo_id

task
├── original_request
├── normalized_task
└── acceptance

repository
├── repo_path
├── base_sha
├── worktree
└── branch

execution
├── state
├── active_plan
├── completed_steps
└── current_step

conversation
├── messages
├── compact_summary
└── recent_turns

recovery
├── checkpoint_ids
└── current_checkpoint

model
├── provider
├── model
└── parameters

metrics
├── tokens
├── cost
├── tool_calls
└── elapsed

failure
└── last_error

timestamps
├── created
└── updated
```

---

# 二十六、什么东西不要持久化

例如：

```text
Python object pointer

subprocess.Popen object

thread lock

open file descriptor

HTTP client instance

Docker process handle
```

这些是：

```text
Ephemeral Runtime State
```

不能 Resume。

Resume 时应该：

```text
从 Durable State
重新构造 Runtime Object
```

---

# 二十七、Session Persistence 的核心公式

可以记成：

```text
Persistent State
+
Current Environment Reconciliation
=
Resumed Runtime
```

而不是：

```text
pickle.dump(agent)
```

---

# 二十八、工业界 Session Resume 已经是标配能力

Codex CLI 当前支持 `codex resume`，本地保存 transcript，让开发者可以继续之前的任务；非交互 `codex exec` 也支持按 Session ID resume。([OpenAI Developers][1])

Claude Code 在进程重启后也支持 `claude --resume` 恢复会话。([Claude Platform Docs][9])

GitHub Copilot CLI 支持：

```text
--continue
--resume
--resume SESSION-ID
```

恢复既有 CLI Session。([GitHub Docs][10])

因此：

```text
Session
```

已经不是聊天产品附件，而是 Coding Agent Runtime 的核心实体。

---

# 二十九、Resume 最难的地方不是读取 JSON

比如 Session 保存：

```text
worktree:
/tmp/codeteam/task-001

base_sha:
abc123
```

第二天 Resume：

```text
Worktree 不存在了
```

怎么办？

又或者：

```text
Branch HEAD 已经变化
```

怎么办？

所以：

```text
resume()
```

必须有：

```text
State Reconciliation
```

---

# 三十、Resume 时至少检查

```text
Session 存在？

Repo 还存在？

Repo identity 一致？

Base SHA 还存在？

Worktree 还存在？

Worktree 属于当前 Task？

Workspace 是否发生外部变化？

Checkpoint Store 完整？

Model Provider 是否还可用？
```

然后：

```text
RESUMABLE

RECOVERY_REQUIRED

INVALID
```

---

# 三十一、推荐 Persistence 格式

对于你当前 MVP，我不建议一上来做数据库服务。

更适合学习的是：

```text
.codeteam-state/
└── sessions/
    └── <session-id>/
        ├── session.json
        ├── events.jsonl
        ├── context.json
        └── artifacts/
```

其中：

```text
session.json
→ 当前 Durable Snapshot

events.jsonl
→ Append-only execution history

context.json
→ compaction information
```

后面如果 Session 多了再换 SQLite。

---

# 三十二、为什么 `events.jsonl` 很有价值

例如：

```text
session.created
plan.created
patch.applied
test.failed
checkpoint.created
context.compacted
model.switched
session.paused
session.resumed
session.completed
```

Resume 和 Debug 都会简单很多。

这其实把 Week 1 Event Log 正式升级成：

```text
Persistent Runtime History
```

---

# 三十三、第五块知识：Context Compaction

先彻底分清：

```text
Session Persistence
```

和：

```text
Context Compaction
```

Session：

```text
磁盘上记住全部历史
```

Context：

```text
这一次送给 LLM 什么
```

完全不同。

---

# 三十四、为什么不能 Resume 后把所有消息重新塞回 LLM

假设：

```text
Session 跑了 2 小时

Tool Calls:
150

Messages:
300

Logs:
200 KB

Files:
很多
```

重新：

```text
messages = 全部历史
```

会出现：

```text
Token 爆炸
Cost 增长
Latency 增长
模型注意力分散
Context Window 满
```

Claude Code 当前会在接近 Context Limit 时自动 compact 会话历史，并允许用 `/compact` 指定摘要时优先保留什么。([Claude Platform Docs][11])

GitHub Copilot CLI 当前在 Context 使用率约 80% 时开始后台 Compaction，并预留约 20% Headroom；若使用率进一步接近约 95% 而后台压缩还没完成，则会等待压缩完成。([GitHub Docs][12])

Codex CLI 当前同样支持接近 Context Window 时自动总结 Session。([OpenAI Developers][13])

---

# 三十五、Compaction 不是简单删前 50%

错误：

```text
messages = messages[-20:]
```

因为被删除的可能正好包括：

```text
用户约束
Bug 根因
重要设计决定
失败尝试
测试命令
```

---

# 三十六、我建议 Context 分层

```text
Tier 0
System / Security Instructions
永远保留

Tier 1
Repository Instructions
永远重新加载

Tier 2
Task Contract
永远保留

Tier 3
Active Plan
保留

Tier 4
Durable Working Memory
压缩后保留

Tier 5
Recent Conversation
保留最近若干轮

Tier 6
Old Tool Output
总结或删除

Tier 7
Large Raw Logs
只保留引用 / 摘要
```

---

# 三十七、Compacted Summary 应重点保存什么

例如：

```text
Task Goal

Current Plan

Completed Work

Files Modified

Important Code Facts

Failed Attempts

Latest Test Results

Current Error

Checkpoint

Remaining Work

User Constraints
```

而不是：

```text
“我们讨论了很多关于登录的事情……”
```

---

# 三十八、Compaction 最大 Failure Case：信息丢失

Claude Code 官方甚至专门支持在 Compaction 后通过 Hook 重新注入重要上下文，因为压缩摘要可能丢失关键细节。([Claude Platform Docs][14])

Claude 的项目级 `CLAUDE.md` 也会在 Compact 后重新读取并注入，而不是完全依赖 Conversation Summary。([Claude Platform Docs][15])

这给你的设计一个很重要的启示：

> **Durable Instructions 不应该由 LLM Summary 承担。**

---

# 三十九、CodeTeam 应该怎么做

Compact 后：

```text
System Rules
+
AGENTS.md / repo rules
+
TaskSpec
+
Active Plan
+
Compacted Working Summary
+
Recent Turns
+
Retrieved Current Code
```

重新组成：

```text
Model Context
```

这就是 Context Engineering。

---

# 四十、第六块知识：模型切换

至少两个 Provider 的验收，不应该变成：

```python
if provider == "a":
    ...
elif provider == "b":
    ...
```

散落全项目。

你 Week 1 已经建立 Provider-neutral Client，这周应该真正产品化。

---

# 四十一、先分清 Provider 和 Model

例如：

```text
Provider:
OpenAI

Model:
xxx
```

或者：

```text
Provider:
Anthropic

Model:
xxx
```

这是两个概念。

所以：

```text
ModelSelection
```

至少：

```text
provider_id
model_id
```

---

# 四十二、工业界也明确区分 Model 与 Provider

Codex 当前支持 Custom Model Provider，Provider 定义 Base URL、Wire API、认证方式和 HTTP Header；配置中 `model` 与 `model_provider` 是独立字段。([OpenAI Developers][16])

GitHub Copilot CLI 当前 `/model` 可以在 Session、Repository 或 Global Scope 切换 Model；如果当前 Turn 正在运行，切换请求会等待当前 Turn 完成后应用，而不会在同一次 Model Request 中途更换。([GitHub Docs][17])

Claude Code 的 Resume 也会考虑 Session 当时使用的 Model，同时允许显式 Model 配置覆盖恢复值。([Claude Platform Docs][18])

---

# 四十三、这告诉你两个重要设计原则

## 原则 1

```text
Model Switching
只发生在 Turn Boundary
```

不要：

```text
一个 Tool Call 做到一半
突然换 Provider
```

---

## 原则 2

每个 Turn 都应该记录：

```text
provider
model
```

以后 Evaluation 才能知道：

```text
这个 Patch
是谁生成的？
```

---

# 四十四、推荐结构

```text
ModelClient
    ▲
    │
┌───┴────────────────┐
│                    │
OpenAICompatible   AnthropicClient
│                    │
▼                    ▼
Provider config    Provider config
```

然后：

```text
ProviderRegistry

get(provider_id)
```

Agent Loop 永远只依赖：

```text
ModelClient
```

---

# 四十五、两 Provider 到底怎么选

对于你的求职项目，我建议：

### 最低验收版本

```text
Provider A:
OpenAI-compatible endpoint A

Provider B:
OpenAI-compatible endpoint B
```

能够证明：

```text
Provider config / endpoint / credential
```

已经抽象。

### 更有工程价值的版本

```text
Provider A:
OpenAI-compatible protocol

Provider B:
Anthropic-native protocol
```

这样才能真正证明：

```text
Agent Runtime
没有和某一种 Wire Protocol 绑定
```

后者更值得作为最终版本。

---

# 四十六、Provider 错误必须统一

例如：

```text
OpenAI:
rate_limit_error

Anthropic:
自己的异常类型
```

Agent Loop 不应该知道。

统一转换：

```text
ModelError

RATE_LIMIT
TIMEOUT
AUTH
CONTEXT_OVERFLOW
INVALID_REQUEST
SERVER
UNKNOWN
```

然后由 Week4 ErrorClassifier 决定：

```text
retry?
compact?
switch?
fail?
```

---

# 四十七、Context Overflow 特别值得和 Model Switching 联动

例如：

```text
Model A
context smaller
```

出现：

```text
CONTEXT_OVERFLOW
```

Recovery：

```text
compact()
→ retry
```

如果仍失败：

```text
possible model switch
```

但不应该：

```text
无限自动换 Provider
```

因为：

```text
Cost
Behavior
Quality
```

都会变化。

所以第一版建议：

```text
显式 model switch
```

优先于：

```text
silent automatic routing
```

---

# 四十八、第七块知识：CLI Interaction

你的最终验收：

```bash
codeteam run "修复登录超时问题"

codeteam resume <session-id>

codeteam diff <session-id>

codeteam rollback <checkpoint-id>
```

CLI 应该是：

```text
Thin Interface
```

而不是把 Runtime 逻辑写在 CLI 函数里。

---

# 四十九、正确架构

```text
CLI

@app.command()
def run(...):
    service.run(...)
```

而不是：

```text
CLI
↓
创建 Worktree
↓
构造 Prompt
↓
调用 LLM
↓
处理 Tool
↓
写 Session
↓
Git Diff
```

全部放一个函数。

---

# 五十、推荐 Typer

对于你当前 Python + 类型标注风格，我建议使用 Typer。

Typer 本身基于 Python Type Hints，并原生支持多个 Command/Subcommand，适合：

```text
run
resume
diff
rollback
```

这种 CLI。([Typer][19])

Python 标准库 `argparse` 也能很好支持 Subcommand；如果你希望完全零第三方依赖，它也是合理方案。([Python documentation][20])

对当前学习项目我倾向：

```text
Typer
```

主要因为你的 CLI Model 可以直接和 Python 类型标注结合，更适合学习和维护。

---

# 五十一、`codeteam run`

建议：

```bash
codeteam run \
  "修复登录超时问题" \
  --provider openai \
  --model xxx
```

它应该：

```text
validate repo

create session

create task worktree

create checkpoint

build context

create plan

execute

verify

persist

show result
```

启动之后第一时间打印：

```text
Session:
abc123
```

这样即使进程后来崩溃，

用户知道：

```bash
codeteam resume abc123
```

---

# 五十二、`codeteam resume`

```bash
codeteam resume abc123
```

流程不是：

```text
load messages
→ run
```

而是：

```text
load Session

→ validate repo

→ reconcile Worktree

→ load checkpoint metadata

→ load active plan

→ restore compacted context

→ initialize model

→ continue state machine
```

---

# 五十三、`codeteam diff`

应该是纯：

```text
READ ONLY
```

例如：

```bash
codeteam diff abc123
```

找到：

```text
Session
→ Task Worktree
→ Base SHA
```

然后调用：

```text
GitWorkspace.diff()
```

不能触发：

```text
LLM
Tool
Checkpoint
```

---

# 五十四、`codeteam rollback`

```bash
codeteam rollback cp-123
```

直接复用 Week3：

```text
CheckpointManager
```

CLI 不应该自己：

```text
git reset
```

同时必须验证：

```text
checkpoint exists

belongs to session/task

worktree matches
```

---

# 五十五、Ctrl+C 也是 CLI 产品能力

如果用户：

```text
Ctrl+C
```

不要：

```text
Python stacktrace
进程直接死
```

推荐：

```text
interrupt current operation

→ cleanup child

→ persist session

→ state = PAUSED

→ print:

Session paused: abc123
Resume with:
codeteam resume abc123
```

这对“支持中断恢复”的验收非常重要。

---

# 五十六、Week 4 建议的核心目录

最终大概可以向下面演化：

```text
codeteam/
├── cli/
│   ├── app.py
│   └── commands.py
│
├── agent/
│   ├── loop.py
│   ├── orchestrator.py
│   ├── planning.py
│   ├── repair.py
│   └── errors.py
│
├── session/
│   ├── models.py
│   ├── store.py
│   └── service.py
│
├── context/
│   ├── ...
│   └── compaction.py
│
├── llm/
│   ├── base.py
│   ├── registry.py
│   ├── openai_compatible.py
│   └── ...
│
├── git/
│   └── Week3 modules
│
└── execution/
    └── Week3 modules
```

这是建议布局，最终仍应以你的实际仓库为准，不要为了符合这张图强行重构。

---

# 五十七、第 4 周详细每日计划

下面我建议仍然保持 **7 天**，而且继续按照你已经确定的统一学习闭环：

```text
Theory
→ Industrial Design
→ Implementation
→ Tests
→ Design Decision
→ Benchmark
→ Ablation
→ Failure Cases
→ Interview Questions
```

---

# Day 1：Issue → Plan → Execution State

## 今天解决什么

第一次实现：

```bash
codeteam run "自然语言任务"
```

背后的 Task Lifecycle。

先不要追求一次完成复杂代码任务。

今天重点：

```text
Natural Language
→ TaskSpec
→ Plan
→ Agent State Machine
```

工业参考上，Codex 当前建议复杂任务先规划，GitHub Copilot cloud agent 也公开采用 research → plan → code change 流程。([OpenAI Developers][3])

### 理论

学习：

```text
Task vs Session

TaskSpec

Goal
Constraint
Acceptance Criterion

Planning

Plan Step

State Machine

Replanning

Terminal State
```

必须弄懂：

```text
Issue
≠
Prompt

Plan
≠
Chain of Thought

Plan
=
Structured Execution Contract
```

### 编码

建议实现：

```text
TaskSpec

Plan
PlanStep
PlanStepStatus

TaskStatus

Planner

SingleAgentOrchestrator
```

第一版：

```text
run(task)
→ inspect repo
→ create plan
→ return/display plan
```

然后再接现有 AgentLoop。

### 测试

至少：

```text
普通自然语言任务

空 Task

Plan 至少有一个 Step

Step 状态转换

无效状态转换

Plan 完成

Plan 失败

Replan
```

### Design Decision

写：

```text
为什么 Plan 是结构化数据，
而不是纯自然语言长文本？
```

比较：

```text
Free-form Plan
vs
Structured Plan
```

### Benchmark

准备 10 个 Task Prompt：

测：

```text
Planning latency

Plan step count

Token usage
```

### Ablation

后面保留：

```text
Plan-first
vs
Direct-edit
```

在最终 15 Task 中比较。

### Failure Cases

重点记录：

```text
Plan 与代码库事实不一致

Plan 过度细碎

Plan 一步过大

Plan 已失效却继续执行
```

### 今日完成

必须能够：

```text
自然语言
→ TaskSpec
→ Plan
→ 执行状态
```

---

# Day 2：Test-Driven Repair Loop

## 今天解决什么

把：

```text
Patch once
```

升级成：

```text
Observe
→ Patch
→ Test
→ Diagnose
→ Repair
```

Aider 当前自动测试/修复机制就是非常直接的工业参考：代码修改后运行 Test Command，非零结果重新反馈给 Agent 修复。([Aider][5])

### 理论

重点：

```text
Reproduction

Test Oracle

Targeted Test

Regression Test

Test Failure

Repair Attempt

Verification

Stopping Condition
```

理解：

```text
test failed
≠
agent failed
```

它可能只是：

```text
Observation
```

### 编码

实现：

```text
VerificationRequest

VerificationResult

VerificationStatus

RepairAttempt

RepairLoop
```

Pipeline：

```text
Patch
↓
target test
↓
FAIL
↓
failure context
↓
Agent
↓
new patch
↓
test
```

设置：

```text
max_repair_attempts
```

### 测试

构造：

```text
第一次 Patch 成功

第一次失败第二次成功

连续失败达到上限

Target Test PASS
Regression FAIL

测试命令不存在

测试 timeout

测试 output truncated
```

### Design Decision

比较：

```text
Patch → Full Test Suite

vs

Patch
→ Target Test
→ Related Regression
→ Full Test where necessary
```

我推荐第二个。

### Benchmark

测：

```text
平均 Repair Attempts

Target Test latency

Total verification latency

Tool calls
```

### Ablation

```text
With repair loop
vs
Single-shot patch
```

指标：

```text
Task Success Rate
```

### Failure Case

重点：

```text
测试本身错误

Flaky Test

Agent 为通过测试破坏正确行为

反复修同一处

Test output 太大
```

---

# Day 3：Error Classification + Retry / Recovery

## 今天解决什么

让 Agent 从：

```text
“出错了”
```

升级成：

```text
“出了哪种错误，
下一步应该做什么？”
```

OpenAI Codex 当前就对 overload 等错误提供明确的 Retry 语义；Claude Code 与 Copilot SDK 也公开提供 Tool/Error 级事件，而不是只有一个失败 Boolean。([OpenAI Developers][6])

### 理论

学习：

```text
Error Taxonomy

Retryable

Non-retryable

Transient

Permanent

Recovery Policy

Backoff

Fail Fast

Fail Closed
```

### 编码

实现：

```text
ErrorCategory

AgentErrorCode

AgentFailure

ErrorClassifier

RecoveryAction

RetryPolicy
```

至少覆盖：

```text
MODEL
CONTEXT
PATCH
TOOL
SECURITY
TEST
GIT
SESSION
USER_INTERRUPT
```

### 测试

至少：

```text
rate limit → retry

timeout → retry

patch mismatch → reread/regenerate

test fail → repair

policy deny → no retry

approval deny → stop

sandbox unavailable → stop

Ctrl+C → PAUSED
```

### Design Decision

核心：

```text
Error Classification
属于 Domain Model

而不是散落的 except 分支
```

### Benchmark

对故障注入：

```text
50 error cases
```

测：

```text
classification accuracy

correct recovery action

unnecessary retry count
```

### Ablation

```text
Typed Error Recovery

vs

Generic Exception Retry
```

重点看：

```text
无意义 Retry
Task latency
Task success
```

### Failure Cases

```text
错误分类错

Transient 被判断 Permanent

Permanent 无限 Retry

原始 Exception 丢失

安全错误被自动重试绕过
```

---

# Day 4：Session Persistence + Resume

## 今天解决什么

正式实现：

```bash
codeteam resume <session-id>
```

Codex、Claude Code、GitHub Copilot CLI 当前都已经将 Session Resume 作为核心 Coding Agent 工作流。([OpenAI Developers][1])

### 理论

学习：

```text
Durable State

Ephemeral State

Session

Resume

Event Log

Snapshot

State Reconciliation

Crash Consistency

Atomic Write
```

### 编码

实现：

```text
Session

SessionStatus

SessionStore

SessionService

SessionManifest
```

建议输出：

```text
sessions/
<id>/
├── session.json
├── events.jsonl
└── context.json
```

实现：

```text
create()

save()

load()

pause()

resume()
```

### 重点 Integration

必须保存：

```text
TaskSpec

Plan

Provider/model

Usage

Current state

Worktree identity

Checkpoint chain
```

### 测试

```text
创建 Session

保存加载一致

程序退出后恢复

PAUSED → RUNNING

不存在 Session

损坏 Session

Worktree missing

Repo HEAD changed

Cross-repo resume
```

### 强制验收实验

真实：

```text
codeteam run task

运行中 Ctrl+C

退出 Python

重新启动：

codeteam resume id
```

必须继续。

### Design Decision

比较：

```text
pickle Runtime Object

vs

Durable Domain State
+
Runtime reconstruction
```

必须选后者。

### Benchmark

测：

```text
Session save latency

Session load latency

events size

100 / 500 / 1000 events
```

### Ablation

```text
No persistence
vs
Persistence
```

人为 Kill 进程：

比较：

```text
Restart from zero time

Resume time
```

---

# Day 5：Context Compaction + Model / Provider Switching

这一天会比较重，但这两个模块联系很强：

```text
Session 可以很长
+
不同 Model Context Window 不同
```

GitHub Copilot CLI、Claude Code 和 Codex 当前都存在自动 Context Compaction。([GitHub Docs][12])

## 上午：Context Compaction

### 理论

学习：

```text
Context Window

Durable Session
vs
Active Context

Summarization

Compaction

Recent Window

Durable Facts

Instruction Reinjection

Context Budget
```

### 编码

实现：

```text
CompactionRequest

CompactionResult

ContextSummary

ContextCompactor
```

结构：

```text
System rules

Repository rules

TaskSpec

Active Plan

Compact Summary

Recent Messages

Current Context
```

### 测试

特别测试摘要是否保留：

```text
用户约束

当前文件

失败测试

当前 Plan

Checkpoint

未完成 Step
```

---

## 下午：Model Switching

Codex 当前 Model 与 Provider 可以独立配置，自定义 Provider 定义连接方式；GitHub Copilot CLI 支持 session/repo/global Model Scope，并避免在一个正在执行的 Turn 中途更换模型。([OpenAI Developers][16])

### 编码

完善：

```text
ProviderRegistry

ModelSelection

ModelMetadata

ModelErrorMapper
```

目标：

```text
provider A
provider B
```

真实跑通。

### 规则

```text
Model switch
只能 Turn Boundary
```

并持久化：

```text
每个 Turn 使用的
provider/model
```

### CLI 后面准备支持

```bash
codeteam run task \
  --provider xxx \
  --model xxx
```

以及：

```bash
codeteam resume id \
  --provider xxx \
  --model xxx
```

可选 Override。

### Benchmark

准备 5 个固定 Coding Tasks，

同样任务：

```text
Provider A
Provider B
```

测：

```text
Task Success

Token

Cost

Latency

Tool Calls

Repair Attempts
```

### Ablation

Context：

```text
No compaction
vs
structured compaction
```

Model：

```text
single provider
vs
provider-neutral runtime
```

前者可量化；后者主要验证架构耦合程度。

---

# Day 6：CLI Productization

## 今天解决什么

把内部 Python System 变成真正可以使用的：

```text
codeteam
```

OpenAI Codex、Claude Code 和 GitHub Copilot 都把终端作为核心 Coding Agent Surface，并支持会话 Resume 等长期工作流。([OpenAI Developers][1])

### 最终四条命令

```bash
codeteam run "修复登录超时问题"

codeteam resume <session-id>

codeteam diff <session-id>

codeteam rollback <checkpoint-id>
```

### 推荐附加

```bash
codeteam sessions

codeteam status <session-id>
```

不是本周硬验收，可以后做。

### 编码

建议：

```text
cli/
├── app.py
└── commands.py
```

使用 Typer。

Typer 原生支持基于类型标注的多 Command/Subcommand，非常契合这个 CLI。([Typer][21])

### `run`

负责：

```text
parse options
↓
SessionService.run()
```

---

### `resume`

负责：

```text
SessionService.resume()
```

---

### `diff`

负责：

```text
Session
→ Worktree
→ GitWorkspace.diff()
```

必须：

```text
READ ONLY
```

---

### `rollback`

负责：

```text
CheckpointManager.rollback()
```

必须校验：

```text
checkpoint ownership
```

---

## CLI 输出建议

不要疯狂打印模型所有内部细节。

例如：

```text
Session: 5a81...

Task:
修复登录超时问题

[inspect] repository
[plan] 5 steps
[edit] src/auth/client.py
[test] 7 passed
[verify] 42 passed

Status: COMPLETED
Duration: 2m31s
Tokens: ...
Cost: ...
Files changed: 2
```

---

## 测试

使用 CLI Runner / subprocess 测：

```text
--help

run

resume

diff

rollback

无效 session

无效 checkpoint

Ctrl+C

invalid provider

exit code
```

### Design Decision

记录：

```text
CLI = Interface Layer

不能承载 Runtime Logic
```

### Benchmark

测：

```text
CLI startup latency
```

但这一天性能 Benchmark 不是重点。

重点：

```text
End-to-End usability
```

---

# Day 7：15 Task Evaluation + README + `codeteam-single-agent`

Day 7 不应该继续堆功能。

今天：

> **证明这个 Single Agent 到底能不能工作。**

---

# 五十八、15 个自建任务应该怎么设计

不要找：

```text
15 个特别简单的“改一行”
```

然后宣布：

```text
成功率 100%
```

建议：

### Bug Fix × 5

```text
B01
单文件 logic bug

B02
跨文件调用 bug

B03
错误配置导致失败

B04
exception handling bug

B05
timeout / resource related bug
```

### Feature × 4

```text
F01
新增小 API

F02
新增 CLI option

F03
新增配置能力

F04
跨模块小 feature
```

### Refactor × 3

```text
R01
提取公共逻辑

R02
重构 interface

R03
rename + downstream updates
```

### Test / Maintenance × 3

```text
M01
补 regression tests

M02
修 failing test suite

M03
修 lint/type issue
```

总计：

```text
5 + 4 + 3 + 3 = 15
```

---

# 五十九、每个 Eval Task 必须有 Oracle

例如：

```text
task.yaml

id:
B01

prompt:
修复登录超时问题

repo:
fixture-login

acceptance_command:
pytest tests/test_login.py

regression_command:
pytest

max_steps:
20

timeout:
...
```

最好还有：

```text
expected_behavior
```

但不要把：

```text
正确修改哪个文件
```

直接塞进 Agent Context。

否则相当于泄题。

---

# 六十、最好做 Held-out Evaluation

如果你反复：

```text
跑 B01
→ 调 Prompt
→ 跑 B01
→ 调 Ranking
→ 跑 B01
```

B01 已经变成：

```text
Development Case
```

不能继续拿它证明泛化。

所以建议：

```text
Dev:
5 Task

Held-out:
10 Task
```

或者：

```text
开发期间 15

最后再追加 5 个未调试任务
```

后者更强。

---

# 六十一、成功率怎么计算

建议严格定义：

```text
Task Success
=
Acceptance Test PASS

AND

Required Regression PASS

AND

Agent completed within limits

AND

No security violation
```

不是：

```text
Agent 自己说：
“问题已经解决。”
```

---

# 六十二、本周核心指标

最终 Evaluation 至少统计：

```text
Task Success Rate

Wall-clock Duration

Model Cost

Input Tokens

Output Tokens

Tool Calls

Repair Attempts

Context Compactions

Files Changed
```

GitHub Copilot cloud agent 当前也向用户暴露 Session Progress、Token Usage、Session Length，并为 Agent PR 提供生命周期相关指标，这反映了 Coding Agent 不应只测“最终有没有代码”。([GitHub Docs][22])

---

# 六十三、建议结果表

最终真正跑完再填写：

| Task | Type | Provider | Success | Attempts | Time | Tokens | Cost |
| ---- | ---- | -------- | ------: | -------: | ---: | -----: | ---: |
| B01  | Bug  | A        |         |          |      |        |      |
| B02  | Bug  | A        |         |          |      |        |      |
| ...  |      |          |         |          |      |        |      |
| M03  | Test | B        |         |          |      |        |      |

不得预填好看的数字。

---

# 六十四、建议增加四个汇总指标

```text
Success Rate

Median Duration

P95 Duration

Median Cost / Successful Task
```

另外：

```text
Success by Task Type
```

很有价值：

```text
Bug:
4/5

Feature:
...

Refactor:
...
```

这样能发现 Agent 到底弱在哪里。

---

# 六十五、本周最值得做的三个 Ablation

如果时间有限，我建议不要一口气做七八个。

优先三个：

## A1：Plan vs No Plan

相同 5 个中等任务：

```text
Plan-first
vs
Direct execute
```

指标：

```text
Success
Tool calls
Tokens
Duration
Repair attempts
```

验证：

```text
Planning
到底是有价值
还是只是多花 Token。
```

---

## A2：Repair Loop vs Single Shot

```text
Patch once

vs

Patch → Test → Repair
```

指标：

```text
Task Success
```

这应该会成为非常强的 Single-Agent Evaluation。

---

## A3：Compaction vs Raw History

使用长任务：

```text
Structured Compaction

vs

Keep history until limit / naive truncation
```

比较：

```text
Task completion

Tokens

Lost-constraint errors

Cost
```

---

# 六十六、本周 Failure Case Database

至少系统记录：

```text
F001
错误 Plan 导致错误文件

F002
检索不到关键文件

F003
Patch 不适用

F004
Repeated repair loop

F005
测试本身 flaky

F006
Context compact 丢用户限制

F007
Resume 时 Worktree 缺失

F008
Session 状态损坏

F009
Provider timeout

F010
Model switch 后行为漂移

F011
CLI interrupted during persistence

F012
Checkpoint mismatch
```

以后这些全部是你的：

```text
面试素材
+
Regression Corpus
```

---

# 六十七、README 不能只写安装方法

最终：

```text
README.md
```

建议至少包含：

```text
1. Project Overview

2. Why CodeTeam

3. Architecture Diagram

4. Single-Agent Workflow

5. Quick Start

6. CLI Commands

7. Model Provider Configuration

8. Context Engine

9. Safety Runtime

10. Session Resume

11. Checkpoint / Rollback

12. Evaluation

13. Benchmark / Ablation Results

14. Failure Cases / Known Limitations

15. Roadmap
```

---

# 六十八、README 首页最关键的 Demo

建议：

```bash
$ codeteam run "修复登录超时问题"

Session: ses_abc123

✓ Repository inspected
✓ Plan created
✓ Failure reproduced
✓ Patch applied
✓ Target test passed
✓ Regression passed

Changed:
  src/auth/client.py
  tests/test_login.py

Status: COMPLETED
```

然后：

```bash
$ codeteam diff ses_abc123
```

以及：

```bash
$ codeteam resume ses_abc123
```

这比 README 前面写 2000 字理念有用得多。

---

# 六十九、Week 4 的每日时间重点

建议大概：

| Day | 主能力                    |    难度 |
| --- | ---------------------- | ----: |
| 1   | Issue → Plan → State   |   ★★★ |
| 2   | Verification / Repair  |  ★★★★ |
| 3   | Error / Retry          |   ★★★ |
| 4   | Persistence / Resume   | ★★★★★ |
| 5   | Compaction / Providers | ★★★★★ |
| 6   | CLI Integration        |  ★★★★ |
| 7   | Evaluation / README    |  ★★★★ |

**Day 4、Day 5 不建议赶进度。**

它们是这一周最有 Agent Runtime 含金量的部分。

---

# 七十、Week 4 的阶段验收我建议重新细化成这样

你原来的验收完全保留，在此基础上增加工程证据：

```text
Product

[ ] codeteam run "<task>"
[ ] codeteam resume <session-id>
[ ] codeteam diff <session-id>
[ ] codeteam rollback <checkpoint-id>


Single Agent

[ ] Natural Language → Task
[ ] Repository inspection
[ ] Plan
[ ] Patch
[ ] Verification
[ ] Repair loop
[ ] Final result


Persistence

[ ] Ctrl+C 可以暂停
[ ] 新进程 Resume
[ ] Plan 恢复
[ ] Usage 恢复
[ ] Checkpoint 恢复
[ ] Worktree 状态校验


Context

[ ] Long session 可 compact
[ ] 用户约束不依赖 summary 保存
[ ] Repo instructions 重新注入
[ ] Active Plan preserved


Models

[ ] Provider A
[ ] Provider B
[ ] Session 保存 provider/model
[ ] Turn boundary 可切换
[ ] Provider error normalized


Evaluation

[ ] 15 个自建 Task
[ ] Success Rate
[ ] Cost
[ ] Duration
[ ] Token
[ ] Repair Attempts
[ ] Failure Cases


Engineering Evidence

[ ] Tests
[ ] Design Decisions
[ ] Benchmarks
[ ] Ablation
[ ] Failure Case Database
[ ] README
```

---

# 七十一、我建议给 Week 4 一个额外的“Stretch Goal”

你原始验收没有规定：

```text
15 个任务至少成功多少个
```

所以不要擅自把一个数字包装成原要求。

但作为项目内部目标，我建议第一版争取：

```text
≥ 12 / 15
```

也就是：

```text
≥ 80%
```

如果最终只有：

```text
9 / 15
```

也不要为了好看修改任务。

反而应该分析：

```text
失败集中在哪类？

Context？
Planning？
Patch？
Testing？
Model？
```

这才是 Evaluation 能力。

---

# 七十二、Week 4 最值得形成的 Design Decision 文档

至少建议有 6 个：

```text
DD-W4-01
Structured Plan vs Free-form Plan

DD-W4-02
Test-driven Repair Loop

DD-W4-03
Typed Error Taxonomy

DD-W4-04
Durable Session State vs Runtime Serialization

DD-W4-05
Structured Context Compaction

DD-W4-06
Provider-neutral Model Runtime
```

这六个会成为你后面面试非常重要的材料。

---

# 七十三、第 4 周结束后，你应该能够回答这些面试问题

### Agent Loop

```text
自然语言 Issue 是怎么变成 Patch 的？

为什么 Coding Agent 要有 Plan？

Plan 怎么失效？怎么 Replan？
```

### Verification

```text
怎么证明 Bug 真修了？

为什么 Test Failure 是 Observation 而不是 Agent Failure？

怎样防止无限 Repair？
```

### Runtime

```text
Agent 进程被杀后怎么 Resume？

Session 里哪些状态必须持久化？

哪些对象绝对不能序列化？
```

### Context

```text
Session Persistence 和 Context Compaction 有什么区别？

为什么不能简单截掉旧消息？

Compaction 后怎样防止关键约束丢失？
```

### Models

```text
Provider 和 Model 有什么区别？

怎么支持两个 Provider？

Model 切换为什么只能发生在 Turn Boundary？

如何统一不同 Provider Error？
```

### Evaluation

```text
你的 Agent Success Rate 是怎么定义的？

15 个 Task 怎么防止 Evaluation 泄题？

你做过什么 Ablation？

你的 Agent 最常失败在哪里？
```

---

# 七十四、第 4 周在整个项目中的真正意义

前三周以后，你可以说：

```text
我实现过：

Context Engine
Patch
Worktree
Checkpoint
Policy
Approval
Sandbox
```

但面试官仍然可以问：

> **“那你的 Agent 到底能不能真的完成一个 Coding Task？”**

第 4 周就是回答这个问题。

最终：

```text
Natural-language Issue
          │
          ▼
        Plan
          │
          ▼
   Context Retrieval
          │
          ▼
        Patch
          │
          ▼
       Verify
          │
    ┌─────┴─────┐
    ▼           ▼
   PASS         FAIL
    │            │
    │       classify error
    │            │
    │       repair / replan
    │            │
    └────────────┘
          │
          ▼
        Result
          │
   ┌──────┼───────┐
   ▼      ▼       ▼
Session  Diff   Metrics
```

这才是真正的：

# `codeteam-single-agent`

而且它第一次能提供完整的三层证据：

```text
Engineering Evidence
→ 能完成任务、能 Resume、能 Rollback

Experimental Evidence
→ 15 Task、Success/Cost/Time、Ablation

Recruiting Evidence
→ 能解释 Agent Loop、Context、Recovery、
   Model Runtime、Evaluation 和失败边界
```

从求职角度看，**Week 4 很可能比你前面任意单独一周都重要**：前三周证明你会造 Runtime Primitive，第 4 周开始证明你能够把这些 Primitive 组成真正可运行、可恢复、可评测的 Agent Harness。

[1]: https://developers.openai.com/codex/cli/features "Codex CLI | ChatGPT Learn"
[2]: https://docs.github.com/copilot/concepts/agents/cloud-agent/about-cloud-agent "About GitHub Copilot cloud agent - GitHub Docs"
[3]: https://developers.openai.com/codex/learn/best-practices "Best practices | ChatGPT Learn"
[4]: https://docs.github.com/copilot/concepts/agents/cloud-agent/about-cloud-agent?utm_source=chatgpt.com "About GitHub Copilot cloud agent"
[5]: https://aider.chat/docs/usage/lint-test.html "Linting and testing | aider"
[6]: https://developers.openai.com/codex/app-server?utm_source=chatgpt.com "Codex App Server"
[7]: https://docs.anthropic.com/en/docs/claude-code/hooks?utm_source=chatgpt.com "Hooks reference - Claude Code Docs"
[8]: https://docs.github.com/en/copilot/how-tos/copilot-sdk/hooks/error-handling?utm_source=chatgpt.com "Error handling hook"
[9]: https://docs.anthropic.com/en/docs/claude-code/troubleshooting?utm_source=chatgpt.com "Troubleshooting - Claude Code Docs"
[10]: https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/chronicle "Using GitHub Copilot CLI session data - GitHub Docs"
[11]: https://docs.anthropic.com/en/docs/claude-code/costs "Manage costs effectively - Claude Code Docs"
[12]: https://docs.github.com/en/copilot/concepts/agents/copilot-cli/context-management?utm_source=chatgpt.com "Managing context in GitHub Copilot CLI"
[13]: https://developers.openai.com/codex/changelog?utm_source=chatgpt.com "ChatGPT & Codex changelog"
[14]: https://docs.anthropic.com/en/docs/claude-code/hooks-guide?utm_source=chatgpt.com "Automate actions with hooks - Claude Code Docs"
[15]: https://docs.anthropic.com/en/docs/claude-code/memory?utm_source=chatgpt.com "How Claude remembers your project - Claude Code Docs"
[16]: https://developers.openai.com/codex/config-advanced?utm_source=chatgpt.com "Advanced Configuration | ChatGPT Learn"
[17]: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference "GitHub Copilot CLI command reference - GitHub Docs"
[18]: https://docs.anthropic.com/en/docs/claude-code/model-config "Model configuration - Claude Code Docs"
[19]: https://typer.tiangolo.com/tutorial/subcommands/?utm_source=chatgpt.com "SubCommands - Command Groups"
[20]: https://docs.python.org/3/library/argparse.html?utm_source=chatgpt.com "argparse — Parser for command-line options, arguments ..."
[21]: https://typer.tiangolo.com/tutorial/commands/?utm_source=chatgpt.com "Commands"
[22]: https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/manage-and-track-agents?utm_source=chatgpt.com "Managing agent sessions - GitHub Copilot"
