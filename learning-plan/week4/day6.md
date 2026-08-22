# 第 4 周 Day 6：CLI Productization

今天和前五天的性质又不一样。

前五天实际上已经逐渐形成了一个完整的 Single-Agent Runtime：

```text
Day 1
TaskSpec → Plan → Execution State

Day 2
Patch → Verification → Repair

Day 3
Failure → Classification → Recovery

Day 4
Session → Persistence → Resume

Day 5
Context Compaction → Provider / Model Runtime
```

但现在这些能力主要还是：

```text
Python API
Class
Service
Manager
```

也就是说，你可能可以在 Python 里：

```python
orchestrator.run(...)
session_service.resume(...)
checkpoint_manager.rollback(...)
```

但一个真正的用户并不应该需要理解这些。

今天要建立的是：

```text
                    Human / Script
                          │
                          ▼
                       codeteam
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
         run            resume           diff
                                           │
                                      rollback
                          │
                          ▼
               Application Services
                          │
                          ▼
                  Agent Runtime
```

所以今天最重要的一句话是：

> **CLI Productization 不是给现有 Python 函数套几个命令名，而是给整个 Agent Runtime 建立一个稳定、可理解、可自动化的用户接口契约。**

OpenAI 当前把 Codex CLI 定位为在终端中完成代码探索、规划、编辑、执行工具、审查 Diff 和持续跟进任务的完整工作 Surface，同时提供 `codex resume` 恢复 Session 和 `codex exec` 进行脚本/CI 式非交互运行。

Claude Code 当前同样支持 `claude`、`--continue`、`--resume`、非交互 `-p`，以及 text/json/stream-json 等不同输出形式。 GitHub Copilot CLI 也把 Session Resume、Worktree、程序化 Prompt、JSONL Output 都作为 CLI 的一等能力。

这几个工业产品共同说明：

> **Terminal 不只是 Agent 的 Debug 入口，而是 Coding Agent 本身的一个正式 Product Surface。**

---

# 一、CLI Productization 到底是在 Productize 什么？

首先避免一个误区：

```text
CLI Productization
≠
把：

python main.py

改名：

codeteam
```

真正 Productize 的是以下几件事：

```text
Runtime Capability
        ↓
Stable Command Contract

Runtime State
        ↓
Understandable User Feedback

Runtime Failure
        ↓
Stable Error / Exit Semantics

Long-running Task
        ↓
Interrupt / Resume Workflow

Internal Events
        ↓
Human-readable Progress

Application API
        ↓
Terminal Interface
```

也就是说，到昨天为止你的 Runtime 可能知道：

```text
TaskStatus
SessionStatus
PlanStepStatus
VerificationStatus
AgentFailure
RecoveryAction
```

今天要解决：

> **普通开发者到底怎么“看到”和“操纵”这些状态？**

---

# 二、最核心的架构原则：CLI = Interface Layer

这是今天必须真正理解的 Design Decision。

正确架构应该是：

```text
ARGV
 │
 ▼
┌─────────────────────────────┐
│          CLI Layer          │
│                             │
│ Parse arguments             │
│ Validate CLI syntax         │
│ Convert to request DTO      │
│ Select output renderer      │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│     Application Service     │
│                             │
│ SessionService              │
│ SingleAgentOrchestrator     │
│ CheckpointManager           │
│ GitWorkspace                │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│       Agent Runtime         │
│                             │
│ Context / Model / Git       │
│ Policy / Sandbox / Repair   │
└─────────────┬───────────────┘
              │
              ▼
         Domain Result
              │
              ▼
┌─────────────────────────────┐
│         Presenter           │
│ Human / JSON / Quiet        │
└─────────────┬───────────────┘
              │
              ▼
          Exit Code
```

最重要的是：

```text
CLI
→ 调 Application Service
```

而不是：

```text
CLI
→ 自己实现业务流程
```

---

# 三、什么叫“Fat CLI”

下面这种代码是今天最应该避免的：

```python
@app.command()
def run(task: str):
    repo = scan_repo()
    branch = create_worktree()
    model = OpenAIClient(...)
    plan = create_plan(...)
    patch = model.generate(...)
    apply_patch(patch)
    subprocess.run(["pytest"])
    save_session(...)
```

表面上：

```bash
codeteam run "fix bug"
```

能用了。

但实际上：

```text
所有 Runtime Logic
都被塞进 CLI Handler
```

这会带来一系列问题：

```text
未来 Web API
无法复用

未来 IDE Plugin
无法复用

Unit Test CLI
必须真的启动 Model

Command Handler 无法 Mock Service

Runtime Logic 与 Typer 强绑定

Session Resume 逻辑到处重复
```

---

# 四、正确 CLI Handler 应该多薄

理想上：

```python
@app.command()
def run(
    task: str,
    provider: str | None = None,
    model: str | None = None,
):
    request = RunRequest(
        task=task,
        provider=provider,
        model=model,
    )

    result = services.session_service.run(
        request
    )

    renderer.render(result)

    raise typer.Exit(
        code=exit_code_mapper.map(result)
    )
```

CLI 做了五件事：

```text
1. Parse

2. Construct request

3. Call service

4. Render result

5. Return exit code
```

没有：

```text
Git logic
LLM logic
Docker logic
Checkpoint logic
Repair logic
```

这就是：

# Thin CLI

---

# 五、工业上为什么这很重要

Codex 当前同时存在：

```text
Interactive CLI

codex exec

App Server

SDK

Cloud
```

它不可能把真正 Agent Runtime 全写在某一个 CLI Command Handler 中。Codex CLI 可以用于交互开发，而 `codex exec` 则可以用于脚本和 CI。

Claude Code 同样同时提供：

```text
Interactive CLI

Print / headless mode

Agent SDK

IDE / Desktop / Web
```

CLI 只是多个 Surface 之一。

这就是为什么你的 CodeTeam 从现在开始也应该建立：

```text
Agent Runtime
      ▲
      │
 ┌────┼───── future
 │    │
CLI  API  IDE
```

而不是：

```text
CLI = Agent Runtime
```

这对以后做 Agent Harness / Runtime 项目非常重要。

---

# 六、今天的四个 Command，本质其实是四个 Use Case

你要求：

```bash
codeteam run "修复登录超时问题"

codeteam resume <session-id>

codeteam diff <session-id>

codeteam rollback <checkpoint-id>
```

不要只理解成四个命令字符串。

它们代表四种完全不同的 Runtime Capability：

| Command | Runtime Capability | Side Effect |
|---|---|---|
| `run` | 创建并执行 Task | 有 |
| `resume` | 恢复已有 Task | 有 |
| `diff` | 检查 Task 修改 | **无** |
| `rollback` | 恢复 Workspace State | 有 |

所以 CLI Layer 需要尊重这些语义。

---

# 七、`codeteam run`：创建一个新的 Agent Task

用户执行：

```bash
codeteam run "修复登录超时问题"
```

推荐内部流程：

```text
Parse CLI
    │
    ▼
Validate task text
    │
    ▼
Resolve repository
    │
    ▼
Resolve provider / model
    │
    ▼
Create Session
    │
    ▼
PRINT SESSION ID
    │
    ▼
Create task Worktree
    │
    ▼
Create initial Checkpoint
    │
    ▼
SingleAgentOrchestrator.run()
    │
    ▼
Task execution
    │
    ▼
Final Result
```

