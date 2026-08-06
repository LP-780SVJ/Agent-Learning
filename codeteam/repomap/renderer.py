"""
RepoMapRenderer: 把 RepoMap 转成稳定的文本格式。

渲染规则：
- 文件路径单独一行，以冒号结尾
- 每个符号一行，以 │ 开头
- 类名显示 class 前缀
- 函数/方法显示签名（默认）或名称（压缩后）
- 省略信息用 ⋮ 标记
- 文件之间空一行
- 末尾保留一个换行符
"""
from __future__ import annotations

from codeteam.repomap.models import (
    RepoMap,
    RepoMapFile,
    RepoMapSymbol,
    SymbolRepresentation,
)


class RepoMapRenderer:
    """把 RepoMap 结构渲染为文本。

    用法：
        renderer = RepoMapRenderer()
        text = renderer.render(repo_map)
    """

    def render(self, repo_map: RepoMap) -> str:
        """渲染完整的 RepoMap。

        Returns:
            格式稳定的文本字符串，末尾带一个换行符
        """
        lines: list[str] = []

        # 标题行
        lines.append(f"# Repository map ({repo_map.mode})")
        if repo_map.query:
            lines.append(f"# Query: {repo_map.query}")
        lines.append("")

        # 文件条目
        for file_entry in repo_map.files:
            lines.extend(self.render_file(file_entry))
            lines.append("")  # 文件间空行

        # 页脚
        if repo_map.omitted_file_count:
            lines.append(
                f"# ... {repo_map.omitted_file_count} "
                "lower-ranked files omitted"
            )
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def render_file(self, entry: RepoMapFile) -> list[str]:
        """渲染单个文件条目。"""
        lines = [f"{entry.path}:"]

        for sym in entry.symbols:
            lines.append(
                self._render_symbol(sym)
            )

        if entry.omitted_symbol_count:
            lines.append(
                f"│ ⋮ {entry.omitted_symbol_count} "
                "lower-ranked symbols omitted"
            )

        return lines

    def _render_symbol(self, sym: RepoMapSymbol) -> str:
        """渲染单个符号。"""
        # 确定展示文本
        if sym.representation == SymbolRepresentation.NAME_ONLY:
            display = sym.name
        else:
            # SIGNATURE 或 SIGNATURE_WITH_DOC
            display = sym.signature or sym.name

        # 确定前缀（类用 class 标记）
        if sym.kind == "class":
            prefix = f"class {sym.name}"
            # 如果有签名（继承信息），追加
            if sym.signature and sym.signature != sym.name:
                prefix = sym.signature
        elif sym.kind in ("function", "method"):
            prefix = display
        else:
            prefix = display

        return f"│ {prefix}"