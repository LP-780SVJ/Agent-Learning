from codeteam.schemas.tool_calls import ToolCall, ToolResult
from codeteam.tools.base import RegisteredTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, tool: RegisteredTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> RegisteredTool:
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        return self._tools[name]

    def execute(self, call: ToolCall) -> ToolResult:
        try:
            tool = self.get(call.name)
            args = tool.args_schema.model_validate(call.arguments)
            output = tool.func(args)

            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                content=str(output),
                success=True,
            )
        except Exception as error:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                content="",
                success=False,
                error=str(error),
            )
