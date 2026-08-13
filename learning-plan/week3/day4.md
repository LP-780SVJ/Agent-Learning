# 第 3 周 Day 4：CommandPolicy 与危险命令识别

今天开始进入 Coding Agent Runtime 里非常关键的一层：

> **Tool Authorization / Command Governance**

前 3 天解决的是：

```text
Day 1
Agent 怎样安全修改文件？
→ Patch

Day 2
多个 Task 怎样彼此隔离？
→ Worktree

Day 3
Task 自己改坏后怎样恢复？
→ Checkpoint / Rollback
```

Day 4 开始解决：

```text
Agent 想执行一个命令时：

这个命令到底能不能执行？

能直接执行？
必须进入 Sandbox？
必须让用户批准？
还是应该永久拒绝？
```

今天最终要形成的不是一个简单：

```python
if "rm -rf" in command:
    reject()
```

而是一条真正的 Agent Tool Runtime 安全链：

```text
LLM / Worker
    │
    │ CommandRequest
    ▼
┌──────────────────────────┐
│   Command Normalizer     │
│ argv / cwd / executable  │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│      CommandPolicy       │
│                          │
│ SafeGitReadRule          │
│ GitDestructiveRule       │
│ NetworkCommandRule       │
│ ...                      │
└────────────┬─────────────┘
             │
      PolicyDecision
             │
       ┌─────┼─────────┐
       ▼     ▼         ▼
     ALLOW  ASK       DENY
       │     │
       │     └──→ Day5 ApprovalManager
       │
       └────────→ Day6 Sandbox
                         │
                         ▼
                    CommandRunner
```

今天最值得记住的一句话是：

> **CommandPolicy 不是“执行命令的安全边界”，而是 Agent Runtime 的风险决策层。真正的安全边界最终还需要 Sandbox。**

OpenAI Codex 当前公开文档就明确把两者分开：Sandbox 定义 Agent 技术上能够做什么，Approval Policy 决定 Agent 在越过某些边界前什么时候必须停下来请求批准；Sandbox 也会约束 `git`、包管理器、测试程序等由 Agent 启动的子进程。

---

# 1. Capability Mapping：今天证明什么 Agent 能力

Day 4 主要对应你的能力树：

```text
Primary

Tool Runtime
├── Command Authorization
├── Risk Classification
└── Safe Execution Gate


Workspace & Sandbox
├── Command Boundary
├── Filesystem Boundary
└── Network Boundary


Secondary

Agent Harness
├── Tool Routing
└── Human-in-the-loop

Observability
├── Policy Decision
└── Risk Reason

Evaluation
└── Adversarial Security Testing
```

以后面试时你不能只说：

> “我实现了一个危险命令黑名单。”

更好的项目表达应该是：

> “我在 Tool Runtime 中实现了独立的 Command Authorization Middleware。模型产生的是结构化 CommandRequest，Policy 根据 executable、argv、cwd、资源范围和副作用做风险分类；低风险命令可以继续，高风险命令进入 Approval，明确禁止的操作直接阻断，而 OS Sandbox 作为下一层真正执行权限限制。”

这已经是：

```text
Agent Runtime Security Architecture
```

而不是普通 Shell Wrapper。

---

# 2. 为什么 Coding Agent 的命令执行尤其危险

传统程序中：

```text
开发者
→ 写死一条 subprocess 命令
```

例如：

```python
subprocess.run(
    ["git", "status"]
)
```

命令基本是开发者提前知道的。

Coding Agent 不一样：

```text
用户任务
 ↓
LLM 推理
 ↓
动态决定工具
 ↓
动态产生参数
 ↓
执行
```

也就是说：

```text
Command
```

本身成为了：

```text
Model Output
```

而模型输入又可能来自：

```text
用户
代码
README
Issue
网页
日志
Tool Output
第三方文档
```

所以攻击链可能变成：

```text
恶意 Repository 文本
       ↓
Indirect Prompt Injection
       ↓
LLM 被诱导
       ↓
生成危险 Tool Call
       ↓
Shell
       ↓
Host
```

OWASP 当前的 AI Agent Security 指南把 Tool Abuse、Privilege Escalation、Data Exfiltration、Excessive Autonomy 和高影响操作滥用都列为 Agent 特有风险，并建议按工具和资源实施 Least Privilege、对敏感工具做显式授权。

---

# 3. Command Injection 到底是什么

先从最传统的问题开始。

假设代码：

```python
filename = user_input

subprocess.run(
    f"cat {filename}",
    shell=True,
)
```

用户本来应该传：

```text
report.txt
```

但如果输入改变了 Shell 对整个字符串的解析结构，就可能从：

```text
“文件名”
```

变成：

```text
“新的命令语义”
```

这就是：

```text
OS Command Injection
```

OWASP 的定义正是：应用程序构造系统命令时，如果外部输入可以通过特殊元素改变原有命令语义，就产生了 Command Injection 风险。OWASP 给出的第一优先防御不是“写更聪明的正则”，而是**尽量根本不要直接调用 OS 命令**；确实需要时再使用参数化和输入验证。

---

# 4. 为什么 `shell=True` 特别敏感

当你写：

```python
subprocess.run(
    "git diff && pytest",
    shell=True,
)
```

真正执行流程大致变成：

```text
Python
 ↓
Shell Interpreter
 ↓
Parse entire string
 ↓
识别：
&&
|
;
>
<
$()
...
 ↓
执行一个或多个命令
```

此时字符串不只是：

```text
data
```

而是：

```text
program
```

所以 Coding Agent 第一版最好根本不要让 LLM 提交：

```python
command: str
```

更合理的是：

```python
argv: list[str]
```

例如：

```python
[
    "git",
    "diff",
    "--",
    "src/auth.py",
]
```

然后：

```python
subprocess.run(
    argv,
    shell=False,
)
```

OWASP 同样建议把命令与参数分开，并使用结构化机制保持“命令”和“数据”的边界。

---

# 5. 为什么 `shell=False` 仍然不等于安全

这是今天非常重要的知识点。

很多初学者会认为：

```text
shell=False
=
没有安全问题
```

不是。

考虑：

```python
subprocess.run(
    [
        "some_program",
        user_input,
    ],
    shell=False,
)
```

虽然：

```text
;
&&
|
```

不再由 Shell 解释，

但是：

```text
user_input
```

仍然可能被目标程序解释成：

```text
Option / Argument
```

这叫：

```text
Argument Injection
```

OWASP 特别强调：即使成功避免了 Shell 元字符注入，攻击者仍然可能控制程序参数，从而改变被调用程序本身的行为。

所以：

```text
Command Injection
```

和：

```text
Argument Injection
```

必须区分。

---

# 6. 一个非常典型的 Argument Injection

假设本意：

```python
[
    "git",
    "diff",
    user_path,
]
```

你觉得：

```text
user_path
```

只是路径。

但如果：

```text
user_path
```

以：

```text
-
```

开头，

Git 可能把它解释成：

```text
option
```

所以你前几天已经见过：

```python
[
    "git",
    "diff",
    "--",
    user_path,
]
```

这里：

```text
--
```

的含义就是：

> 后面的东西不再作为 Option 解析。

这是一类非常典型的：

```text
Argument Injection Defense
```

---

# 7. Command Injection 与 Argument Injection 的关系

可以这样记：

```text
Command Injection

攻击者改变：
“执行哪些程序”


Argument Injection

攻击者改变：
“当前程序怎么执行”
```

例如：

```text
Shell：
program USER_INPUT
```

Command Injection 可能让：

```text
一个 Program
```

变成：

```text
多个 Program
```

Argument Injection 则即使只有一个 Program：

```text
git
curl
docker
python
```

也可能通过参数改变其能力。

OWASP甚至明确指出，Command Injection 本质上也包含 Argument Injection 风险。

---

# 8. 所以 `CommandRequest` 为什么应该结构化

今天推荐：

```python
class CommandRequest(BaseModel):
    argv: tuple[str, ...]

    cwd: str

    task_id: str
    agent_id: str

    reason: str | None = None

    timeout_seconds: float | None = None
```

这里最重要的是：

```python
argv: tuple[str, ...]
```

而不是：

```python
command: str
```

原因：

```text
字符串命令：
“git diff && pytest”

Runtime 必须猜：
这里到底是一个命令还是多个命令？
```

结构化：

```python
(
    "git",
    "diff",
    "--",
    "src/auth.py",
)
```

Runtime 明确知道：

```text
Executable:
git

Argument 1:
diff

Argument 2:
--

Argument 3:
src/auth.py
```

