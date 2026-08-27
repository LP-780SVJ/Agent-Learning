# W5D4 AgentMailbox 正式独立验收报告

**日期**: 2026-08-27
**角色**: Independent Evaluator（Test / Evaluation Agent，验收模式）
**分支**: week5 @ `1a9f52490a60025f2cb059a772ae4c504c90d642`（与预期验收 HEAD 一致）
**权限模式**: 严格独立只读验收（生产代码 / 已有测试 / 教程 / DD / failure case / benchmark 脚本与报告均未改动；唯一写入为本日志；诊断脚本与 benchmark 复现输出均位于 /tmp）
**环境**: Python 3.11.16（.venv），pytest 9.1.1，ruff 0.16.2，pytest-cov 未安装

---

# 1. Evaluation Summary

W5D4 交付物（`codeteam/agent_team/mailbox.py` + `__init__.py` 导出 + `events.py` 5 个 mailbox 事件 + 30 个 mailbox 测试 + benchmark 脚本与报告 + DD + Failure Cases）通过 14 项验收要求中的全部功能判定：

- **Day4 Mailbox 功能结论: PASS**（无 P0/P1 缺陷；1 个 P2 缺陷仅在故障注入下可触发）
- **Day4 工程证据闭环: PARTIAL**（Tests/Benchmark/Failure/DD 齐备，Ablation NOT_RUN，coverage NOT_RUN，raw samples 未保存，内存增长风险未披露）
- **DD-W5-04: PARTIALLY_SUPPORTED**（正确性与 benchmark 趋势已证；缺 ablation 证据 + 1 条 DD 要求在故障注入下被违反 + 内存权衡未披露）
- **全量回归: 1350 passed / 6 skipped（与 Week5 基线一致，6 条均为 Docker 能力性跳过）**
- **生产缺陷: 1 个 P2（broadcast 批内 message_id 去重缺失）**，另记录 2 个 P3 契约缺口、1 个 P2 设计风险（含文档披露缺口）、2 个 P3 测试/证据缺口、1 个 P3 观察项

# 2. Capability Mapping

```
Module: AgentMailbox（W5D4 通信层）
Primary:  Multi-Agent Orchestration — Mailbox / Agent Communication / Coordination Protocol
Secondary: Agent Runtime（Message Model / Queue Semantics / State Boundary）、
           Observability（安全 metadata 审计事件、sink 隔离）、
           Safety（fail-closed 路由 / 容量 / 去重；不绕过 Scheduler ownership）
What was proven:
  1. 14 项验收要求：13 项 PASS + 1 项 PASS（附 D4 缺陷警示）
  2. 线性化点契约：send/receive/broadcast 的锁内原子性与失败无副作用均有行为证据
  3. 边界诚实：in-process / non-durable / at-most-once / 无全局顺序声明，均如实记录
```

# 3. Repository Inspection

```text
HEAD:             1a9f52490a60025f2cb059a772ae4c504c90d642（与预期一致）
初始 git status:  clean（无未提交改动）
Technical Stack:  Python 3.11.16 + pydantic v2；.venv/bin/python
Test Framework:   pytest 9.1.1；ruff 0.16.2
Target Module:    codeteam/agent_team/mailbox.py（329 行）
                  codeteam/agent_team/__init__.py（10 个 mailbox 公共导出）
                  codeteam/events.py（MAILBOX_* 5 个事件类型，37-41 行）
Target Tests:     tests/agent_team/test_mailbox.py（30 个测试）
Evaluation:       evals/week5/benchmark_mailbox.py + docs/benchmark/W5_MAILBOX.md
Public API:       AgentMailbox / AgentMessage / AgentMessageType /
                  MailboxError 家族（5 个异常）全部导出且 import 路径测试通过
File Hash 核对:   mailbox.py 5adc8125...、benchmark 52ce21a6...（与旧报告记录一致）
Missing Interface: 无
Implementation/Requirement Differences:
  - broadcast 批内 message_id 无去重（D4 缺陷，见 §11）
  - payload / created_at 无 JSON 序列化与取值约束（D6/D7 契约缺口）
Applicable Rules: AGENTS.md（.venv、无 skip/xfail 掩盖）、test_Agent.md 验收闭环
```

