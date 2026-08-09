# 第 3 周：Git、Patch、Checkpoint 与安全执行

第二周解决的是：

> **Agent 应该看哪些代码？**

第三周开始解决更危险、也更接近真正 Coding Agent 的问题：

> **Agent 知道应该改什么之后，怎样让它真正修改代码、运行命令，同时保证“改坏了能恢复、任务之间不互相污染、危险操作不会直接执行”？**

因此这一周是从“代码理解系统”进入“代码执行系统”的关键转折点。

完成后，你的执行链应该变成：

```text
用户任务
   ↓
Context Engine
   ↓
Lead Agent
   ↓
WorktreeManager
   └─ 为任务创建独立 Git Worktree
              ↓
       CheckpointManager
       └─ 创建初始 Checkpoint
              ↓
       Agent 产生修改
              ↓
       Patch Validator
       ├─ 路径检查
       ├─ git apply --check
       └─ Patch 范围检查
              ↓
       GitWorkspace.apply_patch()
              ↓
       Git Diff
              ↓
       CommandPolicy
       ├─ ALLOW
       ├─ REQUIRE_APPROVAL
       └─ DENY
              ↓
       ApprovalManager
              ↓
       Sandbox / Docker
              ↓
       CommandRunner
       ├─ Timeout
       ├─ Output Limit
       └─ Resource Limit
              ↓
       Tests
       ↓
    成功？
    ├─ 是 → 保留 Diff / Commit
    └─ 否 → Rollback Checkpoint
```

这一周有一个非常重要的设计思想：

> **Git 负责版本状态；Worktree 负责任务隔离；Checkpoint 负责快速恢复；CommandPolicy 负责判断意图；Sandbox/Docker 负责真正限制能力。**

这四个东西不能互相替代。

---

# 一、先理解第三周五个核心模块的职责

最终建议实现：

```text
codeteam/
├── git/
│   ├── workspace.py
│   ├── diff.py
│   ├── patch.py
│   ├── worktree.py
│   └── checkpoint.py
│
├── execution/
│   ├── command_policy.py
│   ├── approval.py
│   ├── runner.py
│   ├── output_limiter.py
│   └── sandbox.py
│
└── containers/
    ├── docker_runner.py
    └── profiles.py
```

职责一定要拆开：

| 模块                  | 解决的问题              |
| ------------------- | ------------------ |
| `GitWorkspace`      | 当前任务改了什么？Git 状态怎样？ |
| `WorktreeManager`   | 多个任务怎样拥有彼此独立的工作目录？ |
| `CheckpointManager` | 修改失败后怎样恢复？         |
| `CommandPolicy`     | 这个命令是否允许、需审批还是禁止？  |
| `ApprovalManager`   | 谁批准、批准什么、有效多久？     |
| `CommandRunner`     | 命令怎样执行、超时、截断输出？    |
| `DockerRunner`      | 命令真正能访问哪些文件、网络和资源？ |

尤其不要写一个：

```python
class ShellTool:
    ...
```

里面同时完成：

```text
Git
权限
审批
Docker
超时
Checkpoint
```

后期几乎无法维护。

---

# 二、Git Diff：Agent 的“修改审计记录”

## 1. Git Diff 到底是什么

Git 中至少要区分：

```text
HEAD
最后一次提交

Index
暂存区

Working Tree
当前磁盘上的代码
```

因此存在三种常见 Diff。

### Working Tree vs Index

```bash
git diff
```

表示：

```text
我改了，
但还没有 git add 的内容
```

### Index vs HEAD

```bash
git diff --cached
```

表示：

```text
我已经 git add，
准备进入下一次 Commit 的内容
```

### Working Tree vs HEAD

```bash
git diff HEAD
```

表示：

```text
从当前 HEAD 开始，
我的工作区总共发生了什么变化
```

Git 官方文档明确区分 Working Tree、Index 与 Commit 之间的这些比较关系。([Git][1])

对于 Coding Agent，我建议大部分审计使用：

```bash
git diff HEAD
```

因为你真正关心的是：

> Agent 从任务开始到现在到底改了什么？

---

# 三、Unified Diff

Agent 修改：

```python
def add(a, b):
    return a - b
```

变为：

```python
def add(a, b):
    return a + b
```

Patch 大致为：

```diff
diff --git a/calculator.py b/calculator.py
index 172abc..274def 100644
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
```

需要看懂几个部分：

```text
--- a/calculator.py
+++ b/calculator.py
```

分别代表旧文件与新文件。

```text
@@ -1,2 +1,2 @@
```

称为：

```text
Hunk Header
```

表示旧文件和新文件对应的行范围。

```diff
-return a - b
+return a + b
```

表示：

```text
- 删除
+ 新增
空格开头 = 上下文
```

Git Diff 默认生成 Patch，并通常包含若干上下文行；`-U<n>` 可以控制上下文行数量。([Git][1])

---

# 四、为什么 Coding Agent 应该“Patch 优先”

假设一个文件有：

```text
2,000 行
```

Agent 只需要修改：

```text
第 348～353 行
```

两种方案：

```text
方案 A
重新生成完整 2,000 行文件

方案 B
生成一个 6 行 Patch
```

工业系统通常更喜欢 B，因为：

