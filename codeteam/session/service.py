"""codeteam.session.service — Session 生命周期编排。

与 JsonSessionStore 的职责分界（day4.md §二十三~二十四）：
- Store 回答「数据怎么读写」；
- 本文件回答「生命周期何时变化、按什么顺序落盘」。

pause() 的顺序闸门（§二十九，不可颠倒）：
    ① 停止 in-flight 操作（stop_operation 回调）
    ② 刷新 worktree 引用（refresher 回调，Step 5 提供真实 Git 实现）
    ③ 内存状态 → PAUSED
    ④ store.save（state_version + 1，原子写）
    ⑤ append session.paused 事件

顺序错误反例（§二十八）：先 save(PAUSED) 再停后台命令——
磁盘声称已暂停而子进程仍在修改 Worktree，Resume 时对账必然失败。

resume() 属于 Step 6；本文件不实现（load ≠ resume）。
"""
from __future__ import annotations

import subprocess
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar
from dataclasses import dataclass

from codeteam.events import AgentEventType
from codeteam.session.errors import SessionTerminalError
from codeteam.session.models import (
    RepositoryRef,
    Session,
    SessionStatus,
    TaskSpec,
    WorktreeRef,
)
from codeteam.session.store import JsonSessionStore
from codeteam.session.errors import RepositoryMismatchError, SessionTerminalError
from codeteam.session.models import (
    OperationStatus,
    ReconciliationVerdict,          # 需先在 models.py 定义（Step 5 教学有）
    RepositoryRef,
    Session,
    SessionManifest,                # ← create_session 需要
    SessionStatus,
    TaskSpec,
    WorktreeRef,
)

PAUSABLE_STATUSES: frozenset[SessionStatus] = frozenset({
    SessionStatus.CREATED,
    SessionStatus.RUNNING,
    SessionStatus.RECOVERY_REQUIRED,
})
"""允许进入 PAUSED 的来源状态。terminal（COMPLETED/FAILED）拒绝；
PAUSED 本身走幂等分支（见 pause()）。"""

OperationStopper = Callable[[Session], None]
"""停止 in-flight 副作用的回调（如终止 VerificationService 子进程）。
入参是暂停前的 session 快照（含 active_operation 供决策）。"""

SessionRefresher = Callable[[Session], Session]
"""刷新外部引用（worktree HEAD/dirty 等）的回调。
返回更新后的 Session；Step 5 的 GitRefresher 是默认实现。"""

_GIT_TIMEOUT_SECONDS = 10.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionService:
    """Session 生命周期服务：create / pause（resume 见 Step 6）。"""

    def __init__(
        self,
        store: JsonSessionStore,
        *,
        stop_operation: OperationStopper | None = None,
        refresher: SessionRefresher | None = None,
    ) -> None:
        self._store = store
        self._stop_operation = stop_operation
        self._refresher = refresher

    # ── create ─────────────────────────────────────────

    def create_session(
        self,
        *,
        task: TaskSpec,
        repo: RepositoryRef,
        provider_id: str,
        model_id: str,
        worktree: WorktreeRef | None = None,
    ) -> Session:
        """创建并落盘新 Session（v1）+ session.created 事件。

        session_id 由本方法生成（ses_ + uuid 片段），
        保证并发创建不冲突（§二十六）。
        last_event_seq 在内存中推进到 1，随下一次 save 落盘——
        内存值领先磁盘值是本模块的既定语义（save 对齐）。
        """
        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        now = _utc_now()

        session = Session(
            manifest=SessionManifest(
                session_id=session_id,
                repo_id=repo.repo_id,
                created_at=now,
                updated_at=now,
            ),
            task=task,
            provider_id=provider_id,
            model_id=model_id,
            repo=repo,
            worktree=worktree,
        )
        self._store.create(session)

        event = self._store.append_event(
            session_id,
            event_type=AgentEventType.SESSION_CREATED,
            state_version=1,
            payload={
                "task_id": task.task_id,
                "repo_id": repo.repo_id,
                "provider_id": provider_id,
                "model_id": model_id,
            },
        )
        return session.model_copy(
            update={
                "manifest": session.manifest.model_copy(
                    update={"last_event_seq": event.seq}
                ),
                "status": SessionStatus.CREATED,
            }
        )

    # ── pause ──────────────────────────────────────────

    def pause(
        self,
        session: Session,
        *,
        reason: str,
    ) -> Session:
        """暂停会话并持久化。顺序闸门见模块 docstring。

        - PAUSED → PAUSED：幂等，返回传入对象（不重复 save/事件）
        - COMPLETED / FAILED：SessionTerminalError（磁盘不动）
        - 持久化后的最新状态以返回值为准（闭包旧引用会落后）。
        """
        if session.status is SessionStatus.PAUSED:
            return session  # 幂等：重复 Ctrl+C / 信号重入
        if session.status not in PAUSABLE_STATUSES:
            raise SessionTerminalError(
                f"终态 Session 不能 pause: {session.status.value}"
            )

        # ① 先停 in-flight 操作（顺序闸门之首）
        if self._stop_operation is not None:
            self._stop_operation(session)

        # ② 刷新外部引用（worktree HEAD / dirty 等）
        current = session
        if self._refresher is not None:
            current = self._refresher(session)

        # ③ 内存状态 → PAUSED
        paused = current.model_copy(
            update={"status": SessionStatus.PAUSED}
        )

        # ④ 原子落盘（state_version + 1）
        persisted = self._store.save(paused)

        # ⑤ 审计事件（state_version 与快照对齐）
        event = self._store.append_event(
            persisted.manifest.session_id,
            event_type=AgentEventType.SESSION_PAUSED,
            state_version=persisted.manifest.state_version,
            payload={"reason": reason,
                     "task_status": persisted.task_status.value},
        )
        return persisted.model_copy(
            update={
                "manifest": persisted.manifest.model_copy(
                    update={"last_event_seq": event.seq}
                ),
            }
        )

