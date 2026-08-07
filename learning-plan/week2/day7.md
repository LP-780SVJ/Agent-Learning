# 第 2 周第 7 天：系统整合、20 条评测与报告

今天不再增加新的底层算法，而是把前六天的模块接成一条可运行、可评测、可复现的完整链路。

今天需要完成两种能力：

```text
工程能力：
多个独立模块能否稳定协作，生成可供 Coding Agent 使用的上下文？

评测能力：
这个上下文引擎是否真的能找到正确文件？
哪个模块带来了提升？
失败原因是什么？
```

完整流程如下：

```text
Git 仓库
   ↓
RepositoryScanner
   ↓
ParserRegistry
   ↓
SymbolExtractor + ImportExtractor
   ↓
SymbolIndex + ImportGraph
   ↓
InstructionLoader + CommandDetector
   ↓
QueryAnalyzer
   ↓
CandidateGenerator
   ↓
FileRanker
   ↓
RepoMapBuilder
   ↓
ContextSelector + ContextCompressor
   ↓
ContextPack
   ↓
评测与报告
```

今天最重要的工业化认识是：

> 一个功能“看起来能工作”，不等于它“经过可重复评测后被证明有效”。

---

# 一、工业界如何组织代码理解与评测系统

## 1. Meta Glean：先建立事实索引，再向上提供查询

Meta 公开的 Glean 会提前从源码中提取定义、引用及其他代码事实，再通过统一查询系统提供给代码搜索、跳转、文档生成和静态分析工具。对于大仓库，Meta认为让每个 IDE 或工具启动时重新索引全部代码并不可行，因此把代码事实的生产、存储和查询分成不同层。

映射到 CodeTeam：

```text
事实生产层：
RepositoryScanner
Parser
SymbolExtractor
ImportExtractor

事实存储层：
RepositorySnapshot
SymbolIndex
ImportGraph

查询应用层：
CandidateGenerator
FileRanker
RepoMapBuilder
ContextSelector
```

这意味着 `codeteam context` 不应该重新实现一套扫描、解析和 Import 逻辑，而应消费已经构建好的稳定索引。

---

## 2. Google Code Search：文本检索与语义图共同工作

Google 公布的 Code Search 同时提供正则和类型过滤等文本搜索能力，并使用 Kythe 将定义、声明和引用转成跨语言图。其公开流程会从构建信息生成图，合并不同语言的图数据，再裁剪并优化为适合提供交叉引用服务的索引。

这说明工业代码搜索通常不是单一路线：

```text
ripgrep
擅长：
错误消息、字符串、配置键、精确代码文本

SymbolIndex
擅长：
类、函数、方法定义与引用

ImportGraph
擅长：
依赖关系和上下游扩展

混合检索
把这些证据合并
```

你今天的四组实验，本质上是在验证这套逐步增强路线是否成立。

---

## 3. Aider：把索引压缩为 LLM 可消费的 Repo Map

Aider 会把文件、关键类、函数和调用签名压缩成 Repo Map，并使用依赖图排名，从大型仓库中选出能放入 Token 预算的部分，而不是把全部源码发送给模型。其公开文档说明，Repo Map 的默认预算约为 1K Token，并会根据会话状态动态调整。

你今天整合后的系统也应明确分成：

```text
完整索引
不受 LLM 上下文限制，保留全部事实

Repo Map
面向单次查询，只展示部分结构

ContextPack
真正发送给模型的规则、代码和历史
```

---

## 4. GitHub：离线评测要分成执行、评估和汇总

GitHub 公开的 MCP Server 离线评测流程包含三个阶段：

1. 执行 benchmark，并记录模型实际调用的工具和参数；
2. 处理原始结果并计算指标；
3. 聚合整个数据集的统计，生成报告。

其评测数据为每个自然语言请求标注预期工具和预期参数，从而在发布修改前发现回归。

你的代码检索评测可直接采用相同结构：

```text
Fulfillment / 执行：
对每条 Query 运行检索系统
保存 Top 5、分数、证据、耗时和 Token

Evaluation / 评估：
与 Gold Files 对比
计算 Recall@5、Hit@5

Summarization / 汇总：
按系统版本、方法和任务类别汇总
生成 EVALUATION_WEEK2.md
```

不要边运行边只打印几个百分比。必须先保存每条任务的原始预测，之后才能分析失败案例。

---

# 二、上午：系统整合

# 1. 两个 CLI 命令的职责

## `codeteam inspect-repo`

这个命令回答：

> 当前仓库是什么样的？索引是否健康？

它不接收自然语言任务，主要用于仓库初始化和故障排查。

```bash
codeteam inspect-repo .
```

内部流程：

```text
定位 Git 根目录
   ↓
读取 tracked / untracked / ignored
   ↓
识别文件类型、角色和重要性
   ↓
解析源码
   ↓
提取 Symbol 与 Import
   ↓
解析本地 Import
   ↓
建立 SymbolIndex 和 ImportGraph
   ↓
加载仓库根规则
   ↓
识别构建与测试命令
   ↓
生成 InspectionReport
```

---

## `codeteam context`

这个命令回答：

> 针对当前任务，哪些文件和代码应进入 Agent 上下文？

```bash
codeteam context \
  "修复 refresh token 过期后返回 500 的问题"
```

内部流程：

```text
读取或构建 RepositoryIndex
   ↓
QueryAnalyzer
   ↓
CandidateGenerator
   ↓
FileRanker
   ↓
选出 Top 文件
   ↓
加载适用于这些文件的项目规则
   ↓
构建 Query Repo Map
   ↓
选取相关代码片段
   ↓
执行 Token Budget 压缩
   ↓
生成 ContextReport
```

---

# 三、整合时最重要的六个工程问题

## 1. 所有模块必须使用相同的路径格式

最常见的整合 Bug 是不同模块使用不同路径：

```text
RepositoryScanner：
src/auth/service.py

SymbolIndex：
/Users/lee/project/src/auth/service.py

ImportGraph：
src\auth\service.py

CandidateGenerator：
./src/auth/service.py
```

这样同一个文件会被当成四个文件。

系统内部统一使用：

```text
相对于 Git 仓库根目录
POSIX 风格
不以 ./ 开头
```

例如：

```text
src/auth/service.py
```

统一函数：

```python
from pathlib import Path


def normalize_repo_path(
    repository_root: Path,
    path: Path,
) -> str:
    root = repository_root.resolve(strict=True)
    target = path.resolve(strict=False)

    if not target.is_relative_to(root):
        raise PermissionError(
            f"Path escapes repository: {path}"
        )

    return target.relative_to(root).as_posix()
```

所有以下对象都必须使用这个格式：

```text
RepositoryFile.path
Symbol.path
Reference.path
ImportRecord.source_path
ImportEdge.source_path
ImportEdge.target_path
CandidateFile.path
RankedFile.path
ContextItem.path
```

---

## 2. CLI 不能包含业务逻辑

不推荐：

```python
@app.command()
def inspect_repo(path: str):
    # 这里扫描 Git
    # 这里解析 AST
    # 这里提取 Symbol
    # 这里检测命令
    # 这里打印结果
```

推荐：

```text
CLI
只负责参数解析和展示

Use Case / Application Service
负责组织调用顺序

Domain Modules
负责具体逻辑
```

目录：

```text
codeteam/
├── cli/
│   ├── app.py
│   ├── inspect_command.py
│   └── context_command.py
│
├── application/
│   ├── inspect_repository.py
│   └── build_context.py
│
├── repository/
├── parsing/
├── symbols/
├── imports/
├── search/
├── ranking/
├── repomap/
├── instructions/
└── context/
```

---

## 3. 单个文件失败不能终止整个仓库

真实仓库可能存在：

```text
正在编辑的语法错误文件
无法解码文件
超大生成文件
符号链接
Import 无法解析
缺少 Grammar 的语言
```

整合流程应该返回：

```text
已成功解析 287 个文件
部分解析 4 个文件
跳过 12 个文件
失败 2 个文件
```

而不是：

```text
第 76 个文件 SyntaxError
→ inspect-repo 整体退出
```

这与大型代码索引系统的基本设计一致：索引数据是从源码派生的事实集合，一个局部抽取器失败不应该使其他语言或文件的事实不可用。Meta Glean公开强调将不同索引器生成的事实汇聚起来，供上层工具统一查询。

---

## 4. 每次运行必须记录仓库版本

评测结果必须关联到固定仓库状态：

```text
Git commit SHA
工作区是否 dirty
tracked 修改文件
untracked 文件
索引配置
Parser 和 Grammar 版本
排名权重版本
Token Budget
```