---

# 9. 为什么我推荐 `tuple` 而不是 `list`

这是一个小但有价值的 Design Choice。

```python
list[str]
```

是 Mutable。

例如：

```python
request.argv.append(
    "--dangerous-option"
)
```

Validation 后仍可能变化。

而：

```python
tuple[str, ...]
```

更适合作为：

```text
经过 Policy 判断的不可变请求
```

所以：

```text
CommandRequest
```

尽量 Immutable。

未来 ApprovalManager 也会依赖：

```text
批准的是同一个 Request
```

---

# 10. CommandPolicy 不应该相信 LLM 自己写的 Risk

错误：

```python
CommandRequest(
    argv=("git", "push", ...),
    risk="safe",
)
```

然后：

```python
if request.risk == "safe":
    allow()
```

这是非常危险的设计。

因为：

```text
Risk
```

也是 LLM Output。

所以：

> **事实来自 Request，风险来自 Runtime。**

也就是：

```text
LLM：

我想运行：
git ...

Runtime：

我判断：
NETWORK
REMOTE_WRITE
...
```

而不是：

```text
LLM：

我想运行：
git ...

顺便告诉你它很安全。
```

---

# 11. Allowlist 是什么

Allowlist：

> **只有明确知道安全的东西才允许。**

例如：

```text
允许：

git status
git rev-parse HEAD
git worktree list
rg ...
pytest ...
```

其他：

```text
UNKNOWN
```

不自动通过。

OWASP 对 OS Command Injection 的输入验证建议也是 Positive / Allowlist Validation：明确列出允许的命令和参数范围，而不是单纯过滤“坏字符”。

---

# 12. Denylist 是什么

Denylist：

> 明确知道危险的东西禁止。

例如：

```text
sudo
su
shutdown
reboot
...
```

优点：

```text
覆盖面广
Coding Agent 可使用大量工具
```

缺点：

```text
永远不可能枚举所有危险组合
```

例如你禁止：

```text
rm
```

但：

```text
python
```

仍然能删除文件。

你禁止：

```text
curl
```

但：

```text
python requests
```

仍然可以访问网络。

所以：

> **Denylist 不能成为 Coding Agent 的唯一安全机制。**

---

# 13. Allowlist 也不能解决一切

那么是不是：

```text
只 Allowlist
```

就行？

也不完全行。

因为 Coding Agent 是一个：

```text
General Software Engineering Agent
```

未来可能运行：

```text
pytest
cargo
npm
gradle
maven
go
cmake
ruff
eslint
自定义 repo script
```

如果全部人工预定义：

```text
ALLOWLIST
```

系统就会非常难用。

所以我建议 CodeTeam 使用：

```text
Hybrid Policy
```

---

# 14. 推荐的 Hybrid Policy

大致：

```text
Known Safe
→ ALLOW / ALLOW_SANDBOXED


Known Dangerous
→ DENY


High-impact / Context-sensitive
→ REQUIRE_APPROVAL


Unknown
→ REQUIRE_APPROVAL
```

而不是：

```text
Unknown
→ ALLOW
```

可以记成：

```text
安全证据不足
≠
默认安全
```

---

# 15. Least Privilege 到底是什么

Least Privilege：

> 给一个主体完成当前任务所必需的最小能力，不多给。

OWASP 在传统 Command Injection 和 AI Agent Security 两份指南中都强调 Least Privilege；AI Agent 指南还进一步建议按工具、操作类型和资源范围实施权限 Scope。

应用到 CodeTeam：

错误：

```text
Worker Agent

可以：
读整台电脑
写整台电脑
访问公网
Docker privileged
git push 任意 Repo
```

更合理：

```text
Worker task-001

Read:
Task Worktree

Write:
Task Worktree

Network:
disabled

Git:
local only

Remote Write:
no

Credentials:
no
```

这就是：

```text
Task-scoped Least Privilege
```

---

# 16. 工业界案例 1：OpenAI Codex

OpenAI Codex 当前公开的本地安全模型和你今天要设计的东西高度相关。

Codex 把：

```text
Sandbox
```

与：

```text
Approval Policy
```

明确拆开。

其默认 `workspace-write` 模式允许 Agent 在工作目录内读、改文件并执行命令，但默认网络关闭；需要访问工作区之外或需要网络时，会进入 Approval Flow。

更重要的是，Codex 的 Sandbox 不只保护“内置 Edit Tool”，还约束由 Agent 启动的：

```text
git
package manager
test runner
subprocess
```

等命令。

可以抽象成：

```text
Command Intent
        ↓
Policy / Approval
        ↓
Sandbox Capability Boundary
        ↓
OS Process
```

这和你今天的设计非常接近。

---

# 17. 为什么 Codex 这个例子很重要

它说明：

```text
Policy
```

和：

```text
Sandbox
```

不能二选一。

假如只有 Policy：

```text
Policy：
不允许写 ~/.ssh
```

但是程序真的拥有：

```text
整个文件系统权限
```

那么一个 Policy 漏洞就可能越界。

反过来只有 Sandbox：

```text
只能操作 /workspace
```

也不够。

因为：

```text
git reset --hard
```

即使完全限制在：

```text
/workspace
```

里面，也可能把用户任务成果清掉。

所以：

```text
Policy
控制“应该不应该”

Sandbox
控制“能不能”
```

OpenAI 当前公开架构也是按照这种分层思路描述的。

---

# 18. 工业界案例 2：Claude Code

Claude Code 当前公开的 Permission Rules 有三类非常值得你借鉴：

```text
deny

ask

allow
```

并且规则优先级明确是：

```text
deny
→ ask
→ allow
```

其配置甚至支持类似：

```text
Bash(git diff *)
→ allow

Bash(git push *)
→ ask

Bash(curl *)
→ deny
```

这样的工具级 Rule。

这就是一个很典型的：

```text
Policy Rule Engine
```

---

# 19. Claude Code 同样没有把 Policy 当成 Sandbox

Claude Code 现在还提供独立 Bash Sandboxing，可以限制：

```text
filesystem read
filesystem write
network
```

并能够为特定路径建立 allow / deny。

Claude Code 的安全文档还明确强调工作目录边界：默认写操作限制在启动目录及其子目录；网络命令例如 `curl`、`wget` 默认不会被当成普通只读操作自动通过。

所以今天你其实正在实现类似：

```text
Claude Code permissions
```

中的：

```text
Policy Layer
```

Day 6 才实现：

```text
Sandbox Layer
```

---

# 20. 工业界案例 3：GitHub Copilot Coding Agent

GitHub Copilot Cloud Agent 的安全设计也很值得学习。

GitHub 当前公开说明：

- Agent 能 Push 的 Branch 被限制；
- Agent 的 Credentials 能力被限制；
- Agent 创建的 Draft PR 必须由人 Review/Merge；
- 默认限制 Internet Access；
- Session Log 和 Audit Log 用于追踪 Agent 行为。

这里体现的不是简单：

```text
block rm
```

而是：

```text
Capability Scoping
```

例如：

```text
Agent 可以写：
自己的 Task Branch

Agent 不可以：
任意操作 Repo
任意 Merge
```

这正是 Least Privilege 的 Agent Runtime 实践。

---

# 21. GitHub Local Sandbox 还能给你一个很重要的教训

GitHub 当前 Copilot CLI Local Sandbox 会限制：

```text
filesystem
network
system capabilities
```

底层由 Microsoft eXecution Container（MXC）应用 OS 隔离策略。

但 GitHub 官方同时指出一个非常值得注意的问题：

> CLI 自己进程内执行的 built-in file tools 并不会经过 OS Sandbox，因此这些内置工具需要自己检查 Policy。 


这对你的 CodeTeam 非常重要。

因为未来你会同时有：

```text
Shell Command

File Tool

Patch Tool

Git Tool
```

所以安全链不能只是：

```text
所有东西都扔进 Docker 就好了
```

内置 Tool 自己也必须有：

```text
Path Policy
Permission Policy
```

---

# 22. Policy vs Sandbox：今天必须彻底理解

建议记住：

| 层 | 回答的问题 |
|---|---|
| Policy | 这件事应该执行吗？ |
| Approval | 用户愿意让它执行吗？ |
| Sandbox | 即使执行，它最多能做到什么？ |
| Runner | 怎样真正执行？ |
| Checkpoint | 执行失败后怎样恢复？ |

结合前几天：

```text
CommandRequest
      ↓
CommandPolicy
      ↓
Approval
      ↓
Sandbox
      ↓
Runner
      ↓
Workspace
      ↓
Checkpoint / Rollback
```

