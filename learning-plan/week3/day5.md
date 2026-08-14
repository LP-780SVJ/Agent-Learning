# 第 3 周 Day 5：ApprovalManager + Safe CommandRunner

今天这一课，是把昨天的 **“能不能执行？”** 补成真正可运行的 Agent Tool Runtime：

```text
Day 4
CommandPolicy
→ 这条命令风险是什么？

Day 5
ApprovalManager
→ 用户是否授权？

Safe CommandRunner
→ 授权以后，怎样有限、可控、可终止地执行？

Day 6
Sandbox
→ 即使程序恶意，它技术上最多能做什么？
```

最终形成：

```text
LLM / Worker Agent
        │
        ▼
   CommandRequest
        │
        ▼
   CommandPolicy
        │
 ┌──────┼──────────────┐
 │      │              │
DENY   ALLOW     REQUIRE_APPROVAL
 │      │              │
 stop   │              ▼
        │       ApprovalManager
        │         │         │
        │       DENY      APPROVE
        │         │         │
        │        stop       │
        └──────────────┬────┘
                       ▼
                 Sandbox Profile
                       │
                       ▼
                CommandRunner
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
           stdout    stderr    process tree
             │         │         │
             ▼         ▼         ▼
          truncate  truncate   timeout
                                   │
                               SIGTERM
                                   │
                               grace period
                                   │
                               SIGKILL
                                   ▼
                            CommandResult
```

今天最重要的认识是：

> **Approval 是授权机制，Runner 是执行机制。两者不能混在一起。**

---

# 1. Capability Mapping

Day 5 主要证明：

```text
Tool Runtime
├── Human-in-the-loop authorization
├── Safe process execution
├── Timeout
├── Output control
├── Environment isolation
└── Structured execution result

Agent Runtime
├── Action gating
├── Long-running process lifecycle
├── Cancellation
└── Failure handling

Observability
├── Approval audit
├── Process audit
├── Timeout event
└── Output truncation event

Safety
├── Least privilege
├── Secret isolation
├── Process cleanup
└── Resource bounds
```

所以今天并不是：

```text
“学 subprocess.Popen”
```

而是在实现：

> **Agent Runtime 的 Human Authorization + Process Supervisor。**

---

# 2. 为什么有了 CommandPolicy 还需要 Approval？

Day 4 已经能输出：

```text
ALLOW
ALLOW_SANDBOXED
REQUIRE_APPROVAL
DENY
```

那么：

```text
DENY
```

很好处理：

```text
直接拒绝
```

但：

```text
REQUIRE_APPROVAL
```

意味着：

> Runtime 自己不能替用户做这个决定。

例如：

```text
git push origin feature
```

它未必永远应该禁止。

因为用户可能真的要求：

```text
把我的代码提交到远端
```

但是 Agent 又不应该自行决定：

```text
“用户大概想让我 push，我直接干了。”
```

因此：

```text
Policy
=
机器判断风险

Approval
=
人授予权限
```

---

# 3. OpenAI Codex 当前就是这种分层

OpenAI 当前 Codex 官方文档明确把安全控制拆成两层：

```text
Sandbox mode
=
技术上能够做什么

Approval policy
=
什么时候必须停止并请求用户授权
```

默认网络访问受到限制；当操作超出已有 Sandbox 边界或受信范围时，Approval Flow 接管，而不是让 Agent 自己决定越权。

这个架构给你的启示是：

```text
Approval
不能代替 Sandbox

Sandbox
也不能代替 Approval
```

比如：

```text
git push
```

即使 Sandbox 允许联网，

依然可能需要：

```text
用户批准
```

反过来用户批准：

```text
运行 pytest
```

也不意味着 pytest 应该获得：

```text
整个 HOME
SSH Key
公网
Docker Socket
```

访问能力。

---

# 4. Approval Scope 是什么

这是今天第一大理论重点。

Approval 不能只有：

```text
approved = True
```

因为真正的问题是：

> **批准了什么？对谁批准？批准多久？在哪个资源范围内批准？**

一个 Approval 实际至少有四个维度：

```text
Subject
谁获得权限？

Action
获得什么操作权限？

Resource
可以操作什么资源？

Lifetime
权限持续多久？
```

例如：

```text
Subject:
task-001

Action:
python -m pytest

Resource:
/tmp/codeteam/task-001

Lifetime:
one-shot
```

这才是一个完整授权。

---

# 5. One-shot Approval

最保守的 Scope：

```text
ONCE
```

例如 Agent 请求：

```text
python -m pytest tests/git
```

用户点击：

```text
Allow once
```

代表：

```text
只允许这一个 CommandRequest
执行一次
```

不是：

```text
以后所有 python 命令都允许
```

也不是：

```text
以后所有 pytest 命令都允许
```

更不是：

```text
task-001 以后随便执行
```

---

# 6. One-shot 应该怎样实现

推荐不是存：

```python
approved_commands.add(
    "python"
)
```

而是创建一个：

```text
Approval Grant
```

绑定到：

```text
task_id
argv
cwd
sandbox_profile
network requirement
```

例如：

```text
task_id:
task-001

argv:
("python", "-m", "pytest", "tests/git")

cwd:
/tmp/codeteam/task-001

network:
False
```

计算一个：

```text
request_fingerprint
```

例如：

```text
SHA256(
    canonical_command_request
)
```

然后 Approval：

```text
fingerprint = ABC123
scope = ONCE
```

真正执行之前：

```text
Current Request Fingerprint
        ==
Approved Fingerprint
```

才能运行。

---

# 7. 为什么需要 Fingerprint？

这是一个非常重要的安全问题：

```text
TOCTOU
Time of Check to Time of Use
```

假设：

```text
T1
用户批准：

git push origin feature


T2
Agent 修改 Request：

git push --force origin main


T3
Runner 看见：
“前面批准过 git”
→ 执行
```

这就是授权漏洞。

正确方式：

```text
用户批准的是：
Request A

Runner 执行前：
Request B

A != B

→ Approval invalid
```

---

# 8. Approval 应绑定“执行身份”

建议以后把：

```text
CommandRequest
```

序列化成 canonical form：

```text
task_id
agent_id
argv
cwd
network_profile
sandbox_profile
```

而：

```text
reason
```

不应该是安全身份的一部分。

因为：

```text
reason="run tests"
```

只是解释文本。

LLM 随时可以写：

```text
reason="safe command"
```

它不具有安全意义。

---

# 9. Task Approval 是什么

你今天的第二种 Scope：

```text
TASK
```

但这里很容易设计错。

错误理解：

```text
用户批准 task-001
↓
task-001 后续所有命令随便跑
```

这相当于：

```text
Approve Everything
```

Task Scope 应理解成：

> **某一类明确能力，在当前 Task 生命周期内重复使用。**

例如：

```text
task:
task-001

capability:
python -m pytest ...

cwd:
task-001 workspace

network:
disabled
```

那么：

```text
python -m pytest tests/unit
python -m pytest tests/git
```

可能共享这个 Approval。

但：

```text
python -c ...
```

不能。

更不能：

```text
git push
```

---

# 10. 所以 Task Approval 实际上是

```text
Task
×
Command Capability
×
Resource Boundary
×
Execution Profile
```

而不是：

```text
Task
→ Allow Everything
```

这一点以后面试非常值得讲。

---

# 11. GitHub Copilot CLI 的工业 Approval Scope

GitHub 当前 Copilot CLI 提供了非常直接的 Scope 示例。

权限 Prompt 可以选择：

```text
y
→ 只允许这一次

!
→ 当前 Session 中允许类似请求
```

完整权限 UI 还区分：

```text
Once
This location
Always
```

