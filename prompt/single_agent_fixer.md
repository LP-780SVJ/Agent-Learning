# CodeTeam Week4 SingleAgent 第一刀半修复：Verification Environment Contract / Toolchain Preflight

## 角色

你现在是 **CodeTeam / Coding Agent Runtime 的代码修改工程师**。

你的任务不是继续修改 Native Tool Calling，也不是开始 Completion State Machine，而是修复当前 SingleAgent 在第一刀完成以后暴露出来的下一个真实阻塞点：

> **Runtime 要求 Agent 执行某些 verification commands，但当前 Docker verification environment 并不保证具备执行这些命令所需的工具链。**

本次修复称为：

```text
SingleAgent 第一刀半
Verification Environment Contract
```

必须基于当前 `week4` 分支最新代码进行修改。

---

# 一、仓库与目标分支

仓库：

```text
https://github.com/LP-780SVJ/Agent-Learning
```

分支：

```text
week4
```

开始前必须阅读当前最新：

```text
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
README.md
```

重点排查：

```text
codeteam/sandbox/
codeteam/execution/
codeteam/verification/
codeteam/agent/
codeteam/evaluation/
codeteam/cli/

tests/sandbox/
tests/execution/
tests/verification/
tests/agent/
tests/evaluation/
```

尤其定位真实：

```text
DockerSandboxPreflight
DockerRunner
SandboxProfile
SafeExecutionService
RuntimeToolbox / run_tests
CodingAgentRunRequest
AgentEvalRunner
AgentGrader
verification command formatting
failure classification
environment blocked classification
```

---

# 二、上一刀已经解决的问题

上一刀已经完成：

```text
ModelRequest
↓
Provider Adapter
↓
ModelTurn
↓
native tool_calls
↓
Runtime ToolCall
↓
SafeExecutionService
```

最新 B01 执行已经证明：

```text
native_tools_actual = true
response_mode_actual = native_tools
protocol_repair_attempt_count = 0
protocol_failed_count = 0
```

并且模型已经通过 native tool calling 成功：

```text
read_file
↓
apply_patch
↓
真实 Git diff
```

正确修改：

```python
except RefreshTokenExpired:
    return {"status": 401, "error": "internal server error"}
```

为：

```python
except RefreshTokenExpired as exc:
    return {"status": 401, "error": str(exc)}
```

外部 Grader 最终得到：

```text
task verification passed
regression passed
hidden acceptance passed
security passed
```

因此本次**禁止重新处理**：

```text
ModelRequest
ModelTurn
Native Tool Calling
Provider Action Transport
JSON / DSML codec
```

除非真实代码存在与本次 verification environment 修改直接相关的小范围兼容需求。

---

# 三、这次真实失败过程

最新 B01 中，Agent 正确修改代码后执行 Runtime 明确要求的：

```bash
python -m pytest tests/task_verification/test_b01.py -q
```

以及：

```bash
python -m pytest tests/auth -q
```

Docker 内部实际返回：

```text
/usr/local/bin/python: No module named pytest
```

注意：

这不是：

```text
pytest assertion failed
```

而是：

```text
pytest 根本无法启动
```

因此这是：

```text
Verification Environment Failure
```

而不是：

```text
Task Verification Failure
```

---

# 四、后续为什么变成 repeated_action

Agent 看到：

```text
No module named pytest
```

之后根据仓库 `AGENTS.md` 中发现的：

```bash
uv run pytest ...
```

尝试改用：

```bash
uv run pytest tests/task_verification/test_b01.py -q
```

Runtime 拒绝：

```text
Command is not in the task's visible verification commands.
```

因为当前 `run_tests` 对 verification command 使用 exact allowlist。

之后 Agent 再次执行：

```bash
python -m pytest ...
```

仍然：

```text
No module named pytest
```

最终才触发：

```text
REPEATED_ACTION
```

所以真实因果链是：

```text
correct patch
↓
required verification
↓
Docker lacks pytest              ← root cause
↓
verification command cannot run
↓
Agent tries uv
↓
exact command contract rejects
↓
Agent retries required command
↓
same environment failure
↓
REPEATED_ACTION                  ← secondary symptom
```