其中有一个小细节非常重要：

# Session ID 要尽早显示

例如：

```text
Session: ses_7f32...
```

应该在真正长时间运行之前就给用户。

为什么？

因为：

```text
LLM 第一次调用
Docker
Repo Scan
```

都有可能失败。

如果用户连 Session ID 都不知道：

```text
任务刚启动
→ Agent crash
```

他根本不知道：

```bash
codeteam resume ???
```

所以推荐：

```text
基本环境验证
        ↓
创建 Session
        ↓
打印 Session ID
        ↓
真正运行
```

---

# 八、`run` 的 CLI Options 应该怎么想

Day 6 第一版不要加 40 个 Flag。

核心可以只有：

```bash
codeteam run "task" \
  --provider provider-a \
  --model model-x
```

可以考虑：

```text
--provider
--model
--repo
--verbose
```

但我建议把下面两个接口**现在就纳入架构考虑**，不一定 Day 6 全部实现：

```text
--json

--quiet
```

因为它们会直接影响 Presenter Architecture。

后面解释为什么。

---

# 九、`run` 的 Provider / Model 不应该自己解析业务逻辑

CLI：

```text
--provider provider-a
--model model-x
```

只构造：

```text
ModelSelectionOverride
```

然后交给 Day 5：

```text
ProviderRegistry
ModelSelection
ModelMetadata
```

去验证。

CLI 不应该：

```python
if provider == "openai":
    client = OpenAI(...)
```

否则昨天刚做好的 Provider-neutral Runtime 今天就被 CLI 绕开了。

---

# 十、`codeteam resume`：不是重新执行 `run`

用户：

```bash
codeteam resume ses_123
```

错误实现：

```text
load task.prompt

↓

run(task.prompt)
```

这不是 Resume。

正确：

```text
Session ID
   │
   ▼
SessionService.resume()
   │
   ├── load
   ├── schema validation
   ├── repo reconciliation
   ├── worktree reconciliation
   ├── checkpoint validation
   ├── provider/model restoration
   ├── context restoration
   └── runtime reconstruction
   │
   ▼
continue state machine
```

这就是 Day 4 所建立的能力。

---

# 十一、工业 CLI 的 Resume 都越来越强调 Session Identity

Codex 当前：

```text
codex resume <SESSION_ID>
```

可以恢复指定 Session；`--last` 默认在当前 Working Directory 范围内寻找最近 Session，`--all` 才扩大范围。

Claude Code 当前：

```text
claude --continue

claude --resume <session>
```

可以按 ID、名称或 Picker 恢复；Session 持续保存到本地。

GitHub Copilot CLI 的 `--resume` 支持 Session ID、ID Prefix、Session Name；一个很值得学习的细节是：如果在非 TTY 环境下无法打开 Session Picker，它会**报错退出，而不是偷偷创建一个新 Session**。

这个行为很值得 CodeTeam 学习：

> **Resume 解析失败时，Fail Explicitly，不要猜你想干什么。**

---

# 十二、因此 `resume` 有一个重要不变量

```text
用户要求：
resume ses-123
```

如果：

```text
ses-123
不存在
```

必须：

```text
SESSION_NOT_FOUND
exit != 0
```

绝不能：

```text
创建新的 ses-123
```

也不能：

```text
重新运行 Task
```

这是非常重要的 CLI Contract。

---

# 十三、Resume 时建议先显示“恢复点”

例如：

```text
Session: ses_123

Task:
修复登录超时问题

Status:
PAUSED

Plan:
3 / 5 completed

Current:
P4 Run targeted verification

Worktree:
.codeteam/.../task-123

Model:
provider-a / model-x

Resuming...
```

用户立即知道：

> Agent 到底从哪里继续。

而不是：

```text
Resuming...
```

等 20 秒不知道发生什么。

---

# 十四、`codeteam diff` 是今天特别值得设计好的命令

你的：

```bash
codeteam diff <session-id>
```

应该有一个非常强的不变量：

# READ ONLY

也就是说：

```text
Model calls
= 0

Patch calls
= 0

Checkpoint creation
= 0

Command side effects
= 0
```

流程：

```text
session-id
    │
    ▼
SessionStore.load()
    │
    ▼
resolve Task Worktree
    │
    ▼
validate ownership
    │
    ▼
GitWorkspace.diff()
    │
    ▼
print
```

---

# 十五、`diff` 为什么一定不能经过 Agent

假设用户只是：

```bash
codeteam diff ses123
```

如果 Runtime：

```text
先调用 LLM
“请总结一下 diff”
```

那么：

```text
增加 Cost
增加 Latency
可能触发 Tool
甚至可能修改 Workspace
```

完全违背：

```text
diff
```

的用户预期。

所以：

> **Inspection Commands 应该与 Agentic Commands 明确分层。**

---

# 十六、Codex 当前也明确区分 Review / Diff 与修改

Codex 当前可以针对：

```text
uncommitted changes

commit

base branch
```

做 Review，而且官方明确说明 Review 本身不会修改 Working Tree；交互式 `/review` 后还可以使用 `/diff` 检查确切文件修改。

CodeTeam 的：

```text
diff
```

甚至应该更简单：

> 不让模型“Review”，直接展示 Git 事实。

---

# 十七、Session Diff 到底应该和谁比较

这个需要你正式定义 Contract。

如果 Session 创建时：

```text
base_sha = A
```

现在 Task Worktree：

```text
HEAD = T
Working Tree 还有修改
```

用户想看的其实是：

> **这个 Session 相对开始任务时产生了什么变化？**

所以长期来看更合理的语义是：

```text
Session Diff

=
Current Task Workspace State
vs
Session Base State
```

而不是简单：

```text
git diff HEAD
```

因为 Agent 将来可能：

```text
在 Task Branch 提交过 Commit
```

如果你只：

```text
git diff HEAD
```

已经 Commit 的改变就消失了。

---

# 十八、所以建议定义一个明确 API

不要让 CLI 自己：

```python
subprocess.run(
    ["git", "diff", ...]
)
```

而应该：

```text
GitWorkspace.diff_session(
    base_sha=session.base_sha
)
```

或者沿用现有：

```text
GitWorkspace.diff(...)
```

但其 Contract 必须明确：

```text
是否包含：
tracked

staged

unstaged

untracked

committed task delta
```

Week 3 你已经定义过 GitWorkspace 的状态模型，今天只是在 CLI Surface 上把它暴露出来。

---

# 十九、`diff` 没有变化也不是错误

例如：

```bash
codeteam diff ses123
```

结果：

```text
No changes.
```

Exit Code：

```text
0
```

因为：

```text
没有 Diff
```

不是：

```text
Command Failure
```

这个细节对 CLI Scriptability 很重要。

---

# 二十、`codeteam rollback` 的语义完全不同

用户：

```bash
codeteam rollback cp_123
```

这明确意味着：

```text
我要修改当前 Workspace State
```

所以流程不能像 diff 一样简单。

应该：

```text
checkpoint-id
       │
       ▼
CheckpointStore.lookup()
       │
       ▼
Validate checkpoint ownership
       │
       ├── task_id
       ├── worktree
       └── session relation
       │
       ▼
Validate task workspace
       │
       ▼
Create safety checkpoint
       │
       ▼
CheckpointManager.rollback()
       │
       ▼
Verify restored state
       │
       ▼
Update Session
       │
       ▼
append rollback event
```

