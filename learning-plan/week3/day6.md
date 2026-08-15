# 第 3 周 Day 6：Docker Sandbox

今天是第三周安全执行链中非常关键的一天。前面几天你已经逐渐把“LLM 想执行一个命令”变成了一个受控流程：

```text
Day 4
CommandPolicy
→ 这件事应该做吗？

Day 5
ApprovalManager
→ 高风险操作用户是否同意？

Day 5
CommandRunner
→ 怎么限时、限输出、清理进程？

Day 6
Docker Sandbox
→ 即使程序本身恶意，它实际上最多能做什么？
```

完整架构开始变成：

```text
Worker / LLM
    │
    ▼
CommandRequest
    │
    ▼
CommandPolicy
    │
    ├── DENY ──────────────→ STOP
    │
    ├── REQUIRE_APPROVAL
    │          │
    │          ▼
    │    ApprovalManager
    │          │
    │          ▼
    └──── approved
               │
               ▼
        SandboxProfile
               │
               ▼
      DockerCommandBuilder
               │
               ▼
          DockerRunner
               │
               ▼
       Docker Container
               │
         ┌─────┼───────┐
         │     │       │
       FS    Network  cgroup
         │     │       │
         ▼     ▼       ▼
      bounded capabilities
               │
               ▼
          Task Worktree
```

今天最重要的一句话是：

> **Policy 决定“应该做什么”，Approval 决定“用户允许什么”，Sandbox 决定“技术上最多能做什么”。**

这三个必须同时存在。

---

# 1. Capability Mapping：Day 6 到底证明什么能力

今天主要覆盖：

```text
Workspace & Sandbox
├── Filesystem Isolation
├── Network Isolation
├── Resource Isolation
├── Capability Restriction
└── Container Lifecycle

Tool Runtime
├── Sandbox Profile
├── Execution Backend
└── Security Boundary

Agent Runtime
├── Task-scoped Environment
├── Safe Side Effects
└── Failure Containment

Evaluation
├── Escape Tests
├── Resource Limit Tests
└── Security Ablation
```

所以今天绝对不是：

```text
学几个 docker run 参数
```

真正要学习的是：

> **如何把一个潜在不可信的 Coding Agent Command 放到最小权限执行环境中。**

---

# 2. 为什么 Day 4 的 CommandPolicy 仍然不够

假设昨天的 Policy 判断：

```text
python -m pytest
→ ALLOW_SANDBOXED
```

Policy 的判断可能完全正确：

```text
用户确实想跑测试
```

但 Repository 中的测试可能包含：

```python
from pathlib import Path

Path.home().joinpath(
    ".ssh/id_rsa"
).read_text()
```

或者：

```python
import socket

socket.create_connection(...)
```

甚至：

```python
import subprocess

subprocess.run(...)
```

Policy 看到的只是：

```text
python -m pytest
```

它无法可靠推断测试代码内部最终会做什么。

因此：

```text
CommandPolicy
=
Intent-level control
```

而：

```text
Sandbox
=
Capability-level control
```

OpenAI 当前 Codex 的公开设计也是这种分层：Sandbox 定义文件和网络等技术边界，Approval Policy 决定什么时候需要停下来征求授权；由 Agent 启动的 `git`、包管理器、测试程序等子进程同样受 Sandbox 边界约束。([OpenAI Developers][1])

---

# 3. Sandbox 最核心的思维方式

你可以把 Sandbox 想象成：

```text
Agent 想做：

read()
write()
connect()
fork()
mount()
ptrace()
consume memory
consume CPU
```

Sandbox 不去问：

```text
“你的意图是不是善良？”
```

而是直接规定：

```text
你只能：

read /workspace
write /workspace

不能：

read arbitrary host files

不能：
访问公网

不能：
获得新的 privilege

不能：
无限 fork

不能：
无限使用 RAM / CPU
```

也就是说：

> **模型判断可以犯错，但 Sandbox 的权限边界仍然存在。**

---

# 4. 先理解 Docker：Image 和 Container

## Image

Docker 官方把 Image 定义为一个标准化软件包，其中包含运行 Container 所需的文件、二进制程序、库和配置。([Docker Documentation][2])

例如：

```text
codeteam-sandbox image

包含：

Python 3.12
git
ripgrep
pytest
ruff
mypy
必要系统库
```

它更接近：

```text
执行环境模板
```

而不是：

```text
一个正在运行的程序
```

---

# 5. Container

Container 是：

```text
Image
+
runtime configuration
+
isolated process
```

Docker 官方把 Container 描述为 Image 的可运行实例；Container 本质上是一组隔离的进程，而不像 VM 那样拥有完整独立 Kernel。多个 Linux Container 通常仍共享 Host 的 Kernel。([Docker Documentation][3])

因此：

```text
Image
≈ 模板

Container
≈ 从模板启动的一次执行实例
```

例如：

```text
codeteam-sandbox:python312
```

可以同时产生：

```text
container-task-001-run-1
container-task-002-run-1
container-task-003-run-4
```

---

# 6. Docker Container 为什么能隔离

在 Linux 上，Docker 使用 Kernel Namespace 等机制隔离：

```text
process
network
mount
IPC
...
```

并使用 cgroup 等机制控制资源。Docker 官方说明，启动 Container 时会创建 Namespace 和 Control Group，为进程提供隔离和资源控制。([Docker Documentation][4])

可以粗略理解：

```text
Namespace
=
“你能看到什么？”


cgroup
=
“你能用多少？”
```

这是一个非常好的记忆方法。

---

# 7. Namespace 和 Sandbox 的关系

例如：

```text
PID Namespace
```

让 Container 看到自己的进程世界。

```text
Mount Namespace
```

让 Container 看到自己的 Filesystem View。

```text
Network Namespace
```

让 Container 拥有独立 Network Stack。

而：

```text
User Namespace
```

可以让 Container 内部的 UID 与 Host UID 做映射。

Docker 官方明确说明 Namespace 是 Container 隔离的重要基础。([Docker Documentation][5])

---

# 8. Docker Sandbox 并不是 VM

这个面试非常容易被问。

VM：

```text
Guest Kernel
Guest OS
Applications
```

Container：

```text
Host Kernel

├── Container A processes
├── Container B processes
└── Host processes
```

Docker 官方明确指出 Container 和 VM 的关键区别之一就是 Container 通常共享 Kernel。([Docker Documentation][3])

因此：

> Docker 是非常有价值的隔离层，但不能把“Container”理解成绝对安全边界。

这也是为什么后面还要：

```text
Rootless
Capabilities
Seccomp
AppArmor / SELinux
no-new-privileges
```

继续做 Defense in Depth。Docker 默认也会使用 Capability 限制和 Seccomp 等机制。([Docker Documentation][4])

---

# 9. Mount 是今天第一大核心

你的 Coding Agent 最终必须能：

```text
读取代码
修改代码
跑测试
```

所以 Container 一定要看到：

```text
Task Worktree
```

最直接的方法就是：

```text
Bind Mount
```

Docker Bind Mount 会把指定 Host Path 直接暴露到 Container 中；如果 Bind Mount 是 Read-write，那么 Container 对它的修改会直接反映到 Host。Docker 官方明确提醒，Bind Mount 默认具有 Host 文件写权限，因此错误的 Mount 会带来明显安全风险。([Docker Documentation][6])

---

# 10. Worktree 是我们唯一应该默认暴露的 Host State

假设：

```text
Main Worktree:

/Users/user/project


Task-001 Worktree:

/tmp/codeteam/repo123/task-001
```

Sandbox 不应该：

```text
mount /Users/user
mount /
mount project main worktree
```

而只：

```text
Host:

/tmp/codeteam/repo123/task-001

        ↓ bind mount

Container:

/workspace
```

因此：

```text
Container
只能直接接触
task-001
```

而不是：

```text
整个用户机器
```

---

# 11. `--mount` 为什么比 `-v` 更适合 Agent Runtime

Docker 同时支持：

```text
-v
```

和：

```text
--mount
```

Docker 官方目前推荐 `--mount`，因为语义更显式；还有一个对 Runtime 很重要的区别：如果 Host Source Path 不存在，`-v` 可能自动创建目录，而 `--mount type=bind` 默认会直接报错。([Docker Documentation][6])

这非常适合 Agent Runtime。

假设 WorktreeManager Bug 了：

```text
workspace=
/tmp/codeteam/task-001-typo
```

使用：

```text
-v
```

可能：

```text
Docker 自动创建一个空目录
→ Agent 在错误 Workspace 中工作
```

而：

```text
--mount
```

会：

```text
Fail Closed
```

所以我建议 CodeTeam：

```text
始终使用 --mount
```

---

# 12. `--read-only` 到底限制什么

执行：

```text
--read-only
```

意味着：

> Container Root Filesystem 被挂载为 Read-only。

Docker 官方说明，在这种模式下 Container 不能写 Root Filesystem，除非某个路径被额外挂载为可写 Volume / Bind Mount。([Docker Documentation][7])

这恰好符合 Coding Agent：

```text
/
├── usr       RO
├── bin       RO
├── etc       RO
├── lib       RO
├── ...
└── workspace RW
```

因此：

```text
Agent 可以修改项目代码

但不能：

apt install
修改 /etc
覆盖 /usr/bin/python
写系统目录
```

---

# 13. Read-only Root + Writable Worktree

这两个配置并不冲突。

你可以：

```text
--read-only

+
--mount
type=bind,
src=<task-worktree>,
dst=/workspace
```

并让：

```text
/workspace
```

保持 `rw`。

Docker 官方就是这样描述 `--read-only` 的：Root FS 可以是只读，同时通过 Volume 或 Mount 指定少量可写位置。([Docker Documentation][7])

最终：

```text
Root FS
RO

Task Worktree
RW
```

这正是我们要的：

> **Default Deny Write + Explicit Writable Root**

---

# 14. 但是 Read-only Root 会带来一个真实 Failure Case

很多程序会尝试写：

```text
/tmp
/home/user/.cache
~/.cache
```

例如：

```text
compiler temporary files
pytest cache
package cache
```

如果 Root FS：

```text
read-only
```

它们可能失败。

因此 Sandbox 往往需要：

```text
small tmpfs
```