本次不要把 `REPEATED_ACTION` 当作根因。

---

# 五、本次核心问题定义

当前：

```text
Verification Command
        │
        │ "python -m pytest ..."
        ↓
Docker Sandbox
        │
        └── python ✓
            pytest ✗
```

说明：

> **Verification Command 和 Verification Environment 当前是两套彼此独立的配置，没有明确 compatibility invariant。**

目标设计应该是：

```text
Verification Contract
        │
        ├── argv
        ├── cwd
        └── required runtime capabilities
                    │
                    ↓
        Verification Environment
                    │
          ┌─────────┴─────────┐
          ↓                   ↓
      command exists      dependencies exist
```

只有满足：

```text
Environment supports Verification Contract
```

Agent 才允许进入真实模型执行阶段。

---

# 六、本次修改目标

本次只解决以下四件事情：

```text
1. Docker verification environment
   必须能够执行当前 B01 / Week4 Python Runtime 指定的 required
   verification command。本轮只证明 Python + pytest 这一最小 contract，
   不得把结论扩大成支持任意语言或任意项目依赖。

2. Preflight
   不再只验证 Docker 是否能启动，
   还必须验证 verification toolchain 是否可用。

3. Failure classification
   verification environment 不满足时，
   必须识别成 environment blocked / infrastructure failure，
   而不是普通 test failure 或最终 repeated_action。

4. Runtime / Grader verification contract
   明确二者虽然运行在不同环境，
   但必须满足同一个 logical verification contract。
```

---

# 七、非常重要的范围限制

## 本次禁止执行 B01

**不要运行：**

```text
B01
agent-eval --task-id B01
任何真实 LLM B01 smoke
```

B01 由用户本人在修改完成后亲自运行。

你只负责：

```text
代码修改
单元测试
integration tests（不调用真实 LLM，不跑 B01）
regression tests
Design Decision
Failure Case
```

---

# 八、本次禁止 Benchmark

不得运行：

```text
11-task benchmark
agent-eval baseline
agent-eval ablations
任何 benchmark suite
任何性能 benchmark
```

本次不存在 Benchmark 数字。

如果需要更新文档中的 Benchmark：

只能写：

```text
Pending user-run B01 validation.
```

不得编造结果。

---

# 九、第一步：先检查真实代码

正式修改前，先输出：

```text
涉及文件
当前 Docker image/profile
当前 Docker preflight 做什么
当前 run_tests 如何进入 Docker
verification command 在哪里定义
Runtime 中 {python} 如何格式化
Grader 中 {python} 如何格式化
environment_blocked 当前如何判定
```

并明确：

> 本提示词描述与当前真实代码是否完全一致。

若代码已经部分调整，必须以最新代码为准。

---

# 十、不要把 Sandbox Preflight 和 Verification Preflight 混成一个概念

当前类似：

```text
DockerSandboxPreflight
→ test -d /workspace
```

只能证明：

```text
Docker CLI available
Docker daemon available
image starts
workspace mount works
```

这属于：

```text
Sandbox Infrastructure Preflight
```

应该保留。

不要简单把它改成“运行 pytest”。

正确设计应区分：

```text
Layer 1
Sandbox Infrastructure Preflight

Layer 2
Verification Environment Preflight
```

例如：

```text
SandboxPreflight
    ↓
Docker / image / mount available

VerificationEnvironmentPreflight
    ↓
required interpreter / executable / module available
```

不要让一个 `DockerSandboxPreflight` 类开始理解所有语言和测试框架。

---

# 十一、Verification Environment Preflight

需要新增或复用适当 abstraction 表达：

```text
当前 verification commands
        ↓
提取 required capabilities
        ↓
检查 Docker environment
```

对于当前 Week4 Python benchmark，最小需求至少包括：

```text
python executable available
pytest importable / executable
```

例如 capability probe 可以等价于：

```bash
python -m pytest --version
```