这已经是一套完整的：

```text
Agent Tool Runtime Architecture
```

---

# 23. Shell Interpreter 是什么

例如：

```text
bash
sh
zsh
fish
cmd
powershell
```

它们的特殊之处是：

> 输入本身可以是一门程序语言。

例如：

```text
bash -c <string>
```

这里：

```text
<string>
```

不再是普通参数。

而是：

```text
Shell Program
```

Shell 会进一步解析：

```text
变量
管道
重定向
命令连接
命令替换
```

所以：

```text
argv list
+
shell=False
```

虽然避免 Python 自己启动 Shell，

但下面这种请求：

```python
(
    "bash",
    "-c",
    "...",
)
```

实际上还是：

```text
主动调用了 Shell Interpreter
```

---

# 24. 因此需要 `ShellInterpreterRule`

例如：

```python
class ShellInterpreterRule:
    ...
```

它至少应该识别：

```text
sh
bash
zsh
fish

cmd
powershell
pwsh
```

并特别关注：

```text
-c
-command
```

之类“执行字符串程序”的模式。

CodeTeam V1 我建议：

```text
shell -c

→ REQUIRE_APPROVAL
或直接 DENY
```

而不要：

```text
ALLOW
```

---

# 25. Shell 之外还有“代码 Interpreter”

例如：

```text
python -c
node -e
perl -e
ruby -e
```

它们不是 Shell，

但本质上也是：

```text
把字符串当程序执行
```

所以长期来看：

```text
ShellInterpreterRule
```

最好演化成：

```text
DynamicInterpreterRule
```

例如：

```text
Shell
+
Python -c
+
Node -e
+
...
```

今天第一版可以先放在：

```text
ShellInterpreterRule
```

相关风险类别下。

---

# 26. `python -m pytest` 为什么又可以比较安全

注意：

```text
python -c
```

和：

```text
python -m pytest
```

风险并不一样。

```text
python -c
```

等于：

```text
执行 LLM 直接生成的任意 Python Program
```

而：

```text
python -m pytest
```

表示：

```text
运行项目测试框架
```

所以：

```text
Executable 名字
```

本身不足以判断风险。

必须看：

```text
Executable
+
Subcommand / Arguments
+
cwd
+
Resource scope
```

---

# 27. 但 `pytest` 也绝对不是真正“安全”

这是一个非常重要的工业理解。

运行：

```text
pytest
```

本质上意味着：

```text
执行当前 Repository 中的 Python Code
```

如果 Repository 不可信，

测试本身可能执行：

```text
filesystem
network
subprocess
```

所以：

```text
pytest
```

最多应该理解为：

```text
Allowed inside Sandbox
```

而不是：

```text
无风险
```

因此我建议 PolicyDecision 不只有：

```text
ALLOW / DENY
```

---

# 28. 推荐 `PolicyDecision`

第一版：

```python
class PolicyDecision(str, Enum):
    ALLOW = "allow"

    ALLOW_SANDBOXED = "allow_sandboxed"

    REQUIRE_APPROVAL = "require_approval"

    DENY = "deny"
```

语义：

```text
ALLOW
Runtime 认为属于非常受控的低风险操作。


ALLOW_SANDBOXED
可以自动执行，
但必须在 Sandbox 内。


REQUIRE_APPROVAL
只有用户确认后才能进入执行流程。


DENY
即使用户普通审批也不应该由 Agent 执行。
```

Day 5：

```text
ApprovalManager
```

就是处理中间第三种。

---

# 29. Nested Command 是今天最难的概念之一

假设你禁止：

```text
bash -c
```

但是：

```text
env bash -c ...
```

怎么办？

第一层看到：

```text
Executable:
env
```

如果：

```text
env
→ ALLOW
```

那么：

```text
bash
```

被藏在第二层。

这就是：

```text
Nested Command
```

---

# 30. 常见 Nested / Wrapper Command

例如：

```text
env <command>
sudo <command>
nice <command>
timeout <duration> <command>
xargs <command>
```

甚至：

```text
make
npm run
```

内部也可能间接执行其他命令。

所以不能只：

```python
executable = argv[0]

if executable in SAFE:
    allow
```

---

# 31. Nested Command Normalization

以后 Runtime 可以建立：

```text
CommandRequest
      ↓
CommandNormalizer
      ↓
NormalizedCommand
```

例如：

```text
env python -m pytest
```

转换成：

```text
Wrapper:
env

Effective Executable:
python

Effective argv:
-m pytest
```

然后 Policy：

```text
env
+
python -m pytest
```

整体评估。

但不要试图：

```text
递归理解所有 Unix 程序
```

这是不可能的。

遇到不理解的 Wrapper：

```text
UNKNOWN
→ REQUIRE_APPROVAL
```

---

# 32. 更棘手：Git 本身也可能间接执行程序

这是一个非常值得在面试里讲的 Failure Case。

你可能认为：

```text
git diff
```

绝对是：

```text
read-only
```

但 Git 支持 External Diff Driver 和 Text Conversion Driver。Git 官方文档明确说明 `--ext-diff` 可以执行外部 Diff Helper，而 `textconv` 可以运行外部转换程序。

所以 Day 1 我们才建议：

```text
--no-ext-diff
--no-textconv
```

这不是洁癖，而是安全边界。

---

# 33. Git Alias 甚至还能执行 Shell

更典型的是：

```text
git something
```

不能因为：

```text
Executable = git
```

就认为一定安全。

Git 官方支持 Alias，如果 Alias 值以：

```text
!
```

开始，

它会被当成 Shell Command 执行。

所以：

```text
SafeGitReadRule
```

必须采用：

```text
明确 Built-in Subcommand Allowlist
```

例如：

```text
status
diff
rev-parse
...
```

而不是：

```python
if argv[0] == "git":
    return ALLOW
```

---

# 34. SafeGitReadRule 应该怎么想

不要写：

```python
SAFE_GIT = {
    "status",
    "diff",
    "log",
}
```

就结束。

更合理：

```text
git status
    ↓
检查 args


git diff
    ↓
拒绝：
--ext-diff

Runtime 自己产生时：
强制：
--no-ext-diff
--no-textconv
```

也就是说：

> **越安全的 Tool，越应该由 Runtime 自己构造，而不是允许 LLM 自由拼全部参数。**

例如未来最好不是：

```text
run_command(["git", "diff", ...])
```

而是：

```text
GitWorkspace.diff()
```

这样整个：

```text
git diff 参数面
```

都不暴露给 LLM。

---

# 35. 这是今天一个非常重要的 Design Principle

优先：

```text
Narrow Tool
```

而不是：

```text
Generic Shell
```

例如：

```text
GitWorkspace.diff()

GitWorkspace.apply_patch()

WorktreeManager.create()
```

比：

```text
shell("git ...")
```

更安全。

这与 OWASP AI Agent Security 推荐的 Scoped Tool 和 Least Privilege 完全一致。

---

# 36. 推荐今天的数据模型：`RiskCategory`

可以从：

```python
class RiskCategory(str, Enum):
    READ_ONLY = "read_only"

    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"

    NETWORK = "network"
    REMOTE_WRITE = "remote_write"

    PRIVILEGE_ESCALATION = (
        "privilege_escalation"
    )

    SHELL_INTERPRETER = (
        "shell_interpreter"
    )

    WORKSPACE_ESCAPE = (
        "workspace_escape"
    )

    DESTRUCTIVE_GIT = (
        "destructive_git"
    )

    CREDENTIAL_ACCESS = (
        "credential_access"
    )

    SYSTEM_CONTROL = (
        "system_control"
    )

    CONTAINER_PRIVILEGE = (
        "container_privilege"
    )

    PACKAGE_INSTALL = (
        "package_install"
    )

    UNKNOWN = "unknown"
```

注意：

```text
RiskCategory
```

与：

```text
PolicyDecision
```

不是同一个东西。

例如：

```text
NETWORK
```

在不同环境中可能：

```text
REQUIRE_APPROVAL
```

也可能：

```text
DENY
```

---

# 37. `CommandRequest`

推荐概念：

```python
class CommandRequest(BaseModel):
    task_id: str
    agent_id: str

    argv: tuple[str, ...]

    cwd: str

    reason: str | None = None

    timeout_seconds: float = 60.0
```

第一版不要让 LLM 提供：

```text
risk
policy
approval_required
network_safe
```

这些都属于：

```text
Runtime Derived State
```

---

# 38. `PolicyRule`

建议做 Protocol：

