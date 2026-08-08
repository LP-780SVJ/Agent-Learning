"""
RipgrepClient: 封装 ripgrep 为 Python 搜索组件。

核心职责：
- build_argv: 把 SearchQuery 翻译成 rg 命令行参数
- search: 启动 rg 子进程，逐行读取 JSONL，返回 SearchExecution
"""
from __future__ import annotations

import subprocess
import threading


from pathlib import Path
from codeteam.repository.paths import normalize_repo_path

from codeteam.search.models import (
    SearchQuery,
    SearchMatch,
    SearchExecution,
    SearchMode,
    CaseMode,
)
from codeteam.search.json_decoder import (
    parse_ripgrep_line,
    extract_path,
    parse_submatches,
)


class RipgrepClient:
    """封装 ripgrep 命令行工具为 Python 类。

    用法：
        client = RipgrepClient()
        query = SearchQuery(pattern="UserService", mode=SearchMode.LITERAL)
        result = client.search(query, search_path="/path/to/repo")
        for match in result.matches:
            print(f"{match.file_path}:{match.line_number}  {match.line_text}")
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """初始化 RipgrepClient。

        Args:
            timeout_seconds: 搜索超时时间（秒）
        """
        self._timeout_seconds = timeout_seconds

    def build_argv(self, query: SearchQuery, search_path: str = ".") -> list[str]:
        """把 SearchQuery 转换成 ripgrep 的命令行参数列表。

        每个 flag 和它的值都是独立的列表元素——这是 shell=False 安全调用的前提。

        参数映射：
            SearchMode.LITERAL           → -F
            CaseMode.SENSITIVE           → -s
            CaseMode.INSENSITIVE         → -i
            file_types=["py","js"]       → -t py -t js
            globs=["src/**","!tests/**"] → -g src/** -g !tests/**
            context_lines=2              → -C 2
        """
        argv = [
            "rg",
            "--json",         # JSONL 格式输出
            "--no-config",    # 忽略用户的 .ripgreprc
            "--no-heading",   # 不输出文件头（JSON 模式下通常不需要）
        ]

        # 搜索模式：-F（Literal）或不加（Regex，ripgrep 默认）
        if query.mode == SearchMode.LITERAL:
            argv.append("-F")

        # 大小写：-s（区分）或 -i（不区分，ripgrep 默认就是 -i）
        if query.case_mode == CaseMode.SENSITIVE:
            argv.append("-s")

        # 文件类型过滤：每个 -t 独立传入
        for ft in query.file_types:
            argv.extend(["-t", ft])

        # 文件路径 glob：每个 -g 独立传入
        for g in query.globs:
            argv.extend(["-g", g])

        # 上下文行数
        if query.context_lines > 0:
            argv.extend(["-C", str(query.context_lines)])

        # 不传 -m（-m 是每文件上限，不是全局上限）；
        # 全局截断在 search() 中 Python 端实现

        # pattern 和搜索路径
        argv.append(query.pattern)
        argv.append(search_path)

        return argv

    def search(
        self, query: SearchQuery, search_path: str = "."
    ) -> SearchExecution:
        """执行搜索，返回 SearchExecution。

        流程：
        1. build_argv 构造参数
        2. 启动 rg 子进程（shell=False）
        3. 逐行读取 stdout 的 JSONL 输出
        4. 解析 match/context/begin/end/summary
        5. 达到 max_results 时 kill 子进程截断
        6. 汇总为 SearchExecution
        """
        argv = self.build_argv(query, search_path)

        # 启动子进程
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,          # 以文本模式读取（不是 bytes）
            )
        except FileNotFoundError:
            return SearchExecution(
                pattern=query.pattern,
                error="ripgrep (rg) 未安装。请运行: brew install ripgrep",
            )

        # 如果 stderr 管道满了而没人读，子进程会阻塞→死锁。
        # 用一个后台线程持续读取 stderr 到列表中，防止这个问题。
        stderr_lines: list[str] = []

        def _read_stderr() -> None:
            for err_line in proc.stderr:
                stderr_lines.append(err_line)

        stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        stderr_thread.start()

        matches: list[SearchMatch] = []
        pending_context: list[str] = []     # 缓冲：下一个 match 的 context_before
        last_match: SearchMatch | None = None

        total_match_count = 0
        total_elapsed_ms = 0.0
        truncated = False
        time_out = False

        # 逐行读取 ripgrep 的 JSONL 输出
        for line in proc.stdout:

            if proc.poll() is not None:
                # 子进程已退出，可能是被 kill 截断
                break

            msg_type, data = parse_ripgrep_line(line)
            if msg_type is None:
                continue

            if msg_type == "match":
                # ===== 全局截断检查 =====
                if len(matches) >= query.max_results:
                    truncated = True
                    proc.kill()
                    break

                # 提取匹配信息
                file_path = extract_path(data["path"])
                # 将绝对路径转为相对于搜索目录的路径
                try:
                    file_path = normalize_repo_path(Path(search_path), file_path)
                except ValueError:
                    file_path = self._make_relative(file_path, search_path)

                line_text = data["lines"]["text"].rstrip("\n")
                line_no = data["line_number"]
                submatches = parse_submatches(data.get("submatches", []))

                # 创建 SearchMatch，把积攒的 context_before 挂上去
                match = SearchMatch(
                    file_path=file_path,
                    line_number=line_no,
                    line_text=line_text,
                    submatches=submatches,
                    context_before=list(pending_context),  # 复制一份
                )
                pending_context.clear()
                matches.append(match)
                last_match = match

            elif msg_type == "context":
                context_text = data["lines"]["text"].rstrip("\n")
                context_line = data["line_number"]

                # 判断这个 context 属于上一个 match 还是下一个 match
                if (
                    last_match is not None
                    and context_line > last_match.line_number
                    and (context_line - last_match.line_number) <= query.context_lines
                ):
                    # 属于上一个 match 的后面
                    last_match.context_after.append(context_text)
                else:
                    # 属于下一个 match 的前面，先缓冲起来
                    pending_context.append(context_text)
            
            elif msg_type == "begin":
                pass
            elif msg_type == "end":
                last_match = None
                pending_context.clear()
            elif msg_type == "summary":
                total_elapsed_ms = (
                    data.get("elapsed_total", {}).get("nanos", 0)       
                    / 1_000_000
                )
                total_match_count = (
                    data.get("stats", {}).get("matches", 0)
                )

        # ── 步骤 9：等待子进程结束 ──
        try:
            proc.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            time_out = True

        stderr_thread.join(timeout=1.0)
        stderr_text = "".join(stderr_lines).strip()

        # 构建错误信息
        error = ""
        if time_out:
            error = f"搜索超时（{self._timeout_seconds}秒）"
        elif proc.returncode not in (0, 1) and not truncated:
            error = stderr_text or f"ripgrep 异常退出 (code={proc.returncode})"

        return SearchExecution(
            pattern=query.pattern,
            matches=matches,
            duration_ms=total_elapsed_ms,
            total_match_count=total_match_count,
            truncated=truncated,
            error=error,
        )

    @staticmethod
    def _make_relative(file_path: str, search_path: str) -> str:
        """将绝对路径转为相对于 search_path 的路径。

        例如：
            file_path="/repo/auth/service.py", search_path="/repo"
            → "auth/service.py"

        如果 search_path 是相对路径（如 "."），直接返回原路径。
        """
        if search_path in (".", "./"):
            return file_path

        if file_path.startswith(search_path):
            relative = file_path[len(search_path):]
            return relative.lstrip("/")

        return file_path
