# Week5 Day7 Team Runtime 真实 LLM 闭环修复记录

## 1. 背景与目标

Week5 Day7 的目标不是再写一套 Coding Agent，而是让 Team 控制面复用已经存在的
`CodingAgentRuntime`：Lead 产生 DAG，Scheduler 分配节点，Worker 执行单 Agent 闭环，
coordinator 汇总可信 Git 证据，最后由独立 Grader 判断正确性。

预期链路是：

```text
Team request
  -> deterministic one-node smoke plan
  -> Worker claim + budget + fence
  -> CodingAgentRuntime
  -> inspect/read/search
  -> Safe Patch Lane + checkpoint
  -> visible task verification + regression
  -> git diff + submit_result
  -> coordinator-owned workspace evidence
  -> hidden Grader
```

Day7 的单元测试和 Coder 自检最初全部通过，但真实 B01 smoke 连续失败。这段经历说明：
局部组件正确，不等于跨边界协议能够闭环；真实模型的行为方差还会放大控制面的设计缺陷。

## 2. 第一阶段：独立验收先暴露信任边界

独立 tester 在真实 smoke 之前确认了三类问题：

| 等级 | 问题 | 风险 |
| --- | --- | --- |
| P0 | Worker 异常中的 credential marker 原样进入 Team artifact | secret 持久化 |
| P1 | common result 信任 Worker 自报的 diff、changed files 和 verification | 空 workspace 可伪造成功 |
| P2 | smoke 异常后 manifest 停留在 `STARTED` | 实验状态不可审计 |

第一轮修复引入统一递归脱敏、coordinator-owned Git evidence 和原子 manifest 终态转换。
Worker 结果从此只作为 `worker_reported_*` claim，外部公共结果不再把 Worker 自报当事实。

这轮修复是必要的，但它主要保证“失败不会泄密、不会误报、可追溯”，还没有解决“为什么
真实 Worker 无法完成任务”。

## 3. 第二阶段：第一次 B01 揭示跨模块 ID 契约断裂

第一次真实运行证据位于：

```text
evals/week5/agent_runs/day7-b01-team-smoke/
```

模型已经定位到 `src/auth/api.py`，并两次发出合理的 replacement edit。但两个
`apply_patch` 都失败：

```text
Checkpoint creation failed closed:
task_id contains unsupported characters:
'B01:node-worker-implementation:attempt-1'
```

根因不是模型不会改代码，而是 Team 层用冒号拼接 child task id；Checkpoint 和
Worktree 层只接受 `[A-Za-z0-9._-]+`。两边各自的局部测试都通过，却没有一条测试把
`WorkerExecutor` 生成的 ID 真正送入 Patch Lane。

本轮修复把 child id 改为：

```text
sanitized(parent-node-attempt) + sha256(raw identity)[0:12]
```

可读前缀便于诊断，hash 保证原始 parent/node 中不同的特殊字符不会规范化成同一 ID；
attempt 进入 identity，因此重试不会复用 checkpoint ownership。

## 4. 第三阶段：第二次 B01 揭示上下文和停滞控制缺陷

第二次真实运行证据位于：

```text
evals/week5/agent_runs/day7-b01-team-smoke-2/
```

这次 manifest 正确终态化，但 Worker 在 7 个 step 内声明 34 个工具调用，达到节点上限
32；29 个调用发生在首次编辑之前，最终 `patch_attempts=0`、`workspace_version=0`。
Team 起初只报告笼统的 `worker_runtime_failure`。

扩大排查到 Runtime、Provider 请求组装、Context compaction、AgentLoop cache 和 Team
budget 后，发现三个相互叠加的问题。

### 4.1 Native tool schema 被发送两次

完整工具 schema 同时出现在 system message 和 `ModelRequest.tools`。B01 的第一轮输入在
`context_budget=4096` 下因此立即触发 compaction，初始检索得到的完整源码在模型第一次
请求前就被移除。模型只能再次读取已经检索过的文件。

修复后，native-tool 模式：

```text
system message -> compact tool catalog + protocol examples
ModelRequest.tools -> exact JSON schemas, only source of native schemas
```

非 native 模式仍把完整 schema 放进文本协议，并且不再把不会发送的 native schemas
计入 `ModelRequest.tools`。用第二次 B01 的实际首轮消息重算，输入约从超预算降为
`3898/4096` tokens，初始源码可以保留到第一次模型调用。

### 4.2 初始上下文缓存豁免跨轮永久生效

Runtime 原本允许读取初始上下文文件时不计入 cached no-progress。这对同一轮中的重复引用
有意义，但豁免没有轮次边界。模型跨轮反复读取同一批文件时，每次 cache hit 都被视为
fresh observation，AgentLoop 无法触发停滞保护，最终耗尽工具预算。

