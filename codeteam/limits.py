from dataclasses import dataclass

from codeteam.state import AgentLoopState


@dataclass
class AgentLoopLimits:
    max_steps: int = 10
    max_tool_calls: int = 20

def check_step_limit(state: AgentLoopState, limits: AgentLoopLimits) -> bool:
    return state.step_count >= limits.max_steps

def check_tool_call_limit(state: AgentLoopState, limits: AgentLoopLimits) -> bool:
    return state.tool_call_count >= limits.max_tool_calls
