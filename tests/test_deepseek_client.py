from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from crater_dating_agent.agent_models import SessionPhase
from crater_dating_agent.deepseek_client import DeepSeekRangeClient, DeepSeekSettings, RangePromptMode
from crater_dating_agent.i18n import Language
from crater_dating_agent.models import DatingError
from crater_dating_agent.tool_registry import ToolDefinition, ToolRegistry


def test_settings_require_key_and_preserve_model_override() -> None:
    with pytest.raises(DatingError, match="DEEPSEEK_API_KEY"):
        DeepSeekSettings.from_env({})

    settings = DeepSeekSettings.from_env({
        "DEEPSEEK_API_KEY": "test-secret-value",
        "DEEPSEEK_MODEL": "deepseek-v4-flash-vision-exp",
    })
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-v4-flash-vision-exp"

    defaults = DeepSeekSettings.from_env({"DEEPSEEK_API_KEY": "test-secret-value"})
    assert defaults.model == "deepseek-v4-flash-vision-exp"


class FakeCompletions:
    def __init__(self, messages):
        self.responses = list(messages)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=self.responses.pop(0))])


def message(content=None, *, tool_calls=None, reasoning_content=None):
    return SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        reasoning_content=reasoning_content,
        model_dump=lambda: {
            "role": "assistant", "content": content,
            "tool_calls": [call.model_dump() for call in tool_calls or []],
            "reasoning_content": reasoning_content,
        },
    )


def tool_call(identifier: str, name: str, arguments: dict[str, object]):
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments))
    return SimpleNamespace(
        id=identifier, type="function", function=function,
        model_dump=lambda: {"id": identifier, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments)
        }},
    )


def vision_session(tmp_path: Path, *, transcript: bool = False):
    overview = tmp_path / "overview"
    overview.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "white").save(overview / "SID9_global_csfd.png")
    state_path = tmp_path / "session_state.json"
    state_path.write_text("{}", encoding="utf-8")
    values = {
        "phase": SessionPhase.ANALYZING,
        "session_dir": tmp_path,
        "state_path": state_path,
        "case_id": "SID9",
    }
    if transcript:
        transcript_path = tmp_path / "llm" / "tool_transcript.jsonl"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text("", encoding="utf-8")
        values["transcript_path"] = transcript_path
    return SimpleNamespace(**values)