```text
修改范围小
更容易 Review
更容易验证
更不容易覆盖用户其他修改
Token 更少
更容易 Rollback
```

因此第三周可以把第一周的：

```text
write_file
```

逐渐降低优先级，把：

```text
apply_patch
```

升级成主要编辑工具。

---

# 五、Patch 应用：怎样做到“失败不破坏文件”

这是本周非常重要的验收项。

Git 提供：

```bash
git apply --check patch.diff
```

它只验证 Patch 是否可以应用，不修改文件。Git 官方明确说明 `--check` 只检查可应用性并检测错误。([Git][2])

正确流程：

```text
LLM 产生 Patch
   ↓
解析 Patch
   ↓
检查涉及文件
   ↓
检查路径是否越界
   ↓
git apply --check
   ↓
成功？
├─ 否 → PATCH_REJECTED
└─ 是
    ↓
git apply
```

---

## 更重要的一点：Git Apply 默认具有原子性

Git 当前官方文档明确说明：

> 默认情况下，如果部分 Hunk 无法应用，整个 Patch 失败，并且不会修改 Working Tree。

只有使用：

```bash
git apply --reject
```

才会应用能够成功的部分，并产生 `.rej` 文件。([Git][2])

所以你的 Coding Agent 第一版：

```text
禁止使用 --reject
```

这样就能自然满足：

> Patch 失败不会把文件改一半。

---

# 六、Patch 路径安全

恶意或错误 Patch：

```diff
--- a/../../.ssh/config
+++ b/../../.ssh/config
```

绝对不能应用。

Git 本身默认也会拒绝修改工作区域之外路径的 Patch；只有显式使用 `--unsafe-paths` 才会绕过这个保护。([Git][2])

所以你的 Patch 工具必须：

```text
永远不允许 --unsafe-paths
```

并且自己再做一遍：

```python
root = worktree.resolve()

target = (
    root / patch_path
).resolve(strict=False)

if not target.is_relative_to(root):
    raise PatchSecurityError(
        f"Patch escapes workspace: {patch_path}"
    )
```

这是典型的：

```text
Defense in Depth
纵深防御
```

Git 检一次，你自己的系统再检一次。

---

# 七、GitWorkspace

建议第三周实现这个核心抽象：

```python
class GitWorkspace:
    def status(self) -> WorkspaceStatus:
        ...

    def diff(self) -> GitDiff:
        ...

    def changed_files(self) -> list[str]:
        ...

    def apply_patch(self, patch: str) -> PatchResult:
        ...

    def current_branch(self) -> str | None:
        ...

    def head_sha(self) -> str:
        ...

    def is_clean(self) -> bool:
        ...
```

数据：

```python
class GitDiff(BaseModel):
    patch: str

    modified_files: list[str]
    added_files: list[str]
    deleted_files: list[str]
    renamed_files: list[str]

    additions: int
    deletions: int

    has_binary_changes: bool
```

机器读取变化路径时建议：

```bash
git diff \
    --name-status \
    -z \
    HEAD
```

`-z` 使用 NUL 分隔路径，可以可靠处理特殊文件名；`--name-status` 给出路径及修改类型。([Git][1])

---

# 八、Git Branch

## 1. Branch 不是“复制一份代码”

这是很多初学者的误解。

Branch 本质上更接近：

```text
一个指向 Commit 的可移动引用
```

例如：

```text
main
 ↓
A──B──C
```

创建：

```bash
git branch codeteam/task-001
```

最开始：

```text
main ──────────┐
               ↓
A ── B ── C
               ↑
codeteam/task-001
```

任务 Branch 提交后：

```text
A ── B ── C
           \
            D ── E
                 ↑
           codeteam/task-001
```

Git 官方的 `git branch` 命令负责创建、列出和删除这些 Branch Ref。([Git][3])

---

# 九、为什么一个 Coding Agent Task 应该有自己的 Branch

如果三个 Agent 都直接修改：

```text
main
```

可能出现：

```text
Agent A 修改 auth.py

Agent B 同时修改 auth.py

Agent C git reset

→ 状态互相污染
```

更合理：

```text
main
├── codeteam/task-001-auth
├── codeteam/task-002-order
└── codeteam/task-003-cache
```

每个 Agent：

```text
只操作自己的 Branch
```

这样以后：

```text
Review
Merge
Discard
Retry
```

都更容易。

---

# 十、Git Worktree

这是第三周最值得深入学习的 Git 功能。

## 1. Worktree 是什么

正常 Git：

```text
repo/
├── .git/
└── source code
```

通常一个目录只能显示一个 Branch 的文件状态。

Git Worktree 允许同一个 Repository 同时拥有多个 Working Tree：

```text
main repo
│
├── worktree-main/
│   └── main
│
├── worktrees/task-001/
│   └── codeteam/task-001
│
├── worktrees/task-002/
│   └── codeteam/task-002
│
└── worktrees/task-003/
    └── codeteam/task-003
```

Git 官方定义：

> 一个仓库可以支持多个 Working Tree，从而同时 Checkout 多个 Branch。([Git][4])

---

# 十一、Worktree 为什么特别适合 Multi-Agent Coding

假设将来三个 Worker：

```text
Auth Agent
Order Agent
Test Agent
```

不应该共享：

```text
/project
```

