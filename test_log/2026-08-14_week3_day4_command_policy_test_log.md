# Week3 Day4 CommandPolicy Test Log

## 1. Evaluation Summary

任务：对 Week3 Day4 `CommandPolicy` 与危险命令识别实现进行正式测试开发、验收和 Failure Analysis。

结论：功能验收通过，工程证据仍为部分完成。

测试开发已完成：新增 `tests/execution/`，覆盖 Safe / Dangerous / Approval / Unknown / Precedence / Path / Docker / FakeRunner / Evaluation dataset / latency exploratory measurement。未修改生产代码。

初始验收发现 3 类生产缺陷，导致 5 个测试失败。随后通过生产代码修复并复跑回归，当前 Day4 correctness / safety 测试已通过：

- `tests/execution`: 82 passed
- full pytest: 592 passed
- ruff: passed
- mypy: passed

Benchmark / Ablation 尚未正式运行，因此 Design Decision 仍标记为 `PARTIALLY_SUPPORTED`，不能声明所有工程证据完全完成。

## 2. Capability Mapping

Day4 属于能力树中的：

- Tool Runtime / Command Authorization
- Workspace & Sandbox / Command Boundary
- Agent Runtime Safety
- Evaluation / Adversarial Security Testing

主要证明的 Agent 研发能力：

- 在命令进入 Runner 前做结构化授权判断。
- 区分 `ALLOW`、`ALLOW_SANDBOXED`、`REQUIRE_APPROVAL`、`DENY`。
- 对危险命令、解释器字符串执行、凭证路径、workspace escape、Docker privilege 做前置拦截。
- 通过 FakeRunner 证明危险命令不会到达执行层。

## 3. Repository Inspection

技术栈：Python 3.11，Pydantic，pytest，ruff，mypy。

测试框架：pytest。配置来自 `pytest.ini`，`testpaths = tests`。

目标模块：

- `codeteam/execution/models.py`
- `codeteam/execution/command_policy.py`
- `codeteam/execution/policy_rules.py`
- `codeteam/commands/risk_classifier.py`
- `codeteam/tools/shell.py`

读取文件：

- `prompt/test_Agent.md`
- `learning-plan/week3/day4.md`
- `codeteam/execution/`
- `codeteam/commands/risk_classifier.py`
- `codeteam/tools/shell.py`
- `.codex/AGENTS.md`
- `pytest.ini`
- 当前已有测试

真实接口：

- `CommandPolicy.default().evaluate(CommandRequest(...)) -> PolicyEvaluation`
- `PolicyDecision`: `ALLOW` / `ALLOW_SANDBOXED` / `REQUIRE_APPROVAL` / `DENY`
- `RiskCategory`
- `CommandRequest`
- `PolicyEvaluation`

当前已有测试：

- 本次任务前没有 `tests/execution/`。
- 现有测试覆盖 commands、shell tool、git、context、repository 等模块。

文档与当前实现差异：

- `day4.md` 后半段历史检查称 `codeteam/execution/` 可能尚不存在；当前实现已经存在。
- `ShellTool` 仍有自己的危险命令校验，本轮目标不是接入 ShellTool，而是独立验证 `CommandPolicy` public API。

Git 状态：

- 起始目标分支：`week3`
- 起始 HEAD：`8af43f5615f867b61bd9b3208baf867e22b0ad77`
- 测试分支：`codex/week3-day4-command-policy-tests`
- 测试 worktree：`/private/tmp/agent-learning-week3-day4-command-policy-tests`

## 4. Requirement Coverage

