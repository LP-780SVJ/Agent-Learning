# 第 3 周 Day 3：Checkpoint 与 Rollback

今天开始进入 Agent Runtime 里非常重要的 **Recovery / State Management** 层。

Day 1 的 Patch 解决：

```text
Agent 怎么安全地改代码？
```

Day 2 的 Worktree 解决：

```text
多个 Task 怎么互相隔离？
```

今天的 Checkpoint 解决：

```text
一个 Task 自己改坏以后，
怎么回到几分钟前的“已知正确状态”？
```

三天连起来实际上形成：

```text
Task Isolation
        ↓
Git Worktree
        ↓
Safe Editing
        ↓
Patch Runtime
        ↓
State Snapshot
        ↓
Checkpoint
        ↓
Failure
        ↓
Rollback
        ↓
继续执行
```

这已经不是普通 Git 教程了，而是在实现 Coding Agent Runtime 的 **Fault Recovery Primitive**。

---

# 1. Capability Mapping：今天证明什么能力

今天最主要映射到：

| Agent 能力            | Day 3 体现                        |
| ------------------- | ------------------------------- |
| Agent Runtime       | Task 状态保存、恢复、生命周期               |
| Workspace & Sandbox | Workspace Snapshot / Rollback   |
| Tool Runtime        | 修改失败后的恢复能力                      |
| Observability       | Checkpoint Metadata、恢复记录        |
| Reliability         | Agent 做错后不必整个 Task 重启           |
| Multi-Agent 基础      | 每个 Worker 拥有独立 Checkpoint Chain |

最终希望得到这样的系统：

```text
Task-001 Worktree
        │
        ├── cp-000
        │      ↓
        ├── Agent 修改 A
        │
        ├── cp-001
        │      ↓
        ├── Agent 修改 B
        │
        ├── cp-002
        │      ↓
        └── Agent 大规模重构
               ↓
            Tests FAIL
               ↓
      rollback(cp-001)
               ↓
      恢复到 A 已修改
      B 尚未修改的状态
```

这就是 Agent Runtime 中的：

> **recoverable execution（可恢复执行）**

---

# 2. 为什么 Coding Agent 特别需要 Checkpoint

普通开发者写代码时，会主动：

```text
改一点
→ 看一下
→ 跑测试
→ 再改
```

Agent 则可能一次连续执行：

```text
read_file
→ apply_patch
→ apply_patch
→ create_file
→ rename_file
→ run_test
→ 修改配置
→ 再运行命令
```

如果第 8 步才发现：

```text
前面第 4 步设计方向就错了
```

没有 Checkpoint 时，Runtime 只能尝试：

```text
让模型自己“记住刚才改了什么”
→ 再生成反向 Patch
```

这非常脆弱。

因为：

```text
inverse patch
≠
guaranteed previous state
```

Checkpoint 则把问题从：

```text
“请模型想办法撤销刚才的修改”
```

变成：

```text
“Runtime 把 Workspace 恢复到 Snapshot X”
```

这是一个重要的 Agent Harness 思想：

> **不要让模型负责恢复一致性。恢复应该是 Runtime 的确定性能力。**

---

# 3. Commit 和 Checkpoint 到底有什么区别

这是今天第一件必须彻底理解的事情。

两者表面上都在：

```text
保存代码状态
```

但它们服务完全不同的生命周期。

|                     | Commit   | Checkpoint          |
| ------------------- | -------- | ------------------- |
| 核心目的                | 正式版本历史   | Runtime 故障恢复        |
| 谁使用                 | 人、团队、CI  | Agent Runtime       |
| 是否进入正式 Git History  | 是        | 不应该                 |
| 创建频率                | 较低       | 可以很高                |
| 内容                  | 有意义的软件变更 | 任意中间状态              |
| 是否适合自动产生            | 谨慎       | 非常适合                |
| 生命周期                | 长期       | 通常 Task 生命周期        |
| 是否要求代码正确            | 通常应该     | 不要求                 |
| 是否需要 Commit Message | 有业务意义    | 只需 Runtime Metadata |
| 是否应该包含临时状态          | 通常不应该    | 可以                  |

例如 Agent 的内部过程：

```text
cp-001
修改一个函数

cp-002
又修改一个函数

cp-003
测试失败

cp-004
重试另一个方案

cp-005
最终测试通过
```

如果全都做成用户 Git Commit：

```text
commit: agent intermediate state 1
commit: agent intermediate state 2
commit: agent retry 1
commit: agent retry 2
...
```

用户 Git History 会变得非常混乱。

Cline 正是因此采用独立的 **Shadow Git Repository**：Checkpoint 状态记录在影子 Git 仓库，而项目正常 Git History 不被这些内部 Snapshot 污染。其官方文档还明确表示，Checkpoint 可以包含未被项目 Git 跟踪的文件，并可跨编辑器会话保存。([Cline][1])

所以今天必须形成：

```text
Commit
=
Software History


Checkpoint
=
Agent Execution History
```

---

# 4. Snapshot 到底是什么

Snapshot 经常被误解成：

> “复制整个项目目录。”

实际上不是。

Snapshot 是一个**逻辑概念**：

> 在某一个时刻，这个 Workspace 应该是什么状态。

例如：

```text
Checkpoint cp-001

src/a.py       → content hash A1
src/b.py       → content hash B1
tests/test.py  → content hash T1
config.toml    → content hash C1
```

这就是一个 Snapshot。

它不要求物理磁盘真的复制：

```text
checkpoint-001/
    整个项目

checkpoint-002/
    整个项目

checkpoint-003/
    整个项目
```

可以使用 Content Addressing：

```text
Blob A1
Blob B1
Blob C1

Snapshot 001
→ A1 + B1 + C1

Snapshot 002
→ A2 + B1 + C1
```

于是只新增：

```text
A2
```

旧的：

```text
B1
C1
```

仍然复用。

Git 本身就是基于内容寻址的对象模型，因此特别适合用来实现这种高频 Snapshot。

所以：

> **Logical Full Snapshot 不等于 Physical Full Copy。**

这是今天很值得理解的系统设计概念。

---

# 5. Cline 的工业方案：Shadow Git Repository

Cline 是今天最值得研究的参考实现。

