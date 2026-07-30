# Agent-Learning

`week1` 分支完成了一个最小可测试的 coding agent 基础框架：用 Pydantic 定义消息、工具调用、工具结果和最终输出模型；实现工具注册器、calculator、文件工具和受控 Shell 工具；补齐 Mock LLM、Agent Loop、停止条件、事件记录、错误分类、重试判断、token 用量与成本统计。当前重点不是接入真实模型，而是把 “模型输出 -> 工具执行 -> 停止条件 -> 最终结果校验” 这条主链路搭起来，并通过单元测试保证 Agent 不会无限循环、不会重复执行相同动作、不会在验证失败时错误标记完成。

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

## Executable Commands

当前项目没有独立 CLI 或可执行入口，主要通过 Python 模块导入和测试来运行。可以用下面的方式创建环境并安装依赖：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install "pydantic==2.13.4"
```

如果本机没有 `python3.11`，Python `3.12` 也可以运行当前代码；建议团队统一到 Python 3.11。

## Test Commands

运行全部测试：

```bash
.venv/bin/python -m unittest discover tests
```

运行指定模块测试：

```bash
.venv/bin/python -m unittest tests/test_agent_loop_stop_conditions.py
.venv/bin/python -m unittest tests/test_file_tools.py
.venv/bin/python -m unittest tests/test_shell_tool.py
```

## Week1 Acceptance Highlights

- Agent Loop 有最大步骤和工具调用预算，不会无限循环。
- 连续重复相同工具名和参数会被阻止。
- 模型没有给出工具调用或最终结果时会停止并返回明确原因。
- 模型声称 `completed` 也必须通过真实验证结果校验。
- 工具错误会以结构化 `ToolResult` 返回，不会让 Agent 直接崩溃。
- 文件工具和 Shell 工具都限制在 workspace 内，避免越界访问。