```python
from typing import Protocol


class PolicyRule(Protocol):

    def evaluate(
        self,
        request: CommandRequest,
        context: "PolicyContext",
    ) -> "RuleResult | None":
        ...
```

含义：

```text
每个 Rule
只负责一种风险。
```

例如：

```text
GitDestructiveRule

只关心：
危险 Git 行为
```

而不是让一个：

```python
if/elif
```

写 800 行。

---

# 39. 为什么 Rule Chain 比一个巨型函数好

假设：

```python
def evaluate(command):
    if ...
    elif ...
    elif ...
```

后期：

```text
Git
Network
Docker
Credentials
System
Filesystem
```

全部混在一起。

结果：

```text
一个 Rule 修改
可能影响所有策略。
```

Rule Chain：

```text
CommandPolicy
    │
    ├── CredentialPathRule
    ├── PrivilegeEscalationRule
    ├── SystemControlRule
    ├── DockerPrivilegeRule
    ├── GitDestructiveRule
    ├── NetworkCommandRule
    └── SafeGitReadRule
```

更容易：

```text
单测
调试
扩展
Benchmark
Ablation
```

---

# 40. Rule 本身最好返回 Evidence

不要：

```python
return DENY
```

推荐：

```python
class RuleResult(BaseModel):
    rule_id: str

    decision: PolicyDecision

    risk_categories: tuple[
        RiskCategory,
        ...
    ]

    reason: str
```

例如：

```text
rule:
git-destructive

decision:
DENY

risk:
DESTRUCTIVE_GIT

reason:
git reset --hard can discard workspace changes
```

以后 Observability：

```text
为什么 Agent 被拦？
```

就有答案。

---

# 41. `CommandPolicy` 最终结果

可以：

```python
class PolicyEvaluation(BaseModel):
    decision: PolicyDecision

    risk_categories: tuple[
        RiskCategory,
        ...
    ]

    matched_rules: tuple[str, ...]

    reasons: tuple[str, ...]
```

例如：

```text
argv:
git push origin branch

Decision:
REQUIRE_APPROVAL

Risks:
NETWORK
REMOTE_WRITE

Rules:
NetworkCommandRule
RemoteWriteRule
```

---

# 42. 多个 Rule 命中时怎么合并

例如：

```text
sudo git push
```

可能命中：

```text
PrivilegeEscalationRule
NetworkCommandRule
RemoteWriteRule
```

不能：

```text
第一个 ALLOW
→ 立即返回
```

我建议 Day 4 使用：

```text
Severity aggregation
```

例如：

```text
DENY
>
REQUIRE_APPROVAL
>
ALLOW_SANDBOXED
>
ALLOW
```

收集所有 Rule Result，

最后：

```text
取最严格 Decision
```

同时保留所有 Risk。

---

# 43. 为什么这个设计和 Claude Code 不完全相同

Claude Code 当前 Permission Rule 顺序是：

```text
deny
→ ask
→ allow
```

然后 First Match 生效。

CodeTeam 第一版我更建议：

```text
所有独立 Risk Rule 都执行
→ 收集 Evidence
→ highest severity wins
```

原因是：

```text
更适合学习项目
更容易 Observability
更容易解释多重 Risk
```

这属于我们的 Design Decision，

不是说工业系统一定都这么做。

---

# 44. Rule 1：`SafeGitReadRule`

负责识别：

```text
Git 低副作用读取行为
```

例如候选：

```text
git status
git rev-parse
git worktree list
```

以及由 Runtime 固定参数生成的：

```text
git diff
```

决策：

```text
ALLOW
或
ALLOW_SANDBOXED
```

但注意：

```text
不能只判断：
argv[0] == git
```

因为 Git alias、external diff 等机制能够引入额外执行能力。

---

# 45. Rule 2：`GitDestructiveRule`

重点识别：

```text
可能不可逆删除本地 Git / Workspace 状态
```

例如类别：

```text
hard reset
aggressive clean
forced branch deletion
forced worktree removal
```

Day 4 V1：

```text
DENY
```

或者某些：

```text
REQUIRE_APPROVAL
```

具体需要 Design Policy。

对于我们当前 CodeTeam：

```text
git reset --hard
git clean -fdx
```

建议直接：

```text
DENY
```

因为你已经拥有：

```text
CheckpointManager
```

不需要允许 Agent 用这些宽泛破坏性工具做恢复。

---

# 46. Rule 3：`NetworkCommandRule`

风险不仅是：

```text
下载恶意东西
```

还包括：

```text
Data Exfiltration
Supply Chain
Untrusted Content
Non-determinism
```

需要识别：

```text
HTTP clients
SSH
Remote Git
Package managers
```

但 Package Manager 有上下文。

例如：

```text
pytest
```

一般无网络。

```text
pip install
```

通常可能需要网络并运行安装逻辑。

所以：

```text
PACKAGE_INSTALL
+
NETWORK
```

可能同时出现。

OpenAI Codex 默认 `workspace-write` 下关闭网络，并在需要网络时通过权限/Approval 机制处理，就是很典型的这种边界。

---

# 47. Rule 4：`PrivilegeEscalationRule`

识别：

```text
sudo
su
doas
pkexec
```

这种尝试提升 Host 权限的操作。

V1：

```text
DENY
```

因为 Coding Agent 正常开发：

```text
不应该需要 root
```

OWASP 的 Least Privilege 原则同样强调进程应该只拥有完成任务所需的最低权限。

---

# 48. Rule 5：`ShellInterpreterRule`

识别：

```text
bash -c
sh -c
zsh -c
cmd /c
powershell ...
```

以及后面可以扩展：

```text
python -c
node -e
```

第一版建议：

```text
REQUIRE_APPROVAL
```

高风险情形可以：

```text
DENY
```

---

# 49. Rule 6：`FilesystemEscapeRule`

目标：

```text
Command cwd
以及明显的路径参数
不能越过 Task Workspace。
```

例如：

```text
cwd
```

必须：

```text
inside task worktree
```

这是最基本要求。

但是一个非常重要的限制是：

> CommandPolicy 不可能理解所有程序的所有 Path Argument。

例如：

```text
compiler
database
custom tool
```

参数到底哪些是路径？

Policy 很难全部知道。

所以：

```text
FilesystemEscapeRule
```

只能作为：

```text
Intent-level defense
```

真正的文件系统边界还是 Day 6：

```text
Sandbox
```

---

# 50. Rule 7：`DockerPrivilegeRule`

Docker 特别敏感。

重点至少识别：

```text
privileged container

host namespace

host root filesystem mount

docker socket
```

V1 我甚至建议：

```text
Agent 自由 Docker command
默认 REQUIRE_APPROVAL
```

其中明显能突破 Host Isolation 的模式：

```text
DENY
```

---

# 51. Rule 8：`CredentialPathRule`

保护：

```text
SSH keys
cloud credentials
Git credentials
environment secrets
Kubernetes credentials
```

例如路径类别：

```text
~/.ssh
~/.aws
~/.gnupg
~/.kube
```

以及：

```text
.env
credentials
secret files
```

Claude Code 当前 Sandbox 甚至支持专门配置 Credential Files 为 `deny` 或保护模式，这说明 Credentials 应被视为独立于普通文件读取的敏感资源。

---

# 52. Rule 9：`SystemControlRule`

识别：

```text
shutdown
reboot
service/system manager
system-wide process control
```

V1：

```text
DENY
```

这些操作基本不属于 Coding Agent 正常 Task。

---

# 53. Rule 10：`RemoteWriteRule`

这里要和：

```text
NetworkCommandRule
```

区分。

例如：

```text
Network Read

访问文档
下载依赖
```

和：

```text
Remote Write

push
deploy
merge
publish
send
delete remote resource
```

风险不是一个级别。

所以建议：

```text
NETWORK
```

和：

```text
REMOTE_WRITE
```

分开。

GitHub Copilot Cloud Agent 公开安全设计中就采取了很强的远端写 Capability Scoping：Agent 的 Push 目标 Branch 被限制，并且最终 PR Merge 必须由人完成。

---

# 54. `RemoteWriteRule` 对未来非常重要

以后 CodeTeam 不只会有：

```text
git push
```

还可能有：

```text
GitHub MCP
Cloud API
Email Tool
Database Write
Deploy Tool
```

所以：

```text
RemoteWriteRule
```

最终应该演化成：

```text
External Side Effect Policy
```

即：

> 对外部世界产生持久副作用的 Tool Call 都是高风险动作。

OWASP 当前 AI Agent Security 也建议高影响或不可逆动作必须有显式 Human-in-the-loop。

