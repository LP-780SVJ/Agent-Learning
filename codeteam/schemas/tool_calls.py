# 实现ToolCall、ToolRequest

class ToolCall:
    def __init__(self, tool_id: str, tool_name: str, tool_args: dict[str, any]):
        self.tool_id = tool_id
        self.tool_name = tool_name
        self.tool_args = tool_args

    def __repr__(self):
        return f"ToolCall(tool_id={self.tool_id}, tool_name={self.tool_name}, tool_args={self.tool_args})"

class ToolRequest:
    def __init__(self, tool_call_id: str, tool_call_name: str, tool_call_content: str, tool_call_success: bool, tool_call_error: str|None):
        self.tool_call_id = tool_call_id
        self.tool_call_name = tool_call_name
        self.tool_call_content = tool_call_content
        self.tool_call_success = tool_call_success
        self.tool_call_error = tool_call_error

    def __repr__(self):
        return f"ToolRequest(tool_call_id={self.tool_call_id}, tool_call_name={self.tool_call_name}, tool_call_content={self.tool_call_content}, tool_call_success={self.tool_call_success}, tool_call_error={self.tool_call_error})"