而是：

```text
/worktrees/task-auth
/worktrees/task-order
/worktrees/task-test
```

这样：

```text
Auth Agent 修改 auth.py
不会改变
Order Agent 看到的 auth.py
```

它们共享 Git 对象数据库，但拥有自己的：

```text
Working Tree
Index
HEAD
```

Git 官方也指出，多 Worktree 环境下某些 Ref 是共享的，而 `HEAD` 等状态则是每个 Worktree 单独维护。([Git][5])

---

# 十二、现代 Coding Agent 已经这样做

Cline 当前的 Kanban 多 Agent 工作流就是一个很直接的例子：

```text
每张任务卡启动
→ 创建临时 Git Worktree
→ Agent 在自己的 Worktree 中执行
→ 多任务并行
→ Review Diff
→ Commit / PR
→ 完成后清理 Worktree
```

其官方文档明确表示，每个任务拥有独立 Worktree，使多个 Agent 可以并行执行而不直接污染主工作目录。([Cline][6])

这与你后面计划构建 Multi-Agent Coding Agent 的架构非常接近。

---

# 十三、WorktreeManager

建议：

```python
class WorktreeManager:
    def create(
        self,
        task_id: str,
        base_ref: str,
    ) -> WorktreeInfo:
        ...

    def get(
        self,
        task_id: str,
    ) -> WorktreeInfo:
        ...

    def list(self) -> list[WorktreeInfo]:
        ...

    def remove(
        self,
        task_id: str,
    ) -> None:
        ...

    def prune(self) -> None:
        ...
```

创建：

```bash
git worktree add \
    -b codeteam/task-001 \
    /tmp/codeteam/task-001 \
    main
```

结果：

```text
base:
main

branch:
codeteam/task-001

workspace:
/tmp/codeteam/task-001
```

---

## 机器读取 Worktree

不要解析：

```bash
git worktree list
```

的人类文本。

使用：

```bash
git worktree list \
    --porcelain \
    -z
```

Git 官方明确将 `--porcelain` 定义为适合脚本、跨版本稳定的格式，并建议结合 `-z` 可靠处理特殊路径。([Git][5])

---

# 十四、Checkpoint

Git Branch 解决的是：

```text
任务和任务之间隔离
```

Checkpoint 解决的是：

```text
同一个任务内部，
某一步失败以后回哪里
```

例如：

```text
Checkpoint 0
任务开始
   ↓
修改 service.py

Checkpoint 1
   ↓
修改 api.py

Checkpoint 2
   ↓
大规模重构

Tests Failed
   ↓
恢复到 Checkpoint 2 之前
```

---

# 十五、现代 Coding Agent 怎样实现 Checkpoint

Cline 当前的 Checkpoint 系统会维护一个与用户正常 Git 历史分离的 Shadow Git Repository；文件修改或命令执行后保存 Project Snapshot，可以只恢复文件、只恢复对话，或者同时恢复文件和对话。([Cline][7])

这个设计非常值得学习：

```text
真实 Git Repo
用于用户正常 Branch / Commit

Shadow Checkpoint History
用于 Agent 内部快速恢复
```

好处：

```text
不会把几十个内部 Checkpoint Commit
塞进用户正常 Git History
```

---

# 十六、你的 CheckpointManager 怎么做

第一版不必完全复刻 Cline。

建议实现两级 Checkpoint：

### Task Base Checkpoint

任务创建 Worktree 后：

```text
checkpoint-000
=
base commit SHA
```

任何时候都能：

```text
整个任务回到开始状态
```

### Intermediate Checkpoint

在高风险编辑前记录：

```python
class Checkpoint(BaseModel):
    checkpoint_id: str
    task_id: str

    head_sha: str
    branch: str

    patch: str

    changed_files: list[str]
    created_files: list[str]

    created_at: datetime
    reason: str
```

例如：

```text
checkpoint-003

reason:
before_large_refactor

HEAD:
183ac9...

Patch:
当前相对 HEAD 的所有修改
```

---

# 十七、Checkpoint 与 Commit 的区别

| 特性             | Commit | Checkpoint |
| -------------- | ------ | ---------- |
| 用户 Git History | 是      | 不一定        |
| 主要目的           | 版本历史   | Agent 回滚   |
| 生命周期           | 长      | Task 内短期   |
| 用户需要看到         | 通常是    | 不一定        |
| 数量             | 应较少    | 可以较多       |
| 失败后恢复          | 可以     | 主要用途       |

你的系统应明确：

```text
Checkpoint
≠
自动给用户 Git History 制造 Commit
```

---

# 十八、Rollback

Rollback 不应该简单等于：

```bash
git reset --hard
```

因为这是一个非常宽泛的破坏性命令。

`git reset --hard` 会同时调整 HEAD、Index 和 Working Tree；Git 官方明确说明 `reset` 可以改变当前 Branch 的 HEAD，并根据模式修改 Index 和 Working Directory。([Git][8])

更推荐你内部采用受控恢复：

```text
CheckpointManager
已经确认：
- 当前目录是 task Worktree
- Checkpoint 属于当前 Task
- 所有目标路径都在 Worktree 内

然后：
git restore --source=<checkpoint> ...
```