# 4. Requirement Coverage（Requirement -> Evidence Matrix）

| # | Requirement | Evidence（测试 / 诊断 / 代码位置） | Status |
|---|---|---|---|
| R1 | AgentMessage 为 Pydantic 可序列化通信模型，与 LLM Message、AgentEvent 分离 | `test_agent_message_json_round_trip`；mailbox.py:27-60 独立模型；schemas/messages.py 未改动；AgentEvent 仅作审计载体 | PASS |
| R2 | agent_id/task_id/node_id/correlation_id namespace 清晰；必填 ID 拒绝空值 | `_not_blank` validator（5 字段）+ node_id 空白归一为 None；`test_agent_message_rejects_blank_required_fields`（5 参数化）；day4.md §7.3 明确四类 ID 语义 | PASS |
| R3 | Lead/Worker 独立注册地址；未知与重复 fail closed | `register_agent` 深拷贝 identity；`test_registers_lead_and_worker_addresses`、`test_duplicate_agent_is_rejected_without_overwrite`、`test_unknown_sender_recipient_and_receiver_are_rejected` | PASS |
| R4 | send/receive 防御性副本；嵌套 payload 外部突变不污染队列 | 锁内 `model_copy(deep=True)`（send:155/166, receive:185）；`test_send_defensively_copies_payload`；诊断 D3（4 层深嵌套 + receive 后突变 + events 无 payload 键） | PASS |
| R5 | receive 非阻塞、空 inbox 返回 None、destructive at-most-once | mailbox.py:170-187（popleft 不回队）；`test_receive_empty_inbox_returns_none`、`test_send_and_receive_point_to_point_message`（二次 receive 为 None） | PASS |
| R6 | 每 inbox 按成功 append 线性化顺序 FIFO；不声称多 producer 墙钟全局顺序 | deque + 单锁串行化 append/popleft；`test_receive_preserves_per_inbox_fifo_order`；day4.md §3.5 与 F-W5-D4-09 如实声明边界 | PASS |
| R7 | duplicate message_id 即使原消息已消费也拒绝，失败不改队列 | 全局 `_seen_message_ids`；`test_duplicate_message_id_is_rejected_even_after_receive`；诊断 D1（8 线程同 id：1 成功 / 7 DuplicateMessageError / 队列=1） | PASS（broadcast 路径见 D4 缺陷警示） |
| R8 | bounded capacity 不静默丢弃；MailboxFullError 后原队列不变 | `_require_capacity_locked`；`test_capacity_full_fails_closed_and_receive_releases_capacity`；诊断 D2（16 线程抢 1 容量：队列=1、15 个 MailboxFullError） | PASS |
| R9 | broadcast 独立 message_id、共享 correlation_id；未知/容量/构造失败 all-or-nothing | `test_broadcast_sends_independent_messages_with_shared_correlation_id`、`test_broadcast_unknown_recipient_is_all_or_nothing`、`test_broadcast_capacity_failure_is_all_or_nothing`；诊断 D5（blank task_id → ValidationError；第 2 条构造中途抛错 → inbox/seen/events 全部无部分写入） | PASS（附 D4：uuid 碰撞时批内可重复入队） |
| R10 | 多线程 producer 不丢失不重复；join 有 timeout；无 sleep 猜时序 | `test_concurrent_producers_do_not_drop_or_duplicate_messages`（8×25，Barrier + join 2s）；慢 sink 测试用 ThreadEvent 而非 sleep；grep 审计：无 time.sleep / skip / xfail / asyncio | PASS |
| R11 | event 只记录安全 metadata，不含 payload/secret/完整任务内容 | `test_audit_events_use_safe_metadata_without_payload`（allowed_keys 超集断言 + secret 探针）；诊断 D3 events 键检查 | PASS |
| R12 | sink 锁外调用；重入读取、慢 sink、普通异常不死锁/不回滚/不掩盖已提交结果 | `_deliver_events` 在 `with lock` 之外；`test_event_sink_can_read_mailbox_state_without_deadlock`、`test_slow_event_sink_does_not_hold_mailbox_lock`、`test_raising_event_sink_does_not_rollback_send_or_receive`（含 delivery_failed 不递归投递） | PASS |
| R13 | TASK_COMPLETED/TASK_FAILED 消息只是通信，不改变 TaskScheduler 状态 | 诊断 D9：claim 后发送并消费两种消息，record 保持 CLAIMED/owner 不变，scheduler 零事件 | PASS（仓库无回归测试 → P3-3 测试缺口） |
| R14 | 公共 API 导出完整；Day1-Day3 与全量无回归 | `test_public_api_exports_mailbox_objects`（9 个符号 is 断言）；分层回归见 §6 | PASS |

