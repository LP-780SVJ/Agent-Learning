# 第 3 周 Day 1：Git Diff 与 Patch

今天这一课非常关键。前两周你的 Coding Agent 主要是在“读代码、找代码”；从今天开始，它第一次真正进入：

> **修改代码，但不能把用户仓库改坏。**

Day 1 最终应该建立这样一条安全编辑链路：

```text
LLM / Worker Agent
        │
        │  proposed patch
        ▼
┌───────────────────────┐
│    PatchValidator     │
│                       │
│  1. Patch 大小检查   │
│  2. 提取影响路径      │
│  3. 仓库边界检查      │
│  4. git apply --check │
└───────────┬───────────┘
            │
      check success
            ▼
┌───────────────────────┐
│     GitWorkspace      │
│                       │
│     git apply         │
└───────────┬───────────┘
            │
            ▼
        git diff HEAD
            │
            ▼
     交给 Agent / Reviewer
```

今天需要真正理解的不是几条 Git 命令，而是三个工程概念：

```text
Diff        = 描述“发生了什么变化”
Patch       = 一份“可以尝试应用的变化”
Validation  = 在真正写磁盘之前证明这份变化可接受
```

---

# 一、先真正理解 HEAD、Index、Working Tree

Git 的很多命令之所以难，是因为 Git 同时维护三个版本。

可以先把它理解成：

```text
                    Git Repository

               HEAD
                 │
                 │ 最近一次 Commit
                 ▼
        ┌─────────────────┐
        │ Commit Snapshot │
        └─────────────────┘

                 │
                 │ git add
                 ▼
        ┌─────────────────┐
        │      Index      │
        │  / Staging Area │
        └─────────────────┘

                 │
                 │ 当前磁盘
                 ▼
        ┌─────────────────┐
        │  Working Tree   │
        └─────────────────┘
```

Git 官方的 `git status` 定义正是围绕这三者展开：它分别观察 **HEAD 与 Index 的差异**、**Index 与 Working Tree 的差异**，以及未被 Git 跟踪的 Working Tree 文件。([Git][1])

---

# 二、HEAD 是什么

可以把：

```text
HEAD
```

理解成：

> **“我当前工作基于哪个 Commit？”**

例如：

```text
A --- B --- C
          ↑
         HEAD
```

当前：

```text
HEAD = C
```

如果 `C` 中：

```python
def add(a, b):
    return a - b
```

那么 HEAD 保存的仍然是这个版本。

即使你把磁盘上的文件改成：

```python
def add(a, b):
    return a + b
```

HEAD 仍然没有变化。

---

# 三、Index 是什么

Index 经常被叫做：

```text
Staging Area
暂存区
```

但从 Coding Agent 的角度，可以把它理解成：

> **“如果我现在 commit，Git 准备提交的文件快照。”**

例如开始时：

```text
HEAD:
return a - b

Index:
return a - b

Working Tree:
return a - b
```

修改文件后：

```text
HEAD:
return a - b

Index:
return a - b

Working Tree:
return a + b
```

然后：

```bash
git add calculator.py
```

变成：

```text
HEAD:
return a - b

Index:
return a + b

Working Tree:
return a + b
```

---

# 四、Working Tree 是什么

Working Tree 就是 Agent 真正读写的磁盘目录：

```text
repo/
├── src/
│   └── calculator.py
├── tests/
└── pyproject.toml
```

当 Coding Agent 调用：

```text
apply_patch
write_file
```

它首先改变的是：

```text
Working Tree
```

而不是：

```text
HEAD
```

通常也不应该自动修改：

```text
Index
```

这一点对你的 Agent Runtime 很重要：

> **Agent 修改代码 ≠ Agent 自动决定哪些内容应该被 staged。**

因此第三周第一版推荐：

```text
git apply
```

而不是：

```text
git apply --index
```

前者默认只修改 Working Tree；`--index` 则要求同时把 Patch 应用到 Index。Git 官方也明确区分了这两种行为。([Git][2])

---

# 五、三个 `git diff` 到底分别在看什么

这是今天最需要完全掌握的地方。

Git 官方给出的语义非常明确：

```text
git diff
Working Tree ↔ Index

git diff --cached
Index ↔ HEAD

git diff HEAD
Working Tree ↔ HEAD
```

([Git][3])

可以画成：

```text
HEAD
 │
 │  git diff --cached
 ▼
Index
 │
 │  git diff
 ▼
Working Tree


HEAD
 │
 │  git diff HEAD
 └──────────────────► Working Tree
```

---

# 六、用一个完整例子理解三个 Diff

初始版本：

```python
def add(a, b):
    return a - b
```

状态：

| 层            | 内容             |
| ------------ | -------------- |
| HEAD         | `return a - b` |
| Index        | `return a - b` |
| Working Tree | `return a - b` |

这时三个命令都没有输出。

---

## 第一步：修改代码，但不 `git add`

改成：

```python
def add(a, b):
    return a + b
```

状态：

| 层            | 内容      |
| ------------ | ------- |
| HEAD         | `a - b` |
| Index        | `a - b` |
| Working Tree | `a + b` |

于是：

```bash
git diff
```

有变化。

```bash
git diff --cached
```

没有变化。

```bash
git diff HEAD
```

有变化。

Git 官方将无参数 `git diff` 定义为 Working Tree 相对 Index 尚未 staged 的变化，而 `git diff HEAD` 是 Working Tree 相对指定 Commit 的变化。([Git][3])

---

## 第二步：执行 `git add`

```bash
git add calculator.py
```

现在：

| 层            | 内容      |
| ------------ | ------- |
| HEAD         | `a - b` |
| Index        | `a + b` |
| Working Tree | `a + b` |

于是：

```text
git diff
→ 空

git diff --cached
→ 有

git diff HEAD
→ 有
```

---

## 第三步：暂存之后又继续修改

现在又把：

```python
return a + b
```

改成：

```python
return int(a) + int(b)
```

但没有再次 `git add`。

状态：

| 层            | 内容                |
| ------------ | ----------------- |
| HEAD         | `a - b`           |
| Index        | `a + b`           |
| Working Tree | `int(a) + int(b)` |

那么：

```text
git diff

比较：
Index
a + b

与：

Working Tree
int(a) + int(b)
```

而：

```text
git diff --cached

比较：
HEAD
a - b

与：

Index
a + b
```

而：

```text
git diff HEAD

比较：
HEAD
a - b

与：

Working Tree
int(a) + int(b)
```

---

# 七、Coding Agent 最常用哪个？

对于 Agent Task 的审计，我建议默认：

```bash
git diff HEAD
```

因为你真正想回答的是：

> **“从这个 Task 的基准 Commit 开始，当前工作目录总共发生了什么变化？”**

但这里有一个非常重要的坑：

> `git diff HEAD` **不会显示普通 untracked 文件。**

例如 Agent 创建：

```text
tests/test_new_feature.py
```

但没有 `git add`，这个文件不会自然出现在普通 `git diff HEAD` 中；Git 的 `status` 会单独列出 untracked 文件。([Git][1])

所以工业级：

```python
workspace.changed_files()
```

不能只运行：

```bash
git diff HEAD --name-only
```

还必须补：

```bash
git ls-files \
  --others \
  --exclude-standard \
  -z
```

你第二周 RepositoryScanner 已经学过这个问题。

---

# 八、什么是 Unified Diff

Git 默认的文本 Patch 是一种扩展后的 Unified Diff。`git diff -p`、`git show` 等都可以产生这种 Patch。Git 官方专门定义了 Git Extended Diff Format。([Git][4])

例如：

```diff
diff --git a/src/auth/service.py b/src/auth/service.py
index fce813a..a817b21 100644
--- a/src/auth/service.py
+++ b/src/auth/service.py
@@ -42,7 +42,9 @@ class AuthService:
     def refresh_token(self, token):
         payload = decode_token(token)
-        return self.repository.refresh(payload)
+        if payload.expired:
+            raise InvalidRefreshTokenError()
+        return self.repository.refresh(payload)
```

这其实可以拆成四层。

---

# 九、第一层：File Header

```diff
diff --git a/src/auth/service.py b/src/auth/service.py
```

表示：

```text
旧侧：
a/src/auth/service.py

新侧：
b/src/auth/service.py
```

