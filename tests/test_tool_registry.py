from __future__ import annotations

import pytest

from crater_dating_agent.agent_models import SessionPhase
from crater_dating_agent.models import DatingError
from crater_dating_agent.tool_registry import ToolDefinition, ToolRegistry


SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "number"}},
    "required": ["value"],
    "additionalProperties": False,
}


def registry() -> ToolRegistry:
    item = ToolDefinition(
        "run_confirmed_dating", "执行最终定年", SCHEMA,
        frozenset({SessionPhase.CONFIRMED}), lambda args, context: {"value": args["value"]},
    )
    result = ToolRegistry()
    result.register(item)
    return result


def test_final_tool_is_hidden_until_confirmed() -> None:
    tools = registry()
    assert tools.schemas_for(SessionPhase.AWAITING_CONFIRMATION) == []
    assert tools.schemas_for(SessionPhase.CONFIRMED)[0]["function"]["name"] == "run_confirmed_dating"


@pytest.mark.parametrize("arguments", [{}, {"value": "1"}, {"value": 1, "extra": 2}])
def test_invalid_arguments_never_reach_executor(arguments: dict[str, object]) -> None:
    tools = registry()
    with pytest.raises(DatingError, match="参数"):
        tools.execute("run_confirmed_dating", arguments, None, SessionPhase.CONFIRMED)


def test_unknown_or_disallowed_tool_fails_closed() -> None:
    tools = registry()
    with pytest.raises(DatingError, match="不存在"):
        tools.execute("invented", {}, None, SessionPhase.CONFIRMED)
    with pytest.raises(DatingError, match="当前状态"):
        tools.execute("run_confirmed_dating", {"value": 1.0}, None, SessionPhase.ANALYZING)
