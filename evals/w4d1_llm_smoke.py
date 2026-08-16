"""Week 4 Day 1 真实 LLM 冒烟验证。

验证完整管线在真实模型上的表现：
Natural Language → TaskSpec → Repository Inspection → LLMPlanner → READY

依赖：
- secrets.local.env（gitignored，含 CODETEAM_LLM_* 三个配置）
- 项目已有模块：ContextApplicationService / RepositoryInspector /
  LLMPlanner / SingleAgentOrchestrator / OpenAICompatibleClient

运行：
    .venv/bin/python evals/w4d1_llm_smoke.py

安全：
- API key 只存在于 secrets.local.env（永不提交）
- 环境变量 CODETEAM_LLM_* 可覆盖文件配置（供 CI 注入）
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from codeteam.schemas.messages import Message
from codeteam.llm.openai_compatible import OpenAICompatibleClient
from codeteam.application.build_context import ContextApplicationService
from codeteam.agent.inspection import RepositoryInspector
from codeteam.agent.orchestrator import SingleAgentOrchestrator
from codeteam.planning.planner import LLMPlanner

REPO_ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = REPO_ROOT / "secrets.local.env"
FIXTURE_REPO = REPO_ROOT / "tests" / "fixtures" / "test_repo"

QUERY = "AuthService refresh 的完整链路"
TASK_ID = "smoke-001"


# ── 配置加载 ──────────────────────────────────────────────


def _load_local_secrets(path: Path) -> dict[str, str]:
    """从 gitignored 的本地文件读取 KEY=VALUE 配置。

    环境变量优先级更高（适合 CI 注入）。
    """
    if not path.exists():
        return {}
    config: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        config[key.strip()] = value.strip()
    return config


def _resolve_config() -> dict[str, str]:
    """文件优先读取，环境变量覆盖，缺项给出明确提示。"""
    secrets = _load_local_secrets(SECRETS_PATH)
    secrets.update(
        {
            k: v
            for k, v in os.environ.items()
            if k.startswith("CODETEAM_LLM_")
        }
    )

    missing = [
        k
        for k in (
            "CODETEAM_LLM_BASE_URL",
            "CODETEAM_LLM_API_KEY",
            "CODETEAM_LLM_MODEL",
        )
        if not secrets.get(k)
    ]
    if missing:
        raise SystemExit(
            f"缺少配置: {missing}。\n"
            f"请在 {SECRETS_PATH} 中填写，或通过环境变量提供。"
        )

    return secrets


# ── LLM 适配器 ────────────────────────────────────────────


def _make_complete(config: dict[str, str]):
    """构造 LLMPlanner 需要的 complete(prompt) -> str。

    复用 OpenAICompatibleClient 获得 Week 1 的重试能力：
    429/5xx 指数退避重试，401/403 立即失败。
    """

    def _chat_completion_request(messages: list[Message]) -> str:
        """真正的 HTTP 请求 —— OpenAI 兼容 /chat/completions。"""
        body = json.dumps(
            {
                "model": config["CODETEAM_LLM_MODEL"],
                "messages": [
                    {"role": m.role, "content": m.content}
                    for m in messages
                ],
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{config['CODETEAM_LLM_BASE_URL'].rstrip('/')}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {config['CODETEAM_LLM_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    client = OpenAICompatibleClient(
        model=config["CODETEAM_LLM_MODEL"],
        request_func=_chat_completion_request,
    )

    def complete(prompt: str) -> str:
        return client.complete([Message(role="user", content=prompt)])

    return complete


# ── 主流程 ────────────────────────────────────────────────


def main() -> None:
    config = _resolve_config()
    print(f"模型: {config['CODETEAM_LLM_MODEL']}")
    print(f"仓库: {FIXTURE_REPO}")
    print(f"查询: {QUERY}")
    print()

    orchestrator = SingleAgentOrchestrator(
        inspector=RepositoryInspector(ContextApplicationService()),
        planner=LLMPlanner(complete=_make_complete(config)),
        repository_root=FIXTURE_REPO,
    )

    result = orchestrator.run(request=QUERY, task_id=TASK_ID)

    # ── 检查 1：状态走到 READY ──
    print(f"状态: {result.status.value}")
    if result.status.value != "ready":
        print(f"错误: {result.error}")
        raise SystemExit(1)
    print("✓ 状态 READY")

    # ── 检查 2：Plan 生成且步骤非空 ──
    assert result.plan is not None and len(result.plan.steps) >= 1
    print(f"✓ Plan 生成: {len(result.plan.steps)} 个步骤")
    print()
    for step in result.plan.steps:
        print(f"  {step.step_id}: {step.title}")
        print(f"      description: {step.description[:60]}")
        print(f"      files: {list(step.relevant_files)}")
        print(f"      verification: {step.verification}")

    # ── 检查 3：Grounding —— 引用文件必须真实存在 ──
    print()
    missing = [
        f
        for step in result.plan.steps
        for f in step.relevant_files
        if not (FIXTURE_REPO / f).exists()
    ]
    if missing:
        print(f"⚠ 幻觉文件引用（记入 Failure Cases）: {missing}")
    else:
        print("✓ 所有引用文件真实存在")

    # ── 事件序列摘要 ──
    print()
    print("事件序列:")
    for event in result.events:
        print(f"  {event.event_type.value}")

    print()
    print("冒烟通过 ✓")


if __name__ == "__main__":
    main()