如果实现选择 `python -c "import pytest"`，必须明确它是由 Runtime 固定构造、
不可被 Agent 修改的可信基础设施 probe。现有 CommandPolicy 会拒绝 Agent 发出的
`python -c`，不得为了 probe 放宽该安全规则。

边界必须写清：

```text
Verification Environment Preflight
→ Runtime-owned fixed probe
→ 可以直接使用注入的 SandboxRunner / DockerRunner
→ argv 不接受模型或任务文本的任意输入

Agent run_tests
→ 仍然必须经过 SafeExecutionService
→ 仍然受 CommandPolicy、Sandbox 和 exact verification allowlist 约束
```

注意：

**不能在 preflight 阶段运行真实 B01 pytest。**

因为 pristine fixture 的 task test 本来就可能失败。

Preflight 检查的是：

```text
Can verification run?
```

不是：

```text
Does verification pass?
```

---

# 十二、不要现在造通用 Dependency Provisioning System

当前不要新增：

```text
PackageInstaller
DynamicDependencyResolver
EnvironmentBuilder
LanguageRuntimeManager
UniversalToolchainManager
```

这些都属于过度设计。

本次需要购买的能力只是：

> **在 Agent 消耗模型 token 之前，确认当前 Sandbox 能执行本任务要求的 verification commands。**

如果当前 Week4 任务全部主要使用：

```text
python -m pytest
```

那么先把这一条 contract 做正确。

以后出现 Node / Java / Rust 再扩展 capability detection。

---

# 十三、Docker Verification Image

当前仓库只有默认 image 名称：

```text
codeteam-sandbox:latest
```

但没有仓库内可复现的 Dockerfile。用户已经授权本轮把 verification image
纳入项目管理，因此不能只修改本机已有 image，也不能依赖人工进入容器安装包。

本轮必须新增最小、可审计的 image build 定义。默认路径使用：

```text
docker/sandbox/Dockerfile
docker/sandbox/requirements.txt
```

如果当前仓库真实结构存在更合适且已建立的路径，可以沿用，但必须在最终报告中
解释选择。不得创建第二套重复的 image 配置。

目标至少保证：

```text
python
pytest
```

可用。

Dockerfile / requirements 必须至少做到：

```text
明确 Python 3.11 的具体基础镜像版本；条件允许时固定 image digest
pytest 使用精确版本，不使用无上限的 latest
不复制 host .venv
不在运行任务时联网安装依赖
不默认加入与当前 Python verification contract 无关的工具链
```

必须提供并核对本地构建命令，例如：

```bash
docker build -t codeteam-sandbox:latest -f docker/sandbox/Dockerfile docker/sandbox
```

允许 Coder 在 Docker daemon 可用时构建该镜像并运行 Sandbox/Preflight integration
tests；这不属于 B01 或 benchmark。若执行环境无法访问 Docker，必须真实记录为
环境阻塞，不得声称镜像边界已经验证，也不得退回 host shell。

不要为了当前 B01 安装：

```text
大量无关 Python package
全项目 requirements-dev.txt
各种语言工具链
```

除非真实 11-task suite 的 verification contract 已经明确要求。

Preflight 和 Runtime metadata / manifest 至少记录：

```text
configured image tag
实际 image ID 或 digest（可获得时）
Python version
pytest version
verification preflight result/category
```

`requirements-dev.txt` 当前没有固定 pytest 版本，不能直接把它作为可复现的
Sandbox lock。Docker verification requirements 应保持最小并精确固定。

本轮 limitation 必须如实写明：当前只保证 B01 / Week4 Python 测试所需的
Python + pytest；任务仓库未来增加的第三方运行依赖仍需要后续显式环境契约，
本轮不实现通用依赖解析或动态 provisioning。

---

# 十四、Host `.venv` 不能直接塞给 Docker Runtime

禁止采用：

```text
mount host .venv into Docker
```

或：

```text
让 Docker 执行 host 的 .venv/bin/python
```

原因：

```text
破坏 sandbox isolation
host/container ABI 可能不同
macOS host venv 无法直接在 Linux container 使用
benchmark reproducibility 变差
```

Runtime Docker 必须拥有自己的 verification toolchain。

---

