# Week4 Day6 CLI Productization 验收日志

日期：2026-08-22  
目标分支：week4  
任务开始 HEAD：05c8b067104aff5db9fb89c0b1c475cd4cfa202a  
验收范围：`codeteam/cli/`、`codeteam/llm/switching.py`、`tests/cli/`、`tests/llm/test_switching.py`、DD-W4-D6-01/02

## 1. Capability Mapping

被测模块属于能力树：

- Agent Harness：CLI product surface、任务入口、resume 入口、exit contract
- Tool Runtime：read-only diff、rollback、runtime failure 映射
- Session Runtime：resume 复用 Day4 SessionService / reconciliation
- Observability：stdout/stderr、turn.completed provider/model/tokens/cost
- Evaluation：CLI 三层测试、subprocess E2E、benchmark/ablation 数据出口

它证明的能力：

- 把 Python API 转换为稳定 CLI command contract。
- CLI 作为 thin interface layer，而不是 Fat CLI。
- 人类/脚本可依赖 stdout/stderr、exit code、session identity 和 read-only/mutating 边界。

## 2. 只读检查结果

实际执行：

```bash
git status --short --branch --untracked-files=all
git diff --stat
git diff --cached --stat
```

结果：

```text
## week4...origin/week4
```

`git diff --stat` 和 `git diff --cached --stat` 均为空。任务提示中的“staged + unstaged 混合状态”在本次验收开始时未复现；当前工作区实际为干净。

实际检查文件：

- `learning-plan/week4/day6.md`
- `prompt/test_Agent.md`
- `.codex/AGENTS.md`
- `pytest.ini`
- `pyproject.toml`
- `codeteam/cli/app.py`
- `codeteam/cli/render.py`
- `codeteam/cli/requests.py`
- `codeteam/cli/run_command.py`
- `codeteam/llm/switching.py`
- `tests/cli/test_cli_layer1.py`
- `tests/cli/test_cli_integration.py`
- `tests/cli/test_cli_subprocess.py`
- `tests/llm/test_switching.py`
- `docs/design_decisions/DD-W4-D6-01.md`
- `docs/design_decisions/DD-W4-D6-02.md`
- `test_log/2026-08-22_week4_day6_cli_prep_log.md`

依赖管理检查：

- `pyproject.toml` 存在 `[project]`，依赖包含 `typer>=0.23.0` 与 `pydantic>=2`。
- `[project.scripts]` 定义 `codeteam = "codeteam.cli.app:main"`。
- 该依赖声明符合当前 pyproject-based entry point 方案；未发现 Typer 只写入 dev dependency 的问题。

## 3. Requirement Matrix