| 编号 | 要求 | 测试 | 状态 |
| --- | --- | --- | --- |
| R01 | Safe git read 自动允许 | `test_safe_commands_are_auto_allowed[...]` | PASS |
| R02 | pytest / python -m pytest / ruff / mypy 为 `ALLOW_SANDBOXED` | `test_safe_commands_are_auto_allowed[...]` | PASS |
| R03 | sudo / su / doas DENY | `test_dangerous_commands_are_denied[...]` | PASS |
| R04 | git reset --hard / git clean variants DENY | `test_dangerous_commands_are_denied[...]` | PASS |
| R05 | git branch -D / -d old DENY | `test_dangerous_commands_are_denied[git-branch-delete-force]`, `[git-branch-delete]` | PASS |
| R06 | shell `-c` DENY | `test_dangerous_commands_are_denied[sh-c/bash-c/zsh-c]` | PASS |
| R07 | interpreter string execution DENY | `test_dangerous_commands_are_denied[python-c/python311-c/absolute-python-c/env-python-c/env-python3-c/node-e/ruby-e/perl-e]` | PASS |
| R08 | shutdown / reboot DENY | `test_dangerous_commands_are_denied[shutdown/reboot]` | PASS |
| R09 | workspace 外路径和 cwd 外逃 DENY | `test_workspace_external_path_argument_is_denied`, `test_cwd_outside_workspace_is_denied` | PASS |
| R10 | `~/.ssh`, `.aws`, `.kube` DENY | `test_dangerous_commands_are_denied[...]` | PASS |
| R11 | `.env` DENY | `test_dangerous_commands_are_denied[dot-env]` | PASS |
| R12 | Docker privileged/network host/socket/sensitive mount DENY | `test_dangerous_commands_are_denied[docker-*]` | PASS |
| R13 | Docker workspace ordinary bind mount not mis-DENY by privilege rule | `test_docker_workspace_bind_mount_is_not_denied_by_privilege_rule` | PASS |
| R14 | Network / install / remote write require approval | `test_network_install_and_remote_write_commands_require_approval[...]` | PASS |
| R15 | Unknown command defaults to require approval | `test_unknown_command_defaults_to_require_approval` | PASS |
| R16 | Empty argv rejected by Pydantic | `test_empty_argv_is_rejected_by_pydantic` | PASS |
| R17 | Highest risk wins | `test_highest_risk_decision_wins_when_multiple_rules_match` | PASS |
| R18 | `DENY > REQUIRE_APPROVAL > ALLOW_SANDBOXED > ALLOW` | precedence cases plus failure evidence | PASS |
| R19 | `evaluate()` returns `PolicyEvaluation` and does not execute | `test_policy_evaluate_returns_evaluation_without_running_command` | PASS |
| R20 | Dangerous command cannot enter FakeRunner | `test_denied_command_does_not_reach_fake_runner` | PASS |
| R21 | Diagnostic matched rules / risks / reasons | `test_diagnostic_fields_include_rules_risks_and_reasons` | PASS |
| R22 | Safe git read does not allow destructive git subcommands | `test_safe_git_read_does_not_allow_destructive_git_subcommands` | PASS |
| R23 | Evaluation dataset metrics computable | `test_policy_evaluation_dataset_metrics_are_computable` | PASS |
| R24 | Policy latency exploratory measurement practical | `test_policy_latency_exploratory_measurement_is_fast_enough` | PASS |

## 5. Tests

新增：

- `tests/execution/__init__.py`
- `tests/execution/test_command_policy.py`

修改：无。

删除：无。

未修改：

- `codeteam/`
- `learning-plan/`
- `prompt/`
- `.codex/`
- `tests/fixtures/`
- `evals/`
- `README.md`
- 项目配置

## 6. Test Execution Results

独立 linked worktree 中没有 `.venv/`，所以相对命令失败：

```text
.venv/bin/python -m pytest tests/execution -q
zsh:1: no such file or directory: .venv/bin/python
```

随后使用项目主工作区虚拟环境的绝对路径执行等价命令：

```text
/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest tests/execution -q
/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest -q
/Users/root/workspace/Agent-Learning/.venv/bin/python -m ruff check tests/execution codeteam/execution
/Users/root/workspace/Agent-Learning/.venv/bin/python -m mypy tests/execution codeteam/execution
```

初始结果：

```text
tests/execution: 77 passed, 5 failed
full pytest: 587 passed, 5 failed
ruff: All checks passed!
mypy: Success: no issues found in 6 source files
```

初始通过：587
初始失败：5
跳过：0
错误：0

生产缺陷修复后复验：

