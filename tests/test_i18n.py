from __future__ import annotations

import pytest

from crater_dating_agent.i18n import Language, tr


def test_dynamic_case_id_is_preserved_in_both_languages() -> None:
    assert tr("area_legend", Language.ZH, case_id="Saussure_D") == (
        "AREA_Saussure_D 定年区域"
    )
    assert tr("area_legend", Language.EN, case_id="Saussure_D") == (
        "AREA_Saussure_D dating area"
    )


def test_detection_model_label_does_not_expose_person_name() -> None:
    chinese = tr("empty_crater_route", Language.ZH)
    english = tr("empty_crater_route", Language.EN)

    assert chinese == "CRATER 为空，将调用撞击坑自动识别模型"
    assert english == "CRATER is empty; the automatic crater detection model will run"
    assert "王艺燃" not in chinese + english


def test_missing_translation_key_fails_loudly() -> None:
    with pytest.raises(KeyError, match="missing_key"):
        tr("missing_key", Language.ZH)


@pytest.mark.parametrize("language", list(Language))
def test_web_interface_catalog_is_complete(language: Language) -> None:
    required = (
        "page_title", "new_task", "validate_inputs", "start_detection",
        "accept_automatic", "manual_revision_path", "validate_manual",
        "accept_manual", "start_dating", "analyze_ranges", "manual_range",
        "generate_final", "final_result", "advanced_settings",
        "session_phase", "analysis_interrupted", "session_failed",
        "recover_session", "undo_step",
        "resume_task",
    )
    for key in required:
        assert tr(key, language, case_id="SID9")
