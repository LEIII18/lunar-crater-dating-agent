from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from crater_dating_agent.web_app import parse_local_path


APP = Path(__file__).resolve().parents[1] / "crater_dating_agent" / "web_app.py"


def test_copied_local_path_accepts_matching_outer_quotes_and_whitespace() -> None:
    expected = Path(r"E:\data\AREA_SID9.shp")

    assert parse_local_path('  "E:\\data\\AREA_SID9.shp"  ') == expected
    assert parse_local_path("  'E:\\data\\AREA_SID9.shp'  ") == expected
    assert parse_local_path(r"E:\data\AREA_SID9.shp") == expected


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
