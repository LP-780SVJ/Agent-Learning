"""codeteam CLI 主入口。"""

from __future__ import annotations

from argparse import Namespace
from enum import Enum
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError

from codeteam.cli.requests import OutputFormat

app = typer.Typer(
    name="codeteam",
    help="CodeTeam — Coding Agent runtime CLI.",
    no_args_is_help=True,
    add_completion=False,
)


class CliOutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"


class AgentEvalActor(str, Enum):
    LLM = "llm"
    NULL = "null"


class AgentEvalMode(str, Enum):
    BASELINE = "baseline"
    ABLATIONS = "ablations"
    ALL = "all"


class AgentEvalSplitOption(str, Enum):
    DEV = "dev"
    HELDOUT = "heldout"


class AgentCompactionMode(str, Enum):
    STRUCTURED = "structured"
    NONE = "none"
    NAIVE = "naive"


@app.command("inspect-repo")
def inspect_repo(
    path: Annotated[
        Path,
        typer.Argument(help="仓库路径（默认当前目录）"),
    ] = Path("."),
    output_format: Annotated[
        CliOutputFormat,
        typer.Option("--format", help="输出格式：text 或 json"),
    ] = CliOutputFormat.TEXT,
) -> None:
    """检查仓库索引健康状况。"""
    from codeteam.cli.inspect_command import run_inspect

    args = Namespace(path=str(path), format=output_format.value)
    run_inspect(args)


@app.command("context")
def context(
    query: Annotated[
        str,
        typer.Argument(help="任务描述，如 '修复 refresh token 过期返回 500'"),
    ],
    path: Annotated[
        Path,
        typer.Option("--path", help="仓库路径（默认当前目录）"),
    ] = Path("."),
    top_k: Annotated[
        int,
        typer.Option("--top-k", help="返回 Top K 文件（默认 5）"),
    ] = 5,
    budget: Annotated[
        int,
        typer.Option("--budget", help="Repo Map Token 预算（默认 1024）"),
    ] = 1024,
    output_format: Annotated[
        CliOutputFormat,
        typer.Option("--format", help="输出格式：text 或 json"),
    ] = CliOutputFormat.TEXT,
) -> None:
    """根据任务查询构建上下文。"""
    from codeteam.cli.context_command import run_context

    args = Namespace(
        query=query,
        path=str(path),
        top_k=top_k,
        budget=budget,
        format=output_format.value,
    )
    run_context(args)


@app.command("eval")
def eval_command(
    dataset: Annotated[
        Path,
        typer.Option("--dataset", help="评测数据 JSONL 文件"),
    ],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="目标仓库路径（默认当前目录）"),
    ] = Path("."),
    methods: Annotated[
        str,
        typer.Option("--methods", help="方法列表，逗号分隔"),
    ] = "hybrid",
    output: Annotated[
        Path,
        typer.Option("--output", help="结果输出目录"),
    ] = Path("evals/results/"),
) -> None:
    """运行评测实验。"""
    from codeteam.cli.eval_command import run_eval

    args = Namespace(
        dataset=str(dataset),
        repo=str(repo),
        methods=methods,
        output=str(output),
    )
    run_eval(args)


@app.command("agent-eval")
def agent_eval(
    suite: Annotated[
        Path,
        typer.Option("--suite", help="Agent task suite JSONL 文件"),
    ] = Path("evals/week4/agent_task_suite_v1.jsonl"),
    output: Annotated[
        Path,
        typer.Option("--output", help="结果输出目录"),
    ] = Path("evals/week4/agent_runs/latest"),
    actor: Annotated[
        AgentEvalActor,
        typer.Option("--actor", help="runtime model: llm 或 null"),
    ] = AgentEvalActor.LLM,
    mode: Annotated[
        AgentEvalMode,
        typer.Option("--mode", help="baseline, ablations, all"),
    ] = AgentEvalMode.BASELINE,
    split: Annotated[
        AgentEvalSplitOption | None,
        typer.Option("--split", help="只运行 dev 或 heldout"),
    ] = None,
    task_id: Annotated[
        list[str] | None,
        typer.Option("--task-id", help="只运行指定 task，可重复"),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="最多运行多少个 task"),
    ] = None,
    context_budget: Annotated[
        int,
        typer.Option("--context-budget", help="Runtime context token budget"),
    ] = 4096,
    keep_workspaces: Annotated[
        bool,
        typer.Option("--keep-workspaces", help="保留每个 task 的临时 workspace"),
    ] = False,
) -> None:
    """运行 Week4 task-level coding benchmark。"""
    from codeteam.cli.agent_eval_command import run_agent_eval

    args = Namespace(
        suite=str(suite),
        output=str(output),
        actor=actor.value,
        mode=mode.value,
        split=split.value if split is not None else None,
        task_id=task_id,
        limit=limit,
        context_budget=context_budget,
        keep_workspaces=keep_workspaces,
    )
    run_agent_eval(args)


