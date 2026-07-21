from state import AgentLoopState


class AgentLoopLimits:
    max_steps: int = 10
    max_tool_calls: int = 20

def check_step_limit(state: AgentLoopState, limits: AgentLoopLimits):
    return state.step_count >= limits.max_steps

def check_tool_call_limit(state: AgentLoopState, limits: AgentLoopLimits):
    return state.tool_call_count >= limits.max_tool_calls