| ID | 验收要求 | 证据 | 状态 |
| --- | --- | --- | --- |
| R1 | CLI 是 thin interface layer，不是 Fat CLI | `app.py` handler 主要构造 request 并委派；`test_cli_layer1.py` 覆盖 argv→DTO | PASS |
| R2 | `run` 尽早输出 Session ID | `run_agent_task()` 在 orchestrator 前 `render_text("Session: ...")`；prep/测试覆盖 run request，未做长任务时序 E2E | PARTIAL |
| R3 | `resume` 使用 Day4 SessionService/reconciliation，不重新 run | `resume_agent_session()` 调用 `SessionService.resume()`；missing/terminal/recovery 走 SessionError | PASS |
| R4 | `resume --provider/--model` 在真实 override 链路未接通前 fail closed | `test_resume_model_override_fails_closed_until_registry_is_wired` | PASS |
| R5 | `diff` 严格 read-only，不能调用 model/sandbox/mutation backend | `test_diff_is_read_only_and_does_not_mutate_repo_state`；无 model/sandbox 调用证据 | PASS |
| R6 | `rollback` 验证 Session / Task / Checkpoint ownership | `test_rollback_rejects_checkpoint_not_owned_by_session`、`_find_checkpoint()` | PASS |
| R7 | stdout/stderr 分离 | `render_error()` 写 stderr；`test_errors_go_to_stderr_not_stdout`、subprocess missing session | PASS |
| R8 | invalid request / missing session / terminal session / ownership violation exit 2 | missing session、terminal resume、ownership violation 覆盖；invalid `--format` 失败 | PARTIAL |
| R9 | runtime failure exit 1 | rollback result failure 映射 1；缺少稳定 runtime failure CLI case | PARTIAL |
| R10 | Ctrl+C 语义 PAUSED + exit 130 | prep log 明确 SIGINT E2E PARTIAL；`run` status PAUSED maps 130 | PARTIAL |
| R11 | JSON diff 输出合法 JSON，且错误不污染 stdout | `test_diff_json_output_is_valid_and_stable`；missing session stdout 为空 | PASS |
| R12 | 不暴露 Python traceback | 常规 invalid args/missing session/path traversal 覆盖；invalid `--format xml` 暴露 traceback | FAIL |
| R13 | `turn.completed` 包含 provider/model/tokens/cost 归因字段 | `TestTurnUsageAccounting` | PASS |
| R14 | DD-W4-D6-01/02 存在且 Evidence status 不夸大 | 两份 DD 均为 Evidence status: PROPOSED | PASS |
| R15 | Benchmark/Ablation 数据出口具备，本日不跑周度 benchmark | CLI startup、Time to Session ID、turn.completed、diff/rollback journey 可测 | PASS |
| R16 | `--format` 无效值处理 | 额外探测显示 `diff/rollback --format xml` traceback + exit 1 | FAIL |
| R17 | Docker sandbox skip 如实报告 | `tests/sandbox -q -rs` 显示 Colima socket permission denied | BLOCKED_ENV |

## 4. 实际执行命令与结果

### 4.1 CLI tests

```bash
.venv/bin/python -m pytest tests/cli -q
```

结果：

```text
exit code: 0
20 passed
```

### 4.2 Model switching tests

```bash
.venv/bin/python -m pytest tests/llm/test_switching.py -q
```

结果：

```text
exit code: 0
28 passed
```

### 4.3 Combined CLI + switching tests

```bash
.venv/bin/python -m pytest tests/cli tests/llm/test_switching.py -q
```

结果：

```text
exit code: 0
48 passed
```

### 4.4 CLI help

```bash
.venv/bin/python -m codeteam.cli.app --help
```

结果：

```text
exit code: 0
commands listed: inspect-repo, context, eval, run, resume, diff, rollback
```

### 4.5 Ruff

```bash
.venv/bin/python -m ruff check codeteam/cli/app.py codeteam/cli/render.py codeteam/cli/requests.py codeteam/cli/run_command.py codeteam/llm/switching.py tests/cli tests/llm/test_switching.py
```

结果：

```text
exit code: 0
All checks passed!
```

### 4.6 Full pytest

```bash
.venv/bin/python -m pytest -q
```

结果：

```text
exit code: 0
1187 passed, 6 skipped
```

### 4.7 Sandbox regression

```bash
.venv/bin/python -m pytest tests/sandbox -q -rs
```

结果：

```text
exit code: 0
36 passed, 6 skipped
```

skip 原因：

```text
Docker CLI/daemon is unavailable; boundary tests not run:
permission denied while trying to connect to the docker API at
unix:///Users/sqlee/.colima/default/docker.sock
```

未验证范围：

- 真实 Docker read/write workspace
- host secret isolation
- network none
- read-only rootfs
- docker socket absence

### 4.8 Mypy

```bash
.venv/bin/python -m mypy codeteam/cli tests/cli codeteam/llm tests/llm
```

结果：

```text
exit code: 1
26 errors in 8 files
```

mypy 分类：

- Day6 新增/修改目标文件错误：
  - `codeteam/cli/eval_command.py:270`: `CandidateGenerator` 的 `ripgrep` 参数为 `RipgrepClient | None`，期望 `RipgrepClient`。
  - 说明：该文件位于 `codeteam/cli/` 目标模块内，但不是本轮 ruff 触达文件列表中的 Day6 四命令文件；仍会阻塞 `codeteam/cli` 包级 mypy gate。