```text
.venv/bin/python -m pytest tests/execution -q
82 passed in 0.34s

.venv/bin/python -m pytest -q
592 passed in 7.37s

.venv/bin/python -m ruff check codeteam/execution tests/execution
All checks passed!

.venv/bin/python -m mypy codeteam/execution tests/execution
Success: no issues found in 6 source files
```

最终通过：592
最终失败：0
最终跳过：0
最终错误：0

## 7. Coverage

本轮用户未要求运行 coverage 命令，因此未执行覆盖率统计。

## 8. Benchmark / Evaluation

状态：PARTIAL。

本轮建立了可执行 evaluation dataset / 测试用例矩阵：

- Safe cases：15
- Dangerous cases：35
- Approval cases：17
- Total classified policy cases：67

已记录并由 `test_policy_evaluation_dataset_metrics_are_computable` 计算的指标：

- Dangerous Pass-through Rate：测试可计算；当前断言危险样本不能被 `ALLOW` / `ALLOW_SANDBOXED`。
- Safe Auto-Allow Rate：测试可计算；当前断言 safe 样本全部自动允许或 sandboxed allow。
- Approval Burden：测试可计算；当前断言 safe 样本不应落入 approval。
- False Deny Case：测试可计算；当前断言 safe 样本不应 DENY。
- Policy Latency exploratory measurement：`test_policy_latency_exploratory_measurement_is_fast_enough` 对 67 条请求进行本地 exploratory measurement，只验证测量值可计算和排序关系，不声称性能达标。

限制：

- 初始验收发现的生产缺陷已修复，当前 dataset 可作为 Day4 correctness / safety 回归证据。
- 未保存单独 benchmark raw JSONL，因为允许写入范围仅包含 `tests/execution/` 和 `test_log/`，本轮以 pytest 断言和日志记录为主。
- 未建立 200-case 正式 benchmark；标记为 INSUFFICIENT_EVIDENCE。

## 9. Ablation

状态：NOT_RUN。

本轮给出可执行 ablation 方案，但未实现 runner，原因：

- 用户要求至少先建立 dataset 或测试矩阵；未要求本轮实现完整 ablation runner。
- 初始 full policy 存在生产缺陷；缺陷修复后尚未补跑正式 ablation runner。
- 不应在缺陷实现上声称模块贡献或性能收益。

后续可执行方案：

1. Full policy vs denylist-only
   - Dataset：本轮 67-case matrix 扩展到 200 cases。
   - Metrics：Dangerous Pass-through Rate、Safe Auto-Allow Rate、Approval Burden、False Deny Rate。

2. Full policy vs no interpreter/nested detection
   - Dataset：shell `-c`、`/usr/bin/env python -c`、node/ruby/perl `-e`、wrapper cases。
   - Metrics：Dangerous Pass-through Rate。

3. Full policy vs argv[0]-only detection
   - Dataset：`git branch -D`、`python -m pip install`、docker mounts、credential paths。
   - Metrics：classification accuracy、missed dangerous cases。

## 10. Failure Cases

### Failure CP-DAY4-001

Status: RESOLVED.

Module: `codeteam/execution/policy_rules.py`

Scenario: destructive branch deletion is not classified as DENY.

Input:

```text
git branch -D old
git branch -d old
```

Expected:

```text
PolicyDecision.DENY
RiskCategory.DESTRUCTIVE
matched_rules includes git_destructive
```

Actual:

```text
PolicyDecision.REQUIRE_APPROVAL
RiskCategory.UNKNOWN
matched_rules == ()
```

Resolved Actual:

```text
PolicyDecision.DENY
RiskCategory.DESTRUCTIVE
matched_rules includes git_destructive
```

Impact:

Branch deletion is a destructive Git operation. It cannot silently pass as unknown approval-only in a strict command authorization layer requested by Day4.

Reproduction:

```text
/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest tests/execution/test_command_policy.py::test_dangerous_commands_are_denied -q
```

Reproducibility: stable.

Suspected Root Cause:

`GitDestructiveRule` handles `reset --hard` and `clean` force-directory flags but does not handle `git branch -d` or `git branch -D`.

Fix Summary:

