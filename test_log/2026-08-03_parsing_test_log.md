# 解析模块测试报告

**日期**: 2026-08-03
**测试工程师**: 自动化测试 Agent
**分支**: worktree-test_agent_parsing (基于 week2)
**测试目标**: codeteam.parsing 模块（PythonAstParser, TreeSitterParser, ParserRegistry）

---

## 1. 项目检查结果

```
技术栈：       Python 3.11, tree-sitter 0.26, tree-sitter-python 0.25
测试框架：     pytest 9.1.1
目标模块：     codeteam.parsing (models, base, python_ast_parser, tree_sitter_parser, registry)
读取的主要文件：
  - codeteam/parsing/models.py        (数据模型)
  - codeteam/parsing/base.py          (CodeParser Protocol)
  - codeteam/parsing/python_ast_parser.py  (Python AST 解析器)
  - codeteam/parsing/tree_sitter_parser.py (Tree-sitter 解析器)
  - codeteam/parsing/registry.py      (解析器注册中心)
发现的接口：
  - PythonAstParser(max_file_size).parse(source_code: str, file_path: str) -> ParseResult
  - TreeSitterParser(max_file_size).parse(source_code: str, file_path: str) -> ParseResult
  - ParserRegistry().register() / get() / get_default() / parse()
  - ParseStatus: SUCCESS, FAILED, PARTIAL
  - DiagnosticKind: ERROR, WARNING, INFO
现有测试情况：  tests/parsing/ 目录此前不存在；首次建立
```

## 2. 测试需求覆盖情况

| 编号 | 测试要求 | 对应测试 | 状态 |
|------|---------|---------|------|
| T01 | 正常 Python 文件（AST SUCCESS, TS SUCCESS, class=1, func=2） | `TestNormalFile` (3 tests) | 通过 |
| T02 | 空文件（双方 SUCCESS, 统计均为 0） | `TestEmptyFile` (2 tests) | 通过 |
| T03 | 语法错误（AST FAILED, TS PARTIAL + 提取 valid） | `TestSyntaxError` (2 tests) | 通过 |
| T04 | 缺少括号（AST FAILED, TS PARTIAL + diagnostics 非空） | `TestMissingParen` (3 tests) | 通过 |
| T05 | 非 UTF-8（AST 成功, TS 安全失败不抛异常） | `TestNonUTF8` (4 tests) | 1 失败 (已知缺陷) |
| T06 | 超大文件（PARTIAL, 不真正解析） | `TestLargeFile` (3 tests) | 通过 |
| T07 | AST 与 Tree-sitter 数量对照 | `TestCountComparison` (6 tests) | 通过 |
| T08 | Registry 默认选择 | `TestRegistryDefaultSelection` (3 tests) | 通过 |
| T09 | Registry 指定选择 | `TestRegistrySpecificSelection` (3 tests) | 通过 |
| T10 | 未知语言 | `TestUnknownLanguage` (5 tests) | 通过 |
| T11 | 未知 Parser | `TestUnknownParser` (4 tests) | 通过 |

## 3. 新增或修改文件

```
新增：
  tests/parsing/__init__.py
  tests/parsing/test_parsers.py       (22 tests)
  tests/parsing/test_registry.py      (16 tests)

修改：
  无

删除：
  无
```

## 4. 执行命令

```
# 运行解析测试
python -m pytest tests/parsing/ -v

# 运行现有回归测试
python -m pytest tests/ --ignore=tests/parsing --ignore=tests/repository -q

# 覆盖率
python -m coverage run -m pytest tests/parsing/ -q
python -m coverage report --include="codeteam/parsing/*"
```

## 5. 测试结果

```
通过：   37
失败：   1
跳过：   0
错误：   0
总耗时： ~0.04s

新增测试:  38
回归测试:  83 (全部通过，无回归)
```

### 5.1 失败详情

| 测试名称 | `TestNonUTF8::test_tree_sitter_does_not_raise_on_bytes_input` |
|---------|---------------------------------------------------------------|
| 预期结果 | Tree-sitter 收到 bytes 输入时不应抛未捕获异常，应安全返回错误状态 |
| 实际结果 | `AttributeError: 'bytes' object has no attribute 'encode'` |
| 原因分类 | 生产代码缺陷 |
| 是否生产缺陷 | **是** — `TreeSitterParser.parse()` 直接调用 `source_code.encode("utf-8")`，但 `bytes` 类型没有 `.encode()` 方法（应使用 `.decode()`），导致未捕获的 AttributeError 传播，可能使扫描器退出 |

## 6. 覆盖率结果

```
Name                                     Stmts   Miss  Cover
------------------------------------------------------------
codeteam/parsing/__init__.py                 0      0   100%
codeteam/parsing/base.py                     8      0   100%
codeteam/parsing/models.py                  39      0   100%
codeteam/parsing/python_ast_parser.py       36      2    94%
codeteam/parsing/registry.py                31      0   100%
codeteam/parsing/tree_sitter_parser.py      39      1    97%
------------------------------------------------------------
TOTAL                                      153      3    98%
```

总体覆盖率： 98%
未覆盖：
- `python_ast_parser.py`: UnicodeEncodeError 分支（UTF-8 编码检测失败路径）
- `tree_sitter_parser.py`: UnicodeEncodeError 分支（同上）

注：UnicodeEncodeError 分支在当前 `parse(str)` 接口下难以触发（所有 Unicode 均可编码为 UTF-8），需接口改为接受 `bytes` 后方可正常覆盖。