# 5. Tests（被测工件，未改动）

- tests/agent_team/test_mailbox.py — 30 个测试：模型校验 5、地址簿 4、点对点 3、FIFO 1、重复 id 1、防御副本 2、容量 1、broadcast 4、并发 1、审计安全 1、sink 隔离 3、事件防御 1、失败无假事件 1、API 导出 1、payload 默认独立 1
- 分层：Unit（模型/异常）与 Component（线程/锁/sink）混于同一文件，但断言方式区分清晰；无 Integration/E2E 层（符合 Day4 进程内范围）

# 6. Test Execution Results（全部实际执行）

| 命令 | 退出码 | 结果 | 耗时 |
|---|---|---|---|
| `.venv/bin/python -m py_compile codeteam/agent_team/mailbox.py codeteam/agent_team/__init__.py codeteam/events.py evals/week5/benchmark_mailbox.py` | 0 | 编译通过 | 0.28s |
| `.venv/bin/python -m ruff check codeteam/agent_team tests/agent_team evals/week5/benchmark_mailbox.py` | 0 | All checks passed | 0.22s |
| `.venv/bin/python -m pytest tests/agent_team/test_mailbox.py -q` | 0 | 30 passed | 4.38s |
| `.venv/bin/python -m pytest tests/agent_team -q` | 0 | 149 passed | 4.56s |
| `.venv/bin/python -m pytest tests/task tests/planning tests/agent tests/session -q` | 0 | 202 passed | 23.34s |
| `.venv/bin/python -m pytest -q` | 0 | 1350 passed, 6 skipped | 100.75s |
| mailbox.py line/branch coverage | — | **NOT_RUN**（pytest-cov 未安装；按指令不安装依赖） | — |

skip 明细：6 条全部为 tests/sandbox Docker 集成（Docker CLI 不可用，Week3 起的能力性跳过，与 W5D4 无关）。

# 7. Coverage

NOT_RUN（工具不可用）。按 test_Agent.md 原则不将覆盖率解释为设计有效性；本轮以行为断言 + 故障注入诊断 + 全量回归为主要证据。

# 8. 独立诊断（/tmp/w5d4_mailbox_diagnostics.py，一次性脚本，未入仓库）

| ID | 诊断项 | 结果 | 关键数据 |
|---|---|---|---|
| D1 | 8 线程同时发送相同 message_id | **PASS** | 成功=1/8，DuplicateMessageError=7，队列=1，无线程泄漏 |
| D2 | 16 线程竞争最后 1 个容量 | **PASS** | queue_size=1（未超 capacity），MailboxFullError=15/15 |
| D3 | 4 层深嵌套 payload 原地突变 | **PASS** | 存储/返回/接收三侧突变全部隔离；events 无 payload 键 |
| D4 | monkeypatch uuid4 恒定值 → broadcast 重复 id | **DEFECT-CONFIRMED（P2）** | 3 条相同 message_id 分别入 3 个 inbox（queues=[1,1,1]）；后续同 id send 被拒；批内去重缺失 |
| D5 | broadcast 构造失败无部分写入 | **PASS** | blank task_id→ValidationError 与第 2 条消息构造抛 RuntimeError 两种情形下，inbox/seen/events 与基线完全一致 |
| D6 | 不可 model_dump_json 的 payload | **CONTRACT-GAP（P3）** | function/自定义对象：模型接受，仅在 model_dump_json 时抛 PydanticSerializationError；set 可序列化为数组；进程内 send/receive 不受影响（e2e 正常） |
| D7 | created_at NaN/inf/负值 | **CONTRACT-GAP（P3）** | NaN 接受且序列化为 null（roundtrip 静默变值）；±inf 验证通过但 dump 抛 ValidationError；负值接受且 roundtrip 保真 |
| D8 | seen-ids / events 生命周期增长 | **RISK（P2，含文档披露缺口）** | 5000 次 send+receive（inbox 恒空）：_seen_message_ids=5000、_events=10002、驻留堆≈5.4 MiB；DD/Failure 文档均未披露该增长（F-03 仅披露 inbox 无界风险） |
| D9 | TASK_COMPLETED/TASK_FAILED 不改变 Scheduler | **PASS** | claim 后消费两种消息，record 保持 CLAIMED + owner 不变，scheduler 事件增量为 0 |

