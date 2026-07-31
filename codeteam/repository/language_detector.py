# Language detection helpers will infer each file's programming language from its path, extension, and repository conventions.
from pathlib import Path

_EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "cpp",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
}

_SPECIAL_FILENAMES = {
    "Dockerfile": "dockerfile",
    "Makefile": "makefile",
    "BUILD": "starlark",
    "BUILD.bazel": "starlark",
    "WORKSPACE": "starlark",
    "WORKSPACE.bazel": "starlark",
}

class LanguageDetector:
    def detect(self, path: str | Path) -> str | None:
        file_path = Path(path)
        file_name = file_path.name

        if(file_name in _SPECIAL_FILENAMES):
            return _SPECIAL_FILENAMES[file_name]

        suffix = file_path.suffix.lower()
        return _EXTENSION_TO_LANGUAGE.get(suffix)