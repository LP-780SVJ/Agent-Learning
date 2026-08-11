# 第 3 周 Day 2：Git Branch 与 Worktree

今天要解决的是 Coding Agent 从“**单任务安全修改**”走向“**多个任务并行修改**”的问题。

Day 1 解决了：

```text
LLM 产生 Patch
→ 校验
→ 原子应用
→ Git Diff 审计
```

但如果两个 Agent 同时操作同一个目录：

```text
Agent A                     Agent B
   │                           │
   ├─ 修改 auth.py             ├─ 修改 order.py
   ├─ git apply                ├─ git apply
   ├─ 跑测试                   ├─ git switch ...
   └─ ...                      └─ ...

                ↓
        同一个 Working Tree
                ↓
        状态开始互相污染
```

所以今天需要建立：

```text
                         Git Repository
                              │
                 shared commits / refs
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
      Main Worktree     Task-001 Worktree   Task-002 Worktree
      branch: main      branch:              branch:
                        codeteam/task-001     codeteam/task-002

      /project          /tmp/.../task-001    /tmp/.../task-002
           │                  │                  │
        Human             Agent A             Agent B
```

最终你应该能够：

```python
manager.create(
    task_id="task-001",
    base_ref="main",
)
```

得到：

```text
branch:
codeteam/task-001

worktree:
/tmp/codeteam/task-001
```

并满足最重要的两个不变量：

```text
task-001 修改文件
≠
task-002 文件发生变化

task-001 修改文件
≠
main Working Tree 发生变化
```

---

# 一、首先理解 Git Branch 到底是什么

很多初学者会认为：

> Branch 是“一份代码副本”。

实际上不是。

Branch 更准确地说是：

> **一个可移动的 Ref，指向某个 Commit。**

Git 官方把 Ref 描述为历史上的命名指针；本地 Branch 位于 `refs/heads/...` 命名空间，而 `HEAD` 通常是指向当前 Branch 的 symbolic ref。创建新 Branch 时，它会指向指定起点 Commit；单独执行 `git branch <name>` 只创建 Branch，并不会切换当前 Working Tree。([Git][1])

假设历史：

```text
A ───── B ───── C
                ↑
               main
```

实际上：

```text
refs/heads/main
        │
        ▼
        C
```

创建：

```bash
git branch feature-auth
```

得到：

```text
                 main
                  ↓
A ───── B ─────── C
                  ↑
             feature-auth
```

此时并没有：

```text
一份 main 文件
+
一份 feature-auth 文件
```

只是：

```text
两个 Ref
都指向 Commit C
```

---

# 二、Branch 为什么是“可移动”的 Ref

假设当前：

```text
HEAD
 │
 ▼
feature-auth
 │
 ▼
 C
```

提交一次：

```bash
git commit
```

产生：

```text
A ── B ── C ── D
          ↑    ↑
         main  feature-auth
```

发生的是：

```text
refs/heads/feature-auth

从：
C

移动到：
D
```

所以可以把 Branch 理解为书签：

```text
Commit Graph
= 一本永远追加内容的书

Branch
= 可以随着新 Commit 往后移动的书签
```

---

# 三、HEAD 到底是什么

Day 1 已经接触过 `HEAD`，今天要理解得更深。

正常情况下：

```text
HEAD
 │
 ▼
refs/heads/main
 │
 ▼
Commit C
```

也就是说：

```text
HEAD → Branch → Commit
```

而不是直接：

```text
HEAD → Commit
```

例如概念上：

```text
HEAD:
ref: refs/heads/main
```

Git 当前官方文档也是这样定义的：正常状态下 `HEAD` 是当前检出 Branch 的 symbolic ref。([Git][1])

所以如果执行：

```bash
git branch --show-current
```

可能返回：

```text
main
```

---

# 四、`git branch` 和 `git switch` 为什么是两个命令

假设：

```text
main → C
```

执行：

```bash
git branch feature-auth
```

只会：

```text
创建：
refs/heads/feature-auth → C
```

但是：

```text
HEAD 仍然 → main
Working Tree 仍然属于 main
```

Git 官方明确说明，`git branch <new>` 创建新 Branch，但不会切换当前 Working Tree。([Git][2])

要切换：

```bash
git switch feature-auth
```

此时：

```text
HEAD
 ↓
feature-auth
 ↓
C
```

并且 Git 会更新：

```text
Index
+
Working Tree
```

以匹配这个 Branch。([Git][3])

---

# 五、创建并切换 Branch

传统写法：

```bash
git branch feature-auth
git switch feature-auth
```

现在可以：

```bash
git switch -c feature-auth
```

其中：

```text
-c
--create
```

表示：

```text
创建 Branch
+
切换 Branch
```

更有意思的是，Git 把 `git switch -c` 设计为 transactional：如果切换无法完成，例如 Branch 已经在另一个 Worktree 中使用，则不会先留下一个半创建状态的 Branch。([Git][3])

这个思想对 Coding Agent 非常重要：

> **状态变更尽可能使用能够整体成功或整体失败的 Git 高层操作。**

---

# 六、Branch Ref 与 HEAD 的关系

你应该能画出下面这张图。

正常 Branch 状态：

```text
HEAD
 │
 │ symbolic ref
 ▼
refs/heads/codeteam/task-001
 │
 │ branch ref
 ▼
8ac347... Commit
```

提交后：

```text
                  HEAD
                   │
                   ▼
refs/heads/codeteam/task-001
                   │
                   ▼
                  NEW
                   │
                   ▼
                  OLD
```

变化的是：

```text
Branch Ref 指向的位置
```

---

# 七、Detached HEAD 是什么

这是今天另一个核心概念。

正常状态：

```text
HEAD
 │
 ▼
Branch
 │
 ▼
Commit
```

Detached HEAD：

```text
HEAD
 │
 ▼
Commit
```

中间不再有 Branch。

Git 官方将它定义为：

> `HEAD` 直接指向某个 Commit，而不是指向命名 Branch。你仍然可以修改、提交、查看历史，但如果之后离开这些 Commit 而没有建立新的 Ref，它们可能最终失去可达引用。([Git][4])

---

# 八、怎样进入 Detached HEAD

例如：

```bash
git switch --detach 8ac347
```

或者：

```bash
git worktree add --detach \
    /tmp/experiment \
    8ac347
```

`git switch --detach` 官方定位就是检查某个 Commit 或做可丢弃实验。([Git][3])

假设：

```text
main
 ↓
 C
```

执行：

```bash
git switch --detach C
```

状态：

```text
main
 ↓
 C
 ↑
HEAD
```

提交：

```text
main
 ↓
 C ─── D
       ↑
      HEAD
```

`D` 并没有：

```text
refs/heads/xxx
```

指向它。

---

# 九、Detached HEAD 为什么反而适合 Coding Agent

乍一看：

```text
Detached HEAD
```

好像是 Git 的异常状态。

其实不是。

对于：

```text
临时实验
后台 Agent
一次性测试
短生命周期任务
```

它非常有价值。

因为假设启动：

```text
20 个后台 Agent
```

如果每个都自动创建：

```text
codeteam/task-001
codeteam/task-002
...
codeteam/task-020
```

Branch Namespace 会迅速膨胀。

Detached 模式：

```text
Task
→ Worktree
→ Detached HEAD
→ 修改
→ 用户决定保留
→ 再创建 Branch
```

可以避免 Branch 污染。

---

# 十、OpenAI Codex 当前就是一个非常直接的工业实例

公开的 Codex Worktree 文档显示，Codex 在 ChatGPT 桌面端可以让多个独立 Coding Chat 在同一个 Git 项目中并行工作，而不会干扰本地 Checkout；Codex 管理的 Worktree 默认从用户选定 Branch 的 `HEAD` Commit 出发，并且**默认处于 Detached HEAD**。需要长期保存工作时，再通过 “Create branch here” 转成 Branch。Codex-managed Worktree 存放在 `$CODEX_HOME/worktrees`，每个 Chat 会关联自己的 Worktree。([OpenAI Developers][5])