诊断脚本首两轮因脚本自身收件人命名不一致（注册 `w1` 却访问 `worker-1`）产生 5 项假失败，修正后全部复跑，上表为修正后结果；D4/D9 在修正前后结论一致（不受脚本 bug 影响）。

# 9. Benchmark 审计与复现

## 9.1 方法

`evals/week5` 无 `__init__.py`（非包），故经 `importlib.util.spec_from_file_location` 从文件路径加载模块，将模块级 `OUTPUT_PATH` 改为 `/tmp/W5_MAILBOX_acceptance_2026-08-27.md` 后调用 `main()`。仓库内 `docs/benchmark/W5_MAILBOX.md` 未被覆盖（复现前后 sha256 不变核验：52ce21a6…）。

## 9.2 配置核对（全部 ✓）

- warmup=5、measured=30（模块常量 + 复现报告双确认）
- messages 100/1000/10000；producers 1/4/8；broadcast fanout 1/4/16/64
- setup 与热路径分离：`measure_ms_with_setup` 仅计时 operation，setup 单独报告（setup median ≈0.04ms vs send 4.8-498ms，分离真实有效）
- bounded thread join：JOIN_TIMEOUT_SECONDS=60 + live-thread 检查（未按时结束即 RuntimeError）
- provenance：Base HEAD / Commit SHA / dirty 状态 / OS / 两文件 SHA-256 / Python / seed / warmup / measured 齐备

## 9.3 原报告 provenance 判定

原报告基于父 HEAD `a45ff93` + dirty tree。实测当前 clean HEAD `1a9f524` 下两文件 SHA-256 与原报告记录**逐字节一致**（mailbox.py=5adc8125…、benchmark=52ce21a6…），即当时的 dirty 工作区就是本次验收提交的内容；叠加本次在 clean HEAD 的成功复现 → **"本地 mailbox 操作成本"范围内的证据充分**。

## 9.4 复现结果与趋势（同机同 Python，负载更轻）

| 指标 | 原报告 | 复现 | 趋势 |
|---|---:|---:|---|
| send 100/1000/10000 median ms | 7.8/77.9/890.0 | 4.8/45.9/498.1 | 线性扩展 ✓，量级一致 |
| receive 100/1000/10000 median ms | 3.6/33.0/311.9 | 2.2/22.1/220.3 | 线性扩展 ✓，receive 恒快于 send ✓ |
| send throughput median ops/s | 11.2k-12.8k | 20.1k-21.8k | 同数量级 |
| concurrent 10000: p=1 vs p=8 | 13249 vs 9330 | 20375 vs 15348 | 8 producers 竞争退化模式复现 ✓ |
| broadcast fanout 64 median ms | 3.996 | 2.948 | 随 fanout 线性增长 ✓ |

复现整体快约 1.4-1.9×（同机、复现时系统负载更低），趋势与相对关系全部复现，符合"趋势复现、不要求绝对数值一致"的验收口径。

## 9.5 诚实性核对

- approx backlog bytes 明示"serialized message size, not process RSS" ✓（且实测 D8 表明真实驻留还叠加 seen-ids/events，见 P2-2）
- concurrent p95 命名"p95 ops/s"语义诚实（吞吐分布的 95 分位）✓；**观察项 P3-5**：吞吐 p95 是乐观尾部，工程保守读法应取 p05，报告未说明方向差异（命名本身无误导）
- **raw samples 未保存**（仅 median/p95 聚合落盘）→ P3-4 证据缺口（test_Agent.md §55 建议Raw/Summary 分离）
- Deferred Metrics 三项（crash recovery / durable replay / exactly-once）如实标注 DEFERRED/NOT_RUN ✓