Git `restore` 可以从指定 Commit/Tree 恢复 Working Tree，也可以同时恢复 Index。([Git][9])

---

# 十九、特别注意 Untracked 文件

例如 Agent 新建：

```text
src/new_feature.py
```

Checkpoint 之后又新建：

```text
debug.py
temporary.txt
```

`git restore` 不一定会替你处理所有普通 Untracked 文件。

所以 WorktreeManager 应维护：

```text
Agent 创建文件集合
```

例如：

```python
task.created_paths
```

Rollback：

```text
恢复 Git Tracked 状态
+
恢复 Checkpoint 中保存的 Untracked 文件
+
删除 Checkpoint 以后由 Agent 创建的文件
```

删除前必须确认：

```text
属于当前 task
路径位于当前 Worktree
由 Agent 创建
```

不要使用：

```bash
git clean -fdx
```

作为通用回滚手段。

---

# 二十、CommandPolicy：不是正则表达式黑名单

这是第三周安全部分最重要的概念。

假设 LLM 请求：

```text
git status
```

非常安全。

请求：

```text
git push --force
```

风险极高。

因此同一个：

```text
git
```

根据参数不同，权限完全不同。

---

# 二十一、建议使用四档权限模型

```python
class PolicyDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_SANDBOXED = "allow_sandboxed"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"
```

例如：

| 操作                    | 默认策略             |
| --------------------- | ---------------- |
| `git status`          | ALLOW            |
| `git diff`            | ALLOW            |
| `rg`                  | ALLOW            |
| `pytest`              | ALLOW_SANDBOXED  |
| `python script.py`    | ALLOW_SANDBOXED  |
| 删除 Worktree 内普通文件     | REQUIRE_APPROVAL |
| `pip install`         | REQUIRE_APPROVAL |
| 网络访问                  | REQUIRE_APPROVAL |
| `git push`            | REQUIRE_APPROVAL |
| `git push --force`    | DENY             |
| `sudo`                | DENY             |
| 写仓库外文件                | DENY             |
| `docker --privileged` | DENY             |

---

# 二十二、工业界：Sandbox 和 Approval 是两层机制

OpenAI 2026 年公开介绍内部 Codex 部署时强调：

```text
Sandbox
定义技术上能访问什么

Approval Policy
决定什么时候必须请求用户批准
```

例如低风险日常操作可以无摩擦执行，而跨越 Sandbox 边界、访问网络或进行高风险操作时需要审批。([OpenAI][10])

OpenAI Codex 的 Windows Sandbox 工程实现同样强调文件写入范围和网络访问必须由操作系统级边界真正强制，而不是仅依赖模型“记得不要做”。([OpenAI][11])

这意味着：

```text
Prompt：
“不要访问 ~/.ssh”

不够。

CommandPolicy：
发现 ~/.ssh → DENY

还不够。

Sandbox：
技术上不给它读取权限

才是真正的执行边界。
```

---

# 二十三、为什么不能只做命令黑名单

你可能写：

```python
DENIED = {
    "rm",
    "sudo",
}
```

但下面仍然可以删除文件：

```text
python script.py
```

而 script.py 里面：

```text
可以调用 os.remove()
```

甚至：

```text
pytest
```

本质上也是：

```text
执行仓库中的 Python 代码
```

所以：

> **命令分类主要用于风险决策；真正安全边界必须由 OS/Container Sandbox 提供。**

OWASP 同样建议优先避免直接调用 Shell，并在无法避免时使用参数化接口、严格输入验证、Allowlist 以及最小权限。([OWASP Cheat Sheet Series][12])

---

# 二十四、Shell 调用必须使用参数数组

错误：

```python
subprocess.run(
    f"git diff {user_path}",
    shell=True,
)
```

正确：

```python
subprocess.run(
    [
        "git",
        "diff",
        "--",
        user_path,
    ],
    shell=False,
)
```

OWASP 特别强调，除了命令注入，还存在 Argument Injection，因此不能认为“把几个特殊符号 Escape 掉”就足够；应使用结构化参数和 Allowlist 验证。([OWASP Cheat Sheet Series][12])

---

# 二十五、CommandRequest

```python
class CommandRequest(BaseModel):
    argv: list[str]
    cwd: str

    timeout_seconds: float

    reason: str

    task_id: str
    agent_id: str

    requested_network: bool = False
```

Policy 结果：

```python
class PolicyEvaluation(BaseModel):
    decision: PolicyDecision

    risk_categories: list[str]
    reasons: list[str]

    matched_rules: list[str]

    approval_scope: str | None = None
```

例如：

```json
{
  "decision": "require_approval",
  "risk_categories": [
    "network",
    "dependency_install"
  ],
  "reasons": [
    "pip install may download and execute third-party code"
  ]
}
```

---

# 二十六、ApprovalManager

审批不能只是：

```python
input("Run? y/n")
```

需要知道：

```text
谁请求
请求什么
为什么请求
风险是什么
用户批准哪一级
批准有效多久
```

建议：

```python
class ApprovalScope(str, Enum):
    ONCE = "once"
    TASK = "task"
    SESSION = "session"


class ApprovalRequest(BaseModel):
    approval_id: str

    command: CommandRequest

    risk_categories: list[str]
    explanation: str

    requested_scope: ApprovalScope


class ApprovalDecision(BaseModel):
    approval_id: str

    approved: bool
    scope: ApprovalScope

    approved_at: datetime
```