否则两次评测可能实际运行在不同代码上，却被错误比较。

建议：

```python
class RunManifest(BaseModel):
    run_id: str

    repository_root: str
    head_commit: str | None
    working_tree_dirty: bool

    config_hash: str
    dataset_hash: str | None

    parser_versions: dict[str, str]
    ranking_version: str
    renderer_version: str

    started_at: str
```

---

## 5. 人类可读输出与机器输出必须分开

支持：

```bash
codeteam inspect-repo . --format text
codeteam inspect-repo . --format json

codeteam context "..." --format text
codeteam context "..." --format json
```

Text 用于人学习和调试。

JSON 用于：

```text
自动评测
回归对比
持续集成
可视化页面
未来多 Agent 调用
```

不要让评测脚本解析带颜色的终端文本。

---

## 6. 所有选择都要保留原因

`Top 5` 不能只输出路径：

```text
src/auth/service.py
src/auth/api.py
...
```

还要保留：

```text
为什么被召回
为什么得到这个分数
为什么进入 Top 5
为什么某个候选被省略
```

否则 Recall 下降时无法判断是：

```text
QueryAnalyzer 没提取出关键词
SymbolExtractor 漏掉类
ripgrep 没搜索正确字符串
ImportResolver 解析错误
CandidateGenerator 没召回
FileRanker 排名过低
Token Budget 把它裁掉
```

---

# 四、`inspect-repo` 的数据结构

```python
from pydantic import BaseModel, Field


class ParseStatistics(BaseModel):
    success: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0


class ImportGraphStatistics(BaseModel):
    node_count: int
    edge_count: int
    resolved_local_imports: int
    external_imports: int
    unresolved_imports: int
    dynamic_imports: int
    cycle_count: int


class RepositoryInspectionReport(BaseModel):
    repository_root: str
    head_commit: str | None
    working_tree_dirty: bool

    tracked_files: int
    untracked_files: int
    ignored_files: int

    language_counts: dict[str, int]
    role_counts: dict[str, int]

    directory_tree: str
    important_files: list[str]

    instruction_files: list[str]
    detected_commands: list["DetectedCommand"]

    symbol_count: int
    reference_count: int
    symbols_by_kind: dict[str, int]

    parse_statistics: ParseStatistics
    import_graph: ImportGraphStatistics

    warnings: list[str] = Field(
        default_factory=list
    )

    scan_duration_ms: int
    index_duration_ms: int
```

---

# 五、`inspect-repo` 推荐输出

```text
Repository
  Root:       /workspace/codeteam-demo
  Commit:     91e4fc8
  Dirty:      yes

Files
  Tracked:    184
  Untracked:    3
  Ignored:   4,218

Languages
  Python:      112
  Markdown:     18
  TOML:          4
  YAML:          7

Roles
  Source:       91
  Test:         38
  Config:       13
  Instruction:   3
  Generated:    16

Parsing
  Success:     121
  Partial:       2
  Failed:        1
  Skipped:      11

Symbols
  Classes:      47
  Functions:   138
  Methods:     261
  Parameters:  824
  References: 2,917

Import graph
  Nodes:        119
  Edges:        284
  Local:        301
  External:     176
  Unresolved:     7
  Dynamic:        3
  Cycles:         2

Important files
  AGENTS.md
  pyproject.toml
  README.md
  src/main.py
  src/auth/service.py

Project rules
  AGENTS.md
  backend/AGENTS.md
  .clinerules/testing.md

Detected commands
  Test:       uv run pytest
  Lint:       uv run ruff check .
  Typecheck:  uv run mypy src

Tree
  ...
```

同时应输出警告：

```text
Warnings
  src/experimental/broken.py: partial parse
  app.plugins: dynamic import unresolved
  src/legacy/: unsupported language "cython"
```

---

# 六、`context` 的数据结构

```python
class SelectedFileReport(BaseModel):
    path: str
    rank: int
    score: float

    reasons: list[str]
    matched_symbols: list[str]
    matched_lines: list[int]

    compression_level: str
    token_count: int


class OmittedCandidate(BaseModel):
    path: str
    original_rank: int
    score: float
    reason: str


class ContextBuildReport(BaseModel):
    query: str
    analyzed_query: dict

    top_files: list[SelectedFileReport]
    omitted_candidates: list[OmittedCandidate]

    repo_map: str
    code_context: str

    applicable_instructions: dict
    test_commands: list["DetectedCommand"]

    budget_tokens: int
    tokens_before_compression: int
    tokens_after_compression: int

    compression_actions: list[str]

    candidate_count: int
    elapsed_ms: int
```

---

# 七、`context` 推荐输出

```text
Query
  修复 refresh token 过期后返回 500 的问题

Top 5 files

1. src/auth/service.py                    score=9.42
   - Defines refresh_access_token
   - Contains "InvalidRefreshTokenError"
   - Imported by src/auth/api.py

2. src/auth/api.py                        score=8.71
   - Contains refresh endpoint
   - One-hop dependent of service.py
   - Contains HTTP error mapping

3. src/auth/exceptions.py                 score=8.10
   - Defines InvalidRefreshTokenError
   - Imported by service.py

4. tests/auth/test_refresh.py             score=7.26
   - Filename and symbol match
   - Tests refresh token expiration

5. src/auth/repository.py                 score=5.83
   - One-hop dependency of service.py
   - Defines TokenRepository.find

Repository map
  ...

Selected code
  ...

Token usage
  Budget:              8,000
  Before compression: 12,460
  After compression:   7,731

Compression
  src/auth/repository.py:
    SYMBOL_BODY -> SYMBOL_SIGNATURE

  src/auth/models.py:
    FILE_SUMMARY -> PATH_ONLY

Omitted candidates
  src/common/errors.py
    Rank 6; omitted because code budget was exhausted

Test commands
  uv run pytest tests/auth/test_refresh.py -q
  uv run ruff check src/auth tests/auth
```

---

# 八、系统整合的应用服务

## `InspectRepository`

```python
class InspectRepository:
    def __init__(
        self,
        *,
        scanner: RepositoryScanner,
        parser_registry: ParserRegistry,
        symbol_extractor: SymbolExtractor,
        import_extractor: ImportExtractor,
        import_resolver: PythonImportResolver,
        instruction_loader: InstructionLoader,
        command_detector: CommandDetector,
    ) -> None:
        self.scanner = scanner
        self.parser_registry = parser_registry
        self.symbol_extractor = symbol_extractor
        self.import_extractor = import_extractor
        self.import_resolver = import_resolver
        self.instruction_loader = instruction_loader
        self.command_detector = command_detector

    def execute(
        self,
        repository_root: Path,
    ) -> RepositoryInspectionReport:
        snapshot = self.scanner.scan(
            repository_root
        )

        symbol_index = SymbolIndex()
        import_records: list[ImportRecord] = []
        parse_results: list[ParseResult] = []

        for file in snapshot.parseable_files:
            result = self._parse_one(
                repository_root,
                file,
            )
            parse_results.append(result)

            if result.native_tree is None:
                continue

            symbols = self.symbol_extractor.extract(
                path=file.path,
                parse_result=result,
            )
            symbol_index.add_symbols(
                symbols.symbols
            )
            symbol_index.add_references(
                symbols.references
            )

            imports = self.import_extractor.extract(
                path=file.path,
                parse_result=result,
            )
            import_records.extend(imports)

        module_index = build_module_index(
            snapshot
        )

        resolutions = (
            self.import_resolver.resolve_all(
                import_records,
                module_index,
            )
        )

        import_graph = ImportGraph.from_resolutions(
            resolutions
        )

        instructions = (
            self.instruction_loader
            .discover_repository_rules(
                repository_root
            )
        )

        commands = self.command_detector.detect(
            repository_root=repository_root,
            instructions=instructions,
        )

        return build_inspection_report(
            snapshot=snapshot,
            parse_results=parse_results,
            symbol_index=symbol_index,
            import_records=import_records,
            import_graph=import_graph,
            commands=commands,
        )
```

实际项目中建议把索引保存到 SQLite 或本地缓存，`context` 命令不必每次全量解析。

---

## `BuildContext`