---

# 二十一、Checkpoint Ownership 为什么是强安全边界

假设：

```text
cp-001
属于 task-A
```

用户：

```text
当前控制 task-B
```

执行：

```bash
codeteam rollback cp-001
```

如果不验证 Ownership：

```text
task-B
可能被 task-A 的 Snapshot 覆盖
```

这会直接破坏 Week 3：

```text
Task Isolation
```

所以至少必须验证：

```text
checkpoint.task_id
==
session.task_id

checkpoint worktree
==
managed task worktree

worktree != main
```

不能只验证：

```text
checkpoint ID 存在。
```

---

# 二十二、Rollback 是否需要 ApprovalManager？

这里要区分两件事。

Agent 自己决定：

```text
我要 rollback
```

属于 Runtime Internal Recovery，需要安全 Policy。

但用户明确在 CLI 输入：

```bash
codeteam rollback cp123
```

已经形成了一个非常明确的：

```text
Direct User Intent
```

MVP 中通常没必要再弹一次 Agent Approval。

但是可以考虑：

```text
当前 Workspace 有新修改
即将被恢复
```

时：

```text
interactive confirmation
```

例如：

```text
Rollback will restore checkpoint cp123.

Current uncommitted changes will be replaced.
A safety checkpoint will be created.

Continue? [y/N]
```

脚本模式：

```bash
--yes
```

这是 CLI UX 层面的 Confirmation，

不是 Week 3：

```text
Agent ApprovalManager
```

两者语义不同。

---

# 二十三、推荐增加 `sessions`

虽然不是本周硬验收，但它价值很高。

```bash
codeteam sessions
```

可以输出：

```text
SESSION       STATUS       UPDATED       TASK
ses_7f1       RUNNING      2m ago        修复登录超时
ses_81a       PAUSED       1h ago        添加 CLI verbose
ses_9ce       COMPLETED    yesterday     修复 parser
```

它解决：

> 我忘记 Session ID 了怎么办？

而不应该让用户去：

```text
ls ~/.codeteam/sessions/
```

---

# 二十四、工业产品都在解决“找 Session”问题

Codex `resume` 默认可以打开 Session 选择器，也提供 `--last` / `--all`。

Claude Code 提供 `/resume` Picker、按 ID/Name 恢复，并允许给 Session 命名。

GitHub Copilot CLI `--resume` 同样可以按 ID、ID Prefix 或 Name 找 Session。

所以：

```text
sessions
```

最终很可能不是“可有可无”，而会成为一个很好用的 Product Feature。

---

# 二十五、`status` 同样应该 READ ONLY

```bash
codeteam status ses123
```

推荐显示：

```text
Session:
ses123

Session status:
PAUSED

Task status:
VERIFYING

Task:
修复登录超时问题

Plan:
3 / 5 completed

Current step:
P4 targeted verification

Provider:
provider-a

Model:
model-x

Worktree:
...

Checkpoint:
cp004

Tokens:
18,423

Cost:
...

Updated:
...
```

同样：

```text
LLM calls = 0
Tool side effects = 0
```

---

# 二十六、一个好 CLI 最重要的不是“好看”

今天 Productization 很容易跑偏到：

```text
Spinner
Rich Table
Gradient
ASCII Logo
```

这些可以后做。

对于 Coding Agent，真正重要的 UX 是：

```text
我现在在做什么？

为什么还没结束？

当前 Session 是哪个？

有没有修改文件？

测试过了吗？

失败在哪里？

我还能 Resume 吗？

最后到底成功没？
```

---

# 二十七、所以输出应该围绕 Runtime Events

不要让 Orchestrator：

```python
print("running test...")
```

更好的架构：

```text
Runtime
   │
   ▼
EventBus / EventSink

task.started
repo.inspected
plan.created
patch.applied
verification.started
verification.completed
repair.started
task.completed

   │
   ▼
CLI EventRenderer
   │
   ▼
Terminal
```

这会把：

```text
Runtime Logic
```

与：

```text
Terminal Rendering
```

彻底分开。

---

# 二十八、你前几周做的 Event Log 现在终于成为 UI 数据源

例如 Runtime 发出：

```text
repository.inspection_started
```

CLI Render：

```text
[inspect] repository
```

Runtime：

```text
plan.created
step_count=5
```

CLI：

```text
[plan] 5 steps
```

Runtime：

```text
patch.applied
files=["src/auth/client.py"]
```

CLI：

```text
[edit] src/auth/client.py
```

Runtime：

```text
verification.completed
kind=target
passed=7
```

CLI：

```text
[test] 7 passed
```

也就是说：

```text
Runtime Event
≠
UI String
```

Presenter 决定怎么显示。

---

# 二十九、为什么不要把所有内部细节打印出来

用户不需要看到：

```text
Model Request 42

Reasoning tokens ...

Raw Plan JSON

Symbol rank 0.723

Patch hash...

Docker command...

Policy rule aggregation...
```

正常模式应该：

```text
任务进展
+
关键决策
+
重要风险
+
结果
```

Debug 模式：

```bash
codeteam run ... --verbose
```

才进一步显示：

```text
retrieval
policy
tool
model
events
```

而隐藏的模型推理过程本身不应作为 CLI Debug Log。

---

# 三十、推荐三个 Output Level

今天至少架构上考虑：

```text
NORMAL

QUIET

VERBOSE
```

Normal：

```text
[inspect]
[plan]
[edit]
[test]
...
```

Quiet：

```text
只输出最终结果
```

Verbose：

```text
额外显示 Runtime Events
```

以后：

```text
--json
```

不是第四个 Level，

而是：

```text
Output Format
```

---

# 三十一、工业 CLI 为什么普遍支持机器可读输出

GitHub Copilot CLI 当前：

```text
--output-format=text

--output-format=json
```

其中 JSON 是 JSONL：每行一个 JSON Event；还提供 `--silent` 方便脚本使用。

Claude Code 当前则支持：

```text
text

json

stream-json
```

并且非交互模式还能限制 `--max-turns`。

这说明工业 Coding Agent CLI 通常同时服务：

```text
Humans

and

Scripts / CI
```

所以 CodeTeam 虽然 Day 6 不一定必须实现：

```text
--json
```

但现在的 Presenter 设计一定不要把这个未来堵死。

---

# 三十二、建议 CodeTeam 未来的输出结构

Human：

```bash
codeteam run "fix timeout"
```

输出：

```text
Session: ses_123

[inspect] repository
[plan] 5 steps
[edit] src/auth/client.py
[test] targeted: failed
[repair] attempt 1
[test] targeted: passed
[verify] regression: 42 passed

Status: COMPLETED
Duration: 2m31s
Tokens: 18,211
Cost: $...
Files changed: 2
```

机器模式：

```bash
codeteam run "fix timeout" --json
```

概念输出：

```jsonl
{"type":"session.created","session_id":"ses_123"}
{"type":"repository.inspected"}
{"type":"plan.created","steps":5}
{"type":"patch.applied","files":["src/auth/client.py"]}
{"type":"verification.completed","status":"failed"}
{"type":"repair.started","attempt":1}
{"type":"task.completed","status":"completed"}
```

---

# 三十三、stdout 和 stderr 也应该设计

这是 CLI 工程里经常被忽略的地方。

建议长期遵循：

```text
stdout
=
真正的 Command Result


stderr
=
progress / diagnostics / warnings
```