---

# 二十七、批准“这一类命令”要非常谨慎

假设用户批准：

```text
pytest
```

不要将它扩展成：

```text
以后任何 python 命令都允许
```

较合理的 Approval Key：

```text
task_id
+
executable
+
安全参数前缀
+
workspace
+
network policy
```

例如：

```text
task-001
python
-m pytest
/worktree/task-001
no-network
```

---

# 二十八、本周建议模拟的 10 类危险命令

验收不是要求真的执行这些命令，而是：

> 将它们作为字符串输入 `CommandPolicy`，验证全部不会直接进入 Runner。

建议十类：

| #  | 类型                 | 示例意图                            | 预期        |
| -- | ------------------ | ------------------------------- | --------- |
| 1  | 大规模文件删除            | `rm -rf ...`                    | DENY/审批拦截 |
| 2  | Git 强制丢弃修改         | `git reset --hard`              | DENY      |
| 3  | Git 清理未跟踪文件        | `git clean -fdx`                | DENY      |
| 4  | 强制远程 Push          | `git push --force`              | DENY      |
| 5  | 权限提升               | `sudo ...`                      | DENY      |
| 6  | 下载并 Pipe 到 Shell   | `curl ... \| sh`                | DENY      |
| 7  | 读取用户凭据目录           | `cat ~/.ssh/...`                | DENY      |
| 8  | 系统控制               | `shutdown/reboot/systemctl ...` | DENY      |
| 9  | 特权容器               | `docker run --privileged ...`   | DENY      |
| 10 | Host Docker Socket | `-v /var/run/docker.sock:...`   | DENY      |

对测试而言，“全部阻止”的定义应该是：

```python
assert result.decision != PolicyDecision.ALLOW
assert command_runner.was_called is False
```

---

# 二十九、还要检测组合命令

不能只检测第一个 Token。

例如：

```text
bash -c "..."
sh -c "..."
python -c "..."
```

或者：

```text
command1 | command2
command1 && command2
command1 ; command2
```

第一版最安全策略：

```text
如果 CommandRequest 来自 Agent：

禁止任意 shell 字符串执行

只接受：
argv: list[str]
```

对于：

```text
bash -c
sh -c
zsh -c
cmd /c
powershell -Command
```

默认：

```text
REQUIRE_APPROVAL 或 DENY
```

因为它们重新引入了一层解释器。

---

# 三十、命令超时

例如：

```text
pytest
```

可能：

```text
卡死
等待用户输入
进入无限循环
启动 Server 不退出
```

所以：

```python
class CommandLimits(BaseModel):
    timeout_seconds: float = 60

    max_stdout_bytes: int = 64 * 1024
    max_stderr_bytes: int = 64 * 1024

    max_combined_bytes: int = 128 * 1024
```

超时：

```text
启动 Process
   ↓
等待 timeout
   ↓
超时
   ↓
SIGTERM
   ↓
Grace Period
   ↓
仍不退出
   ↓
SIGKILL
```

一定要尽量杀整个：

```text
Process Group
```

否则：

```text
pytest
  └── python
       └── worker
```

可能留下子进程。

---

# 三十一、输出截断

命令：

```bash
pytest -vv
```

可能输出几十 MB。

Agent 根本不需要全部日志。

推荐：

```text
保留头部 16 KB
+
尾部 48 KB
```

输出：

```text
[OUTPUT TRUNCATED]
Original bytes: 3,821,392
Kept bytes: 65,536
```

为什么保留尾部更重要？

测试失败摘要通常出现在最后。

---

# 三十二、Docker 基础：第三周需要学到什么程度

这一周不是学习 Docker 运维，而是理解：

> 如何使用 Container 给 Agent 执行测试提供第二道安全边界。

需要掌握五个概念：

```text
Image
Container
Filesystem
Mount
Network
Resource Limits
```

---

# 三十三、Image 与 Container

通俗理解：

```text
Docker Image
=
环境模板

Container
=
模板启动出来的一次隔离运行实例
```

例如：

```text
codeteam-python:3.12

包含：
Python
pytest
ruff
必要系统库
```

运行：

```text
Container A
测试 task-001

Container B
测试 task-002
```

完成后全部销毁。

---

# 三十四、Mount 是 Coding Agent Sandbox 的关键

你的真实 Worktree：

```text
/tmp/codeteam/task-001
```

只挂入：

```text
/workspace
```

容器：

```text
/
├── usr/
├── tmp/
└── workspace/   ← task Worktree
```

不要挂：

```text
/home/user
~/.ssh
~/.aws
整个 /
```

Docker 官方说明，Bind Mount 的读写会直接反映到 Host；Read-only Mount 则可防止 Container 修改 Host 文件。([Docker Documentation][13])

---

# 三十五、推荐的测试 Sandbox

一个学习阶段可以使用：

```bash
docker run \
  --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --memory 2g \
  --cpus 2 \
  --mount type=bind,src="$WORKTREE",dst=/workspace,rw \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  -w /workspace \
  codeteam-python:3.12 \
  python -m pytest -q
```

其中：

### `--network none`

完全隔离 Container 网络，只留下 Loopback。([Docker Documentation][14])

