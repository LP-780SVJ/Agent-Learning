# Week4 -> Week5 分支合并方案

> 修订日期：2026-08-31；按用户追加授权采用更新后的 Week5 固定输入。
> 本次任务：合并并验证现有代码，不开发新的多 Agent 功能。
> 本文分为 A 部分“本次执行方案”和 B 部分“后续架构路线”。只有 A 部分在本次授权范围内。

## 目标与边界

把 Week4 的统一 CodingAgentRuntime 合入 Week5，形成同时包含以下内容的 Week5 基线：

- Week4：生产 CLI 与 agent-eval 共用的单 Agent Runtime。
- Week5：Day1 Lead/Worker、Day2 TaskDAG hardening、Day3 Scheduler、Day4 Mailbox 及其 hardening。
- 两边已有的测试、教程、设计决策和用户明确保留的实验记录。

合并成功只证明现有 Runtime 与 Week5 Day1–Day4 基础设施共存，不等于 Worker 执行适配、完整 Multi-Agent Runtime 或全部工程证据闭环已经完成。

本次保留已有 Scheduler、Mailbox，不新增 WorkerExecutor、LLM dependency planning 或结果集成服务，不重构 dependency/fencing contract 或 Week4 Runtime；不执行真实 API smoke、benchmark 或 ablation。

---

# A. 本次执行方案

## A1. 项目规约与授权

执行前必须阅读：

- 项目适用的 AGENTS.md，当前主要规约为 `.codex/AGENTS.md`。
- `prompt/coder_Agent.md`。
- 本文件。
- `README.md`、`pyproject.toml`、`pytest.ini`。
- `learning-plan/week5/week5_plan.md`、Day1/Day2 文档、Day3/Day4 当前契约与 hardening 记录，以及相关验收日志；历史验收结论须按其 SHA 解释。
- 两个分支实际代码和 Git 状态。文档快照不能覆盖更新后的代码事实。

本轮是用户明确授权的合并执行任务，不是逐步教学任务。无需展开新教程，但仍须遵守 Coder 的写入边界、测试、安全和证据要求。

允许：

1. 保留并修订本方案已暂存的内容，审核 staged diff，只提交本方案文件。
2. 创建本次专用 integration 分支和 Git worktree。
3. 合并已固定的 Week4 SHA，创建本地 merge commit。
4. 解决不改变双方既有行为的纯文本冲突。
5. 运行现有确定性测试、静态检查、安装验证和 Docker 边界测试。
6. 验收通过后将本地 week5 安全 fast-forward 到通过验收的 integration commit。
7. 新增一份合并日志，并单独提交日志。
8. 在基线证据确认后创建一个可选的本地 baseline tag。

禁止：

- 自动 push、force push、远端分支删除或远端 tag 发布。
- reset --hard、git clean、强制移动分支、覆盖已有 tag、丢弃用户修改或改写历史。
- 使用全局 `-X ours` / `-X theirs`，或整文件选择一侧来掩盖不理解的冲突。
- 为了测试通过删除测试、降低断言、增加 skip/xfail、关闭安全检查。
- 手工重写生产代码、修改依赖声明或测试配置来“顺便修复”已有债务。
- 回退或删除已有 Scheduler/Mailbox，新增 WorkerExecutor，或修改 dependency/fencing contract。
- 读取、输出、复制、提交 `secrets.local.env` 或 API key；不加载真实模型凭证。
- 自动执行 B01、F03、11-task campaign 或任何真实 LLM/API benchmark。
- 清理已有 worktree、历史实验结果、其他 Agent 的分支或文件。

纯文本冲突若实际涉及接口或行为变化，应停下并报告，不能自行把本任务扩大为开发任务。

测试隔离要求仍然有效：改变 Git 状态的测试只能使用 function-scoped `tmp_path` 独立仓库和 baseline commit；只设置仓库本地 Git identity；复杂 fixture 只能复制后测试，不能直接修改主仓库或 `tests/fixtures/`。测试中的 Git subprocess 使用 argv 列表、`shell=False`、超时和输出捕获。本次明确授权的分支合并操作与测试用例对仓库的修改应严格区分。

## A2. 已核实的分支事实

以下是修订时的快照，不是执行时可以跳过复核的硬编码事实：