`a/`、`b/` 不是你仓库真正拥有的目录。

它们是 Git Diff 默认使用的：

```text
source prefix
destination prefix
```

Git 官方默认就是 `a/` 和 `b/`。([Git][3])

因此：

```text
a/src/auth/service.py
```

实际对应：

```text
src/auth/service.py
```

这也是：

```text
git apply 默认 -p1
```

的原因之一：默认会去掉第一层路径成分。([Git][5])

---

# 十、第二层：Blob Header

```diff
index fce813a..a817b21 100644
```

其中：

```text
fce813a
旧 Blob

a817b21
新 Blob

100644
文件模式
```

这里的 Blob 可以简单理解成：

> Git 保存的“文件内容对象”。

---

# 十一、第三层：Old / New File

```diff
--- a/src/auth/service.py
+++ b/src/auth/service.py
```

表示：

```text
--- 旧内容

+++ 新内容
```

这和下面：

```diff
- old line
+ new line
```

是一致的。

---

# 十二、第四层：Hunk

核心：

```diff
@@ -42,7 +42,9 @@ class AuthService:
```

这就是：

```text
Hunk Header
```

含义：

```text
旧文件：
从第 42 行开始
覆盖 7 行

新文件：
从第 42 行开始
覆盖 9 行
```

所以：

```text
-42,7
```

代表旧侧。

```text
+42,9
```

代表新侧。

后面：

```text
class AuthService:
```

属于 Git 尝试提供给人的函数/代码上下文，不是 Hunk 位置计算本身。Git 的扩展 Diff 格式允许 Hunk Header 显示变化所在函数等上下文。([Git][6])

---

# 十三、Hunk 是什么

Hunk 可以理解成：

> **一个局部修改块。**

假设一个 2,000 行文件只改：

```text
50 行附近
700 行附近
1500 行附近
```

Git 不会输出整个文件。

而可能形成：

```text
Hunk 1
50 行附近

Hunk 2
700 行附近

Hunk 3
1500 行附近
```

这正是 Patch 特别适合 Coding Agent 的原因。

Agent 不需要重新生成整个：

```text
2,000 行文件
```

它只描述：

```text
3 个局部修改块
```

---

# 十四、Hunk 中三种行

例如：

```diff
     def refresh_token(self, token):
         payload = decode_token(token)
-        return self.repository.refresh(payload)
+        if payload.expired:
+            raise InvalidRefreshTokenError()
+        return self.repository.refresh(payload)
```

三种类型：

| 开头  | 含义           |
| --- | ------------ |
| 空格  | Context Line |
| `-` | 旧文件中删除       |
| `+` | 新文件中新增       |

注意：

```diff
- old
+ new
```

Git 没有真正的：

```text
modify line
```

修改本质上表示：

```text
delete old
+
add new
```

---

# 十五、Context Lines 为什么非常重要

默认情况下：

```bash
git diff
```

通常输出变化前后 **3 行上下文**；可用：

```bash
git diff -U5
```

改为前后 5 行。Git 官方当前文档明确说明默认 Context 为 3 行，除非 `diff.context` 配置覆盖。([Git][3])

例如真正变化只有：

```diff
-return old
+return new
```

Git 还会携带：

```diff
 def calculate():
     value = prepare()
-return old
+return new
     cleanup()
```

上下文的作用不只是“方便人看”。

还可以帮助：

```text
Patch 应用器确认：
我修改的是正确位置。
```

---

# 十六、为什么不能只靠行号

假设 Patch 生成时函数在：

```text
第 100 行
```

之后另一个工具在文件顶部增加了 5 行：

```text
现在函数到了 105 行
```

如果 Patch 系统只按照：

```text
第 100 行
```

硬改，会非常脆弱。

Unified Diff 会带：

```text
上下文行
+
被删除内容
```

帮助确定它是否仍然匹配目标区域。

所以可以把 Hunk 理解成：

```text
大概位置
+
旧内容
+
上下文指纹
+
新内容
```

---

# 十七、零 Context Patch 为什么不建议使用

Git 可以生成：

```bash
git diff -U0
```

这意味着：

```text
不携带普通上下文行
```

但 Git 官方明确说，`git apply` 默认期望 Unified Diff 至少带上下文，并指出 `--unidiff-zero` 绕过这种安全检查的方式不推荐使用。([Git][5])

因此你的 Coding Agent V1 应该明确禁止：

```text
--unidiff-zero
```

推荐 Patch：

```text
至少保留默认 Context
```

---

# 十八、为什么工业界非常依赖 Diff

这个东西不是 Git 的“附属显示功能”，实际上是现代代码开发工作流的核心对象。

## Google：CL 本质上是一个可审查的 Change

Google 把一个待审查的自包含改动称为：

```text
CL — Changelist
```

官方说明其他系统通常把它叫：

```text
change
patch
pull request
```

([Google GitHub][7])

更重要的是，Google 强烈推荐 Small CL：小改动更容易彻底 Review、更少引入 Bug、更容易 Merge，也更容易 Rollback；Google 还建议功能修改与测试一起提交。([Google GitHub][8])

这对 Coding Agent 有直接启示：

```text
不要让 Agent 一次重写 40 个文件。

更合理：
生成一个窄范围 Patch
→ 检查 Diff
→ 测试
→ 再继续下一步
```

这其实就是后面 Checkpoint 与 Multi-Agent Task 拆分的基础。

---

# 十九、GitHub：PR 的核心 Review 界面就是 Diff

GitHub Pull Request 的：

```text
Files changed
```

本质上就是 Base Branch 与 Compare Branch 的 Diff。GitHub 支持 Reviewer：

```text
逐文件看 Diff
逐行评论
对几行代码提出精确修改
一键应用 Suggestion
批量应用多个 Suggestion
```

([GitHub Docs][9])

这和你的 Agent 编辑工具非常相似：

```text
LLM 不需要说：
“请把 service.py 改一下。”

它应该给出：
一个精确、可审查、可验证的 Patch。
```

---

# 二十、Meta：甚至直接把一次代码变更叫“Diff”

Meta 公布的代码审查实践中直接写到：

> 在 Meta，一组针对代码库的变化就被称为一个 “diff”，并且每个 diff 都必须接受 Review。([Engineering at Meta][10])

Meta 的 Sapling 也是从其超大 Monorepo 工作流发展出来的源码管理系统；公开版本默认支持 Unified Diff，并允许通过 `-U` 调整上下文。([Sapling SCM][11])

所以你可以形成一个非常重要的工业理解：

```text
源码不是 Coding Agent 最合适的“变化单位”。

Diff / Patch 才是。
```

---

# 二十一、Diff 和 Patch 有什么区别

这两个词经常混着用，但概念上最好区分。

```text
Diff
=
描述两个状态之间有什么不同


Patch
=
一种编码后的 Diff，
可以尝试应用到另一个状态
```

例如：

```bash
git diff HEAD
```

得到：

```text
Diff
```

把输出保存：

```bash
git diff HEAD > change.patch
```

那么：

```text
change.patch
```

就可以被：

```bash
git apply change.patch
```

当成 Patch 使用。

---

# 二十二、`git apply` 到底做什么

核心命令：

```bash
git apply change.patch
```

它：

```text
读取 Patch
↓
检查目标文件
↓
匹配 Hunk
↓
修改 Working Tree
```

它**不会自动创建 Commit**。Git 官方明确说明 `git apply` 应用 Patch，但不会创建提交。([Git][2])

这非常适合 Agent。

你希望：

```text
Agent 修改
→ Review
→ Tests
→ 最终决定是否 Commit
```

而不是：

```text
Agent 每一次动作
→ 自动 Commit
```

---

# 二十三、`git apply --check`

这是今天最重要的一条命令：

```bash
git apply --check patch.diff
```

它的作用是：

> **看看 Patch 能不能应用，但不要真正修改文件。**

Git 官方定义：

```text
--check

检查 Patch 是否可以应用，
检测错误，
并关闭真正 Apply。
```

([Git][2])

于是 Coding Agent 应该永远：

```text
Patch
  ↓
git apply --check
  ↓
OK
  ↓
git apply
```

而不是：

```text
Patch
  ↓
直接 git apply
```

---