其设计可以概括为：

```text
User Local Checkout
       │
       ├──────────────────────────────┐
       │                              │
       ▼                              ▼
foreground                    Codex background
main                          detached HEAD
                                   │
                              Worktree #1

                              detached HEAD
                                   │
                              Worktree #2
```

这个设计优点非常清楚：

```text
需要并行任务
→ 创建 Worktree

还没决定是否保留
→ Detached HEAD

决定保留
→ 创建 Branch

准备回到本地
→ Handoff
```

Codex 官方还专门解释了为什么同一个 Branch 不应该同时在多个 Worktree 中 Checkout：Branch Ref 是共享资源，如果多个独立 Working Tree 同时推进同一个 Branch，会产生谁应该更新 Branch Ref 的歧义和竞争。([OpenAI Developers][5])

---

# 十一、那么你的 CodeTeam 为什么先采用“Branch per Task”

你的 Day 2 要求是：

```text
task-001
→ codeteam/task-001
```

这是另一种完全合理的设计。

比较：

| 方案              | Detached Worktree | Branch-per-Task   |
| --------------- | ----------------- | ----------------- |
| 临时任务            | 很适合               | 可以                |
| Branch 污染       | 少                 | 较多                |
| Task 身份         | 需要额外记录            | Branch 天然表达       |
| Commit          | 可以，但需注意保存 Ref     | 很自然               |
| PR              | 先建 Branch         | 很自然               |
| 后续 MergeManager | 多一步               | 简单                |
| 清理              | Worktree 为主       | Worktree + Branch |
| 并行              | 很好                | 很好，只要 Branch 唯一   |

对于你目前的 Coding Agent Runtime，我建议第一版：

```text
Task
→ Unique Branch
→ Unique Worktree
```

因为后面马上要实现：

```text
Checkpoint
Review
Commit
Merge
Multi-Agent
```

Branch 可以天然作为 Task 的持久 Git 身份。

以后再扩展：

```python
manager.create(
    task_id="task-001",
    base_ref="main",
    mode="detached",
)
```

---

# 十二、什么是 Git Worktree

现在进入今天真正的主角。

一个普通 Git Repo：

```text
project/
├── .git/
├── src/
└── tests/
```

只能在这个目录中呈现一个 Working Tree 状态。

但 Git 官方支持：

```text
一个 Repository
+
多个 Working Tree
```

通过：

```bash
git worktree add
```

创建。

Git 官方把最初通过 `git clone` / `git init` 创建的工作目录称为 **main worktree**，之后通过 `git worktree add` 创建的是 **linked worktree**。一个非 bare Repository 有一个 main worktree，可以有零个或多个 linked worktree。([Git][6])

---

# 十三、Main Worktree 与 Linked Worktree

例如：

```text
/home/user/project
```

这是：

```text
Main Worktree
```

然后：

```bash
git worktree add \
  -b codeteam/task-001 \
  /tmp/codeteam/task-001 \
  main
```

得到：

```text
/home/user/project
→ Main Worktree

/tmp/codeteam/task-001
→ Linked Worktree
```

再：

```bash
git worktree add \
  -b codeteam/task-002 \
  /tmp/codeteam/task-002 \
  main
```

最终：

```text
                 Repository
                     │
     ┌───────────────┼─────────────────┐
     │               │                 │
     ▼               ▼                 ▼
Main Worktree    Linked WT #1     Linked WT #2

/project         /tmp/.../001     /tmp/.../002

HEAD             HEAD             HEAD
 ↓                ↓                ↓
main             task-001         task-002

Index #0         Index #1         Index #2

Files #0         Files #1         Files #2
```

---

# 十四、Worktree 不是完整 Git Clone

这点非常重要。

如果创建 10 个 Clone：

```text
repo-clone-1/.git/
repo-clone-2/.git/
repo-clone-3/.git/
...
```

每个 Clone 都有自己的 Git Object Database。

而 Worktree：

```text
                     shared
                       │
                 Object Database
                 Branch Refs
                 Tags
                 Repository Config
                       │
      ┌────────────────┼───────────────┐
      │                │               │
    WT-0              WT-1            WT-2
      │                │               │
    HEAD-0           HEAD-1          HEAD-2
    Index-0          Index-1         Index-2
    Files-0          Files-1         Files-2
```

Git 官方说明 Linked Worktree 与同一个 Repository 关联，**共享公共 Git 数据，但 `HEAD`、`index` 等 Worktree-specific 状态独立**；一般的 `refs/...` 是共享的，而 `HEAD` 等 pseudo refs 通常是 per-worktree。([Git][6])

---

# 十五、到底哪些东西共享，哪些独立

建议牢记这张表：

| 内容                  | 多 Worktree 之间 |
| ------------------- | ------------- |
| Commit Objects      | **共享**        |
| Blob / Tree Objects | **共享**        |
| Local Branch Refs   | **共享**        |
| Tags                | **共享**        |
| Repository Config   | 默认**共享**      |
| Remotes             | **共享**        |
| `HEAD`              | **独立**        |
| Index               | **独立**        |
| Working Tree Files  | **独立**        |
| 当前未提交修改             | **独立**        |

Git 官方还支持启用 `extensions.worktreeConfig` 来维护某些 Worktree-specific Git Configuration，不过默认 Repository Config 是共享的。([Git][6])

---

# 十六、一个非常关键的推论

虽然：

```text
Files
Index
HEAD
```

是隔离的，

但：

```text
Branch Ref
```

是共享的。

例如：

```text
refs/heads/codeteam/task-001
```

是整个 Repository 的公共 Ref。

因此 Git 默认不允许：

```text
Worktree A
checkout task-001

同时

Worktree B
checkout task-001
```

`git worktree add` 默认发现 Branch 已在其他 Worktree Checkout 时会拒绝操作；只有显式 `--force` 才能绕过这一保护。([Git][6])

你的 `WorktreeManager` 必须：

```text
永远不使用：
--force
```

---

# 十七、为什么同 Branch 多 Worktree 很危险

假设错误地允许：

```text
Worktree A
HEAD → task-001

Worktree B
HEAD → task-001
```

A：

```text
Index A
Files A
```

B：

```text
Index B
Files B
```

但是它们都共享：

```text
refs/heads/task-001
```

Agent A Commit：

```text
task-001 → Commit D
```

但 B 的：

```text
Working Tree
Index
```

仍可能对应旧 Commit C。

然后 B 再 Commit：

```text
到底怎样更新 task-001？
```

这就进入复杂竞争状态。

Git 和 Codex 都明确避免这种工作方式。([Git][6])

---

# 十八、Linked Worktree 里的 `.git` 是什么

这是今天非常容易踩坑的点。

Main Worktree：

```text
project/
└── .git/
```

通常 `.git` 是目录。

但 Linked Worktree：

```text
/tmp/codeteam/task-001/
└── .git
```

这里通常是：

```text
一个文件
```

里面概念上记录：

```text
gitdir: /project/.git/worktrees/task-001
```

Git 会在主 Repository 的：

```text
.git/worktrees/<id>/
```

维护这个 Linked Worktree 的私有 Git Metadata；同时 `$GIT_COMMON_DIR` 指回公共 Git Directory。([Git][6])

---

# 十九、这会直接影响你 Day 1 的代码

如果你昨天写了：

```python
if not (root / ".git").is_dir():
    raise NotAGitRepository()
```

今天必须改。

因为：

```text
Linked Worktree

.git
是文件
```

所以工业代码不要自己判断 `.git` 类型。

推荐：

```bash
git rev-parse --show-toplevel
```

或者：

```bash
git rev-parse --git-dir
```

由 Git 判断。

这是第三周第一次典型的：

> **前一天看似合理的实现，到了真正工业场景会出现边界问题。**

---

# 二十、Worktree 的隔离能力到底隔离了什么

假设：

```text
main:
/project/src/auth.py

task-001:
/tmp/.../001/src/auth.py

task-002:
/tmp/.../002/src/auth.py
```

