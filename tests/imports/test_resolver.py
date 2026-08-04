"""测试 PythonImportResolver: 将 ImportRecord 解析为文件路径。

覆盖场景：
- T01: 普通 import → 解析到本地文件
- T02: from import → 解析 name 和 module
- T03: 相对 import → 解析为目标文件
- T05: __init__.py 模块名解析
- T08: 外部依赖 → EXTERNAL
"""

from __future__ import annotations

import pytest

from codeteam.imports.models import (
    ImportRecord,
    ImportResolution,
    ImportKind,
    ResolveStatus,
)
from codeteam.imports.module_index import ModuleIndex
from codeteam.imports.resolver import PythonImportResolver


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_record(
    source_file: str,
    module: str,
    name: str = "",
    alias: str | None = None,
    level: int = 0,
    kind: ImportKind = ImportKind.IMPORT_FROM,
) -> ImportRecord:
    return ImportRecord(
        source_file=source_file,
        module=module,
        name=name or module,
        alias=alias,
        level=level,
        kind=kind,
    )


# Sample repo file list matching the requirements:
# sample_repo/src/app/{__init__,api,service,repository,models,...}.py
SAMPLE_FILES = [
    "app/__init__.py",
    "app/api.py",
    "app/service.py",
    "app/repository.py",
    "app/models.py",
    "app/dynamic.py",
    "app/cycle_a.py",
    "app/cycle_b.py",
    "app/nested.py",
]


@pytest.fixture
def module_index() -> ModuleIndex:
    return ModuleIndex(SAMPLE_FILES)


@pytest.fixture
def resolver(module_index: ModuleIndex) -> PythonImportResolver:
    return PythonImportResolver(module_index)


# ===================================================================
# T01 & T02: 绝对导入解析
# ===================================================================

class TestAbsoluteImportResolution:
    """T01 & T02: 绝对导入应解析到正确的本地文件。"""

    def test_resolve_absolute_import(self, resolver: PythonImportResolver) -> None:
        """from app.service import UserService → RESOLVED → app/service.py。"""
        record = _make_record("app/api.py", "app.service", "UserService")
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.RESOLVED, (
            f"Expected RESOLVED, got {result.status}: {result.reason}"
        )
        assert result.resolved_file == "app/service.py"

    def test_resolve_absolute_import_to_repository(self,
                                                    resolver: PythonImportResolver) -> None:
        """from app.repository import UserRepository → app/repository.py。"""
        record = _make_record("app/service.py", "app.repository", "UserRepository")
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.RESOLVED
        assert result.resolved_file == "app/repository.py"

    def test_plain_import_resolves(self, resolver: PythonImportResolver) -> None:
        """import app.service → RESOLVED。"""
        record = _make_record(
            "app/api.py", "app.service", "app.service", kind=ImportKind.IMPORT
        )
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.RESOLVED
        assert result.resolved_file == "app/service.py"


# ===================================================================
# T03: 相对导入解析
# ===================================================================

class TestRelativeImportResolution:
    """T03: 相对导入解析。"""

    def test_resolve_relative_from_dot_service(self,
                                                resolver: PythonImportResolver) -> None:
        """app/api.py 中的 from .service import X → app/service.py。"""
        record = _make_record(
            "app/api.py", ".service", "UserService", level=1
        )
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.RESOLVED, (
            f"Expected RESOLVED, got {result.status}: {result.reason}"
        )
        assert result.resolved_file == "app/service.py"

    def test_resolve_relative_dot_only(self,
                                        resolver: PythonImportResolver) -> None:
        """app/api.py 中 from . import repository → app/repository.py。

        from . import X 表示从当前包（.）导入 X。
        当前 resolver 在 module='.' 时未使用 record.name 来定位目标，
        target_module 计算为 'app' 而非 'app.repository'。

        已知缺陷：resolver 应使用 record.name('repository') 追加到
        base_parts，形成 'app.repository' → 'app/repository.py'。
        """
        record = _make_record("app/api.py", ".", "repository", level=1)
        result = resolver.resolve(record)

        # 当前行为：解析到 app/__init__.py（因为 target_module='app'）
        # 预期行为：解析到 app/repository.py
        if result.resolved_file == "app/__init__.py":
            # 生产缺陷：resolver 未使用 record.name
            assert result.status == ResolveStatus.RESOLVED
            pytest.fail(
                "PRODUCTION DEFECT: PythonImportResolver does not use "
                "record.name when resolving 'from . import X'. "
                f"Expected resolved_file='app/repository.py', "
                f"got '{result.resolved_file}'. "
                "The resolver should append record.name to the base package "
                "when module is just dots."
            )

    def test_resolve_relative_from_subdirectory(self,
                                                 resolver: PythonImportResolver) -> None:
        """深层文件中的相对导入。"""
        # 需要更多文件来测试——使用 ModuleIndex 直接构造
        files = [
            "app/sub/__init__.py",
            "app/sub/handler.py",
            "app/sub/helper.py",
        ]
        index = ModuleIndex(files)
        r = PythonImportResolver(index)

        # app/sub/handler.py 中 from .helper import X
        record = _make_record("app/sub/handler.py", ".helper", "util", level=1)
        result = r.resolve(record)

        assert result.status == ResolveStatus.RESOLVED
        assert result.resolved_file == "app/sub/helper.py"