# 二十四、为什么即使有 `--check`，真正 `git apply` 仍然可能失败

这里有一个工业实现中非常重要的细节。

假设：

```text
12:00:00
git apply --check
→ OK

12:00:01
另一个进程修改文件

12:00:02
git apply
```

第二次仍然可能失败。

这叫：

```text
TOCTOU
Time Of Check To Time Of Use
```

所以：

```text
--check
```

只是：

```text
Preflight Validation
```

真正的：

```text
git apply
```

仍然是最终裁决者。

但好消息是：Git 默认 Apply 本身也具有我们需要的重要原子性。

---

# 二十五、Patch Atomicity：今天最重要的安全性质

假设 Patch 有两个 Hunk：

```text
Hunk 1
service.py
可以成功

Hunk 2
api.py
已经不匹配
```

你最不希望发生：

```text
service.py
已经修改

api.py
失败

仓库进入半修改状态
```

Git 官方当前文档明确说明：

> 默认情况下，如果某些 Hunk 无法应用，`git apply` 会让**整份 Patch 失败，而且不会修改 Working Tree**。([Git][5])

也就是：

```text
Patch
├── Hunk A ✅
├── Hunk B ✅
└── Hunk C ❌

最终：

A 不应用
B 不应用
C 不应用

整个 Patch 失败
```

这正是 Coding Agent 想要的：

```text
All-or-Nothing
```

---

# 二十六、为什么你的 Agent 必须禁止 `--reject`

因为：

```bash
git apply --reject patch.diff
```

改变了上述语义。

Git 官方说明：

```text
--reject

可以应用的部分仍然应用，
失败的 Hunk 写成 *.rej 文件。
```

([Git][5])

于是：

```text
Patch
├── Hunk A ✅ → 已经修改文件
├── Hunk B ✅ → 已经修改文件
└── Hunk C ❌ → xxx.rej
```

这对人工 Patch 工作流有时有用。

但对 Agent Runtime 非常糟糕：

```text
模型以为 Patch 失败
但仓库其实已经被改了一半
```

所以第三周第一版：

```text
永远禁止 --reject
```

---

# 二十七、Patch Context 错误

假设源文件实际是：

```python
def add(a, b):
    return a * b
```

但 Patch 认为旧内容是：

```diff
 def add(a, b):
-    return a - b
+    return a + b
```

运行：

```bash
git apply --check patch.diff
```

应该失败。

这非常重要。

因为这通常意味着：

```text
Agent 用的是过时上下文
文件已经被别人修改
LLM Hallucinated 原代码
Patch 针对了错误版本
```

所以：

> Patch Failure 不是坏事。

很多时候它是在保护仓库。

---

# 二十八、Patch Path Security

这是今天另一大重点。

恶意 Patch 可以尝试：

```diff
diff --git a/../../.ssh/config b/../../.ssh/config
```

或者：

```text
../../etc/passwd
```

你的系统必须保证：

```text
Agent 只能修改当前 Repository / Worktree
```

不能把：

```text
Patch = 文件修改权限
```

变成：

```text
Patch = 整台电脑写权限
```

---

# 二十九、Git 自己已经有第一层安全

Git 当前 `git apply` 默认会拒绝影响 Working Area 之外路径的 Patch。

官方甚至明确说这类路径可能是：

```text
mistake
or mischief
```

只有：

```bash
--unsafe-paths
```

才绕过这个保护。([Git][5])

因此第一条原则：

```text
永远不允许：

git apply --unsafe-paths
```

---

# 三十、为什么还要自己再做一次 Path Check

因为安全系统应该：

```text
Defense in Depth
```

即：

```text
Layer 1
PatchValidator 自己检查路径

Layer 2
Git apply 内部再次检查

Layer 3
后续 Worktree / Sandbox
从操作系统层限制写范围
```

不要把整个 Agent 的安全性押在：

```text
“Git 应该会拒绝吧”
```

上。

---

# 三十一、不要自己用 `split(" ")` 解析 Patch 文件名

考虑这个合法文件：

```text
src/legacy auth/user service.py
```

Patch Header 可能非常不好手工解析。

Git 的 Diff 格式还支持：

```text
空格
Tab
中文
换行
引号转义
Rename old/new path
```

Git 官方因此提供：

```text
-z
```

使用 NUL 作为机器可读分隔符。([Git][12])

所以这里推荐一个很实用的技巧：

> **让 Git 自己解析 Patch。**

例如：

```bash
git apply \
  --numstat \
  -z \
  -
```

输入 Patch 到 stdin。

它：

```text
解析 Patch
输出涉及文件
但不真正应用
```

`--numstat` 会关闭 Apply，而 `-z` 提供不被特殊文件名破坏的机器格式。Git 官方定义了普通文件和 Rename 情况下的 NUL 格式。([Git][2])

然后你的程序再检查这些路径。

---

# 三十二、路径检查不能只搜索 `..`

错误实现：

```python
if ".." in path:
    reject()
```

因为：

```text
src/version..py
```

可能完全合法。

同时下面还有：

```text
Windows:
C:\Users\...

UNC:
\\server\share

POSIX:
/etc/passwd

Symlink:
repo/outside -> /etc
```

正确逻辑是：

```python
root = workspace.resolve()
target = (root / path).resolve(strict=False)

if not target.is_relative_to(root):
    reject()
```

还需要额外拒绝：

```text
绝对路径
Windows Drive Path
.git/
```

---

# 三十三、Symlink Escape

例如仓库：

```text
repo/
├── src/
└── external -> /home/user
```

Patch 想修改：

```text
external/.ssh/config
```

从字符串看：

```text
external/.ssh/config
```

没有：

```text
../
```

但：

```python
(root / path).resolve()
```

可能得到：

```text
/home/user/.ssh/config
```

已经逃出仓库。

所以路径安全一定要基于：

```text
Canonical / Resolved Path
```

而不是字符串前缀。

第一版可以采取保守原则：

> Patch 中路径经过现有 Symlink 后解析到仓库外，一律拒绝。

---

# 三十四、New File Patch

新增文件的 Patch 常见：

```diff
diff --git a/src/new_service.py b/src/new_service.py
new file mode 100644
index 0000000..ad234ff
--- /dev/null
+++ b/src/new_service.py
@@ -0,0 +1,4 @@
+class NewService:
+    def run(self):
+        pass
```

这里：

```text
--- /dev/null
```

表示：

```text
旧文件不存在
```

Git Extended Diff Header 则仍然会有：

```text
diff --git a/src/new_service.py b/src/new_service.py
```

Git 官方文档明确说明，创建/删除在扩展 Header 和两行 Unified Header 中的表示方式并不完全一样。([Git][6])

---

# 三十五、Deleted File Patch

```diff
diff --git a/src/legacy.py b/src/legacy.py
deleted file mode 100644
index abcdef1..0000000
--- a/src/legacy.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def legacy():
-    pass
```

这里：

```text
+++ /dev/null
```

表示新版本中：

```text
文件不存在
```

---

# 三十六、Rename 不是 Git 保存的一条“重命名操作”

这个概念非常重要。

Git 的底层对象更接近：

```text
旧路径消失
+
新路径出现
```

然后 Diff 系统根据内容相似度：

```text
推断：
这可能是 Rename
```

所以：

```bash
git diff -M
```

中的：

```text
-M
--find-renames
```

就是 Rename Detection。

例如：

```text
old.py
→
new.py
```

如果内容高度相似，输出可能：

```diff
similarity index 98%
rename from old.py
rename to new.py
```

Git 官方定义 `-M<n>` 为基于内容相似度检测 Rename；默认阈值为 50%。([Git][13])

因此你的 Agent 工具为了结果稳定，建议显式：

```bash
--find-renames=50%
```

而不是依赖用户 Git 配置。

---

# 三十七、Rename 的工业意义

假设 Agent：

```text
删除 service.py
新建 auth_service.py
```

如果 Review 看到：

```text
- 800 行
+ 805 行
```

很难 Review。

如果识别成：

```text
rename service.py → auth_service.py
5 行修改
```

就非常清晰。

所以 Rename Detection 主要改善：

```text
Reviewability
```

而不是改变文件系统事实。

---

# 三十八、特殊文件名

测试中必须加入：

```text
src/file with spaces.py
src/中文模块.py
```