其中 location 可以基于 Git Root / 当前目录持久化；同时可以用 `/permissions reset` 清除当前 Session 的内存授权。

你会发现工业系统不会只有：

```text
yes / no
```

而是会设计：

```text
批准范围
+
批准生命周期
```

---

# 12. Claude Code 也是类似思路

Claude Code 当前权限系统同样明确区分：

```text
allow
ask
deny
```

权限由 Claude Code Runtime 执行，而不是模型自己决定；官方安全说明也明确支持用户选择只批准一次，或让某类操作后续自动通过。

这证明：

> **Approval Scope 是现代 Coding Agent Runtime 的核心机制，不只是 UI 按钮。**

---

# 13. CodeTeam 第一版应该支持哪些 Scope？

我建议 Day 5 只真正实现：

```python
class ApprovalScope(str, Enum):
    ONCE = "once"
    TASK = "task"
```

以后再扩展：

```text
SESSION
LOCATION
PERSISTENT
```

原因：

```text
ONCE
最安全、最容易理解

TASK
最贴合 Multi-Agent Runtime

SESSION
涉及跨 Task 权限传播

PERSISTENT
涉及长期权限配置与安全治理
```

先不要一次把授权系统做得过度复杂。

---

# 14. 一个重要原则：DENY 不能被 Approval 推翻

昨天：

```text
git reset --hard
→ DENY
```

今天不能：

```text
用户点了 Approve
→ 执行
```

否则：

```text
DENY
```

和：

```text
REQUIRE_APPROVAL
```

失去区别。

正确：

```text
ALLOW
→ 可继续

ALLOW_SANDBOXED
→ Sandbox 后执行

REQUIRE_APPROVAL
→ 可以被用户授权

DENY
→ ApprovalManager 无权提升
```

所以：

> **只有 `REQUIRE_APPROVAL` 才能进入 ApprovalManager。**

---

# 15. ApprovalDecision

建议：

```python
class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"
```

不要混入：

```text
ALLOW
DENY
```

因为：

```text
PolicyDecision
```

与：

```text
ApprovalDecision
```

属于两个不同层。

例如：

```text
PolicyDecision:
REQUIRE_APPROVAL

ApprovalDecision:
APPROVED
```

最终才能：

```text
EXECUTE
```

---

# 16. ApprovalRequest 应该保存什么

第一版建议类似：

```python
class ApprovalRequest(BaseModel):
    approval_id: str

    task_id: str
    agent_id: str

    command_fingerprint: str

    argv: tuple[str, ...]
    cwd: str

    risk_categories: tuple[
        RiskCategory,
        ...
    ]

    reasons: tuple[str, ...]

    requested_scope: ApprovalScope

    created_at: datetime
```

注意用户看到的 Approval UI 应该显示：

```text
准备运行什么？
在哪个目录？
为什么？
有哪些风险？
是否需要网络？
批准范围是什么？
```

而不是：

```text
Allow?  [Y/N]
```

---

# 17. ApprovalManager 应负责什么

推荐职责：

```text
ApprovalManager

负责：
创建 ApprovalRequest
记录用户决定
创建 Approval Grant
检查 Grant 是否匹配
消费 One-shot Grant
处理 Task Scope
记录 Audit Event

不负责：
执行 Command
判断 Command 风险
Sandbox
Timeout
```

也就是说：

```text
CommandPolicy
≠
ApprovalManager
≠
CommandRunner
```

---

# 18. One-shot 必须是“消费型”的

假设：

```text
approval:
scope=ONCE
```

第一次：

```text
check
→ valid

consume
→ used
```

第二次再拿：

```text
same approval
```

应该：

```text
invalid
```

否则所谓：

```text
one-shot
```

其实是无限次 Token。

---

# 19. 并发下还要注意原子消费

假设两个 Worker 同时：

```text
check approval
```

如果逻辑是：

```python
if not grant.used:
    execute()
    grant.used = True
```

可能：

```text
Thread A:
used=False

Thread B:
used=False

A execute
B execute
```

One-shot 被用了两次。

所以真正设计需要：

```text
check + consume
```

成为一个原子操作。

Day 5 单机 MVP 可以用：

```text
Lock
```

以后持久化可以：

```text
transaction / CAS
```

---

# 20. Approval Audit Log

Approval 最大问题之一是：

> **事后必须能回答为什么这条高风险命令执行了。**

所以至少记录：

```text
approval.requested

approval.approved

approval.denied

approval.consumed

approval.expired
```

每条事件至少：

```text
event_id
timestamp

task_id
agent_id

approval_id
command_fingerprint

scope

risk_categories

decision

actor
```

---

# 21. Audit Log 不等于 Debug Log

Debug Log：

```text
正在检查 approval...
grant found...
```

Audit Log：

```text
谁
在什么时候
批准了什么能力
作用于哪个 Task
实际使用了吗
```

Audit Log 应尽量：

```text
Append-only
```

而不是：

```text
approval.json
不断覆盖
```

---

# 22. 工业界为什么非常重视 Audit

GitHub 当前 Copilot 企业能力提供 Agent Activity Audit Log，Agent Session 也保留工具使用信息；GitHub 还明确建议企业将长期 Audit 数据流式发送到 SIEM。

Copilot SDK / CLI 的 Hook 体系也明确可用于 Tool Approval、Policy Enforcement 和 Audit Logging。

因此 Observability 并不是 Agent 系统上线后才补的东西。

---

# 23. Audit Log 绝不能偷偷记录 Secret

例如：

```text
command:
curl -H "Authorization: Bearer SECRET"
```

如果你把完整 argv 写进 Audit Log：

```text
安全系统
反而永久保存了 Secret
```

所以建议 Audit 存：

```text
sanitized_argv
+
command_fingerprint
```

敏感参数：

```text
***REDACTED***
```

---

# 24. ApprovalManager 之后进入 CommandRunner

现在进入今天第二大核心：

# Safe CommandRunner

Runner 解决的问题不是：

```text
Python 如何执行命令
```

而是：

> **怎样监督一个不可信、可能卡死、可能疯狂输出、可能 Fork 子进程的程序？**

---

# 25. 一个普通 subprocess 为什么不够

最简单：

```python
subprocess.run(
    argv
)
```

会立刻遇到几个 Agent Runtime 问题：

```text
程序永不退出怎么办？

程序 Fork 子进程怎么办？

程序输出 10 GB 怎么办？

程序等待 stdin 怎么办？

程序修改环境怎么办？

程序 exit 1 怎么区分？

Executable 不存在怎么办？

Timeout 后孙进程还活着怎么办？
```

因此 Runner 本质是：

> **Process Supervisor**

---

# 26. CommandLimits

今天推荐：

```python
class CommandLimits(BaseModel):
    timeout_seconds: float = 60.0

    terminate_grace_seconds: float = 2.0

    max_stdout_bytes: int = 64 * 1024

    max_stderr_bytes: int = 64 * 1024

    max_combined_output_bytes: int = (
        128 * 1024
    )
```

将来 Day 6 Sandbox 还能加入：

```text
memory
CPU
PID
network
filesystem
```

但今天先管理：

```text
time
output
process lifecycle
```

---

# 27. Timeout 到底是什么意思

假设：

```text
timeout_seconds = 10
```

真正语义应该定义为：

> 子进程成功启动以后，允许它执行的最大 Wall-clock Duration。

不能只：

```python
proc.wait(timeout=10)
```

然后异常一抛就结束。

因为：

```text
TimeoutExpired
```

并不等于：

```text
Process 已经消失
```

Python 当前 `Popen.communicate(timeout=...)` 文档明确说明：发生 timeout 后，子进程不会自动被清理，调用方需要终止/kill 后继续 `communicate()` 以完成清理和回收。