Cline 官方目前描述的行为是：每次 Cline 修改文件或执行命令后，会把当前文件状态提交到一个与用户项目 Git History 分离的 Shadow Git Repository。这样用户正常 Git History 不会出现 Agent 内部 Checkpoint，同时可以恢复到任务中的任意 Snapshot。([Cline][1])

可以把它理解成：

```text
用户真正的 Git
────────────────────────────

main
 ↓
 C ─────────────── D

这是：
正式软件历史



Cline Shadow Git
────────────────────────────

S0 → S1 → S2 → S3 → S4

这是：
Agent Runtime 状态历史
```

两套历史服务两个目的。

---

# 6. Cline 为什么不是简单调用 `git commit`

因为如果直接：

```bash
git add -A
git commit
```

那么 Runtime Checkpoint：

```text
cp1
cp2
cp3
```

就会真正进入：

```text
codeteam/task-001
```

Branch。

Shadow Repo 则可以做到：

```text
Task Worktree
      │
      │ filesystem state
      ▼
Shadow Git
      │
      ├── snapshot 1
      ├── snapshot 2
      ├── snapshot 3
      └── snapshot 4
```

用户真实：

```text
.git
```

历史不需要记录这些内部步骤。Cline 官方把“Shadow Repo 与用户 Git History 分离”明确列为这个设计的主要性质之一。([Cline][1])

---

# 7. Cline 不仅能够 Restore Files

Cline 的设计实际上说明了一个更深的 Agent Runtime 问题：

```text
Agent State
≠
Workspace State
```

它目前提供三种恢复语义：

| 操作                   | Workspace | Conversation |
| -------------------- | --------- | ------------ |
| Restore Files        | 回滚        | 保留           |
| Restore Task Only    | 保留        | 回滚           |
| Restore Files & Task | 回滚        | 回滚           |

([Cline][1])

这非常重要。

因为 Coding Agent 实际存在两套时间线：

```text
Conversation Timeline

U0
↓
A0
↓
Tool
↓
A1
↓
Tool
↓
A2


Workspace Timeline

S0
↓
S1
↓
S2
↓
S3
```

最终成熟 Runtime 应建立：

```text
Conversation State
        ↕
Checkpoint ID
        ↕
Workspace State
```

---

# 8. Claude Code 也已经采用 Checkpoint / Rewind

Anthropic 当前 Claude Code 也提供 Checkpointing。官方文档显示，每个用户 Prompt 会建立新的 Checkpoint，并为会话保存最近 100 个 Checkpoint 的文件 Snapshot；这些 Checkpoint 随会话保存，所以 Resume 后仍可使用 `/rewind`。Claude Code 的配置文档也明确说明，它会在文件编辑前创建文件 Snapshot，以供 Rewind 恢复。([Claude Platform Docs][2])

它的思路更接近：

```text
Prompt 0
 ↓
Checkpoint 0
 ↓
Agent edits

Prompt 1
 ↓
Checkpoint 1
 ↓
Agent edits

Prompt 2
 ↓
Checkpoint 2
```

然后：

```text
/rewind
      ↓
选择 Checkpoint
      ↓
恢复 Conversation / Code
```

Anthropic 还建议当 Agent 走错方向时及时停止，并通过 `/rewind` 恢复到之前的代码和 Conversation 状态。([Claude Platform Docs][3])

---

# 9. Cline 与 Claude Code 给你的一个重要启示

两者实现细节不同，但共同说明：

```text
Coding Agent
不能只有：

forward execution


还必须有：

recoverable execution
```

也就是：

```text
Execute
→ Observe
→ Detect Failure
→ Restore
→ Retry
```

以后你的 Agent Loop 甚至可以演化成：

```text
checkpoint
    ↓
attempt
    ↓
tests
    ↓
PASS ──────────→ continue

FAIL
 ↓
rollback
 ↓
choose another strategy
```

这就开始接近真正的：

> Agent Runtime，而不只是 LLM + Tools。

---

# 10. OpenAI Codex：Isolation 和 Recovery 是不同问题

OpenAI 当前 Codex App 使用内置 Worktree，让多个 Agent 可以在同一个 Repository 上并行工作而不触碰彼此或用户本地 Git 状态。([OpenAI][4])

这正好和你前两天的架构对应：

```text
Worktree
=
Task Isolation
```

但：

```text
Worktree
≠
Checkpoint
```

因为 Worktree 能保证：

```text
Agent A
不会污染 Agent B
```

但不能自动解决：

```text
Agent A
自己把自己的 Worktree 改坏了
```

所以完整 Runtime 是：

```text
Worktree
解决：
cross-task isolation

Checkpoint
解决：
intra-task recovery
```

这个区别面试时非常重要。

---

# 11. 为什么不直接使用 `git stash`

这是第一个应该认真比较的替代方案。

Git Stash 本身就是：

> 保存 Working Tree 和 Index 的当前变化，然后允许之后重新应用。

Git 现在还支持：

```bash
git stash push -u
```

把 Untracked 文件也纳入 Stash。([Git][5])

看起来非常像 Checkpoint。

但它有几个问题。

首先：

```text
stash
```

主要是 Git 用户临时切换工作的工具，不是专门为 Agent Task Runtime 设计的。

其次，当 Workspace 已发生较大变化时重新：

```bash
git stash apply
```

可能发生冲突；Git 官方明确说明 Stash Apply/Pop 可以因冲突失败。([Git][5])

第三，你希望未来：

```text
Task 001
Task 002
Task 003
```

分别维护清晰的：

```text
Checkpoint Timeline
Metadata
Tool Event
Reason
Recovery History
```

单纯依赖：

```text
stash@{0}
stash@{1}
```

并不是理想的 Agent Runtime abstraction。

因此今天应把：

```text
git stash
```

视为一个值得 Benchmark/Design Comparison 的替代方案，而不是最终 API。

---

# 12. 为什么不直接复制整个目录

第二种最朴素方案：

```text
checkpoint 1
→ shutil.copytree(workspace)

checkpoint 2
→ shutil.copytree(workspace)

checkpoint 3
→ shutil.copytree(workspace)
```

它最大的优点是：

```text
非常容易理解
```

而且 Restore 也简单：

```text
删当前目录
→ Copy Snapshot 回去
```

但大型项目里：

```text
1 GB repo
×
20 checkpoints

≈ 20 GB
```

即使很多文件根本没变化，也不断复制。

所以它非常适合作为你后面 Benchmark 的：

```text
Naive Baseline
```

但不适合作为最终工程方案。