Docker 支持把 `tmpfs` 挂载到 Container 中，内容存在于内存且随 Container 消失。([Docker Documentation][8])

例如未来可以考虑：

```text
/tmp
→ writable tmpfs
```

而不是：

```text
把整个 Root FS 改回 RW
```

---

# 15. 所以理想 Filesystem Layout

建议：

```text
Container

/
RO

/workspace
RW
→ Task Worktree

/tmp
RW
→ tmpfs

其他 Host Paths
NOT MOUNTED
```

以后需要 Cache 时，可以再非常谨慎地增加：

```text
/cache
```

但不要第一版就：

```text
mount ~/.cache
mount ~/.npm
mount ~/.m2
```

这些共享目录会重新引入 Cross-task State 和 Host Exposure。

---

# 16. Network Namespace 是什么

每个 Container 可以拥有自己的 Network Namespace：

```text
network interfaces
routing table
ports
```

如果不指定网络，Docker Container 通常会接入默认 Bridge Network；Docker 官方也指出，没有指定 `--network` 时 Container 通常连接默认 Bridge。([Docker Documentation][9])

这意味着默认 Container：

```text
通常具有网络能力
```

这不符合 Agent Sandbox 的：

```text
Default Deny Network
```

---

# 17. `--network none`

Docker 官方定义：

```text
--network none
```

会让 Container 的 Network Stack 与其他 Container 和 Host Network 隔离，只保留 Loopback Device。([Docker Documentation][10])

因此：

```text
eth0
×
default route
×

lo
✓
```

结果：

```text
curl internet
→ fail

pip install from internet
→ fail

git fetch
→ fail
```

而：

```text
localhost inside same container
```

仍然存在。

---

# 18. 为什么 Agent Sandbox 默认应该 `network none`

网络不仅意味着：

```text
下载依赖
```

还意味着：

```text
Data Exfiltration

Prompt Injection Payload Download

Supply-chain Download

Remote Side Effect

Command & Control
```

OpenAI 当前 Codex 的默认 `workspace-write` Sandbox 同样把网络关闭，需要访问网络时通过配置/Approval 提升。([OpenAI Developers][11])

所以：

```python
network_enabled: bool = False
```

是非常合理的安全默认值。

---

# 19. 但这里有一个非常重要的坑：`--network none` 不等于“整个 Docker 调用不会联网”

假设：

```text
docker run my-image ...
```

而：

```text
my-image
```

本地不存在。

Docker `run` 默认 Pull Policy 是：

```text
missing
```

也就是 Image 不存在时 Docker CLI/Daemon 可以尝试 Pull。Docker 官方支持 `--pull=never` 来禁止运行时隐式拉取。([Docker Documentation][12])

所以：

```text
Container:
--network none
```

只约束：

```text
Container 进程
```

并不等于：

```text
Docker Daemon 本身绝不会访问 Registry
```

这是非常值得在面试中讲的 Boundary Failure。

---

# 20. 因此 CodeTeam 建议

Runtime Sandbox：

```text
使用预构建 Image
+
固定 Image Digest
+
--pull=never
```

例如概念上：

```text
codeteam-sandbox@sha256:...
```

而不是：

```text
python:latest
```

然后临时发现没有 Image：

```text
→ FAIL
```

不要：

```text
→ 自动联网下载
```

这是我们项目自己的 Hardening Decision，不是 Docker 强制要求；依据是 Docker 的默认 Pull 行为。([Docker Documentation][12])

---

# 21. Linux Capability 是什么

传统 Unix 大致是：

```text
root
拥有大量特殊权限
```

Linux 把很多 Root 权限拆成：

```text
Capabilities
```

例如：

```text
CAP_SYS_ADMIN
CAP_NET_ADMIN
CAP_SYS_PTRACE
...
```

Docker 默认已经丢弃许多危险 Capability；Docker 官方安全建议进一步指出，最佳实践是移除所有不需要的 Capability，只显式保留真正需要的。([Docker Documentation][4])

---

# 22. `--cap-drop ALL`

Coding Agent 跑：

```text
python
pytest
git
rg
ruff
mypy
```

绝大多数普通用户态行为根本不需要 Kernel Administrative Capability。

因此：

```text
--cap-drop ALL
```

非常符合：

```text
Least Privilege
```

你的：

```python
drop_all_capabilities: bool = True
```

应该映射成：

```text
--cap-drop ALL
```

Docker CLI 当前支持 `--cap-drop` 来移除 Linux Capabilities。([Docker Documentation][7])

---

# 23. `--privileged` 为什么绝对不能出现

Docker 官方对：

```text
--privileged
```

的描述非常明确：它会赋予全部 Linux Capabilities、访问 Host Devices，并关闭或放松多项默认安全机制，包括默认 Seccomp/AppArmor 等；Docker 明确警告 Privileged Container 不是安全 Sandbox。([Docker Documentation][7])

因此在 CodeTeam 中：

```text
--privileged
```

不是：

```text
REQUIRE_APPROVAL
```

而应该是：

```text
UNREPRESENTABLE
```

也就是说：

> **DockerCommandBuilder 的 API 根本不应该提供 privileged=True。**

这是比运行时：

```python
if privileged:
    reject()
```

更好的设计。

---

# 24. 这叫“Safe by Construction”

错误 API：

```python
builder.build(
    extra_args=[
        "--privileged",
        "--pid=host",
        ...
    ]
)
```

然后再：

```text
检查有没有危险参数
```

更好的 API：

```python
builder.build(
    profile=profile,
    workspace=trusted_workspace,
    request=request,
)
```

Builder 自己只会产生一组经过设计的参数。

也就是说：

```text
危险能力
在类型/API 层不存在
```

而不是：

```text
先让 LLM 表达
再过滤
```

---

# 25. `no-new-privileges`

Docker 支持：

```text
--security-opt no-new-privileges=true
```

它会阻止 Container 中的进程通过类似 setuid / `sudo` / `su` 等方式获得新的 Privilege。([Docker Documentation][7])

你的：

```python
no_new_privileges: bool = True
```

应该映射到这个 Flag。

注意它并不意味着：

```text
当前权限全部消失
```

它只是：

```text
不能获得“新的”Privilege
```

所以仍然要结合：

```text
cap-drop
non-root user
seccomp
read-only root
```

使用。

---

# 26. Seccomp 也已经在帮你

Docker 默认会使用 Seccomp Profile 限制一批 System Call；Docker 官方把 Seccomp 明确定位为 Least Privilege 的重要组成，并不建议随意把默认 Profile 改成 `unconfined`。([Docker Documentation][13])

所以 CodeTeam 第一版应该：

```text
保持 Docker Default Seccomp
```

不要：

```text
--security-opt seccomp=unconfined
```

这和：

```text
不使用 --privileged
```

一起形成 Defense in Depth。

---

# 27. CPU / Memory 为什么必须主动限制

你的任务说明里的这句话非常重要：

> Docker 默认不会自动给 Container 设置 CPU / Memory 上限。

Docker 当前官方文档明确说明：默认 Container 没有资源限制，可以使用 Host Kernel Scheduler 允许的资源；CPU 和 Memory Limit 都需要显式配置。([Docker Documentation][14])

这意味着：

```text
Container
≠
自动资源安全
```

如果 Coding Agent 运行：

```text
buggy compiler
infinite allocation
forking script
```

不设 Limit 仍然可能严重影响 Host。

---

# 28. `--memory`

你的：

```python
memory_mb: int = 2048
```

映射：

```text
--memory 2048m
```

Docker 文档中 `--memory` 是 Container Memory Hard Limit。([Docker Documentation][14])

例如：

```text
memory_mb=2048
```

意味着：

```text
Container 最多约 2 GiB RAM
```

达到限制时，后续行为由 Kernel / OOM 机制处理。

---

# 29. 一个更严格的 Memory 细节：Swap

如果只：

```text
--memory 2048m
```

而没有设置：

```text
--memory-swap
```

Docker 可能允许额外使用 Swap。

Docker 官方说明，当 `--memory-swap` 与 `--memory` 设置为相同值时，可禁止额外 Swap 使用。([Docker Documentation][14])

因此一个更严格的 CodeTeam Profile 可以产生：

```text
--memory 2048m
--memory-swap 2048m
```

这属于推荐 Hardening，不是你今天模型中必须新增字段。

---

# 30. `--cpus`

```python
cpus: float = 2.0
```

映射：

```text
--cpus 2.0
```

Docker 官方说明 `--cpus` 是 CFS CPU Quota 的便捷配置；它限制 Container 可以使用的 CPU 额度，并不是“独占两颗 CPU”。([Docker Documentation][14])

所以：

```text
cpus=2
```

不要理解成：

```text
给 Container 专门分配两颗独占 CPU
```

更接近：

```text
CPU consumption ceiling
```

---

# 31. `--pids-limit`

这个特别适合防：

```text
Fork Bomb
```

或者 Bug：

```text
不停创建 Process
```

Docker 支持：

```text
--pids-limit
```

限制 Container 的 PID 数量。([Docker Documentation][7])

你的：

```python
pids_limit: int = 256
```

意味着：

```text
Container 中进程/线程任务数量受到 cgroup PIDs 控制
```

---

# 32. 为什么 PIDs Limit 很重要

只设置：

```text
CPU = 2
Memory = 2 GB
```

仍然可能：

```text
spawn 10000 processes
```

即使每个进程只消耗很少 CPU/RAM，

仍然可能耗尽：

```text
PID
scheduler
file descriptors
```

等 Host 资源。

因此：

```text
Memory
CPU
PIDs
```

应该作为三套不同资源边界。

---

# 33. Rootless 是什么

Rootless Docker 是：

> Docker Daemon 和 Container 都由非 Root 用户运行，并利用 User Namespace 降低 Docker Daemon / Runtime 漏洞对 Host 的影响。

Docker 官方目前就是这样定义 Rootless Mode 的。([Docker Documentation][15])

这和普通 Docker：

```text
docker CLI
→ rootful Docker daemon
```

的 Trust Model 不一样。

---

# 34. Rootless 不是一个 `docker run` Profile Flag

这是面试非常容易讲错的地方。

你的：

```python
SandboxProfile
```

控制：

```text
一个 Container 怎么运行
```

而：

```text
Rootless Docker
```

主要是：

```text
Docker Engine / Daemon
如何部署
```