`GitDestructiveRule` now recognizes branch deletion flags including `-d`, `-D`, `--delete`, and forced delete forms. Safe branch reads remain limited to `git branch`, `git branch --show-current`, and `git branch --list`.

Regression Test:

- `test_dangerous_commands_are_denied[git-branch-delete-force]`
- `test_dangerous_commands_are_denied[git-branch-delete]`
- `test_safe_git_read_does_not_allow_destructive_git_subcommands`

### Failure CP-DAY4-002

Status: RESOLVED.

Module: `codeteam/execution/policy_rules.py`

Scenario: `.env` in current workspace is not classified as credential access.

Input:

```text
cat .env
```

Expected:

```text
PolicyDecision.DENY
RiskCategory.SECRET_ACCESS
matched_rules includes credential_path
```

Actual:

```text
PolicyDecision.REQUIRE_APPROVAL
RiskCategory.UNKNOWN
matched_rules == ()
```

Resolved Actual:

```text
PolicyDecision.DENY
RiskCategory.SECRET_ACCESS
matched_rules includes credential_path
```

Impact:

`.env` is explicitly listed in credential markers and often contains secrets. Missing this case weakens secret-access safety.

Reproducibility: stable.

Suspected Root Cause:

`_path_like_arguments` does not treat plain dotfile names such as `.env` as path-like, so `CredentialPathRule` never inspects them.

Fix Summary:

`CredentialPathRule` now inspects known credential marker arguments even when they are bare filenames without `/`, including `.env`, `.npmrc`, `.pypirc`, and `.netrc`, without denying arbitrary dotfiles.

Regression Test:

- `test_dangerous_commands_are_denied[dot-env]`

### Failure CP-DAY4-003

Status: RESOLVED.

Module: `codeteam/execution/policy_rules.py`

Scenario: ordinary Docker bind mount from pytest temp workspace under `/private/var/...` is misclassified as host `/var` sensitive mount.

Input:

```text
docker run -v <tmp_workspace>/cache:/cache alpine
```

Expected:

```text
docker_privilege not matched
decision should not be DENY due to docker privilege
```

Actual:

```text
PolicyDecision.DENY
matched_rules == ("docker_privilege",)
reason: Docker host mount target is too sensitive: <tmp_workspace>/cache
```

Resolved Actual:

```text
docker_privilege not matched
workspace-local bind mount is not denied by DockerPrivilegeRule
```

Impact:

False deny for ordinary workspace-local Docker bind mounts on macOS paths that include `/private/var/...`. This increases false deny rate and approval/sandbox friction.

Reproducibility: stable in current macOS temp path environment.

Suspected Root Cause:

`_is_sensitive_docker_host_path` checks whether host path is relative to sensitive `/var`. On macOS, pytest temp dirs resolve under `/private/var/...`, so workspace-local paths are treated as sensitive host mounts.

Fix Summary:

Docker mount sensitivity now first checks whether the host source is inside `request.workspace_root`. Workspace-local bind mounts are not denied by `DockerPrivilegeRule`, while workspace-external sensitive host paths such as `/`, `/etc`, `/var`, `/usr`, and `/var/run/docker.sock` remain denied.

Regression Test:

- `test_docker_workspace_bind_mount_is_not_denied_by_privilege_rule`

## 11. Production Defects

Resolved:

- P1: Git branch deletion is not denied. See Failure CP-DAY4-001.
- P1: `.env` credential access is not denied. See Failure CP-DAY4-002.
- P2: Docker workspace-local bind mount false denied on macOS temp paths. See Failure CP-DAY4-003.

Open Production Defects:

- None known from the current Day4 test suite.

## 12. Design Decision Verification

Decision: Structured argv instead of shell string.

Evidence Collected:

- Tests construct `CommandRequest(argv=tuple(...))`.
- Empty argv rejected by Pydantic.
- Shell/interpreter string execution cases are detected through argv.

Evaluation: PARTIALLY_SUPPORTED.

Reason: Correctness tests support the structure, but no string-regex ablation was run.

Decision: Hybrid Policy.

Evidence Collected:

- Safe commands auto allow or sandbox allow.
- Network/install/remote write require approval.
- Dangerous commands are denied by the current 82-test execution suite.
- Unknown commands require approval.

Evaluation: PARTIALLY_SUPPORTED.

Reason: Correctness and safety tests now support the hybrid policy behavior, but no formal benchmark or ablation has been run.

Decision: Rule Chain + highest severity wins.

Evidence Collected:

- Diagnostic tests confirm matched rules/risks/reasons.
- Precedence tests cover deny over safe, approval over sandbox, and deny over approval.

Evaluation: PARTIALLY_SUPPORTED.

Reason: Rule chain behavior works for current test coverage, including highest severity precedence. It remains PARTIALLY_SUPPORTED because comparative ablation evidence is not yet available.

## 13. Acceptance

| Dimension | Result | Evidence |
| --- | --- | --- |
| Test Development | COMPLETE | `tests/execution/test_command_policy.py` |
| Correctness | PASS | 82 passed in `tests/execution` |
| Safety | PASS for tested Day4 policy cases | Dangerous command gating, credential paths, Docker mount boundaries, and FakeRunner tests pass |
| Benchmark / Evaluation | PARTIAL | executable 67-case matrix, not full benchmark |
| Ablation | NOT_RUN | executable plan recorded |
| Failure Analysis | COMPLETE | 3 failure cases documented and marked resolved |
| Regression | PASS | full pytest: 592 passed |
| Overall Module Acceptance | PASS with evidence limitations | production defects resolved; benchmark/ablation still incomplete |

## 14. Regression

Executed:

- `tests/execution`
- full pytest suite
- ruff over `tests/execution codeteam/execution`
- mypy over `tests/execution codeteam/execution`

Initial execution found 5 Day4 CommandPolicy failures and no unrelated regressions.

After production fixes:

- `tests/execution`: PASS, 82 passed
- full pytest suite: PASS, 592 passed
- ruff over `tests/execution codeteam/execution`: PASS
- mypy over `tests/execution codeteam/execution`: PASS

No known Day4 regression remains in the current test suite.

## 15. Risks and Limitations

- Policy-only testing cannot prove host containment; Sandbox validation remains future work.
- No actual dangerous command was executed; this is intentional.
- Benchmark is a development matrix, not a statistically significant benchmark.
- Ablation runner was not implemented in this turn.
- Docker path behavior is platform-sensitive; macOS `/private/var` temp paths revealed one false deny that is now covered by regression tests.

## 16. Artifacts

- `tests/execution/test_command_policy.py`
- `tests/execution/__init__.py`
- `test_log/2026-08-14_week3_day4_command_policy_test_log.md`

## 17. Interview Evidence

This evaluation provides concrete evidence for:

- Building an Agent Tool Runtime authorization layer.
- Separating policy decisions from command execution.
- Using FakeRunner gating to prove dangerous commands do not reach runner.
- Measuring safety/usability trade-offs with Dangerous Pass-through, Safe Auto-Allow, Approval Burden, and False Deny concepts.
- Performing failure analysis on security rules without hiding production defects.

Limits:

- Current evidence is enough for Day4 functional acceptance, but not enough to claim full CommandPolicy safety across all possible command wrappers, shell aliases, package scripts, or platform-specific path behaviors.
- Current evidence does not prove sandbox containment or ablation value.

## 18. Final Conclusion

Test Development: COMPLETE

Correctness: PASS

Safety: PASS for tested Day4 policy scope

Benchmark / Evaluation: PARTIAL

Ablation: NOT_RUN

Design Decision: PARTIALLY_SUPPORTED

Overall Module Acceptance: PASS with evidence limitations

The Day4 `CommandPolicy` implementation now satisfies the current correctness and safety acceptance scope. The final regression evidence is 82 passing `tests/execution` cases and 592 passing full-suite tests, with ruff and mypy passing over `tests/execution codeteam/execution`.

The module should still be described carefully: the functional Day4 scope is accepted, but benchmark and ablation evidence remain incomplete. Design Decisions are therefore PARTIALLY_SUPPORTED rather than SUPPORTED.
