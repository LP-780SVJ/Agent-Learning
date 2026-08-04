"""
ModuleIndex: 建立"模块名 ↔ 文件路径"的双向映射。

将仓库中的 .py 文件列表转换为可查询的模块索引。
"""
from __future__ import annotations


class ModuleIndex:
    """模块名与文件路径的双向索引。

    用法：
        index = ModuleIndex(["auth/service.py", "auth/__init__.py", "main.py"])
        index.resolve_module("auth.service")  # → "auth/service.py"
        index.get_module("auth/service.py")   # → "auth.service"
    """

    def __init__(self, files: list[str]) -> None:
        """用文件路径列表构建索引。

        Args:
            files: .py 文件的路径列表，如 ["auth/service.py", "main.py"]
                    非 .py 文件会被自动跳过。
        """
        self._module_to_file: dict[str, str] = {}
        self._file_to_module: dict[str, str] = {}

        for f in files:
            module = self._path_to_module(f)
            if module:
                self._module_to_file[module] = f
                self._file_to_module[f] = module

    # ── 查询接口 ─────────────────────────────────────────────

    def resolve_module(self, module_name: str) -> str | None:
        """模块名 → 文件路径。

        Args:
            module_name: 如 "auth.service"、"os.path"

        Returns:
            文件路径如 "auth/service.py"，找不到返回 None
        """
        return self._module_to_file.get(module_name)

    def get_module(self, file_path: str) -> str | None:
        """文件路径 → 模块名。

        Args:
            file_path: 如 "auth/service.py"

        Returns:
            模块名如 "auth.service"，找不到返回 None
        """
        return self._file_to_module.get(file_path)

    # ── 内部方法 ─────────────────────────────────────────────

    @staticmethod
    def _path_to_module(path: str) -> str | None:
        """将文件路径转换为 Python 模块名。

        规则：
            auth/service.py   → auth.service  （去掉 .py，/ 换成 .）
            auth/__init__.py  → auth          （__init__.py 代表它所在的包）
            __init__.py       → None          （根目录的 __init__.py 无意义）
            README.md         → None          （非 .py 文件）
        """
        if not path.endswith(".py"):
            return None

        no_ext = path[:-3]  # 去掉末尾的 ".py"

        # __init__.py 代表所在的包
        if no_ext.endswith("/__init__") or no_ext == "__init__":
            # "auth/__init__" → "auth"
            # 根目录的 "__init__" 无意义，跳过
            if "/" not in no_ext:
                return None
            return no_ext.rsplit("/", 1)[0]

        # 普通文件：路径分隔符 → 点号
        return no_ext.replace("/", ".")


    @property
    def module_count(self) -> int:
        """索引中的模块总数。"""
        return len(self._module_to_file)