# 十五、Runtime 与 Grader 的 `{python}` contract

当前需要重点检查：

```text
AgentEvalRunner
AgentGrader
```

如果真实代码仍然存在：

```text
Runtime:
{python} → "python"

Grader:
{python} → project/.venv/bin/python
```

那么不要简单认为这是错误。

因为：

```text
Runtime
→ Docker

Grader
→ trusted host
```

本来就可以使用不同物理 Python。

真正要求是：

> **它们必须满足同一个 logical verification contract。**

例如：

```text
Runtime verification environment
Python X
pytest Y

Grader trusted environment
Python compatible X
pytest compatible Y
```

至少在 manifest / runtime metadata 中留下足够证据，未来出现：

```text
Runtime fail
Grader pass
```

时能够判断是否环境 drift。

不要为了强行物理统一而破坏 Docker isolation。

---

# 十六、Verification Environment Failure Classification

当前：

```text
python -m pytest
→ No module named pytest
→ exit code 1
```

被当成普通：

```text
VerificationResult(passed=False)
```

然后继续反馈给 Agent。

这不够。

需要区分至少：

```text
TEST_FAILED
```

和：

```text
VERIFICATION_ENVIRONMENT_FAILED
```

例如：

```text
pytest started
tests failed
→ TEST_FAILED

python cannot import pytest
executable missing
environment incapable of running required command
→ VERIFICATION_ENVIRONMENT_FAILED
```

失败命名应优先复用项目现有概念：

```text
environment_blocked
sandbox_unavailable
typed Failure / AgentErrorCode（仅在当前调用链已接入时）
```

但是当前 `CodingAgentRuntime` 不经过旧 Orchestrator 的 `ErrorClassifier /
RecoveryPolicy` 链路。不得为了形式上的复用把新 Runtime 重新耦合到旧
Orchestrator，也不得让 preflight failure 进入 RecoveryPolicy。

推荐保持两级表达：

```text
top-level runtime/eval category:
environment_blocked 或当前兼容的 sandbox_unavailable

specific preflight category:
verification_toolchain_unavailable
python_unavailable
pytest_unavailable
```

可以扩展现有 `SandboxPreflightResult` 或增加极小的 verification check model，
但不能再造一套覆盖整个 Agent 的 failure taxonomy。

---

# 十七、Fail Fast

如果 verification environment preflight 失败：

必须在真实 LLM Provider 调用前停止。

目标 invariant：

```text
verification environment unavailable
        ↓
provider calls = 0
agent steps = 0
agent tool calls = 0
```

返回明确：

```text
environment blocked
```

或项目现有等价状态。

不能让 Agent 自己去发现：

```text
pytest not installed
```

因为这是 Runtime 已经可以提前知道的环境事实。

---

# 十八、不要让 Agent 修 Infrastructure Failure

如果 verification command 无法启动：

不要进入：

```text
repair loop
replan
repeated test retry
```

因为：

```text
No module named pytest
```

不是 source patch 可以修复的 task failure。

原则：

```text
Code failure
→ Agent repair

Environment failure
→ Runtime stop / environment blocked
```

这是本次必须建立的边界。

---

# 十九、关于 `uv run pytest`

当前 Agent 根据 AGENTS.md 尝试：

```bash
uv run pytest ...
```

属于合理推理。

但是本次不要简单放宽：

```text
run_tests accepts any repository-detected command
```

当前 benchmark/task-specific verification commands 是 authoritative completion contract。

优先保留：

```text
task_verification_commands
regression_commands
```

的 exact execution contract。

然后修好 Runtime environment，使：

```bash
python -m pytest ...
```

真正可执行。

---

# 二十、Prompt 中的命令冲突

如果当前 system/user prompt 同时给模型：

```text
Repository:
uv run pytest tests/ -q

Runtime required:
python -m pytest specific-test -q
```

需要做最小澄清。

不要删除仓库 discovered commands。

但应该明确类似：

```text
For completion-required verification, use the task-specific verification commands supplied by the Runtime.
Repository-discovered commands are general project guidance and are not substitutes for required completion commands unless explicitly allowed.
```

