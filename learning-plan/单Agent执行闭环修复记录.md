# CodeTeam 单 Agent 执行闭环修复记录

> 文档状态：持续维护  
> 首次建立：2026-08-27  
> 当前分支：`week4`  
> 当前记录终点：第六刀 Batch-aware Stall Detection 已离线实现；等待用户运行修复后 stability campaign
> 维护范围：从第一次真实 15-task benchmark 开始，持续记录单 Agent 生产闭环的故障、修复、实验和架构演进

## 1. 文档目的

这不是一份普通 changelog，也不是只记录最终正确架构的设计文档。

它要保留 CodeTeam 单 Agent 从“可以调用 LLM”到“能够可靠完成代码任务”的完整工程过程：

```text
问题如何被真实实验暴露
→ 当时如何理解问题
→ 为什么选择某种修复
→ 修复解决了什么
→ 下一次实验又推翻了什么假设
→ 最终如何重新划分架构边界
```

这条经历最终用于面试讲述。重点不是证明开发过程没有犯错，而是证明能够：

- 用真实证据区分模型能力、基础设施故障和评测错误；
- 在失败结果中找到下一层系统边界；
- 避免用 Grader、mock 或定向补丁掩盖生产 Runtime 的缺陷；
- 通过可复现 benchmark 驱动架构演进；
- 清楚说明哪些方案有效、哪些只是把问题推迟到下一层。

## 2. 故事主线

整个修复过程可以概括为：

```text
评测可信度
→ Provider 稳定性
→ 数据集可复现性
→ 产品与评测路径一致
→ 模型动作协议
→ 验证与完成闭环
→ Docker 执行拓扑
→ Provider-specific adapter + provider-neutral core
```

一句话版本：

> 我没有把第一次 benchmark 的低分直接归因于模型，而是逐层剥离 Provider 抖动、patch 格式、评测污染、执行路径分叉、协议不兼容、验证命名空间和 Docker 拓扑问题，最后发现最根本的缺陷是模型适配器只返回 raw text，导致 provider-neutral 被错误实现成了统一文本协议。

## 3. 维护规则

后续每次修改这条主线时，必须更新本文档，并至少记录：

1. 实验或测试的准确路径、命令和时间。
2. 修改前可复现的问题和关键指标。
3. 当时采用的根因假设。
4. 修改的代码边界和设计理由。
5. 修改后的测试与真实实验结果。
6. 新结果是否证明或推翻了原假设。
7. 新暴露的问题、严重等级和下一步。
8. 对应 Git commit；尚未提交时标记为 `UNCOMMITTED`。

记录时必须区分三类陈述：

- **事实**：日志、Git、测试或 artifact 可以直接证明。
- **推断**：根据证据得出的最可能解释，但还缺少关键观测字段。
- **决策**：在多个可行方案之间做出的工程选择。

不得把后续才发现的根因改写成当时已经知道，也不得删除失败实验。

---

## 4. 阶段一：第一次真实 15-task benchmark

### 4.1 初始目标

Week4 收尾时，CodeTeam 已具备 Agent Loop、Context、Patch、Repair、Session、CommandPolicy、Docker Sandbox 和 CLI 等模块。第一次真实 benchmark 的目标是验证：

```text
真实 LLM
→ 理解任务
→ 生成代码修改
→ 应用 patch
→ 通过 regression 和 hidden acceptance
```

运行目录：

```text
evals/week4/agent_runs/real_llm_baseline_20260823_181214
```

### 4.2 实验事实

首次 15 题执行摘要：

| 指标 | 结果 |
|---|---:|
| task_count | 15 |
| success_count | 2 |
| provider_blocked_count | 8 |
| acceptance_passed_count | 4 |
| regression_passed_count | 14 |
| security_passed_count | 15 |

主要失败形态：

- 8 题因 `SSL: UNEXPECTED_EOF_WHILE_READING` 阻断；
- 多题由模型直接手写 unified diff，出现 corrupt patch、hunk context 不匹配；
- `changed_files` 包含 `__pycache__`、`.pytest_cache` 等运行副作用；
- patch apply 失败后的 repair 缺少具体 `git apply` 反馈；
- hidden acceptance 通过并不一定能证明 Agent 修好了问题。

### 4.3 当时判断

第一次结果不能被解释为“模型只有 2/15 的修复能力”。Provider 抖动和 harness 噪声已经淹没 Agent 能力，直接做 ablation 没有意义。

### 4.4 修复方法

对应提交：

```text
3956afc
```

主要修改：

- Provider 增加 retry/backoff；
- 区分 429、5xx、timeout、SSL EOF、DNS、auth 和 invalid request；
- 保存每次 Provider 请求失败原因；
- 支持结构化 file edits，由本地生成 Git patch；
- 保存 raw model output、extracted patch 和 `git apply` stdout/stderr；
- 将 apply 失败原因反馈给 repair；
- pristine baseline 先运行 hidden acceptance；
- Grader 禁止 pycache 写入并过滤运行产物；
- `changed_files` 改为只反映真实 Git 修改。

### 4.5 方法解决了什么

Provider failure 不再直接终止整题；patch 失败开始具有可诊断证据；评测副作用不再被误计为 Agent 代码修改。

### 4.6 接着出现的新问题

第二次 15-task 运行中 Provider 阻断降为 0，但出现了更严重的 benchmark correctness 问题：部分题目在 Agent 修改前已经通过 hidden acceptance。

这说明第一次实验首先测到的是基础设施，而不是 Agent；基础设施稳定后，才有机会发现数据集本身不可信。

---

## 5. 阶段二：评测集本身不可信

### 5.1 实验事实

运行目录：

```text
evals/week4/agent_runs/real_llm_baseline_20260824_202744
```

执行摘要：

| 指标 | 结果 |
|---|---:|
| task_count | 15 |
| success_count | 4 |
| provider_blocked_count | 0 |
| acceptance_passed_count | 9 |
| regression_passed_count | 10 |
| security_passed_count | 15 |
| pristine_acceptance_passed_count | 4 |

暴露的问题：

- B01、B02、B04、M01 等任务的 hidden acceptance 在 pristine 状态已经通过；
- F02、M01、M02、M03 测试的是 CodeTeam 根仓库，而其他题测试 `medium_repo`；
- 各题 base commit 和 fixture 语义不统一；
- 有些题所描述的问题在指定 commit 中已经修好；
- Actor 有时修改测试而非生产代码；
- workspaces 与 artifacts 混杂，存在路径污染风险。

### 5.2 根因

benchmark 没有把以下四个事实固定为不可变输入：

```text
repository fixture
base commit
fault seed
oracle version
```

仅保存任务文本和 hidden test，无法保证每次运行面对的是同一个故障状态。

### 5.3 修复方法

对应提交：

```text
f6d7bb7
```

主要修改：

- 删除针对 CodeTeam 根仓库的 F02、M01、M02、M03；
- 剩余 11 题全部使用 `tests/fixtures/medium_repo`；
- 统一 base commit：`3956afc05d6c1ad2f3efaac9a510133436c0f700`；
- 为需要故障注入的题增加 hash-pinned setup patch；
- 为 11 题增加可见 public task test；
- public 和 hidden oracle 都要求 pristine baseline 失败；
- base commit 无法归档时 fail-closed；
- manifest 保存 fixture、commit、seed、hash 和 oracle review status；
- null baseline 保持 `0/11`。

