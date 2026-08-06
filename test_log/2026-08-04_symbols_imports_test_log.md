# 符号提取与导入图测试报告

**日期**: 2026-08-04
**测试工程师**: 自动化测试 Agent
**分支**: worktree-test_agent_parsing (基于 week2)
**测试目标**: codeteam.symbols (extractor, index) 和 codeteam.imports (extractor, resolver, graph, module_index)

---

## 1. 项目检查结果

```
技术栈：       Python 3.11, tree-sitter 0.26
测试框架：     pytest 9.1.1
目标模块：
  - codeteam/symbols/
    - models.py      (Symbol, SymbolKind, SymbolLocation, SymbolIndex, Reference...)
    - extractor.py   (SymbolExtractor: ast.NodeVisitor)
    - index.py       (SymbolIndex: find_exact, find_qualified, find_prefix...)
  - codeteam/imports/
    - models.py      (ImportRecord, ImportKind, ImportResolution, ResolveStatus, ImportEdge)
    - extractor.py   (ImportExtractor: 提取 import 语句)
    - resolver.py    (PythonImportResolver: 解析为文件路径)
    - graph.py       (ImportGraph: 文件依赖图，BFS 遍历)
    - module_index.py (ModuleIndex: 模块名↔文件路径 双向索引)
读取的主要文件：
  - 上述所有模块 + codeteam/parsing/* (回归)
发现的接口：
  - SymbolExtractor(file_path).extract(tree) -> (list[Symbol], list[Reference])
  - SymbolIndex().add(symbol) / find_exact(name) / find_qualified(qn) / find_prefix(prefix)
  - ImportExtractor(file_path).extract(tree) -> list[ImportRecord]
  - PythonImportResolver(module_index).resolve(record) -> ImportResolution
  - ImportGraph().add_edge(source, target) / dependencies_of() / dependents_of() / neighbors()
  - ModuleIndex(file_list).resolve_module(name) / get_module(path)
现有测试情况：  tests/symbols/ 和 tests/imports/ 此前不存在
```

## 2. 测试需求覆盖情况

| 编号 | 测试要求 | 对应测试 | 状态 |
|------|---------|---------|------|
| T01 | 普通 import (import app.service / as...) | `TestPlainImport` (3 tests) | ✅ 通过 |
| T02 | from import (from X import Y / as Z) | `TestFromImport` (3 tests) | ✅ 通过 |
| T03 | 相对 import (from .service / from . import / ..) | `TestRelativeImport` (4 tests) | ✅ 通过 |
| T04 | 别名 (as 绑定) | `TestAlias` (3 tests) | ✅ 通过 |
| T05 | __init__.py 模块名 | `TestInitPy` (3 tests) | ✅ 通过 |
| T06 | 嵌套类 qualified names + SymbolKind | `TestNestedClass` (3 tests) | ❌ 失败 (生产缺陷) |
| T07 | 同名方法 (find_exact 返回多个) | `TestSameNameMethods` (4 tests) + `TestFindExactSameName` (2 tests) | ❌ 部分 (index 通过，extractor 失败) |
| T08 | 外部依赖 (EXTERNAL) | `TestExternalDependency` (3 tests) + `TestExternalResolution` (3 tests) | ✅ 通过 |
| T09 | 循环 import (安全终止) | `TestCycleImport` (5 tests) | ✅ 通过 |
| T10 | 动态 import (DYNAMIC / UNRESOLVED) | `TestDynamicImport` (3 tests) | ❌ 失败 (生产缺陷) |
| — | 解析器回归 (T01-T11 from parsing) | `tests/parsing/` (38 tests) | 37 通过, 1 已知缺陷 |

## 3. 新增或修改文件

```
新增：
  tests/symbols/__init__.py
  tests/symbols/test_extractor.py       (15 tests)
  tests/symbols/test_index.py           (14 tests)
  tests/imports/__init__.py
  tests/imports/test_extractor.py       (20 tests)
  tests/imports/test_resolver.py        (14 tests)
  tests/imports/test_graph.py           (12 tests)
  test_log/2026-08-04_symbols_imports_test_log.md  (本文件)

修改：
  prompt/test_Agent.md  (更新测试日志写入规则)
  tests/parsing/test_parsers.py  (已存在于先前 commit)
  tests/parsing/test_registry.py  (已存在于先前 commit)
```

