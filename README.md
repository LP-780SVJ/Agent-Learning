# Agent-Learning

`Agent-Learning` 是一个从零搭建 coding agent 的学习型项目。它不是只做一个聊天壳，而是逐步实现一个 agent 在真实代码仓库里工作时需要的基础设施：模型循环、工具执行、安全边界、仓库理解、代码检索、上下文构建、评测和复现记录。

当前项目已经完成 Week1 和 Week2：

- Week1: 搭建 agent 主循环，完成模型输出解析、工具调用、停止条件、最终结果校验、事件记录、用量统计和基础安全工具。
- Week2: 搭建代码上下文引擎，完成仓库扫描、语言/文件分类、Python 解析、符号索引、ImportGraph、AGENTS.md 指令加载、候选召回、排序、Repo Map、上下文压缩、CLI 和检索评测。

所有开发、测试和验收命令都必须使用项目虚拟环境：

```bash
.venv/bin/python
```

不要使用系统默认 `python3` 跑测试或 CLI。

## Current Capabilities

项目目前具备这些能力：

- 运行一个受限 agent loop，并把模型输出转成工具调用或最终结果。
- 注册和执行结构化工具，包括 calculator、文件工具和受控 shell 工具。
- 限制工具访问 workspace，阻止明显危险命令和 shell/interpreter 字符串执行。
- 扫描 Git 仓库，识别 tracked/untracked 文件、语言、文件角色、重要配置和忽略文件。
- 解析 Python 文件，提取 class/function/method/variable 符号和引用。
- 提取 Python import，并解析本地模块依赖，构建 ImportGraph。
- 读取 AGENTS.md / 指令文件，并从项目配置中推断 test/lint/typecheck 命令。
- 针对自然语言任务召回相关文件，综合 filename、ripgrep、SymbolIndex、ImportGraph、test pair、config/instruction 信号排序。
- 构建面向 LLM 的上下文报告，包括 Top files、Repo Map、适用指令、代码片段、测试命令和诊断信息。
- 在总 token 预算下压缩 repo map、instructions 和 code context，避免小预算越界。
- 运行文件检索评测，输出 JSONL 结果和 manifest，记录 commit、dirty 状态、dataset hash、命令参数、Python/ripgrep/parser 版本和 ranking weights。

## Architecture Overview

```text
codeteam/
├── agent_loop.py                  # Week1 agent 主循环
├── state.py                       # AgentLoopState、StopReason、重复动作指纹
├── limits.py                      # 最大步骤/工具调用预算
├── events.py                      # AgentEvent 与事件类型
├── errors.py                      # 异常分类、可重试判断
├── schemas/                       # Message、ToolCall、ToolResult、AgentFinalOutput
├── llm/                           # MockModelClient 与 OpenAI-compatible 接口预留
├── tools/                         # calculator、file tools、safe shell、tool registry
├── usage/                         # token 计数、价格、用量统计
├── repository/                    # Git inventory、scanner、文件分类、语言识别、文件名索引
├── parsing/                       # Python AST / tree-sitter parser registry
├── symbols/                       # 符号模型、提取器、SymbolIndex
├── imports/                       # ImportExtractor、ModuleIndex、Resolver、ImportGraph
├── instructions/                  # AGENTS.md / .clinerules 加载、glob 匹配、命令检测
├── search/                        # QueryAnalyzer、ripgrep client、CandidateGenerator
├── ranking/                       # FileRanker、RankingWeights、PageRank
├── repomap/                       # Repo Map 构建、压缩、渲染
├── context/                       # ContextItem、ContextSelector、ContextCompressor、预算工具
├── application/                   # inspect-repo、build-context、shared repository indexes
├── evaluation/                    # EvalCase、EvalResult、metrics、runner
└── cli/                           # codeteam inspect-repo/context/eval
```

整体运行关系：

```text
User task
  -> QueryAnalyzer
  -> CandidateGenerator
       -> FilenameIndex
       -> RipgrepClient
       -> SymbolIndex
       -> ImportGraph
       -> test/config/instruction heuristics
  -> FileRanker
  -> RepoMapBuilder
  -> InstructionLoader + CommandDetector
  -> ContextSelector + ContextCompressor
  -> ContextBuildReport
```

Week1 agent loop 和 Week2 context engine 目前是两个相对独立的学习模块。Week1 解决“agent 如何安全执行工具并收束”；Week2 解决“agent 在执行前如何理解仓库并拿到合适上下文”。后续 Week3 会继续接入 Git、Patch、Checkpoint 和更强的安全执行边界。

## Week1: Agent Loop

Week1 的目标是实现一个最小但可靠的 agent 执行闭环。

核心流程：

```text
messages
  -> model_client.complete(messages)
  -> parse tool calls or final output
  -> ToolRegistry.execute(tool_call)
  -> append ToolResult as tool message
  -> check step/tool/repetition/no-progress limits
  -> validate AgentFinalOutput semantics
  -> return AgentLoopResult
```