避免 Agent 在 infrastructure failure 后误认为：

```text
uv command
```

可以替换 authoritative verification command。

本次只做必要说明，不重构整个 Prompt。

---

# 二十一、不要修改 Repeated Action 逻辑来掩盖问题

这次严禁通过：

```text
增加 repeated action threshold
允许相同 pytest 重跑 N 次
关闭 repeated action detection
```

来让 B01 “跑得更久”。

因为当前相同 command：

```text
python -m pytest
```

重复执行仍然只会得到：

```text
No module named pytest
```

Repeated Action 是次生症状。

修复 environment 后，这一 failure chain 自然应该消失。

---

# 二十二、Completion State Machine 仍然不要动

此前已经确认另一个独立问题：

```text
patch correct
tests pass
diff reviewed
↓
Runtime 已有完成证据
↓
仍要求模型主动 final
```

这属于：

```text
第二刀：
Runtime Completion Ownership
READY_TO_FINALIZE
```

本次明确禁止：

```text
新增 READY_TO_FINALIZE
修改 submit_result
改变 completion ownership
修改 final handshake
重写 repeated-action completion semantics
```

除非本次改动必须进行非常小的兼容性调整。

---

# 二十三、建议的数据模型

是否新增 abstraction 由真实代码决定。

如果需要新增：

```text
VerificationEnvironmentRequirement
VerificationEnvironmentCheck
VerificationCapability
```

必须保持极小。

例如概念上只需要：

```text
required executable/module
check result
failure reason
```

不要变成通用 workflow engine。

新增 abstraction 必须回答：

> 这个复杂度购买了什么能力？

答案应该是：

```text
fail-fast verification environment validation
```

如果不能回答，就不要增加。

---

# 二十四、建议 Preflight 流程

真实 Eval + Runtime 生命周期应描述为：

```text
AgentEval Task
    ↓
prepare pristine workspace
    ↓
trusted-host pristine public/hidden oracle checks
    ↓
prepare task repo + linked worktree
    ↓
CodingAgentRuntime
    ↓
Sandbox Infrastructure Preflight
    │
    ├── Docker daemon
    ├── image
    └── mount
    ↓
Verification Environment Preflight
    │
    ├── python available
    └── pytest importable
    ↓
Provider call
```

Pristine oracle 当前由 `AgentEvalRunner` 在进入 Runtime 前通过 trusted host
执行；不要为了调整图示而搬动 Grader 生命周期或把 hidden oracle 暴露给 Runtime。
产品 `codeteam run` 没有 pristine oracle，但仍必须在 Provider 前完成两个 preflight。

核心 invariant：

> **Provider call 之前必须知道 verification command 能否启动。**

---

# 二十五、测试要求

本次测试必须重点覆盖行为，而不是对象能否构造。

## A. Sandbox infrastructure available + pytest available

Fake/controlled environment：

```text
Docker available
python available
pytest available
```

结果：

```text
verification environment ready
```

成功结果还必须包含可审计 metadata：

```text
configured image
image id/digest（runner 能取得时）
python version
pytest version
probe argv
```

---

## B. Docker available + pytest missing

模拟：

```text
test -d /workspace succeeds
python -m pytest --version fails
```

必须：

```text
Sandbox infrastructure = available
Verification environment = unavailable
```

不能混淆两者。

---

## C. Missing Python

模拟：

```text
python executable unavailable
```

必须归类：

```text
verification environment failure
```

---

## D. Preflight failure before provider call

使用 FakeModelClient / spy。

验证：

```text
verification environment unavailable
```

时：

```text
model.complete invocation count = 0
```

这是核心测试。

---

## E. Environment failure 不进入 Repair

Spy/fake 验证：

```text
repair agent invocation = 0
```

---

## F. Environment failure 不演化成 Repeated Action

验证 fail-fast 后：

```text
StopReason != REPEATED_ACTION
```

并且产生明确 environment failure。

---

## G. Real test failure 仍属于 task verification failure

模拟 pytest 正常启动：

```text
1 failed
```

必须继续是：

```text
test/verification failure
```

