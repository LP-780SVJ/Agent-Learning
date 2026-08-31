# Week5 Day5 Lifecycle P1/P2 Coder 修复日志

## 结论边界

日期：2026-09-01，Asia/Shanghai。此日志为 Coder 修复与自检证据，不代替
独立 tester 再次验收。没有开始 Day6，也未运行真实 API、Benchmark 或 Ablation。
Benchmark/Ablation 保持 NOT_RUN。

原验收事实保留在 `test_log/2026-09-01_week5_day5_lifecycle_acceptance_log.md`，
本轮未修改该文件或原验收测试。本文记录两类已确认缺陷的修复，而不是覆盖
此前的 FAIL 结论。

## 工作树与输入保护

项目：`/Users/root/workspace/Agent-Learning`。
HEAD：`25dc4c70ac433e0924a65cd2f3a43a320a812b63`；branch：week5。
环境实测：Python 3.11.15，Darwin arm64。所有 Python 命令使用 .venv/bin/python。

开始时工作树包含未提交及未跟踪的 Day5 实现，完整纳入检查和修复：
```text
## week5...origin/week5 [ahead 1]
 M codeteam/agent_team/__init__.py
 M codeteam/agent_team/models.py
 M codeteam/agent_team/scheduler.py
 M codeteam/agent_team/worker.py
 M codeteam/events.py
 M docs/benchmark/W5_SCHEDULER.md
 M evals/week5/benchmark_scheduler.py
AM learning-plan/week5/day5.md
 M tests/agent_team/test_mailbox.py
 M tests/agent_team/test_scheduler.py
?? codeteam/agent_team/contracts.py
?? codeteam/agent_team/coordination.py
?? codeteam/agent_team/lifecycle.py
?? codeteam/agent_team/registry.py
?? docs/benchmark/W5_LIFECYCLE.md
?? docs/design_decisions/DD-W5-05.md
?? docs/failure_cases/W5_LIFECYCLE_FAILURE.md
?? test_log/2026-08-31_week5_day5_lifecycle_implementation_log.md
?? test_log/2026-09-01_week5_day5_lifecycle_acceptance_log.md
?? tests/agent_team/test_fencing.py
?? tests/agent_team/test_lifecycle.py
?? tests/agent_team/test_lifecycle_acceptance.py
?? tests/agent_team/test_registry.py
```

开始与复核时的暂存区摘要均只有 day5.md（3373 insertions）；
该文件 index blob 仍为 `39669324b43e3156589531ae2512e3016f25a755`。
未执行切分支、创建 worktree、stage/commit/merge/push、reset/clean 或 socket 权限修改。
没有修改配置、fixtures、evals、教学文档、旧测试及历史日志。
新日志创建前已用 test -e 确认同名不存在（exit 1）。

### 修改前 SHA256

```text
835c20b38bbd3870c02866990af5d465620f29c34c3685e2c7a7699d87666221  codeteam/agent_team/registry.py
5c5bd5ee837f189bc0c59a56458d173cd674759d18f321885a2a55e26c3256a9  codeteam/agent_team/lifecycle.py
1001aaf5b4e4f2ef2096e84cb55ec351518708719b4b7cff0a16c35b88d3a25b  codeteam/agent_team/scheduler.py
415c3bf2e0cf2a099aabca1b8ecedab3f24bb10c67fb17df46228fa9d7bdb599  tests/agent_team/test_lifecycle_acceptance.py
2e55f7a659cc5445f9c34a6044eff09528a7b3e2925badd740defee7e6333b25  tests/agent_team/test_lifecycle.py
7eeeac0b3fb17b04099855246c8dfe500ba12c1eea97e42cb18fb2f864733966  tests/agent_team/test_fencing.py
f80bd4740e188d76b9c55d24e777972d6964a7350687514a060eaf83e9b71a4c  tests/agent_team/test_scheduler.py
8787f999271c500e2e11867f237d7c48974efdbdd3406cc32bf35e5e59ca8bc4  docs/design_decisions/DD-W5-05.md
c2768bd4d54553b02cf76c99b3694a7398b33e333de93ce28cfa871a787969ac  docs/failure_cases/W5_LIFECYCLE_FAILURE.md
a58ac73d30138bd98ad55256fff27f39e5bafeec0961a43462cdf026853a248f  learning-plan/week5/day5.md
dc3edbcadf9333e41b694cfb4cebca4351f6549e785077b4ebfc5ab42e1561e7  test_log/2026-09-01_week5_day5_lifecycle_acceptance_log.md
```

