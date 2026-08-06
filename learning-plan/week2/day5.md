# 第 5 天：RepoMapBuilder 与文件排序

前四天已经完成了：

```text
RepositoryScanner
→ 找到仓库文件并完成分类

AST / Tree-sitter
→ 理解文件内部语法结构

SymbolIndex / ImportGraph
→ 建立符号和文件依赖关系

CandidateGenerator
→ 根据用户需求召回一批可能相关文件
```

今天要解决的问题是：

> 候选文件可能有 20～100 个，但上下文预算只允许展示其中少量文件和符号。应该优先展示谁？每个文件展示多少？

最终流程是：

```text
用户查询
   ↓
CandidateGenerator
   ↓
20～50 个候选文件
   ↓
FileRanker
   ├─ 查询相关性
   ├─ Symbol 命中
   ├─ ripgrep 命中
   ├─ Import 图关系
   ├─ 全局 PageRank
   └─ 文件类型先验
   ↓
文件和符号排序
   ↓
RepoMapBuilder
   ├─ 选择文件
   ├─ 选择文件内符号
   ├─ 控制 Token Budget
   └─ 自动降级与裁剪
   ↓
RepoMapRenderer
   ↓
query_repo_map.txt
```

今天最核心的认识是：

> **Repo Map 不是仓库摘要文章，而是面向 LLM 的、按查询动态生成的代码结构索引。**

---

# 一、Repo Map 到底是什么

Repo Map 可以理解成代码仓库的“地铁线路图”。

完整源码像整个城市：

```text
几千条道路
数万个建筑
无数房间和设施
```

Repo Map 只保留：

```text
主要线路
重要站点
换乘关系
关键出口
```

一个 Python 仓库的 Repo Map 可能是：

```text
src/auth/api.py:
│ from auth.service import AuthService
│
│ class AuthController:
│     login(request: LoginRequest) -> TokenResponse
│     refresh(request: RefreshRequest) -> TokenResponse

src/auth/service.py:
│ class AuthService:
│     authenticate(username: str, password: str) -> User
│     refresh_access_token(token: str) -> AccessToken

src/auth/repository.py:
│ class TokenRepository:
│     find(token: str) -> RefreshToken | None
│     revoke(token: str) -> None

tests/auth/test_refresh.py:
│ test_expired_refresh_token_returns_401()
│ test_revoked_refresh_token_returns_401()
```

它没有展示：

- 完整函数实现；
- 每一个局部变量；
- 所有注释；
- 所有 Import；
- 每个测试的完整内容。

但模型已经能判断：

```text
接口入口在 api.py
业务逻辑在 service.py
Token 数据访问在 repository.py
对应测试在 test_refresh.py
```

Aider 官方把 Repo Map 定义为整个 Git 仓库的精简地图，包含重要类、函数、类型和调用签名；它会将关键定义行发送给模型，而不是发送所有源码。

---

# 二、工业界为什么需要“结构地图 + 排序”

## 1. Aider：有限上下文下选择重要代码

Aider 的 Repo Map 会：

```text
Tree-sitter 提取定义和引用
→ 构造文件依赖图
→ 图排序
→ 选择重要符号
→ 在 Token Budget 内渲染
```

官方文档明确说明，大型仓库的完整 Map 本身也可能超过上下文，所以 Aider只发送与当前对话状态最相关、且能放入预算的部分。默认 `--map-tokens` 建议值为约 1K Token；没有明确加入聊天的文件时，Map 还可能动态扩大，以便先形成全局理解。

---

## 2. GitHub：先搜索和缩小，再读取源码

GitHub 在 2026 年公开介绍 Copilot Code Review 的代码探索流程时，将工具分成：

```text
glob：发现候选路径
grep：搜索符号和调用位置
view：确定目标后读取具体代码
```

他们发现，Agent 如果过早打开大量文件，会进入“浏览循环”，持续扩大搜索范围并累积无关上下文。调整成“先缩小范围，再读取精确证据”后，平均审查成本下降约 20%，同时维持了质量。

你的 Repo Map 正是介于：

```text
grep / Symbol 搜索
和
读取完整代码
```

之间的压缩层。

---

## 3. Meta Glean：索引事实，再让工具查询

Meta 的 Glean 会预先收集代码中的定义、引用和其他语义事实，通过统一查询系统支持代码浏览、代码搜索和文档生成。它的核心思路不是每次用户查询都重新解析整个仓库，而是：

```text
解析一次
→ 保存结构化代码事实
→ 多个工具复用
``` 


对应到你的项目：

```text
SymbolIndex / ImportGraph
是底层事实

FileRanker
根据任务计算相关性

RepoMapRenderer
生成面向模型的视图
```

---

## 4. Google Kythe：完整图存储与精简服务视图分离

Google 的 Kythe 会把定义、声明和引用转成跨语言图，再对图进行合并、裁剪和服务优化，从而支持代码搜索和交叉引用。Google公开介绍的代码搜索流程中，会保留完整索引事实，但在服务层裁剪不必要的数据，以提高查询效率。

这给 CodeTeam 一个重要设计原则：

```text
完整 SymbolIndex 和 ImportGraph
不能因为 Repo Map 没展示而删除

Repo Map
只是针对某次任务生成的临时视图
```

---

# 三、实际观察 Aider Repo Map

在已经安装 Aider、并进入一个 Git 仓库后执行：

```bash
aider --show-repo-map > aider_repo_map.txt
```

`--show-repo-map` 会输出当前 Repo Map 后退出；Aider 官方 FAQ 也建议通过这一命令为仓库生成 Map 文件。

建议再做三组对比：

```bash
aider \
  --show-repo-map \
  --map-tokens 512 \
  > map_512.txt

aider \
  --show-repo-map \
  --map-tokens 1024 \
  > map_1024.txt

aider \
  --show-repo-map \
  --map-tokens 4096 \
  > map_4096.txt
```

在交互会话中，还可以使用：

```text
/map
```

查看当前 Map。Aider 的 `/map` 命令用于打印当前仓库地图。

---

