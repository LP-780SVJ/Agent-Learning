from codeteam.agent.completion import CompletionGate
from codeteam.agent.runtime_models import VerificationEvidence
from codeteam.agent.runtime_tools import RuntimeEvidence

COMMAND = ("python", "-m", "pytest", "tests")


def _ready_evidence() -> RuntimeEvidence:
    return RuntimeEvidence(
        workspace_version=2,
        task_verification_commands=(COMMAND,),
        verification=[
            VerificationEvidence(
                argv=COMMAND,
                passed=True,
                completion_required=True,
                workspace_version=2,
            )
        ],
        git_diff_checked=True,
        git_diff_checked_version=2,
    )


def test_completion_gate_requires_current_workspace_version() -> None:
    evidence = _ready_evidence()
    evidence.workspace_version = 3

    decision = CompletionGate.evaluate(
        evidence,
        changed_files=("app.py",),
        diff="diff --git a/app.py b/app.py\n",
    )

    assert not decision.ready
    assert "current_version_verification" in decision.missing_requirements
    assert "current_version_diff_review" in decision.missing_requirements


def test_completion_gate_accepts_complete_current_version_evidence() -> None:
    decision = CompletionGate.evaluate(
        _ready_evidence(),
        changed_files=("app.py",),
        diff="diff --git a/app.py b/app.py\n",
    )

    assert decision.ready
    assert decision.missing_requirements == ()


def test_completion_gate_blocks_workspace_hygiene_failure() -> None:
    evidence = _ready_evidence()
    evidence.workspace_hygiene_clean = False

    decision = CompletionGate.evaluate(
        evidence,
        changed_files=("app.py",),
        diff="diff --git a/app.py b/app.py\n",
    )

    assert not decision.ready
    assert "workspace_hygiene_clean" in decision.missing_requirements


def test_completion_gate_requires_task_and_all_broad_commands() -> None:
    broad = ("python", "-m", "pytest", "tests/regression")
    evidence = _ready_evidence()
    evidence.regression_verification_commands = (broad,)

    decision = CompletionGate.evaluate(
        evidence,
        changed_files=("app.py",),
        diff="diff --git a/app.py b/app.py\n",
    )

    assert not decision.ready
    assert "current_version_verification" in decision.missing_requirements