例如：

```bash
codeteam diff ses123 > change.patch
```

用户期望：

```text
change.patch
```

里面只有 Diff。

如果你把：

```text
Loading session...
Repository ready!
```

也打印 stdout，

文件直接坏了。

所以：

```text
diff content
→ stdout

progress / warnings
→ stderr
```

---

# 三十四、这对 JSON 模式更重要

如果：

```bash
codeteam run task --json | jq ...
```

stdout 中突然混进：

```text
Loading provider...
```

整个 JSON Pipeline 就坏了。

所以机器模式的一个强不变量应该是：

```text
stdout
=
valid machine-readable protocol
```

普通 Log：

```text
stderr
```

或者完全关闭。

---

# 三十五、TTY 和 Non-TTY 是两个不同环境

TTY 可以理解：

```text
用户真的在终端面前交互
```

Non-TTY：

```text
CI

pipe

redirect

script
```

例如：

```bash
codeteam run task > result.txt
```

此时：

```text
interactive prompt
```

可能永远没人回答。

GitHub Copilot CLI 当前一个值得学习的行为是：当 `--resume` 需要 Picker、但当前并非 TTY 时，如果无法确定 Session，它会直接报错，而不是进入无法使用的交互或偷偷创建新 Session。

所以 CodeTeam 建议：

```text
if interactive prompt required
and not TTY:

    fail with clear message
```

例如 rollback：

```text
non-TTY
+
needs confirmation
+
no --yes

→ exit non-zero
```

---

# 三十六、第一版不需要做完整 TUI

这是今天特别需要控制 Scope 的地方。

不要看到：

```text
Codex
Claude Code
Copilot
```

界面很丰富，就决定 Day 6：

```text
做一个 curses UI
多 Pane
实时 Token Graph
键盘导航
```

完全没必要。

你的 MVP：

```text
line-oriented streaming CLI
```

就足够。

先保证：

```text
Command Contract

Output Contract

Exit Contract

Resume

Interrupt

Testing
```

稳定。

以后 TUI 只是：

```text
Presenter replacement
```

---

# 三十七、Exit Code 是 CLI API 的一部分

人类看：

```text
Status: FAILED
```

可以理解。

CI 看不到“语义”，它只知道：

```bash
echo $?
```

所以：

```text
Exit Code
```

是你的 CLI 和 Shell/CI 之间的 Contract。

Typer 官方测试文档本身也以：

```python
result.exit_code == 0
```

作为命令成功的重要断言。

---

# 三十八、不要所有命令都 Exit 0

错误：

```text
Task failed.

exit 0
```

Shell：

```bash
codeteam run task && deploy
```

会继续：

```text
deploy
```

非常危险。

所以：

```text
successful command
→ 0

unsuccessful command
→ non-zero
```

是基本原则。

---

# 三十九、但也不要设计 70 个 Exit Code

Day 3 已经有：

```text
AgentErrorCode
```

它可以非常细。

CLI Exit Code 建议粗一点。

例如第一版可以定义：

| Exit | CLI Meaning |
|---:|---|
| `0` | Success |
| `2` | CLI usage / invalid arguments |
| `10` | Resource/state not found or invalid |
| `20` | Task/runtime failure |
| `30` | Security/authorization blocked |
| `130` | User interrupt |

详细原因：

```text
SESSION_NOT_FOUND

PATCH_CONTEXT_MISMATCH

MODEL_AUTH_FAILED
```

放：

```text
Error message / JSON result
```

不要塞进 Shell Exit Code。

---

# 四十、为什么 `Ctrl+C` 建议是特殊退出

用户：

```text
Ctrl+C
```

应该触发：

```text
KeyboardInterrupt
     │
     ▼
CLI catches at outer boundary
     │
     ▼
orchestrator.cancel_current()
     │
     ▼
CommandRunner kills process tree
     │
     ▼
SessionService.pause()
     │
     ▼
persist
     │
     ▼
print resume command
     │
     ▼
exit 130
```

重要：

```text
Ctrl+C
≠
Task Failed
```

它表示：

```text
User Interrupted
```

Session：

```text
PAUSED
```

而不是：

```text
FAILED
```

---

# 四十一、为什么 Ctrl+C 应该在 CLI 最外层接住

如果：

```text
VerificationService
```

内部：

```python
except KeyboardInterrupt:
    return VerificationStatus.FAILED
```

那 Runtime 会认为：

```text
Test Failed
→ Repair
```

于是用户按 Ctrl+C：

```text
Agent 反而继续修代码。
```

这就是非常严重的 Control-flow Bug。

所以：

```text
User Interrupt
```

必须一路传播到：

```text
Application Boundary
```

由 Session Lifecycle 处理。

---

# 四十二、还有一个重要点：先清理，再保存 PAUSED

和 Day 4 一致：

错误：

```text
Session = PAUSED
save

↓

后台 pytest 仍然运行
```

正确：

```text
stop new work

↓

interrupt active process

↓

reap child processes

↓

persist PAUSED

↓

exit
```

否则用户：

```bash
codeteam resume
```

时可能同时有：

```text
旧 pytest

新 pytest
```

两个进程。

---

# 四十三、Typer 为什么比较适合 CodeTeam

Typer 很适合当前项目，主要不是因为它“好看”，而是它与 Python 类型模型比较自然。

Typer 官方本身支持 Command/SubCommand Group，并且 CLI Parameter 能直接映射 Python Type；官方也提供 `CliRunner` 用于在 pytest 中直接 invoke CLI 并断言 Exit Code 和 Output。

你的命令：

```text
run
resume
diff
rollback
sessions
status
```

正是非常标准的：

```text
Command Group
```

---

# 四十四、推荐最初目录结构

你原本：

```text
cli/
├── app.py
└── commands.py
```

对于 Day 6 MVP 完全合理。

建议：

```text
codeteam/
└── cli/
    ├── app.py
    └── commands.py
```

`app.py`：

```text
Typer App

global options

entry point
```

`commands.py`：

```text
run
resume
diff
rollback
```

等输出模式开始复杂以后再拆：

```text
renderers.py
exit_codes.py
```

现在不要过度工程化。

---

# 四十五、`app.py` 应该长什么样

概念：

```python
app = typer.Typer(
    name="codeteam",
    help="Local coding agent runtime.",
)
```

然后：

```text
register commands
```

最终 Python Package 暴露：

```text
codeteam
```

而不是要求用户：

```bash
python -m codeteam.cli.app
```

---

# 四十六、Python Package 最终需要 Console Entry Point

概念上：

```toml
[project.scripts]
codeteam = "codeteam.cli.app:main"
```

于是安装以后：

```bash
codeteam --help
```

成为真正产品入口。

这一步看似简单，实际上完成了：

```text
Python Library
→
Developer Tool
```

的关键转换。

---

# 四十七、建议 CLI Command 和 Service Request 分开

例如：

```text
CLI:

task: str
provider: str
model: str

↓

RunSessionRequest

↓

SessionService.run()
```

而不是：

```text
SessionService.run(
    typer.Argument(...)
)
```

Application Layer 永远不应该依赖：

```text
Typer
Click
```

否则未来换：

```text
FastAPI
IDE Plugin
```

会非常麻烦。

---

# 四十八、Dependency Injection 也很重要

CLI 不应该：

```python
def run(...):
    session_store = JsonSessionStore(...)
    docker = DockerRunner(...)
    ...
```

