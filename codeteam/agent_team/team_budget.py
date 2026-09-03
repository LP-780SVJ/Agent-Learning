"""Constrained Lead-weight allocation and aggregate Team budget accounting."""

from __future__ import annotations

import math
from collections.abc import Iterable

from pydantic import BaseModel, Field

from codeteam.agent.runtime_models import CodingAgentRunRequest, CodingAgentRunResult
from codeteam.agent_team.models import WorkerAssignment
from codeteam.agent_team.team_models import (
    NodeBudgetAllocation,
    TeamBudgetAllocation,
    TeamBudgetUsage,
)


class TeamBudgetError(ValueError):
    pass


class TeamBudgetExceededError(TeamBudgetError):
    pass


class TeamBudgetLimits(BaseModel):
    reserve_ratio: float = Field(default=0.20, ge=0.0, lt=1.0)
    min_steps_per_node: int = Field(default=1, gt=0)
    max_steps_per_node: int | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)


class WeightedTeamBudgetPolicy:
    def __init__(self, limits: TeamBudgetLimits | None = None) -> None:
        self.limits = limits or TeamBudgetLimits()

    def allocate(
        self,
        *,
        parent: CodingAgentRunRequest,
        assignments: tuple[WorkerAssignment, ...],
    ) -> TeamBudgetAllocation:
        if not assignments:
            raise TeamBudgetError("at least one assignment is required")
        node_ids = [item.assignment_id for item in assignments]
        if len(set(node_ids)) != len(node_ids):
            raise TeamBudgetError("assignment ids must be unique")

        fallback = any(item.budget_weight is None for item in assignments)
        weights = {
            item.assignment_id: (1 if fallback else item.budget_weight or 1)
            for item in assignments
        }
        reserve_steps = _reserve(parent.max_steps, self.limits.reserve_ratio)
        allocatable_steps = parent.max_steps - reserve_steps
        max_steps = self.limits.max_steps_per_node or allocatable_steps
        step_allocations = _weighted_integer_allocation(
            total=allocatable_steps,
            weights=weights,
            minimum=self.limits.min_steps_per_node,
            maximum=max_steps,
        )

        reserve_tools = _reserve(parent.max_tool_calls, self.limits.reserve_ratio)
        tool_allocations = _weighted_integer_allocation(
            total=parent.max_tool_calls - reserve_tools,
            weights=weights,
            minimum=1,
            maximum=parent.max_tool_calls,
        )
        repair_allocations = _weighted_integer_allocation(
            total=parent.max_repairs,
            weights=weights,
            minimum=0,
            maximum=parent.max_repairs,
        )
        protocol_allocations = _weighted_integer_allocation(
            total=parent.max_protocol_repairs,
            weights=weights,
            minimum=0,
            maximum=parent.max_protocol_repairs,
        )
        return TeamBudgetAllocation(
            global_max_steps=parent.max_steps,
            global_max_tool_calls=parent.max_tool_calls,
            global_max_repairs=parent.max_repairs,
            reserve_steps=reserve_steps,
            reserve_tool_calls=reserve_tools,
            weight_fallback=fallback,
            weight_fallback_reason=(
                "missing_or_invalid_lead_weight" if fallback else None
            ),
            nodes={
                node_id: NodeBudgetAllocation(
                    node_id=node_id,
                    weight=weights[node_id],
                    max_steps=step_allocations[node_id],
                    max_tool_calls=tool_allocations[node_id],
                    max_repairs=repair_allocations[node_id],
                    max_protocol_repairs=protocol_allocations[node_id],
                )
                for node_id in sorted(node_ids)
            },
        )