```python
class BuildContext:
    def __init__(
        self,
        *,
        repository_index: RepositoryIndex,
        query_analyzer: QueryAnalyzer,
        candidate_generator: CandidateGenerator,
        file_ranker: FileRanker,
        repo_map_builder: RepoMapBuilder,
        instruction_loader: InstructionLoader,
        command_detector: CommandDetector,
        context_selector: ContextSelector,
        context_compressor: ContextCompressor,
        token_counter: TokenCounter,
    ) -> None:
        ...

    async def execute(
        self,
        *,
        query: str,
        top_k: int = 5,
        budget_tokens: int = 8_000,
    ) -> ContextBuildReport:
        analyzed = self.query_analyzer.analyze(
            query
        )

        candidates = (
            await self.candidate_generator
            .generate(query)
        )

        ranked = self.file_ranker.rank(
            candidates,
            query=analyzed,
        )

        top_files = ranked[:top_k]

        instructions = (
            self.instruction_loader.load(
                repository_root=(
                    self.repository_index.root
                ),
                target_paths=[
                    item.path
                    for item in top_files
                ],
            )
        )

        repo_map = self.repo_map_builder.build(
            ranked_files=ranked,
            query=query,
        )

        context_items = (
            self.context_selector.select(
                query=query,
                ranked_files=ranked,
                repo_map=repo_map,
            )
        )

        compressed, actions = (
            self.context_compressor.fit_to_budget(
                items=context_items,
                budget_tokens=budget_tokens,
                counter=self.token_counter,
            )
        )

        commands = self.command_detector.detect(
            repository_root=(
                self.repository_index.root
            ),
            instructions=instructions,
        )

        return build_context_report(
            query=query,
            analyzed=analyzed,
            ranked=ranked,
            repo_map=repo_map,
            context_items=compressed,
            instructions=instructions,
            commands=commands,
            actions=actions,
        )
```

---

# 九、下午：建立 20 条评测集

# 1. 评测集到底在测什么

今天的评测目标不是：

```text
Agent 最终是否修复了 Bug
```

而是：

```text
面对一个代码任务，
上下文引擎能否把完成任务所需文件
排进 Top 5？
```

这是**文件检索评测**。

后续完整 Coding Agent 才会评测：

```text
Patch 是否可应用
测试是否通过
是否引入回归
任务是否解决
```

SWE-bench采用真实 GitHub Issue，应用模型生成的 Patch 后运行仓库测试，并使用 Docker 确保评测环境尽可能一致。

你本周的评测位于 SWE-bench 完整流程之前：

```text
当前：
Issue → 相关文件

后续：
Issue → 相关文件 → Patch → 测试
```

---

# 十、Gold Files 应该怎样定义

## 1. Gold File 不是“任何可能有帮助的文件”

假设任务是：

```text
修复 refresh token 过期返回 500
```

仓库中可能有关：

```text
service.py
api.py
exceptions.py
repository.py
models.py
database.py
README.md
Dockerfile
```

不能把所有沾边文件都标成 Gold。

Gold 应定义为：

> 一个熟悉仓库的工程师，为正确理解并解决该任务，通常必须查看或修改的文件。

建议区分：

```text
required_files
完成任务的关键文件

supporting_files
可能有帮助，但不是必要文件

acceptable_alternatives
不同合法方案可能选择的替代文件
```

数据中仍可以保留 `gold_files` 作为 required files：

```json
{
  "gold_files": [
    "src/auth/service.py",
    "src/auth/api.py",
    "tests/auth/test_refresh.py"
  ],
  "supporting_files": [
    "src/auth/exceptions.py"
  ]
}
```

---

## 2. Gold 数量最好不要超过 5

你的主要指标是 Recall@5。

假设某条任务有 8 个 Gold 文件，那么即使 Top 5 全部正确：

```text
最大 Recall@5 = 5 / 8 = 62.5%
```

这会让指标上限天然小于 100%。

所以第一版建议：

```text
required Gold Files：1～5 个
supporting files：单独保存
```

跨模块任务实在需要更多文件时，应同时报告：

```text
Recall@5
Recall@10
```

---

## 3. 不要用当前系统输出来决定 Gold

错误标注方式：

```text
运行 Hybrid
→ 看它返回什么
→ 把看起来合理的结果标成 Gold
```

这会造成循环验证。

正确方式：

```text
人工阅读任务
→ 搜索和理解代码
→ 查看测试、调用关系和历史修改
→ 确定 Gold
→ 冻结标签
→ 再运行实验
```

GitHub 的公开离线评测同样采用预先整理的 benchmark 输入与预期输出，而不是运行模型后再根据输出调整答案。

---

## 4. Gold 标注证据

每条数据增加：

```json
{
  "gold_rationale": {
    "src/auth/service.py": "异常在该文件中抛出",
    "src/auth/api.py": "HTTP 状态码在接口层映射",
    "tests/auth/test_refresh.py": "包含该行为的回归测试"
  }
}
```

这样后续发现标签问题时，可以判断：

```text
是系统漏召回
还是 Gold 本身标错
```

---

# 十一、20 条数据的推荐格式

```python
from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    id: str
    category: str

    query: str

    gold_files: list[str]
    supporting_files: list[str] = Field(
        default_factory=list
    )

    gold_rationale: dict[str, str]

    repository_commit: str
    notes: str | None = None
```

JSONL：

```json
{"id":"symbol-001","category":"exact_symbol","query":"找到并检查 UserService.refresh_access_token 的实现","gold_files":["src/auth/service.py"],"supporting_files":["tests/auth/test_refresh.py"],"gold_rationale":{"src/auth/service.py":"定义目标方法"},"repository_commit":"91e4fc8"}
```

文件：

```text
evals/week2/file_retrieval.jsonl
```

---

# 十二、五个类别如何设计

# 1. 精确符号：4 条

目标是验证 `SymbolIndex`。

示例：

```text
找到 UserService.refresh_access_token 的实现

修改 InvalidRefreshTokenError 的定义

检查 RepositoryScanner.scan 的调用者

调整 ContextCompressor.fit_to_budget
```

要求：

```text
查询中包含真实符号
但不直接包含文件路径
```

Gold 通常是：

```text
符号定义文件
关键调用文件
对应测试
```

---

# 2. 错误信息：4 条

目标是验证 ripgrep 的精确字符串搜索。

示例：

```text
修复报错 "Token has expired"

处理日志 "Database session is already closed"

定位 "Unsupported parser language" 的来源

修复测试中的 "expected 401, got 500"
```

错误文本应真实存在于仓库中。

不要人为改写到源码完全搜不到，除非你有意测试语义检索。

---

# 3. 业务行为：4 条

目标是测试自然语言到代码概念的映射。

示例：

```text
用户刷新过期令牌时应该返回 401

创建订单后需要释放库存预占

删除用户时应同时撤销活动会话

导出大订单时不应一次加载全部数据
```

这类查询通常不包含精确类名和错误字符串，因此 Filename、Symbol 和 ripgrep都可能变弱。

它会暴露：

```text
QueryAnalyzer 词汇映射不足
缺少语义检索
缺少调用图
测试文件映射不足
```

---

# 4. 配置与测试：4 条

目标是验证重要文件和命令检测。

示例：

```text
修改单元测试默认搜索目录

调整前端 test 脚本使用 Vitest

修复 mypy 不检查 src/auth 的问题

让 make check 同时执行 Lint 和测试
```

Gold 可能包括：

```text
pyproject.toml
pytest.ini
package.json
Makefile
AGENTS.md
对应测试配置文件
```

---

# 5. 跨模块任务：4 条

目标是验证 ImportGraph 和一跳、两跳扩展。

示例：

```text
refresh token 过期异常需要从 service 层传播到 API 层

订单创建后通过事件系统触发库存扣减

用户删除后清理缓存和会话

新增字段需要贯穿 Schema、Service 和 Repository
```

Gold 通常分布在：

```text
入口
业务服务
模型或 Repository
测试
```

---

# 十三、避免评测泄漏

以下 Query 会让评测过于简单：

```text
修改 src/auth/service.py 中的问题
```

如果类别不是显式路径检索，它直接泄露答案。

以下 Query 更合理：

```text
修复 refresh token 过期后返回 500 的问题
```

同时不要把 Git Commit 信息或历史 Patch 内容放入检索输入。

---

# 十四、四组实验如何公平比较

## 实验 A：Filename

只使用：

```text
查询词
→ 文件名、目录名匹配
```

允许：

```text
CamelCase 拆词
snake_case 拆词
路径 Token
```

不允许：

```text
文件内容
SymbolIndex
ImportGraph
```

---

## 实验 B：ripgrep

使用：

```text
QueryAnalyzer
→ 精确字符串和正则搜索
→ 按命中证据排序
```

不使用：

```text
SymbolIndex
ImportGraph
文件依赖扩展
```

---

## 实验 C：ripgrep + Symbol

使用：

```text
Filename
ripgrep
Symbol exact
Symbol prefix
Reference
```

不使用：