所以：

```text
rootless=True
```

不应该随便塞进：

```text
SandboxProfile
```

然后映射成某个不存在的普通 `docker run` Flag。

它属于：

```text
Host Runtime Security Configuration
```

而不是：

```text
Per-command Sandbox Profile
```

---

# 35. Rootless 和“Container 内非 Root 用户”还是两件事

即使 Docker Engine 使用 Rootless Mode，

你仍然应该考虑：

```text
Container 里的程序
```

以一个普通 UID 运行。

Docker 官方在 User Namespace 安全文档中也建议应用程序尽量作为 Unprivileged User 运行。([Docker Documentation][5])

因此最终 Hardened Profile 还可以增加：

```text
run_as_uid
run_as_gid
```

但 Day 6 第一版可以先不把 UID/GID 问题复杂化。

---

# 36. 一个必须牢记的工业级危险点：Docker Socket

假设 Container 被 Mount：

```text
/var/run/docker.sock
```

那么 Container 可以直接和 Host Docker Daemon 通信。

Docker 官方甚至明确展示：把 Docker Socket 与 Docker Binary Bind Mount 到 Container，相当于让 Container 获得操纵 Host Docker Daemon 的能力。([Docker Documentation][7])

因此：

```text
docker.sock
```

是 Day 6 的：

```text
Hard DENY
```

---

# 37. 为什么 Docker Socket 比普通 Secret 更危险

因为如果 Agent 能访问：

```text
/var/run/docker.sock
```

它可能要求 Docker Daemon：

```text
创建新 Container
Mount /
启用 privileged
访问 Host Files
```

于是：

```text
原 Sandbox
```

就能通过：

```text
Docker Daemon
```

绕出去。

所以：

```text
Never mount Docker socket
```

必须成为代码结构保证，而不是 Prompt 约定。

---

# 38. 工业实践：OpenAI Codex 并没有简单把 Docker 当唯一 Sandbox

这是今天特别值得理解的工业设计。

OpenAI 当前公开的 Codex 本地 Sandbox 采用平台原生机制：

```text
macOS
→ Seatbelt

Linux / WSL
→ bubblewrap + seccomp
   部分路径使用 Landlock

Windows
→ Windows sandbox mechanism
```

而不是统一用 Docker。([OpenAI Developers][16])

为什么值得注意？

因为它说明：

> **Sandbox 是抽象能力，Docker 只是 Sandbox Backend 的一种实现。**

---

# 39. 所以你的 CodeTeam 不应该叫 `DockerSandbox` 到处传

更好的架构是：

```text
SandboxRunner Protocol

      │
      ├── DockerRunner
      │
      ├── NativeLinuxRunner     future
      │
      ├── MacOSSandboxRunner    future
      │
      └── WindowsSandboxRunner  future
```

而不是：

```text
Agent Runtime
深度绑定 Docker
```

你的 Day 6：

```text
DockerRunner
```

只是：

```text
Sandbox Backend V1
```

这是一个很重要的 Agent Infra Design Decision。

---

# 40. 工业实践：GitHub Copilot 也是独立 Sandbox Layer

GitHub 当前 Copilot CLI 支持 OS-level Local Sandbox，对：

```text
Filesystem
Network
System capabilities
```

施加约束。([GitHub Docs][17])

因此 OpenAI 和 GitHub 的公开设计都体现同一个原则：

```text
Agent
不能直接继承用户 Process 的全部 Host Capability
```

---

# 41. Claude Code 同样把 Permission 和 Sandbox 分开

Claude Code 当前也有针对 Bash Command 的 Filesystem / Network Sandbox，并明确建议 Permission + Sandbox 做 Defense in Depth。([Claude Platform Docs][18])

这进一步说明：

```text
Policy
Approval
Sandbox
```

是三个不同层次。

---

# 42. 对 CodeTeam 的结论

不要在面试里说：

> “工业界都是 Docker Sandbox，所以我也用了 Docker。”

这不准确。

更合理：

> “我把 Sandbox 抽象成 Runtime Capability Boundary。第一版为了实现可复现、跨开发环境相对统一的隔离后端，我选择 Docker；但 OpenAI Codex、GitHub Copilot CLI、Claude Code 的公开实现说明，本地 Coding Agent 往往也使用 OS-native sandboxing，因此我的 DockerRunner 是可替换 Backend，而不是系统核心接口。”

这才是成熟的系统设计表达。([OpenAI Developers][1])

---

# 43. 现在重新看你的 `SandboxProfile`

你给出的：

```python
class SandboxProfile(BaseModel):
    network_enabled: bool = False

    memory_mb: int = 2048
    cpus: float = 2.0
    pids_limit: int = 256

    read_only_root: bool = True
    drop_all_capabilities: bool = True
    no_new_privileges: bool = True

    workspace_write: bool = True
```

这个模型的方向非常合理。

最重要的是：

> `SandboxProfile` 应描述**安全意图**，而不是直接暴露 Docker 参数。

---

# 44. 为什么不能设计成

```python
class SandboxProfile(BaseModel):
    docker_extra_args: list[str]
```

因为 LLM 或上层模块就可能传：

```text
--privileged

--network host

--pid host

--cap-add SYS_ADMIN
```

然后整个 Sandbox 失效。

所以：

```text
Profile
→ High-level policy
```

而：

```text
DockerCommandBuilder
→ Trusted translation
```

---

# 45. `SandboxProfile` 每个字段的真实意义

## `network_enabled`

```python
False
```

→

```text
--network none
```

Docker `none` Network Driver 会隔离 Container Network，只保留 Loopback。([Docker Documentation][10])

---

## `memory_mb`

```text
2048
```

→

```text
--memory 2048m
```

可选进一步：

```text
--memory-swap 2048m
```

避免额外 Swap。([Docker Documentation][14])

---

## `cpus`

```text
2.0
```

→

```text
--cpus 2.0
```

由 cgroup/CFS 等机制限制 CPU 使用额度。([Docker Documentation][14])

---

## `pids_limit`

```text
256
```

→

```text
--pids-limit 256
```

限制 PID 使用。([Docker Documentation][7])

---

## `read_only_root`

```text
True
```

→

```text
--read-only
```

Container Root FS 只读。([Docker Documentation][7])

---

## `drop_all_capabilities`

```text
True
```

→

```text
--cap-drop ALL
```

符合 Least Privilege 设计。([Docker Documentation][4])

---

## `no_new_privileges`

```text
True
```

→

```text
--security-opt no-new-privileges=true
```

阻止获得新的 Privilege。([Docker Documentation][7])

---

## `workspace_write`

```text
True
```

→

```text
/workspace bind mount
RW
```

否则：

```text
RO
```

Docker Bind Mount 可以明确设置 Read-only。([Docker Documentation][6])

---

# 46. Profile 不应该包含什么

建议不要加入：

```text
privileged
cap_add
devices
host_network
host_pid
docker_socket
arbitrary_mounts
extra_docker_args
```

因为：

```text
这些不是普通 Sandbox 配置
```

而是：

```text
Sandbox Escape Surface
```

第一版干脆让 API 无法表达。

---

# 47. `DockerCommandBuilder` 的真正职责

它不应该只是：

```python
args = ["docker", "run"]
```

然后拼字符串。

它真正应该：

```text
SandboxProfile
+
Trusted Worktree
+
CommandRequest
+
Trusted Sandbox Image
        ↓
安全、确定性的 docker argv
```

并保证：

```text
Forbidden flags
永远不出现

Exactly one host bind mount
只有当前 Task Worktree

Image
来自 Runtime Config

Command
来自已通过 Policy/Approval 的 request
```

---

# 48. 一个概念上的 V1 Docker 命令

最终大致类似：

```text
docker run

--rm
--init
--pull=never

--network none

--read-only

--cap-drop ALL

--security-opt
no-new-privileges=true

--memory 2048m
--memory-swap 2048m

--cpus 2.0

--pids-limit 256

--mount
type=bind,
src=/trusted/task-001,
dst=/workspace

--tmpfs
/tmp:rw,nosuid,size=256m

--workdir
/workspace

<fixed-sandbox-image>

python -m pytest
```

这里 `--init` 可以让 Container 中有一个 Init Process 负责回收 Zombie Processes，Docker 官方明确说明 `--init` 会承担 PID 1 的基本进程回收职责。([Docker Documentation][7])

这是推荐 Hardening 示例，不意味着今天所有附加项必须一次性实现。

---

# 49. 为什么我建议加 `--rm`

Coding Agent 的 Sandbox Container 是：

```text
Ephemeral Runtime
```

不是：

```text
长期服务
```

所以正常结束：

```text
Container 应删除
```

Docker 的 `--rm` 可以在 Container 退出后自动移除其 Container Filesystem。([Docker Documentation][7])

否则：

```text
1000 个 Agent Command
→ 1000 个 Stopped Container
```

逐渐污染 Runtime Host。

---

# 50. 为什么我建议加 `--init`

在 Container 中：

```text
Command
→ child
→ grandchild
```

PID 1 对 Child Reaping 有特殊职责。

Docker 官方提供：

```text
--init
```

专门用于运行一个最小 Init Process，帮助回收 Zombie。([Docker Documentation][7])

这和 Day 5：

```text
Host CommandRunner
Process Group
```

属于不同层：

```text
Day 5
管理 Docker CLI / Host Process lifecycle

Day 6
--init
管理 Container 内 Process lifecycle
```

---

# 51. `DockerRunner` 不要重新实现 Day 5

你已经有：

```text
CommandRunner

timeout
SIGTERM
SIGKILL
stdout limit
stderr limit
env control
```

所以不要：

```text
DockerRunner
重新实现一整套 subprocess
```

更好的关系：

```text
DockerRunner
      │
      ├── DockerCommandBuilder
      │
      ▼
host docker argv
      │
      ▼
CommandRunner
```

也就是：

```text
DockerRunner
=
Sandbox lifecycle orchestration

CommandRunner
=
host process execution
```

---

# 52. 但是这里隐藏着一个重要 Failure Case

假设：

```text
CommandRunner
timeout
```

然后只杀：

```text
docker CLI process
```

Docker Daemon 管理的 Container：

```text
不一定因此已经消失
```

所以工业化一点的 `DockerRunner` 最终还必须管理：

