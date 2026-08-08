# Week 2 Code Context Retrieval Evaluation

## 1. Objective

评测 CodeTeam 检索管线是否能针对代码任务，将关键文件排进 Top 5。

## 2. System Under Test

完整管线：RepositoryScanner → ParserRegistry → SymbolExtractor + ImportExtractor → SymbolIndex + ImportGraph → QueryAnalyzer → CandidateGenerator → FileRanker → RepoMapBuilder → ContextSelector → ContextCompressor

## 3. Repository

- Repository: `tests/fixtures/test_repo/`
- Total files: 16 (14 Python, 1 Markdown, 1 TOML)
- Symbol count: ~1500
- Import edge count: 8 (local)
- Python files parsed: 14/14 success

## 4. Dataset

- Total queries: 27
- Exact symbol: 4 (sym-001 ~ sym-004)
- Error message: 4 (err-001 ~ err-004)
- Business behavior: 4 (biz-001 ~ biz-004)
- Config/test: 5 (cfg-001 ~ cfg-005)
- Cross-module: 4 (crs-001 ~ crs-004)
- Import graph: 2 (imp-001 ~ imp-002)
- Symbol prefix: 2 (sym-005 ~ sym-006)
- Chinese business: 2 (cn-001 ~ cn-002)

**Gold Annotation Policy:**
- required files: 必须查看或修改才能完成任务的文件
- supporting files: 可能有帮助，但不是必要的文件
- maximum required files per query: 5
- 标注方式：先人工阅读代码确定 Gold，再运行实验

## 5. Experimental Methods

| Method | Filename Index | Ripgrep | Symbol Index | Import Graph |
|---|---|---|---|---|
| **filename** | ✅ | ❌ | ❌ | ❌ |
| **ripgrep** | ✅ | ✅ | ❌ | ❌ |
| **ripgrep_symbol** | ✅ | ✅ | ✅ | ❌ |
| **hybrid** | ✅ | ✅ | ✅ | ✅ |

## 6. Metrics

- **Recall@5**: `|Gold ∩ Top5| / |Gold|` — 相关文件在 Top 5 中的比例
- **Hit@5**: `1 if Recall@5 > 0 else 0` — 至少命中一个相关文件
- **Macro Recall@5**: 所有查询的 Recall@5 平均值（每查询等权重）

## 7. Overall Results

| Method | Recall@5 | Hit@5 | Mean Latency |
|---|---|---|---|
| filename | 0.472 | 0.593 | 0ms |
| ripgrep | 0.969 | 1.000 | 43ms |
| ripgrep + Symbol | 0.969 | 1.000 | 42ms |
| **Hybrid** | **1.000** | **1.000** | 42ms |

## 8. Category Results

| Category | filename | ripgrep | rg+Symbol | Hybrid |
|---|---|---|---|---|
| Exact symbol | 0.750 | **1.000** | **1.000** | **1.000** |
| Error message | 0.000 | **1.000** | **1.000** | **1.000** |
| Business behavior | 0.250 | **1.000** | **1.000** | **1.000** |
| Config/test | **1.000** | **1.000** | **1.000** | **1.000** |
| Cross-module | 0.604 | **1.000** | **1.000** | **1.000** |
| Import graph | 0.417 | 0.583 | 0.583 | **1.000** |
| Symbol prefix | 0.000 | **1.000** | **1.000** | **1.000** |
| Chinese business | 0.250 | **1.000** | **1.000** | **1.000** |

## 9. Ablation Findings

### 9.1 Filename → Ripgrep (+0.497 Recall, +0.407 Hit)

文件名匹配可以处理显式路径、配置文件名和部分模块名，但自然语言查询和代码文件名之间仍有明显语义鸿沟。加入 ripgrep 全文搜索后，英文符号、错误消息、中文扩展后的英文代码词以及 AGENTS.md/pyproject.toml 等非 Python 文件都能被召回。

### 9.2 Ripgrep → Ripgrep+Symbol (+0.000 Recall, +0.000 Hit)

本次复跑中 ripgrep 已能覆盖 symbol/prefix 查询，SymbolIndex 没有进一步提升总体 Top5 指标。`sym-005` / `sym-006` 虽然是 prefix 类查询，但 ripgrep 对类名子串仍然足够强，因此 SymbolIndex 的边际收益仍未被充分隔离。

### 9.3 Ripgrep+Symbol → Hybrid (+0.031 Recall, Hit 持平)

Import Graph 在新增的 `imp-001` / `imp-002` 上带来明确提升：当 query 显式给出入口文件并询问依赖链路时，Hybrid 会从显式路径种子扩展到 import 依赖文件。`import_graph` 类别从 ripgrep/ripgrep_symbol 的 0.583 提升到 Hybrid 的 1.000。

### 9.4 关键结论