---

# 28. 所以 Timeout 必须触发“终止流程”

推荐：

```text
deadline reached
      │
      ▼
SIGTERM
      │
      ▼
wait grace period
      │
 ┌────┴────┐
 │         │
exit     still alive
 │         │
done       ▼
         SIGKILL
            │
            ▼
           wait
            │
            ▼
          reap
```

---

# 29. 为什么先 SIGTERM？

在 POSIX 上：

```text
SIGTERM
```

是终止请求。

程序可以：

```text
接收
清理
flush
删除临时文件
关闭数据库
正常退出
```

Python 的 `Popen.terminate()` 在 POSIX 系统上发送 SIGTERM。

因此第一阶段是：

```text
graceful termination
```

---

# 30. 为什么最后还需要 SIGKILL？

程序可能：

```text
忽略 SIGTERM

死循环

Handler 卡住

第三方程序有 Bug
```

这时需要：

```text
SIGKILL
```

Python 官方 signal 文档明确说明，SIGKILL 无法被捕获、阻塞或忽略；`Popen.kill()` 在 POSIX 上发送 SIGKILL。

所以：

```text
SIGTERM
=
请退出

SIGKILL
=
立即退出
```

---

# 31. 但只杀主 Process 还不够

这是今天最重要的 Runner 知识之一。

假设：

```text
Agent command
    │
    ▼
python parent.py
    │
    ├── child A
    │
    └── child B
```

Timeout 时你执行：

```python
proc.kill()
```

可能只杀：

```text
parent
```

而：

```text
child A
child B
```

仍然继续运行。

这就产生：

```text
Orphan / leaked process
```

---

# 32. 为什么需要 Process Group

POSIX 提供：

```text
Process Group
```

把一组相关 Process 组织在一起。

Python 的 `Popen(start_new_session=True)` 在 POSIX 下会在执行子程序前调用 `setsid()`；Python 也提供 `process_group` 参数来设置进程组。

于是：

```text
CommandRunner
     │
     ▼
Process Group
 ├── parent
 ├── child
 └── grandchild
```

Timeout：

```python
os.killpg(
    pgid,
    signal.SIGTERM,
)
```

Python `os.killpg()` 的语义就是向整个 Process Group 发送 Signal。

---

# 33. 所以推荐 POSIX Runner

启动：

```python
Popen(
    argv,
    shell=False,
    start_new_session=True,
    ...
)
```

Timeout：

```text
killpg(SIGTERM)
↓
wait
↓
killpg(SIGKILL)
```

而不是：

```text
proc.kill()
```

只处理一个 PID。

---

# 34. Process Group 和 Sandbox 不是同一个东西

Process Group 能：

```text
一起终止进程
```

不能：

```text
限制文件访问
限制网络
限制 CPU
限制内存
```

甚至进程自己还可能：

```text
setsid()
```

脱离原 Process Group。

所以：

```text
Process Group
=
Lifecycle Control

Sandbox
=
Capability Isolation
```

不要混淆。

---

# 35. Windows 怎么办？

Python 在 Windows 支持：

```text
CREATE_NEW_PROCESS_GROUP
```

并支持特定 Console Control Event；同时 Windows 的 `terminate()/kill()` 语义与 POSIX 不完全相同。

如果未来追求真正可靠的：

```text
kill entire process tree
```

Windows 更适合使用：

```text
Job Object
```

之类的平台执行后端。

所以 CodeTeam 第一版建议：

```text
ProcessController Protocol

POSIXProcessController
WindowsProcessController (later)
```

而不要假装：

```text
一段 signal 代码跨平台完全等价
```

---

# 36. “超过 Timeout 一定结束”要怎样严谨定义

这里有一个非常重要的工程细节。

Python 官方说明，在某些平台 API 上：

```text
process creation
```

本身可能无法立即被 timeout 中断。

因此你真正可以承诺的是：

> **一旦 Process 成功 Spawn，CommandRunner 到达 Deadline 后必须启动终止流程，并在 `terminate_grace + kill/wait` 后确保受控 Process Group 不再运行。**

不要面试时夸张成：

```text
任何系统调用任何情况都能严格 1.000 秒停止
```

---

# 37. Output Limit 为什么是 Agent Runtime 必需能力

假设 Agent 运行：

```text
pytest
```

结果因为某个 Bug：

```text
while True:
    print("error")
```

产生：

```text
100 MB
1 GB
10 GB
```

如果 Runtime 把全部 Output：

```text
保存在 Python 内存
+
发送给 LLM
```

你会同时得到：

```text
OOM

巨量 Token

Context Pollution

UI 崩溃
```

---

# 38. Python `communicate()` 有一个重要限制

Python 官方文档明确说明：

```text
communicate()
```

会把读取的数据缓存到内存，因此不适合大或无限 Output。

所以最终工业 Runner 不能简单：

```python
stdout, stderr = proc.communicate()
stdout = stdout[:65536]
```

因为：

> 截断发生得太晚了。

你可能已经读取了 5GB。

---

# 39. 另一个错误：达到 Limit 后停止读取

例如：

```python
if len(stdout) >= 64KB:
    stop_reading_stdout()
```

这也错。

为什么？

因为 OS Pipe Buffer 是有限的。

如果 Parent 不继续读取：

```text
Child
不停 write()

Pipe 满

Child block
```

Python 官方也提醒，当 stdout/stderr 使用 PIPE 而调用方没有持续消费时，可能因为 Pipe 填满发生 Deadlock。

---

# 40. 正确原则：继续 Drain，只是不继续保存

例如：

```text
Child stdout
      │
      ▼
Runner Reader
      │
      ├── first 16KB → save
      │
      ├── middle      → discard
      │
      └── last 48KB  → save
```

但是：

```text
所有 bytes
都继续从 Pipe 读取
```

因此 Child 不会因为 Pipe 填满而卡住。

---

# 41. 为什么 Head + Tail 比只保留前 N KB 更好

只保留：

```text
First 64KB
```

可能丢失真正 Error：

```text
...
50000 行 build output
...
FINAL ERROR:
Compilation failed
```

所以推荐：

```text
Head:
16KB

Tail:
48KB
```

最终：

```text
[first output]

... output truncated ...

[last output]
```

这样 LLM 同时看到：

```text
启动信息
+
最终错误
```

---

# 42. stdout 与 stderr 应该独立限制

不要：

```text
stdout + stderr
→ 一个字符串
```

因为：

```text
stdout
```

通常是程序正常输出。

```text
stderr
```

通常是诊断信息。

建议：

```text
max_stdout_bytes
max_stderr_bytes
```

分别控制。

另外：

```text
max_combined_output_bytes
```

可以作为整体 Budget。

---

# 43. 内部最好按 bytes 处理

因为：

```text
64 KB
```

是：

```text
bytes
```

不是：

```text
characters
```

尤其：

```text
中文
UTF-8
```

一个字符可能多字节。

建议：

```text
Reader
→ bytes

Buffer
→ bytes

最终
→ decode(errors="replace")
```

否则一个 UTF-8 字符恰好被截断一半时，可能出现解码异常。

---

# 44. 一个推荐的 OutputLimiter

概念：

```text
OutputLimiter

head_limit
tail_limit

total_bytes_seen

truncated
```

逻辑：

```text
前 head_limit
→ 保存

超过以后
→ Ring Buffer 保存最后 tail_limit

全部都计数
```

最终：

```text
captured_bytes
<=
head + tail
```

但：

```text
total_bytes_seen
```

可能是：

```text
10,000,000
```

于是 `CommandResult` 可以告诉用户：

```text
Original stdout:
10 MB

Captured:
64 KB

Truncated:
True
```