# 10. Ablation 审计

```text
状态: NOT_RUN / INSUFFICIENT_EVIDENCE（维持）
依据: day4.md §15 明确标记 PLANNED/NOT_RUN（"当前不运行 ablation，
      因为生产实现还不存在。本轮只规划。"）；
      DD-W5-04 无任何 ablation 声明；benchmark 报告无冒充数据。
判定: 三个规划中的 ablation（Mailbox vs Direct Call / Bounded vs Unbounded /
      Atomic Broadcast vs Loop send）均未执行。按规则不得把 unit test 或
      benchmark 冒充 ablation → INSUFFICIENT_EVIDENCE。
影响: 不否定 Mailbox 功能实现（正确性证据独立成立），
      但工程证据闭环缺少 Ablation 一环 → 闭环结论 PARTIAL。
```

# 11. Production Defects / Risks（按 P0-P3 排序）

## P2-1 缺陷: broadcast 批内 message_id 去重缺失（诊断 D4 稳定复现）

```text
Module:   codeteam/agent_team/mailbox.py broadcast()（213-232 行）
Scenario: uuid.uuid4() 在同一批次内返回相同值（monkeypatch 恒定值注入）
Expected: 批内重复 message_id 被拒绝或去重（DD Requirements: "Reject ... duplicate message IDs"）
Actual:   3 条相同 message_id 分别成功入队 3 个 inbox；仅对"历史已接受 id"检查，
          未对"本批次新生成 id"检查
Reproduction: /tmp/w5d4_mailbox_diagnostics.py diag_d4（patch uuid4 后 broadcast 3 recipients）
Reproducibility: 确定性复现（100%）
Impact:   违反全局 message_id 唯一性不变量。真实触发需要 uuid4 碰撞
          （单对概率约 2^-122）或 uuid 源被替换/劣化 → 实际风险极低；
          后续同 id 的 send 会被拒绝，错误不会无限扩散
Suspected Root Cause: 去重预检循环只查 _seen_message_ids（历史集合），
          而该集合在预检之后、append 循环之中才更新；批内构造期生成的
          重复 id 从未互查
Suggested Direction: 在消息构造期维护批内局部 id 集合并拒绝重复，
          或将 _seen_message_ids.add 前移进预检循环（check-and-add 原子化）
Severity: P2（不变量违反 + 故障注入可触发 + 修复廉价；现实触发概率可忽略）
```

## P2-2 设计风险 + 文档披露缺口: bounded inbox ≠ bounded memory（诊断 D8）

```text
Module:   codeteam/agent_team/mailbox.py _seen_message_ids / _events
Evidence: 5000 次 send+receive（inbox 恒为 0）后：
          _seen_message_ids=5000、_events=10002、tracemalloc 驻留≈5.4 MiB
Analysis: 去重集合与内部事件史随成功操作数线性增长且永不回收。
          "bounded capacity" 仅约束 inbox 深度，不约束进程内存。
          该保留是 F-W5-D4-02 语义（消费后仍拒绝重复 id）的必然代价，
          属于设计权衡而非实现 bug；但 DD-W5-04、W5_MAILBOX_FAILURE.md
          （F-03 仅讨论 inbox 无界）均未披露此增长 → 诚实性缺口
Suggested Direction: 在 DD/Failure 文档补充保留权衡说明；
          Day6 durable 设计时评估事件史上限或去重窗口策略
Severity: P2（长生命周期进程的累计内存风险 + 披露缺失）
```

## P3 清单