修复后不再提供永久豁免：同一 batch 中第一次真实读取仍保证后续安全调用不被提前截断；
跨轮全部命中缓存时，连续两个 stalled turns 会以
`NO_PROGRESS/CACHED_BATCH_STALL` 停止。成功 patch 推进 workspace version 后，新版本仍可
重新读取文件。

### 4.3 Team 丢失 Worker 的根失败分类

节点实际失败是 `max_tool_calls`，Team common result 却折叠为
`worker_runtime_failure`。这不改变任务成败，却拖慢定位。

修复后 Team 从 terminal node results 归一化根因：step/tool cap 映射为
`budget_exhausted`，Provider、environment、protocol 分别保留对应类别，错误摘要包含安全的
`node_id=category`，不包含未经脱敏的 Worker 输出。

## 5. 第四阶段：脱敏安全与证据保真发生冲突

第一轮 P0 修复使用了过宽文本正则，产生新的证据质量问题：

```python
token = request.get("refresh_token", "")
```

在 artifact 中会变成不完整代码；`token-specific errors` 也会被误删。虽然脱敏发生在
Worker 执行结束后的持久化边界，没有改变当次模型决策，但它破坏了 forensic evidence，
后续无法可靠判断模型当时看到了什么。

最终把策略拆成两层：

1. 普通结构化证据采用高精度规则，只处理敏感 key、Bearer、真实 key/value 形态和已知
   secret pattern，保留普通源码标识符与领域术语。
2. 未知异常采用 fail-closed 规则。只要异常文本出现 credential marker 且无法高精度定位
   value，持久化内容降级为 `ExceptionType: <redacted>`，同时保留稳定分类和安全摘要 hash。

这避免了在“泄密”和“证据失真”之间选一个，而是按信任边界使用不同强度。

## 6. 回归测试如何锁住完整链路

本轮增加或强化了以下证据：

- 恶意 parent/node id 生成稳定、合法、不同 attempt 不冲突的 child task id。
- native-tool 首请求不重复完整 schema，4096-token 场景仍保留初始完整文件。
- 跨轮重复读取初始上下文会触发 cached stall；同一轮多调用仍完整处理。
- 源码中的 `token` 变量和 token 领域术语不被误删，真实 secret 继续脱敏。
- Team 将 child `max_tool_calls` 保留为 `budget_exhausted` 根因。
- 离线 B01 走同一生产链完成：

```text
TeamCodingRuntime
  -> WorkerExecutor
  -> CodingAgentRuntime
  -> exact replacement
  -> SafeExecutionService Patch Lane + CheckpointManager
  -> task verification
  -> regression
  -> git_diff
  -> submit_result
  -> coordinator trusted diff
```

该测试脚本化的是 ModelTurn 和 Docker 命令结果，不替换 Runtime、Patch、Checkpoint、Git
evidence 或 Team orchestration，因此可以稳定复现本次跨模块缺陷，同时不冒充真实 LLM
成绩。

## 7. 第四次定位：第三次 B01 暴露“执行历史不等于请求可见性”

第三次真实运行证据位于：

```text
evals/week5/agent_runs/day7-b01-team-smoke-3/
```

前两轮修复都实际生效：Docker/verification preflight 通过，native tools 正常传输，Provider
没有被阻断，17 个声明调用全部获得结果，security 和 broad regression 通过。失败轨迹为：

```text
step 1: exceptions + tokens + repository + list
step 2: api + service + public test + docs
step 3: 重复 step 1 的源码组
step 4: 重复 step 2 的源码组
stop: CACHED_BATCH_STALL
```

最终 `patch_attempts=0`、`workspace_version=0`、task verification/hidden acceptance 均失败。
这次不再是 ID、Provider 或工具预算问题，而是更深的上下文控制缺陷。

Structured compaction 当时保留了“读过哪些路径”，但没有保留这些读取的源码观察；预算只够
最近一个原子 native tool group。模型看到 A 组时缺 B 组，读取 B 组后下一轮又只剩 B 组，
因此形成 A/B 往返。与此同时 Runtime cache 知道两组都执行过，第二次往返便按 duplicate
停机。换句话说，模型的知识边界和 Runtime 的停滞判断使用了两个不同的事实源。

修复没有通过加大 4096 context 或 20/40 budget 掩盖问题，而是：

1. Structured summary 加入有界 working set，保留 `read_file/search_code` 的规范化参数、
   精确观察、hash 和截断标志；最多 8 项、单项 1600 字符、总计 5200 字符。
