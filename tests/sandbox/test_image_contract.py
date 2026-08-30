from __future__ import annotations

import re
from pathlib import Path

from codeteam.sandbox.models import DEFAULT_SANDBOX_IMAGE, SandboxProfile


def _context_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docker" / "sandbox"


def test_project_owned_verification_image_is_minimal_and_version_pinned() -> None:
    context = _context_root()
    dockerfile = (context / "Dockerfile").read_text(encoding="utf-8")
    requirements = (context / "requirements.txt").read_text(
        encoding="utf-8"
    ).splitlines()

    assert re.search(
        (
            r"^FROM python:3\.11\.\d+-slim-bookworm@sha256:"
            r"[0-9a-f]{64}$"
        ),
        dockerfile,
        re.MULTILINE,
    )
    assert "COPY requirements.txt" in dockerfile
    assert requirements
    assert all("==" in line for line in requirements if line.strip())
    assert "pytest==9.1.1" in requirements
    assert "requirements-dev.txt" not in dockerfile
    assert ".venv" not in dockerfile
    assert "secrets.local.env" not in dockerfile


def test_build_context_excludes_host_environment_and_unrelated_repository() -> None:
    context = _context_root()
    dockerignore = (context / ".dockerignore").read_text(encoding="utf-8")

    assert {path.name for path in context.iterdir()} == {
        ".dockerignore",
        "Dockerfile",
        "requirements.txt",
    }
    assert dockerignore.splitlines() == ["*", "!Dockerfile", "!requirements.txt"]
    assert not (context / ".venv").exists()
    assert not (context / "secrets.local.env").exists()


def test_runtime_default_profile_uses_the_project_image_tag() -> None:
    assert DEFAULT_SANDBOX_IMAGE == "codeteam-sandbox:latest"
    assert SandboxProfile().image == DEFAULT_SANDBOX_IMAGE
