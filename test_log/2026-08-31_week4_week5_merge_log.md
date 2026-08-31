# Week4 → Week5 合并验收日志

验收日期：2026-08-31（Asia/Shanghai）。目标 week5 全量授权复验于 11:38 完成。

结论：**MERGE_PASS**。本地 week5 已安全 fast-forward，目标复验 **1583 passed / 0 failed / 0 error / 0 skipped**，Docker 已实际验证。只证明现有 Week4 Runtime 与 Week5 Day1–Day4/hardening 共存，不表示完整 Multi-Agent Coding Harness 已实现。

## 1. 授权与固定输入

本轮按用户明确授权执行方案 A，不是教学或新功能开发。重新完整阅读 `.codex/AGENTS.md`、`prompt/coder_Agent.md`、合并方案，并阅读 README、pytest.ini、pyproject.toml、适用 Week5 教程/验收记录及当前 DAG/Scheduler/Mailbox/模型/测试。没有调用子 Agent。

用户已确认采用旧 `4f8aa91` 之后新增的 7 个 Week5 提交，本次没有使用旧 Week5 输入。

| 项目 | 完整 SHA |
|---|---|
| Week4 原代码 | `c8896a067708c0fe34b0727d04fa0602cc9ceaac` |
| Week5 固定输入 | `58fed46109033acfb72862686f63c51f83b6c548` |
| merge-base | `3956afc05d6c1ad2f3efaac9a510133436c0f700` |
| 方案 commit / 新固定 W4_SHA | `28bd53f9b25e95ad77ff035b0a3580320a902bb4` |
| merge commit / 已复验代码 SHA | `ad3ac1c87a429d54f7e2a8a03646a1e43cf315bd` |
| merge tree | `56ab2b6ea9292b59d210167c440eb4fe699a1a9d` |
| parent 1 | `58fed46109033acfb72862686f63c51f83b6c548` |
| parent 2 | `28bd53f9b25e95ad77ff035b0a3580320a902bb4` |

实际检查了 status、staged/unstaged/untracked、branch、HEAD、merge-base、rev-list、worktree 占用。再次 fetch origin 成功时，origin/week4 为原代码 SHA，origin/week5 为新固定 Week5 SHA；这是本轮 fetch 时快照，不保证之后远端不变。

方案原为 staged 新文件。保留内容，修订过期事实、Import Gate 和 B 部分已实现/未实现边界，检查 staged diff 后只提交该文档（660 行）。新 Week4 HEAD 的唯一新增路径为 `prompt/merge_week4_week5.md`，生产代码未变。此纯文档输入变化由用户预先授权。

相对 merge-base：原两边独有提交 13/12、改动路径 365/42；方案提交后为 14/12、366/42。恰好三条共同修改路径。

## 2. 合并操作与冲突矩阵

```bash
git worktree add -b codex/integration-week5-week4-runtime /private/tmp/agent-learning-week5-week4-20260831-0028 58fed46109033acfb72862686f63c51f83b6c548
git merge --no-ff --no-commit 28bd53f9b25e95ad77ff035b0a3580320a902bb4
git commit -m "merge: integrate week4 coding runtime into week5 foundation"
git switch week5
git merge --ff-only ad3ac1c87a429d54f7e2a8a03646a1e43cf315bd
```

初次 merge exit 1 是两份文档的预期冲突。解决、验收后才创建 merge commit。晋级前再次确认 integration 干净、parent 正确、week5 仍等于固定输入且未被其他 worktree 占用；switch/ff 均 exit 0。

| 文件 | 实际情况 | 保留方式 |
|---|---|---|
| `codeteam/events.py` | 自动合并，无文本冲突 | 保留 Week4 Runtime 与 Week5 9 个 Scheduler、5 个 Mailbox 事件。AST 校验 73 个枚举名/值恰为双方并集，共有键值一致；移除枚举成员后的 AST 与双方相同。 |
| `learning-plan/代码架构.md` | 2 个冲突区块 | 双方测试数字保留为历史记录，不当作本次验收；保留完整 Week5 控制面和 Week4 Runtime 补充链路，分开标注早期评测/演进证据；澄清 Mailbox 已实现但尚未接入完整 Worker 执行链。 |
| `learning-plan/设计决策.md` | 1 个文本冲突区块，另有编号重叠 | D28 保留已演进的 V2；双方 D29–D32 全部保留，Week5 加 W5- 来源前缀，并补 Mailbox 索引。既有 DD-W5-01…04 文档和实现不变。 |