@app.command("run")
def run(
    task: Annotated[str, typer.Argument(help="任务描述")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="仓库路径（默认当前目录）"),
    ] = Path("."),
    provider_id: Annotated[
        str | None,
        typer.Option("--provider", help="LLM provider id"),
    ] = None,
    model_id: Annotated[
        str | None,
        typer.Option("--model", help="LLM model id"),
    ] = None,
    context_budget: Annotated[
        int,
        typer.Option("--context-budget", min=1),
    ] = 4096,
    max_steps: Annotated[int, typer.Option("--max-steps", min=1)] = 20,
    max_tool_calls: Annotated[
        int,
        typer.Option("--max-tool-calls", min=1),
    ] = 40,
    max_repairs: Annotated[int, typer.Option("--max-repairs", min=0)] = 3,
    max_protocol_repairs: Annotated[
        int,
        typer.Option("--max-protocol-repairs", min=0, max=2),
    ] = 2,
    compaction_mode: Annotated[
        AgentCompactionMode,
        typer.Option("--compaction", help="structured, none, or naive"),
    ] = AgentCompactionMode.STRUCTURED,
    output_format: Annotated[
        CliOutputFormat,
        typer.Option("--format", help="输出格式：text 或 json"),
    ] = CliOutputFormat.TEXT,
) -> None:
    """启动一个新的 Agent 任务。"""
    from codeteam.cli.requests import RunRequest
    from codeteam.cli.run_command import run_agent_task

    try:
        request = RunRequest(
            task=task,
            repo=repo,
            provider_id=provider_id,
            model_id=model_id,
            context_budget=context_budget,
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            max_repairs=max_repairs,
            max_protocol_repairs=max_protocol_repairs,
            compaction_mode=compaction_mode.value,
            output_format=cast(OutputFormat, output_format.value),
        )
    except ValidationError as error:
        raise typer.BadParameter(str(error)) from error
    run_agent_task(request)


@app.command("resume")
def resume(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="仓库路径（默认当前目录）"),
    ] = Path("."),
    provider_id: Annotated[
        str | None,
        typer.Option("--provider", help="恢复时覆盖 provider"),
    ] = None,
    model_id: Annotated[
        str | None,
        typer.Option("--model", help="恢复时覆盖 model"),
    ] = None,
) -> None:
    """恢复已有 Session。"""
    from codeteam.cli.requests import ResumeRequest
    from codeteam.cli.run_command import resume_agent_session

    try:
        request = ResumeRequest(
            session_id=session_id,
            repo=repo,
            provider_id=provider_id,
            model_id=model_id,
        )
    except ValidationError as error:
        raise typer.BadParameter(str(error)) from error
    resume_agent_session(request)


@app.command("diff")
def diff(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="仓库路径（默认当前目录）"),
    ] = Path("."),
    base_ref: Annotated[
        str,
        typer.Option("--base", help="Diff 的基准 ref"),
    ] = "HEAD",
    output_format: Annotated[
        CliOutputFormat,
        typer.Option("--format", help="输出格式：text 或 json"),
    ] = CliOutputFormat.TEXT,
) -> None:
    """查看已有 Session 对应工作区的 diff。"""
    from codeteam.cli.requests import DiffRequest
    from codeteam.cli.run_command import diff_agent_session

    request = DiffRequest(
        session_id=session_id,
        repo=repo,
        base_ref=base_ref,
        output_format=cast(OutputFormat, output_format.value),
    )
    diff_agent_session(request)


@app.command("rollback")
def rollback(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    checkpoint_id: Annotated[str, typer.Argument(help="Checkpoint ID")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="仓库路径（默认当前目录）"),
    ] = Path("."),
    output_format: Annotated[
        CliOutputFormat,
        typer.Option("--format", help="输出格式：text 或 json"),
    ] = CliOutputFormat.TEXT,
) -> None:
    """回滚指定 Session 的 checkpoint。"""
    from codeteam.cli.requests import RollbackRequest
    from codeteam.cli.run_command import rollback_agent_session

    request = RollbackRequest(
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        repo=repo,
        output_format=cast(OutputFormat, output_format.value),
    )
    rollback_agent_session(request)


def main(argv: list[str] | None = None) -> None:
    app(args=argv)


if __name__ == "__main__":
    main()