```text
Container ID
```

而不是把 Docker 当普通 subprocess。

---

# 53. 推荐的长期 DockerRunner 生命周期

比单纯：

```text
docker run ...
```

更可靠的设计是：

```text
docker create
      │
      ▼
Container ID
      │
      ▼
record ownership
      │
      ▼
docker start -a
      │
      ├── completed
      │
      └── timeout/error
              │
              ▼
       stop/kill exact owned container
              │
              ▼
           remove
```

这样 Runtime 明确知道：

```text
哪个 Container 属于哪个 task/run
```

这对：

```text
Timeout cleanup
Crash recovery
Leak detection
Audit
```

都更好。

Day 6 MVP 可以先 `docker run --rm`，但应把 Container Ownership 作为后续 Hardening。

---

# 54. Main Worktree 为什么天然不应该被 Mount

Day 2 已经建立：

```text
Task
→ own Worktree
```

所以 Sandbox 输入应该是：

```text
WorktreeManager
返回的 trusted WorktreeInfo
```

而不是：

```text
LLM:
mount_path="/whatever"
```

这意味着：

```text
Task ownership
→ Worktree ownership
→ Sandbox mount
```

形成：

```text
Agent Task
=
唯一 Filesystem Authority
```

---

# 55. 所以正确 Data Flow

```text
task_id
   │
   ▼
WorktreeManager
   │
   ▼
trusted WorktreeInfo
   │
   ▼
SafePath / ownership validation
   │
   ▼
SandboxExecutionContext
   │
   ├── profile
   ├── workspace
   ├── image
   └── command
   │
   ▼
DockerCommandBuilder
   │
   ▼
DockerRunner
```

不要：

```text
LLM
→ 自己指定 mount
```

---

# 56. 推荐再增加一个模型，而不是把所有东西塞进 `SandboxProfile`

例如概念上：

```python
class SandboxExecutionContext(
    BaseModel
):
    task_id: str
    workspace_path: str

    image_ref: str

    command: CommandRequest
```

这样：

```text
SandboxProfile
```

回答：

```text
权限有多大？
```

而：

```text
ExecutionContext
```

回答：

```text
这一次运行谁、在哪、运行什么？
```

职责清晰很多。

---

# 57. Image 也不应该由 LLM 自由指定

错误：

```text
LLM:

image =
random-user/untrusted-image:latest
```

然后 Agent Runtime：

```text
docker run
```

因为 Image 本身也是代码。

建议：

```text
Runtime-controlled image allowlist

+
digest pinning
+
pull=never
```

Day 6 可以先使用一个固定：

```text
codeteam-sandbox
```

Image。

---

# 58. Root FS 只读时 Build/Test 怎么办

真实开发中可能遇到：

```text
pytest
→ .pytest_cache

Python
→ __pycache__

compiler
→ /tmp

npm
→ caches

Java
→ temp files
```

解决思路不是：

```text
read_only_root=False
```

而应该：

```text
明确划分 Writable Area
```

例如：

```text
/workspace
/tmp
```

以及以后：

```text
/cache
```

这是工业 Sandbox 很核心的：

> **Explicit Writable Roots**

OpenAI 当前 Codex 的 `workspace-write` 思路本质上也是类似：Workspace 是默认可写边界，网络和 Workspace 外操作受到额外限制。([OpenAI Developers][11])

---

# 59. Day 6 推荐代码目录

结合 Day 4/5：

```text
codeteam/
└── execution/
    ├── models.py
    ├── command_policy.py
    ├── approval.py
    ├── runner.py
    │
    └── sandbox/
        ├── __init__.py
        ├── models.py
        ├── docker_builder.py
        └── docker_runner.py
```

或者项目还小时：

```text
execution/
├── sandbox.py
└── docker_runner.py
```

都可以。

不要为了架构图漂亮一次拆十几个文件。

---

# 60. 建议 Day 6 拆成 7 个 Step

## Step 1：Docker 基础实验

亲手理解：

```text
Image
Container
Mount
Network
Read-only Root
```

---

## Step 2：`SandboxProfile`

实现：

```text
安全默认
参数验证
```

---

## Step 3：`DockerCommandBuilder`

先只：

```text
生成 argv
不真正执行
```

这是非常适合 Pure Unit Test 的模块。

---

## Step 4：Mount Security

实现：

```text
只有 Task Worktree
绝对禁止 arbitrary mount
绝对禁止 docker.sock
```

---

## Step 5：`DockerRunner`

真正启动受限 Container。

---

## Step 6：Security Integration Tests

在 Container 中验证：

```text
Read workspace
Write workspace
Host isolation
Network
Root FS
PIDs
```

---

## Step 7：Benchmark / Ablation / Failure Analysis

形成工程证据。

---

# 61. DockerCommandBuilder 的测试应该比 Docker Integration Test 更早

例如：

```python
argv = builder.build(...)
```

然后直接检查：

```text
--network
none

--read-only

--cap-drop
ALL

--security-opt
no-new-privileges=true

--memory
2048m

--cpus
2.0

--pids-limit
256
```

并检查：

```text
--privileged
NOT IN argv

--device
NOT IN argv

--pid=host
NOT IN argv
```

这种测试：

```text
快
稳定
不依赖 Docker Daemon
```

---

# 62. 必测：Exactly One Host Bind Mount

不只是：

```text
“包含 workspace mount”
```

而应该：

```text
Host Bind Mount Count
=
1
```

并且：

```text
Source
=
canonical task worktree

Destination
=
/workspace
```

其他 Writable Area：

```text
/tmp
```

使用：

```text
tmpfs
```

而不是 Host Bind。

---

# 63. 为什么用 `docker inspect` 做验收特别好

不用只在 Container 内猜配置是否生效。

创建测试 Container 后：

```text
docker inspect
```

可以检查：

```text
ReadonlyRootfs

HostConfig.Memory

HostConfig.NanoCpus

HostConfig.PidsLimit

HostConfig.CapDrop

HostConfig.SecurityOpt

HostConfig.NetworkMode

Mounts
```

Docker 官方 Bind Mount 文档也使用 `docker inspect` 验证 Mount 的 Source、Destination、RW 状态。([Docker Documentation][6])

这样你的验收从：

```text
“命令里面有参数”
```

升级为：

```text
“Container 实际配置就是这样”
```

---

# 64. 测试 1：读 Worktree 成功

准备：

```text
task-001/
└── hello.txt

content:
hello
```

Container：

```text
cat /workspace/hello.txt
```

预期：

```text
hello
```

证明：

```text
Task Source
被正确暴露
```

---

# 65. 测试 2：写 Worktree 成功

在 Container：

```text
write:
/workspace/generated.txt
```

Container 退出后：

```text
Host task worktree
```

应该出现：

```text
generated.txt
```

因为 Writable Bind Mount 的修改会映射回 Host。([Docker Documentation][6])

同时：

```text
Main Worktree
```

必须不出现这个文件。

这就连接：

```text
Day 2 Worktree Isolation
+
Day 6 Sandbox Mount
```

---

# 66. 测试 3：读未挂载 Host 文件失败

测试时：

```text
tmp_path/
├── task/
│   └── visible.txt
│
└── host_secret_canary.txt
```

只 Mount：

```text
task/
```

Container 尝试读取 Host 的：

```text
host_secret_canary.txt
```

应该：

```text
不存在 / 无法访问
```

注意：

> 不要真的去访问用户 `~/.ssh`。

使用：

```text
synthetic canary
```

证明 Isolation 即可。

---

# 67. 测试 4：访问公网失败

你可以用 Python Socket 做一个短 Timeout Connect：

```text
Container
→ external IP
```

应该失败。

但更确定的测试还应该检查：

```text
NetworkMode == none
```

因为公网本身可能由于 CI 环境、防火墙等原因已经不可达。

Docker `none` 模式只保留 Loopback。([Docker Documentation][10])

所以：

```text
Configuration evidence
+
Behavior evidence
```

两种都做。

---

# 68. 测试 5：写 Root FS 失败

例如：

```text
touch /etc/codeteam_probe
```

预期：

```text
Read-only filesystem
```

同时：

```text
touch /workspace/probe
```

应成功。

这证明：

```text
Default RO
+
Explicit RW Root
```

真正成立。

---

# 69. 测试 6：PIDs Limit

这里**不要跑 Fork Bomb**。

禁止：

```text
:(){ :|:& };:
```

正确做法是写一个受控 Python Test Program：

```text
循环 spawn sleep child

最多尝试：
例如 profile_limit + small_margin

遇到资源限制
→ 停止

finally:
terminate every child
```

验证：

```text
无法无限创建 Process
```

不要硬断言：

```text
恰好第 257 个失败
```

因为：

```text
init
shell
runner
threads
```

本身可能占 PID。

---

# 70. CPU / Memory 推荐怎么测

Day 6 的正确性验收：

```text
docker inspect
```

确认：

```text
Memory
CPU quota
PidsLimit
```

已经配置。

不要为了证明 Memory Limit：

```text
故意把 Host 打到 OOM
```

可以后续在安全 Container 内用受控 Workload 做 Benchmark。

Docker 官方明确提醒，不限制 Container Memory 可能影响整个 Host 稳定性。([Docker Documentation][14])

---

# 71. Docker Socket 测试

不要：

```text
真的把 /var/run/docker.sock
mount 进去测试攻击
```

那违反你今天的安全边界。

正确测试：

```text
DockerCommandBuilder
```

对于任何要求：

```text
source=/var/run/docker.sock
```

必须：

```text
无法表达
或直接 SecurityError
```

同时生成的 `argv` 中：

```text
docker.sock
```

永远不存在。

Docker 官方已经明确说明 Socket Mount 可以赋予 Container 操纵 Docker Daemon 的能力，所以没有必要真实攻击 Host 来证明风险。([Docker Documentation][7])

---

# 72. `--privileged` 同理

不要：

```text
运行一个 privileged Container
然后测试能不能伤害 Host
```

而应该：

```text
builder output
永远不能出现 --privileged
```

这是 Static Safety Invariant。

Docker 官方已经明确说明 Privileged Container 不应被当作安全 Sandbox。([Docker Documentation][7])

---

# 73. Day 6 的核心验收最好定义成 6 个 Invariant

## Invariant 1：Mount Isolation