2. 每次 Provider 请求前构建 request-relative visibility set。缓存内容若已在当前请求可见，
   才算 duplicate；若被 compaction 裁掉，则作为 `memory_restoration` 返回而不推进 stall。
3. 第一个完整可见重复 batch 先给模型一次明确 advisory，连续第二个才停止。
4. 单轮探索限制为四个 list/read/search，超出的 native calls 获得相关联的拒绝结果。
5. 新增 `ModelRequestEvidence`，在不复制完整 prompt 的前提下记录每轮实际发送规模、token
   估算、compaction、可见文件/观察和保留的 provider call ids。

确定性回归复现两轮八个探索调用。在 4096 预算下，第三轮必须同时看到 API、service、
exceptions 和 tokens 的内容，然后经同一生产链完成 patch、两类验证、diff 和 submit。

## 8. 当前结论与证据边界

截至本轮代码修复：

- 已证明 B01 的生产执行链在确定性模型输入下可以完成闭环。
- 已证明第一次真实 smoke 的 patch 必然失败根因已修复。
- 已证明第二次真实 smoke 的首轮上下文挤出和无限 cache 豁免已修复。
- 已证明第三次真实 smoke 的工作集丢失与 request/cache 可见性错位有确定性修复。
- 真实 Provider 的下一次 B01 尚未运行，不能声称 Day7 真实 LLM smoke 已通过。
- 11-task benchmark、Single-vs-Team 和 sequential/parallel ablation 继续为 `NOT_RUN`。
- 一个 one-node Team smoke 只验证 Team wiring，不证明多 Agent 比单 Agent 更好。

下一道 gate 是由学习者在同一 provider/model/budget 下重新运行 B01。只有 Runtime
verification、regression、hidden acceptance 和 `success=true` 同时满足，才进入独立 tester
复验；之后才适合运行多次 benchmark 和 ablation。

## 9. 面试叙述版本

可以把这段经历概括为：

> 我先用独立验收修复了多 Agent 的证据信任边界，保证 Worker 不能伪造 diff 或泄露凭证。
> 真实 B01 随后仍失败。第一次失败不是模型能力问题，而是 Team child id 与 Checkpoint
> 的字符契约不一致；第二次失败则是 native tool schema 重复占用上下文，使初始源码在
> 第一轮前被压缩，再叠加跨轮 cache 豁免，模型一直重复读文件直到工具预算耗尽。我没有
> 通过增加预算掩盖问题，而是统一 ID 契约、去掉 schema 双重表示、把 no-progress 恢复为
> 跨轮控制，并拆分普通证据与异常的脱敏强度。最后用一条离线 B01 生产链回归锁住
> Team、单 Agent、Patch、Checkpoint、验证和 Git evidence，再把真实 LLM 重跑保留为独立
> 的随机性 gate。

这条故事的重点不是“修了几个 bug”，而是展示如何区分模型失败、协议失败、安全边界、
可观测性缺陷和测试盲区，并用分层证据逐步缩小不确定性。

第三次 smoke 又让我补了一层更关键的认识：Runtime cache 里有内容，不代表模型当前看得见。
压缩只保留路径时，模型在两组调用关系文件之间来回读取，而 cache guard 反过来把这种恢复
行为判为重复。我把 structured summary 改成 bounded working set，并让重复判断基于当前
Provider request 的可见集合。这个修复没有取消 no-progress，而是让它使用与模型相同的
事实边界；同时新增每轮 request metadata，使下一次真实失败可以直接回答“当轮到底给模型
看了什么、压缩掉多少、用了多少预算”。

## 10. 第五阶段：working set 有代码，但控制信息仍被压缩丢失

后续真实证据包括：

```text
evals/week5/agent_runs/day7-b01-team-smoke-4/
evals/week5/agent_runs/day7-b01-team-smoke-codex-20260903_131054/
```

两次运行都证明 working set 修复已生效：第三轮后 API、service、exceptions、tokens 和公开
测试同时可见，Provider、Docker 与 Grader 均无环境故障。但模型明确说出 bug 和下一步修改
后，第四、五轮又重复读取相同文件，最终为 `no_progress/cached_batch_stall`，仍然没有 Patch。

根因是 structured summary 只保留了源码内容：

- 最近 native assistant 的诊断意图随原子组一起被裁掉；
- cached wrapper 被解包为 `previous_content` 时，`duplicate/guidance` 元数据被删除；
- `no_progress_advisory` 参与 compaction，却没有进入不可丢的 summary 基座；
- 本地 token 估算比 Provider 报告低约 6% 至 10%，4096 预算没有真正的控制面余量。

