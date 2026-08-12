# Week3 Day2 Worktree Formal Test Log

## 1. 项目检查结果

技术栈：Python 3.11，pytest，ruff，mypy，Git subprocess。

测试框架：pytest。项目配置来自 `pytest.ini`，`testpaths = tests`，`tests/fixtures` 被排除。

目标模块：

- `codeteam/git/worktree.py`
- `codeteam/git/models.py`
- `codeteam/git/errors.py`
- `tests/git/`

读取的主要文件：

- `learning-plan/week3/day2.md`
- `test_log/2026-08-12_week3_day2_worktree_create_test_log.md`
- `codeteam/git/worktree.py`
- `codeteam/git/models.py`
- `codeteam/git/errors.py`
- `tests/git/conftest.py`
- `tests/git/test_apply_patch.py`
- `tests/git/test_diff.py`
- `tests/git/test_patch_validator.py`
- `tests/git/test_path_security.py`
- `.codex/AGENTS.md`
- `pytest.ini`

发现的接口：

- `WorktreeManager(repo_root, worktree_root=None)`
- `WorktreeManager.create(task_id, base_ref="HEAD")`
- `WorktreeInfo(task_id, branch_name, path, base_ref, base_sha, head_sha)`
- `InvalidTaskIdError`
- `BaseRefNotFoundError`
- `BranchAlreadyExistsError`
- `WorktreePathConflictError`
- `GitWorktreeCommandError`

已有测试情况：

- `tests/git/` 原有测试覆盖 Day1 diff、patch、path security，共 27 个 pytest 测试。
- 原有测试没有正式覆盖 Day2 `WorktreeManager.create()`。
- 旧 smoke 日志只记录了直接脚本验证，不是完整 Day2 验收日志。

文档与当前实现不一致：

- `day2.md` 早期章节提示 `codeteam/git/worktree.py` 可能尚不存在；当前实现已经存在。
- `day2.md` 提到 Day1 rename metadata 可能失败；当前 Day1 `tests/git` 在本分支中原有部分通过，不应把 Day1 失败视作背景豁免。
- 当前实现已有 `create()`，但仍复现 smoke 日志中的 `_branch_exists("codeteam/task-001")` 失败。

## 2. 测试需求覆盖情况

| 编号 | Day2 验收要求 | 对应测试 | 状态 |
| --- | --- | --- | --- |
| T01 | `WorktreeManager.create()` 创建 linked worktree 和 task branch | `test_create_returns_structured_info_for_linked_worktree` | 失败，生产缺陷 |
| T02 | 返回结构化 `WorktreeInfo`，字段与当前实现一致 | `test_create_returns_structured_info_for_linked_worktree` | 失败，生产缺陷 |
| T03 | `branch_name == codeteam/<task_id>` | `test_create_returns_structured_info_for_linked_worktree` | 失败，生产缺陷 |
| T04 | linked worktree path 存在 | `test_create_returns_structured_info_for_linked_worktree` | 失败，生产缺陷 |
| T05 | linked worktree 中 `git branch --show-current` 返回任务分支 | `test_create_returns_structured_info_for_linked_worktree` | 失败，生产缺陷 |
| T06 | linked worktree HEAD 等于 base_ref commit | `test_create_returns_structured_info_for_linked_worktree`，`test_create_uses_specified_base_ref_for_worktree_head` | 失败，生产缺陷 |
| T07 | linked worktree `.git` 可以是文件 | `test_create_returns_structured_info_for_linked_worktree` | 失败，生产缺陷 |
| T08 | task worktree 修改文件不会污染 main | `test_task_worktree_modification_does_not_pollute_main_worktree` | 失败，生产缺陷 |
| T09 | main worktree status 不因 task 修改变脏 | `test_task_worktree_modification_does_not_pollute_main_worktree` | 失败，生产缺陷 |
| T10 | 两个不同 task_id 生成不同 branch 和 path | `test_two_task_ids_create_distinct_branches_and_paths` | 失败，生产缺陷 |
| T11 | task-001 修改不污染 task-002 和 main | `test_task_worktree_modification_does_not_pollute_other_task_worktree` | 失败，生产缺陷 |
| T12 | 重复 task_id 被拒绝 | `test_repeated_task_id_is_rejected_without_partial_state` | 失败，生产缺陷 |
| T13 | 重复 branch 被拒绝 | `test_existing_task_branch_is_rejected_without_creating_path` | 通过 |
| T14 | 非法 task_id：空、`../evil`、`task/001`、`.hidden`、反斜杠 | `test_invalid_task_id_is_rejected_without_branch_or_path_escape[...]` | 通过 |
| T15 | worktree path 已存在时拒绝覆盖 | `test_existing_worktree_path_is_rejected_without_overwriting_contents` | 失败，生产缺陷 |
| T16 | base_ref 不存在时失败清晰 | `test_missing_base_ref_fails_clearly_without_partial_state` | 通过 |
| T17 | 不允许 `git worktree add --force` | `test_worktree_subprocess_calls_use_safe_argv_and_no_force_flags` | 通过 |
| T18 | Git subprocess 使用 argv、shell=False、timeout、stdout/stderr 捕获 | `test_worktree_subprocess_calls_use_safe_argv_and_no_force_flags`，`tests/git/conftest.py::run_git` | 通过 |
| T19 | Git 变更测试使用 function-scoped tmp_path 独立 repo | `git_repo_factory` 与全部 worktree 行为测试 | 通过 |
| T20 | 失败场景额外证明无部分状态 | 非法 task、重复 branch、缺失 base_ref、路径冲突测试包含 SHA/status/path/branch/marker 断言 | 部分通过，因主流程缺陷导致部分断言未到达 |

