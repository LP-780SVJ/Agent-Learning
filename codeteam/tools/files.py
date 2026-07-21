import os
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from codeteam.tools.base import RegisteredTool


MAX_FILE_SIZE_BYTES = 1_000_000
DEFAULT_BACKUP_DIR = ".codeteam/backups"
SKIPPED_DIR_NAMES = {
    ".codeteam",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}


@dataclass
class FileToolConfig:
    workspace_root: Path | str
    max_file_size_bytes: int = MAX_FILE_SIZE_BYTES
    backup_dir: Path | str = DEFAULT_BACKUP_DIR

    def __post_init__(self) -> None:
        workspace_root = Path(self.workspace_root).resolve()
        if not workspace_root.exists() or not workspace_root.is_dir():
            raise ValueError(f"Workspace root must be an existing directory: {workspace_root}")

        backup_dir = Path(self.backup_dir)
        if not backup_dir.is_absolute():
            backup_dir = workspace_root / backup_dir
        backup_dir = backup_dir.resolve(strict=False)

        if not _is_relative_to(backup_dir, workspace_root):
            raise ValueError("Backup directory must stay inside the workspace.")
        if self.max_file_size_bytes <= 0:
            raise ValueError("max_file_size_bytes must be positive.")

        self.workspace_root = workspace_root
        self.backup_dir = backup_dir


class ListFilesArgs(BaseModel):
    path: str = "."
    recursive: bool = True


class ReadFileArgs(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None


class WriteFileArgs(BaseModel):
    path: str
    content: str


class SearchCodeArgs(BaseModel):
    query: str = Field(min_length=1)
    path: str = "."
    max_results: int = Field(default=50, ge=1)


def list_files(args: ListFilesArgs, config: FileToolConfig) -> str:
    target = _resolve_workspace_path(args.path, config, must_exist=True)
    files = sorted(
        _relative_display_path(file_path, config)
        for file_path in _iter_files(target, args.recursive, config)
    )

    return "\n".join(files)


def read_file(args: ReadFileArgs, config: FileToolConfig) -> str:
    target = _resolve_workspace_path(args.path, config, must_exist=True)
    if not target.is_file():
        raise ValueError(f"Path is not a file: {args.path}")

    _ensure_file_size(target, config)
    content = _read_text_file(target)

    if args.start_line is None and args.end_line is None:
        return content

    start_line = args.start_line if args.start_line is not None else 1
    end_line = args.end_line
    if start_line < 1:
        raise ValueError("start_line must be >= 1.")
    if end_line is not None and end_line < start_line:
        raise ValueError("end_line must be greater than or equal to start_line.")

    lines = content.splitlines(keepends=True)
    start_index = start_line - 1
    end_index = end_line if end_line is not None else len(lines)

    return "".join(lines[start_index:end_index])


def write_file(args: WriteFileArgs, config: FileToolConfig) -> str:
    target = _resolve_workspace_path(args.path, config, must_exist=False)
    content_size = len(args.content.encode("utf-8"))
    if content_size > config.max_file_size_bytes:
        raise ValueError(
            f"Content exceeds file size limit of {config.max_file_size_bytes} bytes."
        )
    if target.exists() and not target.is_file():
        raise ValueError(f"Path is not a file: {args.path}")

    backup_path = None
    if target.exists():
        _ensure_file_size(target, config)
        backup_path = _backup_existing_file(target, config)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.content, encoding="utf-8")

    target_path = _relative_display_path(target, config)
    result = f"Wrote {content_size} bytes to {target_path}."
    if backup_path is not None:
        result += f"\nBackup saved to {_relative_display_path(backup_path, config)}."
    return result


def search_code(args: SearchCodeArgs, config: FileToolConfig) -> str:
    target = _resolve_workspace_path(args.path, config, must_exist=True)
    matches: list[str] = []
    single_file = target.is_file()

    for file_path in _iter_files(target, recursive=True, config=config):
        try:
            _ensure_file_size(file_path, config)
            lines = _read_text_file(file_path).splitlines()
        except ValueError as error:
            if not single_file and isinstance(error.__cause__, UnicodeDecodeError):
                continue
            raise

        for line_number, line in enumerate(lines, start=1):
            if args.query in line:
                path = _relative_display_path(file_path, config)
                matches.append(f"{path}:{line_number}:{line}")
                if len(matches) >= args.max_results:
                    return "\n".join(matches)

    return "\n".join(matches)


def create_file_tools(
    workspace_root: Path | str,
    max_file_size_bytes: int = MAX_FILE_SIZE_BYTES,
    backup_dir: Path | str = DEFAULT_BACKUP_DIR,
) -> list[RegisteredTool]:
    config = FileToolConfig(
        workspace_root=workspace_root,
        max_file_size_bytes=max_file_size_bytes,
        backup_dir=backup_dir,
    )

    return [
        RegisteredTool(
            name="list_files",
            description="List files inside the workspace.",
            args_schema=ListFilesArgs,
            func=lambda args: list_files(args, config),
        ),
        RegisteredTool(
            name="read_file",
            description="Read a UTF-8 text file inside the workspace.",
            args_schema=ReadFileArgs,
            func=lambda args: read_file(args, config),
        ),
        RegisteredTool(
            name="write_file",
            description="Write a UTF-8 text file inside the workspace with backup.",
            args_schema=WriteFileArgs,
            func=lambda args: write_file(args, config),
        ),
        RegisteredTool(
            name="search_code",
            description="Search text inside UTF-8 files in the workspace.",
            args_schema=SearchCodeArgs,
            func=lambda args: search_code(args, config),
        ),
    ]


def _resolve_workspace_path(
    path: str,
    config: FileToolConfig,
    must_exist: bool,
) -> Path:
    requested_path = Path(path)
    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    candidate = (config.workspace_root / requested_path).resolve(strict=False)
    if not _is_relative_to(candidate, config.workspace_root):
        raise ValueError(f"Path escapes workspace: {path}")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    return candidate


def _ensure_file_size(path: Path, config: FileToolConfig) -> None:
    size = path.stat().st_size
    if size > config.max_file_size_bytes:
        raise ValueError(
            f"File exceeds size limit of {config.max_file_size_bytes} bytes: "
            f"{_relative_display_path(path, config)}"
        )


def _iter_files(target: Path, recursive: bool, config: FileToolConfig):
    if target.is_file():
        if _is_relative_to(target.resolve(strict=False), config.workspace_root):
            yield target
        return

    if not target.is_dir():
        raise ValueError(f"Path is not a file or directory: {target}")

    for root, dir_names, file_names in os.walk(target):
        root_path = Path(root)
        dir_names[:] = [
            dir_name
            for dir_name in dir_names
            if not _should_skip_dir(root_path / dir_name, config)
        ]

        for file_name in file_names:
            file_path = root_path / file_name
            if _is_relative_to(file_path.resolve(strict=False), config.workspace_root):
                yield file_path

        if not recursive:
            break


def _backup_existing_file(path: Path, config: FileToolConfig) -> Path:
    relative_path = path.relative_to(config.workspace_root)
    backup_path = config.backup_dir / str(time.time_ns()) / relative_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(_read_text_file(path), encoding="utf-8")
    return backup_path


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"File is not valid UTF-8: {path}") from error


def _relative_display_path(path: Path, config: FileToolConfig) -> str:
    return path.relative_to(config.workspace_root).as_posix()


def _should_skip_dir(path: Path, config: FileToolConfig) -> bool:
    if path.name in SKIPPED_DIR_NAMES:
        return True
    return not _is_relative_to(path.resolve(strict=False), config.workspace_root)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