### 5.4 方法解决了什么

每道题开始前都能证明：

```text
问题真实存在
public test 能暴露问题
hidden acceptance 能暴露问题
Agent 没有修改时不能获得成功
```

### 5.5 接着出现的新问题

benchmark 数据可信后，发现评测和产品仍然使用不同执行路径：

- `agent-eval` 使用独立 `PatchActor`；
- `codeteam run` 使用另一套生产编排；
- PatchActor 本质仍是一次检索加一次 patch generation；
- 评测结果无法证明用户实际使用的 `codeteam run` 具备同样能力。

这时问题从“评测数据不可信”升级为“评测对象不是真正产品”。

---

## 6. 阶段三：统一产品 Runtime 与 Eval Runtime

### 6.1 设计问题

旧流程大致是：

```text
task
→ 一次 context retrieval
→ 一次 LLM patch generation
→ git apply
→ grader
```

它不能让模型主动：

- 打开更多文件；
- 搜索符号和调用关系；
- 查看修改后的文件；
- 运行针对性测试；
- 查看 `git status` 和 `git diff`；
- 根据测试结果做局部修复；
- 在预算和安全策略内决定下一步。

### 6.2 修复方法

对应提交：

```text
59021f7
```

实现统一 `CodingAgentRuntime`：

```text
codeteam run ─────┐
                  ├─> CodingAgentRuntime
agent-eval ───────┘
```

第一版工具集：

```text
list_files
read_file
search_code
apply_patch
run_tests
git_status
git_diff
```

同时建立以下边界：

- EvalRunner 只准备 fixture、seed、worktree 和批量调度；
- Runtime 负责检索、模型决策、工具调用、修改和可见验证；
- hidden acceptance 只由独立 Grader 在 Runtime 停止后运行；
- `changed_files` 和 diff 以最终 Git 状态为准；
- `completed` 必须具有真实 diff、可见验证和最终 diff 检查。

### 6.3 方法解决了什么

从这一阶段开始，benchmark 测试的是和产品相同的 Agent 执行路径。后续暴露出的 Runtime 缺陷都同时属于产品缺陷，而不是 eval-only actor 的问题。

### 6.4 接着出现的新问题

统一 Runtime 后第一次 11-task baseline：

```text
evals/week4/agent_runs/runtime_baseline_20260825_215834
```

结果为 `0/11`。11 题几乎全部在第一轮停止：

```text
steps=1
tool_calls=0
patch_attempts=0
Model output was not valid JSON
```

模型实际返回的是 DeepSeek DSML 和 Markdown fenced JSON。HTTP API 连通，但 Agent action protocol 没有连通。

---

## 7. 阶段四：Provider Dialect Firewall

### 7.1 根因

“OpenAI-compatible endpoint”只说明请求和响应 envelope 类似，不代表：

- 模型一定返回裸 JSON；
- 模型使用相同的工具调用 dialect；
- 模型会生成 Runtime 需要的 `call_id`；
- prompt 足以成为可靠的协议边界。

### 7.2 修复方法

对应提交：

```text
fba09f3
```

主要修改：

- 增加 `codeteam.agent.protocol` dialect firewall；
- 支持 bare JSON、单一 Markdown JSON fence、DeepSeek DSML；
- DSML 使用结构化 parser，不用模糊正则抽取；
- mixed envelope、尾随文本、损坏 tag 继续 fail-closed；
- Runtime 在 schema validation 后生成 `step-n-call-m`；
- raw output 写入独立 evidence，canonical action 进入模型历史；
- prompt 提供工具与 final output schema；
- 最多允许两次 protocol repair；
- protocol repair 与 code repair 分开计数。

### 7.3 方法解决了什么

此前 11 个第一轮 raw response 可以离线归一为内部工具调用。模型提出的动作不再因为 DSML 或 Markdown 外壳被直接丢弃。

### 7.4 接着出现的新问题

B01 smoke：

```text
evals/week4/agent_runs/runtime_protocol_smoke_20260825_232221
```

关键结果：

| 指标 | 结果 |
|---|---:|
| changed_files | `src/auth/api.py` |
| patch_attempts | 1 |
| hidden acceptance | passed |
| regression | passed |
| steps | 20 |
| tool_calls | 42 |
| actor_status | failed |
| failure_category | `max_steps` |

协议已经能产生正确代码，但 Runtime 在验证环节反复行动，不能完成闭环。

---

## 8. 阶段五：验证命名空间与无进展检测

### 8.1 根因

模型在 tool arguments 中使用容器路径：

```text
/workspace/tests/auth
```

CommandPolicy 却在宿主机 workspace 上判断路径。Docker 路径、宿主机路径和 Agent 可见路径没有统一名称空间。

同时，以下命令语义相同但结构不同：

```text
python -m pytest tests/auth -q
python -m pytest /workspace/tests/auth -q
```

`cwd` 和默认参数差异也让重复动作检测失效，模型反复运行同一验证，消耗约 10 万 tokens。

### 8.2 修复方法

- Agent 可见验证命令统一使用 workspace-relative path；
- `cwd` 统一为 workspace-relative，默认 `.`；
- Docker builder 负责映射到 `/workspace`；
- CommandPolicy 不直接接收容器路径；
- run_tests 在执行前规范化 argv、cwd 和 option value；
- no-progress 使用 canonical arguments 和 workspace version；
- workspace 修改后允许重新验证，状态未变化的语义重复则停止。

### 8.3 方法解决了什么

宿主机、Runtime 和 Docker 的路径职责变得清晰；语义相同的验证动作可以被识别为重复。

### 8.4 接着出现的新问题

下一次 B01：

```text
evals/week4/agent_runs/runtime_verification_smoke_20260826_000800
```

Runtime 执行了 10 steps 和 23 tool calls，但最终因 DSML 多 envelope 和 protocol repair 耗尽而失败，仍未产生 patch。

这说明路径问题修复后，协议可靠性和上下文管理重新成为主要瓶颈。

---

## 9. 阶段六：Canonical Conversation、可见 Oracle 与上下文控制

### 9.1 进一步发现的问题

- invalid raw output 如果直接进入历史，会污染后续协议；
- 如果完全不保留动作事实，模型又可能重复探索；
- protocol repair 如果按生命周期累计，早期偶发错误会耗尽后期额度；
- Agent 只跑宽回归时，无法判断是否修复了当前任务；
- 相同 read/search 会重复消耗 tokens；
- compaction 如果压缩 raw provider dialect，可能把损坏协议重新注入上下文。

### 9.2 修复方法

对应提交：

```text
8ccb5dc
```

- `runtime_messages.json` 只保存 canonical conversation；
- raw provider output 单独写入 `model_outputs.jsonl`；
- 合法 action 重置连续 `protocol_repair_streak`；
- lifetime repair count 继续用于成本和评测；
- JSON mode 默认 `auto`，温度默认 0；
- structured compaction 保留 read/search、workspace version、验证和 completion gate；
- list/read/search/status/diff 增加状态相关缓存；
- 每题增加 completion-required public task verification；
- public oracle 在 pristine 状态通过时不得报告成功。

