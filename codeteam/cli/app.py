"""codeteam CLI 主入口。"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="codeteam",
        description="CodeTeam — 代码上下文引擎",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ── inspect-repo ──
    inspect_parser = subparsers.add_parser(
        "inspect-repo",
        help="检查仓库索引健康状况",
    )
    inspect_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="仓库路径（默认当前目录）",
    )
    inspect_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="输出格式（默认 text）",
    )

    # ── context ──
    context_parser = subparsers.add_parser(
        "context",
        help="根据任务查询构建上下文",
    )
    context_parser.add_argument(
        "query",
        help="任务描述，如 '修复 refresh token 过期返回 500'",
    )
    context_parser.add_argument(
        "--path",
        default=".",
        help="仓库路径（默认当前目录）",
    )
    context_parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="返回 Top K 文件（默认 5）",
    )
    context_parser.add_argument(
        "--budget",
        type=int,
        default=1024,
        help="Repo Map Token 预算（默认 1024）",
    )
    context_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="输出格式（默认 text）",
    )

    # ── eval ──
    eval_parser = subparsers.add_parser(
        "eval", 
        help="运行评测实验"
    )
    eval_parser.add_argument(
        "--dataset",
        required=True,
        help="评测数据 JSONL 文件"
    )
    eval_parser.add_argument(
        "--repo",
        default=".",
        help="目标仓库路径（默认当前目录）",
    )
    eval_parser.add_argument(
        "--methods",
        default="hybrid",
        help="方法列表，逗号分隔"
    )
    eval_parser.add_argument(
        "--output",
        default="evals/results/",
        help="结果输出目录"
    )

    args = parser.parse_args(argv)

    if args.command == "inspect-repo":
        from codeteam.cli.inspect_command import run_inspect
        run_inspect(args)
    elif args.command == "context":
        from codeteam.cli.context_command import run_context
        run_context(args)
    elif args.command == "eval":
        from codeteam.cli.eval_command import run_eval
        run_eval(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