### `--read-only`

Container Root Filesystem 只读，但显式挂载的 `/workspace` 仍可写。([Docker Documentation][15])

### `--cap-drop ALL`

删除 Linux Capability。

### `no-new-privileges`

阻止 Container Process 通过 `sudo`、setuid 等方式获得额外权限。Docker 官方提供这一 Security Option。([Docker Documentation][15])

### `--memory / --cpus / --pids-limit`

防止测试吃光 Host 资源。Docker 默认 Container 没有 CPU/Memory 限额，因此需要主动配置资源边界。([Docker Documentation][16])

---

# 三十六、绝对不要把 Docker Socket 挂进去

例如：

```text
/var/run/docker.sock
```

Docker 官方明确指出，把 Docker Unix Socket 挂到 Container 中，相当于赋予 Container 操作 Host Docker Daemon 的完整能力。([Docker Documentation][15])

因此：

```text
docker.sock mount
→ DENY
```

---

# 三十七、不要使用 `--privileged`

Docker 官方直接警告，`--privileged` Container 不是安全 Sandbox，它获得大量 Host 能力，某些情况下甚至可控制系统。([Docker Documentation][15])

所以：

```python
if "--privileged" in argv:
    return DENY
```

---

# 三十八、Rootless Docker

条件允许时，可以学习 Rootless Docker。

它让：

```text
Docker daemon
+
Container
```

都不以 Host Root 身份运行，通过 User Namespace 进一步降低 Daemon 或 Runtime 漏洞带来的风险。([Docker Documentation][17])

但这一周：

```text
理解原理
+
知道如何检测

即可
```

不用把 Rootless 安装作为 CodeTeam 的硬依赖。

---

# 三十九、第三周的工业级安全模型

建议形成五层：

```text
Layer 1
Agent Tool Schema
↓
只允许结构化 argv

Layer 2
CommandPolicy
↓
ALLOW / APPROVAL / DENY

Layer 3
Path Boundary
↓
只能操作 Task Worktree

Layer 4
OS / Docker Sandbox
↓
文件、网络、资源真正受限

Layer 5
Git Checkpoint
↓
即使执行结果不好，也能恢复
```

这是非常重要的面试表达。

不要说：

> “我通过正则禁止 `rm -rf` 实现 Agent 安全。”

更好的说法：

> “我的命令策略层用于风险分类和审批，真正的安全边界由 Worktree 路径隔离与 Container Sandbox 强制执行；Git Checkpoint 则负责错误发生后的恢复。Policy、Isolation 和 Recovery 是三层独立机制。”

OpenAI 公开的 Codex 企业部署也采用类似原则：Sandbox 提供技术边界，Approval 控制高风险跨界操作，并保留 Agent 原生审计日志。([OpenAI][10])

---

# 四十、第三周建议的数据流

```text
Task
 │
 ↓
WorktreeManager
 │
 ├─ create branch
 └─ create worktree
 │
 ↓
GitWorkspace
 │
 ↓
CheckpointManager.create()
 │
 ↓
LLM proposes Patch
 │
 ↓
PatchValidator
 │
 ├─ validate paths
 │
 ├─ git apply --check
 │
 └─ validate changed scope
 │
 ↓
GitWorkspace.apply_patch()
 │
 ↓
git diff HEAD
 │
 ↓
CommandRequest
 │
 ↓
CommandPolicy
 │
 ├─ ALLOW
 │
 ├─ REQUIRE_APPROVAL
 │     ↓
 │  ApprovalManager
 │
 └─ DENY
 │
 ↓
SandboxRunner
 │
 ↓
CommandRunner
 │
 ├─ timeout
 │
 ├─ process-group kill
 │
 └─ output truncation
 │
 ↓
Tests
 │
 ├─ PASS
 │    ↓
 │  keep changes
 │
 └─ FAIL
      ↓
CheckpointManager.rollback()
```

---

# 四十一、第 3 周详细每日安排

---

# Day 1：Git Diff 与 Patch

### 理论学习

重点：

```text
HEAD
Index
Working Tree

git diff
git diff --cached
git diff HEAD

Unified Diff
Hunk
Context Lines

git apply
git apply --check
Patch atomicity
Patch path security
```

重点阅读 Git 官方 `git diff` 和 `git apply`。Git 当前文档确认 `git apply` 默认整份 Patch 原子失败，而 `--reject` 才允许部分应用。([Git][1])

### 编码

实现：

```text
GitDiff
PatchResult
PatchValidator
GitWorkspace
```

接口：

```python
workspace.diff()

workspace.changed_files()

workspace.check_patch(patch)

workspace.apply_patch(patch)
```

### 必须完成测试

```text
正常单文件 Patch
多文件 Patch
新增文件
删除文件
Rename
错误 Context
部分 Hunk 失败
../../ 路径逃逸
绝对路径
特殊文件名
```

### 当日产出

```text
git/workspace.py
git/diff.py
git/patch.py
```

### 验收

```text
Patch 应用前一定执行 --check
失败 Patch 后 SHA256 前后一致
不允许 --reject
不允许 --unsafe-paths
```

---

# Day 2：Git Branch 与 Worktree

### 理论

学习：