## 3. 新增或修改文件

新增：

- `tests/git/test_worktree.py`
- `test_log/2026-08-12_week3_day2_worktree_test_log.md`

修改：

- `tests/git/conftest.py`
- `tests/git/test_apply_patch.py`
- `tests/git/test_patch_validator.py`

删除：无。

未修改：

- `codeteam/`
- `learning-plan/`
- `tests/fixtures/`
- `evals/`
- `README.md`
- `.codex/AGENTS.md`
- `prompt/test_Agent.md`
- `pytest.ini`

## 4. 执行命令

测试工作在独立 Git worktree `/private/tmp/agent-learning-week3-day2-worktree-formal-tests` 和分支 `codex/week3-day2-worktree-formal-tests` 中进行，基于 `week3` 起始 HEAD：

```text
19ce25c9758d28f5fa55b930418da070d923cf0e
```

linked worktree 中没有 `.venv/`，因此严格相对命令启动失败：

```text
.venv/bin/python -m pytest tests/git/test_worktree.py -q
zsh:1: no such file or directory: .venv/bin/python
```

随后使用同一项目虚拟环境的绝对解释器路径执行等价验证：

```text
/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest tests/git/test_worktree.py -q
/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest tests/git -q
/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest -q
/Users/root/workspace/Agent-Learning/.venv/bin/python -m ruff check tests/git
/Users/root/workspace/Agent-Learning/.venv/bin/python -m mypy tests/git
```

## 5. 测试结果

Day2 单文件：

```text
命令：/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest tests/git/test_worktree.py -q
结果：7 failed, 8 passed
耗时：1.30s
```

Git 模块：

```text
命令：/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest tests/git -q
结果：7 failed, 35 passed
耗时：2.84s
```

全量测试：

```text
命令：/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest -q
结果：7 failed, 485 passed
耗时：5.02s
```

ruff：

```text
命令：/Users/root/workspace/Agent-Learning/.venv/bin/python -m ruff check tests/git
结果：All checks passed!
```

mypy：

```text
命令：/Users/root/workspace/Agent-Learning/.venv/bin/python -m mypy tests/git
结果：Success: no issues found in 7 source files
```

汇总：

```text
通过：485
失败：7
跳过：0
错误：0
```

## 6. 失败测试及原因分类

原因分类：生产代码缺陷。

失败测试：