---

# 55. 一个非常重要的事实：命令“读/写”不是由名字决定

例如：

```text
git
```

可以：

```text
status
```

也可以：

```text
push
```

```text
python
```

可以：

```text
-m pytest
```

也可以：

```text
执行任意代码
```

```text
docker
```

可以：

```text
inspect
```

也可以改变 Host 能力。

因此 Risk Classification 必须：

```text
Executable
+
Arguments
+
Context
```

而不是：

```text
Executable only
```

---

# 56. Context 也很重要

未来：

```python
class PolicyContext(BaseModel):
    workspace_root: str

    network_enabled: bool = False

    trusted_repo: bool = False

    interactive: bool = True
```

例如：

```text
pytest
```

在：

```text
Trusted Repo
+ Sandbox
```

可以：

```text
ALLOW_SANDBOXED
```

但来自：

```text
刚下载的未知 Repository
```

就可能需要：

```text
REQUIRE_APPROVAL
```

所以 Risk 不一定是：

```text
Command-only property
```

而是：

```text
Command × Environment × Trust
```

---

# 57. 今天建议的 Policy Pipeline

我建议不要：

```text
CommandRequest
↓
10 个 regex
↓
Runner
```

而是：

```text
CommandRequest
        │
        ▼
┌─────────────────────┐
│ Request Validation  │
│ argv non-empty      │
│ cwd valid           │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Normalization       │
│ executable          │
│ wrappers            │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Context Validation  │
│ workspace ownership │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Risk Rules          │
│ Git / Net / Shell   │
│ Paths / Credentials │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Decision Aggregator │
│ highest severity    │
└──────────┬──────────┘
           ▼
    PolicyEvaluation
```

---

# 58. 一个建议的数据模型

概念上：

```python
class CommandRequest(BaseModel):
    task_id: str
    agent_id: str

    argv: tuple[str, ...]
    cwd: str

    reason: str | None = None


class RuleResult(BaseModel):
    rule_id: str

    decision: PolicyDecision

    risks: tuple[
        RiskCategory,
        ...
    ]

    reason: str


class PolicyEvaluation(BaseModel):
    decision: PolicyDecision

    risks: tuple[
        RiskCategory,
        ...
    ]

    matched_rules: tuple[str, ...]

    reasons: tuple[str, ...]
```

今天你不必立即照抄。

后面 Coder Agent 再逐步实现。

---

# 59. 一个很值得做的设计：Rule ID 必须稳定

例如：

```text
git.destructive.reset-hard
network.remote-git
privilege.sudo
filesystem.workspace-escape
```

而不是：

```text
Rule 1
Rule 2
```

为什么？

未来 Event Log：

```json
{
  "decision": "deny",
  "rule_id": "git.destructive.reset-hard"
}
```

可以做：

```text
哪些 Rule 被命中最多？
哪些导致最多 Approval？
哪些 False Positive 最高？
```

这直接连接 Day 后续的：

```text
Observability
Evaluation
```

---

# 60. Unknown Command 应该怎么办

这是一个关键 Design Decision。

例如：

```text
some-new-build-tool
```

Policy 根本没见过。

选择：

### A

```text
ALLOW
```

风险：

```text
未知能力自动获得执行权
```

### B

```text
DENY
```

问题：

```text
Coding Agent 很难扩展
```

### C

```text
REQUIRE_APPROVAL
```

我推荐 C：

```text
Known safe → 自动
Known dangerous → 拒绝
Unknown → 人确认
```

Day 6 加 Sandbox 后：

```text
Unknown
→ Approval
→ Sandbox
```

会更合理。

---

# 61. 为什么“正则黑名单”一定会失败

假设：

```python
if "rm -rf" in command:
    deny
```

变化：

```text
不同参数顺序
路径变化
Wrapper
Interpreter
Script
Alias
```

就可能绕过。

更根本的问题是：

> 你在尝试从字符串猜程序语义。

所以：

```text
String Regex
```

只应该是：

```text
某些 Rule 的辅助信号
```

而不应该是：

```text
整个 Policy Engine
```

---

# 62. 今天 15 个 Safe 测试怎么设计

“Safe”不能理解成：

```text
无任何风险
```

而应该是：

```text
符合我们预定义的自动执行 Policy。
```

建议至少：

```text
01 git status
02 git rev-parse HEAD
03 git branch --show-current
04 git worktree list --porcelain
05 Runtime 固定参数 git diff
06 rg literal query
07 rg limited glob
08 pytest
09 python -m pytest
10 ruff check
11 mypy
12 python --version
13 git diff --name-status
14 git status --porcelain
15 pytest specific local test
```

预期可以区分：

```text
ALLOW
```

和：

```text
ALLOW_SANDBOXED
```

例如：

```text
git status
→ ALLOW

pytest
→ ALLOW_SANDBOXED
```

因为 pytest 会执行 Repo Code。

---

# 63. 15 个 Dangerous / High-risk 测试

不要真正执行。

只把：

```text
CommandRequest
```

提交给 Policy。

覆盖：

```text
01 destructive file deletion
02 hard Git reset
03 aggressive Git clean
04 force remote push
05 privilege escalation
06 download-and-execute pattern
07 credential path access
08 system control
09 privileged container
10 docker socket access
11 shell interpreter string execution
12 workspace path escape
13 arbitrary code interpreter
14 remote deployment/write
15 unknown high-risk wrapper
```

核心断言：

```python
assert evaluation.decision in {
    PolicyDecision.DENY,
    PolicyDecision.REQUIRE_APPROVAL,
}
```

以及更关键：

```python
assert fake_runner.calls == []
```

---

# 64. 为什么必须有 FakeRunner

Day 4 的测试目标：

```text
证明危险操作不能进入 Runner。
```

不是：

```text
证明危险命令执行后没出事。
```

架构：

```text
CommandRequest
     ↓
CommandPolicy
     ↓
DENY
     ↓
FakeRunner

calls = 0
```

这样危险命令：

```text
永远不被操作系统看到。
```

---

# 65. 10 类危险操作验收应该怎么定义

不要把：

```text
全部阻止
```

定义成：

```text
全部必须 DENY。
```

因为 Day 5 还存在：

```text
REQUIRE_APPROVAL
```

更准确验收：

> **10 类危险操作全部不能未经授权直接进入 Runner。**

即：

```text
Decision
≠
ALLOW

并且：

Runner invocation
=
0
```

这是你原验收标准更精确的工程表达。

---

# 66. 还需要测试 Rule Precedence

例如：

```text
一个 Command
同时命中：

SafeGitReadRule
+
CredentialPathRule
```

那么：

```text
DENY
```

必须赢。

再例如：

```text
ALLOW_SANDBOXED
+
REQUIRE_APPROVAL
```

最后：

```text
REQUIRE_APPROVAL
```

所以至少测试：

```text
DENY > REQUIRE_APPROVAL
REQUIRE_APPROVAL > ALLOW_SANDBOXED
ALLOW_SANDBOXED > ALLOW
```

---

# 67. 还必须测试 Nested Command

例如：

```text
wrapper
→ shell
→ inner command
```

如果没有 Nested Detection：

```text
外层命令可能看起来无害
```

因此测试：

```text
Direct dangerous
Nested dangerous
```

都应无法直接运行。

这是后面 Ablation 的重要对象。

---

# 68. 还要测试 Unknown Command

输入：

```text
完全未知 executable
```

应该：

```text
REQUIRE_APPROVAL
```

而不是：

```text
ALLOW
```

这样可以防止：

```text
新工具
=
隐式自动权限升级
```

---

# 69. 还应该测试空请求

例如：

```python
argv=()
```

必须：

```text
INVALID / DENY
```

不要等：

```text
subprocess
```

自己报错。

---

# 70. 今天的 Design Decision 1：Structured argv vs shell string

候选：

### A

```text
command: str
```

优点：

```text
LLM 易生成
支持复杂 Shell
```

缺点：

```text
解析不可靠
Command Injection 面大
Nested Command 难分析
```

### B

```text
argv: tuple[str, ...]
```

优点：

```text
命令 / 参数分离
更容易 Policy
shell=False
结构化审计
```

缺点：

```text
复杂 Pipeline 需要更高层 Tool
```

推荐：

```text
B
```

复杂 Shell Operation 不直接支持，

而是：

```text
由专门 Tool
或审批路径
```

执行。

这与 OWASP“命令和参数分离、优先结构化接口”的安全建议一致。

---

# 71. Design Decision 2：Allowlist vs Denylist

候选：