## 需要重点观察什么

### 1. 哪些文件被保留

通常优先出现：

```text
被其他文件频繁引用的模块
重要公共类
入口文件
用户刚刚提到的文件
用户刚刚提到的标识符定义文件
少量项目特殊文件
```

### 2. 哪些函数被省略

观察同一个文件：

```text
文件里可能有 30 个函数
Repo Map 只展示 4～8 个
```

被保留的往往是：

```text
被其他文件使用的公共 API
用户问题中提到的函数
具有较高图关系权重的符号
```

Aider 官方文档指出，示例 Map 并不会包含文件中的全部类和函数，而会优先保留被代码库其他部分更多引用的重要标识符。

### 3. 大文件如何展示

Aider 不会直接把大文件全文放进 Map，而是围绕被选中的定义行渲染必要上下文，用省略标记跳过其余部分。其当前实现会根据选中定义的行号生成结构化上下文，并将过长输出行裁剪到最多约 100 个字符。

### 4. Token 数量变化

比较：

```text
512 Token
1024 Token
4096 Token
```

观察增加预算后：

- 是增加了更多文件；
- 还是在现有文件中增加更多函数；
- 哪些低排名文件最后才出现；
- 生成文件和私有函数是否仍被排除。

---

# 四、Aider 的 Tree-sitter Tags

## 1. Tag 是什么

Tree-sitter 的代码导航规范使用 Query 找出可命名实体，并用 Capture 标记：

```text
角色：definition 或 reference
类型：class、function、call、module 等
名称：@name
```

例如 Python 函数：

```scheme
(function_definition
  name: (identifier) @name)
  @definition.function
```

含义是：

```text
整个 function_definition
→ 函数定义

identifier
→ 函数名称
```

Tree-sitter 官方推荐使用：

```text
@role.kind
```

这种 Capture 命名方式，例如 `@definition.function` 和 `@reference.call`。

---

## 2. Aider 中的简化 Tag

Aider 内部最终会形成类似：

```python
Tag(
    rel_fname="src/auth/service.py",
    fname="/repo/src/auth/service.py",
    name="refresh_token",
    kind="def",
    line=42,
)
```

或者：

```python
Tag(
    rel_fname="src/auth/api.py",
    name="refresh_token",
    kind="ref",
    line=18,
)
```

概念上：

```text
def Tag
表示该文件定义了某标识符

ref Tag
表示该文件引用了某标识符
```

然后构造关系：

```text
api.py 引用了 refresh_token
service.py 定义了 refresh_token

因此：
api.py → service.py
```

---

# 五、Definition 与 Reference 如何形成依赖图

假设仓库中有：

```python
# src/auth/service.py

def refresh_access_token(token: str) -> AccessToken:
    ...
```

```python
# src/auth/api.py

from auth.service import refresh_access_token

def refresh(request):
    return refresh_access_token(request.token)
```

提取：

```text
service.py:
definition refresh_access_token

api.py:
reference refresh_access_token
```

形成边：

```text
api.py ──refresh_access_token──> service.py
```

如果：

```text
api.py 引用了 3 次
worker.py 引用了 1 次
```

可以建立带权边：

```text
api.py    ──weight=3──> service.py
worker.py ──weight=1──> service.py
```

---

## Aider 当前实现中的细节

查看 Aider 当前源码可以发现，它使用 `MultiDiGraph`，将引用文件指向定义文件，并给边附加标识符和权重。对高频引用次数先取平方根，避免某个标识符仅因为出现次数很多就完全支配排序。

当前实现还包含一些启发式：

```text
当前聊天提到的标识符
→ 权重明显提高

较长的 snake_case / kebab-case / CamelCase 标识符
→ 提高权重

以下划线开头的私有名称
→ 降低权重

同名定义超过一定数量的常见名称
→ 降低权重
```

Aider 当前源码中，对被明确提到的标识符和长度足够的结构化标识符会增加权重；以下划线开头或定义位置过多的名称会被降权。

这背后的工程逻辑是：

```text
refresh_access_token
信息量高

run
get
data
信息量低

_private_helper
通常不是跨模块公共入口
```

---

# 六、PageRank 是怎么发挥作用的

## 1. 普通引用次数为什么不够

假设：

```text
common.py 被 50 个测试 Fixture 引用

auth_service.py 被 api.py、worker.py 引用

api.py 又是整个系统的重要入口
```

简单按引用数：

```text
common.py = 50
auth_service.py = 2
```

会认为 `common.py` 更重要。

但 PageRank 会考虑：

> 引用你的文件本身是否重要。

类比网页：

```text
100 个无关小站链接你
不一定比
一个权威网站链接你
更重要
```

---

## 2. 代码图中的 PageRank

你的 Import Graph 方向定义为：

```text
A import B
→ A → B
```

因此：

```text
越多重要文件依赖 B
→ B 的 PageRank 越高
```

例如：

```text
api.py ────────> service.py
worker.py ─────> service.py
service.py ────> repository.py
```

如果 `api.py` 和 `worker.py` 本身重要，`service.py` 会获得较高分；其部分重要性又会继续传给 `repository.py`。

NetworkX 的 `pagerank()` 会根据有向图入边结构计算节点排名，默认阻尼系数为 `0.85`，并支持通过 `personalization` 为部分节点赋予更高的随机跳转概率。

---

## 3. Personalized PageRank

普通 PageRank 回答：

```text
整个仓库中，哪些文件全局重要？
```

个性化 PageRank 回答：

```text
针对当前查询，哪些文件重要？
```

用户问：

```text
修复 refresh token 过期返回 500
```

初始相关文件：

```text
auth/api.py
auth/service.py
auth/exceptions.py
```

个性化向量可以是：

```python
personalization = {
    "src/auth/api.py": 0.4,
    "src/auth/service.py": 0.4,
    "src/auth/exceptions.py": 0.2,
}
```

PageRank 会从这些查询相关文件附近传播重要性。

Aider 当前实现也会根据已加入聊天的文件、聊天中提及的文件和路径标识符构造 personalization，并将其交给 NetworkX PageRank。

