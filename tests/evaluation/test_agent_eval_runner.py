from __future__ import annotations

import json
from pathlib import Path

from codeteam.evaluation.agent_grader import AgentGrader
from codeteam.evaluation.agent_models import (
    AgentEvalSplit,
    AgentEvalTask,
    AgentTaskType,
    EvalRunConfig,
)
from codeteam.evaluation.agent_runner import AgentEvalRunner, load_agent_eval_tasks
from codeteam.evaluation.patch_actor import (
    NullPatchGenerator,
    PatchActor,
    extract_unified_diff,
)


class StaticPatchGenerator:
    last_input_tokens = 3
    last_output_tokens = 4

    def __init__(self, patch: str) -> None:
        self.patch = patch

    def generate_patch(self, **kwargs) -> str:
        return self.patch


def test_extract_unified_diff_from_markdown_fence() -> None:
    raw = """```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
```"""

    patch = extract_unified_diff(raw)

    assert patch.startswith("diff --git a/app.py b/app.py")
    assert patch.endswith("\n")


def test_agent_eval_runner_applies_patch_and_grades_hidden_oracle(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    hidden = tmp_path / "hidden" / "T01"
    hidden.mkdir(parents=True)
    (hidden / "test_app.py").write_text(
        "from app import VALUE\n\n"
        "def test_value_changed() -> None:\n"
        "    assert VALUE == 2\n",
        encoding="utf-8",
    )
    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        json.dumps(
            {
                "task_id": "T01",
                "split": "dev",
                "type": "bug",
                "difficulty": "L1",
                "repo_fixture": str(fixture),
                "base_commit": "",
                "prompt": "change VALUE to 2",
                "acceptance_commands": ["{python} -m pytest {hidden_root}/T01 -q"],
                "regression_commands": [],
                "oracle_review_status": "test",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""
    runner = AgentEvalRunner(
        actor=PatchActor(patch_generator=StaticPatchGenerator(patch)),
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
    )

    results = runner.run_suite(
        tasks=load_agent_eval_tasks(suite),
        config=EvalRunConfig(run_id="test-run"),
        output_dir=tmp_path / "out",
    )

    assert len(results) == 1
    assert results[0].success is True
    assert results[0].changed_files == ("app.py",)
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["success_count"] == 1


def test_null_patch_actor_cannot_pass_even_if_oracle_would_pass(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    hidden = tmp_path / "hidden" / "T01"
    hidden.mkdir(parents=True)
    (hidden / "test_app.py").write_text(
        "from app import VALUE\n\n"
        "def test_baseline_value() -> None:\n"
        "    assert VALUE == 1\n",
        encoding="utf-8",
    )
    task = AgentEvalTask(
        task_id="T01",
        split=AgentEvalSplit.DEV,
        type=AgentTaskType.BUG,
        difficulty="L1",
        repo_fixture=fixture,
        base_commit="",
        prompt="no-op",
        acceptance_commands=("{python} -m pytest {hidden_root}/T01 -q",),
        oracle_review_status="test",
    )
    runner = AgentEvalRunner(
        actor=PatchActor(patch_generator=NullPatchGenerator()),
        grader=AgentGrader(hidden_root=tmp_path / "hidden"),
        keep_workspaces=True,
    )

    results = runner.run_suite(
        tasks=[task],
        config=EvalRunConfig(run_id="null-run"),
        output_dir=tmp_path / "out",
    )

    assert results[0].acceptance_passed is True
    assert results[0].success is False
    assert results[0].failure_category == "no_patch"