开始时内容完全一样：

```python
def login():
    return "old"
```

Task 001 改：

```python
def login():
    return "task-001"
```

此时：

```text
task-001:
task-001

task-002:
old

main:
old
```

所以从文件系统角度：

```text
Task A 写文件
不会直接覆盖
Task B 文件
```

---

# 二十一、Worktree 隔离不等于 Merge 永远不会冲突

这一点必须特别明确。

假设：

```text
task-001
把 login() 改成 A

task-002
把 login() 改成 B
```

两个 Agent 并行编辑期间：

```text
没有 Working Tree 冲突
```

但最后：

```text
task-001 → merge main
task-002 → merge main
```

Task 002 仍可能出现：

```text
Merge Conflict
```

所以：

```text
Worktree Isolation

解决：
并行执行时状态互相污染

不解决：
两个任务做出了语义冲突的修改
```

这是你未来 Multi-Agent Manager 必须处理的两个不同问题。

---

# 二十二、Cline Kanban 是一个非常直接的实践案例

Cline 当前 Kanban 会为每张运行中的任务卡创建一个**临时 Git Worktree**，Agent 获得自己 Worktree 中的 Terminal；多个任务因此可以并行工作，不直接改变用户 Main Working Directory 或其他任务的文件。完成后用户 Review Worktree Diff，然后 Commit/Open PR，任务删除时再清理临时 Worktree。([Cline][7])

它的流程非常接近你后续要实现的：

```text
Kanban Card
     │
     ▼
Ephemeral Worktree
     │
     ▼
Agent Terminal
     │
     ▼
Code Changes
     │
     ▼
Diff Review
     │
   ┌─┴─┐
Commit PR
     │
     ▼
Cleanup
```

---

# 二十三、Cline 还有一个非常值得学习的工程优化

新 Worktree 通常没有：

```text
node_modules/
venv/
build cache/
```

因为它们都被：

```text
.gitignore
```

忽略了。

如果每个 Task 都执行：

```bash
npm install
```

创建 1 GB `node_modules`：

```text
10 个 Agent
≈ 10 GB
+
大量安装时间
```

Cline Kanban 当前会把 `node_modules` 等 Gitignored 文件从主 Repo **symlink 到 Worktree**，以减少重复安装。([Cline][8])

但是 Cline 官方也特别提醒：

> 如果 Agent 修改的是这种 Symlink 指向的 Gitignored 内容，实际上会修改主 Repo 那份共享内容。([Cline][8])

因此：

```text
Tracked Source
→ Worktree 真隔离

Symlinked ignored dependencies
→ 可能共享
```

这对你的 CodeTeam 是一个重要设计教训。

第一版建议：

```text
先不要自动 Symlink node_modules / .venv

优先保证隔离正确

之后再优化：
Dependency Cache
Shared read-only cache
Hardlink
Symlink
Container Layer
```

---

# 二十四、OpenAI Codex 与 Cline 的两种设计值得对比

公开实现可以总结成：

```text
OpenAI Codex

Chat
 ↓
Managed Worktree
 ↓
Detached HEAD
 ↓
用户决定是否建立 Branch
```

([OpenAI Developers][5])

而你的第一版：

```text
CodeTeam

Task
 ↓
Task Branch
 ↓
Task Worktree
 ↓
Worker Agent
```

Cline Kanban则强调：

```text
Card
 ↓
Ephemeral Worktree
 ↓
Agent
 ↓
Diff Review
 ↓
Ship / Cleanup
```

([Cline][8])

这三个设计都在解决同一个工业问题：

> **让 Agent Task 成为独立执行单元，而不是让所有 Agent 直接抢一个目录。**

---

# 二十五、GitHub Copilot Cloud Agent 使用的也是同一类思想

GitHub Copilot Cloud Agent 并不是简单在用户当前 Working Tree 中直接工作。公开文档显示，每个任务运行在自己的 ephemeral development environment 中，并且一个 Agent Task 一次工作在一个 Branch 上、对应一个 PR。([GitHub Docs][9])

它未必采用本地 Git Worktree，但架构原则高度一致：

```text
Task
 ↓
Isolated Environment
 ↓
Task Branch
 ↓
Agent Changes
 ↓
Tests
 ↓
Pull Request
```

所以工业界真正重要的不是：

```text
“必须使用 git worktree”
```

而是：

```text
Task Isolation
+
Independent Git State
+
Reviewable Change
+
Controlled Integration
```

本地 Agent 中，Git Worktree 恰好是一个非常便宜而实用的隔离原语。

---

# 二十六、今天真正应该实现的 Task 生命周期

你第一版可以设计成：

```text
manager.create(
    task_id="task-001",
    base_ref="main"
)
        │
        ▼
验证 Task ID
        │
        ▼
BranchNamingPolicy
        │
        ▼
codeteam/task-001
        │
        ▼
验证 Branch 名
        │
        ▼
解析 base_ref
main → immutable base SHA
        │
        ▼
检查 Branch 冲突
        │
        ▼
计算 Worktree Path
        │
        ▼
检查 Path 冲突
        │
        ▼
git worktree add
-b codeteam/task-001
/path
<base-sha>
        │
        ▼
重新读取 worktree list
        │
        ▼
验证 Postconditions
        │
        ▼
WorktreeInfo
```

---

# 二十七、为什么要先把 `main` 解析成 Commit SHA

用户传入：

```python
base_ref="main"
```

但：

```text
main
```

是一个会移动的 Ref。

假设：

```text
T0
验证 main → C

T1
另一个进程提交
main → D

T2
创建 Worktree from main
```

Task 实际从：

```text
D
```

开始，而不是你记录的：

```text
C
```

这会产生审计不一致。

所以推荐：

```text
base_ref = main
       ↓
resolve
       ↓
base_sha = 8ac347...
       ↓
以后创建 Worktree 使用 base_sha
```

Git 官方给出的可靠验证方式是：

```bash
git rev-parse \
  --verify \
  --end-of-options \
  "$REV^{commit}"
```

如果 `$REV` 不存在或不能解析成 Commit，则命令失败。([Git][10])

---

# 二十八、为什么一定使用 `--end-of-options`

假设 Agent/User 传：

```text
base_ref="--help"
```

你不能让 Git 把它当 Option。

所以：

```bash
git rev-parse \
  --verify \
  --end-of-options \
  "--help^{commit}"
```

告诉 Git：

```text
后面不再解释成命令选项
```

这也是 Argument Injection 防御的一部分。

---

# 二十九、创建 Worktree 的推荐命令

在已经得到：

```text
branch:
codeteam/task-001

path:
/tmp/codeteam/task-001

base_sha:
8ac347...
```

后执行：

```bash
git worktree add \
  -b codeteam/task-001 \
  /tmp/codeteam/task-001 \
  8ac347...
```

Git `worktree add -b` 会基于指定 `<commit-ish>` 创建新 Branch，并把它 Checkout 到新的 Linked Worktree；如果 Branch 已存在，`-b` 默认拒绝，而 `-B` 会覆盖/重置已有 Branch。([Git][6])

因此 CodeTeam：

```text
允许：
-b

禁止：
-B
--force
```

---

# 三十、为什么不能使用 `-B`

`-B` 相当危险。

假设已经存在：

```text
codeteam/task-001
       ↓
      D
```

错误地：

```bash
git worktree add \
  -B codeteam/task-001 \
  /tmp/task-001 \
  main
```

可能试图把 Branch 重置到新的起点。

你的 Agent Runtime 不应该静默覆盖已经存在的任务状态。

因此：

```text
Branch 冲突
→ 显式错误

而不是：
覆盖旧 Branch
```

---

# 三十一、BranchNamingPolicy

现在实现今天第一个自己的核心模块。

任务：

```text
task-001
```

得到：

```text
codeteam/task-001
```

但是用户未来可能提供：

```text
Task 001
修复 登录 BUG
../../evil
--force
feature/foo@{1}
```