## 修复前真实复现

实际命令：
```bash
.venv/bin/python -m pytest tests/agent_team/test_lifecycle_acceptance.py -q
```

结果：exit 1，52 passed / 6 failed，0.16s。没有 collection error、skip 或 xfail。

P1 的两项失败：
- test_restart_interrupt_cleans_matching_reservation[reservation_observer-KeyboardInterrupt]
- test_restart_interrupt_cleans_matching_reservation[reservation_observer-SystemExit]

实际 Worker.status=RESTARTING，restart_id 仍存在；预期 FAILED/None。
reservation 已提交、预算已消耗，但 observer 中断发生于返回 ticket 前，factory 未调用。
同测试的两项 factory 中断实例原本通过，不能把四项笼统归为同一失败。

P2 的四项失败：
- test_exhausted_loss_blocks_all_descendants_in_one_transaction[timeout-False]
- test_exhausted_loss_blocks_all_descendants_in_one_transaction[timeout-True]
- test_exhausted_loss_blocks_all_descendants_in_one_transaction[stop-False]
- test_exhausted_loss_blocks_all_descendants_in_one_transaction[stop-True]

False/True 对应 CLAIMED/RUNNING。Z -> M -> A 中 Z FAILED、M BLOCKED，
但 A 实际仍 PENDING。不是预算或 ownership 错误，而是单次 ID 扫描传播不完整。

## 本轮修改文件

1. codeteam/agent_team/registry.py
2. codeteam/agent_team/lifecycle.py
3. codeteam/agent_team/scheduler.py
4. tests/agent_team/test_lifecycle_fixes.py（新增）
5. docs/design_decisions/DD-W5-05.md（追加验收纠正）
6. docs/failure_cases/W5_LIFECYCLE_FAILURE.md（保留旧案例，追加 F13/F14）
7. test_log/2026-09-01_week5_day5_lifecycle_fix_log.md（本文件）

生产修改没有扩大到授权的三个文件之外。原 tests/agent_team/ 文件均未修改；
git status 中那些已有修改属于任务开始前的工作树状态。

## P1 修复原理

Registry 在持有实际 RestartTicket 的 reserve_restart 返回边界捕获
KeyboardInterrupt/SystemExit，而不是只扩大 Lifecycle.try 或查询最新 lease。
它与 factory 中断共用 _interrupt_restart，重新进入事务并复用
runtime/generation/restart_id/revision/RESTARTING 的匹配检查。

匹配时 FAILED、restart_id=None，保留原 Worker、generation、消耗的一次预算、
next_restart_monotonic 和之前已提交的任务回收。过期 ticket 不覆盖 STOPPED、
更新 reservation 或新 generation，只产生拒绝审计。

reservation 的 WORKER_RESTARTING 历史保留；清理是另一次真实提交，使用
restart_interrupted 原因码和同一 restart_id，不能称为“factory 已执行失败”
或“原 reservation 从未发生”。

清理事件在事务提交后锁外投递。仅在已经传播原始中断的窄边界内隔离次生 observer
BaseException，记录 delivery failure 并通过 add_note 留下安全类型名；原异常对象
继续传播。记录次生审计自身失败时也只附注，不能覆盖原始中断。
普通事件投递并未全局吞掉 KeyboardInterrupt/SystemExit。

## P2 修复原理与复杂度