```text
Host bind mounts
=
exactly one Task Worktree
```

---

## Invariant 2：Network

```text
network_enabled=False

→
NetworkMode == none
```

---

## Invariant 3：Privilege

```text
--privileged
never

--cap-add
never

CapDrop includes ALL
```

---

## Invariant 4：Filesystem

```text
RootFS
read-only

Workspace
only explicit writable host path
```

---

## Invariant 5：Resources

```text
Memory
CPU
PIDs

all explicitly bounded
```

---

## Invariant 6：Docker Socket

```text
docker.sock
never mounted
```

---

# 74. Design Decision 1：Docker vs Native Sandbox

候选：

### A. 无 Sandbox

```text
CommandRunner
直接 Host
```

优点：

```text
快
```

缺点：

```text
几乎没有 capability isolation
```

---

### B. Docker

优点：

```text
Filesystem namespace
Network isolation
cgroup
Capabilities
Environment reproducibility
容易理解
```

缺点：

```text
启动开销
Docker dependency
Host daemon attack surface
Linux-container semantics
```

---

### C. Native OS Sandbox

例如：

```text
Linux:
bubblewrap / Landlock / seccomp

macOS:
Seatbelt

Windows:
native sandbox primitives
```

优点：

```text
启动更轻
本地体验更自然
```

缺点：

```text
跨平台实现复杂
```

OpenAI 当前 Codex 就采用平台原生 Sandbox Backend。([OpenAI Developers][16])

### Day 6 Decision

```text
V1:
Docker

Architecture:
Sandbox backend must remain replaceable.
```

---

# 75. Design Decision 2：Mount-whitelist vs Arbitrary Mounts

### A

```text
用户/Agent 可传：
mounts: list[Mount]
```

灵活。

但非常危险。

### B

```text
DockerCommandBuilder
只接受 trusted task workspace
```

推荐：

```text
B
```

原因：

```text
Sandbox Isolation
实际等于
Mount Authority
```

Bind Mount 可以直接修改 Host，所以 Mount Surface 必须非常窄。([Docker Documentation][6])

---

# 76. Design Decision 3：Writable Root vs Read-only Root

Baseline：

```text
Docker default writable root
```

Full：

```text
read-only root
+
explicit workspace RW
+
tmpfs
```

推荐后者。

因为：

```text
Agent 真正需要写的地方
应该非常有限。
```

---

# 77. Design Decision 4：Drop Default Caps vs Drop All

Docker 本身已经丢弃许多 Capability，但仍保留一些默认 Capability。Docker 安全文档建议进一步遵循“只保留明确需要的 Capability”。([Docker Documentation][4])

对于：

```text
Coding / tests / lint
```

第一版推荐：

```text
cap-drop ALL
```

如果某个 Tool 真的需要 Capability：

```text
不要偷偷 cap-add
```

而应该：

```text
新的 SandboxProfile
+
Design Review
+
Approval
```

---

# 78. Design Decision 5：Network Default

选：

```text
Default:
none
```

需要 Network：

```text
Policy
→ Approval
→ dedicated network-enabled profile
```

而不是：

```text
所有 Container 默认联网
```

这和 OpenAI Codex 当前的 Workspace Sandbox 默认关闭 Network 的方向一致。([OpenAI Developers][11])

---

# 79. Design Decision 6：Rootless 是否强制

我建议：

```text
SandboxProfile
不负责 Rootless
```

而：

```text
Deployment Recommendation:
Prefer Rootless Docker when available
```

因为 Rootless 属于：

```text
Host Docker Runtime posture
```

Docker 官方同样把 Rootless Mode 定义为整个 Docker Daemon/Container Runtime 的非 Root 部署方式。([Docker Documentation][15])

---

# 80. Benchmark 1：Sandbox Startup Overhead

Baseline：

```text
Direct CommandRunner
```

Full：

```text
DockerRunner
```

运行：

```text
python -c pass
```

例如：

```text
30～100 iterations
```

指标：

```text
P50 startup latency

P95 startup latency

total duration
```

回答：

> Docker Sandbox 给每个 Tool Call 带来了多少固定开销？

---

# 81. 这个 Benchmark 对架构非常重要

如果你发现：

```text
direct runner:
5 ms

Docker:
500 ms
```

那么未来可能设计：

```text
Persistent per-task Container
```

而不是：

```text
每条 Command
启动一个 Container
```

所以 Benchmark 不是为了：

```text
证明 Docker 很快
```

而是为了：

```text
影响 Runtime Architecture
```

---

# 82. Benchmark 2：Container-per-command vs Container-per-task

这是以后非常有价值的扩展实验。

### A

```text
每 Command
new Container
```

Isolation 很干净。

### B

```text
Task 生命周期
复用一个 Container
```

速度快。

比较：

```text
P50 command latency
P95
state leakage
cleanup complexity
disk growth
```

这是一个非常好的 Agent Infra Interview Topic。

---

# 83. Benchmark 3：Resource Limit Verification

不同 Profile：

```text
memory:
256MB
512MB
2GB

cpus:
0.5
1
2

pids:
32
64
256
```

使用受控 Workload，

测：

```text
max observed RSS

CPU throughput

max controlled child count

container failure mode
```

但注意：

```text
这属于 Benchmark
不是必须用破坏性压力测试完成
```

---

# 84. Benchmark 4：Workspace I/O Overhead

Baseline：

```text
Host direct filesystem
```

Full：

```text
Docker bind-mounted filesystem
```

Workload：

```text
read 1000 files
write temporary generated files
git status
pytest
```

测：

```text
duration
```

特别是在：

```text
Docker Desktop macOS
Windows
```

Bind Mount I/O 可能和 Linux Native 情况不同，所以实验环境必须记录。Docker Desktop 与 Linux Engine 的实现路径本身不同，结果不可随意横向比较。([Docker Documentation][3])

---

# 85. Ablation 1：去掉 `--network none`

Full：

```text
NetworkMode:
none
```

Ablated：

```text
Docker default bridge
```

比较：

```text
Network Capability
```

可以建立一个完全受控的 Test Network，而不是依赖真实公网。

例如：

```text
Test server container
    │
    ├── Sandbox: none
    │       → cannot connect
    │
    └── Ablated bridge
            → can connect
```

这样证明：

```text
Network Namespace
```

真的改变了 Capability。

---

# 86. Ablation 2：去掉 Read-only Root

Full：

```text
touch /etc/test
→ FAIL
```

Ablated：

```text
root fs writable
```

则同样操作可能成功。

比较：

```text
rootfs_write_success
```

这是一个非常直接的安全 Ablation。

---

# 87. Ablation 3：去掉 `cap-drop ALL`

Full：

```text
CapEff
≈ no capabilities
```

Ablated：

```text
Docker default capabilities
```

可以安全读取：

```text
/proc/self/status
```

中的 Capability Bitmask，

比较：

```text
CapEff
```

不需要真正执行危险 Capability 操作。

---

# 88. Ablation 4：去掉 `pids-limit`

Full：

```text
pids limit
```

Ablated：

```text
no explicit pids limit
```

用受控 Process Spawn Test：

```text
Full
在合理上限前停止

Ablation
可以继续超过该边界
```

不要无限 Spawn。

---

# 89. Ablation 5：Shared Main Workspace vs Task Mount

使用**临时模拟 Repo**，不要碰真实项目。

### Full

```text
mount task-001/
```

Agent 修改：

```text
只改变 task-001
```

### Ablation

```text
mount fake-main/
```

修改会直接污染 fake main。

这个 Ablation 能把：

```text
Worktree
+
Sandbox Mount
```

两层隔离价值串起来。

---

# 90. 哪些 Ablation 绝对不要做

不要真实执行：

```text
mount real docker.sock

--privileged exploit

mount host /

--pid=host destructive operation

CAP_SYS_ADMIN attack
```

这些没有必要。

可以：

```text
Static Builder Test

Synthetic Fake Socket Path

Inspect Configuration
```

证明系统无法构造这些能力。

---

# 91. Failure Case 1：Docker Socket Exposure

已经是今天最严重 Failure Case 之一：

```text
sandbox
+
docker.sock
=
sandbox boundary potentially bypassed
```

所以：

```text
No Docker socket
```

必须成为 Hard Invariant。Docker 官方明确说明 Docker Socket Mount 可以授予 Container 操纵 Host Docker Daemon 的能力。([Docker Documentation][7])

---

# 92. Failure Case 2：Implicit Image Pull

```text
--network none
```

但：

```text
image missing
```

Docker Daemon 仍可能在启动阶段 Pull。

改进：

```text
preloaded pinned image
+
--pull=never
```

这是一个非常适合面试讲的“边界之外的副作用”案例。([Docker Documentation][12])

---

# 93. Failure Case 3：Read-only Root 导致正常 Build 失败

症状：

```text
pytest / compiler
报 PermissionError
```

原因：

```text
工具需要 /tmp / cache
```

错误修复：

```text
read_only_root=False
```

更好的修复：

```text
explicit tmpfs
```

也就是：

> 不要因为一个应用需要写一个目录，就把整个安全边界放开。

---

# 94. Failure Case 4：UID/GID Mismatch

Container 中用户：

```text
UID 1000
```

Host Worktree：

```text
属于另一个 UID
```

可能导致：

```text
Permission denied
```

或者新文件在 Host 出现奇怪 Owner。

这是 Bind Mount + Non-root Container 很常见的工程问题。

后续可以通过：

```text
UID/GID mapping

rootless

user namespace

runner-specific user mapping
```

处理。Docker Rootless / User Namespace 就是处理这类权限隔离的重要机制之一。([Docker Documentation][15])

---

# 95. Failure Case 5：Resource Limits 没配

如果忘记：

```text
memory
cpus
pids
```

Container 并不会自动获得这些限制。

Docker 官方明确说默认没有 Resource Constraints。([Docker Documentation][14])

所以：

```text
SandboxProfile
不能 Optional-by-accident
```

最好始终生成限制。

---

# 96. Failure Case 6：磁盘仍然可以被写爆

这一点非常重要。

你的 Profile 有：

```text
CPU
Memory
PIDs
```

但是：

```text
workspace_write=True
```

意味着 Agent 仍然可能：

```text
写 100 GB 到 Worktree
```

Docker 的：