Branch 名不能直接拼字符串。

Git 对合法 Ref Name 有完整规则，并提供：

```bash
git check-ref-format --branch <name>
```

专门验证名字是否可以作为 Branch。([Git][11])

---

# 三十二、推荐命名策略

第一版：

```python
import hashlib
import re


class BranchNamingPolicy:
    def __init__(
        self,
        prefix: str = "codeteam",
        max_slug_length: int = 64,
    ) -> None:
        self.prefix = prefix
        self.max_slug_length = max_slug_length

    def branch_for(
        self,
        task_id: str,
    ) -> str:
        if not task_id.strip():
            raise ValueError(
                "task_id cannot be empty"
            )

        normalized = task_id.strip().lower()

        slug = re.sub(
            r"[^a-z0-9._-]+",
            "-",
            normalized,
        )

        slug = re.sub(
            r"-+",
            "-",
            slug,
        )

        slug = slug.strip(".-")

        if not slug:
            digest = hashlib.sha256(
                task_id.encode("utf-8")
            ).hexdigest()[:12]

            slug = f"task-{digest}"

        slug = slug[
            : self.max_slug_length
        ]

        return f"{self.prefix}/{slug}"
```

例如：

```text
task-001
→ codeteam/task-001
```

```text
Task Auth Refresh
→ codeteam/task-auth-refresh
```

---

# 三十三、不要认为自己的 Regex 能替代 Git

最终仍然执行：

```python
def validate_branch_name(
    repo_root: Path,
    branch: str,
) -> None:
    result = subprocess.run(
        [
            "git",
            "check-ref-format",
            "--branch",
            branch,
        ],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=5,
        check=False,
    )

    if result.returncode != 0:
        raise InvalidBranchName(
            branch
        )
```

也就是：

```text
自己的 Sanitizer
+
Git 官方 Validator
```

---

# 三十四、Worktree Path 也需要命名策略

用户要求：

```text
/tmp/codeteam/task-001
```

学习版完全可以。

但生产版建议：

```text
/tmp/codeteam/
└── <repository-id>/
    ├── task-001/
    └── task-002/
```

原因：

假设：

```text
repo A:
task-001

repo B:
task-001
```

如果都是：

```text
/tmp/codeteam/task-001
```

会碰撞。

生产版可以：

```text
/tmp/codeteam/
├── a3fc8921/
│   └── task-001
└── b88178cc/
    └── task-001
```

---

# 三十五、WorktreeInfo

建议：

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class WorktreeInfo(BaseModel):
    task_id: str | None = None

    path: str

    branch: str | None = None
    branch_ref: str | None = None

    head_sha: str | None = None

    base_ref: str | None = None
    base_sha: str | None = None

    is_main: bool = False
    is_detached: bool = False
    is_bare: bool = False

    is_locked: bool = False
    lock_reason: str | None = None

    is_prunable: bool = False
    prune_reason: str | None = None

    created_at: datetime | None = None
```

这里：

```text
branch
```

例如：

```text
codeteam/task-001
```

而：

```text
branch_ref
```

是：

```text
refs/heads/codeteam/task-001
```

---

# 三十六、为什么要同时保存 `base_ref` 和 `base_sha`

例如：

```text
base_ref:
main

base_sha:
f8a47c...
```

它们分别表达：

```text
base_ref
用户表达的逻辑起点

base_sha
Task 真正使用的不可变起点
```

以后 main 已经：

```text
C → D → E
```

你仍然知道 Task 是：

```text
基于 C 创建
```

这对之后：

```text
Diff
Merge
Rebase
Checkpoint
Review
```

都很重要。

---

# 三十七、机器读取 Worktree：不要解析人类输出

人类运行：

```bash
git worktree list
```

可能看到：

```text
/project                  8ac347 [main]
/tmp/codeteam/task-001    8ac347 [codeteam/task-001]
/tmp/codeteam/task-002    8ac347 [codeteam/task-002]
```

但是程序不要解析这个。

Git 官方专门提供：

```bash
git worktree list \
  --porcelain \
  -z
```

`--porcelain` 是供脚本稳定解析的格式，并承诺不受用户配置影响；`-z` 使用 NUL 分隔，因此 Worktree Path 中即使存在换行也可以可靠解析。([Git][6])

---

# 三十八、Porcelain 长什么样

概念上：

```text
worktree /project
HEAD 8ac347...
branch refs/heads/main

worktree /tmp/codeteam/task-001
HEAD 8ac347...
branch refs/heads/codeteam/task-001
```

Detached：

```text
worktree /tmp/experiment
HEAD 8ac347...
detached
```

Locked：

```text
worktree /tmp/task
HEAD 8ac347...
branch refs/heads/task
locked managed by codeteam
```

Git 官方定义了这些字段和稳定格式。([Git][6])

---

# 三十九、`-z` 后不是按换行解析

内部类似：

```text
worktree /project<NUL>
HEAD abc...<NUL>
branch refs/heads/main<NUL>
<NUL>
worktree /tmp/task<NUL>
HEAD def...<NUL>
branch refs/heads/task<NUL>
<NUL>
```

所以解析：

```python
data.split(b"\0")
```

而不是：

```python
stdout.decode().splitlines()
```

---

# 四十、Porcelain Parser

```python
import os
from dataclasses import dataclass


@dataclass
class RawWorktreeRecord:
    path: str
    head: str | None = None
    branch_ref: str | None = None

    detached: bool = False
    bare: bool = False

    locked: bool = False
    lock_reason: str | None = None

    prunable: bool = False
    prune_reason: str | None = None


def parse_worktree_porcelain_z(
    data: bytes,
) -> list[RawWorktreeRecord]:
    records: list[RawWorktreeRecord] = []

    current: dict[str, str | bool] = {}

    def flush() -> None:
        nonlocal current

        if not current:
            return

        path = current.get("worktree")

        if not isinstance(path, str):
            raise ValueError(
                "worktree record missing path"
            )

        records.append(
            RawWorktreeRecord(
                path=path,
                head=(
                    current.get("HEAD")
                    if isinstance(
                        current.get("HEAD"),
                        str,
                    )
                    else None
                ),
                branch_ref=(
                    current.get("branch")
                    if isinstance(
                        current.get("branch"),
                        str,
                    )
                    else None
                ),
                detached=bool(
                    current.get("detached")
                ),
                bare=bool(
                    current.get("bare")
                ),
                locked=(
                    "locked" in current
                ),
                lock_reason=(
                    current.get("locked")
                    if isinstance(
                        current.get("locked"),
                        str,
                    )
                    else None
                ),
                prunable=(
                    "prunable" in current
                ),
                prune_reason=(
                    current.get("prunable")
                    if isinstance(
                        current.get("prunable"),
                        str,
                    )
                    else None
                ),
            )
        )

        current = {}

    for token in data.split(b"\0"):
        if token == b"":
            flush()
            continue

        key_bytes, separator, value_bytes = (
            token.partition(b" ")
        )

        key = key_bytes.decode("ascii")

        if not separator:
            current[key] = True
            continue

        current[key] = os.fsdecode(
            value_bytes
        )

    flush()

    return records
```

---

# 四十一、为什么 `os.fsdecode()` 很重要

Worktree Path 本质上属于：

```text
Filesystem Path
```

不是普通 JSON UTF-8 文本。

因此机器层尽量：

```python
os.fsdecode(...)
```

而不是：

```python
.decode("utf-8")
```

这样对特殊文件系统路径更稳健。

---

# 四十二、WorktreeManager 应负责什么

建议边界：

```text
WorktreeManager

负责：
验证 Repository
验证 Base Ref
Task → Branch
Branch 冲突
Task → Worktree Path
Path 冲突
创建 Worktree
列出 Worktree
删除 Worktree
检查 Dirty
验证创建后状态

不负责：
Patch
Checkpoint
Merge
Commit
Approval
测试
```

---

# 四十三、错误类型

建议不要统一：

```python
raise RuntimeError
```

而是：

```python
class WorktreeError(RuntimeError):
    pass