| ID | 类型 | 内容 |
|---|---|---|
| P3-1 | 契约缺口（D6） | payload 接受不可 JSON 序列化值（function/自定义对象），仅在 model_dump_json 时抛 PydanticSerializationError；教程仅"建议 JSON-like"未强制；进程内收发不受影响（e2e 已验证）。Day6 持久化边界落地前应补校验或在文档中将建议升级为契约 |
| P3-2 | 契约缺口（D7） | created_at 无约束：NaN 接受且序列化为 null（roundtrip 静默变值）；±inf 验证通过但 dump 抛 ValidationError；负值接受。影响未来 durable 序列化与 benchmark 的 backlog 字节数 |
| P3-3 | 测试缺口 | R13（消息不能改变 Scheduler 状态）在仓库中无回归测试，本轮证据仅来自一次性诊断 D9。建议入 tests/agent_team（本轮权限禁止新增） |
| P3-4 | 证据缺口 | benchmark 仅保存 median/p95 聚合，raw per-run samples 未落盘（test_Agent.md §55 Raw/Summary 分离建议） |
| P3-5 | 观察项 | concurrent throughput 的 "p95 ops/s" 为吞吐分布乐观尾部；工程保守读法宜用 p05。命名诚实无误导，建议报告补一句方向说明 |

# 12. Design Decision Verification

```text
Decision:     DD-W5-04 — In-Process Mailbox（deque+Lock）Instead of Direct Agent Calls
Hypothesis:   进程内同步 Mailbox 足以证明 Agent communication correctness，
              并与 Day3 同步 Scheduler 核心一致；明确不证明 durability/exactly-once/speedup
Evidence Collected:
  - 30 个 mailbox 单测 + 149 agent_team + 202 Day1-3/Week4 子集 + 1350 全量（0 失败）
  - 9 项独立诊断：7 项 PASS，边界（构造失败、深突变、线程竞争）行为正确
  - Benchmark 复现成功：趋势与相对关系全部复现，provenance 闭环（文件哈希一致）
  - 诚实边界：DD/benchmark/failure 三处声明一致，无 over-claim
Contrary Evidence:
  - D4：DD Requirements 中 "Reject duplicate message IDs" 在 broadcast 批内被违反（故障注入）
  - D8：DD 未披露 seen-ids/events 无界保留的内存权衡
  - Ablation NOT_RUN → "mailbox 优于 direct call" 的价值假设无实验支持
Evaluation:   PARTIALLY_SUPPORTED
Reason:       正确性与本地成本假设有充分可复现证据；但按 test_Agent.md §43，
              缺少 Ablation 支持 + 存在 1 条要求级反向证据 + 1 项关键权衡未披露，
              不足以授予 SUPPORTED。
```

# 13. Acceptance

| 验收项 | 结果 | Evidence |
|---|---|---|
| 1. AgentMessage Pydantic 模型与 LLM Message/AgentEvent 分离 | **PASS** | §4 R1 |
| 2. ID namespace 清晰 + 必填 ID 拒空 | **PASS** | §4 R2 |
| 3. Lead/Worker 注册 + 未知/重复 fail closed | **PASS** | §4 R3 |
| 4. 防御性副本 + 嵌套 payload 隔离 | **PASS** | §4 R4 + D3 |
| 5. 非阻塞 receive / None / destructive at-most-once | **PASS** | §4 R5 |
| 6. per-inbox FIFO（线性化顺序），无全局顺序 over-claim | **PASS** | §4 R6 |
| 7. 重复 message_id 拒绝（含已消费后），失败不改队列 | **PASS**（附 D4 警示） | §4 R7 + D1 |
| 8. bounded capacity fail closed，满后队列不变 | **PASS** | §4 R8 + D2 |
| 9. broadcast 独立 id / 共享 correlation / all-or-nothing | **PASS**（附 D4 警示） | §4 R9 + D5 |
| 10. 多线程无丢失无重复 / bounded join / 无 sleep | **PASS** | §4 R10 + D1/D2 + grep 审计 |
| 11. event 安全 metadata（无 payload/secret） | **PASS** | §4 R11 |
| 12. sink 锁外调用 / 重入 / 慢 / 异常隔离 | **PASS** | §4 R12 |
| 13. 消息不改变 Scheduler 状态 | **PASS**（诊断级证据，测试缺口 P3-3） | D9 |
| 14. API 导出完整 + Day1-Day3 与全量无回归 | **PASS** | §4 R14 + §6 |

# 14. Regression

```text
Full suite: 1350 passed / 6 skipped —— 与 Week5 前序基线一致（6 skip 为 Docker 能力性跳过）
mailbox: 30 passed；agent_team: 149 passed；task/planning/agent/session 子集: 202 passed
ruff: All checks passed（0 error）；py_compile: 0 error
Benchmark/Ablation Regression: benchmark 趋势复现一致；ablation 无历史数据（首次规划态）
```