甚至理论上 POSIX 文件名还可以包含：

```text
Tab
换行
```

因此：

```python
output.decode().splitlines()
```

并不是可靠的机器路径解析方案。

需要：

```text
-z
+
NUL delimiter
```

例如：

```bash
git diff \
  --name-status \
  -z \
  HEAD
```

Git 官方明确说明 `--name-status -z` 会原样输出路径并以 NUL 结束，而不是对 unusual pathname 做字符串 quoting。([Git][14])

---

# 三十九、工业级 `GitWorkspace` 应该怎样设计

推荐不要让外部模块直接拼 Git 命令。

不要：

```python
subprocess.run(
    ["git", "diff", ...]
)
```

散落全项目。

统一：

```text
GitWorkspace
```

作为 Git Repository Gateway。

---

# 四十、数据模型：`GitDiff`

```python
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class GitChangeKind(str, Enum):
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNMERGED = "unmerged"
    UNTRACKED = "untracked"


class GitChange(BaseModel):
    kind: GitChangeKind

    path: str
    old_path: str | None = None

    similarity: int | None = None


class GitDiff(BaseModel):
    base_ref: str

    patch: str

    changes: list[GitChange]
    untracked_paths: list[str]

    additions: int = 0
    deletions: int = 0

    has_binary_changes: bool = False

    patch_bytes: int = 0
```

---

# 四十一、`PatchResult`

```python
class PatchStatus(str, Enum):
    VALID = "valid"

    SECURITY_REJECTED = "security_rejected"
    CHECK_FAILED = "check_failed"
    APPLY_FAILED = "apply_failed"

    APPLIED = "applied"


class PatchResult(BaseModel):
    status: PatchStatus

    patch_sha256: str

    affected_paths: list[str]

    stderr: str = ""
    stdout: str = ""

    applied: bool = False

    failure_reason: str | None = None
```

---

# 四十二、为什么 Patch 要有 SHA256

Agent 可能经历：

```text
生成 Patch
→ Validation
→ Approval
→ Apply
```

你最好确保中途处理的始终是：

```text
同一份 Patch
```

所以：

```python
hashlib.sha256(
    patch_bytes
).hexdigest()
```

可以作为：

```text
Patch Identity
```

以后 ApprovalManager 也可以审批：

```text
patch_sha256 = xxx
```

而不是模糊地：

```text
批准“那个修改”
```

---

# 四十三、PatchValidator 应该负责什么

建议职责：

```text
PatchValidator

输入：
Patch bytes

负责：
Patch 大小
Patch 是否为空
Patch 影响哪些路径
路径是否越界
是否涉及 .git
是否二进制 Patch
是否超过最大文件数
git apply --check

不负责：
真正修改文件
Commit
Rollback
测试
```

---

# 四十四、PatchValidator 第一版限制

我建议先限制：

```text
最大 Patch：
2 MiB

最大文件数：
50

文本 Patch：
允许

Binary Patch：
第一版拒绝

../../：
拒绝

绝对路径：
拒绝

.git：
拒绝

Symlink Escape：
拒绝
```

这些不是 Git 的统一标准，而是适合 Coding Agent MVP 的安全策略。

---

# 四十五、为什么第一版建议拒绝 Binary Patch

Git 当前实际上支持 Binary Patch；`--binary` 已经基本是兼容性选项。([Git][5])

但 Agent V1 最好：

```text
GIT binary patch
→ SECURITY / UNSUPPORTED
```

因为文本 Diff：

```text
人能 Review
模型能理解
可以做行级审计
```

而 Binary Patch：

```text
模型很难判断内容
Review 能力明显下降
```

以后再专门设计：

```text
Asset Tool
```

处理图片和二进制文件更合理。

---

# 四十六、用 Git 自己提取 Patch Paths

这是今天推荐你真正实现的方式。

```python
import os
import subprocess


def extract_patch_paths(
    root: Path,
    patch: bytes,
) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "apply",
            "--numstat",
            "-z",
            "-",
        ],
        cwd=root,
        input=patch,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        raise ValueError(
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    return parse_numstat_paths(
        result.stdout
    )
```

注意：

```text
--numstat
```

会关闭真正的 Apply，所以这里不会修改文件。([Git][2])

---

# 四十七、`--numstat -z` 的 Rename 格式

普通文件大致：

```text
3<TAB>1<TAB>src/file.py<NUL>
```

Rename 则是：

```text
3<TAB>1<TAB><NUL>
old.py<NUL>
new.py<NUL>
```

Git 官方专门这样设计，就是为了机器在不猜文件名的情况下识别单路径与双路径记录。([Git][12])

---

# 四十八、Parser

```python
def parse_numstat_paths(
    data: bytes,
) -> list[str]:
    paths: list[str] = []

    cursor = 0

    while cursor < len(data):
        tab1 = data.index(b"\t", cursor)
        tab2 = data.index(b"\t", tab1 + 1)

        path_end = data.index(
            b"\0",
            tab2 + 1,
        )

        first_path = data[
            tab2 + 1:path_end
        ]

        cursor = path_end + 1

        if first_path:
            paths.append(
                os.fsdecode(first_path)
            )
            continue

        # Rename / Copy
        old_end = data.index(
            b"\0",
            cursor,
        )

        old_path = data[
            cursor:old_end
        ]

        cursor = old_end + 1

        new_end = data.index(
            b"\0",
            cursor,
        )

        new_path = data[
            cursor:new_end
        ]

        cursor = new_end + 1

        paths.append(
            os.fsdecode(old_path)
        )
        paths.append(
            os.fsdecode(new_path)
        )

    return list(dict.fromkeys(paths))
```

使用：

```text
os.fsdecode
```

而不是：

```text
.decode("utf-8")
```

可以更好地处理文件系统中的非常规字节文件名。

---

# 四十九、Path Safety

```python
from pathlib import (
    Path,
    PurePosixPath,
    PureWindowsPath,
)


class PatchSecurityError(RuntimeError):
    pass


def validate_patch_path(
    root: Path,
    path_text: str,
) -> Path:
    posix = PurePosixPath(path_text)
    windows = PureWindowsPath(path_text)

    if (
        posix.is_absolute()
        or windows.is_absolute()
    ):
        raise PatchSecurityError(
            f"Absolute patch path rejected: "
            f"{path_text!r}"
        )

    if windows.drive:
        raise PatchSecurityError(
            f"Windows drive path rejected: "
            f"{path_text!r}"
        )

    if (
        path_text == ".git"
        or path_text.startswith(".git/")
    ):
        raise PatchSecurityError(
            "Patch cannot modify .git metadata"
        )

    canonical_root = root.resolve(
        strict=True
    )

    target = (
        canonical_root / path_text
    ).resolve(strict=False)

    if not target.is_relative_to(
        canonical_root
    ):
        raise PatchSecurityError(
            f"Patch escapes workspace: "
            f"{path_text!r}"
        )

    return target
```

---

# 五十、真正的 `check_patch()`

