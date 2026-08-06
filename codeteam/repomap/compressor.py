"""
压缩器：把文件的符号列表逐级降级。

压缩顺序（越来越省 Token）：
    SIGNATURE_WITH_DOC → SIGNATURE → NAME_ONLY → 仅路径 → 删除
"""
from __future__ import annotations

from codeteam.repomap.models import (
    RepoMapFile,
    RepoMapSymbol,
    SymbolRepresentation,
)


def compress_entry(
    entry: RepoMapFile,
    target_level: SymbolRepresentation,
) -> RepoMapFile:
    """把文件条目的所有符号压缩到目标表示级别。

    已有符号降级，omit 的符号不展示。

    Args:
        entry: 原始文件条目
        target_level: 目标表示级别

    Returns:
        压缩后的新条目（不修改原 entry）
    """
    if target_level == SymbolRepresentation.OMITTED:
        # 全部删除——这个文件不再展示任何符号，仅保留路径
        return RepoMapFile(
            path=entry.path,
            file_score=entry.file_score,
            reasons=entry.reasons,
            symbols=[],
            omitted_symbol_count=entry.omitted_symbol_count + len(entry.symbols),
        )

    # 降级每个符号的表示级别
    new_symbols: list[RepoMapSymbol] = []
    omitted_count = entry.omitted_symbol_count

    for sym in entry.symbols:
        # 比较两个枚举值的大小：SIGNATURE_WITH_DOC > SIGNATURE > NAME_ONLY
        if _representation_order(sym.representation) <= _representation_order(target_level):
            # 符号的表示级别已经 <= 目标级别，保持不变
            new_symbols.append(sym)
        elif target_level == SymbolRepresentation.NAME_ONLY:
            # 降级到仅名称
            new_symbols.append(
                RepoMapSymbol(
                    symbol_id=sym.symbol_id,
                    name=sym.name,
                    qualified_name=sym.qualified_name,
                    kind=sym.kind,
                    signature=None,
                    line=sym.line,
                    score=sym.score,
                    representation=SymbolRepresentation.NAME_ONLY,
                )
            )
        else:
            # 符号的表示级别太高，被 omit
            omitted_count += 1

    return RepoMapFile(
        path=entry.path,
        file_score=entry.file_score,
        reasons=entry.reasons,
        symbols=new_symbols,
        omitted_symbol_count=omitted_count,
    )


def _representation_order(rep: SymbolRepresentation) -> int:
    """表示级别的排序权重。"""
    order = {
        SymbolRepresentation.SIGNATURE_WITH_DOC: 3,
        SymbolRepresentation.SIGNATURE: 2,
        SymbolRepresentation.NAME_ONLY: 1,
        SymbolRepresentation.OMITTED: 0,
    }
    return order.get(rep, 2)