---

## 4. PageRank 不能单独决定最终排名

PageRank 只表示：

```text
图结构中的重要性
```

它不知道用户正在问什么。

例如：

```text
src/common/logging.py
```

可能全局 PageRank 很高，但查询是：

```text
修复购物车折扣计算
```

因此最终得分必须是混合得分：

```text
查询相关性
+
Symbol 命中
+
ripgrep 命中
+
图邻居
+
PageRank
+
文件基础权重
-
生成代码惩罚
```

---

# 七、第一版 FileRanker 设计

## 1. 排名信号

推荐将每个信号归一化到 `[0, 1]`：

```python
class FileSignals(BaseModel):
    query_match: float = 0.0
    symbol_match: float = 0.0
    ripgrep_match: float = 0.0

    import_one_hop: float = 0.0
    import_two_hop: float = 0.0

    global_pagerank: float = 0.0
    personalized_pagerank: float = 0.0

    base_importance: float = 0.0
    test_relevance: float = 0.0

    generated_penalty: float = 0.0
    vendored_penalty: float = 0.0
    binary_penalty: float = 0.0
```

---

## 2. 推荐第一版公式

```text
最终得分 =
    4.0 × 查询直接匹配
  + 4.0 × Symbol 匹配
  + 2.5 × ripgrep 匹配
  + 1.8 × Import 一跳
  + 0.8 × Import 两跳
  + 1.0 × 文件基础权重
  + 1.0 × 测试相关性
  + 1.2 × Personalized PageRank
  + 0.4 × Global PageRank
  - 4.0 × Generated 惩罚
  - 5.0 × Vendored 惩罚
  - 10  × Binary 惩罚
```

这不是行业标准，只是适合学习阶段的初始值。

优先关系应大致是：

```text
用户直接给出路径
≈ 精确 Symbol 定义
> 精确错误信息
> 一跳依赖
> 文件名关键词
> 两跳依赖
> 全局重要性
```

---

## 3. Query Match

查询：

```text
修改 src/auth/service.py 中的 UserService.refresh
```

信号：

```text
完整路径精确命中：1.0
完整文件名命中：0.8
目录名命中：0.4
拆词命中：0.2
```

不要把多个弱关键词简单无限累加。

推荐采用饱和函数：

```python
def saturate(value: float) -> float:
    return 1.0 - math.exp(-value)
```

例如 20 次 `service` 命中不会让分数无限增长。

---

## 4. Symbol Match

```text
精确 Qualified Name：1.0
精确短名称：0.9
Prefix：0.5
Reference：0.4
拆分词：0.2
```

示例：

```text
查询 InvalidRefreshTokenError
```

定义该类的文件：

```text
symbol_match = 1.0
```

仅引用该异常的文件：

```text
symbol_match = 0.5
```

---

## 5. Ripgrep Match

需要考虑：

```text
匹配词的重要性
匹配次数
匹配是否位于测试
匹配是否只是注释
```

第一版：

```python
score = 0.0

for evidence in ripgrep_evidence:
    if evidence.term_kind == "quoted_literal":
        score += 1.0
    elif evidence.term_kind == "exact_identifier":
        score += 0.8
    elif evidence.term_kind == "error_code":
        score += 0.3
    else:
        score += 0.15

ripgrep_score = min(
    1.0,
    math.log1p(score) / math.log(4),
)
```

---

## 6. Import 一跳和两跳

从强候选扩展：

```text
强候选 → 一跳邻居
一跳邻居 → 两跳邻居
```

例如：

```text
api.py → service.py → repository.py
```

用户查询命中 `api.py`：

```text
api.py         query direct = 1.0
service.py     one hop = 1.0
repository.py  two hop = 1.0
```

经过权重后：

```text
api.py > service.py > repository.py
```

防止一个公共模块扩散到全仓库：

```text
一跳最多扩展 10 个
两跳最多扩展 15 个
高出度节点降低扩展权重
```

---

## 7. 文件基础权重

可以沿用第一天的 `importance_score`：

| 文件角色 | 基础倾向 |
|---|---:|
| 明确入口 | 高 |
| Instruction | 高 |
| Build / Config | 中高 |
| 普通 Source | 中 |
| Test | 中 |
| Documentation | 中低 |
| Migration | 低 |
| Lock | 低 |
| Generated | 极低 |
| Vendored | 极低 |
| Binary | 0 |

注意：

```text
基础权重只负责兜底
不能压过查询直接相关性
```

否则 `README.md` 会在所有查询中都排名很高。

---

# 八、排名结果必须可解释

## 1. 数据模型

```python
class RankingEvidence(BaseModel):
    signal: str
    value: float
    weight: float
    contribution: float
    reason: str


class RankedFile(BaseModel):
    path: str
    final_score: float
    rank: int

    signals: FileSignals
    evidence: list[RankingEvidence]

    matched_symbols: list[str] = []
    matched_lines: list[int] = []

    is_generated: bool = False
    is_test: bool = False
```

输出示例：

```json
{
  "path": "src/auth/service.py",
  "final_score": 8.73,
  "rank": 1,
  "evidence": [
    {
      "signal": "symbol_match",
      "value": 1.0,
      "weight": 4.0,
      "contribution": 4.0,
      "reason": "Defines refresh_access_token"
    },
    {
      "signal": "ripgrep_match",
      "value": 0.82,
      "weight": 2.5,
      "contribution": 2.05,
      "reason": "Matched InvalidRefreshTokenError at line 54"
    },
    {
      "signal": "import_one_hop",
      "value": 1.0,
      "weight": 1.8,
      "contribution": 1.8,
      "reason": "Imported by src/auth/api.py"
    }
  ]
}
```

这样才能回答验收要求：

> 为什么这个文件进入 Top 5？

---

## 2. 稳定排序

同分文件必须有确定性 Tie-break：

```python
ranked = sorted(
    files,
    key=lambda item: (
        -round(item.final_score, 8),
        item.path.casefold(),
        item.path,
    ),
)
```

不要依赖：