| 项目 | 当前值 |
|---|---|
| 用户主工作区 | `/Users/root/workspace/Agent-Learning`，当前 week4 |
| week4 原代码 SHA | `c8896a067708c0fe34b0727d04fa0602cc9ceaac` |
| week5 固定 SHA | `58fed46109033acfb72862686f63c51f83b6c548` |
| merge-base | `3956afc05d6c1ad2f3efaac9a510133436c0f700` |
| week4 独有提交 / 改动路径 | 13 / 365 |
| week5 独有提交 / 改动路径 | 12 / 42 |
| 两边相对 merge-base 的改动路径交集 | `codeteam/events.py`、`learning-plan/代码架构.md`、`learning-plan/设计决策.md` |
| 只读 merge-tree 检查 | events 预计自动合并；代码架构预测 2 个冲突区块，设计决策预测 1 个；以实际 merge 为准 |
| 本地与 origin 跟踪引用 | 2026-08-31 再次 fetch 成功后两边均与上述 SHA 相同 |

用户已明确授权旧 Week5 `4f8aa91` 之后的 7 个提交。提交本方案后，week4 SHA、提交数和路径数会正常变化（预期 14 个独有提交、366 条路径）。记录原代码 SHA、文档 commit SHA 和新的 W4_SHA；这一纯文档变化不再询问，其他输入漂移仍须停止。

Week5 当前实际模块：

```text
codeteam/agent_team/
  __init__.py
  models.py
  worker.py
  lead.py
  dag.py
  scheduler.py
  mailbox.py
```

当前已有 TaskScheduler、TaskClaim、AgentMailbox、AgentMessage，以及 9 个 Scheduler 和 5 个 Mailbox 事件。DAG TaskStatus 有七种状态（含 CLAIMED）。DAG 已使用 heap、输入/输出 defensive copy、replace_task_status；factory 在多节点 dependencies=None 时拒绝，dependencies=() 表示明确独立。Scheduler 持有拓扑快照与自己的运行状态，锁内推进、锁外投递事件。Mailbox 已有批内 ID 冲突检查、JSON payload 和有限非负时间戳校验。

当前 Scheduler 的 start/complete/fail 参数仍为 node_id、worker_id（fail 另有 reason/retryable），不接受完整 claim/attempt；不能把 TaskClaim 含 attempt 误称为已经实现 attempt fencing。本次只保留现有契约，不进行重构。

### 用户有意提交的稳定性证据

`stability_20260830_190244/` 中的 202 个已跟踪文件是用户有意保留的实验记录，其中最新 Week4 提交新增了 54 个文件。

这些文件不是误提交，也不是本次清理对象：

- 必须随 Week4 完整合入 Week5。
- 不删除、不移动、不取消跟踪、不改写内容。
- 不新增忽略规则来代替用户对此批证据的选择。
- 合并后比较该目录与固定 W4_SHA 的 Git tree，确认没有丢失或修改。
- 保留现有 `/evals/week4/agent_runs/` 忽略规则；本次不改变实验归档策略。

其他既有已跟踪实验目录同样保留。仅本次新产生的原始验证输出应放入独立临时位置或已有忽略目录；摘要进入新增合并日志。

## A3. 当前整合矩阵

| 范围 | 实际来源 | 本次处理 |
|---|---|---|
| `codeteam/agent/`、`agent_loop.py`、LLM、execution、sandbox 等 Runtime 路径 | Week4 后续演进 | 保留 Week4 最新实现，不接回旧执行循环 |
| `codeteam/events.py` | 双方修改 | 保留双方新增枚举名和值，预计自动合并，核对事件集合为双方并集 |
| `codeteam/agent_team/`、`tests/agent_team/` | Week5 独有新增 | 原 blob 保留 Day1–Day4 及 hardening，实现与测试不回退 |
| `pyproject.toml` 的 setuptools package discovery | Week5 修改 | 保留并验证安装、包导入 |
| README | Week4 当前版本 | 原样保留，不补写尚未实现的功能 |
| 代码架构、设计决策 | 双方修改 | 逐区块整合 Runtime 演进和团队基础设施记录；不整文件选择 ours/theirs，不把旧规划入口重新接回生产链 |
| Week5 教程、DD、验收日志 | Week5 | 保留 |
| 已跟踪稳定性证据 | Week4 | 完整保留 |

当前预测两个文档存在文本冲突，events 的重叠改动不必然冲突。若实际冲突涉及生产行为、接口或安全语义变更，停止报告；自动合并成功也仍需语义和测试验证。