- **ripgrep 仍是最大贡献者**：相对 filename 带来 +49.7% Recall 提升
- **filename 方法已修复静默失败问题**：不再因内部异常产生全空预测
- **中文业务 query 已被基础扩展覆盖**：business/chinese business 类别本轮达到 1.000
- **Hybrid 现在体现 ImportGraph 增益**：import_graph 类别从 0.583 提升到 1.000
- **SymbolIndex 仍需更强区分数据**：当前 prefix case 仍可被 ripgrep 子串匹配解决

## 10. Failure Cases

Hybrid 本轮 27 条 case 没有未命中的 Gold 文件，`errors=0`，`empty predictions=0`。

仍需关注的非 Hybrid 失败：

- `imp-001` / `imp-002`: ripgrep 和 ripgrep_symbol 无法完整追回 import 依赖文件，Hybrid 通过 ImportGraph 修复。
- `sym-005` / `sym-006`: filename baseline 完全失败，ripgrep 和 symbol 方法均可命中。
- 中文 business/config 查询：filename baseline 仍弱，但 ripgrep 结合 QueryAnalyzer domain expansion 后可以召回。

## 11. False Positive Analysis

错误召回到 Top 5 的不相关文件：

- **src/main.py** 频繁出现在 Top 5 中：作为入口文件，基础权重偏高
- **tests/test_auth.py** 多次出现：文件名含 "test"，test_relevance 信号偏高
- **src/auth/api.py** 在非 API 相关查询中出现：被 ImportGraph 从 service.py 扩展

## 12. Missed File Analysis

Hybrid 当前没有 Gold 文件遗漏。剩余分析重点转为 ablation 差异：

| Pattern | Affected methods | Explanation |
|---|---|---|
| Import dependency files | ripgrep, ripgrep_symbol | 文本搜索能命中入口文件，但不能稳定补齐入口文件 import 的依赖文件 |
| Symbol prefix queries | filename | 文件名 baseline 无法从符号前缀定位异常类定义 |
| Chinese business queries | filename | 仅靠文件名仍无法稳定桥接中文业务描述和英文代码命名 |

## 13. Limitations

- 只有一个仓库（16 个文件）
- 只有 27 条查询
- 主要是 Python
- 人工标注 Gold Files（标签可能不完美）
- 评测数据创建者和系统开发者是同一人（有偏见风险）
- 当前数据集偏小，已经能看到 ImportGraph 增益，但仍难以充分隔离 SymbolIndex 的边际贡献

## 14. Next-week Improvements

### Improvement 1: 扩展 QueryAnalyzer 中文→英文映射

**Evidence:** 当前小词典已覆盖 refresh token、库存、订单导出、数据库会话和生成代码规则，但范围仍很窄。

**Change:** 将当前硬编码词典演进为可配置 domain mapping，并加入更多业务短语。

**Expected effect:** 在更多中文自然语言任务上保持稳定召回。

### Improvement 2: 设计更强 SymbolIndex 区分 case

**Evidence:** ripgrep 和 ripgrep_symbol 本轮指标仍然持平，说明当前 symbol/prefix case 仍可被文本子串匹配解决。

**Change:** 增加只靠符号结构能稳定解决、但文本搜索信号弱或噪声大的 case。

**Expected effect:** 更客观评估 SymbolIndex 相对 ripgrep 的边际收益。

### Improvement 3: 非 Python 文件索引产品化

**Evidence:** 本轮通过 ripgrep 搜索 Markdown/TOML 和 domain expansion 解决 AGENTS.md/config 召回，但仍是轻量规则。

**Change:** 给 instruction/config 文件建立独立索引，区分命令、限制、依赖、测试配置等结构化字段。

**Expected effect:** 避免仅靠全文搜索匹配规则文档。

### Improvement 4: 测试文件映射

**Evidence:** 测试文件当前能被部分 query 召回，但源码到测试文件的映射仍偏启发式。

**Change:** 在 CandidateGenerator 中增加源码→测试的 import 映射。

**Expected effect:** test-related 查询的 Recall 提升。

### Improvement 5: 扩展到更多仓库和语言

**Evidence:** 当前只有 1 个 Python 仓库、27 条数据。

**Change:** 准备更多语言的评测仓库（TypeScript/JavaScript），扩展到 50-100 条数据。

## 15. Reproducibility

Values below are copied from the latest `evals/week2/*.manifest.json` files.

```text
Run manifests:   evals/week2/{filename,ripgrep,ripgrep_symbol,hybrid}.manifest.json
Repository:      /Users/root/workspace/Agent-Learning/tests/fixtures/test_repo
Repo dirty:      true
Dataset:         evals/week2/file_retrieval.jsonl
Dataset SHA256:  4a635b8eb1968c286055f45895616f320d2ba54331fdb209969a5a4771dec7cb
Python:          3.11.15
ripgrep:         ripgrep 15.2.0 (rev e89fff89ac)
Parser:          tree_sitter-installed
Ranking:         week2-v2 (weights recorded in each manifest)
Top K:           5
Candidate limit: 50
Context budget:  0
```

The manifest also records `started_at`, exact `command_argv`, `dirty_summary`,
and diagnostics summary for each method.
