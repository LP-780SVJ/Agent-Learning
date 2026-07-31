# RepositoryScanner will walk the workspace and collect the directory tree, important files, file types, languages, and project metadata.
'''
拿到路径
  -> detect language
  -> classify file kind
  -> 读取文件大小
  -> 组装 RepositoryFile
'''

import os
from pathlib import Path
import subprocess

from codeteam.repository.file_classifier import FileClassifier
from codeteam.repository.language_detector import LanguageDetector
from codeteam.repository.models import FileKind, RepositoryFile, RepositorySnapshot


_IMPORTANT_CONFIG_FILENAMES = {
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    ".gitignore",
}

_WALK_IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".codeteam",
}

'''
运行：
    scanner = RepositoryScanner(".")
    snapshot = scanner.scan()
内部流程是：
    RepositoryScanner(".")
        ↓
    self.root = 当前仓库绝对路径
        ↓
    scan()
        ↓
    _is_git_repo()
        ↓
    _git_files()
        ├─ git ls-files -z
        └─ git ls-files --others --exclude-standard -z
        ↓
    得到相对路径列表
        ↓
    _build_repository_file(path)
        ├─ LanguageDetector.detect(path)
        ├─ FileClassifier.classify(path)
        └─ full_path.stat().st_size
        ↓
    RepositorySnapshot(...)
'''

class RepositoryScanner:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.language_detector = LanguageDetector()
        self.file_classifier = FileClassifier()

    def scan(self) -> RepositorySnapshot:
        is_git_repo = self._is_git_repo()

        if is_git_repo:
            relative_paths = self._git_files()
        else:
            relative_paths = self._walk_files()
        files = []

        for relative_path in relative_paths:
            repository_file = self._build_repository_file(relative_path)

            if repository_file.kind == FileKind.IGNORED:
                continue

            files.append(repository_file)

        return RepositorySnapshot(
            root=self.root,
            files=files,
            is_git_repo=is_git_repo,
            important_configs=self._find_important_configs(files),
        )

    def _is_git_repo(self) -> bool:# 判断是不是Git仓库
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

        return result.returncode == 0 and result.stdout.strip() == "true"

    def _git_files(self) -> list[str]:# 获取Git仓库中的所有文件，包括已跟踪和未跟踪的文件
        tracked_files = self._run_git_ls_files(["git", "ls-files", "-z"])
        untracked_files = self._run_git_ls_files(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"]
        )

        all_files = set(tracked_files)# 使用set去重，避免重复文件
        all_files.update(untracked_files)

        return sorted(all_files)

    def _run_git_ls_files(self, argv: list[str]) -> list[str]:# 运行git ls-files命令并解析-z输出
        result = subprocess.run(
            argv,
            cwd=self.root,
            capture_output=True,
            text=False,
        )

        if result.returncode != 0:
            error_message = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"Git command failed: {error_message}")

        paths = []

        for raw_path in result.stdout.split(b"\0"):
            if not raw_path:
                continue

            paths.append(raw_path.decode("utf-8", errors="replace"))

        return paths

    def _build_repository_file(self, relative_path: str) -> RepositoryFile:# 把路径构建为RepositoryFile对象
        full_path = self.root / relative_path
        size_bytes = full_path.stat().st_size

        return RepositoryFile(
            path=relative_path,
            language=self.language_detector.detect(relative_path),
            kind=self.file_classifier.classify(relative_path),
            size_bytes=size_bytes,
        )

    def _find_important_configs(self, files: list[RepositoryFile]) -> list[str]:# 查找重要的配置文件
        important_configs = []

        for file in files:
            file_name = Path(file.path).name

            if file_name in _IMPORTANT_CONFIG_FILENAMES:
                important_configs.append(file.path)

        return sorted(important_configs)

    def _walk_files(self) -> list[str]:
        relative_paths = []

        for current_dir, dir_names, file_names in os.walk(self.root):
            dir_names[:] = [
                name for name in dir_names
                if name not in _WALK_IGNORED_DIRS
            ]

            current_path = Path(current_dir)

            for file_name in file_names:
                full_path = current_path / file_name
                relative_path = full_path.relative_to(self.root).as_posix()
                relative_paths.append(relative_path)

        return sorted(relative_paths)