两份文档是唯一人工冲突编辑路径。未整文件选择 ours/theirs，未修改生产行为、接口、测试预期、依赖声明或安全配置。未新增 WorkerExecutor、重构 dependency/fencing contract、修无关缺陷或批量 lint。

保留实际契约：DAG 七态（含 CLAIMED）、defensive copy、heap topo、显式 dependency fail-closed；Scheduler fresh-PENDING 拓扑快照、锁内 claim/状态推进与锁外事件 sink；Mailbox 原子 broadcast、JSON payload、有限非负时间戳、per-inbox FIFO、destructive receive。

现有边界仍在：start/complete/fail 仅接收 node_id/worker_id，未校验调用方 attempt，不能宣称完整 fencing；Mailbox 非持久化，累计 seen IDs/events 不受 inbox capacity 总量约束。这不是本次新增失败，未在本次修复。

## 3. 输入与实验保全

提交前 tree、晋级后 HEAD 的只读审计均通过：

- Week4 独有改动 363 条路径：mode/blob 与固定 W4_SHA 一致，0 mismatch。
- Week5 独有改动 39 条路径：mode/blob 与固定 W5_SHA 一致，0 mismatch。
- 双方改动集合以外没有额外 tree 改动。Runtime、CLI/eval、agent_team 七个模块、测试及 pyproject 均保持来源 blob；三条共同路径单独审计。
- `stability_20260830_190244/` 的 **202 个已跟踪文件**：路径、mode、blob 与固定 W4_SHA 相同，并逐文件 `git hash-object --no-filters` 核验工作树内容相同。
- 原 Week4 代码 SHA 与 merge SHA 在该实验目录的 `git diff --quiet` 亦 exit 0。
- 未删除、移动、取消跟踪、改写实验文件，未改归档/忽略策略，保留原 `/evals/week4/agent_runs/` 规则。
- `git ls-files -u` 为空；在 codeteam/tests/learning-plan/prompt/README/config 范围匹配真实冲突 marker 行，无匹配。

仅检查 stability summary/manifest 必要元数据。旧记录报告 F03 5/5、B01 2/2、11-task 33/33；manifest 的 base_commit 是 fixture 基线，不是 Runtime 代码 SHA。未发现可据此证明最新 Runtime SHA 的明确执行代码字段，因此只称随原 Week4 提交保留的历史证据，不算本次新 benchmark 成果。

未读取/输出/复制 `secrets.local.env` 或加载真实模型凭证。无真实 API、B01/F03 campaign、11-task benchmark、ablation；现有测试的 fake/scripted provider 与临时仓库不属于真实 benchmark。

## 4. Python、安装与 Import Gate

源解释器 `/Users/root/workspace/Agent-Learning/.venv/bin/python`：Python **3.11.15**。私有 `.venv` 由源 Python `-m venv` 创建，同为 **3.11.15**，`include-system-site-packages=false`。没有共享/复制源 editable 安装，也未修改源 venv。

私有环境根：`/private/tmp/agent-learning-week5-week4-20260831-0028/.venv`。

测试工具对齐：pytest **9.1.1**、Ruff **0.16.2**、mypy **2.3.0**。pytest.ini/pyproject 保持来源内容，未新增 skip/xfail、改断言或关闭安全检查。

实际安装命令（cwd 为 worktree；EVIDENCE 为第 8 节临时目录）：

```bash
.venv/bin/python -m pip --isolated install --disable-pip-version-check --index-url https://pypi.org/simple -c "$EVIDENCE/constraints.txt" -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pip --isolated install --disable-pip-version-check --index-url https://pypi.org/simple -c "$EVIDENCE/constraints.txt" -e .
.venv/bin/python -m pip check
```