class BaseRefNotFoundError(WorktreeError):
    pass


class BranchAlreadyExistsError(
    WorktreeError
):
    pass


class WorktreePathConflictError(
    WorktreeError
):
    pass


class WorktreeNotFoundError(
    WorktreeError
):
    pass


class DirtyWorktreeError(
    WorktreeError
):
    pass


class MainWorktreeRemovalError(
    WorktreeError
):
    pass


class GitWorktreeCommandError(
    WorktreeError
):
    pass
```

这样未来 Agent 可以判断：

```text
Branch conflict
→ 换名字

Dirty
→ 请求 Commit / Rollback

Base 不存在
→ 用户参数错误
```

而不是所有错误都变成：

```text
Git failed
```

---

# 四十四、Base Ref Validator

```python
def resolve_commit(
    self,
    ref: str,
) -> str:
    if not ref:
        raise BaseRefNotFoundError(
            "base_ref is empty"
        )

    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{ref}^{{commit}}",
        ],
        cwd=self.repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=5,
        check=False,
    )

    if result.returncode != 0:
        raise BaseRefNotFoundError(
            f"Invalid base ref: {ref!r}"
        )

    return (
        result.stdout
        .decode("ascii")
        .strip()
    )
```

这个 Base SHA 之后作为 Task 的固定起点。([Git][10])

---

# 四十五、检查 Branch 是否存在

可以：

```python
def branch_exists(
    self,
    branch: str,
) -> bool:
    result = subprocess.run(
        [
            "git",
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ],
        cwd=self.repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        timeout=5,
        check=False,
    )

    return result.returncode == 0
```

创建 Task 时：

```python
if self.branch_exists(branch):
    raise BranchAlreadyExistsError(
        branch
    )
```

不要：

```text
发现已经存在
→ -B 强行复用
```

---

# 四十六、Worktree Path 安全

建议 Manager 有固定根：

```text
/tmp/codeteam
```

然后：

```python
self.worktrees_root = (
    worktrees_root.resolve()
)
```

Task Path：

```python
candidate = (
    self.worktrees_root / slug
).resolve(strict=False)

if not candidate.is_relative_to(
    self.worktrees_root
):
    raise WorktreePathConflictError(
        "worktree path escapes root"
    )