不要把“未来要新增的适配层”描述为本次已有 semantic conflict。

## A4. Phase 0：保护工作区并固定输入

### 1. 盘点现场

在用户项目目录中只读检查：

```bash
git status --short --branch
git worktree list --porcelain
git branch -vv
git rev-parse week4 week5
git merge-base week4 week5
git rev-list --left-right --count week4...week5
```

检查 staged、unstaged、untracked 文件以及其他 worktree 的占用情况。

修订时只有 `prompt/merge_week4_week5.md` 是 staged 新文件，工作树内容与 index 一致。若执行时仍然如此：

- 可以只 stage 本文件，检查 staged diff，然后创建独立文档 commit。
- 若它已提交，不重复提交。
- 若出现其他用户修改，不擅自 stage/stash/提交；需要用户处理时报告准确路径。
- 不要求用户删除本地实验文件，也不把 ignored 文件误认作应清理内容。

### 2. 固定本地与远端信息

可以执行只更新远端跟踪引用的 `git fetch origin`。网络或权限受限时按工具权限流程申请，不绕过限制。

随后比较本地 week4/week5 与 origin 跟踪引用：

- 相同：记录本地完整 SHA 作为本次输入。
- 若唯一差异是上一步本轮已授权创建的方案文档 commit：核验其只包含本文件，记录代码基线 SHA 与文档 commit SHA，可直接使用包含该文档的本地 week4 HEAD。
- 其他不同：先解释 ahead/behind/diverged，停止并请用户确认采用哪个版本。
- 不自动 pull、rebase 或把远端提交带入本次范围。
- fetch 无法完成时，明确标记远端未核验；不得把旧 origin 引用称为远端最新状态。用户确认使用本地引用后才继续。

命令示例：

```bash
W4_SHA=$(git rev-parse week4)
W5_SHA=$(git rev-parse week5)
BASE_SHA=$(git merge-base "$W4_SHA" "$W5_SHA")

git diff --name-status "$BASE_SHA" "$W4_SHA"
git diff --name-status "$BASE_SHA" "$W5_SHA"
git merge-tree "$BASE_SHA" "$W5_SHA" "$W4_SHA"
```

变量仅在同一 shell 会话内有效。通过 Agent 工具分次执行时，要显式使用已记录的值和工作目录，不假设前一次 shell 环境继续存在。

### 3. 基线验证

用项目 `.venv/bin/python` 记录 Python、pytest、Ruff 版本及有效配置，然后验证 Week4：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check codeteam tests
```

- pytest 必须区分 passed / failed / error / skipped 及 skip 原因。
- 全仓 Ruff 的旧记录为 168 项；本轮重新实测两个输入，历史数量不是零错误基线，也不是可任意增加的额度。
- 用相同 Ruff 版本、规则与扫描范围保存结构化基线，后续按相对路径、规则和位置/诊断比较，不只比较总数。
- 两个分支的有效 Ruff 配置必须一致；若工作树位置改变了继承配置，先显式对齐检查环境，不能修改项目 lint 配置来变绿。
- 若 pytest 存在真实失败，先报告，暂停本次合并；不要擅自修复。
- 已明确记录的外部能力缺失可以 conditional skip，但不能宣称该能力通过。

检查已提交稳定性证据的 manifest、summary 与对应代码版本。不重跑真实 benchmark，不把旧版本实验自动算作最新 HEAD 的证据。

可选：验证后创建本地 `week4-single-agent-baseline-YYYYMMDD` annotated tag，指向固定 W4_SHA。它只表示可追溯基线，不表示通用任务零失败。已有同名 tag 时验证其目标；目标不同则停止，不覆盖。不得自动 push tag。

## A5. Phase 1：独立 Integration Worktree

推荐分支名：

```text
codex/integration-week5-week4-runtime
```

从固定 W5_SHA 创建，不直接在用户的主工作区切换、合并或运行破坏性测试。

示例：

```bash
SOURCE_ROOT=/Users/root/workspace/Agent-Learning
INTEGRATION_ROOT="$HOME/.codeteam/worktrees/integration/week5-week4-YYYYMMDD-HHMMSS"

git worktree add -b codex/integration-week5-week4-runtime \
  "$INTEGRATION_ROOT" "$W5_SHA"