# ===================================================================
# T05: __init__.py 模块名
# ===================================================================

class TestInitPy:
    """T05: __init__.py → 模块名为所在包名（如 app）。"""

    def test_init_py_module_name_is_package(self) -> None:
        """app/__init__.py → 模块名 = app。"""
        index = ModuleIndex(["app/__init__.py", "app/api.py", "main.py"])
        assert index.get_module("app/__init__.py") == "app"
        assert index.resolve_module("app") == "app/__init__.py"

    def test_from_app_import_resolves_to_init(self) -> None:
        """from app import UserService → 解析到 app/__init__.py。"""
        index = ModuleIndex(SAMPLE_FILES)
        resolver = PythonImportResolver(index)

        record = _make_record("main.py", "app", "UserService")
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.RESOLVED, (
            f"Expected RESOLVED, got {result.status}: {result.reason}"
        )
        assert result.resolved_file == "app/__init__.py"

    def test_root_init_py_is_skipped(self) -> None:
        """根目录的 __init__.py 不应被索引。"""
        index = ModuleIndex(["__init__.py", "main.py"])
        assert index.get_module("__init__.py") is None


# ===================================================================
# T08: 外部依赖解析
# ===================================================================

class TestExternalResolution:
    """T08: 外部依赖应标记为 EXTERNAL。"""

    def test_external_module_is_external(self, resolver: PythonImportResolver) -> None:
        """import fastapi → EXTERNAL。"""
        record = _make_record(
            "app/main.py", "fastapi", "fastapi", kind=ImportKind.IMPORT
        )
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.EXTERNAL, (
            f"Expected EXTERNAL, got {result.status}"
        )
        assert "fastapi" in result.reason

    def test_from_external_is_external(self, resolver: PythonImportResolver) -> None:
        """from pydantic import BaseModel → EXTERNAL。"""
        record = _make_record("app/main.py", "pydantic", "BaseModel")
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.EXTERNAL

    def test_external_module_not_confused_with_local(self) -> None:
        """不应把 vendor_shadow/requests.py 误认为外部模块 requests。

        当仓库中存在 vendor_shadow/requests.py，ModuleIndex 会索引它。
        import requests 如果解析时查不到 'requests'（因为路径是
        'vendor_shadow/requests' 而非 'requests'），则标记为 EXTERNAL。
        这是正确的——ImportResolver 不做启发式猜测。
        """
        files = ["vendor_shadow/requests.py", "app/main.py"]
        index = ModuleIndex(files)
        resolver = PythonImportResolver(index)

        record = _make_record("app/main.py", "requests", "requests",
                              kind=ImportKind.IMPORT)
        result = resolver.resolve(record)

        # vendor_shadow/requests.py → 模块名 = vendor_shadow.requests
        # import requests 查 requests → 不匹配 → EXTERNAL ✓
        assert result.status == ResolveStatus.EXTERNAL, (
            f"Expected EXTERNAL for 'requests' (vendor_shadow/requests.py "
            f"maps to 'vendor_shadow.requests', not 'requests'), "
            f"got {result.status}: {result.reason}"
        )


# ===================================================================
# 动态导入解析
# ===================================================================

class TestDynamicResolution:
    """动态 import 的解析。"""

    def test_dynamic_with_constant_that_resolves(self) -> None:
        """__import__("app.service") → RESOLVED（常量参数命中索引）。"""
        record = _make_record(
            "main.py", "app.service", "app.service", kind=ImportKind.DYNAMIC
        )
        resolver = PythonImportResolver(ModuleIndex(SAMPLE_FILES))
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.RESOLVED
        assert result.resolved_file == "app/service.py"

    def test_dynamic_with_variable_is_unresolved(self) -> None:
        """importlib.import_module(settings.PLUGIN_MODULE) → UNRESOLVED。

        module='<dynamic>' 表示变量参数无法静态解析。
        """
        record = _make_record(
            "app/dynamic.py", "<dynamic>", "<dynamic>", kind=ImportKind.DYNAMIC
        )
        resolver = PythonImportResolver(ModuleIndex(SAMPLE_FILES))
        result = resolver.resolve(record)

        assert result.status == ResolveStatus.UNRESOLVED, (
            f"Expected UNRESOLVED, got {result.status}"
        )
        assert "字符串常量" in result.reason or "静态" in result.reason