```text
Import 邻居
PageRank
测试文件映射
重要配置增强
```

---

## 实验 D：Hybrid

使用完整方案：

```text
Filename
+
ripgrep
+
SymbolIndex
+
Import 一跳、两跳
+
测试映射
+
重要配置
+
文件基础权重
+
FileRanker
```

可选加入：

```text
Personalized PageRank
```

---

## 统一实验条件

四个实验必须固定：

```text
相同仓库 Commit
相同 20 条 Query
相同 QueryAnalyzer 基础规则
相同 Top K = 5
相同文件过滤范围
相同 Generated/Vendored 策略
相同大小写规则
相同随机种子
```

否则不能确定提升来自哪个组件。

---

# 十五、实验配置

```python
class RetrievalMethod(str, Enum):
    FILENAME = "filename"
    RIPGREP = "ripgrep"
    RIPGREP_SYMBOL = "ripgrep_symbol"
    HYBRID = "hybrid"


class EvaluationConfig(BaseModel):
    method: RetrievalMethod
    top_k: int = 5

    candidate_limit: int = 50
    include_generated: bool = False

    repository_commit: str
    dataset_path: str

    ranking_config_hash: str
    run_id: str
```

---

# 十六、Recall@5

对一条任务：

```text
Gold Files：
G

系统 Top 5：
P₅
```

定义：

```text
Recall@5 = |G ∩ P₅| / |G|
```

例如：

```text
Gold：
service.py
api.py
test_refresh.py

Top 5：
service.py
exceptions.py
api.py
models.py
README.md
```

命中：

```text
service.py
api.py
```

所以：

```text
Recall@5 = 2 / 3 = 66.7%
```

Recall@K 衡量的是相关结果中有多少进入了前 K 个结果，它不考虑这些命中文件在 Top K 内的具体位置。

---

# 十七、Hit@5

定义：

```text
Top 5 里至少出现一个 Gold File
→ Hit@5 = 1

一个都没有
→ Hit@5 = 0
```

上例：

```text
Hit@5 = 1
```

Hit@5 容易看起来很高：

```text
每条任务只找到一个正确文件
Hit@5 可能是 100%

但需要三个文件的任务：
Recall@5 只有 33.3%
```

因此不能只报告 Hit@5。

---

# 十八、Macro Recall@5

20 条任务分别计算 Recall，再取平均：

```text
Macro Recall@5
=
Σ Recall@5(query_i) / 20
```

这样每条 Query 权重相同。

同时按类别计算：

```text
Exact Symbol Recall@5
Error Message Recall@5
Business Behavior Recall@5
Config/Test Recall@5
Cross-module Recall@5
```

类别均值比总均值更能解释系统优劣。

---

# 十九、建议额外记录的指标

虽然验收要求主要是 Recall@5 和 Hit@5，但建议同时记录：

| 指标 | 作用 |
|---|---|
| Precision@5 | Top 5 中有多少是真正相关文件 |
| MRR@5 | 第一个正确文件排得多靠前 |
| Candidate Recall | 排序前的候选池有没有包含 Gold |
| Average Candidate Size | 召回阶段产生多少噪声 |
| Mean Query Latency | 平均查询耗时 |
| P95 Query Latency | 较慢查询表现 |
| Index Build Time | 建立索引耗时 |
| Repo Map Tokens | Map 占用上下文量 |
| Context Tokens | 最终代码上下文量 |

Candidate Recall 尤其重要：

```text
Candidate Recall 低
→ 召回问题

Candidate Recall 高，但 Recall@5 低
→ 排名问题
```

---

# 二十、评测代码

## 单条指标

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryMetrics:
    recall_at_5: float
    hit_at_5: float

    hit_files: tuple[str, ...]
    missed_files: tuple[str, ...]


def evaluate_query(
    *,
    predicted_files: list[str],
    gold_files: list[str],
    k: int = 5,
) -> QueryMetrics:
    predictions = list(
        dict.fromkeys(predicted_files)
    )[:k]

    gold = set(gold_files)

    if not gold:
        raise ValueError(
            "gold_files cannot be empty"
        )

    hits = [
        path
        for path in predictions
        if path in gold
    ]

    missed = sorted(gold - set(hits))

    return QueryMetrics(
        recall_at_5=len(hits) / len(gold),
        hit_at_5=1.0 if hits else 0.0,
        hit_files=tuple(hits),
        missed_files=tuple(missed),
    )
```

---

## 数据集汇总

```python
from collections import defaultdict


def aggregate_results(
    results: list["EvalResult"],
) -> dict:
    by_category: dict[
        str,
        list[EvalResult],
    ] = defaultdict(list)

    for result in results:
        by_category[
            result.category
        ].append(result)

    return {
        "overall": {
            "query_count": len(results),
            "recall_at_5": mean(
                item.metrics.recall_at_5
                for item in results
            ),
            "hit_at_5": mean(
                item.metrics.hit_at_5
                for item in results
            ),
            "mean_latency_ms": mean(
                item.latency_ms
                for item in results
            ),
        },
        "by_category": {
            category: {
                "query_count": len(items),
                "recall_at_5": mean(
                    item.metrics.recall_at_5
                    for item in items
                ),
                "hit_at_5": mean(
                    item.metrics.hit_at_5
                    for item in items
                ),
            }
            for category, items
            in sorted(by_category.items())
        },
    }
```

---

# 二十一、评测运行器

```python
class RetrievalEvaluator:
    def __init__(
        self,
        systems: dict[
            RetrievalMethod,
            RetrievalSystem,
        ],
    ) -> None:
        self.systems = systems

    async def evaluate(
        self,
        *,
        cases: list[EvalCase],
        methods: list[RetrievalMethod],
        top_k: int = 5,
    ) -> list["EvalResult"]:
        results: list[EvalResult] = []

        for method in methods:
            system = self.systems[method]

            for case in cases:
                started = time.monotonic()

                prediction = await system.retrieve(
                    case.query,
                    top_k=top_k,
                )

                latency_ms = int(
                    (
                        time.monotonic()
                        - started
                    )
                    * 1000
                )

                metrics = evaluate_query(
                    predicted_files=[
                        item.path
                        for item
                        in prediction.ranked_files
                    ],
                    gold_files=case.gold_files,
                    k=top_k,
                )

                results.append(
                    EvalResult(
                        case_id=case.id,
                        category=case.category,
                        method=method,
                        query=case.query,
                        gold_files=case.gold_files,
                        predicted_files=[
                            item.path
                            for item
                            in prediction.ranked_files[
                                :top_k
                            ]
                        ],
                        metrics=metrics,
                        latency_ms=latency_ms,
                        evidence=prediction.evidence,
                    )
                )

        return results
```

---

# 二十二、保存原始结果

每条预测保存成 JSONL：

```json
{
  "case_id": "cross-003",
  "method": "hybrid",
  "query": "refresh token 过期异常需要从 service 层传播到 API 层",
  "gold_files": [
    "src/auth/service.py",
    "src/auth/api.py",
    "tests/auth/test_refresh.py"
  ],
  "predicted_files": [
    "src/auth/service.py",
    "src/auth/exceptions.py",
    "src/auth/api.py",
    "src/auth/repository.py",
    "tests/auth/test_refresh.py"
  ],
  "recall_at_5": 1.0,
  "hit_at_5": 1.0,
  "latency_ms": 37
}
```

目录：

```text
evals/results/
├── filename.jsonl
├── ripgrep.jsonl
├── ripgrep_symbol.jsonl
└── hybrid.jsonl
```

---

# 二十三、评测的可复现性

至少记录：

```text
仓库 Commit SHA
数据集 Hash
配置 Hash
方法名称
排名权重
Top K
候选数量上限
ripgrep 版本
Tree-sitter 版本
Grammar 版本
Python 版本
操作系统
运行时间
```

推荐 Manifest：

```json
{
  "run_id": "week2-20260807-001",
  "repository_commit": "91e4fc8",
  "dataset_sha256": "...",
  "top_k": 5,
  "candidate_limit": 50,
  "methods": [
    "filename",
    "ripgrep",
    "ripgrep_symbol",
    "hybrid"
  ],
  "python_version": "3.12.8",
  "ripgrep_version": "14.x",
  "ranking_version": "week2-v1"
}
```

SWE-bench将 Patch 应用和测试放在 Docker 环境中，就是为了减少平台差异、提高结果可重复性；你的文件检索评测暂时不需要为每条任务构建 Docker，但必须冻结仓库 Commit 和配置。

---

# 二十四、确定性测试

当前四种检索方案如果不调用 LLM，应是确定性的。

同一配置连续运行两次：

```bash
codeteam eval \
  --dataset evals/week2/file_retrieval.jsonl \
  --method hybrid \
  --run-id deterministic-1