每个 Command 都构建一次完整 Runtime。

建议有一个：

```text
ApplicationContainer

or

ServiceFactory
```

概念：

```text
build_services()
    │
    ├── SessionService
    ├── Orchestrator
    ├── CheckpointManager
    ├── ProviderRegistry
    └── GitWorkspaceFactory
```

CLI：

```text
services.session_service
```

即可。

---

# 四十九、但是这里还有一个非常重要的性能优化：Lazy Initialization

假设：

```bash
codeteam diff ses123
```

结果启动时初始化：

```text
OpenAI SDK

Anthropic SDK

Docker

Tree-sitter

Model Provider

Context Engine
```

用户可能等：

```text
2 秒
```

才看到 Diff。

完全没有必要。

因为：

```text
diff
```

只需要：

```text
SessionStore
GitWorkspace
```

所以推荐：

```text
Command-specific dependency construction
```

或者：

```text
lazy service initialization
```

---

# 五十、这是 CLI Startup Latency 最可能的性能来源

很多 Python CLI：

```text
代码实际上什么都没做
```

但：

```bash
tool --help
```

需要：

```text
1.5 秒
```

原因经常不是 CLI Framework，

而是 Top-level Import：

```python
import torch
import tree_sitter
import docker
import provider_sdk
...
```

所以：

```text
codeteam --help
```

最好：

```text
不初始化 Model

不探测 Docker

不 Scan Repo

不访问 Network
```

---

# 五十一、CLI Benchmark 应该怎么测

你原计划：

```text
CLI startup latency
```

可以拆成三种：

```text
codeteam --help

codeteam status ses123

codeteam diff ses123
```

分别跑例如：

```text
30~50 次
```

记录：

```text
P50
P95
```

这样可以发现：

```text
纯 CLI 初始化

Session loading

Git inspection
```

分别占多少。

---

# 五十二、但今天更值得关注的是 Time to First Feedback

假设：

```bash
codeteam run task
```

执行：

```text
10 秒
```

后才第一次输出：

```text
Session: ...
```

用户会觉得：

```text
“是不是挂了？”
```

所以我建议额外测：

# Time to First Feedback

从：

```text
process start
```

到：

```text
第一条有意义的 CLI Output
```

---

# 五十三、再增加 `Time to Session ID`

对长 Agent Task 特别重要：

```text
process start
↓
session id available
```

应该非常快。

因为这个 ID 是：

```text
Resume Handle
```

---

# 五十四、End-to-End Usability 怎么评估

今天性能 Benchmark 不是重点，真正重点是用户能不能自然完成：

```text
创建任务
↓
观察进度
↓
Ctrl+C
↓
Resume
↓
查看 Diff
↓
Rollback
```

因此可以建立一个小型 CLI Journey：

```text
Journey 1:
run → completed

Journey 2:
run → Ctrl+C → resume

Journey 3:
run → diff

Journey 4:
run → rollback

Journey 5:
invalid session

Journey 6:
invalid provider
```

每条都验证：

```text
用户是否知道下一步做什么？
```

这就是：

```text
End-to-End Usability
```

---

# 五十五、工业 CLI 一个非常值得学习的原则：错误信息应该是 Actionable

不要：

```text
Error: invalid session
```

更好：

```text
Session 'ses_123' was not found.

Run:
  codeteam sessions

to list available sessions.
```

再比如 Provider：

```text
Provider 'foo' is not configured.

Available providers:
  provider-a
  provider-b
```

也就是说：

> **Error Message 不只是告诉用户“错了”，还应该告诉他“接下来怎么办”。**

---

# 五十六、正常用户不应该看到 Python Traceback

例如：

```bash
codeteam resume abc
```

不要：

```text
Traceback (most recent call last):
...
KeyError
PydanticValidationError
...
```

正常模式：

```text
Session state is corrupted.

Session:
ses_abc

State:
~/.codeteam/...

Resume was stopped to avoid unsafe recovery.
```

如果：

```bash
--verbose
```

或开发 Debug Mode，

再输出详细 Cause。

这和 Day 3：

```text
Internal AgentFailure
≠
User-facing error
```

是同一种思想。

---

# 五十七、Secrets 也不能因为 CLI Debug 而直接输出

尤其：

```text
Provider Environment

API Key

Command argv

HTTP Error

Tool Result
```

可能带 Credential。

GitHub Copilot CLI 当前甚至提供针对 Environment Secret 的 Redaction Flag，并默认对部分 Token 环境变量做输出隐藏。

所以：

```text
--verbose
```

也不应该等于：

```text
disable secret sanitization
```

---

# 五十八、测试：不要只有 `CliRunner`

Typer 官方 `CliRunner` 非常适合：

```text
--help

argument parsing

exit code

output
```

它可以直接：

```python
runner.invoke(app, [...])
```

而无需启动真实 Shell Process。

但你的 CodeTeam 有：

```text
Ctrl+C

Session persistence

Child process

Installed executable
```

所以应该分三层测试。

---

# 五十九、Layer 1：CLI Unit Test

使用：

```text
CliRunner
+
Fake Services
```

例如：

```text
FakeSessionService
```

然后：

```bash
codeteam run "task"
```

验证：

```text
request.task == "task"

service.run calls == 1

exit_code == 0
```

不调用真实 Model。

---

# 六十、Layer 2：CLI Integration Test

临时 Repo：

```text
tmp_path/repo
```

真实：

```text
SessionStore

GitWorkspace

CheckpointManager
```

但 Model 可以：

```text
MockModelClient
```

验证：

```text
run

resume

diff

rollback
```

真实跨模块连接。

---

# 六十一、Layer 3：Subprocess E2E

真正启动：

```text
installed codeteam executable
```

例如：

```text
subprocess.Popen(
    ["codeteam", "run", ...]
)
```

这层才测试：

```text
实际 PATH Entry

Ctrl+C

OS Signal

Cross-process persistence

stdout/stderr

Exit Code
```

这是今天特别重要的一层。

---

# 六十二、为什么 Ctrl+C 不能只靠 CliRunner 测

你真正想证明的是：

```text
OS process
↓
SIGINT
↓
active child cleanup
↓
Session persisted
↓
process exits
↓
new process resumes
```

这必须：

```text
Process A
```

真的退出，

然后：

```text
Process B
```

重新启动。

否则你只是在测试一个：

```text
Python function
```

并没有证明：

# Crash / Interrupt Boundary

---

# 六十三、今天要求的测试建议这样定义

| Test | 最重要断言 |
|---|---|
| `--help` | 不加载 Heavy Runtime；exit 0 |
| `run` | 正确调用 SessionService；尽早显示 session ID |
| `resume` | 正确 Session；继续已有状态 |
| `diff` | **read-only；Model/Runner calls=0** |
| `rollback` | Checkpoint ownership verified |
| invalid session | 不创建新 Session |
| invalid checkpoint | Workspace unchanged |
| Ctrl+C | Session=PAUSED；children cleaned |
| invalid provider | 不开始 Task execution |
| exit code | 与 Domain Result 一致 |

---

# 六十四、我建议再补 10 个高价值 CLI Test

第一类是 **Non-TTY Prompt Test**：需要用户确认但 stdin 不是 TTY 时必须报错，而不是一直等待。

第二类是 **Diff stdout purity**：

```bash
codeteam diff ses > diff.txt
```

