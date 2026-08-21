# W4 Not Doing List

- **日期**: 2026-08-21
- **模块**: Week4 Single-Agent Runtime
- **状态**: Accepted（范围声明）
- **Evidence status**: PROPOSED

---

## Purpose

这份文档记录 Week4 MVP 明确不做的内容。它不是遗忘清单，而是为了让代码注释、恢复策略和验收报告有可追溯的范围边界。

## REREAD Recovery

### 当前 MVP 语义

`REREAD_AND_REGENERATE` 在 Week4 MVP 中表示：调用注入的 rereader 回调，回调成功即视为上下文已刷新，然后重试同一操作。

### 明确不做

MVP 不实现完整的"重读文件 + 重新检索 + 重新调用模型生成修复"链路。

### 理由

完整 REREAD 需要把 file retrieval、context rebuild、planner/repair loop 与当前 operation 重新绑定。这属于 Day6+ CLI / full runtime 集成范围。Day5 只需要证明恢复动作有真实 executor，不再是零发射方。

## RETRIEVE_MORE_CONTEXT Recovery

### 当前 MVP 语义

`RETRIEVE_MORE_CONTEXT` 仍保持终态失败，不在 Day5 orchestrator 中执行。

### 明确不做

MVP 不在 `_execute_with_recovery()` 中临时扩展检索范围，也不自动重跑 ranking / repo map / context builder。

### 理由

检索恢复属于 Context Engineering 的更高层编排，需要明确：

- 原 query 是否改变；
- 是否扩大 top_k；
- 是否允许引入新文件；
- 新上下文如何与 plan/checkpoint/session 对齐。

这些规则没有在 Day5 建完整，因此 fail closed 比静默猜测更安全。

## REPAIR / REPLAN / ASK_USER Recovery

### 当前 MVP 语义

这些 recovery action 在 Day5 orchestrator 中仍走 `recovery_executor_not_wired:*` 终态。

### 明确不做

- 不在 Day5 自动 replan。
- 不在 Day5 自动发起人工询问流程。
- 不在 Day5 把 repair loop 嵌套到所有失败阶段。

### 理由

这些动作会改变任务控制流，需要 CLI/UI、Session Persistence、Approval/Event Log 一起接线。Day5 的目标是补 COMPACT / REREAD 的最小执行器，而不是扩展完整恢复编排。

## Background Async Compaction

### 当前 MVP 语义

Day5 选择 **Turn Boundary 同步压缩**。

### 明确不做

MVP 不做后台异步压缩、不做并行 summarizer worker、不做边跑模型边整理旧上下文。

### 理由

后台异步压缩需要处理并发写、summary 版本竞争、turn 内 selection 不可变、Session state_version 对齐等问题。Week4 MVP 优先选择同步边界，保证行为可测试、可审计、可回放。

## Provider-native Compaction

### 当前 MVP 语义

Compaction 使用项目内结构化 `ContextSummary` / `CompactionResult`。

### 明确不做

MVP 不直接依赖某个 provider 的 native compaction 或 memory API。

### 理由

本项目目标之一是证明 provider-neutral runtime。Provider-native 方案可以作为未来 backend，但不能成为 safety/constraints/plan/checkpoint 的权威来源。

## SessionService Full Model Override

### 当前 MVP 语义

Session durable state 存 provider_id / model_id；ModelSwitchService 支持切换事务。

### 明确不做

Day5 不把 `SessionService.resume()` 完整接入 provider registry、override selection 和 ModelSwitchService。

### 理由

该链路属于 CLI resume 集成范围，需要用户输入、配置加载、credential 检查、事件归因和 runtime factory 一起完成。

## Evidence

- **状态**: PROPOSED
- **当前证据**:
  - `codeteam/agent/orchestrator.py` 对未接线 recovery action fail closed。
  - `tests/agent/test_recovery_executors.py` 覆盖 COMPACT / REREAD MVP 语义。
- **未完成证据**:
  - Day6+ 完整 CLI / Session / Context rebuild 链路尚未验收。