---

# 45. Environment Variables 为什么是安全问题

很多人把：

```text
env
```

只看成配置问题。

Agent Runtime 里它还是：

> **Secret Capability Channel**

父进程可能有：

```text
API keys
Cloud credentials
GitHub token
SSH agent socket
Internal endpoints
```

如果 Runner 默认：

```python
env=os.environ.copy()
```

那么 Repo 内的：

```text
pytest
npm script
Python script
```

都可能读取这些 Secret。

---

# 46. Python 的 `env` 参数有什么意义

Python 当前 `Popen(env=...)` 允许显式传入环境变量 Mapping；如果 `env` 不为 `None`，它会替代默认继承父进程环境的行为。

因此不要：

```text
默认继承所有 Environment
```

更好的方式：

```text
EnvironmentPolicy
      ↓
minimal env
```

---

# 47. 第一版推荐 Allowlist Environment

例如 POSIX 下可以考虑：

```text
PATH
LANG
LC_ALL
TMPDIR
HOME
```

但：

```text
HOME
```

最好以后指向：

```text
Sandbox-specific HOME
```

而不是用户真实 HOME。

Python 官方还提醒，显式 `env` 必须包含目标程序正常运行需要的变量；Windows 某些程序环境还需要有效的 `SystemRoot`。

---

# 48. 默认不要继承 Secret

例如：

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
AWS_*
GITHUB_TOKEN
GH_TOKEN
SSH_AUTH_SOCK
```

除非：

```text
这个 Command 明确需要
+
Policy 允许
+
用户批准
+
Sandbox Profile 允许
```

否则 Runner 应隐藏。

---

# 49. PATH 也不能完全忽略

假设：

```text
argv[0] = "git"
```

Runner 实际执行哪个：

```text
git
```

取决于 Executable Resolution。

Python 官方指出，`cwd`、`PATH` 和平台行为都会影响 Executable Search；使用完整 Executable Path 可以避免很多平台差异。

所以未来更稳妥：

```text
CommandNormalizer
→ resolve trusted executable

Runner
→ execute absolute executable path
```

这也是对昨天：

```text
PATH Hijacking
```

Failure Case 的处理。

---

# 50. stdin 默认怎么办？

建议：

```python
stdin=subprocess.DEVNULL
```

而不是让 Command 继承：

```text
ChatGPT / IDE Terminal stdin
```

因为程序可能：

```text
Are you sure? [y/N]
```

然后永远等待输入。

对于非交互 Agent Runner：

```text
stdin closed
```

应该是默认。

以后真正需要互动时：

```text
InteractiveCommandRunner / PTY
```

单独设计。

不要把两者混在一起。

---

# 51. CommandResult 为什么不能只是 returncode

建议：

```python
class CommandStatus(str, Enum):
    SUCCESS = "success"
    NONZERO_EXIT = "nonzero_exit"
    TIMED_OUT = "timed_out"
    START_FAILED = "start_failed"
```

然后：

```python
class CommandResult(BaseModel):
    status: CommandStatus

    exit_code: int | None

    stdout: str
    stderr: str

    stdout_total_bytes: int
    stderr_total_bytes: int

    stdout_truncated: bool
    stderr_truncated: bool

    timed_out: bool

    duration_ms: float

    terminated_with_sigterm: bool = False
    terminated_with_sigkill: bool = False

    error: str | None = None
```

---

# 52. 为什么 `exit_code != 0` 不是异常

例如：

```text
pytest
→ exit 1
```

这可能只是：

```text
测试失败
```

不是：

```text
CommandRunner 崩了
```

所以：

```text
NONZERO_EXIT
```

属于：

```text
Program Result
```

而：

```text
Executable 不存在
PermissionError
Popen 失败
```

属于：

```text
START_FAILED
```

两者必须区分。

---

# 53. Process 启动失败

例如：

```text
argv:
("definitely-does-not-exist",)
```

应该返回：

```text
START_FAILED
```

并记录：

```text
error_type
sanitized_error
```

而不是让：

```text
FileNotFoundError
```

一路冒到 Agent Loop，把整个 Agent Crash 掉。

---

# 54. Approval → Runner 的最终正确流程

建议不是：

```text
Policy
→ Approval
→ Runner
```

这么简单，而是：

```text
CommandRequest

↓
Policy.evaluate()

↓
DENY?
→ STOP

↓
REQUIRE_APPROVAL?
→ ApprovalManager.request()

↓
user approves

↓
verify approval matches exact current request

↓
consume one-shot / validate task grant

↓
select Sandbox Profile

↓
CommandRunner.run()

↓
Audit Result
```

---

# 55. 最好再有一层 `SafeExecutor`

这里我建议 Day 5 增加一个很薄的：

```text
SafeCommandExecutor
```

或者：

```text
CommandExecutionService
```

职责：

```text
Policy
→ Approval
→ Runner
```

否则 Agent 有可能未来直接调用：

```python
runner.run()
```

绕过：

```text
Policy + Approval
```

正确：

```text
LLM
只能访问：
SafeExecutor
```

底层：

```text
CommandRunner
```

不直接注册为 Tool。

---

# 56. 为什么这对验收非常重要

你的要求：

```text
用户拒绝
CommandRunner 调用次数 = 0
```

这实际上不是：

```text
ApprovalManager 单元测试
```

而是：

```text
Policy → Approval → Runner
```

的 Integration Test。

所以必须存在：

```text
orchestration layer
```

才能真正证明这个不变量。

---

# 57. OpenAI Codex 的审批设计还能给你什么启发

Codex 当前的 Rule 系统直接针对参数向量做 Prefix Rule，而不是只匹配一整条人类 Shell 字符串；Smart Approvals 还能在 Escalation 时提出 Prefix Rule。对于可以安全拆开的 Shell Compound Command，Codex 会分别评估各子命令，并让最严格结果获胜。

这说明工业 Approval 往往不是：

```text
“永久允许 bash”
```

而是尝试把授权缩小成：

```text
某个命令族
+
某些参数前缀
```

这和我们设计：

```text
TASK-scoped capability
```

非常接近。

---

# 58. 今天建议的代码结构

第一版不用拆太多：

```text
codeteam/
└── execution/
    ├── models.py
    ├── command_policy.py      # Day4
    ├── approval.py
    ├── runner.py
    ├── output_limiter.py
    └── executor.py
```

以后复杂再拆：

```text
runner/
├── base.py
├── posix.py
└── windows.py
```

---

# 59. Step 1：Approval Models

实现：

```text
ApprovalScope

ApprovalRequest

ApprovalDecision
```

以及内部可以增加：

```text
ApprovalGrant
```

目标：

```text
One-shot
Task-scoped
fingerprint
```

先把授权语义建清楚。

---

# 60. Step 2：ApprovalManager

至少支持：

```text
create_request()

approve()

deny()

is_authorized()

consume()
```

核心测试：

```text
ONCE 只能使用一次

TASK 不跨 task

DENY 不产生 Grant
```

---

# 61. Step 3：Audit Events

接入 Week 1 Event Log：

```text
approval.requested
approval.approved
approval.denied
approval.consumed
```

不要重新发明一套日志系统。

---

# 62. Step 4：CommandLimits / CommandResult

实现今天 Runner 的契约：

```text
timeout

grace

stdout limit

stderr limit

structured result
```

---

# 63. Step 5：OutputLimiter

实现：

```text
head + tail

total byte count

truncated
```

先单元测试这个纯组件。

这是非常适合独立测试的：

```text
deterministic utility
```

---

# 64. Step 6：CommandRunner

实现：

```text
Popen

stdin DEVNULL

stdout PIPE

stderr PIPE

