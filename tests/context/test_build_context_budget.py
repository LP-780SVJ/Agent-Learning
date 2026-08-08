from __future__ import annotations

from pathlib import Path

import pytest

from codeteam.application.build_context import ContextApplicationService


FIXTURE_REPO = Path(__file__).resolve().parents[1] / "fixtures" / "test_repo"


@pytest.mark.parametrize("budget", [1024, 256, 128, 64, 32])
def test_context_report_respects_total_budget(budget: int) -> None:
    report = ContextApplicationService().execute(
        query="refresh token 异常从 service 层传播到 API 层的完整链路",
        repository_root=FIXTURE_REPO,
        top_k=5,
        budget_tokens=budget,
    )

    assert report.tokens_used <= report.budget_tokens


def test_context_reports_index_diagnostics_for_bad_python_file(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bad.py").write_text(
        "def broken(:\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "- Run tests: `pytest`\n",
        encoding="utf-8",
    )

    report = ContextApplicationService().execute(
        query="broken",
        repository_root=tmp_path,
        top_k=5,
        budget_tokens=128,
    )

    assert report.warning_count >= 1
    assert "src/bad.py" in report.failed_files