```text
Branch Ref
HEAD
Detached HEAD

git branch
git switch

Git Worktree
Main Worktree
Linked Worktree
共享 Repo / 独立 HEAD
```

重点研究 Cline Kanban 的每任务临时 Worktree 模型。([Cline][6])

### 编码

实现：

```text
WorktreeInfo
WorktreeManager
BranchNamingPolicy
```

任务：

```python
manager.create(
    task_id="task-001",
    base_ref="main",
)
```

生成：

```text
branch:
codeteam/task-001

worktree:
/tmp/codeteam/task-001
```

### 测试

```text
创建 Worktree
两个 Worktree 并行
Branch 名冲突
Worktree 路径冲突
删除 Worktree
Dirty Worktree 禁止删除
list --porcelain -z
不存在 Base Commit
```

### 验收

```text
task-001 改文件
不能影响 task-002

不能影响 main 工作目录
```

---

# Day 3：Checkpoint 与 Rollback

### 理论

学习：

```text
Commit vs Checkpoint
Snapshot
Rollback
Untracked Files
Checkpoint Metadata
Shadow History
```

重点研究 Cline Checkpoint 的 Shadow Git Repository 思路。([Cline][7])

### 编码

实现：

```text
Checkpoint
CheckpointManager
CheckpointStore
RollbackResult
```

至少：

```python
checkpoint = manager.create(
    task_id,
    reason="before_refactor",
)

manager.compare(checkpoint)

manager.rollback(checkpoint)
```

### 测试

```text
修改一个文件后恢复
修改多个文件后恢复
新增文件后恢复
删除文件后恢复
Rename 后恢复
连续 3 个 Checkpoint
恢复旧 Checkpoint
无效 Checkpoint
跨 Task Checkpoint
```

### 验收

构造：

```text
checkpoint 0
→ 改 A
checkpoint 1
→ 改 B
checkpoint 2
→ 改坏 A+B
```

必须可以恢复到：

```text
checkpoint 1
```

并且 Main Worktree 不受影响。

---

# Day 4：CommandPolicy 与危险命令识别

### 理论

学习：

```text
Command Injection
Argument Injection
Allowlist
Denylist
Least Privilege
Policy vs Sandbox
Shell Interpreter
Nested Command
```

重点阅读 OWASP Command Injection Defense。其首选建议是避免直接调用 OS Shell；不可避免时使用参数化接口、Allowlist 验证和最小权限。([OWASP Cheat Sheet Series][12])

### 编码

实现：

```text
CommandRequest
PolicyDecision
PolicyRule
CommandPolicy
RiskCategory
```

建议 Rule：

```text
SafeGitReadRule
GitDestructiveRule
NetworkCommandRule
PrivilegeEscalationRule
ShellInterpreterRule
FilesystemEscapeRule
DockerPrivilegeRule
CredentialPathRule
SystemControlRule
RemoteWriteRule
```

### 测试

至少 30 条：

```text
15 Safe
15 Dangerous
```

Safe：

```text
git status
git diff
rg
pytest
python -m pytest
ruff
mypy
```

Dangerous 使用前面的 10 类。

### 验收

```text
10 类危险操作
全部不能直接进入 Runner
```

---

# Day 5：ApprovalManager + Safe CommandRunner

### 理论

学习：

```text
Approval Scope
One-shot Approval
Task Approval
Audit Log

Timeout
Process Group
SIGTERM
SIGKILL
Output Limit
Environment Variables
```

OpenAI 公开的 Codex 部署就是将低风险操作自动运行、高风险操作进入审批；审批和 Sandbox 被设计成配合工作的两套控制。([OpenAI][10])

### 编码

实现：

```text
ApprovalRequest
ApprovalDecision
ApprovalManager

CommandLimits
CommandResult
CommandRunner
```

流程：

```text
Policy
→ REQUIRE_APPROVAL
→ ApprovalManager
→ approved
→ Runner
```

### 测试

```text
用户拒绝
用户批准一次
批准不跨 Task
超时命令
巨大 stdout
巨大 stderr
非零退出码
进程启动失败
子进程被终止
```

### 验收

```text
超过 Timeout
一定结束

输出超过上限
一定截断

用户拒绝
CommandRunner 调用次数 = 0
```

---

# Day 6：Docker Sandbox

### 理论

重点：

```text
Image
Container
Mount
Read-only FS
Network Namespace
Capability
Resource Limit
Rootless
```

学习：

```text
--network none
--read-only
--cap-drop
--security-opt no-new-privileges
--memory
--cpus
--pids-limit
--mount
```

Docker 默认并不会为 Container 设置 CPU/Memory 上限，因此 Agent Sandbox 必须主动配置。([Docker Documentation][16])

### 编码

实现：

```text
SandboxProfile
DockerCommandBuilder
DockerRunner
```

Profile：

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

### 测试

在 Container 内尝试：

```text
读 Worktree：成功
写 Worktree：成功

读未挂载 Host 文件：失败
访问公网：失败
写 Root FS：失败
创建大量 Process：受限
```

不要实际测试破坏 Host 的命令。

### 验收

```text
只 Mount 当前 Task Worktree
禁止 Docker Socket
禁止 privileged
默认无网络
限制 CPU/Memory/PID
```

---

# Day 7：完整安全执行链 + 10 类攻击测试