---

# 13. 为什么 Shadow Git 很适合你的 CodeTeam

结合你 Day 2 已经实现的 Task Worktree，我建议第一版采用：

```text
每个 Task
拥有：

1 个 Task Worktree
+
1 个独立 Shadow Git Repository
+
1 条 Checkpoint Metadata Timeline
```

结构概念上：

```text
Main Repository
│
├── Main Worktree
│
└── Git Objects / Branches
│
└─────────────────────────────────

Task Runtime State
│
├── task-001
│   ├── Worktree
│   │   └── /tmp/.../task-001
│   │
│   ├── Shadow Git
│   │   ├── cp-000
│   │   ├── cp-001
│   │   └── cp-002
│   │
│   └── Metadata
│       ├── cp-000.json
│       ├── cp-001.json
│       └── cp-002.json
│
└── task-002
    ├── Worktree
    ├── Shadow Git
    └── Metadata
```

这里有一个关键设计：

> **Shadow Repository 不放到 Task Worktree 内部。**

否则很容易：

```text
Checkpoint
snapshot Shadow Repo
    ↓
Shadow Repo 又发生变化
    ↓
再次 snapshot
```

甚至产生递归或污染。

---

# 14. Cline 真实 Failure Case 给你的设计教训

Cline 官方文档已经说明，大 Repository 中频繁创建 Checkpoint 可能产生明显 Storage 和性能开销。Cline 在 Multi-root Workspace 中甚至直接禁用了 Checkpoint，因为要协调多个独立 Git History 会带来额外复杂性。([Cline][1])

而 Cline 官方 GitHub Repository 中还出现过一些很有学习价值的故障报告，例如 Shadow Repo `index.lock` 残留导致 Checkpoint 无法继续创建，以及嵌套 Git / `.git_disabled` 处理出现问题。它们是用户/QA issue，不代表所有版本都存在这些问题，但很好地展示了 Shadow Git 实现必须面对的故障类型。([GitHub][6])

因此 CodeTeam 第一版我建议定一个非常重要的不变量：

```text
Checkpoint System

永远不能：

rename 用户 .git
modify 用户 .git
temporarily disable 用户 .git
```

你的 Shadow Repo：

```text
必须完全位于 Runtime State Directory。
```

---

# 15. Untracked Files 为什么是今天最容易漏掉的问题

假设：

```text
checkpoint 0
```

时：

```text
src/service.py
tests/test_service.py
```

之后 Agent 创建：

```text
debug.py
```

它是：

```text
Untracked
```

然后：

```text
rollback(checkpoint0)
```

如果只执行：

```bash
git restore
```

针对项目 Git Tracking State，

那么：

```text
debug.py
```

可能仍然留着。

结果：

```text
“Rollback 成功”
```

实际上：

```text
Workspace ≠ Checkpoint0
```

这叫：

> **Snapshot Fidelity Failure**

所以 Checkpoint 必须明确：

```text
Snapshot Scope
到底包括哪些文件？
```

---

# 16. 我建议 CodeTeam 的 Snapshot Scope

第一版采用：

```text
Tracked Files
+
Untracked Non-Ignored Files
```

不默认 Snapshot：

```text
node_modules/
.venv/
build/
dist/
cache/
.git/
Shadow Repo
```

也就是说：

```text
.gitignore
+
Runtime Exclusion Policy
```

共同决定 Snapshot 范围。

为什么不把：

```text
node_modules
```

也保存？

因为 Checkpoint 主要恢复：

```text
Agent 产生的源码状态
```

而不是：

```text
整个执行机器磁盘状态
```

---

# 17. 一个非常重要的契约：Ignored File 怎么办

例如：

```text
logs/debug.log
node_modules/
.cache/
```

如果被排除于 Snapshot Scope，

那么：

```text
rollback()
```

之后它们：

```text
不保证恢复
```

这不是 Bug。

它应该成为明确契约：

```text
Managed Workspace State
≠
Entire Filesystem State
```

未来 Docker Sandbox 可以负责：

```text
完整执行环境可复现性
```

Checkpoint 只负责：

```text
Workspace Source State Recovery
```

这个边界非常重要。

---

# 18. Checkpoint Metadata 是什么

不能只有：

```text
cp-001
→ Git SHA
```

Agent Runtime 还需要知道：

```text
这是哪个 Task？
为什么创建？
什么时候创建？
当时实际项目 HEAD 是什么？
它前一个 Checkpoint 是什么？
是不是某次 Rollback 自动生成的？
```

所以今天需要：

```python
Checkpoint
```

作为结构化 Runtime State。

建议模型大致包含：

```python
class Checkpoint(BaseModel):
    checkpoint_id: str
    task_id: str

    sequence: int
    reason: str

    created_at: datetime

    shadow_commit_sha: str
    shadow_tree_sha: str

    workspace_head_sha: str

    parent_checkpoint_id: str | None

    file_count: int

    restored_from: str | None = None
```

这里我先解释几个字段。

---

# 19. `shadow_commit_sha`

表示：

```text
Shadow Git 中
这个 Checkpoint 对应哪个 Commit。
```

例如：

```text
cp-001
↓
5fc208abc...
```

以后：

```text
compare
rollback
```

都基于它。

---

# 20. `shadow_tree_sha`

这个字段非常值得加。

Git Commit 指向：

```text
Tree
```

Tree 表示这个 Snapshot 的文件状态。

所以：

```text
shadow_tree_sha
```

可以理解为：

> **这个 Workspace Snapshot 的内容指纹。**

Rollback 后可以：

```text
target tree hash
vs
current restored tree hash
```

验证：

```text
是否真的恢复成功
```

---

# 21. `workspace_head_sha`

注意这里不是：

```text
Shadow HEAD
```

而是 Task Worktree 所属真实 Repository 的：

```text
git rev-parse HEAD
```

例如：

```text
codeteam/task-001
↓
82fc93...
```

为什么保存？

因为将来你需要知道：

```text
这个 Checkpoint
建立在真实项目哪个 Commit 上。
```

如果 Task Branch 自己后来 Commit 了：

```text
HEAD 已变化
```

你就能识别：

```text
Checkpoint Context Drift
```

---

# 22. `reason`

例如：

```text
task_start

before_refactor

after_patch

before_dependency_update

before_test_fix

auto_before_rollback
```

不要只保留：

```text
timestamp
```

