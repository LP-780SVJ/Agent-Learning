from __future__ import annotations

import math
import time
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from codeteam.agent_team.models import AgentInfo, AgentStatus


class Clock(Protocol):
    """Short, non-reentrant local clock; no I/O or business callbacks."""

    def monotonic(self) -> float: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()


class InvalidClockError(ValueError):
    pass


class StaleWorkerGenerationError(ValueError):
    pass


class WorkerStateError(ValueError):
    pass


class TeamConsistencyError(RuntimeError):
    pass


class TokenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class WorkerLease(TokenModel):
    runtime_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    generation: int = Field(ge=1, strict=True)


class OwnedTaskToken(TokenModel):
    node_id: str = Field(min_length=1)
    attempt: int = Field(ge=1, strict=True)
    worker_generation: int = Field(ge=1, strict=True)


class WorkerRuntimeRecord(TokenModel):
    worker_id: str = Field(min_length=1)
    status: AgentStatus
    generation: int = Field(default=1, ge=1, strict=True)
    revision: int = Field(default=0, ge=0, strict=True)
    last_heartbeat_monotonic: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    restart_attempts: int = Field(default=0, ge=0, strict=True)
    next_restart_monotonic: float = Field(default=0, ge=0, allow_inf_nan=False)
    restart_id: str | None = None


class WorkerTimeoutCandidate(TokenModel):
    lease: WorkerLease
    worker_revision: int = Field(ge=0, strict=True)
    observed_status: AgentStatus
    observed_at: float = Field(ge=0, allow_inf_nan=False)
    last_heartbeat_monotonic: float = Field(ge=0, allow_inf_nan=False)
    active_task: OwnedTaskToken | None = None


class LifecyclePolicy(TokenModel):
    heartbeat_timeout_seconds: float = Field(default=15, gt=0, allow_inf_nan=False)
    restart_cooldown_seconds: float = Field(default=2, ge=0, allow_inf_nan=False)
    max_restarts: int = Field(default=2, ge=0, strict=True)

    @field_validator(
        "heartbeat_timeout_seconds", "restart_cooldown_seconds", mode="before"
    )
    @classmethod
    def _numeric_time(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            # Pydantic converts ValueError (not TypeError) into ValidationError.
            raise ValueError("time must be a finite number, not bool or string")  # noqa: TRY004
        return value


class RestartTicket(TokenModel):
    lease: WorkerLease
    restart_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1, strict=True)
    restart_attempt: int = Field(ge=1, strict=True)
    info: AgentInfo


class RestartOutcome(str, Enum):
    RESTARTED = "restarted"
    NOT_ELIGIBLE = "not_eligible"
    COOLDOWN = "cooldown"
    EXHAUSTED = "exhausted"
    FACTORY_FAILED = "factory_failed"
    STALE_TICKET = "stale_ticket"


class RestartResult(TokenModel):
    outcome: RestartOutcome
    lease: WorkerLease
    reason_code: str


class RecoveryOutcome(str, Enum):
    STALE_CANDIDATE = "stale_candidate"
    WORKER_ONLY = "worker_only"
    TASK_REQUEUED = "task_requeued"
    TASK_FAILED = "task_failed"
    ALREADY_STOPPED = "already_stopped"


def is_expired(last_seen: float, now: float, timeout: float) -> bool:
    values = (last_seen, now, timeout)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
        raise ValueError("deadline values must be numbers")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("deadline values must be finite")
    if last_seen < 0 or now < last_seen or timeout <= 0:
        raise ValueError("invalid monotonic deadline")
    return now - last_seen >= timeout