```python
import hashlib


class PatchValidator:
    def __init__(
        self,
        root: Path,
        *,
        max_patch_bytes: int = (
            2 * 1024 * 1024
        ),
        max_files: int = 50,
    ) -> None:
        self.root = root.resolve(
            strict=True
        )
        self.max_patch_bytes = (
            max_patch_bytes
        )
        self.max_files = max_files

    def validate(
        self,
        patch: str,
    ) -> PatchResult:
        patch_bytes = patch.encode(
            "utf-8"
        )

        digest = hashlib.sha256(
            patch_bytes
        ).hexdigest()

        if not patch_bytes.strip():
            return PatchResult(
                status=(
                    PatchStatus.CHECK_FAILED
                ),
                patch_sha256=digest,
                affected_paths=[],
                failure_reason="Empty patch",
            )

        if (
            len(patch_bytes)
            > self.max_patch_bytes
        ):
            return PatchResult(
                status=(
                    PatchStatus.SECURITY_REJECTED
                ),
                patch_sha256=digest,
                affected_paths=[],
                failure_reason=(
                    "Patch exceeds size limit"
                ),
            )

        if b"GIT binary patch" in patch_bytes:
            return PatchResult(
                status=(
                    PatchStatus.SECURITY_REJECTED
                ),
                patch_sha256=digest,
                affected_paths=[],
                failure_reason=(
                    "Binary patches are disabled"
                ),
            )

        try:
            paths = extract_patch_paths(
                self.root,
                patch_bytes,
            )

            if not paths:
                raise PatchSecurityError(
                    "Patch has no file changes"
                )

            if len(paths) > self.max_files:
                raise PatchSecurityError(
                    "Patch touches too many files"
                )

            for path in paths:
                validate_patch_path(
                    self.root,
                    path,
                )

        except (
            PatchSecurityError,
            ValueError,
        ) as exc:
            return PatchResult(
                status=(
                    PatchStatus.SECURITY_REJECTED
                ),
                patch_sha256=digest,
                affected_paths=[],
                failure_reason=str(exc),
            )

        result = subprocess.run(
            [
                "git",
                "apply",
                "--check",
                "-",
            ],
            cwd=self.root,
            input=patch_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            return PatchResult(
                status=(
                    PatchStatus.CHECK_FAILED
                ),
                patch_sha256=digest,
                affected_paths=paths,
                stderr=result.stderr.decode(
                    "utf-8",
                    errors="replace",
                ),
                failure_reason=(
                    "git apply --check failed"
                ),
            )

        return PatchResult(
            status=PatchStatus.VALID,
            patch_sha256=digest,
            affected_paths=paths,
        )
```

---

# 五十一、不要允许调用者传任意 `git apply` 参数

一个非常重要的设计。

不要设计：

```python
workspace.apply_patch(
    patch,
    args=["--reject", "--unsafe-paths"]
)
```

而是：

```python
workspace.apply_patch(
    patch
)
```

内部命令永久固定：

```text
git apply -
```

这样：

```text
--reject
--unsafe-paths
--unidiff-zero
--3way
```

根本没有机会从 Agent Tool Schema 进入系统。

这比写：

```python
if "--reject" in args:
```

更安全。

安全工程里通常应该：

```text
不要给危险能力，
再尝试检测危险用法。

而是：
根本不暴露这个能力。
```

---

# 五十二、文件 SHA256 Snapshot

为了满足你的验收：

```text
Patch 失败后
SHA256 前后一致
```

建议实现：

```python
import hashlib


def sha256_file(
    path: Path,
) -> str | None:
    if not path.exists():
        return None

    if not path.is_file():
        return None

    digest = hashlib.sha256()

    with path.open("rb") as file:
        while chunk := file.read(
            1024 * 1024
        ):
            digest.update(chunk)

    return digest.hexdigest()
```

Snapshot：

```python
def snapshot_paths(
    root: Path,
    paths: list[str],
) -> dict[str, str | None]:
    return {
        path: sha256_file(
            root / path
        )
        for path in paths
    }
```

这里：

```text
None
```

也有意义。

例如新增文件：

```text
Before:
None

After:
SHA256
```

---

# 五十三、`GitWorkspace.apply_patch()`

推荐流程：

```text
validate
↓
保存 affected path SHA256
↓
git apply
↓
失败？
    ↓
重新计算 SHA256
    ↓
assert unchanged
↓
成功
↓
返回新 Diff
```

实现：

```python
class GitWorkspace:
    def __init__(
        self,
        root: Path,
    ) -> None:
        self.root = root.resolve(
            strict=True
        )

        self.validator = PatchValidator(
            self.root
        )

    def check_patch(
        self,
        patch: str,
    ) -> PatchResult:
        return self.validator.validate(
            patch
        )

    def apply_patch(
        self,
        patch: str,
    ) -> PatchResult:
        validation = self.check_patch(
            patch
        )

        if validation.status != (
            PatchStatus.VALID
        ):
            return validation

        before = snapshot_paths(
            self.root,
            validation.affected_paths,
        )

        patch_bytes = patch.encode(
            "utf-8"
        )

        result = subprocess.run(
            [
                "git",
                "apply",
                "-",
            ],
            cwd=self.root,
            input=patch_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=10,
            check=False,
        )

        if result.returncode != 0:
            after = snapshot_paths(
                self.root,
                validation.affected_paths,
            )

            if before != after:
                raise RuntimeError(
                    "CRITICAL: failed git apply "
                    "changed workspace state"
                )

            return PatchResult(
                status=(
                    PatchStatus.APPLY_FAILED
                ),
                patch_sha256=(
                    validation.patch_sha256
                ),
                affected_paths=(
                    validation.affected_paths
                ),
                stdout=result.stdout.decode(
                    "utf-8",
                    errors="replace",
                ),
                stderr=result.stderr.decode(
                    "utf-8",
                    errors="replace",
                ),
                applied=False,
                failure_reason=(
                    "git apply failed"
                ),
            )

        return PatchResult(
            status=PatchStatus.APPLIED,
            patch_sha256=(
                validation.patch_sha256
            ),
            affected_paths=(
                validation.affected_paths
            ),
            stdout=result.stdout.decode(
                "utf-8",
                errors="replace",
            ),
            stderr=result.stderr.decode(
                "utf-8",
                errors="replace",
            ),
            applied=True,
        )
```

Git 已经保证默认 Apply 的原子性；这里再次做 Hash 验证属于 Agent Runtime 自己的 **Invariant Check**。([Git][5])

---

# 五十四、为什么工业系统喜欢这种 Invariant

你可以把：

```text
Git 文档保证
```

与：

```text
Agent Runtime 验收
```

分开。

第一层：

```text
Git 应该保证失败时不修改
```

第二层：

```text
CodeTeam 自己验证：
失败时前后 Snapshot 必须完全一致
```

这样未来：

```text
Git 版本变化
参数被误改
代码重构
```

导致行为改变时，测试会立即发现。

---

# 五十五、`workspace.diff()`

为了让输出不受用户 Git 配置干扰，建议显式控制关键选项：

```python
def diff(
    self,
    base_ref: str = "HEAD",
) -> GitDiff:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--find-renames=50%",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            base_ref,
            "--",
        ],
        cwd=self.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        timeout=10,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.decode(
                "utf-8",
                errors="replace",
            )
        )

    patch = result.stdout.decode(
        "utf-8",
        errors="replace",
    )

    changes = (
        self._tracked_changes(
            base_ref
        )
    )

    untracked = (
        self._untracked_paths()
    )

    return GitDiff(
        base_ref=base_ref,
        patch=patch,
        changes=[
            *changes,
            *[
                GitChange(
                    kind=(
                        GitChangeKind.UNTRACKED
                    ),
                    path=path,
                )
                for path in untracked
            ],
        ],
        untracked_paths=untracked,
        patch_bytes=len(result.stdout),
    )
```

这里非常重要：

```text
patch
```

与：

```text
changes
```

不是完全同义。

普通：

```text
git diff HEAD
```

不会包含纯 untracked 内容。

所以：

```text
GitDiff.changes
```

需要补充 untracked。

---

# 五十六、`changed_files()`

推荐机器读取：

```bash
git diff \
  --name-status \
  --find-renames=50% \
  -z \
  HEAD \
  --
```

再补：

```bash
git ls-files \
  --others \
  --exclude-standard \
  -z
```

不要：

```python
git diff --name-status
→ splitlines()
→ split("\t")
```

因为特殊文件名会破坏解析。

Git 的 `--name-status -z` 正是为机器场景设计的。([Git][14])

---

# 五十七、Git Change Status

需要支持：

| Git Status | 你的类型                   |
| ---------- | ---------------------- |
| `M`        | MODIFIED               |
| `A`        | ADDED                  |
| `D`        | DELETED                |
| `R90`      | RENAMED，90% similarity |
| `C90`      | COPIED                 |
| `T`        | TYPE_CHANGED           |
| `U`        | UNMERGED               |

Git 官方 Diff Format 对这些状态字母有正式定义。([Git][12])

---

# 五十八、新文件还有一个工程陷阱

假设 Agent 通过 Patch 创建：

```text
tests/test_refresh.py
```

由于我们使用的是：

```bash
git apply
```

而不是：

```bash
git apply --index
```

它通常仍然属于：

```text
Untracked
```

因此：

```bash
git diff HEAD
```

并不会把完整新文件内容自然放入普通 Diff。

工业实现有两种路线。

第一版建议：