codeteam eval \
  --dataset evals/week2/file_retrieval.jsonl \
  --method hybrid \
  --run-id deterministic-2
```

断言：

```text
每条 Query 的 Top 5 顺序一致
分数一致
证据一致
Repo Map 一致
```

如果不一致，检查：

```text
set / dict 遍历顺序
并发完成顺序
文件系统顺序
浮点排序
PageRank 节点插入顺序
未固定配置
```

未来加入 LLM Query Rewrite 后，不能只比较完全相同的行动路径。GitHub 在 2026 年公开讨论 Agent 验证时指出，自主 Agent 可能通过多种合法路径完成任务，评测更应关注关键结果，而不是要求过程逐步完全一致。

---

# 二十五、失败分析：从哪里开始查

不要只写：

```text
Hybrid 在 business_behavior 类别表现不好。
```

要把失败定位到具体阶段。

## 1. Query Analysis Failure

例子：

```text
查询：
用户刷新过期令牌时应返回 401

提取词：
用户、刷新、过期、令牌

代码实际使用：
refresh_access_token
expired_token
```

问题：

```text
中英文概念未对齐
CamelCase 或 snake_case 扩展不足
```

---

## 2. Filename Recall Failure

```text
查询包含 login
实际文件叫 session_manager.py
```

说明文件命名与业务语言不一致。

---

## 3. ripgrep Recall Failure

```text
查询说“释放库存预占”
源码写 reservation.release()
```

自然语言没有在代码中直接出现。

---

## 4. Symbol Extraction Failure

```text
目标类由装饰器或动态工厂创建
SymbolExtractor 没有提取
```

或者：

```text
Grammar 不支持该语言
语法错误导致 Symbol 缺失
```

---

## 5. Import Resolution Failure

```text
src layout 判断错误
Namespace Package
Re-export
相对 Import
动态 Import
```

导致一跳邻居没有出现。

---

## 6. Candidate Recall Failure

Gold File 根本不在候选集合里：

```text
Candidate Recall = 0
```

应该改召回逻辑，不是调 FileRanker 权重。

---

## 7. Ranking Failure

Gold File 在候选池中：

```text
候选排名第 9
最终 Top 5 没进入
```

说明召回成功、排序失败。

---

## 8. Generated 或公共模块污染

```text
generated/client.py
common/utils.py
```

因 Symbol 数量、文本命中或 PageRank 过高挤掉真正文件。

---

## 9. Test Pair Failure

实现文件进入 Top 5，但对应测试没进入。

说明需要改进：

```text
源码—测试命名映射
测试 Import 关系
测试函数符号匹配
```

---

## 10. Gold Label Failure

系统返回的文件实际合理，但人工 Gold 漏标。

这不是系统错误，需要更新数据集并记录标签版本。

---

# 二十六、错误召回与漏召回

## 错误召回

Top 5 中不相关文件为什么进入？

常见原因：

```text
短词匹配过强
错误码过于常见
公共模块 PageRank 过高
测试文件名相似但测试对象不同
README 或配置基础权重过高
Generated 文件包含大量匹配
```

---

## 漏召回

Gold 文件为什么没进入？

常见原因：

```text
查询没有源码中的词
SymbolExtractor 漏提取
Import 解析失败
只扩展了一跳
Re-export 没有处理
测试命名不规则
文件被错误标记 Generated
预算裁剪过早
```

---

# 二十七、失败案例记录模板

```markdown
## Failure: cross-003

**Query**

刷新令牌过期时，异常应从 service 层传播到 API 层。

**Gold files**

- `src/auth/service.py`
- `src/auth/api.py`
- `tests/auth/test_refresh.py`

**Hybrid Top 5**

1. `src/auth/service.py`
2. `src/auth/exceptions.py`
3. `src/common/errors.py`
4. `src/auth/repository.py`
5. `src/auth/models.py`

**Missed**

- `src/auth/api.py`
- `tests/auth/test_refresh.py`

**Stage diagnosis**

- `api.py` existed in the candidate pool at rank 8.
- `test_refresh.py` was never recalled.

**Root causes**

- Ranking: `common/errors.py` received excessive PageRank.
- Recall: source-to-test mapping did not support `service.py`
  → `test_refresh.py`.

**Planned fix**

- Cap global PageRank contribution.
- Add import-based test pairing.
- Add a test-function symbol match signal.
```

---

# 二十八、实验结果表

## 总体结果

```markdown
| Method | Recall@5 | Hit@5 | Candidate Recall | Avg Candidates | Mean Latency |
|---|---:|---:|---:|---:|---:|
| Filename |  |  |  |  |  |
| ripgrep |  |  |  |  |  |
| ripgrep + Symbol |  |  |  |  |  |
| Hybrid |  |  |  |  |  |
```

---

## 分类结果

```markdown
| Category | Filename | ripgrep | rg + Symbol | Hybrid |
|---|---:|---:|---:|---:|
| Exact symbol |  |  |  |  |
| Error message |  |  |  |  |
| Business behavior |  |  |  |  |
| Config/test |  |  |  |  |
| Cross-module |  |  |  |  |
```

---

## 预期趋势

不应预先假设结果一定如此，但正常情况下可能观察到：

```text
Filename：
延迟低，适合文件名与 Query 接近的任务

ripgrep：
错误信息表现明显提升

ripgrep + Symbol：
精确类和函数任务明显提升

Hybrid：
跨模块、测试映射和配置任务更强
```

如果 Hybrid 反而下降，常见原因是：

```text
Import 扩展噪声太多
PageRank 压过查询匹配
基础文件权重太强
测试映射产生错误候选
```

这也是消融实验的价值：复杂系统不一定天然优于简单系统。

---

# 二十九、20 条数据是否足够

20 条适合：

```text
学习实现
发现明显 Bug
初步比较组件
形成第一版回归测试
```

但不适合声称：

```text
系统已在所有代码仓库上达到 80%
Hybrid 已被证明显著优于其他方法
```

建议把本周 20 条称为：

```text
Week 2 development evaluation set
```

之后扩展到：

```text
50～100 条
多个仓库
多种语言
不同仓库规模
真实历史 Issue
```

---

# 三十、开发集和测试集

如果你需要在今天调整 FileRanker 权重，不应一边看全部 20 条结果，一边不断调参，最后再把同一 20 条当成最终成绩。

推荐：

```text
15 条 Development
用于观察失败和调整权重

5 条 Held-out
每个类别保留 1 条
只在方案确定后运行
```

本周报告同时写：

```text
Development Recall@5
Held-out Recall@5
```

只有 5 条 Held-out，波动会很大，因此它只是防止最明显的过拟合，不是统计上充分的最终测试。

---

# 三十一、`EVALUATION_WEEK2.md` 结构

```markdown
# Week 2 Code Context Retrieval Evaluation

## 1. Objective

评测 CodeTeam 是否能针对代码任务，
将关键文件排进 Top 5。

## 2. System Under Test

- RepositoryScanner
- SymbolIndex
- ImportGraph
- QueryAnalyzer
- CandidateGenerator
- FileRanker
- RepoMapBuilder
- ContextCompressor

## 3. Repository

- Repository:
- Commit:
- File count:
- Languages:
- Symbol count:
- Import edge count:

## 4. Dataset

- Total queries: 20
- Exact symbol: 4
- Error message: 4
- Business behavior: 4
- Config/test: 4
- Cross-module: 4

## 5. Gold Annotation Policy

- required files
- supporting files
- maximum required files
- annotation procedure

## 6. Experimental Methods

### Filename
### ripgrep
### ripgrep + Symbol
### Hybrid

## 7. Metrics

- Recall@5
- Hit@5
- Candidate Recall
- Mean latency
- Context tokens

## 8. Overall Results

...

## 9. Category Results

...

## 10. Ablation Findings

...

## 11. Failure Cases

...

## 12. False Positive Analysis

...

## 13. Missed File Analysis

...

## 14. Limitations

- only one repository
- only 20 queries
- mainly Python
- manually labeled Gold Files

## 15. Next-week Improvements

...
```

---

# 三十二、下一周改进项应该怎样写

不要写成：

```text
继续优化效果
增加更多功能
提高准确率
```

要从失败证据中生成可执行改进。

示例：

```markdown
## Improvement 1: Re-export resolution

**Evidence**

3/4 cross-module failures involved imports through `__init__.py`.

**Change**

Extend PythonImportResolver to follow one level of package re-export.

**Expected effect**