```text
Pure Allowlist
Pure Denylist
Hybrid
```

我建议：

```text
Hybrid
```

策略：

```text
Known low-risk
→ allow

Known dangerous
→ deny

Unknown / context-sensitive
→ approval
```

原因：

```text
Pure Allowlist
可用性差

Pure Denylist
安全边界弱

Hybrid
适合通用 Coding Agent
```

这是项目 Design Decision，

后面必须通过 Benchmark/Ablation 验证。

---

# 72. Design Decision 3：Rule Chain

候选：

```text
One giant policy function
```

vs

```text
Composable PolicyRule
```

推荐：

```text
Composable Rule
```

因为后续：

```text
单 Rule 测试
Rule Ablation
Risk Observability
新增语言/工具
```

都会容易很多。

---

# 73. Design Decision 4：Default Unknown

选择：

```text
ALLOW
DENY
REQUIRE_APPROVAL
```

推荐：

```text
REQUIRE_APPROVAL
```

这是典型：

```text
Fail Closed enough
but still usable
```

的折中。

---

# 74. Benchmark：今天不能只数 30 个单测

按照你的新全局标准，Day 4 至少应该建立一个：

```text
Policy Classification Benchmark
```

目标回答两个问题：

```text
1.
能不能挡住危险命令？

2.
会不会把大量正常开发命令都误拦？
```

---

# 75. Benchmark Dataset

第一版可以建立：

```text
200 CommandRequest
```

例如：

```text
100 Safe / Routine

100 Dangerous /
Approval-required
```

分类：

```text
Git
Test
Lint
Build
Filesystem
Network
Shell
Docker
Credentials
System
Remote Write
Nested
```

注意：

```text
30 条 Unit Test
```

和：

```text
200 条 Eval Dataset
```

不是同一个东西。

Test：

```text
验证代码契约
```

Eval：

```text
衡量策略质量
```

---

# 76. Benchmark 指标

最重要的四个：

### Dangerous Pass-through Rate

```text
危险样本中
被错误 ALLOW 的比例
```

这是最关键安全指标。

理想：

```text
0
```

在你当前固定安全数据集上必须达到 0。

---

### Safe Auto-Allow Rate

```text
Safe 样本中
无需人工 Approval 的比例
```

越低：

```text
用户每运行两条命令
都被问一次
```

Agent 几乎没法使用。

---

### False Deny Rate

```text
Safe Command
被直接 DENY 的比例
```

---

### Policy Latency

测：

```text
P50
P95
```

因为 Policy 每个 Tool Call 都会走一次。

---

# 77. 一个很有价值的新指标：Approval Burden

定义：

```text
需要用户审批的命令数
/
全部普通开发命令
```

如果：

```text
80%
```

那么：

```text
系统很安全
```

但用户会不停点击 Approval。

OpenAI 的 Sandbox 设计明确提到，合理的技术边界可以减少 Approval Fatigue，让边界内的低风险操作自动进行。

所以：

```text
Security
```

和：

```text
Usability
```

必须一起评估。

---

# 78. Benchmark 结果不要预设

你现在只能定义：

```text
Metrics
Dataset
Baseline
```

不能写：

```text
我的 Policy Dangerous Pass-through 0%
```

除非真正跑过。

按照我们现在统一标准：

```text
No Experiment
→ No Result Claim
```

---

# 79. Ablation 1：Pure Denylist

Full：

```text
Hybrid Policy
```

Ablation：

```text
Denylist Only
```

运行同一：

```text
200-case dataset
```

比较：

```text
Dangerous Pass-through
Safe Auto-Allow
Approval Burden
```

可以验证：

> 单纯列举危险命令是否足够。

---

# 80. Ablation 2：取消 Nested Command Detection

Full：

```text
Nested normalization
```

Ablation：

```text
只分析 argv[0]
```

重点 dataset：

```text
Direct dangerous
Wrapper dangerous
Interpreter nested
```

比较：

```text
Dangerous Pass-through Rate
```

如果移除后危险请求漏掉，

就证明：

```text
Nested Command Analysis
```

确实有价值。

---

# 81. Ablation 3：String + Regex vs Structured argv

Baseline：

```text
command string
+
regex
```

Full：

```text
structured argv
+
semantic rules
```

测试各种：

```text
参数变化
Wrapper
Option
路径
```

比较：

```text
Classification Accuracy
Dangerous Pass-through
```

这个 Ablation 特别适合面试。

---

# 82. Ablation 4：Policy-only vs Policy + Sandbox

这个实验今天暂时不能完整执行。

因为：

```text
Day 6
Sandbox
```

还没有完成。

但是现在就应该记录为：

```text
Future Cross-module Ablation
```

以后比较：

```text
Policy Only

vs

Policy + OS Sandbox
```

主要测试：

```text
Policy 漏判以后
Host 能否仍被 Sandbox 阻断
```

这会成为第三周非常重要的综合安全实验。

---

# 83. Failure Case 1：Git Alias

场景：

```text
SafeGitReadRule
只看：
git + subcommand
```

但 Repo/User Git Config 中定义了：

```text
shell-backed alias
```

Git 官方允许 `!` Alias 调用 Shell。

改进：

```text
只允许 Runtime 已知 Built-in
+
禁用/绕过 alias 影响
+
优先专门 Git Tool
```

---

# 84. Failure Case 2：External Git Helper

场景：

```text
git diff
```

看起来只读，

但 External Diff / textconv 可能执行外部程序。Git 官方文档确认这些机制可以调用外部 Helper。

改进：

```text
Runtime-controlled git diff

--no-ext-diff
--no-textconv
```

---

# 85. Failure Case 3：Nested Wrapper

例如：

```text
Wrapper
→ Interpreter
```

Policy 只检查第一层：

```text
漏判
```

改进：

```text
Wrapper Normalization
+
Unknown → Approval
```

---

# 86. Failure Case 4：Safe Command 执行恶意 Repo Code

例如：

```text
pytest
```

Policy：

```text
Safe development command
```

但 Repository Test：

```text
恶意代码
```

如果没有 Sandbox：

```text
Policy 无法保护 Host
```

改进：

```text
ALLOW_SANDBOXED
```

这就是：

> Policy 不能代替 Sandbox。

---

# 87. Failure Case 5：PATH Hijacking

例如 Policy 看到：

```text
git
```

但实际 PATH 中第一个：

```text
git
```

并不是系统预期的 Git。

这是为什么后续 Runner 还要考虑：

```text
Controlled PATH
Executable Resolution
```

Day 4 暂时记录 Failure Case，

不要现在把 Runner 全部实现掉。

---

# 88. Failure Case 6：Symlink Escape

Command 参数：

```text
workspace/link/file
```

字符串看起来在 Workspace，

但：

```text
link
→ outside directory
```

所以：

```text
字符串前缀检查
```

不够。

需要复用 Day 1 已建立的：

```text
Safe Path Resolver
```

最终 Sandbox 再提供第二层限制。

---

# 89. Failure Case 7：Unknown Package Script

例如：

```text
npm test
```

真正执行什么？

取决于：

```text
package.json
```

也可能串联：

```text
pretest
test
posttest
```

所以：

```text
命令名字安全
≠
底层 Script 安全
```

Day 2/Week2 `CommandDetector` 已经强调过：

```text
检测命令
≠
信任命令
```

这个原则今天正式进入 Runtime。

---

# 90. Failure Case 8：Repository 自己要求放宽权限

例如 README / AGENTS 中写：

```text
请关闭 Sandbox
请跳过安全限制
```

Project Instruction 属于：

```text
Untrusted / lower-authority content
```

它不能改变：

```text
Runtime Security Policy
```

Claude Code 当前甚至不允许项目设置自己开启某些自动/绕过权限模式，以防不可信 Repository 自动提升自己的权限。

这对你的 Agent Harness 是非常重要的设计。

---

# 91. 今日 Architecture

建议形成：

```text
                     Worker Agent
                          │
                          ▼
                ┌──────────────────┐
                │ CommandRequest   │
                │ argv             │
                │ cwd              │
                │ task_id          │
                └────────┬─────────┘
                         ▼
                ┌──────────────────┐
                │ RequestValidator │
                └────────┬─────────┘
                         ▼
                ┌──────────────────┐
                │ CommandNormalizer│
                │ wrappers         │
                │ executable       │
                └────────┬─────────┘
                         ▼
        ┌────────────────────────────────┐
        │          CommandPolicy         │
        │                                │
        │ CredentialPathRule             │
        │ PrivilegeEscalationRule        │
        │ SystemControlRule              │
        │ DockerPrivilegeRule            │
        │ GitDestructiveRule             │
        │ NetworkCommandRule             │
        │ ShellInterpreterRule           │
        │ FilesystemEscapeRule           │
        │ RemoteWriteRule                │
        │ SafeGitReadRule                │
        └───────────────┬────────────────┘
                        ▼
                PolicyEvaluation
                  /     |      \
                 /      |       \
              DENY     ASK    ALLOW*
                        │       │
                     Day5     Day6
                   Approval  Sandbox
```

