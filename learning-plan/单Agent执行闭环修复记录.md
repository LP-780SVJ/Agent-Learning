# CodeTeam 单 Agent 执行闭环修复记录

> 文档状态：持续维护  
> 首次建立：2026-08-27  
> 当前分支：`week4`  
> 当前记录终点：Model Client 已升级为 Agent Turn；等待用户执行 B01 native-tool smoke
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
