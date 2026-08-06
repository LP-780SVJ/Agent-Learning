"""测试 ImportExtractor: 从 Python AST 提取 import 语句。

覆盖场景：
- T01: 普通 import（import app.service / import ... as ...）
- T02: from import（from X import Y / from X import Y as Z）
- T03: 相对 import（from .service import ... / from . import ...）
- T04: 别名（as 绑定）
- T08: 外部依赖（import fastapi → 正确记录模块名）
- T10: 动态 import（is_dynamic / UNRESOLVED）
"""

from __future__ import annotations

import ast
import textwrap

import pytest

from codeteam.imports.models import ImportRecord, ImportKind
from codeteam.imports.extractor import ImportExtractor


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _extract(source: str, file_path: str = "test.py") -> list[ImportRecord]:
    source = textwrap.dedent(source).strip()
    tree = ast.parse(source)
    extractor = ImportExtractor(file_path)
    return extractor.extract(tree)


# ===================================================================
# T01: 普通 Import
# ===================================================================

class TestPlainImport:
    """T01: import app.service / import app.repository as repository。

    断言：
    - requested_modules: app.service, app.repository
    - local_bindings: app (alias=None), repository (alias="repository")
    """

    def test_import_single_module(self) -> None:
        """import app.service → module=app.service, alias=None。"""
        records = _extract("import app.service\n", "app/api.py")

        assert len(records) == 1
        r = records[0]
        assert r.kind == ImportKind.IMPORT
        assert r.module == "app.service"
        assert r.name == "app.service"
        assert r.alias is None
        assert r.source_file == "app/api.py"
        assert r.level == 0

    def test_import_with_alias(self) -> None:
        """import app.repository as repository → alias='repository'。"""
        records = _extract("import app.repository as repository\n", "app/api.py")

        assert len(records) == 1
        r = records[0]
        assert r.module == "app.repository"
        assert r.alias == "repository"

    def test_import_multiple_modules(self) -> None:
        """import os, json as j → 两条记录。"""
        records = _extract("import os, json as j\n", "test.py")

        assert len(records) == 2
        modules = {r.module for r in records}
        assert modules == {"os", "json"}

        # json as j → alias='j'
        json_rec = next(r for r in records if r.module == "json")
        assert json_rec.alias == "j"

        # os → alias=None
        os_rec = next(r for r in records if r.module == "os")
        assert os_rec.alias is None


# ===================================================================
# T02: From Import
# ===================================================================

class TestFromImport:
    """T02: from app.service import UserService / from X import Y as Z。

    断言：
    - module = app.service
    - name = UserService
    - binding = UserService（alias=None 时绑定同 name）
    - binding = UserModel（alias="UserModel" 时绑定 alias）
    """

    def test_from_import_single_name(self) -> None:
        """from app.service import UserService。"""
        records = _extract(
            "from app.service import UserService\n", "app/api.py"
        )

        assert len(records) == 1
        r = records[0]
        assert r.kind == ImportKind.IMPORT_FROM
        assert r.module == "app.service"
        assert r.name == "UserService"
        assert r.alias is None
        assert r.source_file == "app/api.py"

    def test_from_import_with_alias(self) -> None:
        """from app.models import User as UserModel → alias='UserModel'。"""
        records = _extract(
            "from app.models import User as UserModel\n", "app/api.py"
        )

        assert len(records) == 1
        r = records[0]
        assert r.module == "app.models"
        assert r.name == "User"
        assert r.alias == "UserModel"

    def test_from_import_multiple_names(self) -> None:
        """from X import A, B as C → 两条记录。"""
        records = _extract(
            "from app.models import User, Token as AccessToken\n", "app/api.py"
        )

        assert len(records) == 2
        names = {r.name for r in records}
        assert names == {"User", "Token"}

        token_rec = next(r for r in records if r.name == "Token")
        assert token_rec.alias == "AccessToken"


# ===================================================================
# T03: 相对 Import
# ===================================================================

class TestRelativeImport:
    """T03: from .service import UserService / from . import repository。

    断言解析出的 module 包含前导点：
    - from .service import X → module=".service", level=1
    - from . import X → module=".", level=1
    """

    def test_relative_from_import(self) -> None:
        """from .service import UserService → level=1, module='.service'。"""
        records = _extract(
            "from .service import UserService\n", "app/api.py"
        )

        assert len(records) == 1
        r = records[0]
        assert r.level == 1
        assert r.module == ".service"
        assert r.name == "UserService"

    def test_relative_import_dot_only(self) -> None:
        """from . import repository → level=1, module='.'。"""
        records = _extract(
            "from . import repository\n", "app/api.py"
        )

        assert len(records) == 1
        r = records[0]
        assert r.level == 1
        assert r.module == "."

    def test_double_dot_relative_import(self) -> None:
        """from ..parent import Base → level=2, module='..parent'。"""
        records = _extract(
            "from ..parent import Base\n", "app/sub/module.py"
        )

        assert len(records) == 1
        r = records[0]
        assert r.level == 2
        assert r.module == "..parent"
        assert r.name == "Base"

    def test_relative_import_level_with_module_name(self) -> None:
        """from .repository import UserRepository → module 含前导点。"""
        records = _extract(
            "from .repository import UserRepository\n", "app/service.py"
        )

        assert len(records) == 1
        r = records[0]
        assert r.level == 1
        assert r.module == ".repository"
        assert r.name == "UserRepository"