```text
set 遍历顺序
文件系统扫描顺序
NetworkX 节点插入偶然顺序
并发任务完成顺序
```

同一输入必须得到同一输出。

---

# 九、FileRanker 实现骨架

```python
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RankingWeights:
    query_match: float = 4.0
    symbol_match: float = 4.0
    ripgrep_match: float = 2.5

    import_one_hop: float = 1.8
    import_two_hop: float = 0.8

    base_importance: float = 1.0
    test_relevance: float = 1.0

    personalized_pagerank: float = 1.2
    global_pagerank: float = 0.4

    generated_penalty: float = 4.0
    vendored_penalty: float = 5.0
    binary_penalty: float = 10.0


class FileRanker:
    def __init__(
        self,
        weights: RankingWeights | None = None,
    ) -> None:
        self.weights = weights or RankingWeights()

    def rank(
        self,
        candidates: list[CandidateFile],
        *,
        global_pagerank: dict[str, float] | None = None,
        personalized_pagerank: dict[str, float] | None = None,
    ) -> list[RankedFile]:
        global_pagerank = self._normalize(
            global_pagerank or {}
        )
        personalized_pagerank = self._normalize(
            personalized_pagerank or {}
        )

        ranked: list[RankedFile] = []

        for candidate in candidates:
            signals = self._build_signals(
                candidate,
                global_pagerank=global_pagerank,
                personalized_pagerank=personalized_pagerank,
            )

            evidence = self._explain(signals)
            final_score = sum(
                item.contribution
                for item in evidence
            )

            ranked.append(
                RankedFile(
                    path=candidate.path,
                    final_score=final_score,
                    rank=0,
                    signals=signals,
                    evidence=evidence,
                    matched_symbols=[],
                    matched_lines=[
                        item.line_number
                        for item in candidate.evidence
                        if item.line_number is not None
                    ],
                    is_generated=candidate.is_generated,
                    is_test=candidate.is_test,
                )
            )

        ranked.sort(
            key=lambda item: (
                -round(item.final_score, 8),
                item.path.casefold(),
                item.path,
            )
        )

        for index, item in enumerate(
            ranked,
            start=1,
        ):
            item.rank = index

        return ranked

    @staticmethod
    def _normalize(
        values: dict[str, float],
    ) -> dict[str, float]:
        if not values:
            return {}

        maximum = max(values.values())

        if maximum <= 0:
            return {
                key: 0.0
                for key in values
            }

        return {
            key: value / maximum
            for key, value in values.items()
        }
```

`_build_signals()` 负责把第四天的 `CandidateEvidence` 聚合成标准信号。

---

# 十、使用 NetworkX PageRank

## 1. 构图

沿用第三天方向：

```text
A import B
→ A → B
```

```python
import networkx as nx


def build_networkx_graph(
    import_graph: ImportGraph,
) -> nx.DiGraph:
    graph = nx.DiGraph()

    for path in sorted(
        import_graph.all_nodes()
    ):
        graph.add_node(path)

    for edge in sorted(
        import_graph.all_edges(),
        key=lambda item: (
            item.source_path,
            item.target_path,
        ),
    ):
        current = graph.get_edge_data(
            edge.source_path,
            edge.target_path,
            default={},
        )

        previous_weight = float(
            current.get("weight", 0.0)
        )

        graph.add_edge(
            edge.source_path,
            edge.target_path,
            weight=previous_weight
            + max(edge.confidence, 0.1),
        )

    return graph
```

---

## 2. Global PageRank

```python
def compute_global_pagerank(
    graph: nx.DiGraph,
) -> dict[str, float]:
    if graph.number_of_nodes() == 0:
        return {}

    if graph.number_of_edges() == 0:
        uniform = 1.0 / graph.number_of_nodes()
        return {
            node: uniform
            for node in graph.nodes
        }

    return nx.pagerank(
        graph,
        alpha=0.85,
        weight="weight",
        max_iter=100,
        tol=1e-6,
    )
```

---

## 3. Personalized PageRank

```python
def compute_personalized_pagerank(
    graph: nx.DiGraph,
    seed_scores: dict[str, float],
) -> dict[str, float]:
    valid = {
        path: max(score, 0.0)
        for path, score in seed_scores.items()
        if path in graph
    }

    total = sum(valid.values())

    if total <= 0:
        return compute_global_pagerank(graph)

    personalization = {
        path: score / total
        for path, score in valid.items()
    }

    return nx.pagerank(
        graph,
        alpha=0.85,
        personalization=personalization,
        dangling=personalization,
        weight="weight",
        max_iter=100,
        tol=1e-6,
    )
```

NetworkX 官方接口支持同时传入 `personalization` 和 `dangling`；Aider 当前实现也会在存在查询个性化信号时将同一向量用于这两个参数。

---

## 4. 失败降级

```python
from networkx.exception import (
    PowerIterationFailedConvergence,
)


def safe_pagerank(
    graph: nx.DiGraph,
    personalization: dict[str, float] | None,
) -> dict[str, float]:
    try:
        return nx.pagerank(
            graph,
            alpha=0.85,
            personalization=personalization,
            dangling=personalization,
            max_iter=100,
            tol=1e-6,
        )
    except (
        PowerIterationFailedConvergence,
        ZeroDivisionError,
    ):
        return degree_fallback(graph)
```

PageRank 是排序增强项，不能因为它失败导致整个 Repo Map 无法生成。

---

# 十一、从文件排序进入符号排序

文件排到第一，不代表要展示它的所有函数。

需要第二级排序：

```text
文件级排名
→ 决定展示哪些文件

符号级排名
→ 决定每个文件展示哪些类和函数
```

---

## 1. 符号分数

```text
符号得分 =
    5 × 用户精确提及
  + 3 × 查询词匹配
  + 2 × 被 Top 文件引用
  + 1 × 全局引用次数
  + 1 × 公共 API
  + 1 × 类或函数定义
  - 1 × 私有符号
  - 1 × 超长实现
```

推荐：