修复后 summary 新增 `latest_agent_intent`、`control_state` 和每项观察的
`observation_state`。重复读取仍返回原始源码，但同时明确标记 duplicate、workspace version
和下一步 guidance。Provider-neutral token estimator 使用 1.15 保守系数与固定 framing
开销，compaction 与请求边界共用同一估算函数。

## 11. 第六阶段：Patch 成功后，旧意图和验证状态成为新问题

第一轮修复后的真实运行：

```text
evals/week5/agent_runs/day7-b01-team-smoke-control-fix-20260903_135722/
```

首次出现真实进展：`src/auth/api.py` 修改成功，task verification、regression 和 hidden
acceptance 在最终 workspace 全部通过。但模型下一轮仍看到“let me fix it”和修改前 API
快照，又提交了第二个 Patch，之后重复失败 Patch 被 destructive-repeat guard 拒绝。Agent
状态失败，但 Grader 证明源码已经正确。

这说明 compaction 不仅要记忆，还要处理记忆失效。修复把 workspace state 提升为 summary
中的控制权威：

```text
workspace_change.status = patch_applied
workspace_change.workspace_version = 1
last_patch_attempt.status = applied | failed
next_required_action = run_task_verification | ...
```

一旦 workspace version 前进，旧的 pre-edit intent 不再保留为当前意图；变更文件的旧快照
被明确标记可能过期。模型被要求先验证当前 workspace，而不是重放旧 Patch。

第二轮修复后的真实运行：

```text
evals/week5/agent_runs/day7-b01-team-smoke-post-patch-fix-20260903_140118/
```

模型做到单次 Patch，并通过 task verification，但连续重复同一条公开测试。根因是
`RuntimeEvidence.tests_passed` 正确要求 task 与 regression 全部通过，而 summary 只给出笼统
的 `run_task_verification`。于是内部 Gate 知道缺的是 regression，模型却不知道。

修复将验证进度拆成 task、regression 和其他 required commands，分别记录 passed 与 missing
argv。`next_required_action` 在每组完成后单调推进：

```text
run_task_verification
  -> run_regression_verification
  -> inspect_git_diff
  -> submit_result
```

Team common result 同时保留单一 Worker 的具体 `failure_category/failure_origin`；Team artifact
仍保留较高层的 orchestration taxonomy，兼顾聚合统计和根因定位。

## 12. 第七阶段：可信 Gate 已完成，不应被纯协议收尾否决

验证状态拆分后的真实运行：

```text
evals/week5/agent_runs/day7-b01-team-smoke-verification-state-fix-20260903_140446/
```

这次 Runtime 已经得到真实 diff、task verification、regression 和 git diff，
`completion_ready=true`。模型仍重复请求已通过测试，没有调用 `submit_result`，最终为
`completion_guidance_ignored`。Hidden Grader 再次全部通过。

这里暴露的是完成权威设计问题：`submit_result` 是模型表达意图的协议动作，不应凌驾于
Runtime 已建立的 Git、验证和安全事实。最终策略仍要求模型通过 `git_diff` 看过最终差异；
completion-ready 后仍允许 `read_file/search_code/apply_patch` 主动重开任务。但若模型只请求
重复测试、status 或 diff，Runtime 跳过该可选动作并以可信 CompletionGate 结算，完成模式为
`runtime_completion_gate_settlement`。

它不是“测试通过就自动成功”：没有真实 diff、当前 workspace version 的全部验证、最终 diff
检查或安全边界时，Gate 仍不会 ready；任何新 Patch 也会使旧验证与 diff 证据失效。

## 13. 最终真实结果

最终真实运行位于：

```text
evals/week5/agent_runs/day7-b01-team-smoke-completion-settlement-20260903_141033/
```

结果：

```text
success=true
actor_status=completed
changed_files=[src/auth/api.py]
patch_attempts=1
task_verification_passed=true
regression_passed=true
acceptance_passed=true
security_passed=true
completion_mode=runtime_completion_gate_settlement
```

该样本证明 one-node Team 通过真实 Provider、真实 Docker、生产 Patch Lane、公开验证和独立
hidden Grader 完成了 B01 闭环。它仍只是一个 dev smoke，不代表 11-task 稳定率，也不证明
Team 优于 Single；Benchmark/Ablation 仍需多次独立运行后报告。

面试时可以用一句话概括这一段：

> 我发现 Agent 的失败不只来自模型能力，还来自 Runtime 给模型展示的控制状态。修复过程从
> “保留代码”推进到“保留意图和重复判定”，再到“让 Patch 后的状态失效旧记忆”“拆分可见
> 验证阶段”，最后明确 CompletionGate 而非模型礼仪动作才是成功权威；每一步都有真实失败
> 样本和确定性回归，最终真实 B01 才从零 Patch 变成完整通过。