environment filtering

process group

stream readers

timeout

SIGTERM
→ grace
→ SIGKILL
```

---

# 65. Step 7：SafeExecutor 集成

完成：

```text
Policy
→ Approval
→ Runner
```

并满足：

```text
DENY
Runner calls = 0

User DENY
Runner calls = 0

Unapproved REQUIRE_APPROVAL
Runner calls = 0

Approved
Runner calls = 1
```

---

# 66. 你的必做测试 1：用户拒绝

流程：

```text
Policy
→ REQUIRE_APPROVAL

Approval
→ DENIED

Runner
→ never called
```

最关键断言：

```python
assert fake_runner.call_count == 0
```

而不只是：

```python
assert decision == DENIED
```

---

# 67. 测试 2：用户批准一次

```text
ApprovalScope.ONCE
```

第一次：

```text
execute
→ success
```

第二次：

```text
same command
```

应该：

```text
没有新的 Approval
→ 不能执行
```

验证 One-shot：

```text
真的是“一次”
```

---

# 68. 测试 3：批准不跨 Task

批准：

```text
task-001

python -m pytest
```

然后：

```text
task-002
python -m pytest
```

必须：

```text
NOT AUTHORIZED
```

即使：

```text
argv
完全相同
```

---

# 69. 我建议再增加一个测试：批准后 Request 被修改

用户批准：

```text
git push origin feature
```

执行前变成另一个 Request。

Fingerprint：

```text
mismatch
```

必须：

```text
Runner calls = 0
```

这是非常重要的安全 Regression Test。

---

# 70. 测试 4：Timeout Command

安全测试：

```text
python
-c
sleep(...)
```

设置：

```text
timeout = 0.2 s
```

最后：

```text
CommandResult.status
=
TIMED_OUT
```

并且：

```text
process no longer alive
```

---

# 71. 测试 5：SIGTERM 被忽略

这是非常值得增加的测试。

子程序：

```text
忽略 SIGTERM
↓
sleep
```

Runner：

```text
timeout
↓
SIGTERM
↓
grace expires
↓
SIGKILL
```

最终：

```text
terminated_with_sigkill=True
```

这样你真正证明：

```text
Graceful termination 不成功
→ 有强制 fallback
```

---

# 72. 测试 6：子进程也被终止

建立：

```text
parent Python
    │
    └── child Python sleep
```

然后 parent 自己也 sleep。

Runner Timeout 后：

```text
parent
child
```

都不应该继续存活。

这个测试证明：

```text
Process Group
```

而不是只证明：

```text
proc.kill()
```

---

# 73. 测试 7：巨大 stdout

例如子程序连续输出：

```text
5 MB
```

配置：

```text
max_stdout = 64 KB
```

最终：

```text
stdout_total_bytes
≈ 5 MB

len(captured_stdout)
<= 64 KB + marker

stdout_truncated
=
True
```

并且：

```text
Command 能正常退出
```

说明没有 Pipe Deadlock。

---

# 74. 测试 8：巨大 stderr

同样单独验证：

```text
stderr
```

不要只测 stdout。

很多编译器和 Test Runner：

```text
大量日志
```

可能主要出现在 stderr。

---

# 75. 测试 9：stdout + stderr 同时巨大

这个我强烈建议增加。

因为一个错误实现可能：

```text
先读 stdout
```

同时：

```text
stderr pipe 满
```

Child 等待 stderr 被消费。

Parent 等 stdout。

最终：

```text
deadlock
```

Python 官方明确警告多个 PIPE 未正确消费可能造成这种阻塞。

所以两个 Stream 要：

```text
concurrently drain
```

---

# 76. 测试 10：非零 Exit Code

例如：

```text
python -c
"raise SystemExit(7)"
```

结果：

```text
status:
NONZERO_EXIT

exit_code:
7

timed_out:
False
```

Runner 本身：

```text
工作正常
```

只是 Command：

```text
失败
```

---

# 77. 测试 11：Process Start Failed

例如不存在 Executable。

预期：

```text
START_FAILED

exit_code=None

error != None
```

而：

```text
Runner 不 Crash Agent
```

---

# 78. 我建议增加测试 12：stdin 不阻塞

子程序：

```text
input()
```

Runner：

```text
stdin=DEVNULL
```

应该：

```text
快速 EOF / 退出
```

而不是：

```text
永远等待用户输入
```

---

# 79. 我建议增加测试 13：Environment Secret Filtering

测试 Parent 设置：

```text
CODETEAM_SECRET_CANARY
=
VERY_SECRET
```

然后 Command 输出：

```text
环境里是否存在它？
```

期望：

```text
False
```

这能非常直接地证明：

```text
Parent Environment
≠
Child Environment
```

---

# 80. 今天的 Design Decision 1：Approval Token 应绑定什么

方案 A：

```text
只绑定 executable
```

例如：

```text
python
```

太宽。

方案 B：

```text
绑定完整 argv
```

非常安全，但复用率低。

方案 C：

```text
ONCE：
完整 Request

TASK：
明确 capability prefix
+ cwd
+ execution profile
```

我推荐 C。

---

# 81. Design Decision 2：Approval Scope

Day 5：

```text
ONCE
TASK
```

暂不实现：

```text
SESSION
PERSISTENT
```

原因：

```text
避免权限生命周期过长
+
适配每 Task Worktree
+
方便后续 Multi-Agent Ownership
```

---

# 82. Design Decision 3：Runner 是否直接暴露给 LLM

方案 A：

```text
LLM
→ CommandRunner
```

方案 B：

```text
LLM
→ SafeExecutor
→ Policy
→ Approval
→ Runner
```

必须选：

```text
B
```

否则：

```text
整个安全架构可被旁路
```

---

# 83. Design Decision 4：Timeout 杀一个 PID 还是 Process Group

方案 A：

```text
proc.kill()
```

方案 B：

```text
Process Group
SIGTERM
→ Grace
→ SIGKILL
```

POSIX V1 推荐：

```text
B
```

因为 Coding Command 很常见：

```text
pytest
npm
make
compiler
```

再启动子 Process。

---

# 84. Design Decision 5：Output Storage

方案 A：

```text
communicate()
→ 收完全部
→ 截断
```

方案 B：

```text
stream
→ bounded capture
→ keep draining
```

必须选择：

```text
B
```

因为 Python 文档明确指出 `communicate()` 会把输出存入内存，不适用于大型或无界输出。

---

# 85. Design Decision 6：Environment

方案 A：

```text
inherit os.environ
```

方案 B：

```text
minimal allowlist
```

推荐：

```text
B
```

因为 Environment 本身可能包含敏感能力。

---

# 86. 今天的 Benchmark 1：Runner Overhead

建立 Baseline：

```text
subprocess.Popen
最小命令
```

和：

```text
SafeCommandRunner
```

比较：

```text
Process Launch P50
Process Launch P95
Total Runtime
```

例如运行：

```text
python -c pass
```

重复：

```text
100 次
```

回答：

> Safe Runner 的安全控制增加多少执行开销？

---

# 87. Benchmark 2：Timeout Termination Latency

配置：

```text
timeout = 200ms
grace = 100ms
```

运行不会自行退出的程序。

记录：

```text
actual duration
```

观察：

```text
P50
P95
```

目标不是编造：

```text
一定 300ms
```

而是测：

```text
实际 termination overhead
```

---

# 88. Benchmark 3：Output Scalability

Workload：

```text
64 KB
1 MB
10 MB
50 MB
```

输出量。

记录：

```text
runtime

captured bytes

total bytes seen

peak memory
```

理想性质：

```text
Output 从 1MB → 50MB