def test_tool_turn_replays_reasoning_content_and_persists_redacted_protocol(tmp_path: Path) -> None:
    first = message(
        "", tool_calls=[tool_call("call-1", "get_csfd_summary", {})],
        reasoning_content="protocol-token",
    )
    final = message(json.dumps({
        "candidates": [], "overall_observation": "无可靠区间",
        "needs_human_review": True,
    }))
    completions = FakeCompletions([first, final])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        "get_csfd_summary", "读取结构化数据",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        frozenset({SessionPhase.ANALYZING}), lambda args, context: {"bins": 6},
    ))
    settings = DeepSeekSettings(
        "test-secret-value", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp"
    )
    session = vision_session(tmp_path, transcript=True)
    transcript = session.transcript_path
    proposal = DeepSeekRangeClient(settings, sdk_client=sdk).analyze(session, registry, None)

    assert proposal.candidates == ()
    second_messages = completions.requests[1]["messages"]
    assert second_messages[-2]["reasoning_content"] == "protocol-token"
    assert second_messages[-1] == {
        "role": "tool", "tool_call_id": "call-1", "content": '{"bins":6}'
    }
    user_content = completions.requests[0]["messages"][1]["content"]
    assert user_content[0]["type"] == "text"
    assert "结构化 CSFD" in user_content[0]["text"]
    assert user_content[1]["type"] == "image_url"
    data_url = user_content[1]["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]).startswith(b"\x89PNG\r\n\x1a\n")
    assert user_content[1]["image_url"]["detail"] == "original"
    assert "test-secret-value" not in json.dumps(completions.requests, default=str)
    persisted = transcript.read_text(encoding="utf-8")
    assert '"event":"tool_call"' in persisted
    assert '"event":"tool_result"' in persisted
    raw = (tmp_path / "llm_zero" / "raw_response.json").read_text(encoding="utf-8")
    assert json.loads(json.loads(raw)["content"])["overall_observation"] == "无可靠区间"
    assert "test-secret-value" not in persisted + raw
    assert "data:image" not in persisted + raw


def test_malformed_final_json_gets_exactly_one_repair_request(tmp_path: Path) -> None:
    completions = FakeCompletions([
        message("not json"),
        message(json.dumps({"candidates": [], "overall_observation": "修复", "needs_human_review": True})),
    ])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")

    proposal = DeepSeekRangeClient(settings, sdk_client=sdk).analyze(
        vision_session(tmp_path), ToolRegistry(), None
    )

    assert proposal.overall_observation == "修复"
    assert len(completions.requests) == 2
    system_prompt = completions.requests[0]["messages"][0]["content"]
    repair_prompt = completions.requests[1]["messages"][-1]["content"]
    for field in ("candidates", "range_min_km", "range_max_km", "confidence",
                  "reason", "risks", "overall_observation", "needs_human_review"):
        assert field in system_prompt
        assert field in repair_prompt


def test_markdown_fenced_json_is_accepted_without_repair(tmp_path: Path) -> None:
    content = "```json\n" + json.dumps({
        "candidates": [], "overall_observation": "代码块响应",
        "needs_human_review": True,
    }, ensure_ascii=False) + "\n```"
    completions = FakeCompletions([message(content)])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")
    progress = []

    proposal = DeepSeekRangeClient(
        settings, sdk_client=sdk, progress_callback=progress.append
    ).analyze(vision_session(tmp_path), ToolRegistry(), None)

    assert proposal.overall_observation == "代码块响应"
    assert len(completions.requests) == 1
    assert completions.requests[0]["response_format"] == {"type": "json_object"}
    assert progress == ["正在调用 DeepSeek（第 1 次请求）……", "DeepSeek 已返回第 1 次响应。"]


def test_prompt_prioritizes_one_km_craters_without_relaxing_reliability(
    tmp_path: Path,
) -> None:
    content = json.dumps({
        "candidates": [], "overall_observation": "没有可靠区间",
        "needs_human_review": True,
    }, ensure_ascii=False)
    completions = FakeCompletions([message(content)])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")

    DeepSeekRangeClient(settings, sdk_client=sdk).analyze(
        vision_session(tmp_path), ToolRegistry(), None
    )

    prompt = completions.requests[0]["messages"][0]["content"]
    assert "D ≥ 1 km" in prompt
    assert "图像" in prompt and "结构化" in prompt
    assert "统计可靠性" in prompt
    assert "三个" in prompt


def test_english_client_requests_english_prose_without_changing_json_contract(
    tmp_path: Path,
) -> None:
    content = json.dumps({
        "candidates": [],
        "overall_observation": "No reliable interval",
        "needs_human_review": True,
    })
    completions = FakeCompletions([message(content)])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings(
        "secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp"
    )

    DeepSeekRangeClient(
        settings, sdk_client=sdk, response_language=Language.EN
    ).analyze(vision_session(tmp_path), ToolRegistry(), None)

    first_request = completions.requests[0]
    user_text = first_request["messages"][1]["content"][0]["text"]
    system_prompt = first_request["messages"][0]["content"]
    assert "Write overall_observation, reason, and risks in English" in user_text
    for field in ("range_min_km", "range_max_km", "overall_observation"):
        assert field in system_prompt


def test_nonvision_model_is_rejected_before_sending_image(tmp_path: Path) -> None:
    completions = FakeCompletions([])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash")

    with pytest.raises(DatingError, match="视觉模型"):
        DeepSeekRangeClient(settings, sdk_client=sdk).analyze(
            vision_session(tmp_path), ToolRegistry(), None
        )

    assert completions.requests == []


def test_tampered_session_directory_is_rejected_before_image_upload(
    tmp_path: Path,
) -> None:
    trusted = tmp_path / "trusted"
    untrusted = tmp_path / "untrusted"
    session = vision_session(untrusted)
    session.state_path = trusted / "session_state.json"
    trusted.mkdir()
    session.state_path.write_text("{}", encoding="utf-8")
    completions = FakeCompletions([])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")

    with pytest.raises(DatingError, match="会话目录"):
        DeepSeekRangeClient(settings, sdk_client=sdk).analyze(
            session, ToolRegistry(), None
        )

    assert completions.requests == []


@pytest.mark.parametrize("kind", ["corrupt", "oversized_dimensions"])
def test_invalid_global_png_is_rejected_before_image_upload(
    tmp_path: Path, kind: str
) -> None:
    session = vision_session(tmp_path)
    plot = tmp_path / "overview" / "SID9_global_csfd.png"
    if kind == "corrupt":
        plot.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")
    else:
        Image.new("L", (8193, 1), 0).save(plot)
    completions = FakeCompletions([])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")

    with pytest.raises(DatingError, match="PNG|8192"):
        DeepSeekRangeClient(settings, sdk_client=sdk).analyze(
            session, ToolRegistry(), None
        )

    assert completions.requests == []


def test_unrepairable_response_is_saved_before_error(tmp_path: Path) -> None:
    completions = FakeCompletions([message("first invalid"), message("second invalid")])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")
    session = vision_session(tmp_path, transcript=True)

    with pytest.raises(DatingError, match="候选 JSON"):
        DeepSeekRangeClient(settings, sdk_client=sdk).analyze(session, ToolRegistry(), None)

    first = json.loads((tmp_path / "llm_zero" / "raw_response_attempt_1.json").read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "llm_zero" / "raw_response_attempt_2.json").read_text(encoding="utf-8"))
    assert first["content"] == "first invalid"
    assert second["content"] == "second invalid"


