"""codeteam.session.store — Session Durable State 的文件持久化。

职责边界（day4.md §二十三~二十四）：
- JsonSessionStore 只回答「数据怎么读写」；
- 生命周期判断（能不能 resume）属于 SessionService（Step 4/6）。

Crash Consistency 设计：
- session.json 用 temp + flush + fsync + os.replace 原子更新，
  任意时刻崩溃，磁盘上要么是旧完整快照、要么是新完整快照；
- events.jsonl 是 append-only 审计流，容忍末尾半行（loader 丢弃并计数）；
- context.json 是派生状态，用同一原子原语，坏了可重建。

本模块绝不 decide 业务状态——它甚至不知道 PAUSED 是什么含义。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from codeteam.events import AgentEventType
from codeteam.session.errors import (
    SessionAlreadyExistsError,
    SessionCorruptedError,
    SessionNotFoundError,
    SessionSchemaUnsupportedError,
)
from codeteam.session.models import (
    SUPPORTED_SCHEMA_VERSIONS,
    ContextMetadata,
    Session,
    SessionEvent,
)

DEFAULT_SESSIONS_DIR_NAME = ".codeteam/sessions"

_SESSION_ID_PATTERN = re.compile(r"ses_[A-Za-z0-9._-]+")
"""session_id 必须以此格式生成（service 负责 ses_ 前缀），
Store 只做防御性校验：它最终会变成目录名，绝不能含路径成分。"""

_SNAPSHOT_NAME = "session.json"
_EVENTS_NAME = "events.jsonl"
_CONTEXT_NAME = "context.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    """Crash-safe 覆盖写：tmp（同目录）+ flush + fsync + replace。

    - 同目录 tmp：保证与 target 同一文件系统，replace 可用；
    - SIGKILL 打断在 replace 前：旧 target 完整，残留 .tmp 无害
      （loader 只认正式文件名）；
    - 异常路径（含 fault injection）：尽力清理半成品 tmp 再上抛。
    """
    tmp = target.with_name(target.name + ".tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)  # best-effort 清理
        raise


class JsonSessionStore:
    """`.codeteam/sessions/<session_id>/` 三文件的读写器。"""

    def __init__(self, sessions_root: Path | str) -> None:
        # 不在此创建目录：create() 时才建（load 一个空 store 不该有副作用）
        self._root = Path(sessions_root)

    # ── 路径与守卫 ──────────────────────────────────────

    def _session_dir(self, session_id: str) -> Path:
        """session_id → 目录路径，同时做 path traversal 防御。"""
        if not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionNotFoundError(
                f"非法 session_id（含路径成分或格式错误）: {session_id!r}"
            )
        return self._root / session_id

    def _snapshot_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / _SNAPSHOT_NAME

    def _events_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / _EVENTS_NAME

    # ── 快照：create / save / load ─────────────────────

    def create(self, session: Session) -> Session:
        """首次落盘：建目录 + 写 v1 快照（不 bump state_version）。

        幂等性守卫：目录已存在 → SessionAlreadyExistsError，
        绝不覆盖（可能是另一进程的同名 Session）。
        """
        root = self._session_dir(session.manifest.session_id)
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise SessionAlreadyExistsError(
                f"session 目录已存在: {root}"
            ) from error

        _atomic_write_bytes(
            self._snapshot_path(session.manifest.session_id),
            session.model_dump_json(indent=2).encode("utf-8"),
        )
        return session

    def save(self, session: Session) -> Session:
        """更新快照：state_version + 1，返回持久化后的新副本。

        深拷贝再改：绝不原地修改调用方对象（别名分歧防护）。
        """
        persisted = session.model_copy(deep=True)
        persisted.manifest.state_version += 1
        persisted.manifest.updated_at = _utc_now()

        _atomic_write_bytes(
            self._snapshot_path(persisted.manifest.session_id),
            persisted.model_dump_json(indent=2).encode("utf-8"),
        )
        return persisted

    def load(self, session_id: str) -> Session:
        """读取快照。三段闸门，错误类型严格区分：
        不存在 → NotFound；非法 JSON/字段 → Corrupted；
        schema_version 不支持 → SchemaUnsupported（旧 ≠ 坏）。
        """
        path = self._snapshot_path(session_id)
        if not path.is_file():
            raise SessionNotFoundError(f"session 不存在: {session_id}")

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SessionCorruptedError(
                f"session.json 无法解析: {session_id}"
            ) from error

        if not isinstance(raw, dict):
            raise SessionCorruptedError(
                f"session.json 根结构不是对象: {session_id}"
            )

        # schema 闸门必须在 Pydantic 之前：
        # v2 默认忽略未知字段，未来的格式会被默认值「硬猜」出来
        schema_version = raw.get("manifest", {}).get("schema_version")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise SessionSchemaUnsupportedError(
                f"schema_version={schema_version!r} 不受支持 "
                f"(支持: {sorted(SUPPORTED_SCHEMA_VERSIONS)})，"
                f"session: {session_id}"
            )

        try:
            return Session.model_validate(raw)
        except ValidationError as error:
            raise SessionCorruptedError(
                f"session.json 字段非法: {session_id}"
            ) from error

    # ── 事件流：append / load ──────────────────────────

    def append_event(
        self,
        session_id: str,
        *,
        event_type: AgentEventType,
        payload: dict[str, Any] | None = None,
        state_version: int,
    ) -> SessionEvent:
        """追加一条审计事件，Store 负责 seq 分配。

        seq 从文件最后一条合法事件推导（崩溃后重启也不重复），
        不依赖内存状态。state_version 由调用方从当前 Session 传入，
        用于把 event 与快照对齐。
        """
        root = self._session_dir(session_id)
        if not root.is_dir():
            raise SessionNotFoundError(f"session 不存在: {session_id}")

        event = SessionEvent(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            seq=self._last_valid_seq(session_id) + 1,
            state_version=state_version,
            type=event_type,
            timestamp=_utc_now(),
            payload=payload or {},
        )

        # 二进制 append：避免 Windows 换行翻译污染 JSONL
        line = (event.model_dump_json() + "\n").encode("utf-8")
        with open(self._events_path(session_id), "ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def load_events(
        self,
        session_id: str,
    ) -> tuple[list[SessionEvent], int]:
        """读取全部合法事件 + 被丢弃的行数（含末尾半行）。

        崩溃残留在末尾的半条 JSON 不应导致整个审计史打不开——
        丢弃并计数，让调用方可观测到数据损失。
        """
        path = self._events_path(session_id)
        if not path.is_file():
            return [], 0

        events: list[SessionEvent] = []
        dropped = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(SessionEvent.model_validate_json(line))
            except ValidationError:
                dropped += 1
        return events, dropped

    def _last_valid_seq(self, session_id: str) -> int:
        """扫描事件文件取最大合法 seq（MVP O(n)，周度 Benchmark 后再优化）。"""
        events, _ = self.load_events(session_id)
        return events[-1].seq if events else 0

    # ── context.json（派生状态，Day 5 升级为完整 Compaction）──

    def save_context(
        self,
        session_id: str,
        context: ContextMetadata,
    ) -> None:
        root = self._session_dir(session_id)
        if not root.is_dir():
            raise SessionNotFoundError(f"session 不存在: {session_id}")
        _atomic_write_bytes(
            root / _CONTEXT_NAME,
            context.model_dump_json(indent=2).encode("utf-8"),
        )

    def load_context(self, session_id: str) -> ContextMetadata | None:
        path = self._session_dir(session_id) / _CONTEXT_NAME
        if not path.is_file():
            return None
        try:
            return ContextMetadata.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except ValidationError as error:
            raise SessionCorruptedError(
                f"context.json 非法: {session_id}"
            ) from error

    def _last_valid_seq(self, session_id: str) -> int:
        """取最大合法 seq（不是最后一条：中间坏行/乱序时
        events[-1] 可能小于历史最大值，撞号会破坏严格递增）。"""
        events, _ = self.load_events(session_id)
        return max((e.seq for e in events), default=0)


def find_timeline_anomalies(
    events: list[SessionEvent],
) -> list[str]:
    """检测 seq 时间线异常：缺号、重复、乱序（day4.md §五十九）。

    纯函数、不抛异常——返回人类可读的问题清单，空列表 = 时间线完整。
    load_events 不自动调用（读取零成本）；
    resume 诊断与测试显式使用。
    """
    problems: list[str] = []
    seen: set[int] = set()
    previous: int | None = None

    for event in events:
        seq = event.seq
        if seq in seen:
            problems.append(f"duplicate: {seq}")
        else:
            seen.add(seq)
        if previous is not None:
            if seq < previous:
                problems.append(f"out-of-order: {seq} after {previous}")
            elif seq > previous + 1:
                missing = ", ".join(
                    str(n) for n in range(previous + 1, seq)
                )
                problems.append(f"gap: {previous}→{seq} (missing {missing})")
        previous = max(previous, seq) if previous is not None else seq

    return problems