## 4. 执行命令

```
python -m pytest tests/symbols/ tests/imports/ tests/parsing/ -v
python -m pytest tests/ --ignore=tests/symbols --ignore=tests/imports --ignore=tests/parsing -q  # 回归
```

## 5. 测试结果

```
通过：   96
失败：   17
跳过：   0
错误：   0
总耗时： ~0.06s

新增测试:  75 (symbols: 29, imports: 46)
回归测试:  83 (全部通过)
```

## 6. 覆盖率结果

```
Name                                     Stmts   Miss  Cover
------------------------------------------------------------
codeteam/imports/__init__.py                 0      0   100%
codeteam/imports/extractor.py               49      4    92%
codeteam/imports/graph.py                   27      0   100%
codeteam/imports/models.py                  19      0   100%
codeteam/imports/module_index.py            22      1    95%
codeteam/imports/resolver.py                42      0   100%
codeteam/symbols/__init__.py                 0      0   100%
codeteam/symbols/extractor.py               88     16    82%
codeteam/symbols/index.py                   35      0   100%
codeteam/symbols/models.py                  35      0   100%
------------------------------------------------------------
TOTAL (symbols + imports)                  317     21    93%
```

总体覆盖率: **93%** (317 语句, 21 未覆盖)
未覆盖主要集中在:
- `symbols/extractor.py`: `_extract_parameters()` 方法缺失导致功能不可用区的代码未覆盖
- `imports/extractor.py`: `_extract_string_arg()` 方法缺失导致动态 import 路径未覆盖

## 7. 失败测试与生产代码缺陷

### 缺陷 1: SymbolExtractor._extract_parameters() 未定义 [BLOCKING]

| 项目 | 内容 |
|------|------|
| 影响模块 | `codeteam/symbols/extractor.py` |
| 失败测试 | 12 个 (全部涉及函数/类解析的提取测试) |
| 复现命令 | `pytest tests/symbols/test_extractor.py -v` |
| 预期结果 | 解析函数/类源码后提取参数、签名、装饰器 |
| 实际结果 | `AttributeError: 'SymbolExtractor' object has no attribute '_extract_parameters'` |
| 原因 | `_visit_function()` 第 140 行调用 `self._extract_parameters(node.args)` 但该方法未定义 |
| 稳定性 | 每次解析包含函数定义的源码必现 |

### 缺陷 2: ImportExtractor._extract_string_arg() 未定义 [BLOCKING]

| 项目 | 内容 |
|------|------|
| 影响模块 | `codeteam/imports/extractor.py` |
| 失败测试 | 3 个动态 import 测试 |
| 复现命令 | `pytest tests/imports/test_extractor.py::TestDynamicImport -v` |
| 预期结果 | 从 `__import__("x")` 和 `importlib.import_module("x")` 提取字符串参数 |
| 实际结果 | `AttributeError: 'ImportExtractor' object has no attribute '_extract_string_arg'` |
| 原因 | `visit_Call()` 第 107 行调用 `self._extract_string_arg(node)` 但该方法未定义 |
| 稳定性 | 每次遇到 `importlib.import_module(...)` 必现 |

### 缺陷 3: PythonImportResolver 未使用 record.name 解析 `from . import X`

| 项目 | 内容 |
|------|------|
| 影响模块 | `codeteam/imports/resolver.py` |
| 失败测试 | `test_resolve_relative_dot_only` |
| 复现命令 | `pytest tests/imports/test_resolver.py::TestRelativeImportResolution::test_resolve_relative_dot_only -v` |
| 预期结果 | `app/api.py` 中 `from . import repository` → 解析到 `app/repository.py` |
| 实际结果 | 解析到 `app/__init__.py`（target_module 计算为 `app` 而非 `app.repository`） |
| 原因 | `_resolve_relative()` 在 `target_name` 为空时未使用 `record.name` 追加目标模块 |