- 既有历史 import-chain 类型债：
  - `codeteam/parsing/tree_sitter_parser.py`: bytes/str、tree-sitter parse overload 类型问题。
  - `codeteam/application/inspect_repository.py`: `ImportGraph.add_edge` 参数 `str | None`。
  - `codeteam/failures/retry.py`: `object` 转 `float`。
  - `codeteam/failures/classifier.py`: `AgentErrorCode | None` 赋值给 `AgentErrorCode`。
  - `codeteam/search/ripgrep.py`: `IO | None`、`dict | None` 未收窄。
  - `codeteam/agent/orchestrator.py`: `float | None`、`RepairLoopRunResult | None` 未收窄。
- 缺失 stub / 第三方类型问题：
  - `codeteam/instructions/frontmatter.py:8`: missing `yaml` stubs，建议未来安装 `types-PyYAML` 或调整 mypy 配置。
- `codeteam/llm/switching.py`、`tests/cli`、`tests/llm/test_switching.py` 本身未报 mypy 错误。

## 5. 额外风险探测：invalid --format

执行：

```bash
.venv/bin/python -m codeteam.cli.app diff ses_missing --format xml
.venv/bin/python -m codeteam.cli.app rollback ses_missing cp-1 --format xml
```

结果：

```text
exit code: 1
输出包含 Pydantic ValidationError traceback
```

预期：

```text
invalid request 应 exit 2，错误写 stderr，不暴露 Python traceback。
```

结论：确认生产缺陷。

## 6. 确认的生产缺陷

### P1: invalid `--format` 暴露 traceback 且 exit code 错误

模块：

```text
codeteam/cli/app.py
codeteam/cli/requests.py
```

复现：

```bash
.venv/bin/python -m codeteam.cli.app diff ses_missing --format xml
.venv/bin/python -m codeteam.cli.app rollback ses_missing cp-1 --format xml
```

预期：

```text
exit code = 2
stderr = clean invalid argument message
stdout = empty
no Python traceback
```

实际：

```text
exit code = 1
输出 Rich/Pydantic traceback，包含 app.py 路径和 ValidationError。
```

初步原因：

```text
app.py 将 output_format 标注为 str，再 cast(OutputFormat, output_format)；
Typer 不知道合法枚举值。无效值进入 Pydantic DTO 后抛 ValidationError，
未被 CLI 层捕获并映射到 exit 2。
```

影响：

```text
违反 invalid request exit 2、no traceback、machine output stability。
```

### P2: `codeteam/cli` 包级 mypy gate 未通过

模块：

```text
codeteam/cli/eval_command.py
```

错误：

```text
Argument "ripgrep" to "CandidateGenerator" has incompatible type
"RipgrepClient | None"; expected "RipgrepClient"
```

影响：

```text
目标 mypy 命令失败；虽然四命令核心文件和 tests/cli 未报错，
但 codeteam/cli 包级类型验收未通过。
```

### P2: Ctrl+C SIGINT E2E 尚未完成

证据：

```text
test_log/2026-08-22_week4_day6_cli_prep_log.md 标记 PARTIAL。
```

影响：

```text
Day6 今日最终完成标准中的 Ctrl+C→130→PAUSED→resume 跨进程 E2E 未完全满足。
```

## 7. 未覆盖或 PARTIAL 内容

- `run` 尽早输出 Session ID 有代码证据，但缺少稳定长任务时序 E2E。
- Ctrl+C / SIGINT 真正跨进程中断并恢复仍为 PARTIAL。
- runtime failure exit 1 缺少明确 CLI integration case。
- `diff` read-only 目前主要证明 repo status 不变；未显式统计 model/sandbox/mutation backend call count。
- `--format` 无效值没有测试覆盖，且实际失败。
- Docker integration 因 Colima socket 权限被 skip。
- Benchmark / Ablation 未正式执行，只有数据出口和计划。

## 8. DD-W4-D6-01/02 审核结论

DD-W4-D6-01：

