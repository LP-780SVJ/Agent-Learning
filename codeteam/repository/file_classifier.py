# File classification helpers will separate source files, tests, configs, documentation, generated files, and ignored paths during repository scanning.
'''
强约束、越容易误判的规则，越要放前面；越普通、越泛化的规则，越放后面
规则顺序应该是：
1. ignored
2. generated / vendored
3. test
4. docs / config / lock / build / asset / data
5. source
6. unknown
'''

from pathlib import Path

from codeteam.repository.models import FileKind


_IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".codeteam",
}

_GENERATED_DIRS = {
    "dist",
    "build",
    "htmlcov",
    "generated",
}

_VENDORED_DIRS = {
    "node_modules",
    "vendor",
}

_CONFIG_FILENAMES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    ".gitignore",
}

_BUILD_FILENAMES = {
    "Makefile",
    "Dockerfile",
}

_INSTRUCTION_FILENAMES = {
    "AGENTS.md",
    ".clinerules",
}

_LOCK_FILENAMES = {
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}

_DOC_EXTENSIONS = {
    ".md",
    ".rst",
    ".txt",
}

_DATA_EXTENSIONS = {
    ".csv",
    ".jsonl",
    ".tsv",
}

_ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
}

_BINARY_EXTENSIONS = {
    ".bin",
    ".dll",
    ".dylib",
    ".exe",
    ".o",
    ".pyc",
    ".so",
}

_SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".cpp",
    ".cc",
    ".h",
}


class FileClassifier:
    def classify(self, path: str | Path) -> FileKind:
        file_path = Path(path)
        path_parts = file_path.parts
        file_name = file_path.name
        suffix = file_path.suffix.lower()

        if any(part in _IGNORED_DIRS for part in path_parts):
            return FileKind.IGNORED

        if any(part in _GENERATED_DIRS for part in path_parts):
            return FileKind.GENERATED

        if any(part in _VENDORED_DIRS for part in path_parts):
            return FileKind.VENDORED

        if self._is_test_file(file_path):
            return FileKind.TEST

        if file_name in _INSTRUCTION_FILENAMES:
            return FileKind.INSTRUCTION

        if file_name in _LOCK_FILENAMES:
            return FileKind.LOCK

        if file_name in _CONFIG_FILENAMES:
            return FileKind.CONFIG

        if file_name in _BUILD_FILENAMES:
            return FileKind.BUILD

        if suffix in _DOC_EXTENSIONS:
            return FileKind.DOCUMENTATION

        if suffix in _DATA_EXTENSIONS:
            return FileKind.DATA

        if suffix in _ASSET_EXTENSIONS:
            return FileKind.ASSET

        if suffix in _BINARY_EXTENSIONS:
            return FileKind.BINARY

        if suffix in _SOURCE_EXTENSIONS:
            return FileKind.SOURCE

        return FileKind.UNKNOWN

    def _is_test_file(self, path: Path) -> bool:
        path_parts = path.parts
        file_name = path.name

        if "tests" in path_parts or "test" in path_parts:
            return True

        return file_name.startswith("test_") or file_name.endswith("_test.py")