| 信号 | 分值 |
|---|---:|
| 精确 Qualified Name | 5 |
| 精确短名称 | 4 |
| Prefix | 2 |
| ripgrep 命中位于该符号范围 | 2 |
| 被高分文件引用 | 2 |
| 公共类 | 1.5 |
| 公共函数或方法 | 1 |
| 测试函数相关 | 1 |
| `_private` | -1 |
| 自动生成 | -5 |

---

## 2. 符号表示级别

```python
class SymbolRepresentation(str, Enum):
    FULL_BODY = "full_body"
    SIGNATURE_WITH_DOC = "signature_with_doc"
    SIGNATURE = "signature"
    NAME_ONLY = "name_only"
    OMITTED = "omitted"
```

今天的 Repo Map 默认：

```text
类：
类声明 + 选中的方法签名

函数：
装饰器 + 函数签名

常量：
仅保留高相关常量

函数实现：
通常不保留
```

---

## 3. 示例裁剪

原文件：

```python
class AuthService:
    def __init__(self, repository, cache):
        ...

    def login(self, username, password):
        # 80 行实现
        ...

    def refresh_access_token(
        self,
        token: str,
    ) -> AccessToken:
        # 120 行实现
        ...

    def logout(self, token):
        ...

    def _decode_internal_payload(self, token):
        ...

    def _cleanup_cache(self):
        ...
```

查询：

```text
修复 refresh token 过期异常
```

Repo Map：

```text
src/auth/service.py:
│ class AuthService:
│     def refresh_access_token(
│         self,
│         token: str,
│     ) -> AccessToken
│
│     def _decode_internal_payload(
│         self,
│         token: str,
│     )
│
│     ⋮ 4 other methods omitted
```

不是：

```text
展示整个 250 行类
```

---

# 十二、Token Budget

## 1. Token Budget 要分层

假设总 Repo Map 预算：

```text
2,000 Token
```

可以分配：

| 部分 | 预算 |
|---|---:|
| Map 标题和说明 | 100 |
| 项目重要文件 | 200 |
| Top 文件路径 | 150 |
| 类和函数签名 | 1,350 |
| 文件省略信息 | 100 |
| 安全余量 | 100 |

---

## 2. 为什么不能只限制字符数

Token 与字符数不是固定比例，尤其存在：

```text
中文
长标识符
JSON
缩进
特殊符号
不同模型 tokenizer
```

最终必须使用目标模型对应的 Token Counter。

接口：

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        ...
```

测试环境可以使用确定性近似：

```python
class ApproximateTokenCounter:
    def count(self, text: str) -> int:
        return max(
            1,
            len(text.encode("utf-8")) // 4,
        )
```

生产环境再使用模型适配层的真实 tokenizer。

---

## 3. Aider 如何逼近预算

Aider 当前实现会先取得排序后的 Tag，然后尝试不同数量的前缀进行渲染，再计算 Token 数。它使用类似二分搜索的方式调整 Tag 数量，寻找接近最大 Map Token 预算的结果；当前源码接受约 15% 的预算误差范围。

你的第一版可以先采用更容易解释的贪心算法。

---

# 十三、RepoMapBuilder

## 1. 数据模型

```python
class RepoMapSymbol(BaseModel):
    symbol_id: str
    name: str
    qualified_name: str
    kind: SymbolKind

    signature: str | None
    line: int

    score: float
    representation: SymbolRepresentation


class RepoMapFile(BaseModel):
    path: str
    file_score: float
    reasons: list[str]

    symbols: list[RepoMapSymbol]
    omitted_symbol_count: int = 0

    estimated_tokens: int = 0


class RepoMap(BaseModel):
    mode: str
    query: str | None

    budget_tokens: int
    used_tokens: int

    files: list[RepoMapFile]

    omitted_file_count: int
    truncated: bool
```

---

## 2. Builder 流程

```text
取得 RankedFile
→ 对每个文件排序 Symbol
→ 生成最小文件条目
→ 估算 Token
→ 按分数依次加入
→ 超预算则压缩
→ 仍超预算则跳过
→ 生成最终 RepoMap
```

---

## 3. 压缩顺序

超出预算时不要立即删除整个文件。

按以下顺序降级：

```text
完整签名 + 装饰器 + 文档
→ 完整签名
→ 单行签名
→ Symbol 名称
→ 仅文件路径
→ 删除文件
```

例如：

```text
第一版：
@router.post("/refresh")
async def refresh_token(
    request: RefreshRequest,
    service: AuthService,
) -> TokenResponse

压缩：
async def refresh_token(...) -> TokenResponse

继续压缩：
refresh_token()

最终：
src/auth/api.py
```

---

## 4. 贪心构建骨架

```python
class RepoMapBuilder:
    def __init__(
        self,
        *,
        renderer: "RepoMapRenderer",
        token_counter: TokenCounter,
        budget_tokens: int,
    ) -> None:
        self.renderer = renderer
        self.token_counter = token_counter
        self.budget_tokens = budget_tokens

    def build(
        self,
        *,
        ranked_files: list[RankedFile],
        symbol_index: SymbolIndex,
        query: str | None,
        mode: str,
    ) -> RepoMap:
        selected: list[RepoMapFile] = []
        omitted_files = 0

        for ranked_file in ranked_files:
            entry = self._build_file_entry(
                ranked_file=ranked_file,
                symbols=symbol_index.symbols_in_file(
                    ranked_file.path
                ),
                query=query,
            )

            accepted = self._fit_entry(
                selected=selected,
                candidate=entry,
                query=query,
                mode=mode,
            )

            if not accepted:
                omitted_files += 1

        draft = RepoMap(
            mode=mode,
            query=query,
            budget_tokens=self.budget_tokens,
            used_tokens=0,
            files=selected,
            omitted_file_count=omitted_files,
            truncated=omitted_files > 0,
        )

        rendered = self.renderer.render(draft)
        draft.used_tokens = (
            self.token_counter.count(rendered)
        )

        return draft