因为 Observability 需要回答：

> 为什么这里建立了 Checkpoint？

---

# 23. Checkpoint 不应该是 Mutable State

推荐：

```text
cp-001
```

创建以后：

```text
永远不改
```

Rollback：

```text
不是修改 cp-001
```

而是：

```text
读取 cp-001
→ 恢复 Workspace
```

这是非常重要的设计。

Checkpoint 应该：

```text
Immutable
```

---

# 24. Shadow History 应该怎么组织

假设：

```text
cp0
→ 修改 A

cp1
→ 修改 B

cp2
→ 修改坏了
```

Shadow History：

```text
S0 ── S1 ── S2
```

现在：

```text
rollback(cp1)
```

一个非常差的实现是：

```text
S0 ── S1
```

直接删除：

```text
S2
```

更好的 Runtime 设计是：

```text
S0 ── S1 ── S2 ── Safety ── Restored-S1
```

也就是：

> **Rollback 本身也是新的 Runtime Event。**

不要修改历史。

---

# 25. 为什么 Rollback 前最好自动创建 Safety Checkpoint

假设用户本来想：

```text
rollback(cp-002)
```

结果选错：

```text
rollback(cp-001)
```

如果 Rollback 直接覆盖当前状态：

```text
刚才的当前状态又丢了。
```

所以我建议：

```text
rollback(target)

第一步：
create(
    reason="auto_before_rollback"
)
```

把当前状态保存。

然后再恢复目标。

流程：

```text
Current Workspace
       │
       ▼
Safety Checkpoint
       │
       ▼
Restore cp-001
       │
       ▼
Verify
```

如果恢复后后悔：

```text
rollback(safety_checkpoint)
```

即可。

这会让 Runtime 的恢复操作本身也是：

```text
recoverable
```

---

# 26. Rollback 不建议直接用用户 Repository 的 `git reset --hard`

为什么？

因为：

```bash
git reset --hard
```

会修改：

```text
HEAD
Index
Working Tree
```

Git 官方当前文档明确说明 `--hard` 会覆盖 Working Tree、更新 Index，并可能覆盖 Untracked 路径。([Git][7])

但你的 Checkpoint 目标不是：

```text
让 codeteam/task-001 Branch 回到某个 Commit
```

而是：

```text
恢复 Agent Workspace Snapshot
```

所以：

```text
Task Branch
```

最好不要被 Checkpoint 系统随便重写。

---

# 27. Shadow Git 下的恢复思路

概念上可以：

```text
Shadow Repo
      +
Task Worktree
      ↓
target checkpoint commit
      ↓
restore tree
```

Git `restore --source=<tree>` 可以从指定 Commit / Tree 恢复 Working Tree；同时指定 `--staged --worktree` 时可以恢复 Index 和 Working Tree。Git Restore 默认是 no-overlay，因此对 Shadow Git 已跟踪、但目标 Snapshot 中不存在的文件，可以删除以匹配目标 Tree。([Git][8])

你的实际项目：

```text
real task Git index
```

与：

```text
shadow Git index
```

应该完全独立。

---

# 28. 一个比较优雅的 Rollback Algorithm

建议第一版逻辑：

```text
rollback(cp1)
        │
        ▼
validate checkpoint
        │
        ├── exists?
        ├── same task?
        └── correct worktree?
        │
        ▼
create safety checkpoint
        │
        ▼
target_tree = cp1.shadow_tree_sha
        │
        ▼
Shadow Git restore target tree
        │
        ▼
verify restored tree
        │
        ├── target == actual
        │
       yes
        │
        ▼
create rollback-result checkpoint
        │
        ▼
RollbackResult.SUCCESS
```

如果 Verify 失败：

```text
target restore
      ↓
verification failed
      ↓
restore safety checkpoint
      ↓
verify safety state
```

最终可能产生：

```text
ROLLBACK_FAILED_BUT_RECOVERED

或

ROLLBACK_RECOVERY_FAILED
```

不要只返回：

```python
False
```

---

# 29. RollbackResult 为什么应该是结构化对象

建议：

```python
class RollbackStatus(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    FAILED_RECOVERED = "failed_recovered"
    FAILED_UNRECOVERED = "failed_unrecovered"


class RollbackResult(BaseModel):
    status: RollbackStatus

    task_id: str
    target_checkpoint_id: str

    safety_checkpoint_id: str | None

    before_tree_sha: str
    after_tree_sha: str | None

    restored_paths: list[str]
    removed_paths: list[str]

    error: str | None = None
```

以后 Event Log 可以直接记录：

```text
RollbackStarted
RollbackSucceeded
RollbackFailed
RollbackRecovered
```

---

# 30. `CheckpointStore` 的职责

我建议不要让：

```text
CheckpointManager
```

把所有 Git 命令、JSON 存储、路径逻辑全部塞进去。

今天建议职责：

```text
CheckpointManager
=
业务编排


CheckpointStore
=
Snapshot + Metadata 持久化
```

关系：

```text
Agent / Runtime
      │
      ▼
CheckpointManager
      │
      ├── ownership validation
      ├── task validation
      ├── lifecycle
      │
      ▼
CheckpointStore
      │
      ├── Shadow Git
      └── Metadata
```

---

# 31. `CheckpointStore` 第一版接口

暂时先理解接口：

```python
class CheckpointStore:
    def create_snapshot(
        self,
        *,
        task_id: str,
        workspace: Path,
        reason: str,
    ) -> Checkpoint:
        ...

    def get(
        self,
        checkpoint_id: str,
    ) -> Checkpoint | None:
        ...

    def list_for_task(
        self,
        task_id: str,
    ) -> list[Checkpoint]:
        ...

    def compare(
        self,
        checkpoint: Checkpoint,
        workspace: Path,
    ) -> CheckpointComparison:
        ...

    def restore(
        self,
        checkpoint: Checkpoint,
        workspace: Path,
    ) -> None:
        ...
```

今天暂时不要急着全部实现。

---

# 32. `CheckpointManager`

外部 API：

```python
checkpoint = manager.create(
    task_id="task-001",
    reason="before_refactor",
)
```

然后：

```python
comparison = manager.compare(
    checkpoint
)
```

恢复：

```python
result = manager.rollback(
    checkpoint
)
```

外部完全不需要知道：

```text
shadow git
tree hash
restore
Git index
metadata file
```