### 9.3 接着出现的两个新问题

#### 9.3.1 功能已正确，但 Completion Handshake 失败

运行目录：

```text
evals/week4/agent_runs/runtime_stability_smoke_20260826_214116
```

结果：

```text
patch applied
task verification passed
regression passed
hidden acceptance passed
git diff inspected
actor_status=failed
failure_category=repeated_action
```

模型在所有 completion gate 已满足后再次运行同一测试。Runtime 正确识别了无进展，但把任务判为失败，而不是进入一个明确的 finalize handshake。

这暴露出一个仍未完成的设计问题：最终成功是否必须完全依赖模型主动生成 final output，还是 Runtime 在所有客观 gate 满足后应进入受控 finalize 阶段。

#### 9.3.2 Grader 成功，但 Runtime Docker 失败

运行目录：

```text
evals/week4/agent_runs/runtime_stability_smoke_20260826_214408
```

结果：

```text
patch applied
Grader task verification passed
regression passed
hidden acceptance passed
Runtime run_tests failed
Docker bind mount source path does not exist
```

Agent 的 worktree 位于：

```text
/Users/root/workspace/Agent-Learning/evals/week4/agent_runs/...
```

Colima daemon 对该宿主机路径不可见。可信宿主机 Grader 能运行测试，但不能证明生产 Docker Runtime 已完成验证。

这一结果确认了一个重要不变量：

> Grader 的成功不能挽救 Runtime 的失败。否则 benchmark 会掩盖真实产品在 Docker 环境中无法执行测试的问题。

---

## 10. 阶段七：执行 Worktree 与 Artifact 分离

### 10.1 根因

此前 `--output` 同时承担两种职责：

```text
实验报告和 artifact 存储
执行 worktree 存储
```

但二者有不同约束：

- artifact 只需要供用户读取；
- execution root 必须能被 Docker daemon bind mount；
- `--keep-workspaces` 不应影响整个 artifact 根目录；
- 模型调用前应先知道 Docker 是否能看到 worktree。

### 10.2 修复方法

当前 Git 状态：

```text
UNCOMMITTED
基线提交：8ccb5dc
```

主要修改：

- `codeteam run` 和 `agent-eval` 增加 `--worktree-root`；
- 优先级为 CLI > `CODETEAM_WORKTREE_ROOT` > `~/.codeteam/worktrees`；
- 产品任务和 eval 使用独立 namespace；
- `--output` 只保存 manifest、results 和 artifacts；
- 首次模型调用前运行 Docker preflight；
- 区分 CLI、daemon、image、bind mount 和 container startup failure；
- preflight 失败返回 `PAUSED + sandbox_unavailable`；
- 环境失败时 usage、steps 和 tool calls 保持为 0；
- Sandbox 运行中失效时立即 halt，不继续让模型补救；
- Docker exit 125 与普通 pytest exit 1 分开；
- 增加精确 replacement edit，缩短 patch payload；
- `patch_attempts` 记录真实已验证 patch 工具调用。

### 10.3 方法解决了什么

后续两次 B01 的 Docker preflight 均成功：

```text
sandbox_preflight_available=true
environment_blocked_count=0
```

执行目录与 artifact 目录分离的设计成立，Colima 路径问题被消除。

### 10.4 接着出现的新问题

Docker 噪声消失后，模型动作协议再次成为唯一主故障。

---

## 11. 阶段八：两次 Docker Stability Smoke 仍失败

### 11.1 实验路径

```text
evals/week4/agent_runs/runtime_docker_stability_1_20260827_230627
evals/week4/agent_runs/runtime_docker_stability_2_20260827_230653
```

### 11.2 结果对比

| 指标 | Run 1 | Run 2 |
|---|---:|---:|
| steps | 5 | 6 |
| tool_calls | 2 | 8 |
| patch_attempts | 0 | 0 |
| protocol_repairs | 2 | 2 |
| input_tokens | 18,398 | 25,838 |
| output_tokens | 1,102 | 1,182 |
| cost_usd | 0.097668 | 0.132228 |
| runtime verification | not run | not run |
| regression | passed | passed |
| hidden acceptance | failed | failed |
| final category | `invalid_final_output` | `invalid_final_output` |

### 11.3 Run 1 时间线

```text
step 1  read AGENTS.md
step 2  read src/auth/exceptions.py
step 3  provider returns whitespace-only content
        protocol repair 1
step 4  semantically correct patch intent, invalid schema/incomplete JSON
        protocol repair 2
step 5  correct replacement intent, missing outer ]}
        repair budget exhausted
```

### 11.4 Run 2 时间线

```text
step 1  list repository
step 2  read docs and auth rules
step 3  search expired/internal error/RefreshTokenExpired
step 4  correct replacement intent, missing outer ]}
        protocol repair 1
step 5  same intent with newline, missing outer ]}
        protocol repair 2
step 6  same intent, missing outer ]}
        repair budget exhausted
```

### 11.5 可以确认的事实

- Docker preflight 成功；
- 两个 worktree 最终都是 clean；
- 没有 patch 被安全工具执行；
- public task test 和 hidden acceptance 在 unchanged workspace 中继续失败；
- 模型已经定位到正确文件、异常和返回值；
- 模型提出的代码语义是正确的；
- replacement 缩短了 payload，但仍不能保证 JSON envelope 完整；
- 历史 Flash 模型实验也出现过相同缺少闭合符的问题；
- 当前问题不是 B01 的代码推理能力，而是 action transport reliability。

### 11.6 目前无法确认的关键事实

当前 `ModelResponse` 没有保存：

```text
finish_reason
response id
system fingerprint
reasoning mode
provider raw envelope
incomplete reason
```

请求也没有显式设置 `max_tokens`。因此暂时无法区分：

- Provider 因 length 截断；
- inference resource 中断；
- 模型以 stop 结束但生成了坏 JSON；
- JSON mode 在当前模型上没有可靠兑现。

这部分结论必须标记为推断，而不能写成已证明事实。

---

## 12. 当前根本架构判断

### 12.1 最初设计缺陷

最初 `ModelClient` 面向 mock 和 single-shot 文本输出设计：

```python
ModelClient.complete(messages) -> str | ModelResponse
```

而 `ModelResponse` 主要只有：

```text
content
model
input_tokens
output_tokens
```

当系统升级成迭代 Coding Agent 后，这个接口没有同步升级。结果是 Agent Loop 被迫从普通文本中重建：

```text
tool call
tool arguments
final output
finish state
provider failure state
```

这是当前最根本的问题。

### 12.2 被误解的 provider-neutral

当前实现曾把 provider-neutral 理解为：

> 所有 Provider 都通过同一种 raw JSON 文本和 Runtime 对话。

更合理的定义应该是：

> Runtime 依赖统一的内部 `ModelTurn` 和 `ToolCall`；每个 Provider adapter 负责把自己的 native wire protocol 转换成内部结构。

目标架构：

