# Week3 Day1 Git Diff 与 Patch 测试日志

## 1. 任务信息

- 日期：2026-08-10
- 目标分支：`week3`（提示词中的 `{{CODING_BRANCH}}` 未替换，按任务开始时当前分支推定）
- 起始 HEAD：`f52eb0bdaaf720cf71bb1cf65c2c30edd1612c5e`
- 测试分支：`codex/week3-day1-git-patch-tests`
- 测试提交：`802b5bd87383c4f3b0846e8c4c318fdb4bf82ddf`
- 独立 worktree：`/private/tmp/agent-learning-week3-day1-tests`
- 被测模块：`codeteam/git/`
- 测试框架：Python 3.11、pytest 9.1.1
- 最终结论：**部分通过**

本次只新增 `tests/git/` 测试与本日志，未修改 `codeteam/`、教学文档、Fixture、项目配置或其他生产代码。

## 2. 项目检查结果

当前实现包含：

- `GitWorkspace.diff()`
- `GitWorkspace.changed_files()`
- `GitWorkspace.check_patch()`
- `GitWorkspace.apply_patch()`
- `PatchValidator.validate()`
- NUL 格式的 name-status、numstat 和 untracked 路径解析
- Patch 大小、文件数量、Binary、路径边界、`.git` 与 Symlink 检查

任务开始时 `codeteam/git/` 是目标 `week3` 工作区中尚未提交的 `AM` 变更，不在起始 HEAD 中。因此测试代码在独立 worktree 编写和提交，合并前通过主工作区只读加载当前实际实现；测试提交合并后，再在目标分支使用规定命令完成复验。

## 3. 新增测试文件

- `tests/git/__init__.py`
- `tests/git/conftest.py`
- `tests/git/test_diff.py`
- `tests/git/test_apply_patch.py`
- `tests/git/test_patch_validator.py`
- `tests/git/test_path_security.py`

共收集 27 个 pytest Case。所有会改变 Git 状态的测试均通过 function-scoped `tmp_path` 创建独立仓库；每个仓库单独执行 `git init`、仓库本地用户配置和 baseline commit。测试 Git 子进程统一使用 argv 列表、`shell=False`、超时及 stdout/stderr 捕获。

## 4. 需求覆盖矩阵

| 编号 | Day1 要求 | 对应测试 | 结果 |
| --- | --- | --- | --- |
| T01 | 正常单文件 Patch | `test_check_patch_does_not_modify_file_and_single_file_patch_applies` | 通过 |
| T02 | 多文件 Patch | `test_multi_file_patch_applies_all_files` | 通过 |
| T03 | 新增文件 | `test_patch_can_add_file` | 通过 |
| T04 | 删除文件 | `test_patch_can_delete_file` | 通过 |
| T05 | Rename | `test_patch_can_rename_file` | 失败：应用成功，但 `affected_paths` 遗漏旧路径 |
| T06 | 错误 Context 原子失败 | `test_wrong_context_fails_without_changing_hashes_or_git_status` | 通过 |
| T07 | 多 Hunk 部分失败时整体不变 | `test_one_invalid_hunk_prevents_every_hunk_from_being_applied` | 通过 |
| T08 | `../../` 路径逃逸 | `test_patch_validator_classifies_unsafe_patch_as_security_rejected[../../outside.txt]` | 通过 |
| T09 | POSIX/Windows 绝对路径 | `test_path_validator_rejects...`、`test_patch_validator_classifies...` | 通过 |
| T10 | 修改 `.git` | `test_patch_validator_classifies_unsafe_patch_as_security_rejected[.git/config]` | 通过 |
| T11 | 符号链接逃逸 | `test_symlink_escape_is_rejected_and_outside_file_is_unchanged` | 通过 |
| T12 | 空格和中文文件名 | `test_changed_files_and_diff_include_untracked_paths_with_exact_names`、Rename 测试 | 通过 |
| T13 | 空 Patch | `test_empty_patch_is_rejected_without_modifying_repository` | 通过 |
| T14 | Binary Patch | `test_binary_patch_is_rejected_without_modifying_repository` | 通过 |
| T15 | Patch 大小限制 | `test_patch_size_limit_is_enforced_before_parsing` | 通过 |
| T16 | Patch 文件数量限制 | `test_patch_file_count_limit_is_enforced` | 通过 |
| T17 | `changed_files`/`diff` 处理 untracked | `test_changed_files_and_diff_include_untracked_paths_with_exact_names` | 通过 |
| T18 | ignored untracked 不进入结果 | `test_changed_files_excludes_ignored_untracked_files` | 通过 |
| T19 | HEAD 同时覆盖 staged/unstaged | `test_changed_files_reports_staged_and_unstaged_changes_against_head` | 通过 |
| T20 | `check_patch` 只检查不写盘 | 单文件 Patch 测试的前置验证 | 通过 |
| T21 | `apply_patch` 内部先调用 `check_patch` | `test_apply_patch_always_calls_check_patch` | 通过 |
| T22 | Git 调用 argv、`shell=False`、无危险参数 | `test_all_git_subprocess_calls_use_argv_without_dangerous_apply_flags` | 通过 |

