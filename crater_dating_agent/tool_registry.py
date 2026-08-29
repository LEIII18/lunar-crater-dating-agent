from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .agent_models import SessionPhase
from .models import DatingError


Executor = Callable[[dict[str, object], Any], object]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]
    allowed_phases: frozenset[SessionPhase]
    executor: Executor


@dataclass(frozen=True)
class ToolContext:
    session: object
    inputs: object
    services: object


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise DatingError(f"工具重复注册：{definition.name}")
        self._tools[definition.name] = definition

    def schemas_for(self, phase: SessionPhase) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters,
                },
            }
            for item in self._tools.values()
            if phase in item.allowed_phases
        ]

    @staticmethod
    def _validate(arguments: dict[str, object], schema: dict[str, object]) -> None:
        if not isinstance(arguments, dict):
            raise DatingError("工具参数必须是对象")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if any(name not in arguments for name in required):
            raise DatingError("工具参数缺少必填字段")
        if schema.get("additionalProperties") is False and any(
            name not in properties for name in arguments
        ):
            raise DatingError("工具参数包含未声明字段")
        types = {"string": str, "number": (int, float), "boolean": bool}
        for name, value in arguments.items():
            expected = properties.get(name, {}).get("type")
            if expected in types and (
                not isinstance(value, types[expected])
                or expected == "number" and isinstance(value, bool)
            ):
                raise DatingError(f"工具参数 {name} 类型无效")

    def execute(
        self,
        name: str,
        arguments: dict[str, object],
        context: object,
        phase: SessionPhase,
    ) -> object:
        definition = self._tools.get(name)
        if definition is None:
            raise DatingError(f"工具不存在：{name}")
        if phase not in definition.allowed_phases:
            raise DatingError(f"工具 {name} 不允许在当前状态调用")
        self._validate(arguments, definition.parameters)
        return definition.executor(arguments, context)
