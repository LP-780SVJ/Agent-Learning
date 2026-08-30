# 放 MockModelClient，用于测试时模拟模型输出。


from codeteam.llm.base import ModelFinishState, ModelRequest, ModelTurn


class MockModelClient:
    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.index = 0

    def complete(self, *args, **kwargs) -> str:
        if self.index < len(self.outputs):
            output = self.outputs[self.index]
            self.index += 1
            return output
        else:
            raise IndexError("No more mock outputs available.")

    def turn(self, request: ModelRequest) -> ModelTurn:
        return ModelTurn(
            text=self.complete(list(request.messages)),
            finish_state=ModelFinishState.STOP,
            model="mock-model",
        )