```

- 使用真实时间和未占用目录，不能照抄占位日期。
- 目录或分支已存在时，核验是否属于本任务；不强制覆盖或自动删除。
- 创建目录涉及权限申请时使用正常授权流程。
- 不更改用户 Colima、Docker、全局 Git 或 shell 配置。
- 不运行 `git worktree prune` 清理与本次无关的旧登记。
- 用户原目录继续保持 week4。

### 独立 Python 环境

不能直接共享原项目 `.venv` 的 editable 安装。否则在 integration worktree 跑测试，可能实际 import 了原目录的 week4。

使用源项目 Python 3.11 创建本工作树自己的环境：

```bash
"$SOURCE_ROOT/.venv/bin/python" -m venv "$INTEGRATION_ROOT/.venv"
```

之后在 integration worktree 中统一使用 `.venv/bin/python`。

安装时：

- 优先复用源环境已安装的包版本，保存只包含包名和版本的临时 constraints；不复制凭证、带认证信息的索引 URL 或完整环境变量。
- 安装仓库 requirements/dev requirements，并在该私有 venv 中执行 `.venv/bin/python -m pip install -e .`。
- 版本约束、临时安装记录不写回 requirements 或 pyproject。
- 如需下载依赖，按权限流程申请；不改全局 pip 配置、不无故升级源 venv。
- 记录版本差异。不要把依赖升级引起的差异误判为 merge regression。

合并前，在 W5_SHA 下运行 `tests/agent_team`、全量 pytest 与 Ruff 基线检查，确保能够区分 Week5 已有问题和合并后新增问题。

## A6. Phase 2：只合并，不开发

在 integration worktree 执行：

```bash
git merge --no-ff --no-commit "$W4_SHA"
git status --short
git diff --name-only --diff-filter=U
git ls-files -u
```

使用 `--no-commit` 是为了先检查合并结果和验证，再创建 merge commit。

处理原则：

1. 按 A3 预期核对实际冲突；仅逐区块保留双方有效内容，不整文件覆盖。
2. 若出现新冲突，先确认两个输入 SHA 是否已改变。
3. 只有能证明保留双方现有行为的文本冲突可在本次处理。
4. 若需要改动接口、依赖声明、测试预期或安全语义，停止并报告，不扩大授权。
5. 不为了方便把整个 Runtime 或 agent_team 恢复成另一侧的旧版本。

合并前后核对：

- Week4 Runtime 与 CLI/eval 仍共享同一条生产执行链。
- Week5 agent_team 七个模块及 Day1–Day4/hardening 测试完整保留。
- `[tool.setuptools.packages.find]` 下 `include = ["codeteam*"]` 存在。
- 两种 TaskStatus 保持不同 domain，不强行统一；DAG 保持当前七种状态，包含 CLAIMED。
- Scheduler/Mailbox 的现有 import、事件名和值完整保留；不凭空增加新的能力。
- `stability_20260830_190244/` 的路径和 blob 与 W4_SHA 相同。
- 其他本次未授权手工修改的路径没有额外改动。

检查 staged 和工作树内容：

```bash
git diff --check
git diff --cached --check
git diff --cached --stat
git ls-files -u
```

冲突 marker 检查应限制为真实 marker 行，如 `^(<{7}|={7}|>{7})( |$)`，并逐条复核。Markdown/测试样例中可能有合法文本，不能简单把任意 `=======` 匹配都当成冲突。

## A7. Phase 3：Deterministic Mechanical Gate

### Gate 1：安装与真实 Import Origin

合并后在 integration 私有 venv 中重新执行：

```bash
.venv/bin/python -m pip install -e .
```

验证实际存在的模块：

```python
from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.agent_team.lead import LeadAgent
from codeteam.agent_team.worker import WorkerAgent, WorkerRegistry
from codeteam.agent_team.dag import TaskDAG
from codeteam.agent_team.scheduler import TaskScheduler, TaskClaim
from codeteam.agent_team.mailbox import AgentMailbox, AgentMessage, AgentMessageType
```

检查这些模块的 `__file__` 均位于 integration worktree；再从仓库之外的临时 cwd，用该工作树 `.venv/bin/python` 的绝对路径重复 import 检查。

同时检查 agent_team 公共导出与内部模块对象身份一致；不要导入不存在的 WorkerExecutor，不把 PYTHONPATH 指向原项目来掩盖安装问题。

### Gate 2：Week5 Day1–Day4 Foundation 与 Hardening

```bash
.venv/bin/python -m pytest tests/agent_team -q
.venv/bin/python -m ruff check codeteam/agent_team tests/agent_team
```

必须通过。若基线已出现问题，应停止并说明，而不是合并时顺手调整测试或配置。

完整 agent_team 测试必须包含 DAG 声明/快照/七态、Scheduler claim/ownership/retry/事件 sink、Mailbox 原子 broadcast/JSON/时间戳/不绕过 Scheduler 等已有测试；不以旧数量代替实际收集与结果。

### Gate 3：Week4 Runtime 回归

以下目录当前存在，不需要写成“如果有再测”：

```bash
.venv/bin/python -m pytest \
  tests/agent tests/execution tests/sandbox tests/git \
  tests/session tests/evaluation tests/cli tests/llm -q