不能误判成 environment blocked。

---

## H. pytest module missing

模拟 stderr：

```text
No module named pytest
```

必须正确归到 environment failure。

不要只测试 executable-not-found。

---

## I. Prompt contract

如果修改 prompt：

测试 required command 与 discovered AGENTS command 同时存在时，模型可见信息明确：

```text
task-specific command authoritative
```

---

## J. Grader regression

不得改变：

```text
AgentGrader
hidden acceptance
public regression
security gate
```

的判定语义。

只允许补充环境 metadata / contract 信息。

---

## K. Reproducible image contract

至少覆盖：

```text
Dockerfile 与最小 requirements 文件存在
pytest 使用精确版本
image build context 不包含 host .venv、secrets.local.env 或整个无关仓库
Runtime 与 Verification Preflight 使用相同 configured image
Runtime 不在任务执行期间 pip install / pull / 自动重建 image
```

如果 Docker daemon 可用，运行真实 image build + capability probe integration test。
如果 daemon 不可用，纯单元测试仍必须通过，真实 integration 明确 conditional skip，
并在最终报告列出 skip 原因；不得把 skip 写成真实边界通过。

---

# 二十六、Integration Test

增加一个不调用真实 Provider、不运行 B01 的 integration test。

例如：

```text
Fake task
required verification:
python -m pytest some_test.py
```

### Case 1

Sandbox preflight：

```text
Docker OK
pytest missing
```

验证：

```text
task stops before FakeModelClient
environment_blocked = true
```

### Case 2

Sandbox：

```text
Docker OK
pytest available
```

FakeModelClient 才允许收到请求。

不要使用真实 DeepSeek/OpenAI。

---

# 二十七、本次允许执行的测试

允许运行项目内相关 pytest，例如：

```bash
.venv/bin/python -m pytest tests/sandbox -q
.venv/bin/python -m pytest tests/execution -q
.venv/bin/python -m pytest tests/verification -q
.venv/bin/python -m pytest tests/agent -q
.venv/bin/python -m pytest tests/evaluation -q
```

根据实际修改文件选择 touched-module tests。

本次修改横跨 Sandbox、Execution、Runtime 和 Evaluation，触达测试通过以后必须运行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check <本轮触达路径>
.venv/bin/python -m mypy --follow-imports=skip <本轮触达路径>
git diff --check
```

`<本轮触达路径>` 必须替换为真实路径，不得把占位符原样执行。全量 pytest 不是
“若时间允许”；没有跑完必须将任务结论标记为未完成或被环境阻塞。

如果 Docker daemon 可用，还必须执行真实但不含 LLM 的验证：

```bash
docker build -t codeteam-sandbox:latest -f docker/sandbox/Dockerfile docker/sandbox
.venv/bin/python -m pytest tests/sandbox -q -rs
```

上述命令只验证 Sandbox image 和边界，不执行 B01、Agent Eval 或 benchmark。

注意：

```text
这里的 pytest 是 CodeTeam 自身测试，
不是 B01 Agent Eval。
```

---

# 二十八、明确禁止执行的命令

不要运行任何类似：

```bash
.venv/bin/python -m codeteam.cli.app agent-eval \
  --task-id B01 ...
```

不要运行：

```text
agent-eval baseline
agent-eval ablations
11-task suite
任何真实 provider smoke
```

即使你认为修改已经完成，也不要执行。

最终必须告诉用户：

```text
B01 ready for user validation
```

并提供一条已经通过当前 CLI help / 参数定义核对的完整 B01 命令，但不得执行它。
命令必须包含：

```text
--task-id B01
--actor llm
--mode baseline
--native-tools
--no-reasoning
--worktree-root "$HOME/.codeteam/worktrees"
--keep-workspaces
独立的 timestamp output directory
```

不得读取、打印或写入用户 API key。可以提示用户在自己的终端加载
`secrets.local.env`，但不能展示 secret 内容。

最终交给用户的命令模板应保持为：

```bash
RUN_DIR="evals/week4/agent_runs/verification_contract_b01_$(date +%Y%m%d_%H%M%S)"
.venv/bin/python -m codeteam.cli.app agent-eval \
  --suite evals/week4/agent_task_suite_v1.jsonl \
  --output "$RUN_DIR" \
  --actor llm \
  --mode baseline \
  --task-id B01 \
  --context-budget 8192 \
  --max-output-tokens 4096 \
  --model-context-window 32768 \
  --safety-headroom-tokens 1024 \
  --native-tools \
  --no-reasoning \
  --worktree-root "$HOME/.codeteam/worktrees" \
  --keep-workspaces
