"""
YAML Frontmatter 拆分工具。

将 Markdown 文件中的 YAML 头部与正文分离。
"""
from __future__ import annotations

import yaml


def split_frontmatter(content: str) -> tuple[dict | None, str]:
    """拆分 Markdown 文件中的 YAML Frontmatter。

    Frontmatter 格式：
        ---
        key: value
        ---
        正文内容

    Args:
        content: 文件的完整文本内容。

    Returns:
        (frontmatter_dict, body)：
        - 有有效 Frontmatter → (dict, 正文)
        - 无 Frontmatter → (None, 原文)
        - Frontmatter 格式不完整 → (None, 原文)
        - YAML 解析失败 → (None, 原文)
    """
    lines = content.splitlines()

    # 检查第一行是不是 ---
    if not lines or lines[0].strip() != "---":
        return None, content

    # 从第 2 行开始找第二个 ---
    closing_index: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closing_index = i
            break

    # 没有找到闭合的 ---
    if closing_index is None:
        return None, content

    # 提取 Frontmatter 文本和正文
    frontmatter_text = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1:])

    # 空 Frontmatter
    if not frontmatter_text.strip():
        return {}, body

    # 尝试解析 YAML
    try:
        parsed = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        # 解析失败 → 返回 None，但不丢失原文
        # （安全优先：解析失败时不激活条件规则）
        return None, content

    # YAML 解析成功但不是 dict（如只写了 `- foo`）
    if not isinstance(parsed, dict):
        return None, content

    return parsed, body