class TeamBudgetLedger:
    def __init__(
        self,
        allocation: TeamBudgetAllocation,
        *,
        limits: TeamBudgetLimits | None = None,
    ) -> None:
        self.allocation = allocation
        self.limits = limits or TeamBudgetLimits()
        self._usage = TeamBudgetUsage()
        self._node_usage: dict[str, TeamBudgetUsage] = {
            node_id: TeamBudgetUsage() for node_id in allocation.nodes
        }

    @property
    def usage(self) -> TeamBudgetUsage:
        return self._usage.model_copy(deep=True)

    def remaining(self, node_id: str) -> NodeBudgetAllocation:
        allocated = self.allocation.nodes[node_id]
        used = self._node_usage[node_id]
        return allocated.model_copy(
            update={
                "max_steps": max(0, allocated.max_steps - used.steps),
                "max_tool_calls": max(
                    0, allocated.max_tool_calls - used.tool_calls
                ),
                "max_repairs": max(0, allocated.max_repairs - used.repairs),
                "max_protocol_repairs": max(
                    0,
                    allocated.max_protocol_repairs - used.protocol_repairs,
                ),
            }
        )

    def can_dispatch(self, node_id: str) -> bool:
        remaining = self.remaining(node_id)
        return remaining.max_steps > 0 and remaining.max_tool_calls > 0

    def exhaust_unproven_attempt(self, node_id: str) -> TeamBudgetUsage:
        """Conservatively consume the node cap when prior usage is unknowable."""
        remaining = self.remaining(node_id)
        node = _add_usage(
            self._node_usage[node_id],
            TeamBudgetUsage(
                steps=remaining.max_steps,
                tool_calls=remaining.max_tool_calls,
                repairs=remaining.max_repairs,
                protocol_repairs=remaining.max_protocol_repairs,
            ),
        )
        total = _add_usage(
            self._usage,
            TeamBudgetUsage(
                steps=remaining.max_steps,
                tool_calls=remaining.max_tool_calls,
                repairs=remaining.max_repairs,
                protocol_repairs=remaining.max_protocol_repairs,
            ),
        )
        self._node_usage[node_id] = node
        self._usage = total
        return self.usage

    def record(self, node_id: str, result: CodingAgentRunResult) -> TeamBudgetUsage:
        delta = TeamBudgetUsage(
            steps=result.steps_used,
            tool_calls=result.tool_calls_used,
            repairs=result.repair_attempts,
            protocol_repairs=result.protocol_repairs_used,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )
        node = _add_usage(self._node_usage[node_id], delta)
        total = _add_usage(self._usage, delta)
        allocated = self.allocation.nodes[node_id]
        if (
            node.steps > allocated.max_steps
            or node.tool_calls > allocated.max_tool_calls
            or node.repairs > allocated.max_repairs
            or node.protocol_repairs > allocated.max_protocol_repairs
        ):
            raise TeamBudgetExceededError(f"node budget exceeded: {node_id}")
        if (
            total.steps > self.allocation.global_max_steps
            or total.tool_calls > self.allocation.global_max_tool_calls
            or total.repairs > self.allocation.global_max_repairs
        ):
            raise TeamBudgetExceededError("Team hard budget exceeded")
        total_tokens = total.input_tokens + total.output_tokens
        if (
            self.limits.max_total_tokens is not None
            and total_tokens > self.limits.max_total_tokens
        ):
            raise TeamBudgetExceededError("Team token budget exceeded")
        if (
            self.limits.max_cost_usd is not None
            and total.cost_usd > self.limits.max_cost_usd
        ):
            raise TeamBudgetExceededError("Team cost budget exceeded")
        self._node_usage[node_id] = node
        self._usage = total
        return self.usage


def _reserve(total: int, ratio: float) -> int:
    if total <= 1 or ratio <= 0:
        return 0
    return min(total - 1, math.ceil(total * ratio))


def _weighted_integer_allocation(
    *,
    total: int,
    weights: dict[str, int],
    minimum: int,
    maximum: int,
) -> dict[str, int]:
    if total < 0 or minimum < 0 or maximum < minimum:
        raise TeamBudgetError("invalid allocation limits")
    if minimum * len(weights) > total:
        raise TeamBudgetError("minimum node budgets exceed allocatable budget")
    if not weights:
        return {}

    allocations = {node_id: minimum for node_id in weights}
    remaining = total - sum(allocations.values())
    active = {node_id for node_id in weights if allocations[node_id] < maximum}
    while remaining > 0 and active:
        weight_total = sum(weights[node_id] for node_id in active)
        exact = {
            node_id: remaining * weights[node_id] / weight_total
            for node_id in active
        }
        progress = 0
        for node_id in sorted(active):
            grant = min(
                maximum - allocations[node_id],
                math.floor(exact[node_id]),
            )
            allocations[node_id] += grant
            progress += grant
        remaining -= progress
        active = {node_id for node_id in active if allocations[node_id] < maximum}
        if remaining <= 0 or not active:
            break
        order = sorted(
            active,
            key=lambda node_id: (-(exact[node_id] % 1), node_id),
        )
        for node_id in order:
            if remaining <= 0:
                break
            allocations[node_id] += 1
            remaining -= 1
            if allocations[node_id] >= maximum:
                active.discard(node_id)
        if progress == 0 and not order:
            break
    return allocations


def _add_usage(left: TeamBudgetUsage, right: TeamBudgetUsage) -> TeamBudgetUsage:
    fields: Iterable[str] = (
        "steps",
        "tool_calls",
        "repairs",
        "protocol_repairs",
        "input_tokens",
        "output_tokens",
        "cost_usd",
    )
    return TeamBudgetUsage(
        **{
            field: getattr(left, field) + getattr(right, field)
            for field in fields
        }
    )