初始化缓存现有 TaskDAG.topological_sort() 的节点 ID 序列，不依赖以后可能被
修改的原 DAG。每次 _schedule_locked 先做拓扑阻塞闭包：
先处理父节点，逐个访问有限节点列表，每条依赖最多检查一次，O(V + E) 时间、
O(V) 集合空间；没有无界反复扫描。

再按原有 ID 顺序应用状态迁移和事件，保留 READY 队列及无关分支的确定性约定。
拓扑序构建使用现有 heap 算法（O(V + E + V log V)，另计模型快照成本）；
整体 Scheduler 还有原有排序、角色检查和 draft copy 开销，不声称整体线性或性能提升。

timeout、stop、普通 fail 耗尽和非重试失败共享该路径。可重试失败在提交时已回 READY，
不提前阻塞后继。每个真实 BLOCKED 转换仅一个事件，与终态提交 transaction_id 一致；
owner 为空，不入 READY 队列。中途事件准备失败则两个对象、队列 membership、
历史事件和事务计数一起回滚。

## 新增回归地图

新增 test_lifecycle_fixes.py：60 个参数实例（28 个 P1，32 个 P2）。
未修改 tester 的六项失败实例或断言。

P1：
- reservation observer / factory × KeyboardInterrupt / SystemExit；
- 清理 observer 无错误或再次抛 RuntimeError / KeyboardInterrupt / SystemExit；
- 原异常对象 identity、预算、cooldown、Worker identity 和 task snapshot；
- observer 或 factory 重入 stop 后中断；
- 旧清理面对同代新 ticket 或新 generation；
- runtime_id/generation/restart_id/revision 四项 fencing 分别验证；
- 清理事件 observer 与其错误审计再失败，原中断仍保留；
- Event + 有界 join 验证清理 observer 不持核心锁。

P2：
- 64 节点长链、分叉汇合 diamond、顺序与反序重命名；
- timeout/stop × CLAIMED/RUNNING、普通 fail、非重试 fail；
- 无关分支、稳定队列/事件 ID 顺序、全部后继 owner/status/attempt；
- retry 尚未耗尽与耗尽、重复 schedule 无新事件；
- 第二个 BLOCKED 事件 append 后注入异常，验证完整业务及审计回滚。

未使用 sleep、skip/xfail、无限重试；线程错误回传主线程断言。全部为独立内存控制面
对象，不操作主仓库 Git 或 fixtures。

## 按要求顺序执行的复验

| 顺序 | 实际命令 | Exit | 结果 |
| --- | --- | --- | --- |
| 1 | .venv/bin/python -m pytest tests/agent_team/test_lifecycle_acceptance.py -q | 0 | 58 passed，0.12s；原六项全绿 |
| 2 | .venv/bin/python -m pytest tests/agent_team -q | 0 | 383 passed，4.35s |
| 3 | .venv/bin/python -m pytest tests/agent tests/session tests/execution -q | 0 | 363 passed，32.04s |
| 4 | .venv/bin/python -m ruff check codeteam/agent_team codeteam/events.py tests/agent_team | 0 | All checks passed |
| 5 | .venv/bin/python -m mypy codeteam/agent_team tests/agent_team | 1 | 4 项历史诊断，3 文件；checked 23 source files |
| 6 | .venv/bin/python -m pytest -q | 0 | 1792 passed，9 skipped，55.58s；普通沙箱 |
| 7 | .venv/bin/python -m pytest tests/sandbox -q -rs | 0 | 62 passed，9 skipped，0.68s；普通沙箱 |
| 8 | git diff --check | 0 | 无输出 |

开发阶段还实际执行：
- 修完生产后的原验收文件：58 passed，0.12s。
- 新增 test_lifecycle_fixes.py 单独运行：60 passed，0.18s。
- 定向 Ruff 首轮报新增测试的 1 个 unused import，删除后复验通过。
- ruff format 仅针对三个授权生产文件和新增测试文件。
- 只读 git/shasum/nl/sed/rg、.venv/bin/python --version、uname -sm 等核对。