首次 requirements 安装因沙箱 DNS 失败 exit 1，按权限流程重试后 exit 0。合并前/后各执行 editable 安装及 pip check，均 exit 0、No broken requirements。constraints 仅保存包名/版本，不读认证配置，不写回项目。SciPy 下载较慢但最终安装成功。

| 包 | 源 Week4 环境 | integration/目标 week5 环境 |
|---|---|---|
| pydantic / pydantic_core | 2.12.5 / 2.41.5 | 2.13.4 / 2.46.4 |
| networkx | 3.4.2 | 3.6.1 |
| numpy | 1.26.4 | 2.4.6 |
| scipy | 1.15.3 | 1.17.1 |
| tree-sitter | 0.25.2 | 0.26.0 |
| tree-sitter-python | 0.25.0 | 0.25.0 |
| PyYAML | 6.0.3 | 6.0.3 |
| typer | 0.23.0 | 0.23.0 |
| markdown-it-py | 4.0.0 | 4.2.0 |
| codeteam 安装元数据 | 0.4.0（源旧元数据） | 0.1.0（当前 pyproject） |

运行依赖遵守仓库严格版本，没有为复用旧环境而放宽约束。以上差异不误判为 merge 回归；私有环境验收均通过。

Import Gate 合并前覆盖 Foundation，合并后增加 Runtime；分别在 worktree 内和仓库外临时 cwd 用私有 Python 绝对路径执行，目标 week5 再检查一次：

```python
from codeteam.agent.runtime import CodingAgentRuntime
from codeteam.agent_team.lead import LeadAgent
from codeteam.agent_team.worker import WorkerAgent, WorkerRegistry
from codeteam.agent_team.dag import TaskDAG
from codeteam.agent_team.scheduler import TaskScheduler, TaskClaim
from codeteam.agent_team.mailbox import AgentMailbox, AgentMessage, AgentMessageType
```

全部 exit 0。模块 `__file__` 均在 `/private/tmp/agent-learning-week5-week4-20260831-0028/codeteam/`，无源目录导入；sys.prefix 正确。agent_team 公共导出 identity 一致；DAG TaskStatus 与 Coding TaskStatus 不同，七态完整。未导入不存在的 WorkerExecutor，未设置 PYTHONPATH 指向源项目。

## 5. 实际 pytest 与 Docker 结果

均使用当前 worktree `.venv/bin/python -m pytest`；所有 pytest 运行 **failed=0 / errors=0**。

| 阶段 | pytest 参数 | exit | 实测结果 | 时间 |
|---|---|---:|---|---|
| Week4 基线，源 venv，常规沙箱 | `-q -rs` | 0 | 1409 passed, 9 skipped | 53.69s |
| Week4 Docker 授权复跑 | `tests/sandbox -q -rs` | 0 | 71 passed, 0 skipped | 3.78s |
| Week5 Foundation 基线 | `tests/agent_team -q -rs` | 0 | 165 passed, 0 skipped | 4.20s |
| Week5 全量基线，常规沙箱 | `-q -rs` | 0 | 1366 passed, 6 skipped | 27.92s |
| Week5 Docker 授权复跑 | `tests/sandbox -q -rs` | 0 | 42 passed, 0 skipped | 1.93s |
| integration Foundation | `tests/agent_team -q -rs` | 0 | 165 passed, 0 skipped | 4.12s |
| integration Runtime 回归 | 下方完整目录列表 | 0 | 639 passed, 9 skipped | 51.29s |
| integration 全量，常规沙箱 | `-q -rs` | 0 | 1574 passed, 9 skipped | 59.72s |
| integration Docker，常规沙箱 | `tests/sandbox -q -rs` | 0 | 62 passed, 9 skipped | 0.16s |
| integration Docker 授权复跑 | `tests/sandbox -q -rs` | 0 | 71 passed, 0 skipped | 3.75s |
| 目标 week5 Foundation | `tests/agent_team -q -rs` | 0 | 165 passed, 0 skipped | 4.11s |
| 目标 week5 全量，常规沙箱 | `-q -rs` | 0 | 1574 passed, 9 skipped | 57.89s |
| **目标 week5 全量，Docker 可访问授权终端** | `-q -rs` | **0** | **1583 passed, 0 skipped** | **61.36s** |