```text
DeepSeek Chat/Responses API       OpenAI API       其他 Provider
             \                      |                 /
              \                     |                /
               Provider-specific adapters
                           |
                           v
              Provider-neutral ModelTurn
              actions | final | usage | finish
                           |
                           v
                 CodingAgentRuntime
```

### 12.3 为什么 dialect firewall 仍然有价值

Dialect firewall 不是错误实现，它解决了真实存在的 DSML、fenced JSON 和混合文本问题，并建立了：

- raw evidence 与 canonical conversation 分离；
- Runtime-owned call ID；
- fail-closed parser；
- protocol repair 独立计数。

它的问题是被放在了默认生产路径上，承担了 native provider adapter 本应承担的职责。

未来应保留它作为：

- 不支持 native tool calling 的 Provider fallback；
- legacy session/replay 兼容层；
- adversarial input firewall；
- 离线 artifact 分析工具。

而不是所有真实 Provider 的唯一 action transport。

---

## 13. 当前未解决问题清单

| 等级 | 问题 | 当前证据 | 计划方向 |
|---|---|---|---|
| P0 | `ModelResponse` 无法表达 structured turn 和 finish reason | 两次 JSON 在 EOF 前结束，无法判断截断原因 | 引入 `ModelTurn` 与 Provider adapter |
| P0 | production action 依赖 raw-text JSON | 正确 patch 意图无法进入工具层 | 使用 native function/tool calling |
| P1 | Provider 未显式设置/记录输出预算 | 未设置 `max_tokens`，finish reason 丢失 | 输出预算、incomplete 分类和 Provider retry |
| P1 | JSON mode empty content 消耗 Agent repair | Run 1 step 3 | 在 Provider 层作为 transient output 处理 |
| P1 | `context_budget=4096` 未形成硬边界 | Provider 输入出现 4419、4896 tokens | token-aware budget 与 output reserve |
| P1 | Completion handshake 依赖模型主动 final | 214116 所有 gate 通过后 repeated action | 增加受控 finalize 阶段 |
| P2 | protocol repair 反馈过于通用 | 模型确定性重复缺少 `]}` | 提供结构化错误与 adapter-level retry |
| P2 | patch intent 指标低估 | raw 中有 apply_patch 意图但 `patch_attempts=0` | 区分 rejected intent/validated/apply failure |
| P2 | manifest 缺少 per-request Provider 证据 | 只能看到最终 provider_runtime | 保存 finish/mode/retry/incomplete evidence |

在上述 P0/P1 修复前，不运行 11-task baseline 和 ablation。否则结果仍主要反映协议兼容性，而不是 Agent 能力。

---

## 14. 下一阶段拟采用的修复顺序

> 本节是当前计划，不表示已经实现。完成后必须补充 commit、测试和实验结果。

1. 扩展模型响应证据，保留 `finish_reason`、response ID、actual mode、thinking mode、usage 和 incomplete reason。
2. 显式设置输出 token 上限，并从输入 context 中预留输出预算。
3. 将 empty、length 和 insufficient resource 放到 Provider failure/retry 层，不消耗 Agent protocol repair。
4. 设计 provider-neutral `ModelTurn`：`actions | final | usage | finish`。
5. 为 DeepSeek/OpenAI-compatible 实现 native function calling adapter。
6. 将 final submission 也建模成结构化动作，避免 action/final 双文本协议。
7. 保留 JSON/DSML codec 作为 fallback，不再作为默认生产路径。
8. 将 compaction 改成 token-aware，并允许压缩 initial context，而不是永久保留完整前两个消息。
9. 增加 finalize handshake，区分“重复动作失败”和“所有 gate 已满足后的完成确认”。
10. 补齐 provider、protocol、budget、resume、metrics 和 Runtime 集成测试。
11. 连续运行两次 B01；两次均完成后再运行 11-task baseline。
12. baseline 稳定后才运行 planning、repair 和 compaction ablation。

---

## 15. 面试表达素材

### 15.1 30 秒版本

> 我给自己的 Coding Agent 做了 15 题真实 LLM benchmark。第一次只有 2 题成功，但我没有直接归因于模型，而是发现 8 题是 Provider SSL EOF，patch 和 pycache 还污染了评测。修复基础设施后，又发现 4 个 hidden test 在 pristine baseline 已经通过，于是重建了 11 题可复现数据集。随后我把 eval actor 和产品 Runtime 统一，才暴露出 DeepSeek DSML、验证路径、Docker mount 和 raw JSON action 等真实生产问题。最后我定位到根因不是 parser 不够宽松，而是 ModelClient 仍是 single-shot 文本抽象。正确方向是 provider-specific adapter 加 provider-neutral structured ModelTurn。

### 15.2 两分钟版本

> 这段工作最重要的不是把 benchmark 分数调高，而是建立一个可信的失败归因链。第一次 15 题只有 2/15，但其中 8 题是 Provider 阻断，所以我先做 retry、错误分类和 artifact；随后 4 个 hidden oracle 在 pristine 状态已通过，我就统一 fixture、base commit、fault seed 和 public/hidden oracle。数据可信后，我又发现评测用 PatchActor、产品用另一条 Runtime，于是把两者统一成可迭代的 CodingAgentRuntime。
>
> 统一以后 11 题全部在第一轮失败，但模型其实返回了 DSML tool calls，所以我实现 dialect firewall、Runtime-owned call ID 和 protocol repair。协议打通后，B01 已经能生成正确 patch 并通过 hidden test，却因为 `/workspace` 与宿主机路径混用跑到 max steps。修正验证命名空间后，又发现 Colima 看不到项目目录下的 worktree，于是把 execution root 和 artifact root 分离，并增加模型前 Docker preflight。
>
> Docker 修好后，模型仍连续两次生成语义正确但缺少最外层闭合符的 replacement JSON。历史 Flash 和当前 Pro 都复现，说明这不是单次采样问题。继续追踪后发现 ModelResponse 丢弃了 finish reason，也没有 native tool-call 表达能力。我的最终判断是 provider-neutral 应该存在于 Runtime 内部结构，而不是强迫所有 Provider 输出相同 raw JSON。这个过程让我学到，Agent benchmark 首先是基础设施和评测设计问题，其次才是模型能力问题。

### 15.3 可深入追问的技术点

- 为什么 hidden acceptance 必须先在 pristine baseline 失败？
- 为什么 Grader 通过不能覆盖 Runtime 验证失败？
- 为什么 Provider retry 和 protocol repair 必须分账？
- 为什么 Runtime 必须自己生成 call ID？
- 为什么 Docker 路径、Agent 路径和宿主机路径要使用不同边界？
- 为什么 native tool calling 不破坏 provider-neutral？
- 为什么 completion gate 不能只相信模型自报？
- 为什么 ablation 必须等 baseline 稳定后再运行？
- 如何区分模型推理失败、协议失败、环境失败和评测失败？

---

## 16. Git 与实验索引

### 16.1 关键提交