```

此外使用：

```python
os.path.lexists(path)
```

比单纯：

```python
Path.exists()
```

更保守，因为 broken symlink 也应视为路径冲突。

---

# 四十七、创建 Worktree

核心：

```python
def create(
    self,
    *,
    task_id: str,
    base_ref: str,
) -> WorktreeInfo:
    branch = (
        self.naming_policy
        .branch_for(task_id)
    )

    self._validate_branch_name(
        branch
    )

    base_sha = self.resolve_commit(
        base_ref
    )

    if self.branch_exists(branch):
        raise BranchAlreadyExistsError(
            branch
        )

    worktree_path = (
        self._path_for_task(
            task_id
        )
    )

    if os.path.lexists(
        worktree_path
    ):
        raise WorktreePathConflictError(
            str(worktree_path)
        )

    self.worktrees_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    result = subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            base_sha,
        ],
        cwd=self.repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=60,
        check=False,
    )

    if result.returncode != 0:
        raise GitWorktreeCommandError(
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    info = self.get_by_path(
        worktree_path
    )

    if info is None:
        raise GitWorktreeCommandError(
            "Git created worktree but "
            "it was not found afterward"
        )

    if info.branch != branch:
        raise GitWorktreeCommandError(
            "Postcondition failed: "
            "unexpected branch"
        )

    if info.head_sha != base_sha:
        raise GitWorktreeCommandError(
            "Postcondition failed: "
            "unexpected HEAD"
        )

    info.task_id = task_id
    info.base_ref = base_ref
    info.base_sha = base_sha

    return info
```

---

# 四十八、为什么创建之后还要验证 Postcondition

不要认为：

```text
subprocess returncode == 0
```

就等于所有业务条件正确。

我们真正需要的 Invariant 是：

```text
Worktree 已注册
Branch 正确
HEAD 正确
Path 正确
不是 Detached
```

所以：

```text
Command Success
+
State Verification
```

才算成功。

这是工业 Runtime 很重要的模式。

---

# 四十九、`list()`

```python
def list(
    self,
) -> list[WorktreeInfo]:
    result = subprocess.run(
        [
            "git",
            "worktree",
            "list",
            "--porcelain",
            "-z",
        ],
        cwd=self.repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        raise GitWorktreeCommandError(
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    raw_records = (
        parse_worktree_porcelain_z(
            result.stdout
        )
    )

    infos: list[WorktreeInfo] = []

    for index, record in enumerate(
        raw_records
    ):
        branch_ref = (
            record.branch_ref
        )

        branch = None

        if (
            branch_ref
            and branch_ref.startswith(
                "refs/heads/"
            )
        ):
            branch = branch_ref[
                len("refs/heads/"):
            ]

        infos.append(
            WorktreeInfo(
                path=record.path,
                branch=branch,
                branch_ref=branch_ref,
                head_sha=record.head,
                is_main=(index == 0),
                is_detached=(
                    record.detached
                ),
                is_bare=record.bare,
                is_locked=record.locked,
                lock_reason=(
                    record.lock_reason
                ),
                is_prunable=(
                    record.prunable
                ),
                prune_reason=(
                    record.prune_reason
                ),
            )
        )

    return infos
```

Git 保证 `worktree list` 先列 Main Worktree，再列 Linked Worktrees。([Git][6])

---

# 五十、Dirty Worktree

什么叫 Dirty？

例如：

```text
Tracked 文件修改
Tracked 文件删除
Staged 修改
Untracked 新文件
```

都意味着：

```text
Task 还有未处理内容
```

检查建议：

```bash
git status \
  --porcelain=v2 \
  -z \
  --untracked-files=all
```

只要 stdout 非空：

```text
dirty
```

---

# 五十一、为什么删除 Worktree 前自己先检查 Dirty

Git 自身已经有保护：

```bash
git worktree remove <path>
```

默认会拒绝删除不干净的 Worktree；只有 `--force` 才允许移除 Dirty Worktree，而且 Main Worktree 不能通过该命令移除。([Git][12])

但你的 Manager 应再检查一次：

```text
Manager:
dirty?
→ reject

Git:
remove without --force
→ 再检查
```

仍然是：

```text
Defense in Depth
```

---

# 五十二、Dirty 检查

```python
def is_dirty(
    self,
    worktree_path: Path,
) -> bool:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
        ],
        cwd=worktree_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        raise GitWorktreeCommandError(
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    return bool(result.stdout)
```

---

# 五十三、删除 Worktree

推荐：

```python
def remove(
    self,
    *,
    task_id: str,
) -> None:
    info = self.get(task_id)

    if info is None:
        raise WorktreeNotFoundError(
            task_id
        )

    if info.is_main:
        raise MainWorktreeRemovalError()

    path = Path(info.path)

    if self.is_dirty(path):
        raise DirtyWorktreeError(
            info.path
        )

    result = subprocess.run(
        [
            "git",
            "worktree",
            "remove",
            str(path),
        ],
        cwd=self.repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=30,
        check=False,
    )

    if result.returncode != 0:
        raise GitWorktreeCommandError(
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )
```

注意：

```text
没有：
--force
```

---

# 五十四、删除 Worktree 后 Branch 怎么办

这是非常重要的生命周期问题。

```text
Worktree
和
Branch
```

应该是两个资源。

所以：

```text
git worktree remove
```

之后，不应该在 `remove()` 里自动偷偷删除 Branch。

推荐：

```text
remove_worktree()
负责释放执行目录

delete_task_branch()
负责删除 Git Branch
```

以后 Task Lifecycle：

```text
Task SUCCESS
→ Commit / Merge
→ remove Worktree
→ 确认 Branch 已合并
→ delete Branch


Task ABORT
→ Rollback / 用户确认
→ remove Worktree
→ 用户确认可丢弃
→ delete Branch
```

不要把它们揉成：

```python
manager.remove_everything()
```

---

# 五十五、`git worktree prune` 是什么

如果用户直接：

```bash
rm -rf /tmp/codeteam/task-001
```

而没有：

```bash
git worktree remove
```

那么物理目录消失了，但 Main Repository 的：

```text
.git/worktrees/...
```

可能还残留管理信息。

Git 提供：

```bash
git worktree prune
```

清理失效的 Worktree Metadata；Git 也会在后续 GC 时按过期策略清理。([Git][6])

你的 Manager 第一版：

```text
永远用 git worktree remove
```

不要直接：

```python
shutil.rmtree(worktree)
```

---

# 五十六、Worktree Lock 是什么

Git 还支持：

```bash
git worktree lock
```

例如 Worktree 放在：

```text
可移动硬盘
网络盘
某个临时挂载点
```

Git 可能发现路径暂时不存在并认为它可以 Prune。

Lock 可以告诉 Git：

```text
这是合法 Worktree，
不要因为暂时不可访问就清理 Metadata。
```

Git 还支持 `git worktree add --lock`，避免创建后再 Lock 的竞态。([Git][6])

CodeTeam 第一版不需要默认 Lock。

因为：

```text
你的 Worktree 是本机临时执行目录
而且任务结束本来就应该清理
```

---

# 五十七、Branch Conflict 应该怎样处理

第一次：

```python
manager.create(
    task_id="task-001",
    base_ref="main",
)
```

成功：

```text
codeteam/task-001
```

第二次：

```python
manager.create(
    task_id="task-001",
    base_ref="main",
)
```

应该：

```text
BranchAlreadyExistsError
```

而不是：

```text
偷偷重新使用旧 Worktree
```

也不是：

```text
-B reset Branch
```

也不是：

```text
--force
```

---

# 五十八、为什么这对 Agent 很重要

假设旧：

```text
codeteam/task-001

已经有 3 个 Commit
```

Agent Manager 因为 Task ID 冲突而：

```text
-B main
```

等于可能把用户之前的 Task Branch 状态重置。

这属于非常严重的 Agent Runtime Bug。

所以：

> **Name collision 必须显式处理，绝不能用 Force 解决。**

---

# 五十九、Worktree Path Conflict

假设：

```text
/tmp/codeteam/task-001
```

已经是普通用户目录：

```text
task-001/
└── notes.txt
```

Agent 创建 Worktree 时：

```text
不能覆盖
不能删除
不能复用
```

返回：

```text
WorktreePathConflictError
```

尤其不要：

```python
shutil.rmtree(path)
```

然后继续。

---

# 六十、Main Worktree 也要受到保护

假设：

```text
manager.list()[0]
```

是：

```text
/project
branch=main
is_main=True
```

必须：

```python
manager.remove(main)
```

直接在业务层拒绝。

Git 自己也不允许 `git worktree remove` 删除 Main Worktree。([Git][12])

---

# 六十一、两个 Worktree 并行测试是今天最重要的测试

Baseline：

```python
# src/value.py

VALUE = "base"
```

创建：

```python
task1 = manager.create(
    task_id="task-001",
    base_ref="main",
)

task2 = manager.create(
    task_id="task-002",
    base_ref="main",
)
```

然后：

```python
Path(
    task1.path,
    "src/value.py",
).write_text(
    'VALUE = "task-001"\n'
)

Path(
    task2.path,
    "src/value.py",
).write_text(
    'VALUE = "task-002"\n'
)
```

断言：

```python
assert (
    Path(
        task1.path,
        "src/value.py",
    ).read_text()
    == 'VALUE = "task-001"\n'
)

assert (
    Path(
        task2.path,
        "src/value.py",
    ).read_text()
    == 'VALUE = "task-002"\n'
)

assert (
    repo_root / "src/value.py"
).read_text() == (
    'VALUE = "base"\n'
)
```

这就是本日最核心验收：

```text
Agent A ≠ Agent B ≠ Human Main Workspace
```

---

# 六十二、创建 Worktree 测试

```python
def test_create_worktree(
    repo: Path,
    manager: WorktreeManager,
) -> None:
    base_sha = git_output(
        repo,
        "rev-parse",
        "main",
    )

    info = manager.create(
        task_id="task-001",
        base_ref="main",
    )

    assert (
        info.branch
        == "codeteam/task-001"
    )

    assert (
        Path(info.path).exists()
    )

    assert info.head_sha == base_sha

    branch = git_output(
        Path(info.path),
        "branch",
        "--show-current",
    )

    assert (
        branch
        == "codeteam/task-001"
    )
```

---

# 六十三、两个 Worktree 测试

除了文件内容隔离，再测试 Git 状态：

```python
assert manager.is_dirty(
    Path(task1.path)
)

assert manager.is_dirty(
    Path(task2.path)
)

assert not git_is_dirty(
    repo_root
)
```

如果 Task 001 Commit：

```text
只推进：
codeteam/task-001
```

不应推进：

```text
main
codeteam/task-002
```

---

# 六十四、Branch 名冲突测试

```python
def test_branch_conflict(
    repo: Path,
    manager: WorktreeManager,
) -> None:
    git(
        repo,
        "branch",
        "codeteam/task-001",
        "main",
    )

    with pytest.raises(
        BranchAlreadyExistsError
    ):
        manager.create(
            task_id="task-001",
            base_ref="main",
        )
```

同时断言：

```text
没有创建 Worktree Path
没有修改已有 Branch
```

---

# 六十五、Worktree Path 冲突测试

预先：

```python
target = (
    manager.worktrees_root
    / "task-001"
)

target.mkdir(
    parents=True
)

(target / "important.txt").write_text(
    "do not delete"
)
```

调用：

```python
with pytest.raises(
    WorktreePathConflictError
):
    manager.create(
        task_id="task-001",
        base_ref="main",
    )
```

然后：

```python
assert (
    target / "important.txt"
).read_text() == "do not delete"
```

---

# 六十六、删除 Worktree

```python
def test_remove_clean_worktree(
    manager: WorktreeManager,
) -> None:
    info = manager.create(
        task_id="task-001",
        base_ref="main",
    )

    path = Path(info.path)

    manager.remove(
        task_id="task-001"
    )

    assert not path.exists()

    assert all(
        item.path != str(path)
        for item in manager.list()
    )
```

Branch 是否还存在：

```python
assert manager.branch_exists(
    "codeteam/task-001"
)
```

这可以帮助你建立：

```text
Worktree 生命周期
≠
Branch 生命周期
```

的认识。

---

# 六十七、Dirty Worktree 禁止删除

```python
def test_dirty_worktree_refuses_removal(
    manager: WorktreeManager,
) -> None:
    info = manager.create(
        task_id="task-001",
        base_ref="main",
    )

    file = (
        Path(info.path)
        / "src/value.py"
    )

    file.write_text(
        'VALUE = "changed"\n'
    )

    with pytest.raises(
        DirtyWorktreeError
    ):
        manager.remove(
            task_id="task-001"
        )

    assert Path(info.path).exists()
```

再测 Untracked：

```python
Path(
    info.path,
    "new_file.txt",
).write_text("new")
```

一样要 Dirty。

---

# 六十八、为什么 Dirty Worktree 必须拒绝删除

假设 Agent 工作 30 分钟：

```text
改了 5 个文件
新增 2 个测试
测试已经通过
```

结果 Task Manager 因某个异常：

```text
直接 worktree remove --force
```

就可能把没有 Commit 的修改直接丢掉。

所以：

```text
Dirty Worktree
→ 不能直接删除
```

下一阶段才允许：

```text
Checkpoint
Commit
Rollback
Explicit Discard
```

来决定如何处理。

---

# 六十九、`list --porcelain -z` 测试

至少要覆盖：

```text
main
linked branch
detached
path with spaces
```

实际测试：

```python
infos = manager.list()

assert any(
    info.is_main
    for info in infos
)

task = next(
    info
    for info in infos
    if info.branch
    == "codeteam/task-001"
)

assert not task.is_detached
```

Parser 还建议独立测试：

```python
raw = (
    b"worktree /repo\x00"
    b"HEAD aaaaaa\x00"
    b"branch refs/heads/main\x00"
    b"\x00"
    b"worktree /tmp/task with space\x00"
    b"HEAD bbbbbb\x00"
    b"detached\x00"
    b"\x00"
)
```

确保：

```text
/tmp/task with space
```

不被拆坏。

---

# 七十、不存在 Base Commit

```python
def test_invalid_base_ref(
    manager: WorktreeManager,
) -> None:
    with pytest.raises(
        BaseRefNotFoundError
    ):
        manager.create(
            task_id="task-001",
            base_ref=(
                "definitely-not-a-ref"
            ),
        )
```

并断言：

```text
没有 Branch
没有 Worktree
```

这也是为什么：

```text
resolve base
```

一定要发生在：

```text
create branch
create path
```

之前。

---

# 七十一、额外建议做的五个测试

今天最低要求是 8 类，但我建议再增加：

| 测试                       | 目的            |
| ------------------------ | ------------- |
| invalid task id          | Branch Naming |
| Main Worktree 删除         | 防误删           |
| Untracked Dirty          | 防丢新文件         |
| Detached Worktree parser | HEAD 模型       |
| 同一 Branch 已在其他 Worktree  | 验证 Git 防护     |

尤其：

```text
同 Branch 多 Worktree
```

可以帮助你真正理解为什么：

```text
Branch Ref 共享
HEAD / Index 独立
```

---

# 七十二、Manager 不应该暴露 `force`

这是今天一个非常重要的 API 设计原则。

不要：

```python
manager.create(
    ...,
    force=True,
)

manager.remove(
    ...,
    force=True,
)
```

至少你的 Coding Agent Tool Layer 不应该有它。

因为 Git Worktree 中的 `--force` 可以绕过“Branch 已在其他 Worktree 使用”“Worktree 不干净”等重要安全保护。([Git][6])

更好的 API：

```python
create(...)
```

失败：

```text
BranchAlreadyExists
PathConflict
```

交给上层显式处理。

---

# 七十三、WorktreeManager 和 Day 1 GitWorkspace 怎么连接

以后：

```python
task = manager.create(
    task_id="task-001",
    base_ref="main",
)

workspace = GitWorkspace(
    Path(task.path)
)
```

然后：

```python
workspace.check_patch(patch)
workspace.apply_patch(patch)
workspace.diff()
```

完整：

```text
Main Repo
   │
   ▼
WorktreeManager
   │
   ├── Task 001
   │      │
   │      ▼
   │  GitWorkspace
   │      │
   │      ▼
   │  Patch Runtime
   │
   └── Task 002
          │
          ▼
      GitWorkspace
          │
          ▼
      Patch Runtime
```

这就形成了真正的：

```text
Task-scoped GitWorkspace
```

---

# 七十四、一个未来 Multi-Agent 系统应该怎样看待 Worktree

以后你的 Lead Agent 不应该告诉 Worker：

```text
你的仓库是 /project
```

而应该给：

```python
WorkerContext(
    task_id="task-001",
    workspace_path=(
        "/tmp/codeteam/.../task-001"
    ),
    branch="codeteam/task-001",
    base_sha="8ac347...",
)
```

Worker 的所有：

```text
read_file
apply_patch
run_test
git_diff
```

默认 Root 都应该是：

```text
workspace_path
```

它甚至不应该知道 Main Repository 的可写路径。

---

# 七十五、Worktree 是隔离层，但还不是安全 Sandbox

这点今天也要明确。

Worktree 可以阻止：

```text
Agent A 正常修改 Task B 的 Working Tree
```

但如果 Agent 拥有：

```bash
rm -rf /tmp/codeteam/task-002
```

它仍然可以主动越界。

因此：

```text
Git Worktree
=
版本与工作目录隔离

不是：
Security Sandbox
```

第三周 Day 4～6 的：

```text
CommandPolicy
Path Boundary
Docker Sandbox
```

才负责真正的权限安全。

所以整个架构最终是：

```text
Worktree
解决：
任务状态隔离

CommandPolicy
解决：
操作意图约束

Sandbox
解决：
操作系统级权限边界
```

---

# 七十六、今天推荐的目录

```text
codeteam/
└── git/
    ├── __init__.py
    ├── models.py
    ├── branch.py
    ├── worktree.py
    ├── workspace.py
    └── errors.py

tests/
└── git/
    ├── conftest.py
    ├── test_branch_naming.py
    ├── test_worktree_parser.py
    ├── test_worktree_create.py
    ├── test_worktree_isolation.py
    └── test_worktree_remove.py
```

其中：

```text
branch.py
→ BranchNamingPolicy

worktree.py
→ WorktreeManager

models.py
→ WorktreeInfo

workspace.py
→ 昨天 GitWorkspace
```

---

# 七十七、完整的 `WorktreeManager` 骨架

你今天不用一字不差照抄，但实现结构建议接近下面这样：

```python
class WorktreeManager:
    def __init__(
        self,
        *,
        repo_root: Path,
        worktrees_root: Path,
        naming_policy: BranchNamingPolicy,
    ) -> None:
        self.repo_root = (
            repo_root.resolve(strict=True)
        )

        self.worktrees_root = (
            worktrees_root.resolve(
                strict=False
            )
        )

        self.naming_policy = naming_policy

    def create(
        self,
        *,
        task_id: str,
        base_ref: str,
    ) -> WorktreeInfo:
        branch = (
            self.naming_policy
            .branch_for(task_id)
        )

        self.validate_branch(branch)

        base_sha = self.resolve_commit(
            base_ref
        )

        if self.branch_exists(branch):
            raise BranchAlreadyExistsError(
                branch
            )

        path = self.path_for_task(
            task_id
        )

        self.validate_new_path(path)

        result = self.run_git(
            "worktree",
            "add",
            "-b",
            branch,
            str(path),
            base_sha,
            timeout=60,
        )

        if result.returncode != 0:
            raise GitWorktreeCommandError(
                self.decode_stderr(result)
            )

        info = self.get_by_path(path)

        if info is None:
            raise GitWorktreeCommandError(
                "Created worktree "
                "cannot be rediscovered"
            )

        if info.branch != branch:
            raise GitWorktreeCommandError(
                "Branch postcondition failed"
            )

        if info.head_sha != base_sha:
            raise GitWorktreeCommandError(
                "HEAD postcondition failed"
            )

        info.task_id = task_id
        info.base_ref = base_ref
        info.base_sha = base_sha

        return info

    def list(
        self,
    ) -> list[WorktreeInfo]:
        ...

    def get(
        self,
        task_id: str,
    ) -> WorktreeInfo | None:
        ...

    def remove(
        self,
        *,
        task_id: str,
    ) -> None:
        ...

    def is_dirty(
        self,
        path: Path,
    ) -> bool:
        ...

    def resolve_commit(
        self,
        ref: str,
    ) -> str:
        ...

    def branch_exists(
        self,
        branch: str,
    ) -> bool:
        ...
```

---

# 七十八、今天的手工实验 1：Branch 与 HEAD

先不要编码。

创建测试仓库：

```bash
mkdir branch-lab
cd branch-lab

git init
git config user.name "Test User"
git config user.email "test@example.com"

echo hello > file.txt

git add .
git commit -m "baseline"

git branch -M main
```

查看：

```bash
git branch --show-current
git rev-parse HEAD
git symbolic-ref HEAD
```

然后：

```bash
git branch feature-a
```

再：

```bash
git branch
git branch --show-current
```

你应该观察到：

```text
feature-a 已存在

但：
HEAD 仍然是 main
```

然后：

```bash
git switch feature-a
```

再次观察。

---

# 七十九、手工实验 2：Detached HEAD

执行：

```bash
BASE=$(git rev-parse HEAD)

git switch --detach "$BASE"
```

观察：

```bash
git branch --show-current
```

应该为空。

但：

```bash
git rev-parse HEAD
```

仍然返回 Commit SHA。

这正好帮助你理解：

```text
Current Branch
可能不存在

Current Commit
仍然存在
```

所以你的模型中不要写：

```python
branch: str
```

而应：

```python
branch: str | None
```

---

# 八十、手工实验 3：真正创建两个 Worktree

回到 main：

```bash
git switch main
```

创建：

```bash
git worktree add \
  -b task-a \
  ../task-a \
  main
```

再：

```bash
git worktree add \
  -b task-b \
  ../task-b \
  main
```

运行：

```bash
git worktree list
```

然后分别：

```bash
cd ../task-a
echo task-a > file.txt

cd ../task-b
cat file.txt
```

应该仍然是：

```text
hello
```

回 Main：

```bash
cd ../branch-lab
cat file.txt
```

还是：

```text
hello
```

这一步如果亲自做过，Worktree 的概念基本就不会再混乱。

---

# 八十一、手工实验 4：同 Branch 不能正常检出两次

假设：

```text
task-a
```

已经在：

```text
../task-a
```

执行：

```bash
git worktree add \
  ../task-a-2 \
  task-a
```

默认应该被 Git 拒绝，因为该 Branch 已经在另一个 Worktree 中 Checkout。([Git][6])

这一步非常重要。

它会让你真正理解：

```text
为什么 Task Branch 必须唯一。
```

---

# 八十二、手工实验 5：Porcelain

运行：

```bash
git worktree list \
  --porcelain
```

然后：

```bash
git worktree list \
  --porcelain \
  -z \
  > worktrees.bin
```

Python：

```python
data = Path(
    "worktrees.bin"
).read_bytes()

print(
    data.replace(
        b"\0",
        b"<NUL>\n",
    )
)
```

亲自观察：

```text
worktree
HEAD
branch
detached
```

字段。

---

# 八十三、今天的时间安排

| 阶段 |     时间 | 内容                            | 产出                       |
| -- | -----: | ----------------------------- | ------------------------ |
| 1  | 45 min | Branch Ref / HEAD             | 手画 Ref 图                 |
| 2  | 35 min | `git branch` / `git switch`   | branch-lab               |
| 3  | 30 min | Detached HEAD                 | detached 实验              |
| 4  | 50 min | Worktree 原理                   | 两 Worktree 实验            |
| 5  | 30 min | Cline / Codex 工业实践            | 对比笔记                     |
| 6  | 45 min | `WorktreeInfo` + Naming       | `models.py`, `branch.py` |
| 7  | 90 min | `WorktreeManager.create/list` | `worktree.py`            |
| 8  | 45 min | Dirty / Remove                | `remove()`               |
| 9  | 90 min | 8～15 个测试                      | `tests/git/`             |
| 10 | 30 min | 并行隔离验收                        | isolation report         |

总学习/开发时间约：

```text
7～8 小时
```

---

# 八十四、今天至少完成的测试矩阵

| 场景                  | 预期                        |
| ------------------- | ------------------------- |
| 创建 Worktree         | 成功                        |
| task-001 + task-002 | 完全独立                      |
| 修改 task-001         | task-002 不变               |
| 修改 task-001         | main 不变                   |
| Branch 已存在          | 拒绝                        |
| Path 已存在            | 拒绝                        |
| Clean Worktree 删除   | 成功                        |
| Dirty Tracked       | 删除失败                      |
| Dirty Untracked     | 删除失败                      |
| Porcelain `-z`      | 正确解析                      |
| Path 带空格            | 正确解析                      |
| Detached Record     | 正确解析                      |
| Base Ref 不存在        | 创建前失败                     |
| Main Worktree 删除    | 拒绝                        |
| Invalid Task ID     | Sanitizer / Validation 正确 |

做到 12～15 个测试比较合适。

---

# 八十五、今天必须能回答的 20 个问题

1. Branch 本质上是什么？
2. `refs/heads/main` 中保存的是什么？
3. `HEAD` 和 Branch 有什么区别？
4. Commit 后为什么 Branch 会“向前移动”？
5. `git branch foo` 为什么不会改变当前文件？
6. `git switch foo` 会改变哪些 Git 状态？
7. `git switch -c foo` 和 `git branch foo && git switch foo` 有何区别？
8. Detached HEAD 是什么？
9. Detached HEAD 下能不能 Commit？
10. 为什么临时 Agent 特别适合 Detached HEAD？
11. Main Worktree 和 Linked Worktree 分别是什么？
12. Worktree 和 Clone 最核心的差别是什么？
13. 多 Worktree 哪些状态共享？
14. 为什么 HEAD 和 Index 必须是 per-worktree？
15. 为什么一个 Branch 默认不能同时 Checkout 到两个 Worktree？
16. 为什么 Worktree 隔离不能避免未来 Merge Conflict？
17. 为什么 Linked Worktree 中 `.git` 通常不是目录？
18. 为什么程序必须使用 `git worktree list --porcelain -z`？
19. 为什么 Dirty Worktree 不能直接删除？
20. 为什么 `WorktreeManager` 不应该向 Agent 暴露 `force=True`？

---

# 八十六、今天的最终验收

今天结束时，你应该达到下面这条完整链路：

```text
Task
 │
 ▼
task_id
 │
 ▼
BranchNamingPolicy
 │
 ▼
codeteam/task-001
 │
 ▼
git check-ref-format
 │
 ▼
resolve base_ref
 │
 ▼
main → immutable base_sha
 │
 ▼
check branch collision
 │
 ▼
check path collision
 │
 ▼
git worktree add -b
 │
 ▼
Linked Worktree
 │
 ▼
parse worktree list --porcelain -z
 │
 ▼
verify:
branch
HEAD
path
 │
 ▼
WorktreeInfo
 │
 ▼
GitWorkspace
 │
 ▼
Worker Agent
```

最终工程上最值得记住的不是 `git worktree add` 这条命令，而是下面四句话：

```text
Branch
=
Task 的 Git 身份

Worktree
=
Task 的文件系统执行空间

HEAD + Index
=
每个 Task 独立的 Git 工作状态

Shared Object DB + Shared Refs
=
所有 Task 仍属于同一个 Repository
```

而到了 Multi-Agent Coding Agent 中，就会进一步变成：

```text
Task
→ Unique Branch
→ Unique Worktree
→ Unique Worker
→ Unique Checkpoint Chain
→ Diff
→ Review
→ Merge
```

这就是你后续实现 `CheckpointManager`、Worker Agent 并行和 Merge Manager 的底层隔离基础。

[1]: https://git-scm.com/docs/git "Git - git Documentation"
[2]: https://git-scm.com/docs/git-branch "Git - git-branch Documentation"
[3]: https://git-scm.com/docs/git-switch "Git - git-switch Documentation"
[4]: https://git-scm.com/docs/git-checkout "Git - git-checkout Documentation"
[5]: https://developers.openai.com/codex/environments/git-worktrees?utm_source=chatgpt.com "Worktrees | ChatGPT Learn"
[6]: https://git-scm.com/docs/git-worktree "Git - git-worktree Documentation"
[7]: https://docs.cline.bot/usage/kanban "Kanban - Cline"
[8]: https://docs.cline.bot/kanban/core-workflow "Core Workflow - Cline"
[9]: https://docs.github.com/copilot/concepts/agents/cloud-agent/about-cloud-agent?utm_source=chatgpt.com "About GitHub Copilot cloud agent"
[10]: https://git-scm.com/docs/git-rev-parse?utm_source=chatgpt.com "Git - git-rev-parse Documentation"
[11]: https://git-scm.com/docs/git-check-ref-format "Git - git-check-ref-format Documentation"
[12]: https://git-scm.com/docs/git-worktree?utm_source=chatgpt.com "git-worktree Documentation - Git"