```text
--memory
```

不能限制：

```text
Bind-mounted Host Disk Usage
```

所以：

```text
Disk Quota
Workspace Size Limit
```

是当前 Sandbox 的一个明确 Known Limitation。

这非常值得写入 Failure Case。

---

# 97. Failure Case 7：Output Limit 和 Docker Log 不是一回事

Day 5：

```text
CommandRunner
限制 stdout/stderr capture
```

但 Docker Daemon 自己还可能配置 Container Logging Driver。

Docker 支持独立的 Container Logging Driver，包括关闭 Docker Log 存储的 `none` 驱动。([Docker Documentation][7])

因此需要记住：

```text
LLM output limit
```

不一定等于：

```text
Host Docker log disk usage limit
```

这可以作为后续 Runner Hardening 课题。

---

# 98. Failure Case 8：Container Leak

如果：

```text
Python process crash
Docker CLI timeout
Host reboot
```

可能留下：

```text
stopped / running codeteam container
```

因此建议所有 Container：

```text
label:
codeteam.task_id
codeteam.run_id
```

然后 Runtime Startup 可以：

```text
发现自己的孤儿 Container
→ 清理
```

不要按：

```text
container name contains "task"
```

粗暴删除。

---

# 99. Failure Case 9：Container Name Collision

两个 Worker 同时：

```text
task-001
```

如果名字：

```text
codeteam-task-001
```

会冲突。

应该：

```text
task_id
+
run_id
```

例如：

```text
codeteam-task-001-a13f...
```

并保存 Ownership Metadata。

---

# 100. Failure Case 10：Container Escape / Kernel Vulnerability

Docker Container 在 Linux 上共享 Host Kernel。([Docker Documentation][3])

所以即使配置：

```text
cap-drop ALL
read-only
network none
```

也不能声称：

```text
绝对无法逃逸
```

更成熟的 Hardening 包括：

```text
Rootless
user namespace
default seccomp
AppArmor / SELinux
patched kernel
VM isolation where needed
```

Docker 官方本身也提供 Enhanced Container Isolation、Rootless、Seccomp、AppArmor 等额外机制。([Docker Documentation][19])

---

# 101. Failure Case 11：Capability 全丢后某些工具不能工作

例如：

```text
debugger
ptrace-based test
network test
special filesystem tools
```

可能需要额外 Capability。

正确做法不是：

```text
Sandbox 默认 cap-add ALL
```

而是：

```text
Default profile
→ fail

明确识别需求
→ specialized profile
→ Policy
→ Approval
```

也就是：

```text
Least Privilege Escalation
```

---

# 102. Failure Case 12：`network_enabled=True` 太粗

未来：

```text
network=True
```

可能意味着：

```text
能访问整个互联网
```

但 Agent 真正需要的可能只是：

```text
pypi.org
```

所以成熟系统需要：

```text
Domain Allowlist
Egress Proxy
Network Policy
```

OpenAI Codex Cloud 公开设计也支持更细粒度的 Internet Access / Domain Allowlist。([OpenAI Developers][11])

因此今天：

```text
bool
```

适合 MVP，

但不是最终 Network Policy Model。

---

# 103. Tests 和 Benchmark 要再次区分

今天：

```text
Tests
```

回答：

```text
Sandbox 边界正确吗？
```

例如：

```text
不能访问 Host canary
```

---

Benchmark：

```text
Sandbox 成本是多少？
```

例如：

```text
Docker 启动 P95
```

---

Ablation：

```text
这个安全机制真的产生了能力差异吗？
```

例如：

```text
with/without read-only root
```

---

Failure Case：

```text
边界在哪些情况下仍然可能失败？
```

例如：

```text
Docker socket
disk exhaustion
```

---

# 104. Day 6 需要的 Benchmark Dataset/Workload

建议至少准备：

```text
B1
no-op command

B2
git status

B3
rg query

B4
pytest small suite

B5
read 1000 files

B6
write generated files
```

分别比较：

```text
Host Runner
vs
Docker Sandbox
```

指标：

```text
P50 latency
P95 latency
CPU time
wall time
startup overhead
cleanup latency
```

---

# 105. Benchmark 结果必须记录环境

Docker Benchmark 特别依赖：

```text
Linux native Docker Engine

vs

macOS Docker Desktop

vs

Windows Docker Desktop
```

所以至少记录：

```text
OS
Docker version
Docker backend
CPU
RAM
Image digest
Git commit
```

否则：

```text
P95=300ms
```

几乎没有可比较意义。

---

# 106. Day 6 最终 Evaluation Matrix

建议最终让 Test Agent 输出类似：

| 能力                       | Evidence |
| ------------------------ | -------- |
| Task Worktree 可读         | PASS     |
| Task Worktree 可写         | PASS     |
| Main Worktree 不受影响       | PASS     |
| Unmounted Host 文件不可见     | PASS     |
| Network none             | PASS     |
| RootFS read-only         | PASS     |
| CapDrop ALL              | PASS     |
| no-new-privileges        | PASS     |
| Memory limit             | PASS     |
| CPU limit                | PASS     |
| PID limit                | PASS     |
| Docker Socket absent     | PASS     |
| Privileged absent        | PASS     |
| Only one Host Bind Mount | PASS     |
| Container cleanup        | PASS     |

---

# 107. 今天必须理解的一个重要架构变化

Day 5 之前：

```text
CommandRunner
是最终执行器
```

Day 6 以后：

```text
SafeExecutor
    │
    ▼
SandboxRunner
    │
    └── DockerRunner
            │
            ▼
       Host CommandRunner
```

也就是说：

```text
CommandRunner
```

从：

```text
“运行用户代码”
```

变成：

```text
“运行 Docker Runtime CLI”
```

而用户真正的：

```text
pytest
git
python
```

运行在 Container 内。

---

# 108. 最终架构应该逐渐变成

```text
                  Agent Loop
                      │
                      ▼
                Tool Runtime
                      │
                      ▼
                CommandRequest
                      │
                      ▼
                CommandPolicy
                      │
                      ▼
               ApprovalManager
                      │
                      ▼
                SafeExecutor
                      │
                      ▼
               SandboxRunner
                      │
           ┌──────────┴─────────┐
           ▼                    ▼
     DockerRunner          NativeRunner
        V1                   Future
           │
           ▼
      CommandRunner
           │
           ▼
      OS / Docker
           │
           ▼
       Container
           │
      ┌────┼────────┐
      ▼    ▼        ▼
   Mount  Net     cgroup
      │
      ▼
 Task Worktree
      │
      ▼
CheckpointManager
```

现在第三周的各模块真正开始连接成一个完整 Harness。

---

# 109. 今天最终完成标准

按照你现在的固定工程闭环，Day 6 真正完成应该达到：

```text
Theory

[ ] Image
[ ] Container
[ ] Namespace
[ ] Mount
[ ] Read-only FS
[ ] Network Namespace
[ ] Capability
[ ] cgroup resource limits
[ ] Rootless


Industrial Design

[ ] Docker security model
[ ] OpenAI Codex sandbox layering
[ ] GitHub Copilot sandbox
[ ] Claude Code sandbox


Implementation

[ ] SandboxProfile
[ ] DockerCommandBuilder
[ ] DockerRunner


Hard Security Invariants

[ ] only Task Worktree mounted
[ ] docker.sock impossible
[ ] privileged impossible
[ ] default no network
[ ] rootfs read-only
[ ] cap-drop ALL
[ ] no-new-privileges
[ ] memory explicit
[ ] CPU explicit
[ ] PID explicit


Tests

[ ] read worktree
[ ] write worktree
[ ] main unaffected
[ ] host canary inaccessible
[ ] internet/network unavailable
[ ] root write rejected
[ ] PIDs bounded
[ ] inspect actual config


Design Decisions

[ ] Docker as replaceable backend
[ ] mount whitelist
[ ] read-only root
[ ] drop all capabilities
[ ] no-network default
[ ] Rootless as deployment hardening


Benchmark

[ ] startup latency
[ ] command overhead
[ ] workspace I/O
[ ] cleanup
[ ] resource behavior


Ablation

[ ] no network isolation
[ ] writable root
[ ] default caps
[ ] no pids limit
[ ] shared/main mount baseline


Failure Cases

[ ] docker socket
[ ] implicit image pull
[ ] UID mismatch
[ ] read-only temp failure
[ ] disk exhaustion
[ ] container leak
[ ] image supply chain
[ ] kernel/shared-kernel boundary
```

---

# 110. 今天必须能回答的 Interview Questions

### Docker 基础

1. Image 和 Container 有什么区别？
2. Container 和 VM 的核心区别是什么？
3. Namespace 和 cgroup 分别解决什么问题？
4. Bind Mount 为什么是 Sandbox 最大攻击面之一？
5. `--mount` 为什么比 `-v` 更适合 Runtime？

### Filesystem

6. `--read-only` 为什么不会阻止 Worktree 写入？
7. 为什么应该 Root FS 只读、Worktree 单独 RW？
8. Root FS 只读以后 `/tmp` 怎么处理？
9. 为什么不能 Mount Main Worktree？
10. 为什么 Docker Socket 绝对不能 Mount？

### Network

11. `--network none` 到底隔离了什么？
12. 为什么 `--network none` 仍不能保证 Docker Engine 不会 Pull Image？
13. 为什么 Agent 默认 Network 应关闭？
14. 未来怎样做 Domain-level Network Policy？

### Privilege

15. Linux Capability 是什么？
16. 为什么 `cap-drop ALL` 比 Docker 默认 Capability 更适合 Coding Agent？
17. `no-new-privileges` 和 `cap-drop` 有什么区别？
18. 为什么 `--privileged` 不应该进入 Approval 流程？
19. Rootless Docker 和 Container Non-root User 有什么区别？

### Resources

20. 为什么 Container 默认不是资源受限的？
21. `--memory` 是什么？
22. `--cpus=2` 是不是独占两颗 CPU？
23. `--pids-limit` 为什么重要？
24. Memory/CPU/PID 为什么不能互相替代？
25. 为什么这些限制仍然无法限制 Worktree Disk Usage？

### Agent Runtime