| Commit | 作用 |
|---|---|
| `ff7d43a` | 增加 Week4 agent eval harness |
| `3956afc` | Provider retry、结构化 patch、artifact 和 pristine oracle |
| `f6d7bb7` | 重建 11-task 可复现 benchmark |
| `59021f7` | 统一 `codeteam run` 与 `agent-eval` Runtime |
| `fba09f3` | Provider dialect firewall 与 bounded protocol repair |
| `8ccb5dc` | Canonical conversation、public oracle、验证命名空间和协议稳定性 |
| `UNCOMMITTED`，基于 `8ccb5dc` | Docker 可见 worktree、preflight、Sandbox halt 与 replacement patch |

### 16.2 关键实验

| 实验目录 | 主要发现 |
|---|---|
| `real_llm_baseline_20260823_181214` | Provider 阻断、patch 格式和 pycache 污染 |
| `real_llm_baseline_20260824_202744` | pristine oracle 通过、fixture/base 不可信 |
| `runtime_baseline_20260825_215834` | 统一 Runtime 不理解 DSML/fenced JSON |
| `runtime_protocol_smoke_20260825_232221` | patch 正确但验证循环达到 max steps |
| `runtime_verification_smoke_20260826_000800` | protocol repair 和 DSML 仍不稳定 |
| `runtime_stability_smoke_20260826_214116` | 所有测试通过但 completion handshake 失败 |
| `runtime_stability_smoke_20260826_214408` | Docker daemon 看不到项目目录 worktree |
| `runtime_docker_stability_1_20260827_230627` | Docker 成功，replacement JSON 缺少闭合符 |
| `runtime_docker_stability_2_20260827_230653` | 相同协议问题稳定复现 |

---

## 17. 持续更新日志

### 2026-08-27

- 根据 Git 历史、对话记录和现有 eval artifacts 建立本文档。
- 记录第一次 15-task benchmark 到两次 Docker stability smoke 的完整问题链。
- 当前结论：Docker execution root 修复已得到 preflight 证据；单 Agent 仍被 raw-text action transport 阻断。
- 下一步：先升级 Model Response / Provider Adapter 边界，不运行 11-task baseline。

### 2026-08-28：第一刀修复——ModelRequest → ModelTurn

#### 问题与根因

修改前真实链路是：

```text
messages
→ complete(messages)
→ message.content
→ JSON / fence / DSML parser
→ Runtime ToolCall
```

OpenAI-compatible HTTP 实现位于 CLI evaluation 模块，请求不发送 Runtime
tool schema 或显式输出预算；响应只保留 `content/model/tokens`；Runtime
生成的 `role=tool` observation 在下一次 Provider 请求中又被包装成
`role=user` JSON。`content=None + native tool_calls` 无法表达，`length` 与
malformed JSON 也无法区分。

确认的 Root Cause：

> Agent action transport was incorrectly modeled as free-form text generation.

原 failure 保留为：模型已理解正确修改 → action JSON envelope 截断 → parser
无法恢复完整 patch → `SafeExecutionService` 从未收到 patch → 任务失败。

#### 设计选择

采用 [DD-W4-D7-07](../docs/design_decisions/DD-W4-D7-07.md)：

```text
ModelRequest
→ OpenAI-compatible Provider Adapter
→ ModelTurn
→ Runtime-owned ToolCall
→ ToolRegistry / Runtime Tool
→ SafeExecutionService
→ ToolResult
→ native role=tool
→ next ModelRequest
```

关键不变量：

- `provider_call_id` 是 opaque transport correlation；`runtime_call_id` 在
  Runtime schema validation 后生成。两者共同持久化但不能交叉信任。
- native tool calls 优先；同一 turn 即使同时含 textual action，也只执行
  native action 一次。
- JSON、fenced JSON、DSML 与 bounded protocol repair 保留为 fallback。
- `finish_reason=length` 直接分类 `output_truncated`，不进入 JSON parser，
  不调用 backend，也不消耗 protocol repair。
- `content=None + tool_calls` 是合法 turn；empty content + empty calls 才是
  bounded transient/incomplete provider turn。
- `context_budget` 明确为 input budget，并满足
  `max_input <= context_window - max_output - safety_headroom`。
- native `apply_patch` / `run_tests` 不绕过既有 Safe Execution boundary。

#### 生产修改

- 新增 provider-neutral `ModelRequest`、`ModelTurn`、`ModelUsage`、
  `ModelFinishState` 与 input budget validation。
- `ToolCall` / `ToolResult` / `Message` 最小扩展双 ID，没有复制第二套业务
  ToolCall schema。
- `codeteam.llm.openai_compatible` 接管 HTTP payload、native schema、response
  parsing、capability fallback、finish/retry metadata 和 provider manifest；
  `run_command.py` 不再反向导入 `agent_eval_command.py` 的 Provider factory。
- AgentLoop 变为 native-first，legacy `complete()` 通过 compatibility adapter
  继续支持现有 fake/planner/text provider。
- native assistant/tool chain 进入 canonical durable messages；audit evidence
  增加 response ID、finish state/reason、actual mode、usage、incomplete reason、
  system fingerprint 和双 ID 映射。
- Session durable state 保存输出预算、context window、headroom、native/reasoning
  配置；resume 与 recent-tail selection 不拆散 native turn group。
- structured compaction 不再永久保留完整前两条消息，并按完整 serialized
  messages + tools 的 UTF-8 估算做输入预算检查；native assistant/tool group
  整体保留或整体丢弃。
- CLI 增加 `--max-output-tokens`、`--model-context-window`、
  `--safety-headroom-tokens`、`--native-tools/--text-actions` 与
  `--reasoning/--no-reasoning`。

#### 离线验证

```text
.venv/bin/python -m pytest -q
1308 passed, 6 skipped in 33.52s
```

新增回归覆盖 native happy path、tool result round-trip、empty/native、
empty/incomplete、length、malformed args、unknown tool、native+text 去重、
fallback compatibility、SafeExecution patch/command、usage/finish evidence、
Session resume、compaction atomicity 和 input/output budget。

静态门与 diff gate 在本轮收尾命令中执行并记录于最终交付；真实 Provider
未调用，API key 未读取、打印或持久化。

#### 未运行项与仍未解决问题

```text
B01 real-provider smoke: NOT_RUN_BY_CODER
11-task benchmark: NOT_RUN
Native Tool Transport Success Rate: NOT_RUN
Protocol Parse Failure Rate: NOT_RUN
Provider Incomplete Turn Rate: NOT_RUN
ToolCall → Runtime Execution Rate: NOT_RUN
Native vs textual ablation: NOT_RUN
```

第二刀仍然 pending：Runtime completion ownership / `READY_TO_FINALIZE`。
本轮没有修改 completion state machine、submit-result semantics 或
repeated-action completion handshake，不能宣称 SingleAgent 已完全解决。

### 2026-08-29：第一刀半——Verification Environment Contract

#### 真实 Failure Case

第一刀之后，用户亲自运行 B01，native transport 已经稳定工作：

```text
native_tools_actual=true
response_mode_actual=native_tools
protocol_repair_attempt_count=0
protocol_failed_count=0
read_file → apply_patch → real Git diff
```

模型正确地把 expired refresh token 的 generic error 改为异常消息。之后
Runtime 执行 authoritative task command：

```text
python -m pytest tests/task_verification/test_b01.py -q
```

Docker 返回：

```text
/usr/local/bin/python: No module named pytest
```