```

如果实现期间 CLI 参数发生了必要变化，必须同步更新该模板和 README，并在最终
报告解释；不得为了让命令可运行而扩大本轮功能范围。

---

# 二十九、Design Decision

完成后新增或更新 DD。

至少包括：

```text
Problem
Alternatives
Decision
Invariant
Trade-offs
Verification
Limitations
Interview Version
```

核心 Problem：

```text
The Runtime required verification commands that its Docker environment was not guaranteed to support.
```

Decision 应体现：

```text
Sandbox availability
!=
Verification environment readiness
```

以及：

```text
Verification environment must be validated before provider execution.
```

除新增或更新对应 DD 外，本轮必须同步维护以下持续文档：

```text
README.md
learning-plan/单Agent执行闭环修复记录.md
learning-plan/代码架构.md
learning-plan/设计决策.md
```

更新要求：

```text
README.md
→ image build 命令、preflight 行为、B01 用户命令、环境阻塞状态

单Agent执行闭环修复记录.md
→ 追加“正确 patch → Docker 无 pytest → repeated_action”故事线、根因、修复与待验证状态

代码架构.md
→ 补充 Infrastructure Preflight、Verification Preflight、run_tests 和 Grader 的真实函数链与参数

设计决策.md
→ 记录 project-owned pinned image、trusted fixed probe、fail-fast、Runtime/Grader logical contract
```

所有文档都必须如实标记：

```text
B01: NOT_RUN_BY_CODER / pending user validation
11-task benchmark: NOT_RUN
ablation: NOT_RUN
Completion Ownership: pending
```

---

# 三十、Alternatives 必须讨论

至少比较：

### Alternative A

让 Agent 自己发现 pytest 不存在并恢复。

拒绝原因：

```text
浪费 token
Agent 无法可靠修 infrastructure
污染 failure classification
```

### Alternative B

允许 Agent 自动改用 `uv run pytest`。

拒绝/暂缓原因：

```text
会破坏 authoritative task verification command
且不能保证 Docker 有 uv
```

### Alternative C

mount host `.venv`。

拒绝原因：

```text
sandbox / ABI / reproducibility
```

### Alternative D

Verification Environment Preflight + pinned toolchain。

当前 Decision。

---

# 三十一、Failure Case

新增本次真实 Failure Case：

```text
Correct patch generated and applied
↓
Runtime executes required python -m pytest
↓
Docker Python has no pytest module
↓
Agent attempts repository-recommended uv command
↓
Runtime exact verification allowlist rejects it
↓
Agent retries required command
↓
Repeated action
↓
Actor marked failed
↓
External grader later proves patch is actually correct
```

Root Cause 写：

> Runtime verification commands and the sandbox verification environment did not share an explicit compatibility contract.

不要写：

```text
Agent chose the wrong command.
```

也不要写：

```text
Repeated action was the root cause.
```

---

# 三十二、Benchmark / Ablation

本次：

```text
不执行 Benchmark
不执行 B01
不执行 Ablation
```

Design Decision 中可以写后续验证计划：

```text
Pending user-run B01 validation.
```

不得填写：

```text
success rate
latency improvement
token savings
```

除非已有真实单元测试数据能支持对应陈述。

---

# 三十三、修改完成后的汇报格式

完成后必须按以下结构回答。

## 1. Root Cause Confirmation

说明：

```text
当前 Docker 缺什么
当前 preflight 为什么没发现
当前 Runtime / Grader verification contract 是否存在差异
当前 environment failure 如何被错误分类
```

---

## 2. Files Changed

逐项：

```text
path
修改内容
为什么需要修改
```

新增文件必须说明：

> 为什么不能复用已有模块？

---

## 3. New Verification Lifecycle

画出修改后的真实链路：

```text
Task
↓
Sandbox Infrastructure Preflight
↓
Verification Environment Preflight
↓
Provider
↓
CodingAgentRuntime
↓
run_tests
↓
Docker
```

---

## 4. Invariants

明确列出：

```text
Environment incapable of running required verification
→ Provider invocation count = 0

