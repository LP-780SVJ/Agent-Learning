"""
codeteam.search.models - 搜索系统的统一数据模型

定义搜索参数、匹配结果和执行摘要的核心数据结构。
下游代码（RipgrepClient、QueryAnalyzer、CandidateGenerator）都消费这些模型。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel


# ----SearchQuery-------------------------------------------------------
class SearchMode(str, Enum):
    """搜索模式。

    LITERAL: 固定字符串搜索（ripgrep -F），把 pattern 当普通文本
    REGEX:   正则表达式搜索，pattern 按正则语法解释

    默认用 LITERAL 的原因：
    Agent 搜索的代码片段常含正则特殊字符（( ) [ ] . * + ?），
    如果默认 Regex，这些字符会被误解析。Literal 把它们当普通文本。
    """
    LITERAL = "literal"
    REGEX = "regex"


class CaseMode(str, Enum):
    """大小写模式。

    INSENSITIVE: 不区分大小写（ripgrep 默认行为，-i）
    SENSITIVE:   区分大小写（ripgrep -s）
    """
    INSENSITIVE = "insensitive"
    SENSITIVE = "sensitive"


@dataclass
class SearchQuery:
    """封装一次搜索的全部参数。

    为什么不用 frozen=True？
    - 它是查询请求，不是客观事实
    - QueryAnalyzer 可能分步构造、逐步补充参数

    Attributes:
        pattern: 搜索模式串，如 "UserService"、"class\\s+\\w+Error"
        mode: LITERAL 或 REGEX
        case_mode: 是否区分大小写
        file_types: 文件类型过滤（对应 rg -t），如 ["py", "js"]
        globs: 文件路径 glob 过滤（对应 rg -g），如 ["src/**", "!tests/**"]
        context_lines: 每个匹配显示前后多少行上下文（对应 rg -C）
        max_results: 全局匹配数上限（Python 端截断，注意 rg -m 是每文件的上限）
    """
    pattern: str
    mode: SearchMode = SearchMode.LITERAL
    case_mode: CaseMode = CaseMode.INSENSITIVE
    file_types: list[str] = field(default_factory=list)
    globs: list[str] = field(default_factory=list)
    context_lines: int = 0
    max_results: int = 100


# ---SearchMatch-------------------------------------------------------
@dataclass
class SearchSubmatch:
    """ripgrep 返回的一个 submatch（正则捕获组匹配）。

    start/end 是**字节偏移**（不是字符偏移），
    在匹配行的文本中从 start 到 end 位置就是匹配到的文本。

    示例：pattern = "def (\\w+)"，匹配 "def get_user(self):"
    → SearchSubmatch(start=4, end=12, text="get_user")
    （捕获组 1 匹配了函数名，不包括 "def "）
    """
    start: int       # 字节偏移起始位置
    end: int         # 字节偏移结束位置
    text: str        # 匹配到的文本内容


@dataclass
class SearchMatch:
    """一次匹配结果。

    包含匹配所在的文件、行号、完整行文本、所有 submatch
    以及上下文行。

    为什么不用 frozen=True？
    context_before/context_after 在解析 JSONL 时逐步追加——
    先收到 "match" 消息创建 SearchMatch，然后收到 "context" 消息时补充上下文。
    """
    file_path: str
    line_number: int           # 行号（1-based，与 ripgrep 保持一致）
    line_text: str             # 匹配行的完整文本
    submatches: list[SearchSubmatch] = field(default_factory=list)
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)


@dataclass
class SearchExecution:
    """一次搜索执行的完整结果。

    包含所有匹配、耗时、统计信息和错误信息。

    Attributes:
        pattern: 实际使用的搜索模式
        matches: 所有匹配结果列表
        duration_ms: 搜索耗时（毫秒）
        total_match_count: ripgrep 报告的匹配总数
        truncated: 是否因为超过 max_results 而被截断
        error: 错误信息（搜索失败时）
    """
    pattern: str
    matches: list[SearchMatch] = field(default_factory=list)
    duration_ms: float = 0.0
    total_match_count: int = 0
    truncated: bool = False
    error: str = ""

# ── 候选来源枚举 ───────────────────────────────────────────

class CandidateSource(str, Enum):
    """召回来源类型。

    每个来源有不同的权重——显式路径是最强信号，
    import 邻居是弱信号。
    """
    EXPLICIT_PATH = "explicit_path"       # 用户明确指定了文件路径
    FILENAME = "filename"                 # 文件名匹配
    SYMBOL_EXACT = "symbol_exact"         # SymbolIndex 精确名称匹配
    SYMBOL_PREFIX = "symbol_prefix"       # SymbolIndex 前缀匹配
    RIPGREP = "ripgrep"                   # ripgrep 文本搜索
    IMPORT_DEPENDENCY = "import_dependency"  # A 依赖 B → B 作为候选
    IMPORT_DEPENDENT = "import_dependent"    # B 被 A 依赖 → A 作为候选
    TEST_PAIR = "test_pair"               # 源文件的对应测试文件
    IMPORTANT_CONFIG = "important_config" # 重要配置文件


# ── 候选证据 ───────────────────────────────────────────────

class CandidateEvidence(BaseModel):
    """一条召回证据：为什么这个文件被选中。

    每条证据记录：
    - 来自哪个召回通道
    - 由哪个查询词触发
    - 人类可读的命中描述
    - 权重（用于计算 preliminary_score）
    """
    source: CandidateSource
    query_term: str | None = None
    detail: str
    line_number: int | None = None
    weight: float = 1.0

    @property
    def _dedup_key(self) -> tuple:
        """去重键：来源 + 词条 + 详情 + 行号。

        同一文件的同一条证据不会重复添加。
        """
        return (
            self.source,
            self.query_term,
            self.detail,
            self.line_number,
        )


# ── 候选文件 ───────────────────────────────────────────────

class CandidateFile(BaseModel):
    """一个候选文件 + 完整证据链 + 初步评分。

    preliminary_score 是所有证据权重的累加——
    被越多通道命中（且命中信号越强），分数越高。
    """
    path: str
    evidence: list[CandidateEvidence] = []
    preliminary_score: float = 0.0
    match_count: int = 0          # ripgrep 命中次数
    is_test: bool = False
    is_config: bool = False


class AnalyzedQuery(BaseModel):
    """一次自然语言查询的分析结果。

    把原始问题拆分为结构化的搜索信号，保留每个信号的分类标签。
    下游 CandidateGenerator 根据这些标签决定走哪路召回通道。

    为什么用 BaseModel 而不是 @dataclass？
    - AnalyzedQuery 是"分析结果"，可能被序列化（日志、调试）
    - BaseModel 自带 .model_dump() 序列化能力
    - 如果后期需要加 validation（如 paths 必须在仓库内），也方便扩展
    """
    raw_query: str                    # 原始用户问题

    # ── 分类信号 ──
    quoted_literals: list[str] = []   # 引号内的精确文本
    paths: list[str] = []             # 提取到的文件路径
    identifiers: list[str] = []       # 代码标识符（完整）
    identifier_parts: list[str] = []  # 标识符拆分后的片段
    exception_names: list[str] = []   # 异常类名（*Error / *Exception）
    error_codes: list[str] = []       # 错误码（HTTP 400-599 / AUTH-1003）
    chinese_spans: list[str] = []     # 中文连续片段

    # ── 优先级分类 ──
    primary_terms: list[str] = []     # 高优先级搜索词 → ripgrep LITERAL 搜索
    secondary_terms: list[str] = []   # 低优先级搜索词 → 辅助过滤 / 文件名匹配