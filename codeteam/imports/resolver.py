"""
PythonImportResolver: 把 ImportRecord 解析成 ImportResolution。

处理三级解析：
- 绝对导入（level=0）：查 ModuleIndex，找不到标记为 EXTERNAL
- 相对导入（level>0）：计算目标模块名，查 ModuleIndex
- 动态导入：常量参数直接查 ModuleIndex，变量参数标记 UNRESOLVED
"""
from __future__ import annotations

from codeteam.imports.models import (
    ImportRecord,
    ImportResolution,
    ImportKind,
    ResolveStatus,
)
from codeteam.imports.module_index import ModuleIndex


class PythonImportResolver:
    """将 ImportRecord 解析为具体的文件路径。

    用法：
        index = ModuleIndex(files)
        resolver = PythonImportResolver(index)
        resolution = resolver.resolve(record)
    """

    def __init__(self, module_index: ModuleIndex) -> None:
        self._index = module_index

    # ── 公开入口 ─────────────────────────────────────────────

    def resolve(self, record: ImportRecord) -> ImportResolution:
        """解析一条 ImportRecord，返回 ImportResolution。

        根据 level 分流：
        - level == 0 → 绝对导入
        - level > 0  → 相对导入
        """
        # 动态 import：常量参数尝试解析，变量参数标记 UNRESOLVED
        if record.kind == ImportKind.DYNAMIC:
            return self._resolve_dynamic(record)

        if record.level == 0:
            return self._resolve_absolute(record)
        else:
            return self._resolve_relative(record)

    # ── 绝对导入 ─────────────────────────────────────────────

    def _resolve_absolute(self, record: ImportRecord) -> ImportResolution:
        """解析绝对导入：直接查 ModuleIndex。

        import os               → module="os"        → EXTERNAL
        from auth.repo import X → module="auth.repo" → RESOLVED（如存在）
        """
        target = self._index.resolve_module(record.module)
        if target:
            return ImportResolution(
                record=record,
                status=ResolveStatus.RESOLVED,
                resolved_file=target,
            )
        # v1 不读取虚拟环境，不命中则假定为外部模块
        return ImportResolution(
            record=record,
            status=ResolveStatus.EXTERNAL,
            reason=f"模块 '{record.module}' 不在仓库索引中（可能是外部库）",
        )

    # ── 相对导入 ─────────────────────────────────────────────

    # ── 相对导入 ─────────────────────────────────────────────

    def _resolve_relative(self, record: ImportRecord) -> ImportResolution:
        """解析相对导入：计算目标模块名。

        算法：
        1. 查出源文件的模块名（如 auth.sub.service）
        2. 按 level 去掉末尾段数 → 基准包
        3. 追加目标模块名 → 完整限定名
        4. 查 ModuleIndex

        示例：
        源文件 auth/sub/service.py → 模块名 auth.sub.service
        from .repository import X (level=1)
        → 去掉最后 1 段 ['auth','sub','service'] → ['auth','sub']
        → 追加 'repository' → 'auth.sub.repository'
        """
        # 步骤 1：获取源文件的模块名
        source_module = self._index.get_module(record.source_file)
        if source_module is None:
            return ImportResolution(
                record=record,
                status=ResolveStatus.UNRESOLVED,
                reason=f"源文件 '{record.source_file}' 不在模块索引中",
            )

        # 步骤 2：按 level 去掉末尾段数
        parts = source_module.split(".")
        remove_count = record.level  # level=1 去 1 段, level=2 去 2 段

        if remove_count >= len(parts):
            return ImportResolution(
                record=record,
                status=ResolveStatus.UNRESOLVED,
                reason=(
                    f"相对层级 {record.level} 超出包 "
                    f"'{source_module}' 的范围（只有 {len(parts)} 层）"
                ),
            )

        base_parts = parts[:-remove_count] if remove_count > 0 else parts

        # 步骤 3：追加目标模块名（去掉前导点）
        target_name = record.module
        while target_name.startswith("."):
            target_name = target_name[1:]

        if target_name:
            target_module = ".".join(base_parts + [target_name])
        elif record.name:
            target_module = ".".join(base_parts + [record.name])
        else:
            # from . import X → 目标模块就是基准包本身
            target_module = ".".join(base_parts)

        # 步骤 4：查 ModuleIndex
        target_file = self._index.resolve_module(target_module)
        if target_file:
            return ImportResolution(
                record=record,
                status=ResolveStatus.RESOLVED,
                resolved_file=target_file,
            )

        return ImportResolution(
            record=record,
            status=ResolveStatus.UNRESOLVED,
            reason=f"目标模块 '{target_module}' 在仓库中不存在",
        )

    # ── 动态导入 ─────────────────────────────────────────────

    def _resolve_dynamic(self, record: ImportRecord) -> ImportResolution:
        """解析动态 import。

        常量字符串：__import__("os.path") → 查 ModuleIndex
        变量参数：  __import__(var)       → UNRESOLVED（无法静态解析）
        """
        if record.module == "<dynamic>":
            return ImportResolution(
                record=record,
                status=ResolveStatus.UNRESOLVED,
                reason="动态 import 参数不是字符串常量，无法静态解析",
            )

        # 常量参数，尝试查找
        target = self._index.resolve_module(record.module)
        if target:
            return ImportResolution(
                record=record,
                status=ResolveStatus.RESOLVED,
                resolved_file=target,
            )
        return ImportResolution(
            record=record,
            status=ResolveStatus.EXTERNAL,
            reason=f"动态导入的模块 '{record.module}' 不在仓库中",
        )