26. Policy 和 Sandbox 为什么都需要？
27. Approval 和 Sandbox 为什么不同？
28. DockerRunner 为什么应该是可替换 Backend？
29. 为什么 OpenAI Codex 选择 Native Sandbox，而你的 V1 使用 Docker？
30. 怎么证明你的 Sandbox 真正有效而不只是“参数很多”？

---

# 111. 如果面试官问：“Docker 本来就隔离了，你加这些 Flag 有什么意义？”

你最终应该能回答：

> “默认 Docker Container 并不等于适合执行不可信 Agent Code 的 Sandbox。Docker 默认没有 CPU/Memory Resource Limit，默认 Container 也通常具有网络能力，并且 Root Filesystem 默认可写；Bind Mount 如果配置错误会直接暴露 Host 文件。我的 Runtime 因此把 Docker 当作可配置的 Sandbox Backend：只将当前 Task Worktree Bind Mount 到 `/workspace`，Root FS 为 Read-only，默认 `--network none`，`--cap-drop ALL`，启用 `no-new-privileges`，同时显式设置 Memory、CPU 和 PID cgroup Limit；Docker Socket、Privileged Mode、Device Mount 和任意额外 Mount 在 Builder API 层无法表达。另外 Image 由 Runtime 固定并使用 `--pull=never`，避免 Container Network 已关闭但 Docker Daemon 仍隐式拉取 Image 的边界漏洞。”

这就已经不是：

```text
“我会 docker run”
```

而是：

```text
Agent Sandbox Threat Model
+
Least Privilege
+
Filesystem Isolation
+
Network Isolation
+
Resource Governance
+
Capability Control
```

Docker 官方对默认资源限制、Network、Bind Mount、Privilege 和 Capability 的行为都支持上述威胁模型。([Docker Documentation][14])

---

# 112. Day 6 最终的工程闭环

今天真正应该形成：

```text
Theory
        ↓
Namespaces / cgroups
Mount / Network / Caps
        ↓
Industrial Design
        ↓
Docker
OpenAI Codex
Claude Code
GitHub Copilot
        ↓
Implementation
        ↓
SandboxProfile
DockerCommandBuilder
DockerRunner
        ↓
Tests
        ↓
Filesystem
Network
Privilege
Resources
        ↓
Design Decisions
        ↓
Docker V1
Narrow Mount
RO root
No Network
        ↓
Benchmark
        ↓
Startup / I/O /
resource overhead
        ↓
Ablation
        ↓
Network
RootFS
Caps
PIDs
        ↓
Failure Cases
        ↓
socket
pull
disk
UID
container leak
kernel boundary
        ↓
Interview Evidence
```

Day 6 完成以后，你前六天实际上已经组成了一个相当完整的 **Agent Safe Execution Runtime**：

```text
Patch                Day 1
  ↓
Worktree Isolation   Day 2
  ↓
Checkpoint Recovery  Day 3
  ↓
Command Policy       Day 4
  ↓
Human Approval       Day 5
  ↓
Safe Runner          Day 5
  ↓
Docker Sandbox       Day 6
```

最值得你在这一阶段建立的系统认识是：

> **真正的 Agent Harness 不只是负责“让模型能够调用工具”，它还必须负责限制副作用、隔离任务、保存状态、授权风险行为、监督进程、限制系统资源，并在模型判断错误时依然保证执行边界。**

[1]: https://developers.openai.com/codex/sandboxing?utm_source=chatgpt.com "Sandbox | ChatGPT Learn"
[2]: https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-an-image/?utm_source=chatgpt.com "What is an image?"
[3]: https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/?utm_source=chatgpt.com "What is a container?"
[4]: https://docs.docker.com/engine/security/?utm_source=chatgpt.com "Docker Engine security"
[5]: https://docs.docker.com/engine/security/userns-remap/?utm_source=chatgpt.com "Isolate containers with a user namespace"
[6]: https://docs.docker.com/engine/storage/bind-mounts/ "Bind mounts | Docker Docs"
[7]: https://docs.docker.com/reference/cli/docker/container/run/ "docker container run | Docker Docs"
[8]: https://docs.docker.com/engine/storage/tmpfs/?utm_source=chatgpt.com "tmpfs mounts"
[9]: https://docs.docker.com/engine/network/drivers/bridge/?utm_source=chatgpt.com "Bridge network driver"
[10]: https://docs.docker.com/engine/network/drivers/none/?utm_source=chatgpt.com "None network driver"
[11]: https://developers.openai.com/codex/agent-approvals-security?utm_source=chatgpt.com "Agent approvals & security"
[12]: https://docs.docker.com/reference/cli/docker/container/run/?utm_source=chatgpt.com "docker container run"
[13]: https://docs.docker.com/engine/security/seccomp/?utm_source=chatgpt.com "Seccomp security profiles for Docker"
[14]: https://docs.docker.com/engine/containers/resource_constraints/ "Resource constraints | Docker Docs"
[15]: https://docs.docker.com/engine/security/rootless/?utm_source=chatgpt.com "Rootless mode"
[16]: https://developers.openai.com/codex/permissions?utm_source=chatgpt.com "Permissions | ChatGPT Learn"
[17]: https://docs.github.com/copilot/concepts/about-cloud-and-local-sandboxes?utm_source=chatgpt.com "About cloud and local sandboxes for GitHub Copilot"
[18]: https://docs.anthropic.com/en/docs/claude-code/settings?utm_source=chatgpt.com "Claude Code settings - Claude Code Docs"
[19]: https://docs.docker.com/enterprise/security/hardened-desktop/enhanced-container-isolation/?utm_source=chatgpt.com "Enhanced Container Isolation"


# 今日详细教程

我已完成只读检查，本轮没有修改任何文件。Day6 的核心是：把“命令可以被批准执行”继续升级成“即使命令内部恶意，也只能在受限环境里行动”。

**1. 今天做什么**

Day6 解决的是 `Safe Execution Runtime` 的技术边界问题。

Day4 `CommandPolicy` 回答：“这条命令风险是什么？”  
Day5 `ApprovalManager / CommandRunner` 回答：“用户是否授权？如何限时、限输出、清理进程？”  
Day6 `Docker Sandbox` 回答：“即使被授权的命令内部做坏事，它技术上最多能访问什么？”

所以 Day6 在系统里的位置是：

```text
Policy = 意图层风险判断
Approval = 人类授权判断
Sandbox = 操作系统/容器层能力边界
Runner = 进程生命周期管理
```

**2. Capability Mapping**

Day6 对应能力树：

```text
Workspace & Sandbox
Tool Runtime
Agent Runtime Safety
Evaluation
```

它能证明你具备：

- 把 Coding Agent 命令放进最小权限执行环境的能力。
- 区分 policy、approval、runner、sandbox 四层职责的能力。
- 设计可测试安全边界，而不是只写危险命令黑名单。
- 面试时可以讲清楚 Agent Runtime 为什么需要 defense in depth。

**3. Theory**

Image vs Container：  
Image 是运行环境模板，包含文件、依赖、二进制和配置；Container 是从 Image 启动的一次运行实例。

Namespace：  
让容器里的进程看到“自己的进程表、网络、挂载空间”等，像被放进一个隔离视角里。

cgroup：  
限制资源，比如内存、CPU、进程数量。没有资源限制时，恶意或失控测试可能拖垮宿主机。

Bind Mount：  
把宿主机路径挂到容器里。它是 Day6 最大风险点，因为容器可以通过 mount 读写宿主机文件。

read-only root filesystem：  
`--read-only` 让容器根文件系统不能写。正常写入只允许发生在明确挂载的路径，比如 `/workspace` 或 `/tmp`。

`--network none`：  
让容器没有外部网络，只保留 loopback。这样测试代码即使想连公网，也连不出去。

`--pull=never`：  
防止 `docker run` 因 image 不存在而隐式联网拉取镜像。注意：关闭容器网络不等于 Docker daemon 不会联网。

`--cap-drop ALL`：  
移除 Linux capabilities，避免容器获得不必要的内核级权限。

`--security-opt no-new-privileges`：  
禁止容器内进程通过 setuid 等方式获得新权限。

memory / cpu / pids limit：  
限制内存、CPU 使用额度和最大进程数，防止 fork bomb、无限占内存、CPU 打满。

Docker socket 为什么极危险：  
如果把 `/var/run/docker.sock` mount 进容器，容器可以控制宿主机 Docker daemon，相当于绕过 sandbox。

Docker Sandbox 不是 VM：  
容器通常共享宿主机内核；它是很有价值的隔离层，但不是绝对安全边界。

**4. Industrial Design**

官方公开事实：

- Docker 官方说明容器安全依赖 namespaces、cgroups、capabilities、daemon attack surface 等机制。
- Docker bind mount 默认可写，容器修改会反映到宿主机。
- Docker `run` 支持 `--read-only`、`--network`、`--pull=never`、`--cap-drop`、`--security-opt no-new-privileges`、资源限制等参数。
- OpenAI Codex 公开文档把 sandbox 和 approval 区分为两个协同控制：sandbox 定义技术边界，approval 决定何时暂停询问用户。

工程推断：

- Coding Agent 不能只靠命令字符串判断，因为 `pytest`、`npm test`、`python script.py` 内部可以执行任意代码。
- container-per-command 隔离更强，但启动开销更高。
- container-per-task 性能更好，但状态污染和逃逸影响面更大。
- Docker 是 V1 可落地方案，但长期应抽象成可替换 backend。

适合 CodeTeam 的选择：

- V1 用 Docker Sandbox，但接口命名应偏 `SandboxRunner`，不要把全系统绑死到 Docker。
- 默认 container-per-command，先追求边界清晰。
- 只 mount 当前 task worktree，不 mount 主仓库、HOME、SSH、Docker socket。
- 默认 `network none`、`pull never`、read-only root、drop capabilities、resource limits。

**5. 当前仓库检查**

Day4 当前能力：

- [models.py](/Users/root/workspace/Agent-Learning/codeteam/execution/models.py)：`CommandRequest`、`PolicyDecision`、`RiskCategory`、`PolicyEvaluation`。
- [command_policy.py](/Users/root/workspace/Agent-Learning/codeteam/execution/command_policy.py)：聚合规则，最高风险胜出。
- [policy_rules.py](/Users/root/workspace/Agent-Learning/codeteam/execution/policy_rules.py)：git、shell、网络、docker、credential、workspace escape 等规则。