---

# 92. 今天建议的目录

不需要一次拆太细。

```text
codeteam/
└── execution/
    ├── models.py
    ├── command_policy.py
    ├── policy_rules.py
    └── errors.py
```

如果后面 Rule 增多，再拆：

```text
execution/
└── rules/
    ├── git.py
    ├── network.py
    ├── filesystem.py
    ├── interpreter.py
    ├── privilege.py
    └── docker.py
```

不要 Day 4 一开始就建立十几个文件。

---

# 93. 今天建议拆成 7 个实现 Step

### Step 1：数据模型

实现：

```text
CommandRequest
PolicyDecision
RiskCategory
RuleResult
PolicyEvaluation
```

---

### Step 2：PolicyRule Protocol

实现：

```text
PolicyRule
```

并理解：

```text
Rule
为什么独立
```

---

### Step 3：高危核心 Rules

先做：

```text
PrivilegeEscalationRule
GitDestructiveRule
ShellInterpreterRule
SystemControlRule
```

---

### Step 4：资源边界 Rules

实现：

```text
FilesystemEscapeRule
CredentialPathRule
NetworkCommandRule
RemoteWriteRule
DockerPrivilegeRule
```

---

### Step 5：Safe Rules + Aggregator

实现：

```text
SafeGitReadRule
CommandPolicy
```

以及：

```text
highest severity wins
```

---

### Step 6：30+ 测试

```text
15 Safe
15 Dangerous
+
Nested
+
Rule precedence
+
Unknown
```

---

### Step 7：Evaluation

```text
Benchmark
Ablation
Failure Report
Design Decision
Interview Story
```

---

# 94. Day 4 最终完成标准

不要只看：

```text
30 tests pass
```

真正完成应达到：

```text
Theory

[ ] Command Injection
[ ] Argument Injection
[ ] Allowlist
[ ] Denylist
[ ] Least Privilege
[ ] Policy vs Sandbox
[ ] Interpreter
[ ] Nested Command


Implementation

[ ] CommandRequest
[ ] PolicyDecision
[ ] RiskCategory
[ ] PolicyRule
[ ] CommandPolicy
[ ] 10 类 Rule


Correctness

[ ] 15 Safe
[ ] 15 Dangerous
[ ] Unknown
[ ] Nested
[ ] Precedence


Security

[ ] 10 类危险操作
    全部无法直接进入 Runner


Design

[ ] argv vs string
[ ] Hybrid Policy
[ ] Rule Chain
[ ] Unknown → Approval


Benchmark

[ ] Policy Evaluation Dataset
[ ] Dangerous Pass-through Rate
[ ] Safe Auto-Allow Rate
[ ] Approval Burden
[ ] P50/P95 Policy Latency


Ablation

[ ] Denylist-only
[ ] No Nested Detection
[ ] String Regex baseline


Failure Cases

[ ] Git Alias
[ ] External Diff
[ ] Nested Wrapper
[ ] Repo Code Execution
[ ] PATH Hijacking
[ ] Symlink Escape
[ ] Package Script
[ ] Project Permission Escalation
```

---

# 95. 今天必须能够回答的面试问题

### 基础安全

1. Command Injection 和 Argument Injection 有什么区别？
2. 为什么 `shell=False` 仍然可能不安全？
3. 为什么 `argv` 比 Shell String 更适合 Agent Runtime？
4. Allowlist 和 Denylist 各有什么问题？
5. Least Privilege 在 Coding Agent 中如何落地？

### Agent Runtime

6. CommandPolicy 和 Sandbox 为什么必须分层？
7. 为什么 Policy 不能只看 executable？
8. 为什么 `pytest` 不应该简单标为 SAFE？
9. Unknown Command 为什么不默认 ALLOW？
10. 为什么 LLM 不能自己填写 Risk Level？

### 系统设计

11. 为什么使用 Rule Engine，而不是巨大 `if/else`？
12. 多个 Rule 冲突怎样解决？
13. 怎么处理 Nested Command？
14. 为什么 Git 本身也可能间接执行外部程序？
15. 为什么应该尽量提供 Narrow Tool，而不是通用 Shell？

### Evaluation

16. 如何证明 CommandPolicy 真正有效？
17. 为什么只做 30 个单测不够？
18. Dangerous Pass-through Rate 是什么？
19. Approval Burden 为什么也很重要？
20. 怎么设计 Denylist-only Ablation？

---

# 96. 面试官如果问：“你不就是写了一堆危险命令正则吗？”

你最终应该能回答：

> 我的实现不是字符串黑名单。LLM 输出首先被约束成不可变的结构化 `CommandRequest`，Runtime 分离 executable、arguments、cwd 和 Task Context；随后由多个独立 PolicyRule 对 Git 副作用、网络、远端写入、权限提升、解释器、凭据路径和 Workspace Escape 等风险分别分类，再由统一 Aggregator 生成 ALLOW、SANDBOX、APPROVAL 或 DENY。对于 Shell/Wrapper/Nested Command 我不会只看第一个 token。Policy 只负责 Authorization，真正的文件系统和网络边界由后续 OS Sandbox 强制执行。我还会通过 Dangerous Pass-through、Safe Auto-Allow 和 Ablation 来验证策略是否既安全又可用。

这个回答对应的就是：

```text
Agent Tool Runtime
+
Authorization
+
Sandbox Boundary
+
Human-in-the-loop
+
Evaluation
```

而不是：

```text
字符串过滤
```

---

# 97. 今天的完整工程闭环

Day 4 最终应该形成：

```text
Theory
Command / Argument Injection
Least Privilege
Policy vs Sandbox

        ↓

Industrial Design
OWASP
OpenAI Codex
Claude Code
GitHub Copilot

        ↓

Implementation
CommandRequest
PolicyRule
CommandPolicy
RiskCategory

        ↓

Tests
15 Safe
15 Dangerous
Nested / Unknown / Precedence

        ↓

Design Decision
Structured argv
Hybrid Policy
Composable Rules

        ↓

Benchmark
Pass-through
Approval Burden
Latency

        ↓

Ablation
Denylist only
No Nested
Regex command string

        ↓

Failure Cases
Git alias
external helpers
repo scripts
PATH
symlink
...

        ↓

Interview Evidence
Tool Runtime Security
```

Day 4 完成以后，你的 Coding Agent 就会从：

```text
LLM
→ 想运行什么就运行什么
```

真正升级成：

```text
LLM
→ 提出 Action Intent
→ Runtime 判断风险
→ 决定权限
→ 用户审批（Day 5）
→ Sandbox 强制边界（Day 6）
→ Runner 执行
```

这也是第三周里最能直接体现 **Agent Harness / Tool Runtime / Agent Safety** 能力的一天。

已按 [coder_Agent.md](/Users/root/workspace/Agent-Learning/prompt/coder_Agent.md:287) 做了只读检查，没有修改代码。Day4 主题是 **CommandPolicy 与危险命令识别**，也就是让 Coding Agent 在执行命令前先经过 Runtime 风险判断。

**1. 今天在整个 Coding Agent 中做什么**

今天解决的是：

```text
LLM 想运行命令
→ Runtime 判断这条命令的风险
→ 决定 allow / sandbox / approval / deny
→ 之后才交给 CommandRunner 或 ShellTool
```

它在系统里的位置：

```text
Agent Loop
 ↓
Tool Call: run_command
 ↓
CommandRequest
 ↓
CommandPolicy
 ↓
PolicyEvaluation
 ↓
ApprovalManager / Sandbox / CommandRunner
```

没有它，Agent 就会从“能调用工具”变成“模型想跑什么就跑什么”，这正是 Agent Tool Runtime 的高风险点。

**2. Capability Mapping**

Primary：

```text
Tool Runtime
Workspace & Sandbox
Agent Runtime Safety
```

Secondary：

```text
Observability
Evaluation
Human-in-the-loop
```