```

---

## 5. 判断是否能加入

```python
def _fit_entry(
    self,
    *,
    selected: list[RepoMapFile],
    candidate: RepoMapFile,
    query: str | None,
    mode: str,
) -> bool:
    representations = [
        SymbolRepresentation.SIGNATURE_WITH_DOC,
        SymbolRepresentation.SIGNATURE,
        SymbolRepresentation.NAME_ONLY,
    ]

    for representation in representations:
        compressed = self._compress_entry(
            candidate,
            representation,
        )

        trial = RepoMap(
            mode=mode,
            query=query,
            budget_tokens=self.budget_tokens,
            used_tokens=0,
            files=[*selected, compressed],
            omitted_file_count=0,
            truncated=False,
        )

        text = self.renderer.render(trial)
        tokens = self.token_counter.count(text)

        if tokens <= self.budget_tokens:
            compressed.estimated_tokens = tokens
            selected.append(compressed)
            return True

    return False
```

该实现容易理解，但每次都会重新渲染整个 Map。仓库较大后，可进一步：

```text
缓存每个 Entry 各压缩级别的 Token 数
+
维护当前 Token 增量
```

---

# 十四、RepoMapRenderer

## 1. Renderer 只负责展示

Renderer 不应该决定：

```text
哪些文件更重要
哪些符号进入 Map
Token 怎么分配
```

它只负责把 `RepoMap` 转成稳定文本。

```python
class RepoMapRenderer:
    def render(
        self,
        repo_map: RepoMap,
    ) -> str:
        lines: list[str] = []

        lines.append(
            f"# Repository map ({repo_map.mode})"
        )

        if repo_map.query:
            lines.append(
                f"# Query: {repo_map.query}"
            )

        lines.append("")

        for file_entry in repo_map.files:
            lines.extend(
                self._render_file(file_entry)
            )

        if repo_map.omitted_file_count:
            lines.append(
                f"# ... {repo_map.omitted_file_count} "
                "lower-ranked files omitted"
            )

        return "\n".join(lines).rstrip() + "\n"
```

---

## 2. 文件渲染

```python
def _render_file(
    self,
    entry: RepoMapFile,
) -> list[str]:
    lines = [
        f"{entry.path}:",
    ]

    for symbol in entry.symbols:
        prefix = self._symbol_prefix(
            symbol.kind
        )

        if symbol.representation == (
            SymbolRepresentation.SIGNATURE
        ):
            display = (
                symbol.signature
                or symbol.name
            )
        else:
            display = symbol.name

        lines.append(
            f"│ {prefix}{display}"
        )

    if entry.omitted_symbol_count:
        lines.append(
            "│ ⋮ "
            f"{entry.omitted_symbol_count} "
            "lower-ranked symbols omitted"
        )

    lines.append("")
    return lines
```

---

## 3. 是否把排名原因写进 Map

建议输出两份内容。

### 面向 LLM

```text
query_repo_map.txt
```

保持精简：

```text
src/auth/service.py:
│ class AuthService:
│     refresh_access_token(token: str) -> AccessToken
```

### 面向调试

```text
query_repo_map_debug.json
```

包含：

```text
分数
所有 Ranking Evidence
Token
被省略原因
符号分数
```

不建议把所有数字和理由塞进 LLM Map，因为这些调试信息本身也消耗 Token。

但可以保留一句极简说明：

```text
# Selected: exact symbol + imported by auth/api.py
```

仅用于开发阶段。

---

# 十五、Global Repo Map

Global Map 不提供用户查询。

它回答：

```text
这个仓库整体有哪些核心模块？
```

排序信号：

```text
Global PageRank
+
文件基础重要性
+
公开 Symbol 数量
+
被引用次数
+
入口文件
+
重要配置
-
Generated / Vendored
```

示例：

```text
# Repository map (global)

AGENTS.md
pyproject.toml

src/main.py:
│ create_app() -> FastAPI

src/auth/service.py:
│ class AuthService:
│     authenticate(...) -> User
│     refresh_access_token(...) -> AccessToken

src/users/service.py:
│ class UserService:
│     get_user(...) -> User
│     create_user(...) -> User

src/common/database.py:
│ create_session() -> AsyncSession
```

没有查询时，也不能返回空 Map。

Aider 的 Repo Map 在没有明确加入聊天文件时，会扩大 Map 预算以提供更广泛的仓库视图；当前配置项 `--map-multiplier-no-files` 默认值为 2。

---

# 十六、Query Repo Map

查询：

```text
修复 InvalidRefreshTokenError 导致 refresh 接口返回 500
```

输出：

```text
# Repository map (query)
# Query: 修复 InvalidRefreshTokenError 导致 refresh 接口返回 500

src/auth/exceptions.py:
│ class InvalidRefreshTokenError(TokenError)

src/auth/service.py:
│ class AuthService:
│     refresh_access_token(
│         token: str
│     ) -> AccessToken

src/auth/api.py:
│ class AuthController:
│     refresh(
│         request: RefreshRequest
│     ) -> TokenResponse

tests/auth/test_refresh.py:
│ test_expired_refresh_token_returns_401()
│ test_invalid_refresh_token_returns_401()

src/auth/repository.py:
│ class TokenRepository:
│     find(token: str) -> RefreshToken | None
```

查询换成：

```text
优化订单导出任务的内存占用
```

排名应该明显变化：

```text
orders/exporter.py
orders/worker.py
orders/repository.py
tests/orders/test_exporter.py
common/streaming.py
```

这就是验收项中的：

> 查询变化时排名变化。

---

# 十七、生成代码为什么不应占据主要 Map

假设：

```text
src/generated/openapi_client.py
```

有 500 个类和 3,000 个方法。

如果只按 Symbol 数量：

```text
generated/openapi_client.py
会压过所有人工代码
```

因此 Generated 文件要：

```text
保留索引
降低排名
默认只展示少量公共入口
尽量找到生成源
```

例如：

```text
openapi.yaml
→ 生成
src/generated/openapi_client.py
```

Repo Map 应优先展示：

```text
openapi.yaml
生成命令或配置
人工封装层 client_wrapper.py
```

而不是生成文件的 3,000 个方法。

Google Kythe 也专门区分生成代码与源代码关系，使工具能够跨生成边界导航，同时避免让用户只能面对难读的生成实现。

---

# 十八、稳定性设计

## 1. 所有输入都排序

```python
files = sorted(
    files,
    key=lambda item: item.path,
)

