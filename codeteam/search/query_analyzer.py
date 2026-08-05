"""
QueryAnalyzer: 把自然语言问题拆成结构化的搜索信号。

识别 7 种信号类型：
- 引号内容（5 种引号格式）
- 文件路径
- 代码标识符（CamelCase / snake_case）
- 异常名（*Error / *Exception）
- 错误码（HTTP 状态码 / 命名错误码）
- 中文片段

然后按优先级分为 primary_terms（高优）和 secondary_terms（低优）。
"""
from __future__ import annotations

import re

from codeteam.search.models import AnalyzedQuery


# ── 正则常量（模块级，编译一次，重复使用）───────────────────

# 5 种引号：英文双引号、英文单引号、反引号、中文双引号、中文单引号
_QUOTED_RE = re.compile(
    r"""
    `(?P<backtick>[^`\n]+)`
    |
    "(?P<double>[^\"\n]+)"
    |
    '(?P<single>[^'\n]+)'
    |
    \u201c(?P<cn_double>[^\u201d\n]+)\u201d
    |
    \u2018(?P<cn_single>[^\u2019\n]+)\u2019
    """,
    re.VERBOSE,
)

# CamelCase 边界：小写→大写、大写→大写小写（如 XML→Parser、HTTPS→erver）
_CAMEL_BOUNDARY_RE = re.compile(
    r"""
    (?<=[a-z0-9])(?=[A-Z])
    |
    (?<=[A-Z])(?=[A-Z][a-z])
    """,
    re.VERBOSE,
)

# snake_case / kebab-case / dot.separated 的分隔符
_SEPARATOR_RE = re.compile(r"[_\-\.]+")

# 代码标识符：以字母或下划线开头，后跟字母数字下划线
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

# 异常名：以大写开头，以 Error 或 Exception 结尾
_EXCEPTION_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception)\b")

# HTTP 错误码：HTTP 400-599，HTTP 前缀可选
_HTTP_CODE_RE = re.compile(r"\b(?:HTTP\s*)?([45]\d{2})\b", re.IGNORECASE)

# 命名错误码：全大写前缀 + 连字符 + 3 位以上数字（如 AUTH-1003、PAYMENT_5002）
_NAMED_ERROR_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9_]*\-\d{3,}\b")

# 路径：至少两级目录 + 文件名（含扩展名）
_PATH_RE = re.compile(
    r"""
    (?:
        [A-Za-z]:[\\/]
    )?
    (?:
        [A-Za-z0-9_.\- ]+[\\/]
    )+
    [A-Za-z0-9_.\- ]+
    """,
    re.VERBOSE,
)

# 中文连续片段（至少 2 个字）
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{2,}")

# 中文停用短语（过于泛化，没有搜索价值）
_GENERIC_CHINESE_TERMS: set[str] = {
    "修复",
    "问题",
    "代码",
    "出现",
    "导致",
    "检查",
    "实现",
    "解决",
    "处理",
    "修改",
    "增加",
    "删除",
    "更新",
    "添加",
    "使用",
    "如何",
    "怎么",
    "什么",
    "哪里",
    "为什么",
    "在哪里",
    "在哪个",
    "有没有",
    "能不能",
}


# ── 辅助函数 ───────────────────────────────────────────────