```

这不替代全量测试。位于 tests 根目录的 AgentLoop/协议测试仍由下一 Gate 覆盖。

### Gate 4：全量与 Docker 边界

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/sandbox -q -rs
```

- 全量 pytest 不允许新增失败、collection error 或未解释的 skip。
- daemon 权限受限时，按工具权限流程申请在可访问 Docker 的终端复跑。
- 不绕过 sandbox、不改 socket 权限、不自动 pull/build 镜像，不改测试让它跳过。
- 仍不可访问时，记录准确原因和未验证边界。
- 若只出现两边基线均已确认的 Docker 能力 skip，且其他 Gate 通过，可合并并标记 `MERGE_PASS_WITH_ENV_LIMITATION`；不能称 Docker 验收通过。
- 若新增了环境故障、失败或 skip，先解释相对基线的变化；未澄清前不得晋级目标分支。

### Gate 5：Ruff 与历史类型债

```bash
.venv/bin/python -m ruff check codeteam tests
```

判定要求：

- agent_team 范围检查必须通过。
- 本轮手工解决冲突触达的文件检查必须通过；若这些文件已有 lint 债需要扩大修改范围，先报告。
- 全仓 Ruff 与两个输入分支基线比较，不得引入新诊断。
- 保留既有诊断明细和退出码，不把基线债务包装成 PASS。
- 168 只是本次核查时 Week4 的数量快照，不是未来固定阈值。
- 不执行 `ruff --fix` 或批量格式化。

mypy 为历史债审计项，不要求本次清零。可复跑：

```bash
.venv/bin/python -m mypy codeteam/agent_team tests/agent_team
```

按文件区分目标范围错误与历史 import-chain 错误；新引入的目标范围错误需报告并阻止晋级。不得加入 ignore、改类型配置来规避诊断。

### Gate 6：输入保全

两边各自独有路径须原样合入；三条共同修改路径单独审计：

- 相对 W4_SHA，Week4 独有改动文件应保持原 blob。
- 相对 W5_SHA，Week5 独有改动文件应保持原 blob。
- 特别验证 pyproject、agent_team、Runtime、测试和用户保留的实验目录保持来源 blob；events 验证双方枚举并集且公共结构未变，两份共同文档记录逐区块处理方式。
- 若出现例外，日志中逐文件写出修改原因及额外验证。

不要仅凭 merge exit code 0 或 pytest 数量增加判断合并完整。

## A8. Phase 4：Merge Commit 与 Week5 晋级

所有阻断 Gate 通过后，检查暂存区，确保只有两边合并内容和明确审核过的文本解决结果。

创建一个本地 merge commit，例如：

```bash
git commit -m "merge: integrate week4 coding runtime into week5 foundation"
```

记录 MERGE_SHA，核验其两个 parent 分别是固定 W5_SHA 与 W4_SHA。

随后确认：

- integration 工作树干净；ignored venv/cache 不作为待提交内容。
- 本地 week5 仍等于固定 W5_SHA。
- week5 没有被其他 worktree 占用；若占用，检查其路径和状态，不能忽略占用强行 checkout。
- 若 week5 已前进，停止并保留 integration 成果，不 force-update、reset 或擅自二次合并。

当 week5 未被其他 worktree 占用时，可在当前 integration worktree 内切换到 week5，然后安全晋级：

```bash
git switch week5
git merge --ff-only "$MERGE_SHA"
```

此时该 worktree 成为 week5 工作树；用户原目录仍为 week4。

这里不再使用第二次 `--no-ff`。integration commit 已经是合并两个历史的 merge commit，不需要额外制造一层 merge commit。

晋级后，在 week5 工作树重新执行：

```bash
.venv/bin/python -m pytest tests/agent_team -q
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check codeteam/agent_team tests/agent_team
.venv/bin/python -m ruff check codeteam tests
```

