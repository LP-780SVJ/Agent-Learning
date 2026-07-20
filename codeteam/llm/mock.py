# 放 MockModelClient，用于测试时模拟模型输出。

from typing import List
from codeteam.schemas.final_output import AgentFinalOutput

class MockModelClient:
    def __init__(self, outputs: List[str]):
        self.outputs = outputs
        self.index = 0

    def complete(self, *args, **kwargs) -> str:
        if self.index < len(self.outputs):
            output = self.outputs[self.index]
            self.index += 1
            return output
        else:
            raise IndexError("No more mock outputs available.")