def _deduplicate(items: list[str]) -> list[str]:
    """去重，保持首次出现顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# ── 信号提取函数 ────────────────────────────────────────────

def _extract_quoted(text: str) -> list[str]:
    """提取所有引号内的内容。

    支持 5 种引号格式：
        "双引号"  '单引号'  `反引号`  "中文双引号"  '中文单引号'

    引号内容是用户明确指定的精确短语，直接作为 primary term。
    """
    results: list[str] = []
    for match in _QUOTED_RE.finditer(text):
        # next(group for group in match.groups() if group is not None)
        # groups() 返回所有命名捕获组，只有一个非 None（因为 | 是互斥的）
        value = next(
            group for group in match.groups() if group is not None
        )
        results.append(value.strip())
    return _deduplicate(results)


def _split_camel_case(value: str) -> list[str]:
    """按大小写边界拆分 CamelCase。

    使用 re.split 而不是 re.findall——split 在边界处切割，保留所有片段。

    'InvalidRefreshTokenError' → ['Invalid', 'Refresh', 'Token', 'Error']
    'HTTPServerError'          → ['HTTP', 'Server', 'Error']
    """
    parts = _CAMEL_BOUNDARY_RE.split(value)
    return [part for part in parts if part]


def _split_identifier(value: str) -> list[str]:
    """将标识符拆分为单词片段。

    先按分隔符（_ - .）切分，再对每个片段做 CamelCase 拆分。

    'refresh_access_token' → ['refresh', 'access', 'token']
    'user-service'         → ['user', 'service']
    """
    result: list[str] = []
    for segment in _SEPARATOR_RE.split(value):
        result.extend(_split_camel_case(segment))
    return [item for item in result if item]


def _identifier_priority(value: str) -> float:
    """计算标识符的搜索优先级。

    评分规则（越高越可能是代码标识符）：
        +2.0  含下划线（snake_case）
        +2.0  含内部大小写边界（CamelCase）
        +3.0  以 Error 或 Exception 结尾
        +1.0  含点号（方法调用链）

    score >= 2 → primary term
    score < 2  → secondary term
    """
    score = 0.0

    if "_" in value:
        score += 2.0

    if re.search(r"[a-z][A-Z]", value):
        score += 2.0
    if value.endswith(("Error", "Exception")):
        score += 3.0

    if "." in value:
        score += 1.0

    return score


def _extract_paths(text: str) -> list[str]:
    """从文本中提取文件路径。

    提取后做基本清洗：
        - 去掉句末标点（如 "auth/service.py。" → "auth/service.py"）
        - 统一反斜杠为正斜杠
        - 拒绝含 ".." 的路径（防止遍历到仓库外）
    """
    raw_paths = _PATH_RE.findall(text)
    cleaned: list[str] = []

    for path in raw_paths:
        # 去掉末尾标点
        path = path.rstrip(".,;:!?）)】] \t")
        # 统一分隔符
        path = path.replace("\\", "/")
        # 拒绝 ".."
        if ".." in path.split("/"):
            continue
        cleaned.append(path)

    return _deduplicate(cleaned)


# ── QueryAnalyzer ───────────────────────────────────────────

class QueryAnalyzer:
    """自然语言查询分析器。

    用法：
        analyzer = QueryAnalyzer()
        analyzed = analyzer.analyze("UserService 在 auth/service.py 中定义？")
        # analyzed.primary_terms   → ["auth/service.py", "UserService"]
        # analyzed.secondary_terms → ["user", "service", "定义"]
    """

    def analyze(
        self,
        query: str,
    ) -> AnalyzedQuery:
        quoted = _extract_quoted(query)

        paths = _deduplicate(
            _extract_paths(query)
        )

        identifiers = _deduplicate(
            _IDENTIFIER_RE.findall(query)
        )

        exceptions = _deduplicate(
            _EXCEPTION_RE.findall(query)
        )

        error_codes = _deduplicate([
            *[
                match.group(1)
                for match in (
                    _HTTP_CODE_RE.finditer(query)
                )
            ],
            *_NAMED_ERROR_CODE_RE.findall(query),
        ])

        identifier_parts: list[str] = []

        for identifier in identifiers:
            identifier_parts.extend(
                _split_identifier(identifier)
            )

        chinese_spans = [
            item
            for item in _CJK_RE.findall(query)
            if item not in _GENERIC_CHINESE_TERMS
        ]

        primary_terms = _deduplicate([
            *quoted,
            *paths,
            *exceptions,
            *[
                item
                for item in identifiers
                if _identifier_priority(item) >= 2
            ],
        ])

        secondary_terms = _deduplicate([
            *error_codes,
            *identifier_parts,
            *chinese_spans,
        ])

        return AnalyzedQuery(
            raw_query=query,
            quoted_literals=quoted,
            paths=paths,
            identifiers=identifiers,
            identifier_parts=_deduplicate(
                identifier_parts
            ),
            exception_names=exceptions,
            error_codes=error_codes,
            chinese_spans=chinese_spans,
            primary_terms=primary_terms,
            secondary_terms=secondary_terms,
        )
