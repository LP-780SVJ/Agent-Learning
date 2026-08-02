# Repository Test Log - 2026-08-03

## Task Summary

根据 `prompt/test_Agent.md` 的测试与验收要求，为 repository 扫描相关模块新增自动化测试，并实际执行测试。

本次测试开发只新增测试文件，未修改项目源代码。

## Project Check

```text
技术栈：Python 3.11
测试框架：unittest
目标模块：codeteam/repository/*
主要接口：RepositoryScanner、FileClassifier、LanguageDetector、DirectoryTreeRenderer、RepositoryFile、RepositorySnapshot
缺失接口：codeteam/repository/git_inventory.py
已有测试情况：此前无 tests/repository 测试；原有 83 个 unittest 测试通过
```

## Added Test Files

```text
tests/repository/__init__.py
tests/repository/test_git_inventory.py
tests/repository/test_file_classifier.py
tests/repository/test_scanner.py
tests/repository/test_tree_renderer.py
```

## Commands Executed

```bash
.venv/bin/python -m unittest discover -s tests/repository
.venv/bin/python -m unittest discover tests
.venv/bin/python -m coverage --version
.venv/bin/python -m ruff check tests/repository
.venv/bin/python -m mypy tests/repository
```

## Test Results

```text
repository 焦点测试：16 个执行，4 通过，11 失败，1 错误
全量测试：99 个执行，87 通过，11 失败，1 错误，总耗时 0.504s
覆盖率：未执行，当前 .venv 未安装 coverage
Lint：未执行，当前 .venv 未安装 ruff
类型检查：未执行，当前 .venv 未安装 mypy
```

## Coverage Matrix

| 编号 | 测试要求 | 对应测试 | 状态 |
| --- | --- | --- | --- |
| T01 | tracked 正常文件标记 tracked | `test_marks_tracked_and_untracked_files_separately_before_commit` | 失败：`git_inventory.py` 缺失 |
| T02 | untracked 新文件标记 untracked | `test_marks_tracked_and_untracked_files_separately_before_commit` | 失败：`git_inventory.py` 缺失 |
| T03 | `.gitignore` 文件不进入可见清单 | `test_ignored_untracked_file_is_hidden_but_tracked_file_stays_visible` | 失败：`git_inventory.py` 缺失 |
| T04 | 已 tracked 后再 ignore 仍是 tracked | `test_git_scan_keeps_tracked_file_after_ignore_rule_is_added` | 失败：`RepositoryFile` 无 Git 状态字段 |
| T05 | 文件名包含空格正确解析 | `test_git_scan_preserves_space_unicode_and_newline_paths` | 通过 |
| T06 | 文件名包含中文正确解析 | `test_git_scan_preserves_space_unicode_and_newline_paths` | 通过 |
| T07 | 文件名包含换行，`-z` 正确处理 | `test_git_scan_preserves_space_unicode_and_newline_paths` | 通过 |
| T08 | 符号链接指向仓库外不跟随 | `test_non_git_directory_falls_back_to_filesystem_scan_and_filters_noise` | 失败：symlink 仍进入清单 |
| T09 | 二进制文件标记 binary | `test_binary_extension_is_marked_binary` | 失败：标记为 unknown |
| T10 | `generated/` 文件标记 generated | `test_generated_directory_is_marked_generated` | 失败：标记为 source |
| T11 | `test_*.py` 标记 test | `test_test_python_file_keeps_language_separate_from_role` | 通过 |
| T12 | `AGENTS.md` 标记 instruction、高重要性 | `test_scan_marks_binary_generated_tests_and_high_importance_instructions` | 部分通过：instruction 通过，importance 字段缺失 |
| T13 | tracked 文件被删除标记 deleted | `test_git_scan_marks_deleted_tracked_file_without_stat_failure` | 错误：对已删除文件执行 `stat()` |
| T14 | 非 Git 目录回退到文件系统扫描 | `test_non_git_directory_falls_back_to_filesystem_scan_and_filters_noise` | 部分通过：能回退，但未过滤噪声 |
| T15 | `node_modules` 忽略或折叠 | `test_node_modules_file_is_marked_vendored_for_folding_or_ignoring`、scanner 测试 | 部分通过：classifier 标 vendored，scanner 仍展开 |

## Failure Analysis

```text
失败类型：接口尚未实现
影响测试：test_git_inventory.py 中 4 个测试
实际结果：ModuleNotFoundError: No module named 'codeteam.repository.git_inventory'
建议：新增 git_inventory.py，并暴露 GitInventory 或 GitRepositoryInventory。

失败类型：生产代码缺陷
影响测试：scanner 中 Git 状态相关测试
实际结果：RepositoryFile 无 status/git_status/state 字段
建议：RepositoryFile 增加 tracked/untracked/deleted 状态模型，Scanner 同时合并 tracked、untracked、deleted 信息。

失败类型：生产代码缺陷
影响测试：test_git_scan_marks_deleted_tracked_file_without_stat_failure
实际结果：FileNotFoundError，Scanner 对 deleted 文件执行 full_path.stat()
建议：deleted tracked 文件不应依赖工作区实体存在，可记录 size_bytes=0 或 None。

失败类型：生产代码缺陷
影响测试：generated、binary、AGENTS.md 高重要性、node_modules、symlink 相关测试
实际结果：分类或过滤逻辑缺失
建议：补充 generated 目录、二进制识别、importance 字段、vendored 折叠/忽略和 symlink 越界过滤。

失败类型：生产代码缺陷
影响测试：test_tree_renderer.py
实际结果：NameError: name 'dataclass' is not defined
建议：补齐 tree_renderer.py 所需导入，并保证模块可正常 import。
```

## Acceptance Notes

```text
git add 后尚未 commit 的文件属于 tracked：因为它已进入 Git index，git ls-files 会列出。
.gitignore 不能忽略已 tracked 文件：ignore 只影响未跟踪候选文件，不会移除 index 中已有文件。
Scanner 需要同时读取 tracked 和 untracked：否则会漏掉新建但尚未提交的真实工作区文件。
git ls-files 必须使用 -z：普通换行无法安全解析包含换行的文件名。
git ls-files 与 ripgrep 职责区别：前者获取 Git 文件清单，后者做内容搜索。
文件语言和文件角色必须分开：例如 tests/test_app.py 语言是 python，角色是 test。
Generated 不应直接删除或完全忽略：它可能是协议、客户端或构建产物，应标记并降权处理。
目录树只是压缩视图：用于上下文概览；完整文件列表必须保留给精确检索。
Scanner 不应该跟随符号链接：避免越界读取仓库外内容。
大型仓库需要增量扫描：重复全量扫描成本高，且会重复处理未变化文件。
```

## Final Status

```text
测试代码开发：完成
测试执行：完成
生产功能验收：未通过
剩余风险：coverage、ruff、mypy 未安装，无法生成覆盖率和静态检查证据
```