Improve recall of API and service files connected through package exports.

**Evaluation**

Re-run cases `cross-001`, `cross-003`, and add two regression cases.
```

另一例：

```markdown
## Improvement 2: Suppress generic symbols

**Evidence**

`get`, `run`, and `create` caused 34 irrelevant candidates.

**Change**

Apply inverse document frequency to symbols defined in more than
10 files.

**Expected effect**

Reduce common-symbol noise without affecting exact qualified names.
```

---

# 三十三、今天的详细时间安排

## 上午第一阶段：整合索引管线，约 90 分钟

完成：

```text
RepositoryScanner
→ ParserRegistry
→ SymbolExtractor
→ ImportExtractor
→ Resolver
→ SymbolIndex
→ ImportGraph
```

输出：

```text
repository_index.json
```

验证：

```text
所有路径格式统一
单文件失败不终止
统计数量合理
Import 图没有不存在的路径
```

---

## 上午第二阶段：实现 `inspect-repo`，约 60 分钟

实现：

```text
InspectionReport
Text Renderer
JSON Renderer
CLI 参数
```

支持：

```bash
codeteam inspect-repo .
codeteam inspect-repo . --format json
codeteam inspect-repo . --no-cache
```

---

## 上午第三阶段：实现 `context`，约 100 分钟

接通：

```text
QueryAnalyzer
CandidateGenerator
FileRanker
RepoMapBuilder
InstructionLoader
CommandDetector
ContextSelector
ContextCompressor
```

支持：

```bash
codeteam context "..." \
  --top-k 5 \
  --budget 8000 \
  --format text

codeteam context "..." \
  --debug-evidence \
  --format json
```

---

## 上午第四阶段：整合测试，约 50 分钟

至少测试：

```text
正常仓库
空仓库
非 Git 目录
部分语法错误
无规则文件
无测试配置
无搜索结果
Token Budget 极小
同分候选稳定排序
```

---

## 下午第一阶段：建立 20 条数据，约 100 分钟

每个类别 4 条。

对每条任务：

```text
编写 Query
人工分析代码
标注 required Gold
标注 supporting files
写 Gold rationale
确认路径存在
确认 Gold 数量不超过 5
```

---

## 下午第二阶段：运行四组实验，约 60 分钟

```bash
codeteam eval \
  --dataset evals/week2/file_retrieval.jsonl \
  --methods filename,ripgrep,ripgrep-symbol,hybrid \
  --top-k 5 \
  --output evals/results/
```

生成：

```text
run_manifest.json
filename.jsonl
ripgrep.jsonl
ripgrep_symbol.jsonl
hybrid.jsonl
summary.json
```

---

## 下午第三阶段：失败分析，约 60 分钟

对所有 Hybrid 失败项分类：

```text
Query Analysis
Filename
ripgrep
Symbol
Import Resolution
Candidate Recall
Ranking
Test Mapping
Budget
Gold Label
```

至少详细分析 5 个失败案例。

---

## 下午第四阶段：生成报告，约 60 分钟

输出：

```text
EVALUATION_WEEK2.md
```

报告必须包含：

```text
总体结果
分类结果
四种方法对比
至少 5 个失败案例
错误召回分析
漏召回分析
限制
下一周改进项
```

---

# 三十四、今日验收标准

今天结束时应满足：

```text
[ ] codeteam inspect-repo . 可以运行
[ ] 输出仓库统计和压缩目录树
[ ] 输出重要文件和规则文件
[ ] 输出测试、Lint 和构建命令
[ ] 输出 Symbol 和 Import 图统计
[ ] 局部解析失败不会终止命令

[ ] codeteam context "query" 可以运行
[ ] 输出 Top 5 文件
[ ] 每个文件有选择理由
[ ] 输出 Query Repo Map
[ ] 输出具体代码片段
[ ] 输出 Token 使用情况
[ ] 输出被省略候选及原因
[ ] 输出适用测试命令
[ ] ContextPack 不超过预算

[ ] 建立 20 条人工标注数据
[ ] 五个类别各 4 条
[ ] 每条数据冻结仓库 Commit
[ ] 每个 Gold File 有理由
[ ] 运行四种检索方案
[ ] 计算 Recall@5 和 Hit@5
[ ] 按类别统计
[ ] 至少分析 5 个失败案例
[ ] 生成 EVALUATION_WEEK2.md
```

---

# 今日最终目录

```text
codeteam/
├── cli/
│   ├── app.py
│   ├── inspect_command.py
│   ├── context_command.py
│   └── eval_command.py
│
├── application/
│   ├── inspect_repository.py
│   └── build_context.py
│
└── evaluation/
    ├── models.py
    ├── loader.py
    ├── metrics.py
    ├── runner.py
    ├── aggregator.py
    ├── failure_analysis.py
    └── report.py

evals/
├── week2/
│   ├── file_retrieval.jsonl
│   ├── run_manifest.json
│   ├── filename.jsonl
│   ├── ripgrep.jsonl
│   ├── ripgrep_symbol.jsonl
│   ├── hybrid.jsonl
│   ├── summary.json
│   └── EVALUATION_WEEK2.md
│
└── fixtures/

artifacts/
├── repository_inspection.json
├── context_report.json
├── global_repo_map.txt
└── query_repo_map.txt
```

今天的核心链路可以总结为：

```text
inspect-repo
证明代码库索引系统能够完整运行

context
证明索引能够服务一次真实查询

Gold Dataset
定义什么叫“检索正确”

Ablation
证明哪个模块真正有用

Recall@5
衡量关键文件找全了多少

Hit@5
衡量是否至少找到一个正确入口

Failure Analysis
解释系统为什么失败

Evaluation Report
把个人感觉变成可复现的工程证据
```

---

# 附录：Day 7 教学教程

> 以下为学习教练根据 `task_to_knowledge.md` 要求编写的逐步教学路线图。

---

## 这部分在做什么

今天不写新算法，而是把前六天的模块接成一条可运行、可评测、可复现的完整链路。

```
前六天：自底向上构建模块
  "我需要一个能提取符号的类"  → SymbolExtractor
  "我需要一个能排名的引擎"    → FileRanker
  "我需要一个能构建地图的工具" → RepoMapBuilder

今天：自顶向下验证系统
  "这些模块真的能协作吗？"     → codeteam inspect-repo .
  "20条任务 × 4种方法 → 哪种最好？" → codeteam eval
  "为什么那条任务失败了？"     → Failure Analysis
```

上午做系统整合，把散落的模块接成两个可运行的命令。下午建立 20 条人工标注的评测数据，跑 4 组消融实验，生成可复现的评测报告。

---

## 涉及哪些文件

### 新建目录和文件

```
codeteam/
├── cli/                          ← 命令行入口层
│   ├── __init__.py
│   ├── app.py                    ← CLI 主入口
│   ├── inspect_command.py        ← inspect-repo 命令
│   ├── context_command.py        ← context 命令
│   └── eval_command.py           ← eval 命令
│
├── application/                  ← 应用服务层（编排业务逻辑）
│   ├── __init__.py
│   ├── inspect_repository.py     ← InspectRepository 用例
│   └── build_context.py          ← BuildContext 用例
│
└── evaluation/                   ← 评测系统
    ├── __init__.py
    ├── models.py                 ← EvalCase / EvalResult / QueryMetrics
    ├── metrics.py                ← Recall@5 / Hit@5 计算
    ├── runner.py                 ← RetrievalEvaluator
    ├── aggregator.py             ← 按类别汇总
    └── failure_analysis.py       ← 失败分类诊断

evals/
└── week2/
    ├── file_retrieval.jsonl      ← 20 条人工标注数据
    ├── run_manifest.json         ← 实验配置清单
    ├── *.jsonl                   ← 四组实验结果
    ├── summary.json              ← 汇总统计
    └── EVALUATION_WEEK2.md       ← 最终报告
```

### 依赖的已有模块

今天依赖前六天的几乎所有模块。核心集成路径：

```
RepositoryScanner → ParserRegistry
  → SymbolExtractor + ImportExtractor
  → SymbolIndex + ImportGraph
  → InstructionLoader + CommandDetector
  → QueryAnalyzer → CandidateGenerator
  → FileRanker → RepoMapBuilder
  → ContextSelector → ContextCompressor → ContextPack
