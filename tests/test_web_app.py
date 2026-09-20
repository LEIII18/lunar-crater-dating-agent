from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

import crater_dating_agent.web_app as web_app
from crater_dating_agent.agent_models import SessionPhase
from crater_dating_agent.deepseek_client import RangePromptMode
from crater_dating_agent.i18n import Language, tr
from crater_dating_agent.web_app import default_output_root, parse_local_path


APP = Path(__file__).resolve().parents[1] / "crater_dating_agent" / "web_app.py"


def test_copied_local_path_accepts_matching_outer_quotes_and_whitespace() -> None:
    expected = Path(r"E:\data\AREA_SID9.shp")

    assert parse_local_path('  "E:\\data\\AREA_SID9.shp"  ') == expected
    assert parse_local_path("  'E:\\data\\AREA_SID9.shp'  ") == expected
    assert parse_local_path(r"E:\data\AREA_SID9.shp") == expected


def test_output_root_uses_environment_override_and_preserves_default(tmp_path: Path) -> None:
    configured = tmp_path / "configured-output"

    assert default_output_root({"CRATER_OUTPUT_ROOT": str(configured)}) == configured
    assert default_output_root({}) == web_app.PROJECT_ROOT / "outputs"


def test_initial_page_has_bilingual_switch_and_three_required_paths() -> None:
    app = AppTest.from_file(APP)
    app.run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "月球撞击坑智能定年系统"
    labels = [item.label for item in app.text_input]
    assert "AREA_<编号>.shp 本机绝对路径" in labels
    assert "CRATER_<编号>.shp 本机绝对路径" in labels
    assert "原始 GeoTIFF 本机绝对路径" in labels
    assert any(button.label == "验证输入并新建任务" for button in app.button)
    assert any(button.label == "恢复已有任务" for button in app.button)
    assert "workflow_state.json" in [item.label for item in app.text_input]
    assert "王艺燃" not in str(app)


def test_language_switch_changes_fixed_ui_without_changing_path_values() -> None:
    app = AppTest.from_file(APP)
    app.run(timeout=20)
    app.text_input[0].set_value(r"E:\data\AREA_Saussure_D.shp")
    app.radio[0].set_value("English").run(timeout=20)

    assert app.title[0].value == "Lunar Crater Intelligent Dating System"
    assert app.text_input[0].value == r"E:\data\AREA_Saussure_D.shp"
    assert any(button.label == "Validate inputs and create task" for button in app.button)


def test_detection_interruption_warning_is_available_in_both_languages() -> None:
    assert tr("detection_interruption_warning", Language.ZH) == (
        "自动识别运行期间，请勿切换语言、刷新页面或关闭此浏览器标签。"
    )
    assert tr("detection_interruption_warning", Language.EN) == (
        "While automatic detection is running, do not change language, refresh "
        "the page, or close this browser tab."
    )


def test_web_analysis_uses_selected_few_shot_mode(monkeypatch, tmp_path: Path) -> None:
    selected_modes = []
    updated = object()

    class FakeStreamlit:
        session_state = SimpleNamespace()

        def caption(self, text: str) -> None:
            pass

        def radio(self, label: str, *, options, format_func, key: str) -> str:
            assert label == tr("prompt_mode", Language.ZH)
            assert options == ["zero_shot", "few_shot"]
            assert format_func("few_shot") == "专家案例引导（few-shot）"
            assert tr("prompt_mode_few_shot", Language.EN) == "Expert-guided (few-shot)"
            return "few_shot"

        def text_input(self, label: str, *, type: str, key: str) -> str:
            return "test-key"

        def button(self, label: str, *, type: str) -> bool:
            return True

        def empty(self):
            return SimpleNamespace(info=lambda text: None)

        def rerun(self) -> None:
            pass

    class FakeClient:
        def __init__(self, settings, *, response_language, progress_callback, prompt_mode):
            selected_modes.append(prompt_mode)

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(web_app, "st", FakeStreamlit())
    monkeypatch.setattr(web_app.DeepSeekSettings, "from_env", lambda values: object())
    monkeypatch.setattr(web_app, "DeepSeekRangeClient", FakeClient)
    monkeypatch.setattr(web_app, "analyze_session", lambda path, *, client: updated)

    web_app._agent_stage(
        SimpleNamespace(phase=SessionPhase.OVERVIEW_READY, state_path=tmp_path / "state.json"),
        Language.ZH,
    )

    assert selected_modes == [RangePromptMode.FEW_SHOT]
    assert web_app.st.session_state.agent_session is updated


def test_candidate_statistics_warnings_are_shown_as_red_errors(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.errors: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def info(self, message: str) -> None:
            pass

        def container(self, *, border: bool):
            return self

        def subheader(self, message: str) -> None:
            pass

        def write(self, message: str) -> None:
            pass

        def error(self, message: str) -> None:
            self.errors.append(message)

        def checkbox(self, label: str, *, key: str) -> bool:
            return False

        def button(self, label: str, *, key: str) -> bool:
            return False

        def expander(self, label: str):
            return self

        def number_input(self, label: str, *, min_value: float, value: float) -> float:
            return value

    candidate_path = tmp_path / "llm" / "range_candidates.json"
    candidate_path.parent.mkdir()
    candidate_path.write_text(json.dumps({
        "overall_observation": "需要复核",
        "candidates": [{
            "range_min_km": 0.1,
            "range_max_km": 0.2,
            "reason": "低统计候选",
            "risks": [],
            "warnings": ["LOW_EVENT_COUNT"],
        }],
    }), encoding="utf-8")
    fake_st = FakeStreamlit()
    monkeypatch.setattr(web_app, "st", fake_st)

    web_app._candidate_stage(SimpleNamespace(session_dir=tmp_path, state_path=tmp_path / "state.json"), Language.ZH)

    assert fake_st.errors == [f"{tr('risks', Language.ZH)}: LOW_EVENT_COUNT"]