这就是 Harness / Runtime 封装。

---

# 33. `compare(checkpoint)` 到底应该比较什么

建议定义：

```text
Checkpoint Snapshot

vs

Current Task Workspace
```

例如：

```text
Checkpoint cp1

A.py = v2
B.py = v1


Current

A.py = v2
B.py = v2
C.py = new
```

那么：

```text
compare(cp1)
```

返回：

```text
Modified:
B.py

Added:
C.py
```

如果：

```text
old.py → new.py
```

可以进一步利用 Git Rename Detection 显示 Rename。

注意：

```text
Compare
```

必须是只读操作。

---

# 34. Untracked 对 Compare 也有影响

普通：

```bash
git diff
```

不会自动显示未被 Shadow Repo 追踪的新文件。

所以：

```text
compare()
```

不能只调用一次：

```text
git diff
```

还需要识别：

```text
当前 Snapshot Scope 内的新增文件
```

然后返回：

```text
Added
```

这和 Day 1：

```text
changed_files()
```

处理 Untracked 的问题是同一个思想。

---

# 35. Metadata 放在哪里

不要：

```text
task_worktree/
└── .codeteam/checkpoints/
```

因为：

```text
Checkpoint
```

自己可能被 Snapshot。

建议 Runtime State：

```text
CODETEAM_STATE_ROOT/
└── repositories/
    └── <repo-id>/
        └── tasks/
            └── task-001/
                ├── shadow/
                └── checkpoints/
```

例如：

```text
checkpoints/
├── cp-000.json
├── cp-001.json
└── cp-002.json
```

Shadow：

```text
shadow/
└── .git/
```

具体最终路径以后可以配置，不要写死系统全局路径。

---

# 36. 为什么每 Task 一个 Shadow Repo

这里其实存在两种方案。

### 方案 A

```text
一个 Repository
→ 一个 Shadow Repo
→ 所有 Task 都写进去
```

### 方案 B

```text
Task 001
→ Shadow 001

Task 002
→ Shadow 002
```

我推荐 CodeTeam 第一版使用 B。

因为：

```text
Task 生命周期更清楚
故障隔离更强
删除 Task 更容易清理
Checkpoint Ownership 更简单
并发锁粒度更小
```

代价是：

```text
Git Object Dedup
只能 Task 内复用
```

而不能所有 Task 共享。

这就是今天第一个正式 Design Decision 候选。

---

# 37. Cline 的 Failure Case 为什么支持这个思路

Cline 官方仓库的公开 issue 曾出现 Shadow Repository 损坏或残留 `index.lock` 影响 Checkpoint 的情况。([GitHub][9])

这提醒我们：

> Shadow Repo 本身也是一种 Runtime State，需要做故障隔离。

如果一个 Shadow Repo 坏了：

```text
最好只影响：
task-001
```

而不是：

```text
Checkpoint 系统全部瘫痪。
```

---

# 38. Checkpoint Store 需要锁

假设：

```text
Agent Tool Thread A
→ create checkpoint

Agent Tool Thread B
→ create checkpoint
```

同时对：

```text
同一个 Shadow Git Index
```

执行操作。

Git 会使用：

```text
index.lock
```

保护 Index 更新。

在 Cline 公开 issue 中也能看到残留 `index.lock` 导致创建 Checkpoint 失败的实例。([GitHub][6])

所以你的 Runtime 层不要仅依赖 Git：

```text
Per-Task Lock
        ↓
Checkpoint Create
```

第一版：

```text
同一 task
串行 checkpoint

不同 task
可以并行
```

---

# 39. Shadow History 应该 Append-only

我推荐：

```text
S0
 ↓
S1
 ↓
S2
 ↓
Safety
 ↓
Rollback-to-S1
 ↓
S4
```

而不是：

```text
S0
 ↓
S1
```

然后删除后面的历史。

原因是 Observability。

以后你可以回答：

```text
Agent 什么时候做错？
回滚到了哪里？
失败状态是什么？
回滚以后又走了什么路径？
```

这也给 Week 5/6 的：

```text
Trace
Event Log
Agent Replay
```

打基础。

---

# 40. 这和 Event Sourcing 有点像，但不要混为一谈

两者共同点：

```text
历史不轻易覆盖
```

但是你的 Checkpoint：

```text
主要记录 State Snapshot
```

而标准 Event Sourcing：

```text
主要记录导致状态变化的 Event
```

未来可能：

```text
Event Log:
ToolApplied
PatchApplied
TestFailed
RollbackStarted

Checkpoint:
Workspace Snapshot
```

两者配合。

---

# 41. 今天的 Architecture

建议先建立：

```text
                        Task Runtime

                ┌─────────────────────┐
                │    task-001         │
                └──────────┬──────────┘
                           │
                           ▼
                ┌─────────────────────┐
                │   Git Worktree      │
                └──────────┬──────────┘
                           │
                           │ current workspace
                           ▼
                ┌─────────────────────┐
                │ CheckpointManager   │
                └───────┬─────┬───────┘
                        │     │
          metadata      │     │ snapshot
                        ▼     ▼
              ┌───────────┐  ┌───────────────┐
              │Checkpoint │  │CheckpointStore│
              │ Metadata  │  │ Shadow Git    │
              └───────────┘  └───────┬───────┘
                                     │
                          S0 → S1 → S2 → S3
                                     │
                                     ▼
                                 rollback
```

---

# 42. 今天建议的文件结构

不要过度拆文件。

第一版可以：

```text
codeteam/
└── git/
    ├── models.py
    ├── workspace.py
    ├── worktree.py
    ├── checkpoint.py
    └── errors.py
```

如果后面复杂起来，再拆：

```text
checkpoint/
├── manager.py
├── store.py
├── models.py
└── shadow_git.py
```

今天不建议一开始就拆成十几个文件。

---

# 43. 今天的核心模型

至少：

```text
Checkpoint

CheckpointManager

CheckpointStore

RollbackResult
```

另外推荐有：

```text
CheckpointComparison
```

但它不是今天最低要求。

关系：

```text
Checkpoint
=
数据

CheckpointStore
=
保存/读取 Snapshot

CheckpointManager
=
业务控制

RollbackResult
=
恢复结果
```

---

# 44. 今天的实现步骤

按照你现在统一的工程闭环，我建议把 Day 3 拆成下面 7 个 Step。