```

### 已可复用的模块（减少工作量）

| 模块 | 状态 | 今天的使用方式 |
|---|---|---|
| `codeteam/context/` | 完整实现（budget/models/compressor/selector） | 第 4 步直接复用 |
| `codeteam/instructions/loader.py` | 完整实现 | 第 2 步直接复用 |
| `tests/search/conftest.py` | 完整 fixtures（含 candidate_generator） | 集成测试使用 |

### 需要新建/补全的模块

| 模块 | 当前状态 | 今天要做的事 |
|---|---|---|
| `codeteam/instructions/command_detector.py` | 空壳 | 实现命令检测 |
| `codeteam/cli/` | 不存在 | 新建 CLI 层 |
| `codeteam/application/` | 不存在 | 新建应用服务层 |
| `codeteam/evaluation/` | 不存在 | 新建评测系统 |

---

## 文件之间的交互关系

### inspect-repo 命令的数据流

```
用户执行: codeteam inspect-repo .

CLI 层 (cli/inspect_command.py)
  │ 解析参数：路径、--format、--no-cache
  │
  ▼
应用层 (application/inspect_repository.py)
  │
  ├── RepositoryScanner.scan(root) → RepositorySnapshot
  │
  ├── 遍历每个 Python 文件：
  │   ├── ParserRegistry.parse(code) → ParseResult
  │   ├── SymbolExtractor.extract(tree) → (Symbols, References)
  │   └── ImportExtractor.extract(tree) → ImportRecords
  │
  ├── SymbolIndex.add(symbols) + add_references(refs)
  ├── PythonImportResolver.resolve_all(records)
  ├── ImportGraph.from_resolutions(resolutions)
  │
  ├── InstructionLoader.discover_repository_rules(root)
  ├── CommandDetector.detect(root, instructions)
  │
  └── → RepositoryInspectionReport
       │
       ▼
  渲染输出 (--format text 或 --format json)
```

### context 命令的数据流

```
用户执行: codeteam context "修复 refresh token 过期返回 500"

CLI 层 (cli/context_command.py)
  │ 解析参数：query、--top-k、--budget、--format
  │
  ▼
应用层 (application/build_context.py)
  │
  ├── QueryAnalyzer.analyze(query) → AnalyzedQuery
  ├── CandidateGenerator.generate(query) → list[CandidateFile]
  ├── FileRanker.rank(candidates) → list[RankedFile]
  │
  ├── top_files = ranked[:top_k]
  ├── RepoMapBuilder.build(ranked, symbol_index) → RepoMap
  │
  ├── ContextSelector.select(query, ranked, repo_map) → context_items
  ├── ContextCompressor.fit_to_budget(items, budget_tokens) → (compressed, actions)
  │
  ├── InstructionLoader.load(root, target_paths)
  ├── CommandDetector.detect(root, instructions)
  │
  └── → ContextBuildReport
       │
       ▼
  渲染输出 (--format text 或 --format json)
```

### 评测系统的数据流

```
evals/week2/file_retrieval.jsonl (20 条)
  │
  ▼
RetrievalEvaluator
  │
  ├── 对每种方法 (filename / ripgrep / ripgrep_symbol / hybrid)：
  │   ├── 对每条 EvalCase：
  │   │   ├── 运行检索 → predicted_files
  │   │   ├── evaluate_query(predicted, gold) → QueryMetrics
  │   │   └── 记录 latency_ms
  │   └── 保存结果到 evals/results/{method}.jsonl
  │
  ├── aggregate_results() → 按类别汇总
  ├── failure_analysis() → 失败分类诊断
  └── → EVALUATION_WEEK2.md
```

---

## 建议拆成哪些步骤

### 第 1 步：路径格式统一

**目标**：实现 `normalize_repo_path()`，确保所有模块使用相同的路径格式。

**为什么先做它**：这是最常见的整合 Bug——同一个文件在不同模块里路径格式不同（`src/auth/service.py` vs `/Users/lee/project/src/auth/service.py` vs `src\auth\service.py`），变成"四个不同文件"。必须第一步统一。

**规范**：POSIX 风格、相对 Git 仓库根、不以 `./` 开头。例如 `src/auth/service.py`。

**涉及文件**：可在 `codeteam/repository/` 或新建一个 `codeteam/shared/paths.py`。

---

### 第 2 步：实现 `application/inspect_repository.py` — 索引管线

**目标**：把 Scanner → Parser → Extractor → Index → Graph 接成完整管线。

**为什么第二步做**：这是上午的核心——证明索引系统能完整运行。有了它，`inspect-repo` 命令和 `context` 命令才有数据源。

**关键设计**：
- 单个文件解析失败不终止整个管线——继续处理下一个文件，收集警告
- 返回解析统计：成功 N 个、部分 M 个、跳过 K 个、失败 P 个
- 路径格式统一（依赖第 1 步）

**涉及文件**：`codeteam/application/inspect_repository.py`

---

### 第 3 步：实现 `cli/inspect_command.py` + 文本/JSON 输出

**目标**：`codeteam inspect-repo .` 可以运行。

**为什么第三步做**：这是第一个可验证的里程碑——跑一条命令就能看到整个仓库的索引健康状况。

**输出要求**：
- 仓库信息（Root、Commit、Dirty）
- 文件统计（Tracked/Untracked/Ignored）
- 语言分布和角色分布
- 解析统计（Success/Partial/Failed/Skipped）
- Symbol 统计（Classes/Functions/Methods 数量）
- Import 图统计（Nodes/Edges/Local/External/Unresolved）
- 重要文件列表和项目规则
- 检测到的命令（Test/Lint/Build）
- 目录树
- 警告列表

**涉及文件**：`codeteam/cli/app.py`、`codeteam/cli/inspect_command.py`

---

### 第 4 步：实现 `command_detector.py` + `application/build_context.py`

**目标**：补全 CommandDetector，然后把 QueryAnalyzer → CandidateGenerator → FileRanker → RepoMapBuilder → ContextCompressor 接成完整管线。

**为什么第四步做**：`context` 命令依赖完整的上下文管线。CommandDetector 是昨天遗留的空壳，需要补全。

**涉及文件**：
- `codeteam/instructions/command_detector.py`（补全）
- `codeteam/application/build_context.py`（新建）

---

### 第 5 步：实现 `cli/context_command.py` + `cli/eval_command.py`

**目标**：`codeteam context "query"` 和 `codeteam eval` 可以运行。

**为什么第五步做**：这是第二个可验证的里程碑——针对一条真实查询，看到 Top 5 文件、Repo Map 和 Token 使用情况。

**输出要求**：
- Top 5 文件（含分数和入选理由）
- 每个文件的匹配符号和行号
- Repo Map 文本
- Token 使用（预算、压缩前、压缩后）
- 压缩记录
- 被省略候选及原因
- 测试命令

**涉及文件**：`codeteam/cli/context_command.py`、`codeteam/cli/eval_command.py`

---

### 第 6 步：建立 20 条评测数据

**目标**：编写 `evals/week2/file_retrieval.jsonl`。

**为什么第六步做**：评测数据可以和系统整合并行准备。5 个类别各 4 条，覆盖不同的检索能力维度。

**五个类别**：

| 类别 | 验证目标 | 示例查询 |
|---|---|---|
| exact_symbol | SymbolIndex 精确匹配 | "找到 UserService.refresh_access_token 的实现" |
| error_message | ripgrep 文本搜索 | "修复报错 'Token has expired'" |
| business_behavior | 自然语言→代码映射 | "用户刷新过期令牌时应返回 401" |
| config_test | 重要文件检测 | "修改单元测试默认搜索目录" |
| cross_module | ImportGraph 邻居扩展 | "异常从 service 层传播到 API 层" |

**标注原则**：
- Gold File 不是"任何可能有帮助的文件"，而是"必须查看或修改的文件"
- 每条 Gold ≤ 5 个（保证 Recall@5 上限可达 100%）
- 不能用系统输出决定 Gold（循环验证）
- 每个 Gold File 附带 rationale（为什么选它）

**涉及文件**：`evals/week2/file_retrieval.jsonl`

---

### 第 7 步：实现 `evaluation/` 评测系统 + 四组消融实验

**目标**：`codeteam eval` 可以运行四组实验并计算指标。

**为什么第七步做**：评测系统依赖前面所有步骤——系统能运行 + 数据已标注 = 可以跑实验。

**四组消融实验**：

| 实验 | 启用的模块 | 禁用的模块 | 验证假设 |
|---|---|---|---|
| A: Filename | FilenameIndex | ripgrep, SymbolIndex, ImportGraph | 文件名匹配的基线 |
| B: ripgrep | + QueryAnalyzer + ripgrep | SymbolIndex, ImportGraph | 文本搜索的提升 |
| C: ripgrep+Symbol | + SymbolIndex | ImportGraph, PageRank | 符号匹配的提升 |
| D: Hybrid | 全部 | — | 完整方案 vs 单路 |

**核心指标**：

```
Recall@5 = |Gold ∩ Top5| / |Gold|
Hit@5    = 1 if Recall@5 > 0 else 0
Macro Recall@5 = Σ Recall@5(query_i) / N
```

**附加指标**：Candidate Recall（候选池覆盖率）、Mean Latency、Candidate Size。

**统一实验条件**：相同仓库 Commit、相同 20 条 Query、相同 Top K=5、相同文件过滤。

**涉及文件**：`codeteam/evaluation/` 下全部文件

---

### 第 8 步：失败分析 + 生成报告

**目标**：分析 Hybrid 的失败案例，生成 `EVALUATION_WEEK2.md`。

**为什么第八步做**：实验跑完后，最值钱的工作不是看总体数字，而是看懂"为什么这条任务失败了"。

**10 种失败分类**：

```
Query Analysis Failure   → 中英文概念未对齐
Filename Recall Failure  → 文件名与业务语言不一致
ripgrep Recall Failure   → 自然语言没在代码中直接出现
Symbol Extraction Failure → 装饰器/动态工厂创建的类被漏掉
Import Resolution Failure → re-export 或动态 import 未解析
Candidate Recall Failure → Gold 不在候选池（召回问题）
Ranking Failure           → Gold 在候选池但排名太低（排序问题）
Generated/公共模块污染    → common.py 因 PageRank 过高挤掉真正文件
Test Pair Failure         → 测试文件没进入
Gold Label Failure        → 系统对但 Gold 标错
```

**管线诊断逻辑**：

```
Candidates 里有没有 Gold？
  ├── 没有 → 召回问题（QueryAnalyzer / ripgrep / SymbolExtractor）
  └── 有，但没进 Top 5 → 排名问题（FileRanker / PageRank / base_importance）
      ├── 被 Generated 挤掉 → 惩罚不够
      ├── 被 common.py 挤掉 → PageRank 过高
      └── 被超预算裁掉 → Budget 分配问题