- `test_create_returns_structured_info_for_linked_worktree`
- `test_create_uses_specified_base_ref_for_worktree_head`
- `test_task_worktree_modification_does_not_pollute_main_worktree`
- `test_task_worktree_modification_does_not_pollute_other_task_worktree`
- `test_two_task_ids_create_distinct_branches_and_paths`
- `test_repeated_task_id_is_rejected_without_partial_state`
- `test_existing_worktree_path_is_rejected_without_overwriting_contents`

共同错误：

```text
codeteam.git.errors.GitWorktreeCommandError:
fatal: 'refs/heads/codeteam/task-001' - not a valid ref
```

部分失败中的 task id 为 `task-feature`，对应错误为：

```text
fatal: 'refs/heads/codeteam/task-feature' - not a valid ref
```

## 7. 已确认的生产代码缺陷

### P1 缺陷：`_branch_exists` 对不存在的嵌套分支判断错误，阻断 `WorktreeManager.create()`

影响模块：

```text
codeteam/git/worktree.py
```

对应测试：

```text
tests/git/test_worktree.py::test_create_returns_structured_info_for_linked_worktree
```

前置条件：

- 使用 `tmp_path` 创建独立 Git 仓库。
- 设置仓库本地 `user.name` 和 `user.email`。
- 创建 baseline commit。
- 显式将分支重命名为 `main`。
- 初始化 `WorktreeManager(repo_root=repo, worktree_root=tmp_path / "worktrees")`。

复现步骤：

1. 执行 `/Users/root/workspace/Agent-Learning/.venv/bin/python -m pytest tests/git/test_worktree.py -q`。
2. 观察 `test_create_returns_structured_info_for_linked_worktree`。

预期结果：

- `_branch_exists("codeteam/task-001")` 对不存在的分支返回 `False`。
- `create("task-001", base_ref="main")` 继续执行 `git worktree add -b codeteam/task-001 ... main`。
- 返回 `WorktreeInfo`，并创建 linked worktree。

实际结果：

```text
GitWorktreeCommandError: fatal: 'refs/heads/codeteam/task-001' - not a valid ref
```

稳定性：

- 是否稳定复现：是
- 复现次数：多次
- 影响平台：当前 macOS / zsh / Git 环境

初步原因：

当前实现使用：

```text
git show-ref --verify refs/heads/codeteam/task-001
```

在当前 Git 版本中，不存在的嵌套分支 ref 返回的 exit code 不是实现所假定的 `1`，而是进入 fatal 分支，导致 `_branch_exists` 抛出 `GitWorktreeCommandError`。因此 `create()` 在检查分支冲突阶段失败，无法进入 `git worktree add`。

建议：

修正 `_branch_exists` 对不存在 ref 的判断，或使用更适合查询分支存在性的 Git 命令/参数组合。修复后重新运行：

```text
.venv/bin/python -m pytest tests/git/test_worktree.py -q
.venv/bin/python -m pytest tests/git -q
.venv/bin/python -m pytest -q
```

本测试任务未修改生产代码。

## 8. 未覆盖或无法验证内容

- 因 `create()` 主流程被 `_branch_exists` 阻断，linked worktree 成功创建后的隔离性、`.git` 文件形态、HEAD/base_ref 后置条件无法在当前实现上通过验证。
- 重复 task_id 测试依赖首次创建成功，因此当前失败发生在首次创建阶段。
- path 已存在测试当前先触发 `_branch_exists` fatal，因此无法验证实现是否优先报告 `WorktreePathConflictError`。
- 未执行覆盖率命令，因为用户本次未指定覆盖率要求。

## 9. Day2 最终结论

部分通过。

正式 pytest 测试开发已完成：新增了 `tests/git/test_worktree.py`，并对既有测试 helper 做了静态检查兼容调整；所有测试都使用 `tmp_path` 独立临时 Git 仓库、仓库本地 Git config、argv 列表、`shell=False`、timeout 和输出捕获。

被测功能验收未通过：`WorktreeManager.create()` 当前仍因 `_branch_exists("codeteam/<task_id>")` 失败而无法创建 linked worktree。ruff 和 mypy 均通过。