仍按 A7 的 Ruff 基线和环境限制判定。复验失败时如实报告 week5 已晋级但验收未完成；不要回滚、重写或掩盖现场。

本次不 push。保留 integration 分支和本次 worktree，向用户报告位置。PR/远端同步属于用户之后的操作，不与本地晋级同时自动执行。

## A9. 日志与交付

复验后新增：

```text
test_log/YYYY-MM-DD_week4_week5_merge_log.md
```

若同名文件存在，使用时间后缀创建新文件，不覆盖/追加既有日志。

必须包含：

- 本次任务范围与明确非目标。
- 输入 W4_SHA / W5_SHA / merge-base，以及 MERGE_SHA 和 parent 核验。
- integration 分支、worktree 路径、最终本地 week5 SHA。
- 用户主工作区仍在 week4，且没有被测试污染的检查结果。
- 202 个已跟踪实验文件按用户意图完整保留的核验。
- 是否出现冲突、涉及文件、实际解决方式。
- Python、关键包、Ruff 版本和配置、安装与 import origin 证据。
- 两边基线、合并后 Gate、目标 week5 复验的实际命令、退出码和结果。
- passed / failed / error / skipped 数量、Docker skip 原因和未覆盖内容。
- 全仓 Ruff 历史诊断与新增诊断比较；mypy 若未运行则明确 NOT_RUN。
- 真实 API / benchmark / ablation 均为 NOT_RUN，本次没有新增其通过证据。
- 最终结论：`MERGE_PASS`、`MERGE_PASS_WITH_ENV_LIMITATION` 或 `BLOCKED`。
- 后续仅建议在另行授权后设计 WorkerExecutor/Team Runner、生命周期与结果集成，不声称 Multi-Agent 执行链已完成。

日志在 week5 上单独创建 docs commit；不得包含原始临时输出、venv、凭证或无关改动。日志可以记录 merge/code SHA，但不能把尚未生成的日志 commit SHA 写成已知值；最终回复另行报告日志 commit SHA。

若在晋级前被阻断，在 integration worktree 新增日志并保留现场；不得为了提交日志盲目 stage unresolved merge，也不得假称已合回 week5。

最终回复至少给出：

1. 输入和结果 SHA、merge commit、日志 commit。
2. 当前 week4 / week5 / integration 分支状态及 worktree 路径。
3. 实际变更、冲突和证据保全情况。
4. 测试结果与历史 Ruff/mypy 债、环境限制。
5. 日志绝对路径。
6. 明确“未 push、未执行真实 benchmark、未实现 B 部分”。

## A10. 本次 Real LLM 规则

正常纯合并不重跑 F03 x 5 / B01 x 2 / 11-task x 3。

如果合并过程中不得不手工修改 Runtime、Provider、tool、sandbox 等核心行为，这已超出本次纯合并授权：

- 先停止并报告需要修改的契约。
- 获得后续授权后再修复并补确定性测试。
- 需要真实模型确认时，最后只提供 B01 smoke 命令供用户亲自执行。
- 本次 merge-coder 不自动运行 B01，不以未运行的 smoke 作为 PASS 证据。

---

# B. 合并后的 Week5 架构路线

> 以下区分当前 Day1–Day4 已实现基础设施与后续适配路线，不是本次 merge 的生产代码修改清单。
> 后续每个阶段需要用户重新授权，并按 Coder 教学/研发规约执行。

## B1. 唯一执行引擎

目标链路：

```text
LeadAgent
  -> LeadPlanningResult
  -> TaskDAG
  -> TaskScheduler                 [已实现进程内调度]
  -> TaskClaim                     [已实现，尚非完整 attempt fencing]
  -> WorkerExecutor                [待实现]
  -> CodingAgentRunRequest
  -> Week4 CodingAgentRuntime
  -> CodingAgentRunResult
  -> Team Runner / IntegrationService [待实现]
```

WorkerAgent 保留 identity、role、capability 职责。不要在其中复制第二套 LLM/Tool/repair/completion 循环。

不把旧 ModelClient.complete 或旧 Orchestrator 重新接回生产执行路径来适配多 Agent。

## B2. 保留现有 Dependency Contract，后续再讨论规划声明归属

当前事实：