- 文件存在。
- Decision 为 Thin CLI + Request DTO + Renderer。
- Evidence status 为 PROPOSED，未夸大为 SUPPORTED。
- 当前证据与测试基本匹配；未完成证据明确列出 Journey Benchmark 与 SIGINT E2E。

DD-W4-D6-02：

- 文件存在。
- Decision 为 explicit exit/output contract。
- Evidence status 为 PROPOSED，未夸大为 SUPPORTED。
- 未完成证据明确列出真实 SIGINT E2E 和 JSONL stream 输出验证。

结论：DD 文档状态诚实，符合本日“设计决策证据不得夸大”的要求。

## 9. Benchmark / Ablation 状态

Benchmark：DESIGNED / NOT_RUN

具备数据出口：

- CLI startup latency：`python -m codeteam.cli.app --help` 可重复计时。
- Time to First Feedback / Session ID：`run_agent_task()` 在 orchestrator 前输出 `Session: ...`。
- `turn.completed` 提供 provider/model/input_tokens/output_tokens/model_calls/cost_usd。
- diff/rollback journey 可由 subprocess tests 扩展采样。

Ablation：DESIGNED / NOT_RUN

可做：

- Lazy vs eager import 的 startup P50/P95 对比。
- Thin vs fat CLI 的 import/side-effect/call-count 指标。
- diff read-only vs mutation backend ablation。

本日不执行周度 benchmark/ablation，未生成性能数字。

## 10. Day6 最终结论

Day6 结论：部分通过。

通过部分：

- CLI 三层测试通过。
- `codeteam --help` 真实模块入口可跑。
- full pytest 通过：1187 passed, 6 skipped。
- ruff 通过。
- resume 使用 Day4 SessionService；override fail closed。
- diff JSON 合法，常规错误不污染 stdout。
- rollback ownership 有测试证据。
- `turn.completed` 计量字段已补齐并测试通过。
- DD-W4-D6-01/02 Evidence status 均为 PROPOSED。

未通过 / 部分通过：

- invalid `--format` 暴露 traceback，exit code 为 1 而非 2。
- `codeteam/cli` 包级 mypy 命令失败。
- 真正 Ctrl+C→130→PAUSED→resume 跨进程 E2E 未完成。
- Docker integration 因环境权限 skip，真实 sandbox boundary 未在本终端验证。

是否建议提交当前 week4 分支：不建议直接提交为“Day6 完成”。建议先修复 P1 invalid `--format` traceback/exit code，并补稳定 SIGINT E2E；若只作为阶段性 CLI prep，可提交时必须在提交说明中明确 Day6 为 PARTIAL。

## 11. Coder 修复后复验

日期：2026-08-22

本节保留以上 tester 原始验收结论作为历史记录；以下为 Coder 针对 P1/P2 缺陷修复后的复验结果。

### 11.1 修复内容

P1 invalid `--format`：

- `codeteam/cli/app.py` 新增 CLI 层 `CliOutputFormat` 枚举。
- `diff --format` 与 `rollback --format` 现在在 Typer 参数解析层限制为 `text/json`。
- 无效值不会进入 `DiffRequest` / `RollbackRequest`，也不会调用 `diff_agent_session()` / `rollback_agent_session()`。
- `tests/cli/test_cli_layer1.py` 与 `tests/cli/test_cli_subprocess.py` 补充 invalid format 覆盖。

P2 `codeteam/cli/eval_command.py:270` mypy 目标内错误：

- `eval_command.py` 新增 `_DisabledRipgrepClient`，用于 filename-only 等禁用 ripgrep 的 eval 方法。
- `_build_retriever()` 不再把 `RipgrepClient | None` 传给 `CandidateGenerator`。
- tester 指出的 `CandidateGenerator(ripgrep=...)` 类型错误已消除。
- `mypy codeteam/cli/eval_command.py` 仍因 import-chain 历史债失败，剩余错误来自 `codeteam/parsing/tree_sitter_parser.py` 与 `codeteam/search/ripgrep.py`，不属于本轮允许修改范围。