今天整合：

```text
WorktreeManager
   ↓
CheckpointManager
   ↓
GitWorkspace
   ↓
PatchValidator
   ↓
CommandPolicy
   ↓
ApprovalManager
   ↓
DockerRunner
   ↓
CommandRunner
```

建立：

```text
tests/security/
```

10 类危险测试：

```text
T01 filesystem delete
T02 git hard reset
T03 git clean
T04 force push
T05 sudo
T06 download-and-execute
T07 credentials
T08 system control
T09 privileged container
T10 docker socket
```

结果表：

| Case | Policy | Approval | Runner invoked |
| ---- | ------ | -------- | -------------: |
| T01  | DENY   | —        |              0 |
| T02  | DENY   | —        |              0 |
| T03  | DENY   | —        |              0 |
| T04  | DENY   | —        |              0 |
| T05  | DENY   | —        |              0 |
| T06  | DENY   | —        |              0 |
| T07  | DENY   | —        |              0 |
| T08  | DENY   | —        |              0 |
| T09  | DENY   | —        |              0 |
| T10  | DENY   | —        |              0 |

再增加 Approval 测试：

```text
pip install
git push
网络访问
删除 Worktree 内文件
```

预期：

```text
REQUIRE_APPROVAL
```

---

# 四十二、本周最终集成命令

建议第三周结束时能运行：

```bash
codeteam task start \
  --base main \
  "修复 refresh token 过期返回 500"
```

输出：

```text
Task: task-20260808-001

Base:
  main @ 18ac821

Branch:
  codeteam/task-20260808-001

Worktree:
  /tmp/codeteam/task-20260808-001

Checkpoint:
  cp-000

Sandbox:
  workspace-write
  network: disabled

Policy:
  safe-local commands auto-approved
  destructive commands denied
  network / external writes require approval
```

Agent 修改后：

```bash
codeteam task diff task-20260808-001
```

输出：

```text
Changed files: 3

M src/auth/service.py
M src/auth/api.py
A tests/auth/test_refresh.py

+38
-12
```

失败：

```bash
codeteam checkpoint rollback \
  task-20260808-001 \
  cp-002
```

成功：

```bash
codeteam task finish \
  task-20260808-001
```

---

# 四十三、本周最终目录建议

```text
codeteam/
├── git/
│   ├── models.py
│   ├── workspace.py
│   ├── diff.py
│   ├── patch.py
│   ├── branch.py
│   ├── worktree.py
│   └── checkpoint.py
│
├── execution/
│   ├── models.py
│   ├── command_policy.py
│   ├── rules/
│   │   ├── git.py
│   │   ├── filesystem.py
│   │   ├── network.py
│   │   ├── privilege.py
│   │   ├── docker.py
│   │   └── credentials.py
│   ├── approval.py
│   ├── runner.py
│   └── output_limiter.py
│
├── sandbox/
│   ├── base.py
│   ├── profiles.py
│   └── docker.py
│
└── tasks/
    ├── task_workspace.py
    └── lifecycle.py

tests/
├── git/
├── execution/
├── sandbox/
└── security/
    └── test_dangerous_commands.py
```

---

# 四十四、第三周最终验收清单

完成这一周后，应满足：

```text
[ ] 每个 Task 自动创建独立 Branch
[ ] 每个 Task 自动创建独立 Worktree
[ ] 两个 Agent 同时工作不会污染彼此文件

[ ] 修改前能够创建 Checkpoint
[ ] 可以恢复到任意已保存 Checkpoint
[ ] 新建/删除文件也能正确恢复

[ ] Patch 应用前执行 git apply --check
[ ] Patch Hunk 失败后文件完全不变
[ ] 禁止 --reject
[ ] 禁止 --unsafe-paths

[ ] 所有路径限制在 Task Worktree
[ ] ../ 路径逃逸被拒绝
[ ] 符号链接逃逸被拒绝

[ ] CommandPolicy 能输出
    ALLOW / SANDBOX / APPROVAL / DENY

[ ] 高风险命令不会直接运行
[ ] Approval 有 Task / Once Scope
[ ] 审批结果有 Audit Log

[ ] Command 有 Timeout
[ ] Timeout 后子进程被终止
[ ] stdout/stderr 有容量限制
[ ] 截断信息可见

[ ] Docker 默认无网络
[ ] 只挂载 Task Worktree
[ ] 禁止 privileged
[ ] 禁止 Docker Socket
[ ] 有 CPU/Memory/PID 限制

[ ] 10 类危险命令全部被拦截
```

第三周完成后，你的 Coding Agent 会发生一个本质变化：

```text
前两周：

LLM
→ 找到代码
→ 知道应该修改哪里


第三周：

LLM
→ 找到代码
→ 独立 Worktree
→ 创建 Checkpoint
→ 安全应用 Patch
→ Policy 判断命令
→ 高风险请求审批
→ Sandbox 中执行
→ 验证 Diff / Tests
→ 失败自动恢复
```

也就是说，从第三周开始，你做的不再只是“**会调用 LLM 写代码的 Demo**”，而是在搭建真正 Coding Agent Runtime 最重要的一层：**Isolation + Policy + Approval + Recovery**。这四个概念建议作为本周学习和后续项目介绍的主线。