- LeadPlanningResult 只有 task_id、plan、assignments。
- TaskDAG factory 接受显式 assignment-ID dependency pairs，默认 None。
- 多节点未声明时抛 UndeclaredDependenciesError；显式空 tuple 表示独立节点，单节点允许省略；factory 返回前 validate。
- 重复 edge 在当前 DAG 中是幂等的。
- 两种 TaskStatus 分属顶层 Coding Task 和 DAG Node，不能直接互换。

当前 factory 已区分下列语义；后续是否将声明搬入 LeadPlanningResult，需要单独设计迁移，不在本次实施：

```text
None -> 未声明
()   -> 明确独立
```

目前 fail-closed 语义已经有实现和测试，不能恢复成旧的默认全部独立。

推荐后续决策：

- dependency spec 使用 step-ID 还是 assignment-ID，必须唯一且明确。
- 若采用 step-ID spec，由 factory 映射到 assignment-ID；同时保证映射一对一，或明确多 assignment 的展开规则。
- 不将两个来源同时作为权威，不让显式参数与 result 内 dependency 静默覆盖。
- 不根据文件重叠或 PlanStep 的排列顺序猜依赖。
- 不为多 Agent 修改共享 PlanStep 的既有执行契约。
- 保留多节点未声明时 fail-closed、单节点可省略的既有契约；如未来迁移声明来源，另写 DD 并测试。
- 重复声明是拒绝还是规范化，单独决定，不顺手破坏当前底层 add_dependency 的幂等性。

测试覆盖链、diamond、独立节点、unknown/self/cycle、声明遗漏和 ID 映射。

## B3. TaskDAG 状态所有权

旧 Day2 验收指出的内部可变引用风险已由 hardening 改为输入和输出深拷贝；nodes/topological_sort/get_ready_tasks 返回防御性快照，并有对应测试。DAG 的 replace_task_status 拒绝裸字符串，topological_sort 使用 heap。

Scheduler 已在构造时 validate，并要求全 PENDING 的 fresh DAG，随后使用拓扑快照和自己的 TaskRuntimeRecord 状态。后续适配层仍需遵守：

- 保留已有 defensive copy，不暴露内部可变状态。
- Scheduler 执行期状态以 TaskRuntimeRecord 为权威，不把原 DAG 的状态当同步投影。
- node_id 与 assignment_id 是否必须相同。
- DAG 查询只计算依赖就绪，不偷偷写 READY。
- 两种 TaskStatus 在适配层使用明确 alias。

不要在本次 merge 中冻结模型、恢复旧引用语义或重写现有状态测试；已有 heap 实现原样保留。

## B4. 已有 Scheduler 与尚待设计的 Attempt Fencing

当前 Scheduler 已实现 Lock 保护的原子 claim、owner 校验、attempt 计数、retry cap、缺角色等待和锁外事件 sink。start/complete/fail 仍按 node_id/worker_id 校验 owner 和预期状态，未校验调用方携带的 attempt；同 owner 跨 attempt 的迟到结果隔离不能宣称已证明。这是当前契约边界，本次不重构，也不把后续要求冒充合并新增失败。

后续设计应包含：

- 原子 claim、明确 owner、单调 attempt 或等价不可复用 claim token。
- start/complete/fail 接收并验证完整 claim，而不仅 node_id/worker_id。
- 旧 attempt 迟到结果不能完成新 attempt，即使 worker_id 相同。
- 拒绝 stale claim 时不改变节点状态、worker availability、usage 或 completion 事件。
- 可重试失败、终态失败、取消和暂停有明确规则。
- WorkerRegistry 只负责身份/静态能力，动态占用只有一个权威来源。

现有 claim/retry 测试必须保留；完整 fencing 与 Worker 适配的后续设计仍须另行授权、先确定性验证再接真实 Worker。

## B5. WorkerExecutor 适配边界

WorkerExecutor 只做：

```text
WorkerExecutionRequest
  -> build CodingAgentRunRequest
  -> CodingAgentRuntime.run()
  -> WorkerExecutionResult
```

Team Runner 才负责 Scheduler lifecycle；不把 scheduler.start/complete/fail 嵌进适配器。

关键契约：