| Step | 目标                                     | 主要产出                           |
| ---- | -------------------------------------- | ------------------------------ |
| 1    | 建立 Checkpoint 数据模型                     | `Checkpoint`, `RollbackResult` |
| 2    | 定义 Snapshot Scope 与 Runtime State Path | 路径、安全契约                        |
| 3    | 初始化每 Task Shadow Git                   | `CheckpointStore` 基础           |
| 4    | 实现 `create()`                          | Snapshot + Metadata            |
| 5    | 实现 `compare()`                         | Snapshot vs Current            |
| 6    | 实现安全 `rollback()`                      | Safety CP + Restore + Verify   |
| 7    | 完成测试、Benchmark、Ablation                | Evaluation evidence            |

之后你说：

```text
开始第 1 步
```

我们再进入代码细节。

---

# 45. Step 1 最终应该做到什么

能够：

```python
checkpoint = Checkpoint(
    ...
)

result = RollbackResult(
    ...
)
```

并理解：

```text
为什么 Checkpoint 应 immutable
为什么需要 tree sha
为什么需要 task_id
为什么需要 reason
为什么 RollbackResult 不能只是 bool
```

---

# 46. Step 2：定义 Snapshot Scope

必须先明确：

```text
Include

Tracked
Untracked non-ignored
```

以及：

```text
Exclude

.git
Shadow Runtime State
Ignored caches
Runtime temporary files
```

否则写 Shadow Git 时很容易不断补 Bug。

---

# 47. Step 3：Shadow Git

目标不是：

```text
先实现 Rollback
```

而是先证明：

```text
Task Workspace
        ↓
create snapshot
        ↓
Shadow Git Commit
        ↓
项目真实 HEAD 完全不变
```

最重要的不变量：

```text
before_real_head
==
after_real_head

before_real_branch
==
after_real_branch
```

---

# 48. Step 4：Create Checkpoint

流程：

```text
manager.create(task_id, reason)
          ↓
find task worktree
          ↓
lock task
          ↓
validate workspace
          ↓
snapshot managed files
          ↓
shadow commit
          ↓
tree hash
          ↓
persist metadata
          ↓
Checkpoint
```

---

# 49. Step 5：Compare

目标：

```python
manager.compare(checkpoint)
```

能回答：

```text
Modified
Added
Deleted
Renamed
```

但：

```text
绝不修改 Workspace。
```

---

# 50. Step 6：Rollback

核心：

```text
validate
↓
safety checkpoint
↓
restore target
↓
verify target tree
↓
success
```

如果失败：

```text
restore safety
↓
verify safety
```

这是 Day 3 最重要的 Runtime 逻辑。

---

# 51. 你的验收场景怎么运行

用户给出的：

```text
checkpoint 0
→ 改 A
checkpoint 1
→ 改 B
checkpoint 2
→ 改坏 A+B
```

假设：

```text
cp0

A = A0
B = B0
```

修改 A：

```text
A = A1
B = B0

cp1
```

修改 B：

```text
A = A1
B = B1

cp2
```

最后改坏：

```text
A = BROKEN
B = BROKEN
```

执行：

```python
manager.rollback(cp1)
```

最终必须：

```text
A = A1
B = B0
```

不是：

```text
A = A0
B = B0
```

也不是：

```text
A = A1
B = B1
```

---

# 52. Main Worktree 必须同时验证

假设：

```text
Main:

A = A0
B = B0
```

整个 Task：

```text
create
modify
checkpoint
rollback
```

结束后：

```text
Main:

A = A0
B = B0
```

必须一字不变。

这就是 Day 2 和 Day 3 联合证明：

```text
Task Isolation
+
Task Recovery
```

---

# 53. 测试策略

你要求的测试都必须保留，我还建议补充一些 Agent Runtime 特有测试：

| 场景                   | 验证重点                   |
| -------------------- | ---------------------- |
| 修改 1 文件              | 基本恢复                   |
| 修改多文件                | Snapshot 一致性           |
| 新增文件                 | Untracked 恢复           |
| 删除文件                 | 缺失文件恢复                 |
| Rename               | Path Set 恢复            |
| 连续 3 CP              | Timeline               |
| 恢复旧 CP               | Random access recovery |
| 无效 CP                | Validation             |
| 跨 Task CP            | Ownership              |
| Main 不受影响            | Isolation              |
| Ignored File         | Snapshot Scope         |
| Rollback 前 Safety CP | Undo the undo          |
| Metadata reload      | Persistence            |
| 同 Task 并发 CP         | Locking                |
| Shadow Repo 损坏       | Failure isolation      |

---

# 54. “新增文件后恢复”应该测两个方向

## 场景 A

Checkpoint 时不存在：

```text
new.py
```

之后 Agent 创建：

```text
new.py
```

Rollback：

```text
new.py
应该被移除
```

---

## 场景 B

Checkpoint 时存在：

```text
new.py
```

之后 Agent 删除。

Rollback：

```text
new.py
必须恢复
```

只有这两个都通过，

才能说：

```text
Untracked Snapshot
```

真的实现正确。

---

# 55. Rename 的本质

Checkpoint Restore 不一定需要理解：

```text
rename
```

的语义。

例如：

```text
old.py
→
new.py
```

Snapshot 本质是：

```text
old.py absent
new.py exists
```

恢复旧 Snapshot：

```text
old.py exists
new.py absent
```

所以：

```text
Rename Detection
```

主要服务：

```text
compare() 可读性
```

而不是 Restore Correctness。

---

# 56. Design Decision 1：Checkpoint Backend

今天应该正式记录第一个 Decision：

```text
Problem

Agent intermediate state
如何持久化？
```

候选：

| 方案                  | 优点                | 缺点                     |
| ------------------- | ----------------- | ---------------------- |
| Task Branch Commit  | 最简单               | 污染正式历史                 |
| Git Stash           | Git 原生            | Task 隔离/冲突/Metadata 较弱 |
| Full Directory Copy | 简单可靠              | 时间和磁盘成本高               |
| Shadow Git          | 增量对象、Diff/Tree 原生 | 实现复杂、需要管理 Shadow Repo  |
| 自研 CAS Store        | 控制力最高             | 开发成本最高                 |

我建议：

```text
Decision:
Per-task Shadow Git
```

但现在只是：

```text
Engineering Decision
```

还不能说：

```text
“已经证明最佳”
```

需要 Benchmark。