`diff.txt` 里不能出现 Progress Log。

第三类是 **No-change Diff**：没有变化时 Exit 0。

第四类是 **Resume Completed Session**：如果当前设计规定 Completed 不再 Resume，就必须明确报错或提示 fork/new task，不能重新执行。

第五类是 **Cross-repo Resume**：遵循 Day 4 Repository Identity，不静默切 Repo。

第六类是 **Concurrent Resume**：Session 已被另一个 Writer 持有时，CLI 给清楚错误。

第七类是 **Rollback Main Worktree Rejected**：任何错误 Checkpoint 映射都不能恢复 Main。

第八类是 **Verbose Secret Redaction**：即使 Verbose 也不能出现 Secret Canary。

第九类是 **Help Offline**：`codeteam --help` 不能需要网络、Docker、Provider。

第十类是 **Machine Output Stability**：如果后续加 `--json`，stdout 每一行都必须是合法 JSON。

---

# 六十五、你的最终 CLI Architecture 我建议形成这样

```text
                      Shell
                        │
                        ▼
                 ┌─────────────┐
                 │  Typer CLI  │
                 └──────┬──────┘
                        │
                 Parse / Validate
                        │
                        ▼
                 Command Request
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
      RunUseCase    ResumeUseCase   DiffUseCase
        │               │               │
        ▼               ▼               ▼
 SessionService    SessionService   GitWorkspace
        │               │               │
        ▼               ▼               │
  Orchestrator     Reconciliation        │
        │               │               │
        └───────────────┬───────────────┘
                        ▼
                    Domain Result
                        │
                        ▼
                  Event / Result
                        │
          ┌─────────────┼───────────────┐
          ▼             ▼               ▼
     HumanRenderer  JsonRenderer   QuietRenderer
          │             │               │
          └─────────────┴───────────────┘
                        │
                        ▼
                    Exit Code
```

Rollback：

```text
CLI
 ↓
Checkpoint Lookup
 ↓
Ownership Validation
 ↓
CheckpointManager
 ↓
Session Update
 ↓
Renderer
```

---

# 六十六、Design Decision：Fat CLI vs Thin CLI

今天应该正式记录：

```text
DD-W4-D6-01

CLI as Interface Layer
```

### Alternative A：Fat CLI

```text
Typer command
直接实现：
Git / Model / Session / Patch / Sandbox
```

优点：

```text
开发快
文件少
```

缺点：

```text
逻辑重复
不可复用
难测试
难增加 Web/IDE Surface
CLI Framework 与 Domain 耦合
```

---

### Alternative B：Thin CLI

```text
CLI
→ Request DTO
→ Application Service
→ Domain Result
→ Presenter
```

优点：

```text
可测试

可替换 Surface

Runtime 与 Typer 解耦

支持 Human / JSON Output

Command Contract 清楚
```

缺点：

```text
需要多一层 Application API

类型更多
```

Decision：

```text
B
```

这不是需要 Ablation 才能决定的“模型效果假设”，而是一个 Architecture Decision。

但仍可以通过：

```text
CLI handler LOC

Mockability

新增 API Surface 修改范围
```

等工程指标验证它的价值。

---

# 六十七、我还建议记录第二个 Design Decision

```text
DD-W4-D6-02

Event-driven CLI Rendering
```

Decision：

```text
Agent Runtime emits structured events.

CLI renders them.

Runtime must not print directly.
```

原因：

```text
Human CLI
JSON
Future TUI
IDE
Observability
```

全部可以复用同一个 Event。

这是一个非常有 Agent Harness 味道的设计。

---

# 六十八、Failure Case 1：CLI 自己实现 Runtime Logic

症状：

```text
run() 400 行

resume() 300 行

rollback() 200 行
```

最后：

```text
API 想复用 Agent
```

只能 Copy。

这是典型：

```text
Fat Controller
```

问题。

---

# 六十九、Failure Case 2：`diff` 意外产生 Side Effect

例如：

```text
diff
→ SessionService.resume()
→ Orchestrator
→ Model Call
```

严重违背用户预期。

因此最好做强测试：

```text
diff

Model calls = 0
Sandbox calls = 0
Command mutation = 0
Checkpoint writes = 0
```

---

# 七十、Failure Case 3：Resume 不存在 Session 时偷偷新建

这种 UX 看起来：

```text
“更智能”
```

实际上非常危险。

用户以为：

```text
继续以前的任务
```

实际：

```text
新任务从头开始
```

可能重新修改同一个 Repo。

必须：

```text
Fail Explicitly
```

GitHub Copilot CLI 当前在无法无歧义 Resume 且无法显示 Picker 的非 TTY 场景，也选择退出错误而不是默默开始新 Session。

---

# 七十一、Failure Case 4：Rollback 只看 Checkpoint ID

```text
checkpoint exists
→ restore
```

不验证：

```text
task
session
worktree
```

就是 Cross-task Corruption。

必须：

```text
Ownership First
```

---

# 七十二、Failure Case 5：Ctrl+C 只把主进程杀了

例如：

```text
codeteam
被 Ctrl+C 停止
```

但：

```text
pytest
python child
docker
```

继续后台运行。

随后 Resume：

```text
产生第二组进程
```

所以 Day 5 CommandRunner 的 Process Group Cleanup 今天必须真正进入 E2E。

---

# 七十三、Failure Case 6：所有 Log 都打印 stdout

结果：

```bash
codeteam diff > x.patch
```

得到：

```text
Loading session...
✓ ready
diff --git ...
```

不可用。

所以：

```text
Output Contract
```

属于 CLI API。

---

# 七十四、Failure Case 7：所有 Error 都 Exit 0

Human：

```text
知道失败
```

CI：

```text
认为成功
```

非常危险。

Exit Code 必须稳定。

---

# 七十五、Failure Case 8：非 TTY 环境弹交互 Prompt

CI：

```text
waiting for input...
```

永远挂住。

所以：

```text
TTY awareness
```

必须进入 CLI Productization。

---

# 七十六、Failure Case 9：`--help` 都初始化整个 Agent

用户：

```bash
codeteam --help
```

结果：

```text
load Docker
load Tree-sitter
load Provider
scan config
network auth
```

CLI 启动慢。

解决：

```text
Lazy Initialization
```

---

# 七十七、Failure Case 10：Verbose 泄露 Secret

Debug：

```text
provider headers
env
command
```

被完整打印。

所以：

```text
Verbose
≠
Unsafe Logging
```

Redaction 必须一直开启。

---

# 七十八、今天 Benchmark 我建议怎么做

你要求：

```text
CLI Startup Latency
```

可以正式设计为：

```text
50 cold process runs

codeteam --help

codeteam status <small-session>

codeteam diff <small-session>
```

记录：

```text
P50
P95
```

环境：

```text
Python version
OS
CodeTeam commit
```

不要提前编结果。

---

# 七十九、但真正的核心指标建议是这四个

```text
Time to First Feedback

Time to Session ID

Resume-to-ready Latency

CLI Journey Success Rate
```

其中 Journey Success Rate：

例如定义 6 个用户流程：

```text
run

interrupt-resume

diff

rollback

invalid session

invalid provider
```

要求：

```text
用户不需要进入 Python
也能完成整个 Workflow
```

这才是真正的：

# End-to-End Usability

---

# 八十、Day 6 我建议按 7 个 Step 实现

