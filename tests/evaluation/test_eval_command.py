from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path

from codeteam.application.repository_index import IndexDiagnostics, RepositoryIndexes
from codeteam.cli import eval_command
from codeteam.evaluation.models import EvalCase
from codeteam.imports.graph import ImportGraph
from codeteam.repository.filename_index import FilenameIndex
from codeteam.repository.models import FileKind, RepositoryFile, RepositorySnapshot
from codeteam.symbols.index import SymbolIndex


def _fake_indexes(root: Path) -> RepositoryIndexes:
    file_path = root / "x.py"
    file_path.write_text("print('x')\n", encoding="utf-8")
    filename_index = FilenameIndex()
    filename_index.add("x.py")
    return RepositoryIndexes(
        snapshot=RepositorySnapshot(
            root=root,
            files=[
                RepositoryFile(
                    path="x.py",
                    language="python",
                    kind=FileKind.SOURCE,
                    size_bytes=file_path.stat().st_size,
                )
            ],
            languages={"python": 1},
            important_configs=[],
            is_git_repo=False,
        ),
        symbol_index=SymbolIndex(),
        filename_index=filename_index,
        import_graph=ImportGraph(),
        diagnostics=IndexDiagnostics(warnings=["x.py: sample warning"]),
    )


def test_eval_manifest_contains_reproducibility_fields(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text('{"id":"c1","query":"x","gold_files":["x.py"]}\n')
    output = tmp_path / "manifest.json"

    eval_command.save_run_manifest(
        output_path=output,
        repo_root=tmp_path,
        dataset_path=dataset,
        method="filename",
        top_k=5,
        candidate_limit=50,
        context_budget=0,
        diagnostics_summary={"warning_count": 1, "warnings": ["x.py: warning"]},
        command_argv=["codeteam", "eval"],
    )

    manifest = json.loads(output.read_text(encoding="utf-8"))
    for field in [
        "repo_path",
        "head_commit",
        "dirty",
        "dirty_files",
        "dirty_summary",
        "dataset_path",
        "dataset_hash",
        "command_argv",
        "python_version",
        "ripgrep_version",
        "parser_version",
        "candidate_limit",
        "context_budget",
        "diagnostics_summary",
    ]:
        assert field in manifest


def test_run_eval_builds_indexes_once_for_multiple_cases(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    calls = {"count": 0}

    def fake_build_indexes(root: Path) -> RepositoryIndexes:
        calls["count"] += 1
        return _fake_indexes(root)

    monkeypatch.setattr(eval_command, "build_repository_indexes", fake_build_indexes)
    monkeypatch.setattr(
        eval_command,
        "load_eval_cases",
        lambda path: [
            EvalCase(id="c1", category="unit", query="x", gold_files=["x.py"]),
            EvalCase(id="c2", category="unit", query="x", gold_files=["x.py"]),
        ],
    )

    args = Namespace(
        dataset=str(dataset),
        repo=str(tmp_path),
        methods="filename",
        output=str(output_dir),
    )

    eval_command.run_eval(args)

    assert calls["count"] == 1
    rows = [
        json.loads(line)
        for line in (output_dir / "filename.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 2
    assert rows[0]["predicted_files"] == ["x.py"]