Agent 根据 `AGENTS.md` 尝试 `uv run pytest`，但 exact verification allowlist
正确拒绝替代命令；再次执行 required command 仍然缺 pytest，最终形成
`REPEATED_ACTION`。可信宿主机 Grader 随后证明 public task verification、
regression、hidden acceptance 和 security 全部通过。

完整 Failure Case：
[FC-W4-D7-01](../docs/failure_cases/FC-W4-D7-01.md)。

#### 根因

```text
Verification command contract
!=
Verification environment capability
```

旧 `DockerSandboxPreflight` 的固定 `test -d /workspace` 只能证明 Docker CLI、
daemon、image、mount 与 container startup。`No module named pytest` 的 exit 1
却被当作普通 `VerificationEvidence(passed=False)`，因此基础设施错误进入了
Agent code repair/no-progress 路径。

确认的 Root Cause：

> Runtime verification commands and the sandbox verification environment did
> not share an explicit compatibility contract.

#### 设计选择

采用 [DD-W4-D7-08](../docs/design_decisions/DD-W4-D7-08.md)：

```text
Sandbox Infrastructure Preflight
  → test -d /workspace

Verification Environment Preflight
  → python --version
  → python -m pytest --version

Task Verification
  → exact command → SafeExecutionService → Docker
```

项目新增 `docker/sandbox/`：Python `3.11.15-slim-bookworm` 同时固定 tag 与
digest，pytest `9.1.1` 及直接运行依赖使用精确版本。build context 只包含
Dockerfile 与 requirements，不复制 host `.venv`、仓库或 secrets；Runtime
期间不联网安装、不 pull、不自动重建镜像。

关键不变量：

- verification preflight 失败时 Provider calls、steps、tool calls、tokens、
  cost 与 repairs 都为 0；
- fixed probe 由 Runtime 构造，不接受模型/任务的任意 argv，也不放宽
  `python -c` CommandPolicy；
- `No module named pytest` 分类为 `verification_environment_failed /
  pytest_unavailable`，不再演化成 repair 或 repeated action；
- 普通 pytest assertion failure 仍是 `test_failed`，继续作为代码修复反馈；
- Runtime Docker 与 trusted-host Grader 可以使用不同物理 Python，但 manifest
  同时保存 logical capabilities、image identity 和双方版本证据；
- task-specific command authoritative；AGENTS discovered command 只是一般指导。

#### 验证结果

```text
相关 Sandbox/Execution/Verification/Agent/Evaluation/CLI:
374 passed, 8 skipped in 19.04s

最终普通 sandbox 全量:
1322 passed, 8 skipped in 29.77s

真实 Docker（最终 digest-pinned image）:
58 passed in 2.78s
```

真实 Docker 覆盖 image ID、Python `3.11.15`、pytest `9.1.1`、只读 root、
无网络、workspace mount 和 Docker socket 不可见。普通 sandbox 的 8 个 skip
是受限执行环境无法访问 Docker socket；提升权限后的真实 Docker suite 无 skip。

#### 未运行项与边界

```text
Post-fix B01: NOT_RUN_BY_CODER / pending user validation
11-task benchmark: NOT_RUN
Native/text ablation: NOT_RUN
Completion Ownership / READY_TO_FINALIZE: pending
```

本轮只保证 Week4 Python + pytest 最小 contract。仓库未来需要的第三方运行依赖、
Node/Java/Rust/uv 等必须通过后续显式环境契约扩展；没有新增动态 provisioning、
PackageInstaller 或通用 DependencyResolver。

### 2026-08-29：第二刀——Scratch Isolation + Versioned Completion

#### 历史证据，不是本轮重跑

本轮以用户已有的
`evals/week4/agent_runs/verification_contract_11task_20260829_134620/`
为 pre-fix 基线：11 tasks 中 actor success 5、acceptance 9、task verification
10、regression 10、security 11，provider/environment blocked 都为 0。Coder 没有
运行 B01、11-task、benchmark、ablation 或任何真实 LLM 命令。

两个 failure case 决定本轮边界：

1. [F03 scratch pollution](../docs/failure_cases/FC-W4-D7-02.md)：pytest
   `tmp_path` 落入 `/workspace/pytest-of-root`，产生 YAML 和 symlink；后续
   checkpoint 正确拒绝 symlink，patch 全部 fail closed。
2. [B02/F01/R03 completion false negative](../docs/failure_cases/FC-W4-D7-03.md)：
   intended diff、task、regression、hidden、security 都已通过，actor 却在继续
   test/diff/no-op 后以 `repeated_action` 失败。B03 同时存在 completion false
   negative 与 scratch 污染。

R02 是真正的语义编码遗漏：executor 的 transient `RuntimeError` 没有重试。
本轮不修改 prompt/oracle/fixture、不硬编码 R02，也不让 Grader rescue actor。

#### Phase A：验证 scratch 所有权

采用 [DD-W4-D7-09](../docs/design_decisions/DD-W4-D7-09.md)：

- `run_tests` 强制 `workspace_write=False`；patch 仍走 host
  `SafeExecutionService`；
- Docker 添加 128 MiB `/tmp` tmpfs，`nosuid,nodev,noexec,mode=1777`；
- `TMPDIR/TMP/TEMP=/tmp`、`HOME=/tmp/home`、cache 与 pycache 都在 `/tmp`；
- Runtime 固定 `PYTEST_ADDOPTS=-p no:cacheprovider`；模型不能覆盖 profile；
- 验证前后 fingerprint tracked + non-ignored untracked 的 path/type/mode/content；
  symlink 只 hash link metadata，绝不 follow target；
- mutation 会增加 `workspace_version`、记录
  `workspace_hygiene_failed`、使 diff review stale 并暂停；不自动删除证据。

没有采用 auto-delete、放宽 CheckpointManager、host writable scratch mount 或继续
依赖可写 source workspace。

#### Phase B/C：版本化证据与 Runtime-owned finalization

采用 [DD-W4-D7-10](../docs/design_decisions/DD-W4-D7-10.md)：

- `VerificationEvidence.workspace_version` 保留完整历史；
- `git_diff_checked_version == workspace_version` 才算当前 diff 已审；
- task-specific commands 和所有 configured broad regression commands 都必须在
  当前版本通过；没有 task command 时保留 broad fallback；
- pure `CompletionGate` 还检查 real/safe diff、hygiene 与 execution pause；hidden
  acceptance 不进入 gate；
- native `submit_result(summary, notes?)` 只表达完成请求，不接受 tests/status/diff
  自报字段；accepted/rejected 都生成匹配的 `role=tool`；
- accepted result 先进入 canonical conversation，再产生 typed terminal completion，
  不再请求 Provider；mixed batch 全部不执行；
- ready 后重复调用被 skip 并返回 advisory，持续无进展仍 bounded stop；
- textual final 只是 compatibility fallback，也必须经过同一个 versioned gate；
- Session 持久化 fingerprint/version/evidence history/diff-review version/hygiene，
  resume drift 或旧状态缺字段都会使旧证据 stale，不持久化 trusted ready bit。

Evaluation 新增 actor completed、within budget、failure category histogram、
completion ready、ready-but-actor-failed、post-ready calls 和 verification workspace
mutation 计数。外部 Grader 的成功依旧不能升级 actor 状态。