---

# 57. Design Decision 2：Rollback History

候选：

```text
A.
直接把 Shadow Branch reset 到旧状态

B.
History append-only，
Rollback 创建一个新的恢复状态
```

我建议 B：

```text
append-only
```

理由主要是：

```text
可审计
回滚本身可撤销
更适合 Event Log
更适合 Debug
```

---

# 58. Design Decision 3：Rollback 前 Safety Checkpoint

候选：

```text
A.
直接 Restore

B.
先 Snapshot 当前状态
再 Restore
```

我建议 B。

这是一个特别适合 Ablation 的设计。

---

# 59. Benchmark：今天不要只跑单测

按照你新的项目要求，CheckpointManager 完成以后需要做真正 Benchmark。

今天建议的核心 Benchmark：

```text
Shadow Git
vs
Full Directory Copy
```

实验 Workload 可以设置成：

| Repo   |    文件数 |       总大小 |   每次变化 |
| ------ | -----: | --------: | -----: |
| small  |    100 |     ~1 MB |   1 文件 |
| medium |  1,000 | ~10–20 MB |  10 文件 |
| large  | 10,000 |      自己生成 | 100 文件 |

每组：

```text
Warmup
+
20 checkpoints
+
重复若干次
```

测量：

```text
checkpoint_create_ms

compare_ms

rollback_ms

disk_growth_bytes

snapshot_fidelity

failure_count
```

最终比较：

```text
Full Copy

vs

Shadow Git
```

现在先设计 Benchmark，**不要预设 Shadow Git 一定更快**。

---

# 60. 为什么磁盘增长非常值得测

Cline 官方本身就提醒，大 Repository 中 Checkpoint 可能带来显著 Storage 和性能成本。([Cline][1])

所以 Shadow Git 的核心假设之一就是：

```text
很多 Checkpoint
只有少量文件变化时，

内容寻址与对象复用
应该比整仓复制更节省磁盘。
```

但这个“应该”必须用你自己的实验验证。

---

# 61. Ablation 1：取消 Untracked Snapshot

Full：

```text
Tracked
+
Untracked
```

Ablated：

```text
Tracked only
```

建立：

```text
create new_file.py
↓
checkpoint
↓
delete new_file.py
↓
rollback
```

比较：

```text
Snapshot Fidelity
```

如果 Ablated 方案无法恢复：

```text
new_file.py
```

你就可以证明：

> Untracked capture 不是“额外功能”，而是完整 Workspace Recovery 的必要条件。

---

# 62. Ablation 2：取消 Safety Checkpoint

Full：

```text
Current
↓
Safety
↓
Rollback
```

Ablated：

```text
Current
↓
Rollback
```

测试：

```text
错误地选择旧 Checkpoint
↓
用户后悔
↓
尝试恢复 Rollback 前状态
```

指标：

```text
Recovery Success Rate
```

Full：

```text
可以 rollback safety
```

Ablated：

```text
原未提交状态可能无法再恢复
```

这会非常有面试价值。

---

# 63. Failure Case 1：Shadow Repo Corruption

例如：

```text
Shadow Git config 损坏
index.lock 遗留
```

Cline 的官方 GitHub issue 中已有这类公开故障实例。([GitHub][9])

你的系统未来应该：

```text
Task 001 Shadow Repo 坏
```

只能影响：

```text
Task 001 checkpoint
```

而不能影响：

```text
Task 002
Task 003
Main Git
```

这就是：

> Failure Domain Isolation

---

# 64. Failure Case 2：Large Repository

情况：

```text
100,000 文件

每个 Tool Call
都创建 Snapshot
```

可能：

```text
Checkpoint latency ↑
Disk usage ↑
Agent loop latency ↑
```

Cline 官方也明确提示，大 Repository 的 Checkpoint 会带来 Storage 和性能成本。([Cline][1])

未来可能优化：

```text
Checkpoint frequency

Incremental scan

Changed-files-only detection

Retention policy

GC
```

---

# 65. Failure Case 3：Nested Git Repository

例如：

```text
repo/
└── vendor/
    └── another-repo/
        └── .git
```

Shadow Snapshot 很容易和嵌套 Git 产生复杂行为。Cline 过去公开 issue 中就出现过与嵌套 Git 和 `.git_disabled` 处理相关的问题。([GitHub][10])

所以你第一版应该：

```text
明确排除：
.git
nested repository metadata
```

不要试图：

```text
rename 用户 .git
```

---

# 66. Failure Case 4：Multi-root

例如 Task 同时修改：

```text
frontend-repo/

backend-repo/
```

这已经不是：

```text
一个 Snapshot Timeline
```

而是：

```text
Snapshot A
+
Snapshot B
+
Distributed Restore
```

如果：

```text
A restore 成功
B restore 失败
```

就产生跨 Repo Partial Recovery。

Cline 当前正因为这个协调问题，在 Multi-root Workspace 下禁用 Checkpoint。([Cline][11])

所以 CodeTeam Day 3：

```text
单 Task
单 Repository
```

是合理边界。

Multi-repo Checkpoint 应作为未来设计课题。

---

# 67. Failure Case 5：Rollback 本身失败

这是很多初学实现不会考虑的问题。

不能假设：

```text
Rollback
一定成功。
```

可能出现：

```text
Permission Error

Disk Full

Shadow Repo Corruption

Git Process Failure

File Locked

Process Concurrently Modifying File
```

所以才需要：

```text
Safety Checkpoint
+
Restore
+
Verification
+
Fallback Restore
```

---

# 68. Checkpoint 的 Benchmark 和 Tests 是不同问题

今天尤其需要记住：

```text
Tests
```

回答：

```text
能否正确恢复？
```

例如：

```text
新增文件能恢复吗？
```

Benchmark 回答：

```text
恢复需要多久？
```

Ablation 回答：

```text
Shadow Git / Untracked / Safety CP
到底有没有价值？
```

Failure Case 回答：

```text
什么时候恢复仍然可能失败？
```

---

# 69. 今天的学习时间安排

建议 Day 3 按下面节奏完成：