失败与拒绝场景均比较操作前后 SHA256 和 NUL 格式 Git 状态；路径逃逸额外验证仓库外文件未被创建或修改。

## 5. 实际执行命令与结果

### 单文件测试

```text
.venv/bin/python -m pytest /private/tmp/agent-learning-week3-day1-tests/tests/git/test_diff.py -q
3 passed in 0.30s

.venv/bin/python -m pytest /private/tmp/agent-learning-week3-day1-tests/tests/git/test_patch_validator.py -q
7 passed in 0.51s

.venv/bin/python -m pytest /private/tmp/agent-learning-week3-day1-tests/tests/git/test_path_security.py -q
10 passed in 0.56s

.venv/bin/python -m pytest /private/tmp/agent-learning-week3-day1-tests/tests/git/test_apply_patch.py -q
1 failed, 6 passed in 0.78s
```

### 独立 worktree 模块测试

```text
.venv/bin/python -m pytest /private/tmp/agent-learning-week3-day1-tests/tests/git -q
1 failed, 26 passed in 1.85s
```

### 目标 `week3` 分支合并后复验

```text
.venv/bin/python -m pytest tests/git -q
1 failed, 26 passed in 1.95s

.venv/bin/python -m pytest -q
1 failed, 476 passed in 4.23s
```

最终模块结果：通过 26，失败 1，跳过 0，错误 0，共 27。

最终全量结果：通过 476，失败 1，跳过 0，错误 0，共 477。

首次直接从 worktree 执行时，因起始 HEAD 不包含尚未提交的 `codeteam/git/`，出现 4 个 `ModuleNotFoundError` 收集错误；改为从主工作区只读加载当前实现后收集正常。该环境问题不计入最终测试结果。

## 6. 覆盖率与静态检查

覆盖率命令：

```text
env COVERAGE_FILE=/private/tmp/agent-learning-week3-day1-tests/.coverage .venv/bin/python -m coverage run --branch --source=codeteam.git -m pytest /private/tmp/agent-learning-week3-day1-tests/tests/git -q
env COVERAGE_FILE=/private/tmp/agent-learning-week3-day1-tests/.coverage .venv/bin/python -m coverage report -m
```

| 模块 | 覆盖率 |
| --- | ---: |
| `codeteam/git/__init__.py` | 100% |
| `codeteam/git/diff.py` | 77% |
| `codeteam/git/errors.py` | 100% |
| `codeteam/git/models.py` | 100% |
| `codeteam/git/patch.py` | 79% |
| `codeteam/git/workspace.py` | 77% |
| 总体 | 80% |

分支覆盖已开启。重点未覆盖区域主要是超时、底层 Git 命令失败、畸形机器输出以及 TOCTOU 下预检查成功但真正 apply 失败的异常分支。

`ruff` 和 `mypy` 未安装，命令分别返回 `No module named ruff` 与 `No module named mypy`，因此静态检查无法执行。

## 7. 失败测试与生产缺陷

### 缺陷：Rename Patch 的受影响路径遗漏旧路径

- 失败测试：`tests/git/test_apply_patch.py::test_patch_can_rename_file`
- 复现命令：`.venv/bin/python -m pytest tests/git/test_apply_patch.py::test_patch_can_rename_file -q`
- 预期：`PatchResult.affected_paths == ["old name.txt", "新名字.txt"]`
- 实际：`PatchResult.affected_paths == ["新名字.txt"]`
- Patch 应用结果：成功，旧文件删除，新文件内容正确
- 原因分类：生产代码缺陷
- 稳定性：模块、覆盖率和全量测试中均稳定复现
- 责任模块：`codeteam/git/patch.py` 的 `extract_patch_paths()` / `parse_numstat_paths()`

初步原因：当前实现依赖 `git apply --numstat -z` 的输出识别 Rename。实际 Rename Patch 的 numstat 结果只提供目标路径，`parse_numstat_paths()` 因 `first_path` 非空直接返回目标路径，未从 Patch 扩展头提取 `rename from` 旧路径。因此结果元数据不完整，失败 apply 时的旧路径快照也可能缺失。

建议生产代码在后续修复中可靠解析并验证 Rename 的 old/new 两侧路径，并保留 NUL 安全语义；本测试任务未修改生产代码。

## 8. 验收结论与风险

Day1 的正常修改、新增、删除、Diff/untracked、错误 Context 原子性、多 Hunk 原子性、路径安全、Symlink、防 Binary、Patch 限制和 subprocess 安全要求均通过。Rename 文件操作本身成功，但结构化受影响路径不完整，因此不能声明生产功能全部验收通过，最终结论为 **部分通过**。

未覆盖或无法验证项：

- `git apply --check` 成功后真实文件被并发修改的 TOCTOU 分支。
- Git 子进程超时、命令不存在和超大输出等底层故障注入。
- Windows 原生平台路径行为；当前仅在 macOS 上验证 Windows 路径文本拒绝。
- `ruff`、`mypy` 静态检查因环境缺少依赖未执行。