```text
GitDiff.patch
= tracked patch

GitDiff.untracked_paths
= 未跟踪文件

Review 阶段：
对 untracked 文件单独生成 new-file diff
```

可以用：

```bash
git diff \
  --no-index \
  -- \
  /dev/null \
  path
```

生成“新增文件 Patch”。

注意 `git diff --no-index` 发现差异时退出码通常是 `1`，这代表“有差异”，不代表程序故障。

---

# 五十九、今日测试仓库

建议创建测试 Fixture：

```text
tests/
└── fixtures/
    └── git_repo/
```

但 pytest 测试里最好每次：

```text
tmp_path
→ git init
→ Commit 初始状态
```

这样完全隔离。

Helper：

```python
import subprocess
from pathlib import Path


def git(
    root: Path,
    *args: str,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=True,
    )


def create_repo(
    tmp_path: Path,
) -> Path:
    root = tmp_path / "repo"
    root.mkdir()

    git(root, "init")

    git(
        root,
        "config",
        "user.email",
        "test@example.com",
    )

    git(
        root,
        "config",
        "user.name",
        "Test User",
    )

    return root


def commit_all(
    root: Path,
    message: str = "baseline",
) -> None:
    git(root, "add", "-A")
    git(
        root,
        "commit",
        "-m",
        message,
    )
```

---

# 六十、测试 1：正常单文件 Patch

Baseline：

```python
def add(a, b):
    return a - b
```

Patch：

```diff
diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
```

断言：

```python
result = workspace.check_patch(
    PATCH
)

assert result.status == PatchStatus.VALID

result = workspace.apply_patch(
    PATCH
)

assert result.status == PatchStatus.APPLIED

assert (
    root / "calculator.py"
).read_text() == (
    "def add(a, b):\n"
    "    return a + b\n"
)
```

---

# 六十一、测试 2：多文件 Patch

Patch 同时改：

```text
service.py
api.py
```

断言：

```text
check 成功
apply 成功

affected_paths：
service.py
api.py
```

而且：

```text
两个文件同时发生变化
```

---

# 六十二、测试 3：新增文件

Patch：

```diff
diff --git a/new_module.py b/new_module.py
new file mode 100644
--- /dev/null
+++ b/new_module.py
@@ -0,0 +1,2 @@
+def run():
+    pass
```

Apply 后：

```python
assert (
    root / "new_module.py"
).exists()
```

同时：

```python
assert (
    "new_module.py"
    in workspace.changed_files()
)
```

这里能够检测到 untracked 是重要验收。

---

# 六十三、测试 4：删除文件

Baseline：

```text
legacy.py
```

Patch 删除文件。

断言：

```python
assert not (
    root / "legacy.py"
).exists()
```

并且：

```text
changed_files
→ DELETED
```

---

# 六十四、测试 5：Rename

创建：

```text
old_service.py
```

然后测试：

```bash
git mv old_service.py new_service.py
```

再：

```python
diff = workspace.diff()
```

应该能通过显式：

```text
--find-renames=50%
```

得到：

```text
RENAMED
old_service.py
→
new_service.py
```

不要把测试写成：

```text
必须 similarity=100
```

如果测试里同时修改了内容，相似度自然会变化。

---

# 六十五、测试 6：错误 Context

Baseline：

```python
return a * b
```

Patch：

```diff
-return a - b
+return a + b
```

断言：

```python
result = workspace.check_patch(
    patch
)

assert result.status == (
    PatchStatus.CHECK_FAILED
)
```

并验证原文件 Hash 未变。

---

# 六十六、测试 7：部分 Hunk 失败

这是本日最重要测试。

Baseline：

```text
a.py
b.py
```

Patch：

```text
a.py Hunk
正确

b.py Hunk
故意错误
```

首先记录：

```python
before_a = sha256_file(
    root / "a.py"
)
before_b = sha256_file(
    root / "b.py"
)
```

运行：

```python
result = workspace.apply_patch(
    patch
)
```

预期：

```text
CHECK_FAILED
```

然后：

```python
assert sha256_file(
    root / "a.py"
) == before_a

assert sha256_file(
    root / "b.py"
) == before_b
```

这就验证：

> 一个 Hunk 失败时，另一个能成功的 Hunk 也不能偷偷留下修改。

这和 Git 官方的默认 Atomic Apply 语义一致。([Git][5])

---

# 六十七、测试 8：`../../` 路径逃逸

Patch：

```diff
diff --git a/../../outside.txt b/../../outside.txt
new file mode 100644
--- /dev/null
+++ b/../../outside.txt
@@ -0,0 +1 @@
+evil
```

断言：

```text
SECURITY_REJECTED
```

且：

```python
assert not outside_path.exists()
```

实际上 Git 自身也默认会拒绝这种 Patch，但你的 Validator 应先发现。([Git][5])

---

# 六十八、测试 9：绝对路径

准备 Patch 涉及类似：

```text
/etc/passwd
C:\Users\User\file
```

断言：

```text
SECURITY_REJECTED
```

而不是期待：

```text
git apply
```

替你兜底。

---

# 六十九、测试 10：特殊文件名

创建：

```text
src/file with spaces.py
src/中文模块.py
```

然后修改。

断言：

```text
changed_files()
```

完整返回：

```text
src/file with spaces.py

src/中文模块.py
```

不能：

```text
src/file
with
spaces.py
```

因此测试必须走：

```text
-z / NUL
```

路径解析。

---

# 七十、再增加四个非常值得做的测试

虽然不在最低验收里，我建议今天一起加。

| 测试            | 原因              |
| ------------- | --------------- |
| 空 Patch       | Agent 可能输出空修改   |
| `.git/config` | 防止 Git 元数据修改    |
| 二进制 Patch     | V1 明确拒绝         |
| 超大 Patch      | 防止错误 LLM 输出耗尽资源 |

这样今天大约会有：

```text
14～18 个单元测试
```

比较合适。

---

# 七十一、今天推荐的目录

```text
codeteam/
└── git/
    ├── __init__.py
    ├── models.py
    ├── workspace.py
    ├── diff.py
    ├── patch.py
    └── errors.py

tests/
└── git/
    ├── conftest.py
    ├── test_diff.py
    ├── test_patch_validator.py
    ├── test_apply_patch.py
    └── test_path_security.py
```

---

# 七十二、各模块职责

| 文件             | 职责                              |
| -------------- | ------------------------------- |
| `models.py`    | GitDiff、GitChange、PatchResult   |
| `diff.py`      | Diff / name-status / numstat 解析 |
| `patch.py`     | PatchValidator、路径安全             |
| `workspace.py` | 对外 Git Workspace API            |
| `errors.py`    | Git / Patch 异常                  |

最重要的是：

```text
diff.py
不要负责写文件

patch.py
不要负责 Commit

workspace.py
负责协调
```

---

# 七十三、`GitWorkspace` 最终接口

今天完成后，希望能这样使用：

```python
workspace = GitWorkspace(
    Path("/workspace/project")
)
```

查看：

```python
diff = workspace.diff()

print(diff.patch)
```

变化文件：

```python
changes = workspace.changed_files()
```

验证：

```python
validation = workspace.check_patch(
    patch
)
```

真正应用：

```python
result = workspace.apply_patch(
    patch
)
```

Agent 层完全不需要知道：

```text
git apply
--check
--numstat
-z
-p1
```

这些细节都被 Runtime 封装。

---

# 七十四、Agent Tool 最终应该暴露什么

以后给 LLM 的工具可以是：

```python
apply_patch(
    patch: str
) -> PatchResult
```

而不是：

```python
run_shell(
    command="git apply ..."
)
```

区别非常大。

前者：

```text
Agent 提交意图：
“我要应用这份 Patch”
```

Runtime 能保证：

```text
安全检查
路径限制
原子性
审计
```

后者：

```text
Agent 获得任意 Shell 能力
```

几乎绕过了整个安全设计。

---

# 七十五、今天真正应该形成的工业级 Editing Pipeline

最终推荐牢记这条链：