## 7. 生产代码缺陷

### 缺陷 1：TreeSitterParser 对 bytes 输入抛未捕获异常

#### 影响模块

`codeteam/parsing/tree_sitter_parser.py`

#### 对应测试

`tests/parsing/test_parsers.py::TestNonUTF8::test_tree_sitter_does_not_raise_on_bytes_input`

#### 前置条件

调用方错误传入 `bytes` 类型（如直接从文件读取的原始字节），而非预期的 `str`。

#### 复现步骤

1. 创建 `TreeSitterParser()` 实例
2. 传入 `bytes` 数据: `b"# -*- coding: latin-1 -*-\nname = 'caf\xe9'\n"`
3. 调用 `parse()`

#### 预期结果

返回 `ParseResult(status=PARTIAL, diagnostics=[...])` 或等效错误结果，不抛异常。

#### 实际结果

`AttributeError: 'bytes' object has no attribute 'encode'`

#### 错误信息

```
codeteam/parsing/tree_sitter_parser.py:39: in parse
    source_bytes = source_code.encode("utf-8")
AttributeError: 'bytes' object has no attribute 'encode'
```

#### 稳定性

- 是否稳定复现：是
- 复现次数：每次传入 bytes 必现
- 影响平台：全部

#### 初步原因

`parse()` 签名声明 `source_code: str`，但未做运行时类型检查。当传入 `bytes` 时，`source_code.encode("utf-8")` 调用失败 — `bytes` 对象没有 `.encode()` 方法（应使用 `.decode()` 将 bytes 转为 str）。

`PythonAstParser` 有同样的问题：它也在 `parse()` 中调用 `source_code.encode("utf-8")`。

#### 建议

1. 在 `parse()` 入口增加类型守卫：`if isinstance(source_code, bytes): source_code = source_code.decode("utf-8", errors="replace")`
2. 或将 `parse()` 的签名改为接受 `str | bytes`（更健壮）
3. `PythonAstParser` 应做相同修复

### 缺陷 2：ParseStatus 缺少 SKIPPED 枚举值

#### 影响模块

`codeteam/parsing/models.py`

#### 描述

需求要求超大文件返回 `ParseStatus.SKIPPED`，但枚举只有 `SUCCESS`、`FAILED`、`PARTIAL`。当前实现用 `PARTIAL` 代替。

#### 建议

增加 `SKIPPED = "skipped"` 枚举值，用于"未执行解析但也不视为错误"的场景（如文件过大跳过）。

### 缺陷 3：构造参数名不一致

#### 影响模块

`codeteam/parsing/python_ast_parser.py`、`codeteam/parsing/tree_sitter_parser.py`

#### 描述

需求文档使用 `max_source_bytes`，实现使用 `max_file_size`。两者语义相近但不同（`max_file_size` 更清晰）。

#### 建议

统一命名或确认需求中的 `max_source_bytes` 只是示意性命名。

## 8. 验收结果

| 验收项 | 结果 | 证据 |
|--------|------|------|
| T01 正常文件解析 | 通过 | `test_parsers.py::TestNormalFile` 全部 (3/3) |
| T02 空文件处理 | 通过 | `test_parsers.py::TestEmptyFile` 全部 (2/2) |
| T03 语法错误处理 | 通过 | `test_parsers.py::TestSyntaxError` 全部 (2/2) |
| T04 缺少括号处理 | 通过 | `test_parsers.py::TestMissingParen` 全部 (3/3) |
| T05 非 UTF-8 处理 | 部分通过 | 3/4 通过；1 失败为生产缺陷 |
| T06 超大文件 | 通过 | `test_parsers.py::TestLargeFile` 全部 (3/3) |
| T07 统计对照 | 通过 | `test_parsers.py::TestCountComparison` 全部 (6/6) |
| T08 Registry 默认选择 | 通过 | `test_registry.py::TestRegistryDefaultSelection` 全部 (3/3) |
| T09 Registry 指定选择 | 通过 | `test_registry.py::TestRegistrySpecificSelection` 全部 (3/3) |
| T10 未知语言 | 通过 | `test_registry.py::TestUnknownLanguage` 全部 (5/5) |
| T11 未知 Parser | 通过 | `test_registry.py::TestUnknownParser` 全部 (4/4) |
| 回归测试 | 通过 | 83 个已有测试全部通过 |
| 测试日志写入 ./test_log | 通过 | `test_log/2026-08-03_parsing_test_log.md` |

## 9. 风险和未完成项

```
未测试内容：
  - parse() 中 UnicodeEncodeError 分支（当前 str 接口无法触发）
  - 超大文件的边界值（恰好等于 max_file_size 的情况）
  - Tree-sitter 解析极大嵌套深度的代码
  - 并发调用解析器

无法验证内容：
  - ParseStatus.SKIPPED（枚举中不存在该值）
  - DiagnosticKind.FILE_TOO_LARGE（枚举中不存在该值）

环境限制：
  - tree-sitter-python Grammar 版本可能影响 MISSING 节点的具体类型

跨平台风险：
  - 路径分隔符行为（parse() 中仅作透传，风险较低）

不稳定测试：
  - 无

后续建议：
  1. 修复 TreeSitterParser 和 PythonAstParser 对 bytes 输入的健壮性
  2. 增加 ParseStatus.SKIPPED 枚举值
  3. 考虑将 parse() 签名改为接受 str | bytes
  4. 补充边界值测试（恰好等于 max_file_size）
  5. 补充并发安全性测试
```