```

**涉及文件**：`evals/week2/EVALUATION_WEEK2.md`

---

## 整体实现思路

### 六个整合工程原则

**1. 所有路径格式统一**

系统内部统一使用：POSIX 风格、相对 Git 仓库根、不以 `./` 开头。

所有以下对象都必须使用这个格式：`RepositoryFile.path`、`Symbol.path`、`ImportRecord.source_path`、`ImportEdge.source/target_path`、`CandidateFile.path`、`RankedFile.path`、`ContextItem.path`。

**2. CLI 不含业务逻辑**

CLI 层只负责参数解析和展示。业务逻辑在 `application/` 层编排，具体实现在各 domain 模块中。这样 CLI 可以换（Typer → Click → argparse），业务逻辑不受影响。

**3. 单文件失败不终止整个仓库**

真实仓库存在语法错误文件、无法解码文件、超大生成文件、符号链接、无法解析的 Import。整合流程返回"成功 N、部分 M、跳过 K、失败 P"的统计，而不是在第 76 个文件遇到 SyntaxError 就整体退出。

**4. 每次运行记录仓库版本**

评测结果关联到固定仓库状态：Git Commit SHA、工作区是否 dirty、索引配置、Parser/Grammar 版本、排名权重版本、Token Budget。否则两次评测可能运行在不同代码上却被错误比较。

**5. 人类可读和机器输出分开**

`--format text` 输出给人看（带颜色、树形结构）。`--format json` 输出给评测脚本（结构化、可对比）。不要让评测脚本解析带颜色的终端文本。

**6. 所有选择保留原因**

Top 5 不仅输出路径，还输出：为什么被召回、为什么得到这个分数、为什么进入 Top 5、为什么某个候选被省略。否则 Recall 下降时无法判断是 QueryAnalyzer 没提取出关键词、ripgrep 没搜索到正确字符串、还是 FileRanker 排名过低。

### 20 条评测数据设计指南

**避免评测泄漏**：
- ❌ "修改 src/auth/service.py 中的问题"（直接泄露路径）
- ✅ "修复 refresh token 过期后返回 500 的问题"（需要系统自己找到文件）

**Gold 数量控制**：
- 每条 required Gold：≤ 5 个
- 超过 5 个的跨模块任务：同时报告 Recall@5 和 Recall@10

**类别分布**：5 个类别 × 4 条 = 20 条。每个类别测试不同的检索能力维度，消融实验可以揭示哪个模块对哪个类别贡献最大。

### 四组消融实验的公平性

四个实验必须固定：相同仓库 Commit、相同 20 条 Query、相同 QueryAnalyzer 基础规则、相同 Top K=5、相同文件过滤范围、相同 Generated/Vendored 策略。

预期趋势（不做假设，仅为参考）：

```
Filename:       延迟低，适合文件名与 Query 接近的任务
ripgrep:        错误信息表现明显提升
ripgrep+Symbol: 精确类和函数任务明显提升
Hybrid:         跨模块、测试映射和配置任务更强
```

如果 Hybrid 反而下降，常见原因：Import 扩展噪声太多、PageRank 压过查询匹配、基础文件权重太强、测试映射产生错误候选。

---

## 测试思路

### 整合测试（上午）

至少覆盖：

```
正常仓库 → 索引构建成功，统计数字合理
空仓库   → 不崩溃，警告"无 Python 文件"
非 Git 目录 → 降级为 os.walk 扫描
部分语法错误 → 部分成功，收集警告
无规则文件 → 指令加载返回空
Token Budget 极小（128） → Map 仍生成，大量省略
同分候选 → 稳定排序
```

### 评测测试（下午）

至少覆盖：

```
确定性测试：同一配置连续运行两次 → 结果完全一致
Recall@5 计算：3 个 Gold 命中 2 个 → Recall = 0.667
Hit@5 计算：  3 个 Gold 命中 1 个 → Hit = 1.0
Candidate Recall：Gold 在候选池 vs 不在 → 区分召回/排序问题
空 Gold 列表 → ValueError
```

---

## 关键验收标准

### inspect-repo

- [ ] `codeteam inspect-repo .` 可以运行
- [ ] 输出仓库统计和目录树
- [ ] 输出重要文件和规则文件
- [ ] 输出测试、Lint 和构建命令
- [ ] 输出 Symbol 和 Import 图统计
- [ ] 局部解析失败不会终止命令
- [ ] `--format json` 输出结构化数据

### context

- [ ] `codeteam context "query"` 可以运行
- [ ] 输出 Top 5 文件（含分数和理由）
- [ ] 输出 Query Repo Map
- [ ] 输出 Token 使用情况
- [ ] 输出被省略候选及原因
- [ ] ContextPack 不超过预算

### 评测

- [ ] 建立 20 条人工标注数据
- [ ] 五个类别各 4 条
- [ ] 每条数据冻结仓库 Commit
- [ ] 每个 Gold File 有理由
- [ ] 运行四种检索方案
- [ ] 计算 Recall@5 和 Hit@5
- [ ] 按类别统计
- [ ] 至少分析 5 个失败案例
- [ ] 生成 EVALUATION_WEEK2.md

---

## 20 个验收问题

学习结束后应能独立回答：

1. 为什么整合前必须统一路径格式？
2. 为什么 CLI 不应该包含业务逻辑？
3. 为什么单个文件失败不能终止整个仓库的索引构建？
4. 为什么每次评测必须记录仓库 Commit SHA？
5. 为什么人类可读输出和机器输出必须分开？
6. 为什么 Top 5 不能只输出路径，还要保留原因？
7. `inspect-repo` 和 `context` 分别解决什么问题？
8. 为什么需要 Application Service 层，而不是 CLI 直接调用 domain 模块？
9. 什么是消融实验？为什么要跑四组而不是只跑 Hybrid？
10. Recall@5 和 Hit@5 有什么区别？为什么不能只报告 Hit@5？
11. Macro Recall@5 和 Micro Recall@5 有什么区别？
12. Gold File 为什么不应该超过 5 个？
13. 为什么不能用系统输出来决定 Gold 标注？
14. Candidate Recall 为什么是诊断召回 vs 排序问题的关键指标？
15. 10 种失败分类分别对应管线的哪个阶段？
16. 为什么 20 条数据足够发现明显 Bug，但不足以声称"系统已达生产级别"？
17. 为什么相同查询必须产生相同结果（确定性）？
18. 为什么跨模块类别的 Gold 通常分布在多个文件中？
19. 如果 Hybrid 的 Recall@5 低于 ripgrep+Symbol，可能是什么原因？
20. 评测报告为什么必须包含"下一周改进项"，且改进项要附带证据？