captured memory
不跟着线性增长
```

这才证明：

```text
bounded output capture
```

确实有效。

---

# 89. Benchmark 4：Approval Burden

构造例如：

```text
50 次 pytest
10 次 git status
5 次 git push
```

比较：

```text
全部 One-shot
```

vs

```text
低风险 auto
+
Task-scoped Approval
```

指标：

```text
approval prompts count

approval cache hit rate
```

这个实验能说明：

> Approval Scope 不只是安全设计，也影响 Agent Autonomy 和用户体验。

---

# 90. Ablation 1：取消 Process Group

Full：

```text
kill process group
```

Ablation：

```text
只 proc.kill()
```

运行：

```text
parent
→ child
```

Timeout。

指标：

```text
leaked_process_count
```

如果 Ablation：

```text
parent dead
child alive
```

就直接证明 Process Group 的价值。

---

# 91. Ablation 2：`communicate()` 全量缓存

Full：

```text
streaming bounded capture
```

Ablation：

```text
communicate()
→ capture all
```

运行：

```text
1MB
10MB
50MB
```

比较：

```text
peak memory
```

这个实验非常适合项目展示。

---

# 92. Ablation 3：Approval 只绑定 executable

Full：

```text
task
+
argv/capability
+
cwd
+
profile
```

Ablation：

```text
只 executable
```

测试：

```text
Approve:
python -m pytest

Then request:
python -c arbitrary_code
```

如果 Ablation 错误放行，

就证明：

```text
过宽 Approval Scope
```

的风险。

---

# 93. Ablation 4：继承全部 Environment

Full：

```text
minimal env
```

Ablation：

```text
os.environ.copy()
```

Parent 设置：

```text
SECRET_CANARY
```

Repo command 尝试读取。

指标：

```text
secret exposure
```

这也是一个非常有力的 Agent Security Ablation。

---

# 94. Failure Case 1：Approval Over-generalization

用户批准：

```text
pytest
```

实现错误地变成：

```text
所有 python 自动允许
```

根因：

```text
Grant Scope 过宽
```

改进：

```text
structured capability
+
task
+
resource
```

---

# 95. Failure Case 2：Approval TOCTOU

批准：

```text
Request A
```

实际执行：

```text
Request B
```

改进：

```text
fingerprint
+
execution-time verification
```

---

# 96. Failure Case 3：跨 Task Grant 泄漏

```text
task-001
approval
```

错误被：

```text
task-002
```

复用。

这实际上属于：

```text
Authorization Isolation Failure
```

和 Worktree 的：

```text
Filesystem Isolation
```

是两种不同隔离。

---

# 97. Failure Case 4：SIGTERM 被忽略

表现：

```text
Timeout
→ terminate
→ 进程仍活着
```

改进：

```text
grace
→ SIGKILL
```

---

# 98. Failure Case 5：Grandchild 泄漏

```text
parent killed
child survives
```

原因：

```text
只 kill PID
```

改进：

```text
Process Group
```

---

# 99. Failure Case 6：Child 主动逃离 Process Group

某个程序可以自行：

```text
setsid
```

从你管理的 Process Group 脱离。

所以：

```text
Process Group
```

不是 Sandbox。

未来真正强隔离还需要：

```text
Container
cgroup
namespace
Job Object
OS sandbox
```

---

# 100. Failure Case 7：Output Truncate 导致 Deadlock

错误：

```text
达到 64KB
→ stop reading
```

结果：

```text
pipe fills
→ child blocks
→ Runner hangs
```

正确：

```text
stop storing
≠
stop draining
```

---

# 101. Failure Case 8：UTF-8 截断

例如：

```text
"...中文..."
```

恰好在多字节字符中间截断。

如果直接：

```text
string slicing
```

可能出现问题。

更合理：

```text
bytes
→ bounded storage
→ decode(errors="replace")
```

---

# 102. Failure Case 9：Secret 被写进 Audit Log

即使 Environment 没传给 Child，

如果 Approval Audit 保存：

```text
完整 argv
```

仍可能泄漏：

```text
token
password
credentials
```

所以：

```text
Execution Log
```

也必须执行 Redaction。

---

# 103. Failure Case 10：PATH Hijacking

Runner 认为：

```text
git
```

是系统 Git。

实际：

```text
workspace/bin/git
```

被执行。

改进：

```text
controlled PATH
+
trusted executable resolution
```

---

# 104. Failure Case 11：Timeout 与 Spawn

前面已经提到，Python 官方说明 Process Creation 本身在某些平台上不能被 timeout 立刻中断。

所以你的指标和文档必须明确：

```text
execution timeout
```

从什么时候开始计算。

---

# 105. Failure Case 12：Approval Log 与 Execution Log 无法对应

如果：

```text
approval
```

和：

```text
command.started
```

没有共同：

```text
approval_id
command_fingerprint
task_id
```

以后出了事故你只能看到：

```text
用户批准过一条命令
```

却不知道：

```text
实际执行的是不是那条。
```

因此两套 Event 必须关联。

---

# 106. 今天推荐的 Event Schema

例如：

```text
policy.evaluated

approval.requested
approval.approved
approval.denied
approval.consumed

command.started
command.completed
command.start_failed

command.timed_out
command.sigterm_sent
command.sigkill_sent

command.stdout_truncated
command.stderr_truncated
```

这些以后直接成为：

```text
Agent Trace
```

的一部分。

---

# 107. OpenAI 的一个更高级工业方向：Auto-review

OpenAI Codex 当前还公开了 Auto-review：符合条件的 Sandbox Boundary Escalation 可以由独立 Reviewer Agent 处理，而主 Agent 仍处于相同 Sandbox、Approval Policy、Filesystem 和 Network 边界下。

这对你未来 Multi-Agent 很有启发：

```text
Worker
→ Approval Request
→ Reviewer Agent
→ decision
```

但 Day 5 暂时不要实现。

现在仍应该：

```text
Human Approval
```

作为可信根。

---

# 108. 今天推荐拆成 8 个 Step

| Step | 内容 |
|---|---|
| 1 | ApprovalScope / Request / Decision |
| 2 | Fingerprint + ApprovalGrant |
| 3 | ApprovalManager |
| 4 | Audit Events |
| 5 | CommandLimits / CommandResult |
| 6 | OutputLimiter |
| 7 | Process Group + Timeout Runner |
| 8 | SafeExecutor Integration |

---

# 109. 今天真正完成需要多少测试？

用户要求的最低测试：

```text
用户拒绝
用户批准一次
批准不跨 Task
超时
巨大 stdout
巨大 stderr
非零退出码
启动失败
子进程终止
```

我建议 Day 5 最终做到大约：

```text
20～30 个测试
```

另外覆盖：

```text
one-shot consumption
task grant reuse
fingerprint mismatch
DENY 不可审批
stdout + stderr 并发
SIGTERM ignored
secret environment
stdin EOF
approval audit
output truncation metadata
```

---

# 110. 今日最终验收应该写成三个强不变量

## Invariant 1：Authorization

```text
Policy = DENY
或
Approval = DENIED

→

CommandRunner invocation count
必须 = 0
```

---

## Invariant 2：Termination

```text
Command 超过 Deadline

→
SIGTERM

→ grace

→ 必要时 SIGKILL

→
受控 Process Group 最终不再运行
```

---

## Invariant 3：Bounded Output

```text
Child 输出任意大

→
Runner 仍持续 drain

→
内存只保留 bounded output