### Docker 审批复验

普通沙箱九个 skip 全部因 Docker API socket 权限：
unix:///Users/sqlee/.colima/default/docker.sock。
这些 skip 不能当真实容器边界通过。没有更改 socket 权限，没有 host fallback。

按工具审批机制授权后：
- .venv/bin/python -m pytest tests/sandbox -q -rs：71 passed，零 skip，3.36s。
- .venv/bin/python -m pytest -q：1801 passed，零失败、零 skip，58.33s。
  授权复跑使用与普通沙箱相同的生产代码和测试版本。

## 历史 mypy 诊断逐项核对

1. codeteam/agent_team/dag.py:197：空 set 推导的 dependents 缺类型标注。
2. tests/agent_team/test_models.py:107：故意传非法字符串给 AgentRole 类型参数。
3. tests/agent_team/test_models.py:110：故意传非法字符串给 AgentStatus 类型参数。
4. tests/agent_team/test_dag.py:86：故意传非法字符串给 TaskStatus 类型参数。

已逐行读取，且 git diff HEAD -- 对上述三个文件无输出；它们未被本轮修改。
诊断与先前验收四项逐字对应。本轮三个生产文件和新增测试无新增类型诊断，
但整个 mypy 门禁仍是 exit 1，不能写成通过。没有修改历史类型债、添加 Any 或
放宽断言来掩盖问题。

## 剩余限制与交接

Benchmark/Ablation：NOT_RUN；仅保留既有周末计划，没有新性能结果。
没有 Day6、SQLite、跨进程恢复、WorkerExecutor 或第二套 Coding Loop。
同步 factory/observer 永不返回时仍不能抢占；注入的 Python 中断测试不等于真实
OS 任意时点 signal 或 SIGKILL 恢复。若次生审计记录自身失效，诊断保留在原异常
note，而非持久日志；不承诺 durable audit 或 external exactly-once。

本轮缺陷是否修复以原六项及全部回归结果为准。此处的 Coder 自检通过不替代
tester 独立复验，原验收 FAIL 历史保持可追溯。

最终结论：**本轮缺陷修复通过（Coder 自检）**。原六项失败全绿、Agent Team
383 passed、授权全量 1801 passed，无新增回归失败。Ruff 通过；mypy 四项历史
诊断仍未通过，不以 pytest 通过代替静态门禁。独立 tester 复验待进行。

### 最终输入保护与修改指纹

重新计算首次记录的所有输入 SHA256：除三个授权生产文件与 DD/Failure Cases
之外全部一致，包含原验收测试、test_lifecycle.py/test_fencing.py/test_scheduler.py、
day5.md 和原验收日志。暂存区与 HEAD 未变化。三个生产文件的最终 SHA256：

```text
26bf4a348956b59f369f0332f7f648469ff67b2806c7332decbc95f8483b58a9  codeteam/agent_team/registry.py
b6ac735131bee42402c38a3b90921b53f276f855f5b4b76f274eb5d2b6906f3b  codeteam/agent_team/lifecycle.py
0f34b1df9862d7a0eac7d5ac71c4181b56eaaa89e3b017b376e7eca1941c887e  codeteam/agent_team/scheduler.py
0e9e85ec2e1acf065da505b65f1c1d3999444bf796af5fe4e59d074b3c16e1d5  tests/agent_team/test_lifecycle_fixes.py
```

## 建议 Git Commit 摘要（未执行提交）

```text
fix(agent-team): 清理中断的重启预留并完整传播终态依赖

- 使用实际 RestartTicket 清理 observer/factory 中断，保留原始异常
- 防止旧清理覆盖 STOPPED、新 reservation 或新 generation
- 拓扑计算终态阻塞闭包，保留原有确定性调度及事务回滚
- 新增 60 项回归，保留并修复 tester 六项原失败
- 追加 DD、Failure Cases 和修复复验记录，实验保持 NOT_RUN
```