Day5 当前能力：

- [approval.py](/Users/root/workspace/Agent-Learning/codeteam/execution/approval.py)：approval request/grant、scope、fingerprint、audit event。
- [runner.py](/Users/root/workspace/Agent-Learning/codeteam/execution/runner.py)：`shell=False`、timeout、进程组清理、输出截断、env allowlist、cwd 边界。
- [safe_executor.py](/Users/root/workspace/Agent-Learning/codeteam/execution/safe_executor.py)：policy → approval → runner 的编排。
- [output_limiter.py](/Users/root/workspace/Agent-Learning/codeteam/execution/output_limiter.py)：stdout/stderr 截断。

当前没有发现：

```text
codeteam/sandbox/
tests/sandbox/
```

现有 shell tool：

- [shell.py](/Users/root/workspace/Agent-Learning/codeteam/tools/shell.py) 仍是独立安全 shell tool，有自己的 argv/path/危险命令检查。
- Day6 后可以逐步让 shell 执行走 `SafeCommandExecutor + SandboxRunner`，但今天不要急着接。

测试影响：

- `tests/execution/` 已覆盖 Day4/Day5。
- `tests/git/` 会影响 worktree mount 设计。
- `pytest.ini` 已排除 `tests/fixtures`，避免 fixture repo 被 pytest 收集。
- `.codex/AGENTS.md` 要求必须用 `.venv/bin/python`，shell 执行必须 `shell=False`。

**6. 涉及文件**

Day6 可能新增：

- `codeteam/sandbox/__init__.py`：导出 sandbox public API。
- `codeteam/sandbox/models.py`：`SandboxProfile`、`SandboxExecutionContext`、`SandboxResult`。
- `codeteam/sandbox/docker_builder.py`：把 profile/context 编译成 `docker run` argv。
- `codeteam/sandbox/docker_runner.py`：调用 Docker CLI，复用 Day5 timeout/output 限制思想。
- `codeteam/sandbox/errors.py`：sandbox 配置错误、Docker 不可用、mount 不安全。
- `tests/sandbox/test_docker_builder.py`：不依赖 Docker daemon 的 builder 单测。
- `tests/sandbox/test_mount_security.py`：路径边界、Docker socket、敏感 mount。
- `tests/sandbox/test_docker_runner_integration.py`：Docker 可用时才跑的集成测试。

这轮不创建，只规划。

**7. Architecture / Data Flow**

```text
CommandRequest
→ CommandPolicy
→ ApprovalManager
→ SandboxProfile
→ SandboxExecutionContext
→ DockerCommandBuilder
→ DockerRunner
→ Docker Container
→ SandboxResult
```

更贴近当前仓库的版本：

```text
SafeCommandExecutor
    ├── CommandPolicy.default().evaluate()
    ├── ApprovalManager.consume()
    └── SandboxRunner.run()
            └── DockerRunner.run()
                    └── docker run argv
```

Day6 的重点不是替换 Day5，而是让 Day5 的 runner backend 从“本机 subprocess”变成“可替换执行后端”。

**8. 今日步骤拆分**

Step 1: Docker 基础实验和威胁模型  
目标：理解 Docker 能限制什么、不能限制什么。  
为什么先做：否则容易把 Docker 当 VM。  
涉及文件：暂不改代码。  
前置知识：image/container、mount、network、resource limit。  
完成标志：你能解释 Docker socket、bind mount、network none 的风险。

Step 2: `SandboxProfile`  
目标：定义安全意图。  
涉及文件：`codeteam/sandbox/models.py`。  
前置知识：Pydantic `BaseModel`、默认值、字段校验。  
完成标志：能实例化默认安全 profile。

Step 3: `SandboxExecutionContext`  
目标：定义本次执行的 workspace、cwd、argv、container name。  
涉及文件：`codeteam/sandbox/models.py`。  
前置知识：`Path`、路径 resolve、workspace boundary。  
完成标志：context 不允许 workspace 外路径。

Step 4: `DockerCommandBuilder`  
目标：把 profile/context 转成安全的 `docker run` argv。  
涉及文件：`docker_builder.py`。  
前置知识：list[str]、不使用 shell string。  
完成标志：builder 输出包含 `--network none`、`--read-only`、`--pull=never` 等。

Step 5: Mount security  
目标：只允许一个 task worktree mount，禁止 socket、HOME、SSH、敏感 host path。  
涉及文件：`docker_builder.py` / `errors.py`。  
前置知识：路径归一化、symlink、bind mount。  
完成标志：危险 mount 在 builder 阶段失败。

Step 6: `DockerRunner`  
目标：执行 Docker CLI，并返回结构化结果。  
涉及文件：`docker_runner.py`。  
前置知识：`subprocess.Popen`、timeout、stdout/stderr。  
完成标志：能跑简单命令，超时能清理容器。

Step 7: Security integration tests  
目标：Docker 可用时验证真实边界。  
涉及文件：`tests/sandbox/`。  
前置知识：pytest conditional skip。  
完成标志：读 workspace 成功，读 host secret 失败，网络失败，root 写入失败。

Step 8: Benchmark / Ablation / Failure Cases  
目标：证明 sandbox 有效果，也知道成本和失败点。  
涉及文件：后续 benchmark/test log。  
前置知识：计时、环境记录、对照组。  
完成标志：有指标、有对照、有失败案例记录。

**9. Test Strategy**

先写 builder 单元测试，不依赖 Docker daemon：

- `docker run` argv 必须是 list，不是 shell string。
- 必须包含 `--network none`。
- 必须包含 `--read-only`。
- 必须包含 `--pull=never`。
- 必须包含 `--cap-drop ALL`。
- 必须包含 `--security-opt no-new-privileges`。
- 必须包含 memory/cpu/pids limit。
- 只允许 workspace bind mount 到 `/workspace`。
- 禁止 Docker socket。
- 禁止 `/`、`/etc`、`/var`、`/usr`、HOME、SSH、AWS、Kube mount。

Docker 可用时再做 integration tests：

- 容器内读 `/workspace` 成功。
- 容器内写 `/workspace` 成功或按 profile 成功。
- 容器内读未挂载 host 文件失败。
- 访问公网失败。
- 写 root filesystem 失败。
- pids limit 生效。
- timeout 后 container 不泄漏。

Docker 不可用时：

- integration tests 可以 capability-based skip。
- skip 必须说明未验证范围。
- builder 和 mount security 单测不能 skip。

**10. Design Decision Plan**

DD1: Docker 作为 V1 backend，但 `SandboxRunner` 应可替换。  
DD2: 默认 `network none`。  
DD3: read-only root + limited writable mounts。  
DD4: no Docker socket / no privileged / no host namespace。  
DD5: fixed trusted image + `--pull=never`。  
DD6: resource limits required by default。

**11. Benchmark Plan**

要提前记录环境：

- Docker version
- OS
- Docker backend，比如 Linux Engine / Docker Desktop
- image name 和 digest/tag
- warmup 次数
- iterations
- task workspace 大小

指标：

- Docker startup overhead
- container-per-command vs container-per-task
- resource limit verification
- workspace bind mount I/O overhead
- stdout/stderr 大输出开销
- timeout cleanup latency

**12. Ablation Plan**

- Full sandbox vs no sandbox。
- `--network none` vs default bridge。
- read-only root vs writable root。
- `--cap-drop ALL` vs Docker default capabilities。
- pids limit vs no pids limit。
- task worktree mount vs main workspace mount。
- `--pull=never` vs Docker default pull policy。

注意：危险 ablation 不应该真实攻击宿主机；用受控命令证明边界变化即可。

**13. Failure Cases to Watch**

- Docker socket exposure。
- implicit image pull。
- read-only root breaks normal tools。
- UID/GID mismatch。
- missing resource limits。
- disk still writable through mounted workspace。
- Docker log growth。
- container leak after timeout。
- container name collision。
- Docker Desktop macOS bind mount performance。
- container escape / shared kernel limitation。
- package manager 需要网络但默认无网。
- tool 写 `/tmp` 失败，需要 tmpfs。
- image 不存在且 `--pull=never` 导致 start failed，这是正确失败。

**14. Interview Focus**

Day6 结束后你要能回答：

- 为什么 Policy / Approval / Sandbox 都需要？
- Docker 默认隔离为什么不够？
- 为什么 Docker socket 不能 mount？
- 为什么 `--network none` 还要配 `--pull=never`？
- 为什么 DockerRunner 应该是可替换 backend？
- 为什么只 mount task worktree，而不是 main workspace？
- 为什么 builder 单测比 Docker integration test 更早？
- 如何证明 Sandbox 真有效，而不是“参数很多”？
- Docker Sandbox 为什么不是 VM？
- Rootless Docker 和 container 内 non-root user 有什么区别？

**15. 今日最终完成标准**

功能验收：

- 有 `SandboxProfile`、`SandboxExecutionContext`、`DockerCommandBuilder`、`DockerRunner` 的最小闭环。
- 能把 `CommandRequest` 转成安全 Docker 执行。

安全验收：

- 默认无网络。
- 默认 read-only root。
- 默认资源限制。
- 禁止 Docker socket。
- 禁止 privileged / host namespace。
- 禁止 workspace 外 mount。

测试证据：

- builder 单测不依赖 Docker。
- mount security 单测覆盖危险路径。
- Docker 可用时 integration tests 验证真实边界。
- Docker 不可用时只 skip integration，并记录未验证范围。

Benchmark / Ablation 证据：

- 有 startup overhead。
- 有 container-per-command vs container-per-task 对比。
- 有 network/read-only/cap/pids ablation。
- 有环境 manifest。

Failure Case 记录：

- 至少记录 Docker socket、implicit pull、read-only root、UID/GID、container leak、Docker Desktop I/O。

面试表达：

- 能讲清楚 Day6 是 `Workspace & Sandbox` 能力，不是 Docker 参数堆砌。
- 能讲清楚为什么本项目 V1 选择 Docker，但架构上保留 Native Sandbox backend 的位置。

参考来源：  
[Docker Engine security](https://docs.docker.com/engine/security/)  
[Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)  
[Docker run reference](https://docs.docker.com/reference/cli/docker/container/run)  
[Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)  
[OpenAI Codex sandboxing](https://developers.openai.com/codex/sandboxing)