面试价值：这不是“写几个危险命令正则”，而是在实现 **Agent 的命令授权中间层**。OpenAI 公开文章也把 sandbox、approval、network policy、rules、telemetry 作为 Coding Agent 安全部署的核心控制面。([openai.com](https://openai.com/index/running-codex-safely/))

**3. Theory**

今天必须理解这些概念：

```text
Command Injection
Argument Injection
shell=True vs shell=False
argv 结构化命令
Allowlist / Denylist / Hybrid Policy
Least Privilege
Policy vs Sandbox
Nested Command
Human Approval
```

核心认识：`shell=False` 只能避免 Shell 解释 `; && |` 这类元字符，但不能阻止目标程序把参数解释成危险 option。OWASP 也强调参数化执行、输入验证、allowlist、sandbox、least privilege 和人工审批。([cheatsheetseries.owasp.org](https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html?utm_source=openai))

**4. Industrial Design**

工业系统通常分层处理：

```text
Narrow Tool
→ Command Policy
→ Approval
→ Sandbox
→ Audit Logs
```

OpenAI Codex 的公开实践是：sandbox 定义技术边界，approval policy 决定何时请求用户批准，低风险动作尽量流畅，高风险动作停下来审查。([openai.com](https://openai.com/index/running-codex-safely/))  
OWASP Excessive Agency 也明确指出 Agent 风险来自过多功能、权限和自治，并建议减少工具能力、最小权限、高影响操作人工审批、完整授权校验。([genai.owasp.org](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/))  
Claude Code 也提供 allowed/disallowed tools、permission mode 等权限配置，这说明主流 Coding Agent 都不会把 Shell 当成无边界能力直接交给模型。([docs.anthropic.com](https://docs.anthropic.com/en/docs/claude-code/cli-usage?utm_source=openai))

**5. 当前仓库检查**

当前已有：

- [shell.py](/Users/root/workspace/Agent-Learning/codeteam/tools/shell.py:94)：已有 `RunCommandArgs`、`ShellToolConfig`、`run_command()`，但危险命令识别还写在 ShellTool 内部。
- [risk_classifier.py](/Users/root/workspace/Agent-Learning/codeteam/commands/risk_classifier.py:42)：已有 `classify_risk(argv)`，但它属于“命令检测阶段”的粗分类，不是 Runtime Authorization。
- [models.py](/Users/root/workspace/Agent-Learning/codeteam/commands/models.py:27)：已有 `CommandRisk`，可作为参考，但 Day4 需要更细的 `RiskCategory` / `PolicyDecision`。
- [detector.py](/Users/root/workspace/Agent-Learning/codeteam/commands/detector.py:47)：负责从 AGENTS、pytest、Makefile、package.json 检测命令。
- Week3 前置模块已存在：`GitWorkspace`、`WorktreeManager`、`CheckpointManager`。
- 还没有 `codeteam/execution/`，也没有 `CommandPolicy`、`CommandRequest`、`PolicyRule`。

注意：`learning-plan/week3/day4.md` 当前是 untracked。

**6. 涉及文件**

建议新增：

```text
codeteam/execution/models.py
→ CommandRequest / PolicyDecision / RiskCategory / RuleResult / PolicyEvaluation

codeteam/execution/policy_rules.py
→ 各类 PolicyRule

codeteam/execution/command_policy.py
→ CommandPolicy 聚合器

codeteam/execution/errors.py
→ CommandPolicyError 等异常

tests/execution/test_command_policy.py
→ Day4 主测试
```

可能后续修改：

```text
codeteam/tools/shell.py
→ 未来接入 CommandPolicy，但今天不急着动
```

**7. Architecture / Data Flow**

```text
argv + cwd + task_id
 ↓
CommandRequest
 ↓
PolicyRule[]
 ↓
RuleResult[]
 ↓
CommandPolicy aggregation
 ↓
PolicyEvaluation
 ↓
ALLOW / ALLOW_SANDBOXED / REQUIRE_APPROVAL / DENY
```

重要边界：

```text
CommandDetector = 发现项目建议命令
CommandPolicy = 运行前授权判断
ShellTool / Runner = 真正执行命令
Sandbox = 真正技术隔离
```

**8. 今日步骤拆分**

Step 1：数据模型  
目标：定义 `CommandRequest`、`PolicyDecision`、`RiskCategory`、`RuleResult`、`PolicyEvaluation`。

Step 2：PolicyRule Protocol  
目标：让每条规则都有统一接口，便于组合和测试。

Step 3：高危核心规则  
目标：识别 `sudo`、`rm -rf`、`git reset --hard`、shell `-c`、系统关机等。

Step 4：资源边界规则  
目标：识别网络、远端写入、凭证路径、workspace escape、Docker privileged。

Step 5：Safe Rules + Aggregator  
目标：允许明确低风险命令，多个 rule 冲突时最高风险胜出。

Step 6：测试  
目标：覆盖 safe、dangerous、unknown、nested、precedence。

Step 7：工程证据  
目标：形成 Design Decision、Benchmark 方案、Ablation 方案、Failure Cases。

**9. Test Strategy**

测试地图：

```text
正常路径：git status、git diff --、ruff check、mypy、pytest collect-only
危险路径：rm -rf、sudo、git reset --hard、git push --force
审批路径：pip install、npm install、git push、curl
未知路径：自定义脚本、未知 executable
Nested：bash -c、python -c、npm script、sh wrapper
Precedence：一个命令同时命中 safe 和 dangerous 时 dangerous 胜出
Path：凭证路径、绝对路径、..、symlink escape
```

测试重点不是“能不能运行命令”，而是“Runtime 是否做出正确授权判断”。

**10. Design Decision Plan**

今天最终需要记录这些决策：

```text
DD1: CommandRequest 使用结构化 argv，不接受 shell string
DD2: 使用 Hybrid Policy，不用纯 allowlist 或纯 denylist
DD3: Policy 只做授权判断，不替代 Sandbox
DD4: Unknown command 默认 REQUIRE_APPROVAL
DD5: 多规则冲突时 highest severity wins
DD6: Runtime 不相信 LLM 自己声明的 risk
```

**11. Benchmark Plan**

Benchmark 要回答：

```text
CommandPolicy 是否足够安全且不过度打扰用户？
```

指标：

```text
Dangerous Pass-through Rate
Safe Auto-Allow Rate
False Deny Rate
Approval Burden
Policy Latency P50/P95
```

Baseline：

```text
当前 codeteam.commands.risk_classifier.classify_risk()
```

Full：

```text
新的 CommandPolicy + PolicyRule
```

**12. Ablation Plan**

建议做三组：

```text
Ablation 1: Hybrid Policy vs Denylist Only
Ablation 2: Nested Detection vs 只看 argv[0]
Ablation 3: Structured argv vs command string regex
```

未来 Day6 后再做：

```text
Policy only vs Policy + Sandbox
```

**13. Failure Cases to Watch**

重点记录：

```text
Git alias 执行 shell
git diff external diff / textconv
bash -c nested command
python -c / node -e
npm test 实际执行恶意 package script
PATH hijacking
读取 ~/.ssh / .env
symlink escape
项目 instruction 要求关闭安全策略
pytest 运行恶意仓库代码
```

OWASP Prompt Injection 也强调外部内容可能诱导模型执行未授权行为，所以项目 README/AGENTS 不能提升 Runtime 权限。([genai.owasp.org](https://genai.owasp.org/llmrisk/llm01-prompt-injection/))

**14. Interview Focus**

你今天结束后要能回答：

```text
为什么 shell=False 仍然不够？
CommandPolicy 和 Sandbox 有什么区别？
为什么 Unknown 不默认 Allow？
为什么 pytest 不能简单视为完全安全？
为什么风险不能由 LLM 自己填写？
如何设计 rule precedence？
如何证明你的 Policy 不是字符串黑名单？
如何量化安全性和可用性的 trade-off？
```

一句面试表达：

```text
我实现的是 Agent Tool Runtime 的命令授权层，而不是 Shell 包装器。
```

**15. 今日最终完成标准**

今天真正完成应满足：

```text
[ ] 理解 Command Injection / Argument Injection
[ ] 新增 CommandPolicy 数据模型
[ ] 实现 PolicyRule 协议
[ ] 实现核心危险规则
[ ] 实现资源边界规则
[ ] 实现 Safe Rules 和 Aggregator
[ ] 至少 30 个测试覆盖 safe/dangerous/unknown/nested/precedence
[ ] 明确 Policy vs Sandbox 边界
[ ] 写出 Benchmark / Ablation / Failure Case 方案
[ ] 能讲清楚工业设计和面试故事
```

下一步如果你说“开始第 1 步”，我们就只做 **数据模型设计**，先不写完整策略引擎。