主要模块：

- `codeteam/agent_loop.py`: 主循环，协调模型、工具、停止条件、事件和用量。
- `codeteam/schemas/messages.py`: 对话消息模型。
- `codeteam/schemas/tool_calls.py`: 工具调用和工具结果模型。
- `codeteam/schemas/final_output.py`: 最终输出结构和语义校验。
- `codeteam/tools/registry.py`: 工具注册与执行。
- `codeteam/tools/files.py`: workspace 内安全文件读写。
- `codeteam/tools/shell.py`: 受控命令执行。
- `codeteam/usage/tracker.py`: token 和成本累计。

Week1 已覆盖的安全/可靠性点：

- 最大步骤数和最大工具调用数。
- 重复工具调用检测，避免无意义循环。
- 无工具调用、无最终结果时返回明确停止原因。
- 模型声称 `completed` 也必须通过最终结果语义校验。
- 工具异常以结构化 `ToolResult` 返回。
- 文件工具限制在 workspace 内，并处理路径越界、符号链接越界、文件大小限制和写前备份。
- Shell 工具使用 `argv` 和 `shell=False`，限制 cwd/env/timeout/output，并阻止危险命令和 `sh -c`、`bash -c`、`python -c` 等字符串执行。

## Week2: Code Context Engine

Week2 的目标是让 agent 能够在代码仓库中找到相关文件，并把它们压缩成可控上下文。

### Repository Indexing

仓库索引由 `codeteam/application/repository_index.py` 统一构建，供 `context` 和 `eval` 复用。

它会生成：

- `RepositorySnapshot`: 仓库文件清单、语言计数、角色分类、重要配置。
- `FilenameIndex`: 文件名和路径 token 索引。
- `SymbolIndex`: Python 符号定义和引用索引。
- `ImportGraph`: 本地模块依赖图。
- `IndexDiagnostics`: 解析/读取/提取失败的 warnings 和 failed files。

`inspect-repo` 命令使用这些信息检查仓库健康状态。

### Retrieval

检索管线由 `QueryAnalyzer`、`CandidateGenerator` 和 `FileRanker` 组成。

`QueryAnalyzer` 会提取：

- 引号内容和精确短语。
- 文件路径。
- snake_case / CamelCase / 异常名 / 错误码。
- 中文片段。
- 小规模中文业务词到英文代码词的 domain expansion。

`CandidateGenerator` 会聚合多路候选：

- explicit path
- filename match
- symbol exact match
- symbol prefix match
- ripgrep full-text search
- import dependency/dependent neighbors
- source/test pair
- important config/instruction files

`FileRanker` 再综合 query match、ripgrep match、symbol match、ImportGraph one-hop/two-hop、PageRank、test relevance、generated/vendor penalty 等权重排序。

### Context Building

`codeteam/application/build_context.py` 将检索结果转成 `ContextBuildReport`。

报告包含：

- analyzed query
- Top K files 和命中理由
- omitted candidates
- Repo Map
- applicable AGENTS instructions
- compressed code context
- detected test/lint/typecheck commands
- diagnostics and failed files
- token budget usage

上下文预算是总预算，不是只约束代码片段。当前实现会让 repo map、instructions 和 code context 共享 `budget_tokens`，并在 1024/256/128/64 等小预算下保持 `tokens_used <= budget_tokens`。

### Instructions And Commands

`instructions/` 负责加载项目规则，例如 AGENTS.md 和 .clinerules。`commands/` 和 `instructions/command_detector.py` 负责从显式指令、pyproject、package.json、Makefile、pytest 配置中检测命令。

优先级原则：

- AGENTS.md 中显式写出的 test/lint/typecheck 命令优先。
- 项目配置推断作为 fallback。
- 命令会保留 source 和 category，便于 context report 说明“为什么推荐这个命令”。

## CLI Usage

查看 CLI 帮助：

```bash
.venv/bin/python -m codeteam.cli.app --help
```

检查仓库索引健康状态：

```bash
.venv/bin/python -m codeteam.cli.app inspect-repo . --format json
.venv/bin/python -m codeteam.cli.app inspect-repo tests/fixtures/test_repo --format json
.venv/bin/python -m codeteam.cli.app inspect-repo tests/fixtures/medium_repo --format json
```

根据任务构建上下文：

```bash
.venv/bin/python -m codeteam.cli.app context \
  "refresh token 异常从 service 层传播到 API 层的完整链路" \
  --path tests/fixtures/test_repo \
  --top-k 5 \
  --budget 1024 \
  --format json
```

运行 Week2 小仓库评测：

```bash
.venv/bin/python -m codeteam.cli.app eval \
  --dataset evals/week2/file_retrieval.jsonl \
  --repo tests/fixtures/test_repo \
  --methods filename,ripgrep,ripgrep_symbol,hybrid \
  --output evals/week2
```

运行 medium_repo 压力评测：