symbols = sorted(
    symbols,
    key=lambda item: (
        -item.score,
        item.qualified_name,
        item.range.start.line,
    ),
)
```

## 2. 浮点数固定精度

```python
stable_score = round(
    score,
    8,
)
```

## 3. PageRank 图节点顺序固定

构图前：

```python
for path in sorted(paths):
    graph.add_node(path)
```

## 4. 渲染换行固定

```text
统一使用 \n
文件末尾保留一个换行
```

## 5. 不在输出中放时间戳

否则同一输入每次文件内容都会不同，不利于 Snapshot Test。

---

# 十九、缓存

今天可以先不完成，但架构应预留三层缓存。

```text
Tag Cache
key = path + content_hash + grammar_version

Ranking Cache
key = repository_snapshot_hash + query_analysis

Render Cache
key = ranked_symbols + budget + renderer_version
```

Aider 当前实现也缓存 Tag、Map 和渲染后的 Tree Context，并会根据文件修改时间和 Map 参数决定是否复用。

---

# 二十、推荐目录结构

```text
codeteam/
├── ranking/
│   ├── models.py
│   ├── file_ranker.py
│   ├── symbol_ranker.py
│   ├── pagerank.py
│   └── normalizers.py
│
├── repomap/
│   ├── models.py
│   ├── builder.py
│   ├── renderer.py
│   ├── budget.py
│   └── compressor.py
│
└── usage/
    └── token_counter.py

tests/
├── ranking/
│   ├── test_file_ranker.py
│   ├── test_symbol_ranker.py
│   └── test_pagerank.py
│
└── repomap/
    ├── test_builder.py
    ├── test_renderer.py
    ├── test_budget.py
    └── snapshots/
```

---

# 二十一、测试任务

## 1. 同一查询结果稳定

```python
def test_same_query_is_deterministic(
    ranker: FileRanker,
    candidates: list[CandidateFile],
) -> None:
    first = ranker.rank(candidates)
    second = ranker.rank(
        list(reversed(candidates))
    )

    assert [
        item.path
        for item in first
    ] == [
        item.path
        for item in second
    ]
```

候选输入顺序不同，最终结果仍应一致。

---

## 2. 无查询仍能展示核心结构

准备：

```text
src/main.py
src/auth/service.py
src/common/database.py
README.md
generated/client.py
```

无 Query 时应优先出现：

```text
main.py
auth/service.py
common/database.py
重要配置
```

不能：

```text
Repo Map 为空
```

---

## 3. 查询变化时排名变化

```python
auth_rank = ranker.rank(
    candidates_for(
        "refresh token error"
    )
)

order_rank = ranker.rank(
    candidates_for(
        "order export memory"
    )
)

assert auth_rank[0].path != (
    order_rank[0].path
)
```

进一步验证：

```text
auth 查询 Top 5 中至少 3 个 auth 文件
order 查询 Top 5 中至少 3 个 order 文件
```

---

## 4. Generated 不占主要 Map

构造：

```text
generated/client.py：500 个 Symbol
src/client_wrapper.py：5 个 Symbol
```

查询：

```text
修改客户端请求重试逻辑
```

即使 Generated Symbol 数量很多，也应优先：

```text
client_wrapper.py
```

除非查询明确写出：

```text
generated/client.py
```

---

## 5. Map 不超过预算

```python
def test_map_never_exceeds_budget() -> None:
    repo_map = builder.build(
        ranked_files=ranked_files,
        symbol_index=symbol_index,
        query="refresh token",
        mode="query",
    )

    text = renderer.render(repo_map)
    used = token_counter.count(text)

    assert used <= 1024
```

建议测试：

```text
预算 128
预算 256
预算 512
预算 1024
```

---

## 6. 大文件只展示相关符号

文件包含：

```text
100 个函数
```

查询只命中：

```text
refresh_access_token
```

Map 应包含：

```text
refresh_access_token
相关异常辅助函数
```

而不是全部 100 个函数。

---

## 7. 一跳优于两跳

图：

```text
api.py → service.py → repository.py
```

查询直接命中 `api.py`。

断言：

```text
score(api.py)
>
score(service.py)
>
score(repository.py)
```

除非 `repository.py` 有更强的直接查询证据。

---

## 8. PageRank 不能压过精确查询

构造：

```text
common.py
被 100 个文件 Import

rare_bug.py
精确定义 UserSpecifiedRareError
```

查询：

```text
UserSpecifiedRareError
```

断言：

```text
rare_bug.py
排名高于
common.py
```

---

# 二十二、Snapshot Test

Repo Map 是文本格式，非常适合 Snapshot Test。

```python
def test_query_repo_map_snapshot(
    snapshot,
) -> None:
    repo_map = builder.build(
        ranked_files=ranked_files,
        symbol_index=symbol_index,
        query="refresh token error",
        mode="query",
    )

    rendered = renderer.render(repo_map)

    snapshot.assert_match(
        rendered,
        "query_refresh_token.txt",
    )
```

当 Renderer 变化时，可以直接观察：

```diff
+ 新增了 test_refresh.py
- 删除了 generated/client.py
```

比只断言文件数更容易发现排序退化。

---

# 二十三、今日产出示例

## `global_repo_map.txt`

```text
# Repository map (global)

AGENTS.md

pyproject.toml

src/main.py:
│ create_app() -> FastAPI

src/auth/service.py:
│ class AuthService:
│     authenticate(
│         username: str,
│         password: str
│     ) -> User
│     refresh_access_token(
│         token: str
│     ) -> AccessToken

src/users/service.py:
│ class UserService:
│     get_user(user_id: int) -> User
│     create_user(data: UserCreate) -> User

src/common/database.py:
│ create_session() -> AsyncSession