- assignment_id 当前形如 `plan_id:step_id`，不能直接作为 WorktreeManager task ID。
- 生成合法、抗碰撞且含 team/node/attempt 身份的 execution ID；不放宽 WorktreeManager 路径规则。
- 明确 fresh attempt 与同 attempt resume 的区别；前者默认新 worktree，后者恢复既有 Session/worktree。
- WorkerAssignment.verification 可能是自然语言，不能 shlex.split 后就当权威命令。
- 验证命令来自受信任结构化配置，并继续经过 Runtime 命令和安全边界。
- Runtime PAUSED/approval/environment failure 原样返回，不能粗暴当 coding FAILED 或自动 retry。
- 并行 Worker 各有独立 Runtime、Session、可变 ModelClient 状态、usage 和 evidence；可共享只读配置。
- 使用 factory 构造执行实例，不假设 mutable Runtime/Provider 客户端线程安全。

## B6. 已有 Mailbox 的通信边界与后续接入

当前 AgentMailbox 已实现进程内同步通信：独立地址簿、deque + Lock、per-inbox FIFO、非阻塞 destructive receive、容量拒绝、去重、原子 broadcast、锁外事件 sink。hardening 已覆盖批内 UUID 碰撞拒绝、JSON payload、有限非负时间戳，以及 TASK_COMPLETED/TASK_FAILED 不自动改变 Scheduler 的测试。

接入 Team Runner 时必须继续保持：

- Mailbox 传消息，不直接修改 Scheduler 状态。
- TASK_COMPLETED 消息不等于已验证完成。
- Scheduler 是任务状态权威；Team Runner 验证结果和 claim 后显式推进。
- 重复/迟到消息、未知 worker、消息顺序、投递失败须测试。

当前不证明 durable delivery、ack/replay、跨进程通信、完整 claim fencing 或端到端 Worker 执行。既有 benchmark/ablation 文档按各自 SHA 和 STALE/DEFERRED 标记保留，本次不重跑。

## B7. 确定性 Team Smoke 先于真实模型

后续按顺序验证：

1. 单节点 scripted model：claim -> Runtime -> patch -> verification -> diff/submit -> 结果消费。
2. retry + fencing：attempt1 迟到结果不污染 attempt2。
3. 两个 worktree 的源码、Session、usage、事件互不污染。
4. Runtime PAUSED 与环境失效不会被误记为节点完成或 coding failure。
5. 在真实 Team Runner 接入已有 Mailbox 后，消息仍不会绕过状态权威。

之后才由用户另行授权真实单 Worker smoke，再扩展到两个独立 Worker。

第一轮不要同时启用 LLM Lead、LLM Worker、并发、依赖和结果合并，避免无法定位失败来源。

## B8. Dependent DAG 需要代码集成状态

`A completed -> B ready` 只解决调度依赖，不能使 B 自动看到 A 在另一个 worktree 的未提交修改。

后续目标：

```text
Integration base C0
  -> Worker A worktree @ C0
  -> Runtime completed
  -> IntegrationService 验证并集成 A 结果
  -> Integration commit C1
  -> 节点 A 对依赖方可消费
  -> Worker B worktree @ C1
```

规则：

- 依赖节点只有在前置结果已进入可消费的代码基线后才能解锁。
- 区分 Worker 执行成功与团队结果已集成；必要时单独设计 integrating 状态。
- IntegrationService 复用现有 Git/Patch/SafeExecution 能力，不实现第二套 patch engine。
- 使用专用团队 integration workspace，不修改用户原始仓库工作区。
- WorktreeManager 需要真实 commit base，不能把 integration 工作区的未提交修改冒充新的 base SHA。
- 冲突、验证失败、stale base、并发集成应有单独的 fail-closed 规则。
- 用户分支最终合并与团队内部临时 integration commit 是不同授权边界。

## B9. 后续顺序与非声明

```text
本次：week4 -> week5 干净合并 + 确定性回归
  -> 保留已实现 DAG/Scheduler/Mailbox，另行设计完整 claim fencing 与适配契约
  -> WorkerExecutor + scripted-model Team smoke
  -> 已有 Mailbox 的 Team Runner 接入与后续生命周期边界
  -> 用户授权的单 Worker real smoke
  -> 两个独立 Worker
  -> Dependent DAG + IntegrationService
```

每一步按照实际 Week5 教程重新对齐范围、DD、配套测试和验收，不能因为本文件列出路线就视为已授权实现。

最终准确表述：

> 本次验收通过后，只证明 Week4 Runtime 与 Week5 Day1–Day4 及 hardening 能在同一代码基线上共存。真正的 Multi-Agent Coding Harness 仍需 Worker 适配、完整 claim fencing、生命周期及结果集成验证；这些均未在本次实现。