def test_sid55_few_shot_precedes_current_case_with_images_and_full_summary(tmp_path: Path) -> None:
    content = json.dumps({
        "candidates": [], "overall_observation": "没有可靠区间",
        "needs_human_review": True,
    }, ensure_ascii=False)
    completions = FakeCompletions([message(content)])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")

    DeepSeekRangeClient(
        settings, sdk_client=sdk, prompt_mode=RangePromptMode.FEW_SHOT
    ).analyze(
        vision_session(tmp_path), ToolRegistry(), None
    )

    messages = completions.requests[0]["messages"]
    assert "SID55" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    example = messages[1]["content"]
    assert "SID55" in example[0]["text"]
    assert '"total_event_count":204' in example[0]["text"]
    assert [item["type"] for item in example[1:]] == ["image_url", "image_url"]
    assert all(item["image_url"]["url"].startswith("data:image/png;base64,") for item in example[1:])
    assert messages[2]["role"] == "user"
    assert "结构化 CSFD" in messages[2]["content"][0]["text"]


def test_default_zero_shot_uses_original_prompt_without_sid55_example(tmp_path: Path) -> None:
    completions = FakeCompletions([message(json.dumps({
        "candidates": [], "overall_observation": "无可靠区间",
        "needs_human_review": True,
    }, ensure_ascii=False))])
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = DeepSeekSettings("secret", "https://api.deepseek.com", "deepseek-v4-flash-vision-exp")

    DeepSeekRangeClient(settings, sdk_client=sdk).analyze(
        vision_session(tmp_path), ToolRegistry(), None
    )

    messages = completions.requests[0]["messages"]
    assert len(messages) == 2
    assert "SID55" not in messages[0]["content"]
    assert messages[1]["role"] == "user"