P2 SIGINT E2E：

- `codeteam/cli/run_command.py` 新增测试专用 hook：`CODETEAM_CLI_TEST_WAIT_AFTER_SESSION=1`。
- 该 hook 只在测试环境启用：`run` 打印 `Session: <id>` 后进入可控等待点，收到 SIGINT 后持久化 `PAUSED` 并以 exit code 130 退出。
- `tests/cli/test_cli_subprocess.py::test_run_sigint_pauses_session_and_resume_uses_new_process` 使用真实 subprocess 运行 `python -m codeteam.cli.app run ...`，行同步等到 Session ID 后发送 SIGINT，再用新进程执行 `resume`。
- 复验证据显示：exit 130、session 落盘为 `PAUSED`、新进程 resume exit 0、stdout/stderr 无 Traceback。

其他 CLI 稳定性：

- `codeteam/cli/render.py` 的 stdout/stderr 输出改为 `flush=True`，保证 Session ID 与错误信息对真实 subprocess/脚本更稳定可见。

### 11.2 新增 / 调整测试

- `tests/cli/test_cli_layer1.py::test_diff_invalid_format_exits_2_without_calling_business`
- `tests/cli/test_cli_layer1.py::test_rollback_invalid_format_exits_2_without_calling_business`
- `tests/cli/test_cli_subprocess.py::test_real_process_diff_invalid_format_exits_2_without_traceback`
- `tests/cli/test_cli_subprocess.py::test_real_process_rollback_invalid_format_exits_2_without_traceback`
- `tests/cli/test_cli_subprocess.py::test_run_sigint_pauses_session_and_resume_uses_new_process`

### 11.3 实际复验命令

```bash
.venv/bin/python -m pytest tests/cli -q
# 25 passed

.venv/bin/python -m pytest tests/llm/test_switching.py -q
# 28 passed

.venv/bin/python -m pytest tests/cli tests/llm/test_switching.py -q
# 53 passed

.venv/bin/python -m codeteam.cli.app --help
# exit code 0，列出 inspect-repo/context/eval/run/resume/diff/rollback

.venv/bin/python -m ruff check codeteam/cli/app.py codeteam/cli/render.py codeteam/cli/requests.py codeteam/cli/run_command.py codeteam/cli/eval_command.py codeteam/llm/switching.py tests/cli tests/llm/test_switching.py
# All checks passed!

.venv/bin/python -m mypy codeteam/cli/eval_command.py
# exit code 1；tester 指出的 eval_command.py:270 已消除，剩余为 import-chain 历史债：
# codeteam/parsing/tree_sitter_parser.py、codeteam/search/ripgrep.py

.venv/bin/python -m mypy codeteam/cli tests/cli codeteam/llm tests/llm
# exit code 1；剩余 25 errors in 7 files，均为既有 import-chain / stub / unrelated typing debt。

.venv/bin/python -m pytest -q
# 1192 passed, 6 skipped

.venv/bin/python -m pytest tests/sandbox -q -rs
# 36 passed, 6 skipped
```

Sandbox skip 原因保持不变：

```text
Docker CLI/daemon is unavailable; boundary tests not run:
permission denied while trying to connect to the docker API at
unix:///Users/sqlee/.colima/default/docker.sock
```

### 11.4 修复后结论

Day6 功能验收：通过。

已修复：

- P1 invalid `--format` traceback / exit code 错误。
- P2 `codeteam/cli/eval_command.py:270` 目标内 mypy 错误。
- P2 Ctrl+C/SIGINT -> exit 130 -> PAUSED -> resume 跨进程 E2E。

仍保留：

- `mypy codeteam/cli/eval_command.py` 和包级 mypy 命令仍会因历史 import-chain 类型债失败。
- Docker integration 在当前环境因 Colima socket 权限 skip，真实 Docker boundary 未在本终端复验。
- Benchmark / Ablation 未在本次修复中执行，留周度评估。

建议：可以提交当前 week4 分支，但提交说明应如实包含 mypy import-chain 历史债与 Docker environment skip。