**Step 1：建立 Typer Entry Point。** 只做到：

```bash
codeteam --help
```

和四个 Command 可见，不调用 Runtime。此时就顺便确定 Arguments、Options、Help Text 和 Console Script Packaging。

**Step 2：先实现 `diff`。** 因为它是最简单、纯 Read-only 的命令，非常适合验证 CLI → SessionStore → GitWorkspace → Renderer 的整个薄层架构，而且没有 LLM 干扰。

**Step 3：实现 `run`。** 接 SessionService / Orchestrator，最关键是尽早输出 Session ID，然后订阅 Runtime Event 生成 `[inspect]`、`[plan]`、`[edit]`、`[test]` 等进度。

**Step 4：实现 `resume`。** 直接复用 Day 4 SessionService，不重写 reconciliation；真实测试 PAUSED Session、新 Process Resume、Cross-repo 和不存在 Session。

**Step 5：实现 `rollback`。** 接 Week 3 CheckpointManager，严格做 Checkpoint → Task → Worktree Ownership 验证，并保留 safety checkpoint。

**Step 6：统一 Error、Exit Code、Output。** 建立 Domain Result → Human Message → CLI Exit Code 的映射；Ctrl+C 特殊处理。架构上预留 `--verbose`、`--quiet` 和未来 `--json`。

**Step 7：做真正 E2E。** 使用安装后的 `codeteam` 可执行文件而不是 Python Function，真实运行：

```text
run
↓
Ctrl+C
↓
新 Process resume
↓
diff
↓
rollback
```

然后才算 Day 6 完成。

---

# 八十一、今天最终应该看到这样的体验

```bash
$ codeteam run "修复登录超时问题"
```

```text
Session: ses_5a81c2

Task:
修复登录超时问题

[inspect] repository
[plan] 5 steps
[reproduce] test_login_timeout failed
[edit] src/auth/client.py
[test] targeted test failed
[repair] attempt 1
[edit] src/auth/retry.py
[test] targeted: 7 passed
[verify] auth regression: 42 passed

Status: COMPLETED
Duration: 2m31s
Tokens: 18,421
Cost: ...
Files changed: 2

Inspect changes:
  codeteam diff ses_5a81c2
```

用户中途：

```text
^C

Stopping active command...
Saving session...

Session paused: ses_5a81c2

Resume with:
  codeteam resume ses_5a81c2
```

然后：

```bash
$ codeteam resume ses_5a81c2
```

```text
Session: ses_5a81c2

Task:
修复登录超时问题

Progress:
3 / 5 steps complete

Current:
P4 targeted verification

Resuming...
```

这个体验已经非常接近一个真正可以给开发者用的 Single-Agent Coding Tool。

---

# 八十二、Day 6 最终验收 Checklist

你今天结束时应该满足：

```text
CLI Surface

[ ] codeteam --help

[ ] codeteam run "<task>"

[ ] codeteam resume <session-id>

[ ] codeteam diff <session-id>

[ ] codeteam rollback <checkpoint-id>


Architecture

[ ] CLI 只做 parse / call / render

[ ] Runtime 不直接 print CLI 字符串

[ ] CLI 不包含 Git/LLM/Sandbox 业务逻辑

[ ] diff 是严格 Read-only

[ ] rollback 验证 checkpoint ownership


Runtime Integration

[ ] run 创建 Session

[ ] Session ID 尽早显示

[ ] resume 使用 Day4 reconciliation

[ ] provider/model 使用 Day5 registry

[ ] Ctrl+C 清理 Active Operation

[ ] Ctrl+C 保存 PAUSED Session


Output

[ ] 正常模式信息精简

[ ] progress 与 final result 清晰

[ ] Error actionable

[ ] 不暴露 Python traceback

[ ] Secret 始终 redacted

[ ] stdout/stderr 语义清楚


Testing

[ ] --help

[ ] run

[ ] resume

[ ] diff

[ ] rollback

[ ] invalid session

[ ] invalid checkpoint

[ ] invalid provider

[ ] Ctrl+C

[ ] exit code

[ ] Cross-process resume

[ ] diff side-effect calls == 0


Evaluation

[ ] CLI startup P50/P95

[ ] Time to First Feedback

[ ] Time to Session ID

[ ] Resume-to-ready

[ ] E2E CLI Journey
```

---

# 八十三、今天你必须能回答的面试问题

你需要真正理解这些问题，而不是背答案：

**CLI 架构方面**：为什么 CLI 不应该直接包含 Agent Runtime Logic？CLI Command Handler 最合理的职责是什么？为什么 Application Service 不应该依赖 Typer？以后要增加 REST API / IDE Plugin，你现在的设计需要改哪些模块？

**Command Contract 方面**：为什么 `diff` 必须严格 Read-only？为什么 Session Diff 最好以 Task Base State 为基准，而不只是 `git diff HEAD`？为什么 Rollback 必须验证 Checkpoint Ownership？为什么 Resume 找不到 Session 时不能自动创建？

**Session 方面**：`run` 为什么应该尽早输出 Session ID？Ctrl+C 为什么应该变成 `PAUSED` 而不是 `FAILED`？为什么真正的 Resume Test 必须跨 Process？

**CLI 工程方面**：stdout 和 stderr 为什么应该区分？TTY 和 Non-TTY 有什么区别？为什么 CI 中不能随意弹 Prompt？为什么 Exit Code 是 CLI Contract 的一部分？

**Productization 方面**：为什么 Agent CLI 需要 Human Output 和 Machine-readable Output 两套 Presenter？为什么 Runtime 应该发 Structured Event 而不是直接 print？为什么 `codeteam --help` 不应该初始化 Model 和 Docker？

**Evaluation 方面**：CLI Startup Latency 怎么测？为什么 Time-to-first-feedback 比单纯 Process Startup 更重要？怎样定义一个 End-to-End Usability Journey？

---

# 八十四、如果面试官问：“CLI 不就是给 Python 函数套层 Typer 吗？”

你应该能够回答：

> CodeTeam 的 CLI 只是 Agent Runtime 的 Interface Layer，而不是 Runtime 本身。CLI 将 argv 转换成 Application Request，由 SessionService、SingleAgentOrchestrator、GitWorkspace 和 CheckpointManager 执行真正的 Use Case，再把结构化 Runtime Event 和 Domain Result交给 Presenter。这样 `run`、`resume`、`diff` 和 `rollback` 有明确不同的 Capability Contract，例如 `diff` 是严格 Read-only，任何 Model、Sandbox 和 Mutation Backend 的调用次数都必须为 0；`rollback` 则必须验证 Checkpoint、Task 和 Worktree Ownership。Ctrl+C 不是普通 Exception，而会终止 Active Operation、持久化 PAUSED Session，再以明确退出状态结束。CLI 同时区分 Human Output、未来 JSON Output、stdout/stderr 和 TTY/non-TTY 行为，因此同一 Runtime 后续可以继续暴露给 IDE、API 或 CI，而不用复制 Agent Logic。

到这个程度，你做的就不再只是：

```text
Python CLI
```

而是：

```text
Agent Runtime
        │
        ▼
Stable Developer Interface
        │
 ┌──────┼────────┐
 ▼      ▼        ▼
Human  Script    CI
```

Day 6 的真正价值，就是第一次让前面五天构建出来的 **Task、Plan、Repair、Recovery、Persistence、Context 和 Model Runtime** 不再只是内部代码，而真正变成一个开发者能够理解、控制、中断、恢复、检查和撤销的 Coding Agent 产品。

