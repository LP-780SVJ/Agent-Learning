# Reviewer Prompt: Four-Week Overall Review

任务：对 `/Users/root/workspace/Agent-Learning` 当前 `week4` 分支做四周总体 code review。你是 reviewer，只能读取、运行、统计和汇报；不能修改任何代码、测试、文档或配置。

必须遵守：

- 使用项目虚拟环境：`.venv/bin/python`。
- 不使用系统默认 `python3`。
- 只读 review，不得执行 `apply_patch`，不得 `git add`、`git commit`、`git reset`、`git checkout --`、`rm`。
- 可以运行测试、ruff、mypy、CLI、eval、Docker 相关命令；如果 Docker daemon 不可访问，记录环境阻塞，不得改代码绕过。
- 不得读取或打印 secret 值；只允许报告 secret 配置是否存在。

重点阅读：

- `/Users/root/workspace/Agent-Learning/README.md`
- `/Users/root/workspace/Agent-Learning/learning-plan/`
- `/Users/root/workspace/Agent-Learning/code_review/`
- `/Users/root/workspace/Agent-Learning/test_log/`
- `/Users/root/workspace/Agent-Learning/docs/design_decisions/`
- `/Users/root/workspace/Agent-Learning/evals/`
- `/Users/root/workspace/Agent-Learning/codeteam/`
- `/Users/root/workspace/Agent-Learning/tests/`
- `/Users/root/workspace/Agent-Learning/prompt/coder_Agent.md`
- `/Users/root/workspace/Agent-Learning/prompt/test_Agent.md`
- `/Users/root/workspace/Agent-Learning/.codex/AGENTS.md`

建议执行命令：

```bash
git status --short --branch
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/sandbox -q -rs
.venv/bin/python -m ruff check codeteam tests evals
.venv/bin/python -m mypy codeteam tests
.venv/bin/python -m codeteam.cli.app --help
.venv/bin/python -m codeteam.cli.app eval --dataset evals/week2/file_retrieval.jsonl --repo tests/fixtures/test_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output /tmp/codeteam-review-week2-eval
.venv/bin/python -m codeteam.cli.app eval --dataset evals/medium_repo/file_retrieval.jsonl --repo tests/fixtures/medium_repo --methods filename,ripgrep,ripgrep_symbol,hybrid --output /tmp/codeteam-review-medium-eval
```

Review 目标：

1. 按 P0/P1/P2/P3 列 findings。每个 finding 必须包含文件/行号、影响、复现方式、建议修复方向。
2. 检查测试真实性：是否过度 mock、是否只测 happy path、是否能暴露真实边界、是否存在测试为了实现而写。
3. 检查 eval 客观性：dataset 是否泄漏答案、gold 是否合理、fixture 是否过拟合、指标是否充分、manifest 是否可复现。
4. 检查是否存在面向 pytest/eval 设计的实现：生产代码是否硬编码测试条件、是否为过某条 eval 特化逻辑、是否牺牲泛化。
5. 检查架构边界：Context / Git / Execution / Sandbox / Session / CLI / LLM / Evaluation 的职责是否清楚，是否有循环依赖或层级穿透。
6. 检查冗余代码和可瘦身结构：重复模型、重复命令封装、旧模块残留、未使用 import/函数、可以合并或删除的 adapter、过度抽象。
7. 检查安全边界：path traversal、symlink、`.git`、credentials、shell/interpreter `-c`、Docker mount/network/rootfs、approval bypass、rollback ownership。
8. 检查恢复能力：patch failure atomicity、checkpoint rollback、session persistence/resume、SIGINT pause、provider/model drift、context compaction failure。
9. 给出下一阶段准入建议：是否可以进入 Week5；进入前必须修复哪些；哪些可以留作 P3/技术债。

输出文件：

`/Users/root/workspace/Agent-Learning/code_review/four_week_overall_review.md`

报告结构必须包含：

- Executive Summary
- Commands Run
- Findings by Severity
- Test Quality Audit
- Evaluation Quality Audit
- Test/Eval Overfitting Audit
- Architecture Boundary Audit
- Redundant Code / Simplification Opportunities
- Security Audit
- Known Historical Debt
- Next-Stage Readiness
- Recommended Fix Order

最终结论只能是以下之一：

- `READY_FOR_WEEK5`
- `READY_WITH_P2_DEBT`
- `BLOCKED_BY_P0_OR_P1`
- `BLOCKED_BY_ENVIRONMENT`