#### 离线验证边界

新增测试覆盖 tempfile/pytest scratch、source read-only、fingerprint 内容变化、
symlink metadata、patch/checkpoint 在验证后仍可用、版本 stale、task+broad gate、
submit accepted/rejected/mixed、native pairing、ready duplicate、Session resume 与
workspace drift、Evaluation metrics。最终验证结果：

```text
focused sandbox/execution/git/agent/session/evaluation/cli:
487 passed, 9 skipped

full pytest:
1336 passed, 9 skipped

real Docker sandbox (elevated Colima access):
60 passed

touched-path Ruff:
All checks passed!

touched source Mypy --follow-imports=skip:
Success: no issues found in 12 source files

git diff --check:
passed (no output)
```

最初受限执行的 Docker 命令得到 `51 passed, 9 skipped`，skip 原因为无法连接
Colima socket；获得 Docker daemon 权限后同一命令实际执行为 `60 passed`。

```text
Post-fix B01: NOT_RUN_BY_CODER
Post-fix 11-task: NOT_RUN_BY_CODER
Benchmark / ablation / real LLM: NOT_RUN_BY_CODER
```

### 2026-08-29：第四刀——Progress Control & Diagnostic Affordance

#### 用户运行证据

本轮只读取既有真实运行，不由 coder 重跑：

- `completion_gate_b01_20260829_171808`：B01 1/1 success，completion ready、actor
  completed、task/regression/acceptance/security 全通过，repair/protocol/provider/
  environment/workspace mutation 均为 0。
- `completion_gate_11task_20260829_171835`：10/11 success；唯一失败 F03 为
  `max_steps`。整体 acceptance/regression/task verification 均 10，security 11，
  ready-but-actor-failed、post-ready calls、workspace mutation 均为 0。
- F03 完整 evidence：20 turns、37 calls、0 patch attempts、0 changed files；sandbox、
  verification toolchain 和 Provider 正常。模型已读到 dispatcher、public test 和 config，
  正确理解 explicit false 才 suppress、missing 保持行为，却围绕 PyYAML availability
  持续不同 read/search/list。第 19 turn 已形成 minimal parser/fallback 思路，仍未 patch。

因此根因分层是：primary 为 Runtime 缺少 source-progress-aware intervention；secondary
为实际 verification sandbox 缺少受限 dependency probe；重复初始读取是效率贡献项。
它不是 retrieval、completion、repair、provider、protocol 或 verification failure。

#### 实现决策

1. [DD-W4-D7-11](../docs/design_decisions/DD-W4-D7-11.md)：新增独立
   `ProgressTracker/ProgressPolicy`。source、diagnostic、completion 三类进展不混账；
   40%/70% 两级 soft advisory 进入下一次正常 request；85% 后满足条件才
   `PAUSED + no_source_progress`，不强迫错误 patch。一次成功 patch 为新 workspace
   version 重置提示状态。
2. [DD-W4-D7-12](../docs/design_decisions/DD-W4-D7-12.md)：新增
   `inspect_environment`，只允许 module/bare executable；Runtime fixed probe 在真实
   read-only verification Docker 中运行。availability 与 declaration 分开，未声明但
   image 偶然具备会警告不可移植。没有 generic `run_command`，没有放宽 `python -c`。
3. [DD-W4-D7-13](../docs/design_decisions/DD-W4-D7-13.md)：从
   `ContextBuildReport` 显式建立 versioned `InitialContextSnapshot`。完整且当前、并仍
   位于请求内才返回引用；被 compaction 移除则回完整缓存；partial/ranged/stale 真实读。

F03 失败分析保存在
[FC-W4-D7-04](../docs/failure_cases/FC-W4-D7-04.md)。Session schema 升至 v4，累计
progress metrics 可 resume；Evaluation result 和 summary 贯通 first patch、pre-edit、
advisory/pause、environment inspection、initial context reuse 等字段。

#### 用户运行稳定性方案

新增 `scripts/run_single_agent_stability_validation.sh`：顺序执行 F03 x5、B01 x2、
11-task x3；每次独立时间戳/序号目录，业务失败不中断后续运行，最终由项目
`.venv/bin/python` 汇总 `stability_summary.json` 并按门槛返回 exit code。Coder 只运行
了 `bash -n` 和 `--dry-run`，没有执行真实 Provider campaign。

#### 离线验证结果

```text
focused agent/execution/sandbox/evaluation/session/scripts:
426 passed, 9 skipped

full pytest:
1367 passed, 9 skipped

touched-path Ruff:
All checks passed!

touched source Mypy --follow-imports=skip:
Success: no issues found in 11 source files

bash -n + stability --dry-run:
passed; 10 commands printed, no campaign output created

git diff --check:
passed (no output)
```

9 个 skip 仍是当前受限终端不能访问 Docker daemon 的既有 integration skip；本轮没有
申请或执行真实 Docker probe，也没有把 host availability 当作 sandbox evidence。

```text
Post-change real LLM: NOT_RUN_BY_CODER
Post-change benchmark: NOT_RUN_BY_CODER
Commit: UNCOMMITTED
```

### 2026-08-30：第五刀——Finalization-aware Budget & Terminal Settlement

#### 问题：40/40 正确，但 Actor 只有 38/40

本轮继续读取用户已运行的
`evals/week4/agent_runs/stability_20260830_002409`，不由 coder 重跑。40 个结果的
acceptance/regression/task verification/security/within-budget correctness 全部通过，
但 Actor success 为 38/40。两个失败都不是“模型不会写代码”：

1. F03 run `03_F03_3_20260830_002622`：第 17/18 turn 已通过 task/regression，
   第 20 turn `git_diff` 才使 CompletionGate READY；flat budget 先报 MAX_STEPS，无法再
   用第 21 turn submit。
2. F04 run `09_11task_2_20260830_003505`：v4 verification PASS 后第 17 turn 合法 docs
   patch 推进到 v5，旧验证被正确 stale；optional diagnostics/diff/submit 用完余量，
   submit 被正确拒绝缺少 v5 verification。task declared 30 被 run default 20 裁成
   effective 20，但旧 artifacts 没有明确记录三种预算来源。

真实记录分别落在 [FC-W4-D7-05](../docs/failure_cases/FC-W4-D7-05.md) 和
[FC-W4-D7-06](../docs/failure_cases/FC-W4-D7-06.md)。归因是 Finalization Budget / Actor
Orchestration False Negative，而不是 retrieval、patch correctness、grader、Provider、
protocol、sandbox 或 security failure。

#### 方法：预算内 reserve，而不是提高 max_steps

[DD-W4-D7-14](../docs/design_decisions/DD-W4-D7-14.md) 选择组合方案：

- 在 effective budget 内预留 `max(3, ceil(20%))`；20 步默认 reserve 4，可显式覆盖。
- 有真实 diff 且 remaining turns 进入 reserve 时，Runtime 用 CompletionGate 的当前
  missing requirements、精确 task/regression commands 和 diff state 生成 finalization
  advisory。reserve 不冻结代码；发现真实 bug 仍允许 patch，版本和证据照常失效。