Environment failure
→ Not a test assertion failure

Environment failure
→ No repair/replan loop

Runtime verification command
→ Supported by configured sandbox environment
```

---

## 5. Compatibility

说明是否影响：

```text
CLI run
Agent Eval
Grader
SafeExecutionService
Docker Sandbox
Native Tool Calling
Session
```

---

## 6. Tests

列出：

```text
测试文件
case
执行命令
真实结果
```

---

## 7. B01

只能写：

```text
B01 was NOT executed by the coder.
Ready for user-run validation.
```

不要声称 B01 成功。

---

## 8. Benchmark

必须写：

```text
Benchmark was NOT executed.
```

---

## 9. Design Decision

给出 DD 路径和核心 Decision。

---

## 10. Failure Case

给出 failure case 路径。

---

## 11. Remaining Issue

明确：

```text
Completion Ownership / READY_TO_FINALIZE
```

仍然 pending。

本次不要声称 SingleAgent 已完全修复。

---

# 三十四、本次最终验收标准

只有同时满足以下条件才算完成：

```text
[ ] Sandbox infrastructure preflight 与 verification environment preflight 已分开

[ ] Runtime 能在模型调用前确认 required verification toolchain 是否存在

[ ] python/pytest 缺失能够被识别为 environment failure

[ ] environment failure 时 provider invocation = 0

[ ] environment failure 不进入 repair loop

[ ] environment failure 不最终伪装成 repeated_action

[ ] 正常 pytest assertion failure 仍属于 task verification failure

[ ] 仓库内存在最小、版本固定、可复现构建的 Sandbox Dockerfile/requirements

[ ] Runtime Docker verification environment 确实提供 required pytest toolchain

[ ] Preflight metadata 能说明 configured image、Python/pytest version 和失败 category

[ ] 没有 mount host .venv 到 Docker

[ ] 没有通过放宽 run_tests allowlist 掩盖问题

[ ] AGENTS discovered command 与 authoritative task verification command 的优先级已澄清

[ ] Runtime / Grader logical verification contract 已明确

[ ] Native Tool Calling 第一刀没有回归

[ ] Agent run_tests / patch lane 没有绕过 SafeExecutionService；只有不可由 Agent
    控制 argv 的固定基础设施 preflight 可以直接使用注入的 SandboxRunner

[ ] 触达测试、全量 pytest、触达范围 Ruff/Mypy 和 git diff --check 已真实执行

[ ] Docker daemon 可用时已完成 image build 与真实 Sandbox integration；不可用时已明确记录 skip/block

[ ] README、单Agent执行闭环修复记录、代码架构、设计决策和对应 DD 已同步更新

[ ] Failure Case 已记录

[ ] coder 没有执行 B01

[ ] coder 没有执行 benchmark

[ ] Completion State Machine 没有被顺手重构
```

---

# 三十五、核心原则

整个修改过程中记住三个边界：

```text
Sandbox Preflight
回答：
“容器能不能运行？”

Verification Environment Preflight
回答：
“容器能不能运行本任务要求的验证工具？”

Task Verification
回答：
“代码修改是否正确？”
```

这三个问题不能继续混为一谈。

同时：

> **Agent 应该修代码问题，Runtime 应该负责发现基础设施问题。**

以及：

> **如果 Runtime 已经知道验证环境无法执行 required command，就不应该再花一次 LLM token 让 Agent 亲自发现它。**

本次目标不是“让 B01 看起来通过”，而是建立一个正确、可测试、可解释的 Verification Environment Contract。

B01 的真实结果由用户在本次代码修改完成以后亲自执行验证。
