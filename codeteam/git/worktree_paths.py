from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from pathlib import Path

WORKTREE_ROOT_ENV = "CODETEAM_WORKTREE_ROOT"
DEFAULT_WORKTREE_ROOT = Path("~/.codeteam/worktrees")


def resolve_worktree_root(
    explicit: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the shared base directory for production and eval worktrees."""
    values = os.environ if environ is None else environ
    configured = explicit or values.get(WORKTREE_ROOT_ENV) or DEFAULT_WORKTREE_ROOT
    return Path(configured).expanduser().resolve(strict=False)


def repository_worktree_root(
    repo_root: str | Path,
    *,
    worktree_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    repo = Path(repo_root).resolve(strict=True)
    base = resolve_worktree_root(worktree_root, environ=environ)
    digest = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:12]
    slug = _safe_slug(repo.name or "repository")
    return base / "repos" / f"{slug}-{digest}"


def eval_worktree_root(
    run_id: str,
    *,
    worktree_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    if not run_id or _safe_slug(run_id) != run_id:
        raise ValueError(f"Invalid eval run id: {run_id!r}")
    base = resolve_worktree_root(worktree_root, environ=environ)
    return base / "evals" / run_id


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return slug or "repository"