```text
                 LLM
                  │
                  │ Patch
                  ▼
         ┌─────────────────┐
         │ Size / Type Gate│
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │ Parse Patch Paths│
         │ git apply        │
         │ --numstat -z     │
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │ Path Boundary   │
         │                 │
         │ absolute?       │
         │ ../ escape?     │
         │ symlink escape? │
         │ .git?           │
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │ git apply       │
         │ --check         │
         └────────┬────────┘
                  │ success
                  ▼
         ┌─────────────────┐
         │ Snapshot Hashes │
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │ git apply       │
         └────────┬────────┘
                  │
          ┌───────┴───────┐
          │               │
       Success          Failed
          │               │
          ▼               ▼
      git diff       verify SHA256
          │               │
          ▼               ▼
       Review          unchanged
```

---

# 七十六、今天的详细学习安排

| 阶段 |     时间 | 内容                                  | 产出             |
| -- | -----: | ----------------------------------- | -------------- |
| 1  | 40 min | HEAD / Index / Working Tree 实验      | 手写状态图          |
| 2  | 40 min | 三种 git diff                         | `diff_lab.md`  |
| 3  | 45 min | Unified Diff / Hunk / Context       | 能手工解释 Patch    |
| 4  | 30 min | `git apply` / `--check` / Atomicity | Patch 实验       |
| 5  | 60 min | GitDiff + Diff Parser               | `diff.py`      |
| 6  | 80 min | PatchValidator                      | `patch.py`     |
| 7  | 60 min | GitWorkspace                        | `workspace.py` |
| 8  | 90 min | 10+ pytest 测试                       | `tests/git/`   |
| 9  | 30 min | 失败场景与审计                             | 测试报告           |

总时间大约：

```text
7～8 小时
```

---

# 七十七、第一阶段一定要手工做的 Git 实验

建立：

```bash
mkdir patch-lab
cd patch-lab

git init

git config user.name "Test User"
git config user.email "test@example.com"
```

创建：

```bash
cat > calculator.py <<'EOF'
def add(a, b):
    return a - b
EOF

git add calculator.py
git commit -m "baseline"
```

然后依次经历：

```text
1. git diff
2. 修改 calculator.py
3. git diff
4. git diff --cached
5. git diff HEAD
6. git add calculator.py
7. 再运行三个 diff
8. 再修改一次文件
9. 再运行三个 diff
```

你如果把这一步完全理解透，后面的 Git 学习会简单很多。

---

# 七十八、第二阶段一定要手工做 Patch 实验

生成：

```bash
git diff HEAD > change.patch
```

查看：

```bash
cat change.patch
```

然后恢复文件：

```bash
git restore calculator.py
```

检查：

```bash
git apply --check change.patch
```

再应用：

```bash
git apply change.patch
```

最后：

```bash
git diff HEAD
```

你会第一次真正看到：

```text
Diff
→ Patch File
→ Validation
→ Apply
→ 重新产生同样 Diff
```

这就是非常核心的闭环。

---

# 七十九、今天完成后必须能回答的问题

最终你应该能清楚解释：

1. `HEAD`、`Index` 和 `Working Tree` 各自代表什么。
2. 为什么 `git diff` 和 `git diff HEAD` 不是同一个东西。
3. 为什么 `git diff --cached` 能告诉我们“下一次 Commit 准备提交什么”。
4. 为什么普通 `git diff HEAD` 看不到纯 Untracked 文件。
5. Unified Diff 中 `---`、`+++`、`@@` 分别代表什么。
6. `@@ -42,7 +42,9 @@` 中四个数字是什么。
7. Hunk 是什么。
8. Context Line 除了方便人看之外，还有什么意义。
9. 为什么 Agent 不应该默认产生 `-U0` Patch。
10. 为什么 Patch 比整文件重写更适合 Coding Agent。
11. `git apply --check` 为什么必须在真正 Apply 前执行。
12. 为什么 `--check` 成功之后真正 Apply 仍然可能失败。
13. Git 默认的 Patch Atomicity 是什么。
14. 为什么必须禁止 `--reject`。
15. 为什么必须禁止 `--unsafe-paths`。
16. 为什么 Patch Path 不能仅检查字符串里有没有 `..`。
17. Symlink 如何导致路径逃逸。
18. 为什么机器解析文件名必须优先使用 NUL 格式。
19. Git 为什么能够把 Delete + Add 显示成 Rename。
20. 为什么 Agent Runtime 应提供 `apply_patch()`，而不是让 LLM 自己运行 `git apply`。

---

# 八十、今天最终验收

你今天真正达到合格标准，应该同时满足下面这些条件：

* `workspace.diff()` 能稳定获取当前修改，并显式处理 untracked 文件；`workspace.changed_files()` 使用机器可读的 NUL 路径格式，并能正确处理空格、中文和 Rename；`workspace.check_patch()` 永远只验证、不修改文件；`workspace.apply_patch()` 内部永远先执行 `check_patch()`；正常单文件、多文件、新增、删除、Rename Patch 都有测试。
* 错误 Context 与“部分 Hunk 失败”测试中，所有受影响文件的 SHA256 前后完全一致；`../../`、绝对路径、`.git` 和 Symlink Escape 被 `PatchValidator` 拒绝；Agent API 没有任何入口能够传入 `--reject`、`--unsafe-paths` 或 `--unidiff-zero`；所有 Git 调用都使用参数数组并保持 `shell=False`。
* 最终形成 `git/workspace.py`、`git/diff.py`、`git/patch.py`，并且可以从外层只通过 `diff()`、`changed_files()`、`check_patch()`、`apply_patch()` 四个接口完成所有编辑工作。

如果今天只记住一个工业级原则，就是：

```text
LLM 不是“文件写入者”。

LLM 只是：
Patch Proposal Generator

真正拥有修改权限的是：
GitWorkspace Runtime

而 Runtime 必须保证：

Validate
→ Bound
→ Check
→ Apply atomically
→ Diff
→ Verify
```

从这一层开始，你后面的 Worktree、Checkpoint、Rollback、Approval 和 Sandbox 才有可靠的底座。

[1]: https://git-scm.com/docs/git-status?utm_source=chatgpt.com "Git - git-status Documentation"
[2]: https://git-scm.com/docs/git-apply?utm_source=chatgpt.com "Git - git-apply Documentation"
[3]: https://git-scm.com/docs/git-diff.html "Git - git-diff Documentation"
[4]: https://git-scm.com/docs/diff-generate-patch.html "Git - diff-generate-patch Documentation"
[5]: https://git-scm.com/docs/git-apply "Git - git-apply Documentation"
[6]: https://git-scm.com/docs/diff-generate-patch.html?utm_source=chatgpt.com "Git - diff-generate-patch Documentation"
[7]: https://google.github.io/eng-practices/?utm_source=chatgpt.com "Google Engineering Practices Documentation | eng-practices"
[8]: https://google.github.io/eng-practices/review/developer/small-cls.html?utm_source=chatgpt.com "Small CLs | eng-practices"
[9]: https://docs.github.com/en/enterprise-cloud%40latest/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests?utm_source=chatgpt.com "Reviewing changes in pull requests - GitHub Enterprise Cloud Docs"
[10]: https://engineering.fb.com/2022/11/16/culture/meta-code-review-time-improving/?utm_source=chatgpt.com "Move faster, wait less: Improving code review time at Meta"
[11]: https://sapling-scm.com/docs/introduction/?utm_source=chatgpt.com "Sapling SCM | Sapling"
[12]: https://git-scm.com/docs/diff-format.html?utm_source=chatgpt.com "Git - diff-format Documentation"
[13]: https://git-scm.com/docs/git-diff-index?utm_source=chatgpt.com "Git - git-diff-index Documentation"
[14]: https://git-scm.com/docs/git-diff.html?utm_source=chatgpt.com "Git - git-diff Documentation"

---

# 教练教程：Day 1 学习路线图

本学习路线根据以下内容制定：

- `prompt/task_to_knowledge.md`
- `learning-plan/week3/week3_plan.md`
- `learning-plan/week3/day1.md`
- 当前 `codeteam/` 和 `tests/` 目录结构

目前仓库中还没有 `codeteam/git/` 和 `tests/git/`，因此 Day 1 是一个全新的模块。本教程先建立完整学习路线，不直接实现代码。

## 这部分在做什么

前两周，你的 Agent 已经能够读取仓库、搜索文件、构建上下文。Day 1 开始解决一个更危险的问题：