- READY 后 submit accepted；patch 合法 reopen；first targeted read/search 合法；重复
  read/search 和 test/list/status/diff 等冗余工作返回 cache/advisory。batched tool calls
  每次调用前重算 gate，防止 READY→patch 后错误跳过新版本验证。

#### 新问题：最后一轮才 READY，仍没有 submit turn

Reserve 不能保证模型一定提前 submit。F03 证明最后一个合法 tool call 本身可能才生成
current diff-review evidence。因此只做 prompt/advisory 仍会把客观完成误报成预算失败。

#### 新方法：Runtime-only terminal settlement

step boundary 现在先处理已有 safety halt，再读取当前 CompletionGate。NOT READY 保持
MAX_STEPS；READY 时重新计算 fresh Git content fingerprint，只有与 Runtime evidence
fingerprint 相同才无额外 Provider call 地完成。外部未观察 mutation 会
`PAUSED + workspace_drift`，stale verification/environment/security pause 都不能结算。
fallback summary 只列 bounded changed files，不伪装成 model output；`completion_mode`
区分 `model_submitted` 与 `runtime_budget_boundary_settlement` 并进入 Runtime、Session
schema v5/events、Eval result/summary/manifest。

#### 证据与后续验证

Eval CLI 和 stability script 显式支持/传递 `--max-steps 20`。每个结果和 manifest 记录
task declared、run cap、effective 和 source；B02/B05/F04/R02/R03 的 25/25/30/30/30
声明预算在本轮因果实验里都明确裁为 20。新的稳定性聚合不再只盯
`no_source_progress`：只要 Actor 非 completed，而 acceptance/regression/task
verification/security/within-budget 全真，就计入
`grader_correct_but_actor_failed_count` 并让 campaign 非零退出；同时 fail provider、
environment、protocol、ready-actor failure、workspace mutation 或非 20 effective budget。

Coder 只执行 deterministic tests、`bash -n` 和 stability `--dry-run`；F03 x5、B01 x2、
11-task x3 真实 campaign 仍由用户运行。没有执行 benchmark、ablation 或 11-task。

### 2026-08-30：第六刀——Batch-aware Stall Detection

#### 问题：39/40 中唯一失败由 Runtime 在 native batch 中途制造

本轮读取用户已运行的
`evals/week4/agent_runs/stability_20260830_102307`，不由 coder 重跑。campaign
事实为：Actor 39/40、security 40/40；F03 定向 4/5、B01 2/2、三次完整 11-task
33/33。唯一失败是 `02_F03_2_20260830_102401`：F03 在 11 turns、33 tool calls、
31 diagnostic progress、0 patch 下以 `no_progress` 结束；Provider/native protocol、
sandbox 和 verification toolchain 均正常。

失败 turn 声明三个 native calls：

```text
read AGENTS.md                         cached
read src/experimental/broken_parser_case.py  fresh
read src/plugins/loader.py             fresh
```

真实 durable messages 只有第一个 ToolResult。代码核对确认
`cached_no_progress_count` 在 `for call in tool_calls` 内逐 call 增长，到阈值立即 return；
Repeated Action 也在同一循环内直接 return。因此轨迹可由现有控制流完整解释：Runtime
在 ToolCall 粒度做了本应属于 Model Turn 的 stall decision。

该事实只证明 lost execution opportunity。丢失的是两个 fresh read，不是 patch，不能
声称继续执行必然成功或 F03 应稳定 5/5。

#### 方法：检测 per-call，决策 per-turn

[DD-W4-D7-15](../docs/design_decisions/DD-W4-D7-15.md) 保留现有 mechanical guard，
但把停滞结算移到完整安全 batch 后：

- cached/repeated exploration 每个 call 返回 correlated cache/duplicate ToolResult；
- 一个 assistant turn 无论有几个 cache hit，streak 最多 `+1`；
- 同 batch 任一 uncached observation 使 turn 不是 pure mechanical stall；
- successful patch 仍通过现有 observer 推进 workspace/source progress；
- fresh diagnostic 不重置 ProgressTracker source clock；
- 连续两个完整 stalled turns 仍会 `NO_PROGRESS/REPEATED_ACTION`；
- repeated `apply_patch`/`submit_result`、mixed submit、tool budget 和 Runtime halt 保持
  fail-fast，后续调用明确写 safety/budget rejection。

没有修改 40%/70%/85% ProgressPolicy、CompletionGate、Finalization Budget、Terminal
Settlement、Sandbox、native protocol、Initial Context、retrieval、planner、repair 或
checkpoint。

#### 新问题：同名 no-progress 无法表达 failure ownership

`StopReason.NO_PROGRESS` 同时表示 cached stall、empty batch、empty model turn 和
completion guidance ignored；仅看 `failure_category` 无法判断 Runtime 是否丢弃了同
batch 的安全调用。

#### 新方法：结构化 origin 与 premature-stop gate

AgentLoopResult 新增 `failure_origin`，至少区分 `cached_batch_stall`、
`empty_tool_batch`、`empty_model_turn`、`completion_guidance_ignored`，并记录 repeated
stall。`declared/processed/rejected/unprocessed-safe` 计数贯通 Runtime、Eval task
result、summary、manifest 和 stability aggregation。

Stability 不要求 `mechanical_no_progress_failure_count == 0`，因为两个完整机械停滞
turn 是合法 guard；它直接要求：

```text
batch_premature_stop_count == 0
progress_guard_unprocessed_safe_tool_call_count == 0
```

同时保留 source no-progress、repeated action 和既有 Provider/environment/protocol/
completion/security 控制，F03 floor 仍为 `>= 4/5`。

Failure Case 记录于
[FC-W4-D7-07](../docs/failure_cases/FC-W4-D7-07.md)。

#### 离线证据边界

新增 deterministic tests 真实模拟 multi-tool native ModelTurn，覆盖精确 F03 顺序、
单 turn 多 cache、两个完整 stalled turns、cached/repeated + fresh/patch、等价 tests、
tool budget、Runtime halt、mixed submit、failure origins、source progress 和 Eval/
stability 传播。最终离线结果：

```text
batch-aware focused: 10 passed
tests/agent: 158 passed
tests/evaluation: 41 passed
full pytest: 1409 passed, 9 skipped
touched-path Ruff: All checks passed
touched-source Mypy --follow-imports=skip: 8 files, no issues
git diff --check: passed
bash -n + stability --dry-run: passed; 10 commands, explicit max-steps 20,
                                    no campaign output created
```

9 个 skip 是受限终端无法访问 Docker/Colima 的既有 integration skip；本轮没有修改
sandbox，也没有申请真实 Docker 或 Provider 执行。

```text
Post-change stability campaign: NOT_RUN_BY_CODER / pending user validation
11-task / benchmark / ablation / real LLM: NOT_RUN_BY_CODER
Commit: UNCOMMITTED
```

仍然诚实保留：turn-level stall 是 heuristic；ProgressPolicy 只测 source-state progress，
不理解 semantic completion；LLM reasoning 仍有方差；F03 仍可能因真实推理失败；不宣称
deterministic 100%；environment inspection cache 与 stdlib portability classification
延期为 P2。