Runtime 完整命令：

```bash
.venv/bin/python -m pytest tests/agent tests/execution tests/sandbox tests/git tests/session tests/evaluation tests/cli tests/llm -q -rs
```

Runtime 子集不替代全量；根目录 AgentLoop/协议测试由全量覆盖。agent_team 测整个目录，包含 DAG、Scheduler、Mailbox 及既有 hardening。

常规沙箱 skip 原因均为访问 `unix:///Users/sqlee/.colima/default/docker.sock` permission denied。Week4/integration/目标有 9 条 Docker 测试，Week5 原输入有 6 条，不是新增未解释 skip。未改 socket/Colima/skip 条件/安全开关，权限复跑后实际执行。最终全量无 skip，但保留早先环境限制记录。

既有测试镜像 `codeteam-sandbox:latest`，只读 inspect：

```text
ID: sha256:dff25cf760392c91085850801d346048c04eb336d5acd528d3245cd2095c3956
RepoDigest: codeteam-sandbox@sha256:dff25cf760392c91085850801d346048c04eb336d5acd528d3245cd2095c3956
```

测试使用已有镜像、`--pull=never`，未 pull/build。Docker 本次已验证，最终不是 MERGE_PASS_WITH_ENV_LIMITATION；常规沙箱本身的 socket 权限限制仍客观存在。

## 6. 静态检查与历史债

### Ruff

全仓命令：`.venv/bin/python -m ruff check codeteam tests --output-format json --output-file <阶段>-ruff.json`。

两输入同为 Ruff 0.16.2。保存 `--show-settings`，归一化 worktree root 后完全相同；verbose 显示 Ruff default settings，target Python 从 requires-python 推导为 Py311。未改规则或运行 --fix。Ruff 扫描包含 pytest 不收集的 fixture 源文件，所以保留历史 invalid-syntax。

| 阶段 | 全仓诊断 | exit | agent_team 局部检查 |
|---|---:|---:|---|
| Week4 | 168 | 1 | 无该模块；events 局部 exit 0 |
| Week5 | 190 | 1 | 0 诊断，exit 0 |
| integration | 168 | 1 | 0 诊断，exit 0；events 亦通过 |
| 目标 week5 | 168 | 1 | 0 诊断，exit 0；events 亦通过 |

按 **相对路径、rule、起止行列、message** 比较 merged/target 与两个输入诊断集合并集，**新增 0**。不是只比总数，不能说全仓 Ruff 零错误通过。merged/target JSON 哈希相同。

规则计数如下（W4 与 merged/target 相同；完整逐项位置/消息见第 8 节 JSON）：

```text
W4/merged/target:
B005=1 BLE001=14 F401=43 F541=1 F811=1 F821=2 F841=3 FURB122=1
I001=64 PERF102=1 PIE790=2 PIE810=2 PLW1510=6 PYI013=2 RUF012=4
RUF059=2 S112=1 SIM102=1 SIM103=1 SIM114=1 UP012=1 UP017=10 UP035=3
invalid-syntax=1
W5 与以上相比的计数差异：
BLE001=15 F401=44 I001=68 TRY201=2 UP006=1 UP017=21 UP035=5
```

### mypy

Week4 源 venv 补充审计 `.venv/bin/python -m mypy codeteam`：exit 1，**79 errors / 15 files / checked 178 source files**。这是整个生产包的历史债，不与只扫 agent_team 的数量作等价比较。

Week5 基线、integration、目标均运行 `.venv/bin/python -m mypy codeteam/agent_team tests/agent_team`，均 exit 1，**5 errors / 4 files / checked 14 source files**。位置和消息相同，新增 0。它们位于目标范围，不能误称全是 import-chain 债：