### 缺陷 4: TreeSitterParser 对 bytes 输入抛 AttributeError (已知)

| 项目 | 内容 |
|------|------|
| 影响模块 | `codeteam/parsing/tree_sitter_parser.py` |
| 失败测试 | `TestNonUTF8::test_tree_sitter_does_not_raise_on_bytes_input` |
| 原因 | `parse()` 中 `source_code.encode("utf-8")` — bytes 类型没有 `.encode()` 方法 |

## 8. 验收结果

| 验收项 | 结果 | 证据 |
|--------|------|------|
| T01 普通 import 提取 | 通过 | `TestPlainImport` (3/3) |
| T02 from import 提取 | 通过 | `TestFromImport` (3/3) |
| T03 相对 import 提取 | 通过 | `TestRelativeImport` (4/4) |
| T04 别名绑定 | 通过 | `TestAlias` (3/3) |
| T05 __init__.py 模块名 | 通过 | `TestInitPy` (3/3) |
| T06 嵌套类 | 未通过 | 12 个提取测试因缺陷 1 失败 |
| T07 同名方法 | 部分通过 | Index 查询通过 (6/6), Extractor 失败 |
| T08 外部依赖 | 通过 | Extract + Resolve 共 6 个测试全部通过 |
| T09 循环 import | 通过 | `TestCycleImport` (5/5), BFS 安全终止 |
| T10 动态 import | 未通过 | 3 个测试因缺陷 2 失败 |
| 解析器回归 | 部分通过 | 37/38, 1 已知缺陷 |
| 已有测试回归 | 通过 | 83 个已有测试全部通过 |
| 日志以新文件写入 | 通过 | `2026-08-04_symbols_imports_test_log.md` |
| prompt 文件更新 | 通过 | 第 1116 行增加了新文件写入要求 |

## 9. 风险和未完成项

```
未测试内容：
  - SymbolIndex 的并发安全性
  - 大型仓库 (1000+ 文件) 的 ImportGraph 性能
  - 循环 import 深度 >100 的 BFS 内存使用

无法验证内容：
  - SymbolExtractor._extract_parameters() 的正确实现（方法未定义）
  - ImportExtractor._extract_string_arg() 的正确实现（方法未定义）
  - neighbors() 接受 depth 参数（实际 API 不支持）

环境限制：
  - 无

跨平台风险：
  - 路径分隔符 (ModuleIndex._path_to_module 使用 "/")

不稳定测试：
  - 无

后续建议：
  1. **紧急**: 实现 SymbolExtractor._extract_parameters() 方法
  2. **紧急**: 实现 ImportExtractor._extract_string_arg() 方法
  3. 修复 PythonImportResolver 对 `from . import X` 的处理
  4. 修复 TreeSitterParser 对 bytes 输入的健壮性
  5. 考虑 ImportGraph.neighbors() 增加 depth 参数
  6. 考虑 parse() 签名改为接受 str | bytes
```

## 10. 测试设计说明

### 符号提取测试 (test_extractor.py)

由于 SymbolExtractor 的实际 API 与需求文档存在差异，测试已适配真实接口：

| 差异 | 需求文档 | 实际实现 |
|------|---------|---------|
| 类名 | `PythonSymbolExtractor` | `SymbolExtractor` |
| 构造参数 | `path, module_name, source` | `file_path` |
| 入口方法 | `visit(tree)` | `extract(tree)` → (symbols, references) |
| qualified_name 分隔符 | `::` (如 `app.nested::Outer`) | `.` (如 `Outer`, `Outer.Inner`) |
| module_name 来源 | 显式传入 | 由 file_path 隐式表达 |

### 符号索引测试 (test_index.py)

全部使用公开 API (add, find_exact, find_qualified, find_prefix, symbols_in_file, references_to)，不依赖 Extractor。

### 导入图测试 (test_graph.py)

已验证 BFS 遍历在循环图中安全终止：
- 两节点循环: a↔b, depth=5 和 depth=None 均安全终止
- 三节点循环: a→b→c→a, depth=None 安全终止
- BFS 不会重复访问已加入 visited 的节点
```