def _run_git(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    """项目惯例封装：argv / shell=False / timeout / check=False。
    对账中「命令失败」是证据不是异常，返回 CompletedProcess 由调用方读。"""
    return subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True,
        shell=False, timeout=_GIT_TIMEOUT_SECONDS, check=False,
    )


def probe_git_common_dir(cwd: Path) -> str:
    result = _run_git(["rev-parse", "--git-common-dir"], cwd=cwd)
    if result.returncode != 0:
        raise RepositoryMismatchError(f"不是 Git 仓库: {cwd}")
    return str((cwd / result.stdout.decode().strip()).resolve())


def probe_head(worktree: Path) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], cwd=worktree)
    return result.stdout.decode().strip() if result.returncode == 0 else None


def probe_dirty(worktree: Path) -> bool:
    result = _run_git(["status", "--porcelain"], cwd=worktree)
    return bool(result.stdout.decode().strip())


def probe_commit_exists(repo: Path, sha: str) -> bool:
    return _run_git(
        ["cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo,
    ).returncode == 0


@dataclass(frozen=True)
class ReconciliationReport:
    """对账结论。ephemeral 诊断数据（dataclass，非 Durable 契约）：
    verdict 聚合规则 = 最严重 issue 决定；session 字段可能已打补丁
    （如 stale RUNNING → RECOVERY_REQUIRED），Step 6 负责持久化它。"""
    verdict: ReconciliationVerdict
    issues: tuple[str, ...]
    session: Session


class GitWorktreeRefresher:
    """Step 4 refresher 插槽的真实实现：刷新 worktree 引用基线。

    供 pause() 前调用（把「现在」定格成对账基线）；
    probe 失败（目录没了）不抛——保留旧值，让 reconcile 报 drift。
    """

    def __call__(self, session: Session) -> Session:
        if session.worktree is None:
            return session
        path = Path(session.worktree.path)
        head = probe_head(path) if path.is_dir() else None
        dirty = probe_dirty(path) if path.is_dir() else session.worktree.last_known_dirty
        if head is None:
            return session
        return session.model_copy(update={"worktree": session.worktree.model_copy(
            update={"last_known_head_sha": head, "last_known_dirty": dirty},
        )})


class SessionReconciler:
    """State Reconciliation：持久化期望 vs 当前现实（day4.md §四十九）。

    只报告、不抛业务异常（load 层异常已由 Store 闸门处理）；
    resume()（Step 6）根据 verdict 决定抛哪个 error 或继续。
    """

    _SEVERITY: ClassVar[dict[ReconciliationVerdict, int]] = {
        ReconciliationVerdict.RESUMABLE: 0,
        ReconciliationVerdict.RECOVERY_REQUIRED: 1,
        ReconciliationVerdict.INVALID: 2,
    }

    def __init__(
        self,
        *,
        is_provider_available: Callable[[str, str], bool] | None = None,
        list_checkpoint_ids: Callable[[], set[str]] | None = None,
    ) -> None:
        self._is_provider_available = is_provider_available
        self._list_checkpoint_ids = list_checkpoint_ids

    def reconcile(
        self,
        session: Session,
        *,
        current_repo: Path,
    ) -> ReconciliationReport:
        issues: list[tuple[str, ReconciliationVerdict]] = []

        # ① repo identity：git_common_dir（不是 remote URL，§三十六）
        if probe_git_common_dir(current_repo) != session.repo.git_common_dir:
            issues.append((
                f"repo_mismatch: {current_repo} != {session.repo.git_common_dir}",
                ReconciliationVerdict.INVALID,
            ))
            # repo 都不对，后续检查没有意义
            return self._report(session, issues)

        # ② base SHA 存在性
        if not probe_commit_exists(current_repo, session.repo.base_sha):
            issues.append((
                f"base_missing: {session.repo.base_sha}",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            ))

        # ③ task worktree（None = run 中途暂停，未建 worktree，跳过）
        session = self._reconcile_worktree(session, issues)

        # ④ checkpoint chain
        session = self._reconcile_checkpoints(session, issues)

        # ⑤ provider 可用性（注入方缺省 = 跳过，Day 5 补体系）
        if self._is_provider_available is not None and not (
            self._is_provider_available(session.provider_id, session.model_id)
        ):
            issues.append((
                f"provider_unavailable: {session.provider_id}/{session.model_id}",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            ))

        # ⑥ stale RUNNING：磁盘 RUNNING + 无锁持有者（锁在 Step 6，
        #    此处语义 = reconcile 被调用即无活跃 writer）
        session = self._reconcile_stale_running(session, issues)

        # ⑦ in-flight 操作
        if (
            session.active_operation is not None
            and session.active_operation.status is OperationStatus.STARTED
        ):
            issues.append((
                f"inflight_operation: {session.active_operation.kind}",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            ))

        return self._report(session, issues)

    def _reconcile_worktree(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> Session:
        ref = session.worktree
        if ref is None:
            return session
        path = Path(ref.path)
        if not path.is_dir():
            issues.append((
                f"worktree_missing: {ref.path}",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            ))
            return session

        head = probe_head(path)
        if head is not None and head != ref.last_known_head_sha:
            issues.append((
                f"worktree_head_drift: {ref.last_known_head_sha[:8]}→{head[:8]}",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            ))
        dirty = probe_dirty(path)
        if dirty != ref.last_known_dirty:
            issues.append((
                f"worktree_dirty_drift: {ref.last_known_dirty}→{dirty}",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            ))
        return session

    def _reconcile_checkpoints(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> Session:
        if self._list_checkpoint_ids is None:
            return session
        available = self._list_checkpoint_ids()
        for cp_id in (*session.checkpoint_ids, session.current_checkpoint_id):
            if cp_id is not None and cp_id not in available:
                issues.append((
                    f"checkpoint_missing: {cp_id}",
                    ReconciliationVerdict.RECOVERY_REQUIRED,
                ))
        return session

    def _reconcile_stale_running(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> Session:
        if session.status is SessionStatus.RUNNING:
            issues.append((
                "stale_running: 磁盘 RUNNING 且无活跃 writer",
                ReconciliationVerdict.RECOVERY_REQUIRED,
            ))
            # 打补丁：绝不带着 RUNNING 直接续跑（F2）
            return session.model_copy(
                update={"status": SessionStatus.RECOVERY_REQUIRED}
            )
        return session

    def _report(
        self,
        session: Session,
        issues: list[tuple[str, ReconciliationVerdict]],
    ) -> ReconciliationReport:
        verdict = max(
            (severity for _, severity in issues),
            default=ReconciliationVerdict.RESUMABLE,
        )
        return ReconciliationReport(
            verdict=verdict,
            issues=tuple(text for text, _ in issues),
            session=session,
        )