| 位置 | 已有诊断 |
|---|---|
| `codeteam/agent_team/dag.py:197` | dependents 缺类型注解，var-annotated |
| `tests/agent_team/test_scheduler.py:478` | received 缺类型注解，var-annotated |
| `tests/agent_team/test_models.py:107` | role 的 str 与 AgentRole 不兼容，arg-type |
| `tests/agent_team/test_models.py:110` | status 的 str 与 AgentStatus 不兼容，arg-type |
| `tests/agent_team/test_dag.py:86` | status 的 str 与 TaskStatus 不兼容，arg-type |

本次不清零历史债，未新增 ignore、改类型配置或修生产/测试代码。

### Git whitespace

工作树与 index 间 `git diff --check` exit 0，三条共同路径的 staged diff --check exit 0。全体 `git diff --cached --check` exit **2**：193 条 trailing-whitespace/EOF blank-line 诊断，来源含文档及实验 diff。相同命令检查输入 Week4=193、Week5=6；按路径/行/诊断比较，合并新增 **0**。来源 blob 已证实未改，尤其没有为消除检查输出而改写实验文件。

## 7. 分支状态与未完成项

日志写入前目标 week5 与 integration 均在已复验 merge SHA，worktree 干净；用户源目录仍为 week4，无测试污染。

- 源 worktree：`/Users/root/workspace/Agent-Learning`，week4=`28bd53f9b25e95ad77ff035b0a3580320a902bb4`，相对 origin/week4 快照 ahead 1。
- 保留 integration 分支：`codex/integration-week5-week4-runtime`=`ad3ac1c87a429d54f7e2a8a03646a1e43cf315bd`。
- 保留本次 worktree：`/private/tmp/agent-learning-week5-week4-20260831-0028`，当前检出 week5。
- 目标已复验代码 SHA：`ad3ac1c87a429d54f7e2a8a03646a1e43cf315bd`。本日志随后作为唯一文件单独 docs commit，parent 为该 merge SHA；生成后最终汇报给出日志 commit SHA，避免自引用伪造。
- 日志提交后 week5 比 merge 多 1 个纯日志提交，相对 origin/week5 快照 ahead 16。未新建 baseline tag。
- 历史 5 个 prunable Week3 worktree 登记与 `.claude/worktrees/test_agent_parsing` 均未清理、删除或切换。

方案 A 没有未完成的阻断 Gate。历史 Ruff/mypy/whitespace 债保留；完整 Worker 执行、attempt fencing、持久生命周期、结果集成及真实性能验证仍需后续授权。

明确：**未 push、未 force push、未 reset、未覆盖用户修改、未执行真实 API/benchmark/ablation、未实现 B 部分。** B 部分只修订事实与后续路线文本。

## 8. 日志与原始证据位置

本日志为新文件，不覆盖或追加旧日志：

`/private/tmp/agent-learning-week5-week4-20260831-0028/test_log/2026-08-31_week4_week5_merge_log.md`

原始证据目录（不提交原始输出、venv 或包清单）：

`/private/tmp/week4-week5-merge-20260831.q7ZfD0`

包含各阶段 pytest/Docker 输出、`merged-runtime.txt`、`target-pytest-escalated.txt`、各阶段 Ruff JSON/settings、mypy/whitespace 输出、安装记录、仅包名/版本的环境清单、只读 `audit.py`、`week5-fast-forward.txt` 和 staged stat。临时目录不是长期归档替代品，Git 中本日志与固定输入可用于重现检查。

关键原始证据 SHA-256：

```text
w4-ruff.json                34ce0fe8b76b8dc67b0bee0382bf89f63ee27e0068ec3138c74d8d02a3a85ca8
w5-ruff.json                15932e467248feb262f3593ca073e183dc5b10b99ec0ea1f6c48467d01b95fc4
merged-ruff.json            0d8f323d46968efece17e8ad5914575540462903cbc4d8c28d42983fa78343ff
target-ruff.json            0d8f323d46968efece17e8ad5914575540462903cbc4d8c28d42983fa78343ff
target-pytest-escalated.txt  97b35a00b034436afe4364f4743589304cb561a7cdea050110a811d0ab17d0cd
```
