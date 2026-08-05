"""
FilenameIndex: 文件名倒排索引。

把仓库所有文件路径按文件名分词建索引，支持快速搜索。
搜索时忽略大小写——输入 "user" 能匹配到 UserRepository.py。
"""
from __future__ import annotations

import re


class FilenameIndex:
    """文件名倒排索引。

    用法：
        index = FilenameIndex()
        index.add("auth/user_service.py")
        index.add("models/UserRepository.py")
        results = index.search("user")
        # → ["auth/user_service.py", "models/UserRepository.py"]
    """

    def __init__(self) -> None:
        # token → 文件路径集合
        self._by_token: dict[str, set[str]] = {}# set天然去重，避免重复添加同一文件

    # ── 写入 ──────────────────────────────────────────────────

    def add(self, file_path: str) -> None:
        """向索引中添加一个文件。

        将文件名拆分成 token，每个 token 关联到这个文件路径。
        同一文件重复添加不会产生重复记录（因为用 set 存储）。

        Args:
            file_path: 文件路径，如 "auth/user_service.py"
        """
        tokens = self._tokenize(file_path)
        for token in tokens:
            token = token.lower()
            if token not in self._by_token:
                self._by_token[token] = set()
            self._by_token[token].add(file_path)

    def add_batch(self, file_paths: list[str]) -> None:
        """批量添加文件。"""
        for fp in file_paths:
            self.add(fp)

    # ── 查询 ──────────────────────────────────────────────────

    def search(self, term: str) -> list[str]:
        """搜索文件名包含指定词条的文件。

        忽略大小写。返回排序后的文件路径列表。
        无结果时返回空列表（不抛异常）。

        Args:
            term: 搜索词，如 "user"、"service"、"repository"

        Returns:
            匹配的文件路径列表（按字母序）
        """
        results = self._by_token.get(term.lower(), set())
        return sorted(results)

    # ── 分词 ──────────────────────────────────────────────────

    @staticmethod
    def _tokenize(file_path: str) -> set[str]:
        """将文件路径拆分成搜索 token。

        三层切分策略：
        1. 取文件名（去掉目录部分）
        2. 按 _ - . 分隔符切分
        3. 再按大小写边界切分（CamelCase → camel, case）

        保留完整原名，确保完整类名搜索也能命中。

        示例：
            auth/user_service.py → {user_service, user, service, py}
            models/UserRepo.py   → {UserRepo, User, Repo, userrepo, py}
        """
        # 取文件名（去掉目录前缀）
        filename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        tokens: set[str] = set()

        # ① 完整文件名和扩展名
        tokens.add(filename)
        if "." in filename:
            name_part, ext = filename.rsplit(".", 1)
            tokens.add(ext)          # "py"
        else:
            name_part = filename
        tokens.add(name_part)         # "user_service" / "UserRepository"

        # ② 按分隔符切分
        for part in re.split(r"[_\-\.]", name_part):
            if not part:
                continue
            tokens.add(part)          # "user" / "service"

            # ③ 按大小写边界切分
            # r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)'
            #   ↑           ↑
            #   可选的单个大写  连续大写字母，但后面不能是小写
            #   + 小写序列    （避免把 Upper 拆成 Upp 和 er）
            #
            # UserRepository → ["User", "Repository"]
            # XMLParser      → ["XML", "Parser"]  ✅ 不是 ["X", "M", "L", "Parser"]
            for word in re.findall(
                r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)",
                part,
            ):
                tokens.add(word.lower())

        return tokens

    # ── 统计 ──────────────────────────────────────────────────

    @property
    def total_files(self) -> int:
        """索引中的文件总数（去重）。"""
        all_files: set[str] = set()
        for paths in self._by_token.values():
            all_files.update(paths)
        return len(all_files)

    @property
    def total_tokens(self) -> int:
        """索引中的 token 总数。"""
        return len(self._by_token)