# Week4 Day6 CLI Productization Prep Log

- **日期**: 2026-08-22
- **阶段**: tester 验收前准备
- **范围**: CLI Productization (`run`, `resume`, `diff`, `rollback`)

## 修复内容

- 修复 `codeteam/cli/run_command.py` ruff 问题：
  - import block 排序。
  - 删除 rollback 中重复 except 分支。
  - 保留 rollback 原有错误语义：非法请求 exit 2，执行失败 exit 1。
- `resume --provider/--model` 在 registry factory 未接线前 fail closed：
  - 不再接受参数后静默忽略。
  - 当前返回 exit 2，并提示 model override 未接线。
- `render_error()` 保持 stderr 输出，避免污染 diff/json stdout。

## 测试准备

新增 `tests/cli/` 三层测试：

```text
Layer 1: CliRunner unit
  argv -> request DTO / invalid args / stdout-stderr / no traceback

Layer 2: tmp_path integration
  git repo + session store + checkpoint state
  diff read-only / diff JSON / resume refusal / rollback ownership / rollback success

Layer 3: subprocess E2E
  python -m codeteam.cli.app --help
  real process stdout/stderr/exit code
```

## PARTIAL: SIGINT E2E

真实 `run -> Ctrl+C/SIGINT -> exit 130 -> PAUSED -> resume` 跨进程 E2E 暂未宣称完成。

原因：

```text
当前 CLI run 使用 MockPlanner + 快速 Orchestrator pipeline，
缺少可控长运行 test harness。直接对真实进程发送 SIGINT 容易竞态：
进程可能在信号发送前已经结束。
```

后续建议：

```text
新增可注入 sleeper/blocking planner 或 test-only long-running runtime factory，
再做稳定 SIGINT E2E。
```

## 后续债务

- Benchmark / Ablation 尚未周度执行。
- `resume --provider/--model` 需要 registry factory 后接入 ModelSwitchService。
- `CONTEXT_STALE rebuild` 需要 application service 统一接线。