# ... 72 lower-ranked files omitted
```

---

## `query_repo_map.txt`

```text
# Repository map (query)
# Query: 修复 InvalidRefreshTokenError 导致 refresh 接口返回 500

src/auth/exceptions.py:
│ class InvalidRefreshTokenError(TokenError)

src/auth/service.py:
│ class AuthService:
│     refresh_access_token(
│         token: str
│     ) -> AccessToken
│     _decode_refresh_token(
│         token: str
│     ) -> TokenPayload

src/auth/api.py:
│ class AuthController:
│     refresh(
│         request: RefreshRequest
│     ) -> TokenResponse

tests/auth/test_refresh.py:
│ test_expired_token_returns_401()
│ test_invalid_token_returns_401()

src/auth/repository.py:
│ class TokenRepository:
│     find(token: str) -> RefreshToken | None

# ... 18 lower-ranked files omitted
```

---

# 二十四、今日详细任务安排

## 第一阶段：观察 Aider，约 60 分钟

运行：

```bash
aider \
  --show-repo-map \
  --map-tokens 512 \
  > map_512.txt

aider \
  --show-repo-map \
  --map-tokens 1024 \
  > map_1024.txt

aider \
  --show-repo-map \
  --map-tokens 4096 \
  > map_4096.txt
```

记录：

```text
每份 Map 的 Token 预算
文件数量
符号数量
最大单文件符号数
被省略的重要函数
Generated 文件情况
```

---

## 第二阶段：研究 Aider 源码，约 60 分钟

重点阅读当前 `repomap.py` 中：

```text
get_tags
get_ranked_tags
get_ranked_tags_map
render_tree
to_tree
token_count
```

重点回答：

1. Definition 和 Reference 怎样变成图边？
2. 为什么对引用次数取平方根？
3. 为什么长 CamelCase / snake_case 名称加权？
4. 为什么私有名称降权？
5. Personalization 来自哪里？
6. 怎样找到接近 Token Budget 的 Tag 数量？
7. 为什么只渲染 Lines of Interest？

---

## 第三阶段：实现 FileRanker，约 90 分钟

完成：

```text
FileSignals
RankingEvidence
RankedFile
RankingWeights
FileRanker
```

支持：

```text
查询匹配
Symbol
ripgrep
Import 一跳
Import 两跳
基础权重
Generated 惩罚
```

先不接 PageRank，也能产生稳定排序。

---

## 第四阶段：加入 PageRank，约 60 分钟

实现：

```text
build_networkx_graph
compute_global_pagerank
compute_personalized_pagerank
safe_pagerank
```

验证：

```text
公共核心文件全局分高
查询相关子图个性化分高
循环依赖不会失败
无边图能够降级
```

---

## 第五阶段：实现 SymbolRanker，约 50 分钟

支持：

```text
查询精确符号
Prefix
引用次数
公共/私有
测试符号
Generated 惩罚
```

确保：

```text
文件排名
和
文件内符号排名
是两套逻辑
```

---

## 第六阶段：实现 RepoMapBuilder，约 75 分钟

完成：

```text
RepoMap
RepoMapFile
RepoMapSymbol
预算分配
逐级压缩
超预算跳过
省略计数
```

---

## 第七阶段：实现 Renderer，约 45 分钟

输出：

```text
global_repo_map.txt
query_repo_map.txt
ranking_debug.json
```

要求：

```text
输出顺序稳定
函数签名易读
文件之间有空行
省略信息明确
结尾只有一个换行
```

---

## 第八阶段：测试和评估，约 60 分钟

至少完成：

```text
稳定性
无查询
查询变化
Generated 降权
预算限制
一跳/两跳
PageRank
符号裁剪
大文件
Snapshot
```

建议不少于 20 个测试。

---

# 二十五、今日验收问题

学习结束后，应能清晰回答：

1. Repo Map 和完整代码摘要有什么区别？
2. 为什么 Repo Map 仍然不能包含全部符号？
3. Definition 和 Reference 如何形成文件图？
4. 为什么简单引用计数不等于代码重要性？
5. PageRank 为什么适合代码依赖图？
6. Global PageRank 和 Personalized PageRank 有什么区别？
7. 为什么 PageRank 不能独立决定最终排名？
8. 为什么查询直接匹配必须高于全局图权重？
9. 为什么一跳邻居应高于两跳邻居？
10. 为什么公共工具模块容易在图排序中过度占优？
11. 为什么引用次数应使用对数或平方根压缩？
12. 为什么文件排名和符号排名必须分开？
13. 为什么大文件应该展示相关函数，而不是整个文件？
14. 为什么 Generated 文件不能完全删除，但应该降权？
15. Token 超限时应按什么顺序压缩？
16. 为什么不能直接按字符数量限制 Map？
17. 为什么同一查询的输出必须完全稳定？
18. 为什么排名理由应保存在调试数据，而不是全部写进 LLM Map？
19. 为什么 Global Map 在没有 Query 时也不能为空？
20. 为什么 Repo Map 只是视图，而 SymbolIndex 必须保留完整信息？

---

# 今日最终目录

```text
codeteam/
├── ranking/
│   ├── models.py
│   ├── file_ranker.py
│   ├── symbol_ranker.py
│   └── pagerank.py
│
├── repomap/
│   ├── models.py
│   ├── builder.py
│   ├── renderer.py
│   ├── compressor.py
│   └── budget.py
│
└── usage/
    └── token_counter.py

tests/
├── ranking/
│   ├── test_file_ranker.py
│   ├── test_symbol_ranker.py
│   └── test_pagerank.py
│
└── repomap/
    ├── test_builder.py
    ├── test_renderer.py
    ├── test_budget.py
    └── snapshots/

artifacts/
├── global_repo_map.txt
├── query_repo_map.txt
└── ranking_debug.json
```

今天最重要的工程链路是：

```text
CandidateGenerator
负责“不漏”

FileRanker
负责“谁优先”

SymbolRanker
负责“文件中展示什么”

RepoMapBuilder
负责“预算内选择多少”

RepoMapRenderer
负责“怎样高密度地展示给模型”
```