```bash
.venv/bin/python -m codeteam.cli.app eval \
  --dataset evals/medium_repo/file_retrieval.jsonl \
  --repo tests/fixtures/medium_repo \
  --methods filename,ripgrep,ripgrep_symbol,hybrid \
  --output /tmp/codeteam-medium-verify
```

## Evaluation

当前有两层评测材料：

- `evals/week2/file_retrieval.jsonl`: Week2 小型验收数据集，目标是验证主链路、ablation 和 manifest 能跑通。
- `evals/medium_repo/file_retrieval.jsonl`: 更复杂的 medium benchmark，目标是暴露真实检索弱点。

对应 fixture：

- `tests/fixtures/test_repo/`: 小型、可预测、适合 smoke test。
- `tests/fixtures/medium_repo/`: 中等复杂度，包含 auth、orders、inventory、billing、notifications、common、plugins、generated、vendor、docs、configs、AGENTS.md 和一个故意 broken parser case。

注意：medium benchmark 的 JSONL 数据集放在 `evals/medium_repo/`，不放在 `tests/fixtures/medium_repo/` 内部，避免检索器把评测数据文件本身召回。

Week2 最新验收结果：

```text
.venv/bin/python -m pytest -q
450 passed
```

Week2 小仓库 eval：

| Method | Recall@5 | Hit@5 |
|---|---:|---:|
| filename | 0.472 | 0.593 |
| ripgrep | 0.969 | 1.000 |
| ripgrep_symbol | 0.969 | 1.000 |
| hybrid | 1.000 | 1.000 |

medium_repo eval：

| Method | Recall@5 | Hit@5 |
|---|---:|---:|
| filename | 0.325 | 0.400 |
| ripgrep | 0.667 | 0.700 |
| ripgrep_symbol | 0.686 | 0.733 |
| hybrid | 0.653 | 0.700 |

这些结果的含义：

- Week2 小仓库更像验收冒烟，能证明主链路已打通。
- medium_repo 更像压力测试，目前仍暴露 business behavior、cross-module、中文语义和非直接文本匹配的弱点。
- SymbolIndex 在当前小数据集里没有明显拉开 ripgrep，因为很多 symbol case 也能被全文搜索解决。
- ImportGraph 在小数据集中能提升 import_graph 类别，但在 medium_repo 中仍依赖足够好的 seed candidate。

## Development Setup

推荐使用 Python 3.11，与当前验收环境保持一致。

创建环境并安装依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-dev.txt
```

如果系统有多个 Python 版本，请优先使用 `.venv/bin/python` 执行所有项目命令。

## Test Commands

运行全部测试：

```bash
.venv/bin/python -m pytest -q
```

运行部分测试：

```bash
.venv/bin/python -m pytest tests/test_shell_tool.py -q
.venv/bin/python -m pytest tests/context tests/evaluation -q
.venv/bin/python -m pytest tests/search tests/ranking -q
```

`pytest.ini` 会排除 `tests/fixtures/`，避免 fixture 仓库里的示例测试被主项目 pytest 误收集。

## Repository Guide

重要目录：

- `.codex/AGENTS.md`: 当前项目给 Codex/coder 的本地工作约束，要求使用 `.venv/bin/python`。
- `code_review/`: reviewer 日志，包括 Week1 和 Week2 总体 review。
- `evals/`: 评测数据、结果和 Week2 评测报告。
- `tests/fixtures/`: 用于 scanner/retrieval/context 的 fixture 仓库。
- `tests/fixtures/medium_repo_design.md`: medium fixture 的架构设计文档。

重要文档：

- `evals/week2/EVALUATION_WEEK2.md`: Week2 评测报告和复现信息。
- `code_review/week1_review.md`: Week1 review 记录。
- `code_review/week2_overall_review.md`: Week2 总体 review 记录。

## Known Limitations

当前项目仍是学习型实现，不是生产级 coding agent。

已知限制：

- 中文业务语义扩展仍是小规模硬编码映射。
- SymbolIndex 的边际收益需要更强、更干净的评测 case 才能充分衡量。
- medium_repo 显示复杂业务行为和跨模块召回仍不稳定。
- 当前 shell 工具是应用层安全限制，不等价于 Docker/OS sandbox。
- Week1 agent loop 和 Week2 context engine 还没有完全整合成一个端到端真实 coding agent。
- 评测数据仍主要是 Python 仓库，跨语言覆盖不足。

## Roadmap

下一阶段 Week3 的主题是：

```text
Git, Patch, Checkpoint, and safe execution
```

目标分工：

- Git 负责版本状态。
- Worktree 负责任务隔离。
- Checkpoint 负责快速恢复。
- CommandPolicy 负责判断命令意图。
- Sandbox/Docker 负责真正限制执行能力。

Week3 之后，项目可以逐步把 Week1 的 agent loop、Week2 的 context engine、Week3 的 Git/Patch/Checkpoint 安全执行流程接成更完整的 coding agent。