# 15. Deferred 与 Non-claims（明确不计入 Day4 失败）

```text
Deferred（DD §Alternatives/§Evidence Still Missing、day4.md §6、benchmark §Deferred 三处一致）:
heartbeat、worker crash recovery、ack/nack、message retry/redelivery、durable replay、
SQLite/durable queue、cross-process delivery、distributed pub-sub、exactly-once、
Worker execution loop、Scheduler bypass、端到端 Multi-Agent 加速

Non-claims（如实声明，未发现 over-claim）:
- 不证明 Multi-Agent 端到端加速 / crash recovery / exactly-once
- 多 producer 不承诺墙钟全局顺序（F-W5-D4-09）
- approx backlog bytes 非真实 RSS
- F-W5-D4-08 诚实记录 destructive receive 崩溃丢失为已知限制
```

# 16. Artifacts

```text
本报告:       test_log/2026-08-27_week5_day4_mailbox_acceptance_log.md（唯一仓库写入）
诊断脚本:     /tmp/w5d4_mailbox_diagnostics.py（一次性，未入仓库）
benchmark 复现: /tmp/W5_MAILBOX_acceptance_2026-08-27.md（OUTPUT_PATH 重定向，未覆盖仓库报告）
被测工件（未改动）:
  codeteam/agent_team/mailbox.py、codeteam/agent_team/__init__.py、codeteam/events.py
  tests/agent_team/test_mailbox.py、evals/week5/benchmark_mailbox.py
  docs/design_decisions/DD-W5-04.md、docs/benchmark/W5_MAILBOX.md、
  docs/failure_cases/W5_MAILBOX_FAILURE.md、learning-plan/week5/{week5_plan,day4}.md
```

# 17. Interview Evidence（全部实测）

```text
- 8 线程同 id 竞争：恰 1 成功 + 队列恰 1 条（去重线性化点正确）
- 16 线程抢 1 容量：队列从未超限，15 次 fail-closed
- 4 层深嵌套突变三侧隔离：防御性副本不是口头承诺
- broadcast 构造中途失败：inbox/seen/events 与基线逐字段一致（all-or-nothing 真）
- 故障注入发现批内去重缺失：能区分"文档声明的不变量"与"实现实际保证"
- inbox 恒空下 5000 次操作仍驻留 5.4 MiB：能指出 bounded inbox ≠ bounded memory
- TASK_COMPLETED 消息后 Scheduler record 零变化：通信层与状态机边界清晰
- benchmark 同机复现：send/receive 线性扩展、8-producer 竞争退化模式可重现
```

# 18. Final Conclusion

```text
Test Development:        N/A（验收模式，未在 tests/ 新增；诊断仅在 /tmp）
Correctness:             PASS（14/14 验收项；1 个 P2 缺陷仅故障注入可触发）
Safety:                  PASS（fail-closed 路由/容量/去重；sink 隔离；不绕过 Scheduler ownership）
Observability:           PASS（安全 metadata 事件 + delivery_failed 隔离；D8 保留策略待披露）
Benchmark:               COMPLETE（复现成功 + provenance 闭环；raw samples 未存 → P3-4）
Ablation:                NOT_RUN / INSUFFICIENT_EVIDENCE（如实维持，无冒充）
Failure Cases:           COMPLETE（9 案例与实测行为一致；D8 披露缺口待补）
Coverage:                NOT_RUN（pytest-cov 不可用）

Day4 Mailbox 功能结论:   PASS
Day4 工程证据闭环:       PARTIAL（缺 Ablation；coverage/raw samples/内存披露三项缺口）
DD-W5-04:                PARTIALLY_SUPPORTED

缺陷计数: P0=0  P1=0  P2=2（D4 批内去重缺失、D8 内存增长+披露缺口）
          P3=5（payload 契约、created_at 契约、R13 测试缺口、raw samples、p95 方向观察）
```

---

## 附：Git 状态记录

```text
初始: HEAD=1a9f52490a60025f2cb059a772ae4c504c90d642（与预期一致），status=clean，branch=week5
最终: 同 HEAD，工作区除本日志外无任何新增/修改（详见最终核查输出）
```