| 阶段                |      时间 | 内容                           |
| ----------------- | ------: | ---------------------------- |
| Theory            |  60 min | Commit / Snapshot / Rollback |
| Industrial Design |  45 min | Cline + Claude Code          |
| Git Lab           |  45 min | Shadow Git 实验                |
| Step 1            |  45 min | 数据模型                         |
| Step 2            |  40 min | Snapshot Scope               |
| Step 3            |  60 min | Shadow Store                 |
| Step 4            |  60 min | Create                       |
| Step 5            |  45 min | Compare                      |
| Step 6            |  90 min | Rollback                     |
| Tests             |  90 min | 主要验收                         |
| Evaluation        | 60 min+ | Benchmark + Ablation         |

---

# 70. 今天先做的 Shadow Git 实验

在正式 Coding 前，很建议自己手工做一次。

概念实验：

```text
真实 Workspace
/tmp/checkpoint-lab/project

Shadow Repository
/tmp/checkpoint-lab/shadow
```

让：

```text
Shadow Git Dir
```

和：

```text
Project Worktree
```

分开。

你需要亲自观察：

```text
修改 project 文件
↓
Shadow Repo snapshot
↓
真实项目 Git HEAD 不变
↓
再次修改
↓
Shadow Repo 有第二个 Snapshot
```

不要一开始就把命令封装进 Python，否则你很难真正理解：

```text
Shadow Git
在干什么。
```

---

# 71. 今天最终应该形成的完整 Pipeline

```text
                   Worker Agent
                        │
                        │ edits
                        ▼
                 Task Worktree
                        │
                        ▼
              CheckpointManager
                  │           │
                  │           │
                  ▼           ▼
             Metadata     Shadow Git
                              │
                      S0 → S1 → S2
                              │
                              ▼
                         Tool Failure
                              │
                              ▼
                     rollback(target)
                              │
                              ▼
                    Safety Checkpoint
                              │
                              ▼
                      Restore Snapshot
                              │
                              ▼
                        Tree Verify
                         /        \
                      PASS        FAIL
                       │            │
                       ▼            ▼
                    continue    restore safety
```

---

# 72. 今天的 Interview Questions

完成后你至少应该能够自己回答下面这些问题。

| 类型          | 问题                                      |
| ----------- | --------------------------------------- |
| 原理          | Commit 和 Checkpoint 有什么区别？              |
| 原理          | Logical Snapshot 为什么不一定意味着复制全部文件？       |
| Runtime     | Coding Agent 为什么需要 Checkpoint？          |
| Runtime     | Checkpoint 与 Worktree 分别解决什么问题？         |
| Design      | 为什么不用普通 Git Commit？                     |
| Design      | 为什么不用 `git stash`？                      |
| Design      | 为什么选择 Shadow Git？                       |
| Design      | 为什么每 Task 一个 Shadow Repo？               |
| Design      | 为什么 Rollback History 应该 append-only？    |
| Reliability | 为什么 Rollback 前还要创建 Safety Checkpoint？   |
| Correctness | Untracked 文件为什么特别重要？                    |
| Safety      | 为什么不能直接对真实 Branch `git reset --hard`？   |
| Failure     | Shadow Repo 自己损坏怎么办？                    |
| Scalability | 10 万文件时每个 Tool Call 都 Checkpoint 会发生什么？ |
| Evaluation  | 怎么证明 Shadow Git 比 Copy Snapshot 更值得使用？  |
| Ablation    | 怎么证明 Untracked Capture 真的有价值？           |

---

# 73. 如果面试官问：“这不就是 Git 吗？”

你最终应该能够表达成：

> Git 只是我实现 Checkpoint Backend 使用的存储原语。真正的 Agent Runtime 问题是如何把一个长时间运行、持续执行副作用操作的 Agent 变成可恢复执行系统。我需要定义 Task-scoped Snapshot、Checkpoint Metadata、Workspace Ownership、Untracked File Scope、Rollback Verification、Pre-rollback Safety Snapshot 和 Failure Isolation。Shadow Git 只是其中用于增量存储和 Diff 的实现方案。

这个回答就已经从：

```text
“我会 git restore”
```

上升到了：

```text
Agent Runtime State & Recovery Design
```

---

# 74. 今日 Design Decision / Benchmark / Ablation / Failure 闭环

今天最终不要以：

```text
9 个测试通过
```

作为结束。

Day 3 真正完成应该形成：

```text
Theory
Checkpoint / Snapshot / Rollback 理解

Industrial Design
Cline Shadow Git
Claude Code Rewind

Implementation
Checkpoint
CheckpointManager
CheckpointStore
RollbackResult

Tests
状态恢复正确

Design Decision
为什么 per-task Shadow Git

Benchmark
Shadow Git vs Full Copy

Ablation
Tracked-only vs Tracked+Untracked
No Safety CP vs Safety CP

Failure Cases
Large Repo
Shadow corruption
Concurrent checkpoint
Nested Git
Rollback failure

Interview
能解释 Recovery Runtime
```

这样 Day 3 才真正服务于你的 Agent Runtime / Harness 求职主线，而不是只增加几个 Git Utility Class。

你下一步直接说 **“开始第 1 步”**，我们就从 `Checkpoint` 与 `RollbackResult` 两个数据模型开始，先只读检查你当前 `codeteam/git/` 的实际代码，再一步一步实现。

[1]: https://docs.cline.bot/core-workflows/checkpoints "Checkpoints - Cline"
[2]: https://docs.anthropic.com/en/docs/claude-code/checkpointing?utm_source=chatgpt.com "Checkpointing - Claude Code Docs"
[3]: https://docs.anthropic.com/en/docs/claude-code/costs?utm_source=chatgpt.com "Manage costs effectively - Claude Code Docs"
[4]: https://openai.com/index/introducing-the-codex-app/ "Introducing the Codex app | OpenAI"
[5]: https://git-scm.com/docs/git-stash "Git - git-stash Documentation"
[6]: https://github.com/cline/cline/issues/5243?utm_source=chatgpt.com "Git index lock file error when creating checkpoints at task completion"
[7]: https://git-scm.com/docs/git-reset "Git - git-reset Documentation"
[8]: https://git-scm.com/docs/git-restore "Git - git-restore Documentation"
[9]: https://github.com/cline/cline/issues/9631?utm_source=chatgpt.com "CHECKPOINT CORRUPTION BUG REPORT (feature) #9631"
[10]: https://github.com/cline/cline/issues/6625?utm_source=chatgpt.com "git directory renamed to .git_disabled when canceling task #6625"
[11]: https://docs.cline.bot/features/multiroot-workspace "Multi-Root Workspaces - Cline"