> Agent 怎样真正修改代码，同时保证错误修改不会破坏仓库？

今天要建立这条安全编辑链路：

```text
模型生成 Patch
    ↓
PatchValidator
    ├── 检查 Patch 大小和类型
    ├── 找出受影响的文件
    ├── 检查路径是否越过仓库边界
    └── git apply --check 预演
    ↓
GitWorkspace.apply_patch()
    ├── 再确认验证结果
    ├── 保存原文件 SHA256
    ├── 执行 git apply
    └── 返回结构化 PatchResult
    ↓
GitWorkspace.diff()
    ↓
Agent 或人工 Review 修改
```

你今天需要区分三个概念：

- `Diff`：描述已经发生了哪些变化。
- `Patch`：一份可以尝试应用到文件上的修改说明。
- `Validation`：真正修改文件前，检查这份 Patch 是否合法、是否能够应用。

## 涉及哪些文件

建议逐步建立下面的目录：

```text
codeteam/git/
├── __init__.py
├── models.py
├── errors.py
├── diff.py
├── patch.py
└── workspace.py

tests/git/
├── __init__.py
├── conftest.py
├── test_diff.py
├── test_patch_validator.py
├── test_apply_patch.py
└── test_path_security.py
```

各文件职责如下：

| 文件 | 主要职责 |
|---|---|
| `models.py` | 定义 `GitDiff`、`GitChange`、`PatchResult` 等结构化数据 |
| `errors.py` | 定义 Patch 安全检查、Git 执行失败等异常 |
| `diff.py` | 执行或解析 Git Diff、文件状态和统计信息 |
| `patch.py` | 验证 Patch，不真正修改文件 |
| `workspace.py` | 提供 `diff()`、`check_patch()`、`apply_patch()` 等统一入口 |
| `conftest.py` | 为测试创建临时 Git 仓库 |
| `test_diff.py` | 测试修改、新增、删除、重命名等状态 |
| `test_patch_validator.py` | 测试 Patch 预检查和格式限制 |
| `test_apply_patch.py` | 测试正常应用与原子失败 |
| `test_path_security.py` | 测试绝对路径、路径逃逸、`.git`、符号链接 |

现有的 `codeteam/tools/shell.py` 是通用命令工具。Day 1 不应该让业务代码到处调用它来拼 Git 命令，而应该由 `GitWorkspace` 集中管理 Git 操作。通用命令的审批与沙箱属于本周后面的内容。

## 文件之间如何交互

```text
models.py
   ↑
   ├── diff.py 解析 Git 输出，创建 GitDiff / GitChange
   ├── patch.py 验证 Patch，创建 PatchResult
   └── workspace.py 组合 diff.py 和 patch.py

调用者
   ↓
GitWorkspace
   ├── diff() ----------→ diff.py
   ├── changed_files() -→ diff.py
   ├── check_patch() ---→ PatchValidator
   └── apply_patch()
          ├── check_patch()
          ├── 保存 SHA256
          ├── git apply
          └── 返回 PatchResult
```

最重要的边界是：

- `diff.py` 负责读取和解析，不负责改文件。
- `patch.py` 负责验证，不负责真正应用。
- `workspace.py` 负责协调完整流程。
- 外部调用者不能传入任意 `git apply` 参数。

## 建议拆成九步

| 步骤 | 学习内容 | 涉及文件 |
|---|---|---|
| 第 1 步 | 理解 HEAD、Index、Working Tree | 暂不写代码 |
| 第 2 步 | 手工观察三种 `git diff` | 暂不写代码 |
| 第 3 步 | 学会阅读 Unified Diff 和 Hunk | 暂不写代码 |
| 第 4 步 | 手工实验 `git apply --check` 和原子性 | 暂不写代码 |
| 第 5 步 | 定义 Git 和 Patch 数据模型 | `models.py`、`errors.py` |
| 第 6 步 | 实现 Diff 输出解析 | `diff.py` |
| 第 7 步 | 实现 PatchValidator | `patch.py` |
| 第 8 步 | 实现 GitWorkspace 对外接口 | `workspace.py` |
| 第 9 步 | 编写测试并完成验收 | `tests/git/` |

这个顺序很重要：先亲手看懂 Git 的状态变化，再把它写成 Python。否则很容易出现“代码能运行，但不知道每个 Git 参数为什么存在”的情况。

## 各步骤的大致目标

### 第 1 步：理解 Git 的三个区域

第 1 步要弄清楚三个版本：

```text
HEAD         = 最近一次提交保存的版本
Index        = 下一次准备提交的版本
Working Tree = 当前磁盘上的版本
```

### 第 2 步：观察三种 Diff

第 2 步要掌握：

```text
git diff          Working Tree 和 Index
git diff --cached Index 和 HEAD
git diff HEAD     Working Tree 和 HEAD
```

还要特别注意：普通的 `git diff HEAD` 不会自动展示未跟踪文件的完整内容。

### 第 3 步：阅读 Unified Diff

第 3 步学习 Patch 中的文件头、旧文件、新文件、Hunk Header、上下文行，以及 `+`、`-`、空格三种行。

### 第 4 步：验证 Patch 行为

第 4 步验证：

```text
git apply --check 只检查，不写文件
git apply         真正应用
```

还要故意制造一个错误 Hunk，观察整份 Patch 默认原子失败。

### 第 5 步：定义数据模型

第 5 步定义这些模型：

- `GitChangeKind`
- `GitChange`
- `GitDiff`
- `PatchStatus`
- `PatchResult`
- `PatchSecurityError`

这一阶段会复习 `Enum`、Pydantic `BaseModel`、可选类型 `str | None`、列表类型 `list[str]`。

### 第 6 步：解析 Git 输出

第 6 步使用 Git 的机器可读输出解析变化，重点学习 `bytes`、NUL 字符 `b"\0"` 和 `os.fsdecode()`。

### 第 7 步：实现 PatchValidator

第 7 步给 Patch 建立三层验证：

```text
大小和类型检查
    ↓
路径安全检查
    ↓
git apply --check
```

### 第 8 步：实现 GitWorkspace

第 8 步把内部模块组装为统一接口：

```python
workspace.diff()
workspace.changed_files()
workspace.check_patch(patch)
workspace.apply_patch(patch)
```

其中 `apply_patch()` 必须在内部调用 `check_patch()`，不能依赖调用者“记得先检查”。

### 第 9 步：测试与验收

第 9 步用独立临时仓库验证全部行为。

## 整体实现原则

所有 Git 命令都使用参数列表：

```python
["git", "apply", "--check", "-"]
```

并保持 `shell=False`。这样不会让 Patch 内容被 shell 当成命令解释。

路径不能只用下面这种字符串判断：

```python
".." in path
```

最终应该把路径解析为真实路径，再判断它是否仍位于仓库根目录内部。还要单独拒绝 `.git` 和通过符号链接越过仓库边界的情况。

Agent API 中不要提供这些危险选项：

```text
--reject
--unsafe-paths
--unidiff-zero
```

特别是 `--reject` 可能造成部分 Hunk 已应用、部分 Hunk 失败，破坏“要么全部成功，要么完全不变”的安全保证。

## 测试思路

测试不能直接在当前项目仓库上修改文件。每个测试都应该用 pytest 的 `tmp_path` 创建一个全新的临时 Git 仓库。

最低测试范围包括：

- 单文件 Patch 正常应用。
- 多文件 Patch 同时应用。
- 新增文件。
- 删除文件。
- Rename。
- 错误 Context。
- 多个 Hunk 中有一个失败。
- `../../` 路径逃逸。
- 绝对路径。
- 修改 `.git`。
- 符号链接逃逸。
- 包含空格或中文的文件名。
- 空 Patch。
- Binary Patch。
- Patch 超过大小限制。

失败场景不能只断言 `success=False`，还要比较修改前后的 SHA256，证明文件确实没有发生变化。

后续单独运行 Day 1 测试的命令应为：

```bash
.venv/bin/python -m pytest tests/git -q
```

全量验证使用：

```bash
.venv/bin/python -m pytest -q
```

今天完成后，你最终要得到的是一个可靠的 `GitWorkspace`：外部只提交 Patch，不需要了解底层 Git 参数；系统先检查、再应用、最后返回可审计的结构化结果。