# ===================================================================
# T04: 别名 (as binding)
# ===================================================================

class TestAlias:
    """T04: 别名——本地绑定名字的验证。

    import app.service as service_module → 本地绑定 = service_module
    from app.models import User as DomainUser → 本地绑定 = DomainUser
    """

    def test_import_as_alias(self) -> None:
        """import app.service as service_module。"""
        records = _extract(
            "import app.service as service_module\n", "app/api.py"
        )
        r = records[0]
        assert r.module == "app.service"
        assert r.alias == "service_module"

    def test_from_import_as_alias(self) -> None:
        """from app.models import User as DomainUser。"""
        records = _extract(
            "from app.models import User as DomainUser\n", "app/api.py"
        )
        r = records[0]
        assert r.name == "User"
        assert r.alias == "DomainUser"

    def test_no_alias_means_alias_is_none(self) -> None:
        """没有 as 时 alias 应为 None。"""
        records = _extract("import os\n", "test.py")
        assert records[0].alias is None

        records2 = _extract("from os import path\n", "test.py")
        assert records2[0].alias is None


# ===================================================================
# T08: 外部依赖
# ===================================================================

class TestExternalDependency:
    """T08: 外部依赖的 import 语句正确记录。

    import fastapi → module="fastapi", kind=IMPORT
    from pydantic import BaseModel → module="pydantic", name="BaseModel"

    ImportExtractor 只负责提取，不负责解析。外部性由 Resolver 判断。
    """

    def test_import_external_module(self) -> None:
        """import fastapi → module='fastapi'。"""
        records = _extract("import fastapi\n", "app/main.py")

        assert len(records) == 1
        r = records[0]
        assert r.module == "fastapi"
        assert r.kind == ImportKind.IMPORT

    def test_from_external_import(self) -> None:
        """from pydantic import BaseModel。"""
        records = _extract(
            "from pydantic import BaseModel\n", "app/main.py"
        )

        assert len(records) == 1
        r = records[0]
        assert r.module == "pydantic"
        assert r.name == "BaseModel"
        assert r.kind == ImportKind.IMPORT_FROM

    def test_external_module_with_alias(self) -> None:
        """import numpy as np。"""
        records = _extract("import numpy as np\n", "app/main.py")

        r = records[0]
        assert r.module == "numpy"
        assert r.alias == "np"


# ===================================================================
# T10: 动态 Import
# ===================================================================

class TestDynamicImport:
    """T10: 无法解析的动态 import。

    断言：
    - is_dynamic = True（kind=DYNAMIC）
    - requested_module = None 或 "<dynamic>"（变量参数时）
    - 不猜测模块名

    注意：已知缺陷 —— ImportExtractor._extract_string_arg() 方法
    被调用但未定义，动态 import 提取会崩溃。
    """

    def test_dynamic_import_via_importlib(self) -> None:
        """importlib.import_module(settings.PLUGIN_MODULE) → DYNAMIC。

        变量参数无法静态解析，module 应为 '<dynamic>'。
        """
        source = (
            "import importlib\n"
            "module = importlib.import_module(settings.PLUGIN_MODULE)\n"
        )
        try:
            records = _extract(source, "app/dynamic.py")
        except AttributeError as exc:
            if "_extract_string_arg" in str(exc):
                pytest.fail(
                    "Production defect: ImportExtractor._extract_string_arg() "
                    "is called but not defined. "
                    f"Error: {exc}"
                )
            raise

        dynamic_records = [r for r in records if r.kind == ImportKind.DYNAMIC]
        assert len(dynamic_records) >= 1, (
            f"Expected at least 1 DYNAMIC record, got {len(dynamic_records)}"
        )
        dyn = dynamic_records[0]
        # 变量参数 → module 应为 '<dynamic>'
        assert dyn.module == "<dynamic>", (
            f"Expected module='<dynamic>' for variable arg, got '{dyn.module}'"
        )

    def test_dynamic_import_via_dunder_import(self) -> None:
        """__import__(variable) → DYNAMIC。"""
        source = "mod = __import__(some_var)\n"
        try:
            records = _extract(source, "app/dynamic.py")
        except AttributeError as exc:
            if "_extract_string_arg" in str(exc):
                pytest.fail(
                    "Production defect: ImportExtractor._extract_string_arg() "
                    "is called but not defined."
                )
            raise

        dynamic_records = [r for r in records if r.kind == ImportKind.DYNAMIC]
        assert len(dynamic_records) >= 1

    def test_dynamic_import_with_constant_string(self) -> None:
        """__import__("os.path") → DYNAMIC with constant module name。"""
        source = "mod = __import__('os.path')\n"
        try:
            records = _extract(source, "app/dynamic.py")
        except AttributeError as exc:
            if "_extract_string_arg" in str(exc):
                pytest.fail(
                    "Production defect: ImportExtractor._extract_string_arg() "
                    "is called but not defined."
                )
            raise

        dynamic_records = [r for r in records if r.kind == ImportKind.DYNAMIC]
        assert len(dynamic_records) >= 1
