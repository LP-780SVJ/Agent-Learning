from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel


@dataclass
class RegisteredTool:
    name: str
    description: str
    args_schema: type[BaseModel]
    func: Callable[[BaseModel], str]
