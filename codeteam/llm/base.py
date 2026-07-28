from dataclasses import dataclass


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model: str = "mock-model"
    input_tokens: int = 0
    output_tokens: int = 0