→
CommandResult.truncated = True
```

---

# 111. 今天必须能够回答的 Interview Questions

### Approval

1. Approval 和 Policy 有什么区别？
2. One-shot Approval 怎么保证只能使用一次？
3. 为什么 Approval 不能只绑定 executable？
4. Task Approval 为什么不是“整个 Task 全部允许”？
5. 怎么防止 Approval TOCTOU？
6. 为什么 DENY 不能被用户普通 Approval 提升？
7. Approval Audit 需要记录什么？
8. 为什么 Audit Log 也可能泄露 Secret？

### Runner

9. `subprocess.run(timeout=...)` 为什么还不够？
10. 为什么要区分 SIGTERM 与 SIGKILL？
11. 为什么不能只杀 Parent PID？
12. Process Group 解决什么问题？
13. Process Group 为什么仍然不是 Sandbox？
14. 为什么 stdout 达到 Limit 后仍然必须继续读取？
15. 为什么 `communicate()` 不适合无限输出？
16. 为什么 stdout/stderr 要同时读取？
17. 为什么默认关闭 stdin？
18. 为什么 Non-zero Exit 不等于 Runner Failure？
19. Environment Variables 为什么属于 Agent Security？
20. 为什么 Runtime 应控制 PATH？

---

# 112. 面试官如果问：“这不就是 subprocess 加 timeout 吗？”

你应该能够解释：

> 我把 Command Execution 设计成了 Agent Runtime 的受控副作用管线，而不是直接封装 `subprocess.run`。高风险命令先经过 Policy 和 task-scoped Approval，Approval 与具体 CommandRequest 指纹绑定，避免跨 Task 复用和 TOCTOU。执行阶段在 POSIX 下为任务命令创建独立 Process Group；Timeout 后先发送 SIGTERM，超过 Grace Period 再 SIGKILL 整个受控进程组。stdout/stderr 持续 Drain，但只保留有界的 Head/Tail Buffer，避免无限输出造成 OOM 或 Pipe Deadlock。同时 Child 使用最小 Environment，避免默认继承 Host Credentials。所有 Approval、Timeout、Kill 和 Truncation 都生成结构化 Audit Event。

这样体现的是：

```text
Human-in-the-loop
+
Process Supervision
+
Resource Bounding
+
Secret Isolation
+
Observability
```

而不是：

```text
会使用 subprocess
```

---

# 113. Day 5 的 Benchmark / Ablation / Failure 闭环

今天真正结束时，应该形成：

```text
Theory
├── Approval Scope
├── Process Group
├── Timeout
├── Signals
├── Output Limit
└── Environment Isolation

Industrial Design
├── OpenAI Codex
├── GitHub Copilot
└── Claude Code

Implementation
├── ApprovalRequest
├── ApprovalDecision
├── ApprovalManager
├── CommandLimits
├── CommandResult
├── OutputLimiter
├── CommandRunner
└── SafeExecutor

Tests
├── Approval
├── Timeout
├── Output
├── Exit
└── Child cleanup

Design Decisions
├── Once / Task scope
├── Request fingerprint
├── Process-group termination
├── Streaming bounded output
└── Minimal environment

Benchmark
├── Runner overhead
├── Termination latency
├── Output scalability
└── Approval burden

Ablation
├── no process group
├── communicate full capture
├── executable-only approval
└── inherited environment

Failure Cases
├── TOCTOU
├── cross-task leakage
├── orphan process
├── SIGTERM ignored
├── pipe deadlock
├── secret leakage
└── PATH hijack
```

完成 Day 5 后，你的第三周架构就已经基本连成：

```text
CommandRequest
      │
      ▼
CommandPolicy             Day 4
      │
      ▼
ApprovalManager           Day 5
      │
      ▼
Sandbox                   Day 6
      │
      ▼
CommandRunner             Day 5
      │
      ▼
Task Worktree             Day 2
      │
      ▼
Checkpoint / Rollback     Day 3
```

这五天实际上正在共同构造一个完整的 **Agent Tool Runtime / Safe Execution Harness**，而不是五组独立 Git 或 subprocess 工具。

**0. 只读检查结论**

我已只读检查当前仓库，没有修改代码。你给的路径 `/Users/workspace/...` 不存在；当前真实根目录是 `/Users/workplace/Agent-Learning`。

当前 Git 状态显示：

```text
?? learning-plan/week3/day5.md
```

也就是说 Day5 文档目前是未跟踪文件，但可以作为只读学习依据。当前仓库已经有 Day4 的 `codeteam/execution/command_policy.py`、`models.py`、`policy_rules.py` 和 `tests/execution/test_command_policy.py`。

**1. Today in the System**

今天解决的是：

```text
CommandPolicy 判断风险以后，
Runtime 如何请求用户授权，
并在授权后安全、可控、可终止地执行命令？
```

位置：

```text
LLM / Worker Agent
 ↓
CommandRequest
 ↓
CommandPolicy
 ↓
ALLOW / ALLOW_SANDBOXED / REQUIRE_APPROVAL / DENY
 ↓
ApprovalManager
 ↓
SafeCommandExecutor
 ↓
CommandRunner
 ↓
CommandResult
```

今天不是“会用 subprocess”这么简单，而是做 Agent Tool Runtime 的授权门禁和进程监督。

**2. Capability Mapping**

Primary:

```text
Tool Runtime
Workspace & Sandbox
Agent Runtime Safety
```

Secondary:

```text
Observability
Human-in-the-loop
Evaluation
Failure Analysis
```

它最终证明：你知道 Coding Agent 不能直接运行模型提出的命令，必须有风险判断、用户授权、执行限制、超时清理、输出控制和审计证据。

**3. Theory**

今天必须理解：

```text
PolicyDecision
= 机器判断命令风险。

ApprovalDecision
= 用户是否授权。

ApprovalScope
= 授权范围，例如 ONCE / TASK。

ApprovalGrant
= 已批准的权限凭证。

CommandRunner
= 进程监督器，不是安全策略判断器。

OutputLimiter
= 持续 drain 输出，但只保存 head + tail。

CommandResult
= 结构化执行结果，不只是 exit code。
```

最重要边界：

```text
Approval 不能代替 Sandbox。
Sandbox 不能代替 Approval。
Runner 不能绕过 Policy + Approval。
DENY 不能被用户 approval 提升执行。
```

**4. Industrial Design**

Day5 文档给出的工业方向是：现代 Coding Agent 通常把权限系统拆成 sandbox capability 与 approval policy 两层；审批还会区分一次、本 session、本位置或长期权限。

可稳定参考的官方基础资料：

- Python `subprocess` 明确说明 `communicate(timeout=...)` 超时后不会自动杀掉进程，调用方需要清理：[Python subprocess](https://docs.python.org/3/library/subprocess.html)
- Python `signal` 说明 `SIGTERM`、`SIGKILL` 等信号语义：[Python signal](https://docs.python.org/3/library/signal.html)
- Claude Code 权限/设置需要实现前再核对官方文档：[Claude Code docs](https://docs.anthropic.com/en/docs/claude-code)

工程推断：CodeTeam 第一版应采用保守设计：

```text
ApprovalManager 只处理授权。
CommandRunner 只处理执行。
SafeCommandExecutor 串联 Policy → Approval → Runner。
```

**5. 当前仓库检查**

已有：

```text
codeteam/execution/models.py
- CommandRequest
- PolicyDecision
- RiskCategory
- RuleResult
- PolicyEvaluation

codeteam/execution/command_policy.py
- CommandPolicy.default()
- evaluate(request)

codeteam/execution/policy_rules.py
- CwdWorkspaceRule
- GitDestructiveRule
- ShellInterpreterRule
- NetworkCommandRule
- RemoteWriteRule
- DockerPrivilegeRule
- SafeDevCommandRule
- SafeGitReadRule