---

# 附录：W4D6 工程地图（2026-08-22 实测落盘，Step 0）

## 1. 今天在整个 Coding Agent 中做什么

CLI = Thin Interface Layer：argv → Request → Service → 渲染。同时收口 Day 5 验收 4 项 PARTIAL（B11/B8/B9/A10/A13——原语有、接线缺，地基全在 CLI 主流程）。

## 2. Capability Mapping

Primary: Agent Harness（产品化边界）/ Observability（Events→UI）；Secondary: Safety（diff 只读、rollback 归属、Ctrl+C 先清理）/ Evaluation（CLI Benchmark 出口）。

## 3. Theory

Thin vs Fat CLI；READ ONLY 命令（副作用预算=0，测试断言）；Exit Code 克制体系（0/2/130/1）；Ctrl+C 最外层接住→cleanup→persist PAUSED→130；stdout/stderr 分离；三级 Output；Lazy Initialization（startup latency 主源）；Turn 计量只在 ModelResponse 返回后可知→turn 边界是唯一计量点。

## 4. Industrial Design

Codex/Claude/Copilot 共识：CLI 不承载 Runtime、Session ID 早显示、Resume ≠ 重新 run、Review/Diff 与修改分离。CodeTeam 取向同款 + Events 驱动 UI。

## 5. 当前仓库检查（实测）

已存在：

| 项 | 实际状态 |
|---|---|
| `codeteam/cli/app.py` | argparse，3 命令（inspect-repo/context/eval），函数内 lazy import 已有好习惯；command 直收 argparse Namespace（偏 Fat，今日顺带 Thin 化） |
| Typer | 0.23.0 已在 .venv（requirements.txt 未声明，需补） |
| Entry point | 不存在：根目录无 pyproject.toml/setup.py/setup.cfg |
| `SessionService` | create_session(task,repo,provider_id,model_id,worktree) / pause(session,reason) / resume(session_id,current_repo)->ResumeOutcome{session,runtime} |
| `CheckpointManager` | initialize/create/compare/list_checkpoints/rollback(checkpoint)->RollbackResult；state_root 强制 workspace 外 |
| `GitWorkspace` | diff(base_ref="HEAD")->GitDiff / changed_files / check_patch/apply_patch |
| `ModelSwitchService` | turn(selection) contextmanager；turn.completed 仅 turn_id/provider/model（B11 缺口） |
| `AgentLoop` | model_client 注入；UsageTracker.record_step 已计 tokens |
| `ContextAssembler` | ActiveContext.fits_budget 无消费方（A10）；check_stale 无 Session 接线（A13） |
| `orchestrator` | run(request,task_id)->OrchestrationResult（events/task_state/error 齐）；今日零改动（Thin 红线自证） |

缺口：四命令零实现、无 entry point、无 Request 分层、B11/B8/B9/A10/A13 未接。

## 6. 涉及文件

新增：pyproject.toml（[project.scripts] codeteam="codeteam.cli.app:main"）、codeteam/cli/requests.py（RunRequest/ResumeRequest/DiffRequest/RollbackRequest）、codeteam/cli/run_command.py（resume/diff/rollback/sessions 同构）、codeteam/cli/render.py、tests/cli/（三层）。
修改：cli/app.py（argparse→Typer，迁移旧 3 命令）、llm/switching.py（B11）、session/service.py（B8/B9/A13）、requirements.txt（+typer）。

## 7. Architecture / Data Flow

```text
run    → RunRequest → [lazy] registry.build → create_session → print "Session: ses_x"
       → orchestrator.run → events → render → Ctrl+C(最外层) → pause 落盘 → exit 130
resume → load → lock → reconcile → override? switch 事务 : 恢复原 selection
       → CONTEXT_STALE? check_stale → rebuild → 继续
diff   → Session→worktree→base_sha → GitWorkspace.diff → stdout（0 副作用）
rollback → checkpoint 存在 + task_id 匹配 + worktree 匹配 → CheckpointManager.rollback
```

## 8. 今日步骤拆分（P2 已排期）

| Step | 内容 | P2 | 完成标志 |
|---|---|---|---|
| 0 | 本附录落盘 | — | ✅ |
| 1 | switching.py turn 计量：wrapper client 捕获 ModelResponse→finally 发 tokens/cost | B11 | turn.completed 含计量；switching 测试绿 |
| 2 | CLI 骨架：pyproject+entry point+Typer+requests.py+render.py+测试地基 | — | codeteam --help 真实可跑 |
| 3 | run 命令：Session 早显示→orchestrator→渲染→Ctrl+C→130 | — | run 全流程 + SIGINT 集成 |
| 4 | resume 接 ModelSwitchService（override 双态）+ CONTEXT_STALE rebuild | B8/B9/A13 | override 三态测试绿 |
| 5 | diff（READ ONLY 断言）+ fits_budget 闸门（turn 发起前） | A10 | 零副作用计数测试 |
| 6 | rollback 三重 ownership + 可选 sessions/status | — | 越权拒绝测试 |
| 7 | DD-W4-D6-01/02 + 触达 ruff + 全量回归 | — | 验收清单全绿 |

## 9. Test Strategy

Layer1 CliRunner unit（argv→Request/exit code/流分离）；Layer2 integration（tmp repo 真跑；diff 断言 MockClient 调用=0、Sandbox=0、git 写命令=0）；Layer3 subprocess E2E（--help；run→SIGINT→130→resume，清 W4D4 R23 债）。约束：tmp_path+local identity、无网络、无 sleep、无 skip。

## 10. Design Decision Plan

DD-W4-D6-01 Fat vs Thin CLI（Interface Layer）；DD-W4-D6-02 Ctrl+C 与 Exit Code 契约（先清理再持久化；130 vs 1）。

## 11. Benchmark Plan（数据出口当日保证）

CLI startup latency（--help 首字节，lazy vs eager 对照）；Time to First Feedback（入口→首事件渲染）；Time to Session ID（→"Session: ses_x"）。

## 12. Ablation Plan

Lazy vs Eager import（startup P50/P95）；Thin 架构度量（cli/ import 生产模块数应仅 service 层、git/subprocess 出现次数应 0）。

## 13. Failure Cases to Watch

F1 fat CLI；F2 diff 副作用；F3 resume 偷建新 Session；F4 rollback 只看 ID；F5 Ctrl+C 不清理子进程；F6 日志污染 stdout；F7 万事 Exit 0；F8 traceback 直出；F9 secret 进 debug。

## 14. Interview Focus

CLI 为何 Thin；diff 为何 READ ONLY 且断言；Ctrl+C 为何先清理再落盘；Exit code 为何克制；lazy import 优化什么；turn.completed 为何补 tokens/cost；resume override 为何过 switch 事务。

## 15. 今日最终完成标准

```text
[ ] 四命令经 entry point 真实可跑
[ ] B11/B8/B9/A10/A13 五接线全通
[ ] diff READ ONLY + rollback 三重 ownership 断言
[ ] Ctrl+C→130→PAUSED→resume 跨进程 E2E（R23 清债）
[ ] 三层 CLI 测试；全量回归 ≥1165；触达 ruff 0 error
[ ] DD-W4-D6-01/02（PROPOSED）；Benchmark 出口可测
```