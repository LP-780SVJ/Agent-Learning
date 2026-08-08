# Agent-Learning

`Agent-Learning` 是一个学习型 coding agent 框架。Week1 搭好了 “模型输出 -> 工具执行 -> 停止条件 -> 最终结果校验” 主链路；Week2 增加了仓库扫描、解析、符号索引、ImportGraph、代码检索、Repo Map、Context 构建、CLI 和文件检索 eval。

所有开发和验收命令都必须使用项目虚拟环境：`.venv/bin/python`。不要使用系统默认 `python3` 跑测试或 CLI。

## Code Framework

```text
codeteam/
├── agent_loop.py              # Agent 主循环：解析模型输出、执行工具、处理停止条件、记录事件和用量
├── state.py                   # AgentLoopState、StopReason、重复动作指纹
├── limits.py                  # AgentLoopLimits、最大步骤/工具调用预算检查
├── events.py                  # AgentEvent、AgentEventType、事件构造
├── errors.py                  # AgentError、ErrorCategory、异常分类与重试判断
├── schemas/
│   ├── messages.py            # Message
│   ├── tool_calls.py          # ToolCall、ToolResult
│   └── final_output.py        # CompletionStatus、AgentFinalOutput、最终输出语义校验
├── tools/
│   ├── base.py                # RegisteredTool
│   ├── registry.py            # ToolRegistry
│   ├── calculator.py          # calculator 工具
│   ├── files.py               # list_files/read_file/write_file/search_code
│   └── shell.py               # run_command，受控 subprocess 工具
├── llm/
│   ├── base.py                # ModelResponse
│   ├── mock.py                # MockModelClient
│   └── openai_compatible.py   # 预留真实模型接入位置
└── usage/
    ├── pricing.py             # 模型价格与单次成本计算
    └── tracker.py             # 多步 token/cost 统计

tests/
├── test_agent_loop_*.py       # Agent Loop 停止条件、重复动作、事件和用量测试
├── test_file_tools.py         # 安全文件工具测试
├── test_shell_tool.py         # 受控 Shell 工具测试
├── test_tool_*.py             # 工具模型、calculator、registry 测试
├── test_final_output_*.py     # 最终输出结构/语义校验测试
├── test_error_classification.py
├── test_retry.py
├── test_pricing.py
└── test_usage_tracker.py
```

## Main Components

### Data Models

- `Message`：表示 `system/user/assistant/tool` 四类对话消息。
- `ToolCall`：表示模型请求执行的工具名和参数。
- `ToolResult`：表示工具执行后的结构化结果，包含 `success/content/error`。
- `AgentFinalOutput`：表示模型最终回答的统一出口。
- `CompletionStatus`：用枚举表达 `completed/failed/needs_user_input`，避免到处比较裸字符串。

### Tool System

- `RegisteredTool`：统一描述一个工具的名称、说明、参数 schema 和执行函数。
- `ToolRegistry`：负责注册工具，并把 `ToolCall` 执行为 `ToolResult`。
- `calculator`：基础算术工具。
- `files.py`：安全读写 workspace 内文件，包含路径越界检查、符号链接越界检查、文件大小限制和写前备份。
- `shell.py`：受控执行命令，强制 `shell=False`、`argv` 参数、workspace 内 `cwd`、timeout、输出截断、环境变量白名单，并禁止 `sudo`、`git push` 等危险命令。

### Agent Loop

`run_agent_loop` 是 week1 的主控流程：

```text
messages
  -> model_client.complete(messages)
  -> 解析为工具调用或 AgentFinalOutput
  -> 工具调用交给 ToolRegistry.execute()
  -> ToolResult 转回 tool Message
  -> 检查最大步骤、工具调用预算、重复动作、无进展输出
  -> 只有 final output 通过结构校验和语义校验后才允许 completed
```

停止结果由 `AgentLoopResult` 返回，包含 `status`、`stop_reason`、`messages`、`final_output`、`error`、`steps_used`、`tool_calls_used`、事件列表、token 用量、成本和耗时。

## Development Setup

创建环境并安装依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-dev.txt
```

## Test Commands

运行全部测试：

```bash
.venv/bin/python -m pytest -q
```

运行部分测试：

```bash
.venv/bin/python -m pytest tests/search tests/ranking -q
.venv/bin/python -m pytest tests/test_shell_tool.py -q
```

## CLI Usage

检查仓库索引健康状态：

```bash
.venv/bin/python -m codeteam.cli.app inspect-repo . --format json
.venv/bin/python -m codeteam.cli.app inspect-repo tests/fixtures/test_repo --format json
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

运行 Week2 文件检索评测：

```bash
.venv/bin/python -m codeteam.cli.app eval \
  --dataset evals/week2/file_retrieval.jsonl \
  --repo tests/fixtures/test_repo \
  --methods filename,ripgrep,ripgrep_symbol,hybrid \
  --output evals/week2
```

Week2 eval fixture 位于 `tests/fixtures/test_repo/`，数据集和报告位于 `evals/week2/`。
Medium benchmark 的被检索仓库位于 `tests/fixtures/medium_repo/`，数据集位于仓库外的 `evals/medium_repo/file_retrieval.jsonl`，避免 eval JSONL 被检索器当成候选文件。

## Week1 Acceptance Highlights

- Agent Loop 有最大步骤和工具调用预算，不会无限循环。
- 连续重复相同工具名和参数会被阻止。
- 模型没有给出工具调用或最终结果时会停止并返回明确原因。
- 模型声称 `completed` 也必须通过真实验证结果校验。
- 工具错误会以结构化 `ToolResult` 返回，不会让 Agent 直接崩溃。
- 文件工具和 Shell 工具都限制在 workspace 内，避免越界访问。