tests/execution/test_command_policy.py
- 82 个 Day4 policy 测试
```

缺失：

```text
ApprovalManager
ApprovalRequest / ApprovalGrant
Approval audit log
CommandRunner
CommandLimits / CommandResult
OutputLimiter
SafeCommandExecutor
tests for approval + runner
```

已有 `codeteam/tools/shell.py` 是旧的 shell tool runner，但它和 Day5 的 execution runtime 不是同一层，不能直接当最终 Safe CommandRunner。

**6. 涉及文件**

可能新增：

```text
codeteam/execution/approval.py
→ ApprovalManager、grant 检查、one-shot consume

codeteam/execution/runner.py
→ Safe CommandRunner / process lifecycle

codeteam/execution/output_limiter.py
→ head + tail bytes limiter

codeteam/execution/executor.py
→ Policy + Approval + Runner 编排

tests/execution/test_approval.py
tests/execution/test_runner.py
tests/execution/test_safe_executor.py
```

可能修改：

```text
codeteam/execution/models.py
→ ApprovalScope、ApprovalDecision、ApprovalRequest、ApprovalGrant、CommandLimits、CommandResult

codeteam/execution/__init__.py
→ 导出公共 API
```

**7. Architecture / Data Flow**

```text
CommandRequest
 ↓
CommandPolicy.evaluate()
 ↓
DENY
 → CommandResult / ExecutionResult rejected, runner 不被调用

ALLOW / ALLOW_SANDBOXED
 ↓
SafeCommandExecutor
 ↓
CommandRunner.run()

REQUIRE_APPROVAL
 ↓
ApprovalManager.create_request()
 ↓
user decision
 ↓
APPROVED?
 ↓
verify fingerprint
 ↓
consume ONCE grant / validate TASK grant
 ↓
CommandRunner.run()
```

Runner 内部：

```text
Popen(shell=False, stdin=DEVNULL, env=allowlist, start_new_session=True)
 ↓
read stdout/stderr
 ↓
OutputLimiter drains all, stores bounded head+tail
 ↓
timeout?
 ↓
SIGTERM process group
 ↓
grace period
 ↓
SIGKILL process group
 ↓
CommandResult
```

**8. 今日步骤拆分**

Step 1：扩展 execution models  
目标：定义 Approval / Runner 的状态语言。完成标志：模型能表达 approval request、grant、limits、result。

Step 2：实现 fingerprint  
目标：防止 TOCTOU。完成标志：同一请求 fingerprint 稳定，argv/cwd/profile 变化 fingerprint 变化。

Step 3：实现 ApprovalManager  
目标：支持 ONCE / TASK grant。完成标志：one-shot 只能消费一次，TASK 不等于 allow everything。

Step 4：实现 OutputLimiter  
目标：限制 stdout/stderr 保存量但继续 drain。完成标志：大输出不会撑爆内存，保留 head + tail。

Step 5：实现 CommandRunner  
目标：执行命令、环境 allowlist、timeout、结构化结果。完成标志：success/nonzero/start_failed/timed_out 都可区分。

Step 6：实现 SafeCommandExecutor  
目标：串联 policy、approval、runner。完成标志：DENY 和用户拒绝时 runner 调用次数为 0。

Step 7：补测试与证据  
目标：覆盖安全、超时、输出、approval、audit、runner 不绕过 policy。

**9. Test Strategy**

Approval 测试：

```text
REQUIRE_APPROVAL 创建 ApprovalRequest
ONCE grant 第一次有效，第二次无效
fingerprint 不匹配拒绝
TASK grant 只允许同类 capability
DENY 不能进入 approval 提权
用户拒绝时 runner 不调用
```

Runner 测试：

```text
echo success
exit 1 nonzero
不存在命令 START_FAILED
timeout 命令 TIMED_OUT
stdout/stderr 截断
stdin 不阻塞
env 不泄露 secret
cwd 必须在 workspace
```

Executor 测试：

```text
ALLOW 直接执行
ALLOW_SANDBOXED 进入 runner，并记录 sandbox intent
REQUIRE_APPROVAL approved 后执行
REQUIRE_APPROVAL denied 不执行
DENY 不执行
```

**10. Design Decision Plan**

需要形成至少三项 Decision：

```text
DD-Day5-01: Approval Scope 第一版只支持 ONCE / TASK
DD-Day5-02: Runner 使用 process group + SIGTERM/SIGKILL 处理 timeout
DD-Day5-03: Output capture 使用 head + tail，而不是完整 communicate 后截断
```

每项都要比较替代方案：

```text
yes/no approval vs scoped grant
proc.kill only vs process group kill
full output vs first-N vs head+tail
inherit env vs allowlist env
```

**11. Benchmark Plan**

问题：

```text
CommandPolicy + Approval + Runner 的 overhead 是否可接受？
OutputLimiter 是否能处理大输出？
Timeout cleanup 是否稳定？
```

指标：

```text
approval check latency
runner startup latency
timeout cleanup latency
captured bytes vs total bytes
memory growth
large-output duration
```

Baseline：

```text
subprocess.run(..., capture_output=True)
```

System under test：

```text
SafeCommandExecutor + CommandRunner + OutputLimiter
```

**12. Ablation Plan**

Ablation 1：去掉 ApprovalManager  
比较高风险命令是否能绕过用户授权。

Ablation 2：去掉 fingerprint  
比较 request 被修改后是否仍能复用旧 approval。

Ablation 3：去掉 process group cleanup  
比较 timeout 后子进程是否残留。

Ablation 4：去掉 OutputLimiter  
比较大输出下内存和返回结果大小。

**13. Failure Cases to Watch**

```text
TOCTOU Approval Reuse
批准 git push 后实际执行 git push --force。

One-shot Double Spend
并发下一次授权被执行两次。

Approval Escalates DENY
DENY 命令被用户 approval 误执行。

Output OOM
命令输出过大，Runner 先读进内存再截断。

Pipe Deadlock
达到 limit 后不继续读 pipe，子进程阻塞。

Process Leak
timeout 只 kill parent，child 继续运行。

Secret Leak
env 或 audit log 保存 API key / SSH_AUTH_SOCK。

PATH Hijack
workspace 中伪造 git/python 被执行。

Interactive Hang
命令等待 stdin，永不退出。
```

**14. Interview Focus**

你要能回答：

```text
为什么 CommandPolicy 后还要 Approval？
为什么 Approval 不能只有 boolean？
为什么 DENY 不能被用户 approval 推翻？
为什么 one-shot grant 要消费？
为什么 fingerprint 不包含 reason？
为什么 Runner 不是 Sandbox？
为什么 timeout 后不能只 proc.kill？
为什么 communicate 后再截断不够安全？
为什么 env 默认不能继承 os.environ？
为什么 exit 1 不是 Runner exception？
```

**15. 今日最终完成标准**

今天完整完成时应达到：

```text
1. ApprovalScope / ApprovalRequest / ApprovalGrant / ApprovalDecision 存在。
2. CommandRequest fingerprint 稳定且可测试。
3. ApprovalManager 支持 ONCE 和 TASK。
4. ONCE grant 原子消费，不能复用。
5. DENY 命令无法通过 approval 执行。
6. CommandRunner 返回结构化 CommandResult。
7. Runner 支持 timeout、grace、kill、output limit、env allowlist、stdin DEVNULL。
8. SafeCommandExecutor 串联 Policy → Approval → Runner。
9. 用户拒绝和 policy deny 时 runner 调用次数为 0。
10. tests/execution 新增 approval / runner / executor 测试。
11. 有 Design Decision / Benchmark / Ablation / Failure Case 计划。
```

今天这个模块最终证明的是：你能把 Coding Agent 的命令执行从“风险分类”推进到“授权后可控执行”，这是 Agent Tool Runtime 进入生产级安全边界前的关键一层。