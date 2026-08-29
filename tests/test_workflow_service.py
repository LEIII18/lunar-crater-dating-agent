from __future__ import annotations

import json
import struct
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import shapefile
from pyproj import CRS

from crater_dating_agent.models import DatingError
from crater_dating_agent.path_resolver import resolve_agent_inputs
from crater_dating_agent.pipeline_runner import DetectionSettings
from crater_dating_agent.session_store import create_session_at
from crater_dating_agent.workflow_models import (
    DetectionRunResult,
    OverlayPreview,
    WorkflowPhase,
    WorkflowRequest,
)
from crater_dating_agent.workflow_service import (
    accept_automatic_result,
    accept_manual_revision,
    import_manual_revision,
    load_workflow_state,
    run_automatic_detection,
    start_dating_session,
    start_workflow,
)


def _write_inputs(root: Path, *, crater_count: int) -> WorkflowRequest:
    root.mkdir(parents=True, exist_ok=True)
    projection = CRS.from_epsg(4326).to_wkt()
    area = root / "AREA_SID9.shp"
    with shapefile.Writer(str(area), shapeType=shapefile.POLYGON) as writer:
        writer.field("Area", "F", size=19, decimal=11)
        writer.field("Area_Name", "C", size=30)
        writer.poly([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]])
        writer.record(4.0, "SID9")
    area.with_suffix(".prj").write_text(projection, encoding="utf-8")
    crater = root / "CRATER_SID9.shp"
    with shapefile.Writer(str(crater), shapeType=shapefile.POLYGON) as writer:
        writer.field("Diam_km", "F", size=19, decimal=11)
        writer.field("x_coord", "F", size=19, decimal=11)
        writer.field("y_coord", "F", size=19, decimal=11)
        writer.field("tag", "C", size=8)
        for index in range(crater_count):
            x = 0.2 + index * 0.2
            writer.poly([[[x, x], [x + 0.1, x], [x + 0.1, x + 0.1], [x, x]]])
            writer.record(0.5, x, x, "standard")
    crater.with_suffix(".prj").write_text(projection, encoding="utf-8")
    image = root / "63_61E8_08N.tif"
    image.write_bytes(b"tif")
    return WorkflowRequest(area, crater, image)


def _settings(tmp_path: Path) -> DetectionSettings:
    return DetectionSettings(
        arcpy_python=tmp_path / "arcpy.exe",
        model_python=tmp_path / "model.exe",
        model_dir=tmp_path / "model",
    )


def _clock() -> datetime:
    return datetime(2026, 8, 25, 15, 0, 0).astimezone()


def _set_dbf_count(dbf_path: Path, count: int) -> None:
    data = bytearray(dbf_path.read_bytes())
    data[4:8] = struct.pack("<I", count)
    dbf_path.write_bytes(data)


def _fake_preview(*args, **kwargs) -> OverlayPreview:
    output_path = Path(args[3])
    output_path.write_bytes(b"png")
    return OverlayPreview(output_path, SimpleNamespace(data=[]), 100, 100)


def test_empty_crater_waits_for_detection_and_confirmation(tmp_path: Path) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=0),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )

    assert state.phase is WorkflowPhase.DETECTION_READY
    assert state.route.value == "auto_detect"
    assert state.selected_crater_shp is None
    with pytest.raises(DatingError, match="确认|定年"):
        start_dating_session(state, prepare_session=lambda *args, **kwargs: object())


def test_nonempty_crater_skips_detection_and_is_dating_ready(tmp_path: Path) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=2),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )

    assert state.phase is WorkflowPhase.DATING_READY
    assert state.selected_crater_shp == state.workspace.crater_shp
    assert state.data_source == "existing"


def test_automatic_detection_stops_at_review_until_user_accepts(tmp_path: Path) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=0),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )

    def fake_detector(workspace, settings, on_line=None):
        _set_dbf_count(workspace.crater_shp.with_suffix(".dbf"), 4)
        log_path = workspace.logs_dir / "detection.log"
        log_path.write_text("detected", encoding="utf-8")
        return DetectionRunResult(workspace.crater_shp, 4, log_path, ("detector",))

    reviewed = run_automatic_detection(
        state, detection_runner=fake_detector, preview_renderer=_fake_preview
    )

    assert reviewed.phase is WorkflowPhase.DETECTION_REVIEW
    assert reviewed.automatic_crater_shp == reviewed.workspace.crater_shp
    assert reviewed.automatic_preview_path.is_file()
    assert reviewed.selected_crater_shp is None
    accepted = accept_automatic_result(reviewed)
    assert accepted.phase is WorkflowPhase.DATING_READY
    assert accepted.selected_crater_shp == accepted.automatic_crater_shp
    assert accepted.data_source == "automatic"


def test_manual_revision_gets_new_preview_and_second_confirmation(tmp_path: Path) -> None:
    initial = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=0),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )

    def fake_detector(workspace, settings, on_line=None):
        _set_dbf_count(workspace.crater_shp.with_suffix(".dbf"), 3)
        log_path = workspace.logs_dir / "detection.log"
        log_path.write_text("detected", encoding="utf-8")
        return DetectionRunResult(workspace.crater_shp, 3, log_path, ("detector",))

    reviewed = run_automatic_detection(
        initial, detection_runner=fake_detector, preview_renderer=_fake_preview
    )
    manual_request = _write_inputs(tmp_path / "manual", crater_count=2)

    manual = import_manual_revision(
        reviewed, manual_request.crater_shp, preview_renderer=_fake_preview
    )

    assert manual.phase is WorkflowPhase.MANUAL_REVIEW
    assert manual.manual_crater_shp.parent == manual.workspace.manual_revision_dir
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        assert (manual.workspace.manual_revision_dir / f"AREA_SID9{suffix}").is_file()
    assert manual.manual_preview_path.is_file()
    assert manual.automatic_crater_shp.is_file()
    assert manual.selected_crater_shp is None
    accepted = accept_manual_revision(manual)
    assert accepted.phase is WorkflowPhase.DATING_READY
    assert accepted.selected_crater_shp == accepted.manual_crater_shp
    assert accepted.data_source == "manual"


def test_workflow_state_json_contains_route_but_no_api_key(tmp_path: Path) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=1),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )

    payload = json.loads(state.state_path.read_text(encoding="utf-8"))

    assert payload["route"] == "use_existing"
    assert payload["phase"] == "dating_ready"
    assert "api_key" not in json.dumps(payload).lower()


def test_saved_workflow_can_be_loaded_after_web_refresh(tmp_path: Path) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=2),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )

    loaded = load_workflow_state(state.state_path)

    assert loaded == state
    assert loaded.workspace.root == state.state_path.parent.resolve()


def test_workflow_loader_rejects_embedded_workspace_outside_task_root(
    tmp_path: Path,
) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=2),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )
    payload = json.loads(state.state_path.read_text(encoding="utf-8"))
    payload["workspace"]["root"] = str(tmp_path / "other-task")
    state.state_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatingError, match="任务根目录|工作流状态"):
        load_workflow_state(state.state_path)


def test_start_dating_passes_selected_task_copy_and_existing_directory(
    tmp_path: Path,
) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=1),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )
    captured = {}

    def fake_prepare(request, **kwargs):
        captured["request"] = request
        captured.update(kwargs)
        return "agent-session"

    result = start_dating_session(state, prepare_session=fake_prepare, clock=_clock)

    assert result == "agent-session"
    assert captured["request"].crater_shp == state.workspace.crater_shp
    assert captured["request"].area_shp == state.workspace.area_shp
    assert captured["session_dir"] == state.workspace.root
    payload = json.loads(state.state_path.read_text(encoding="utf-8"))
    assert payload["phase"] == "dating_started"


def test_failed_dating_attempt_is_archived_before_retry(tmp_path: Path) -> None:
    state = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=1),
        _settings(tmp_path),
        tmp_path / "outputs",
        clock=_clock,
    )
    state.workspace.root.joinpath("session_state.json").write_text(
        '{"phase": "failed"}\n', encoding="utf-8"
    )
    state.workspace.root.joinpath("llm").mkdir()
    state.workspace.root.joinpath("llm", "evidence.txt").write_text(
        "failed response", encoding="utf-8"
    )
    state.workspace.root.joinpath("overview").mkdir()
    state.workspace.root.joinpath("overview", "evidence.log").write_text(
        "failed craterstats", encoding="utf-8"
    )

    def create_real_session(request, **kwargs):
        return create_session_at(
            resolve_agent_inputs(request), kwargs["session_dir"], clock=kwargs["clock"]
        )

    session = start_dating_session(
        state, prepare_session=create_real_session, clock=_clock
    )

    archives = list(state.workspace.root.joinpath("failed_attempts").iterdir())
    assert session.state_path.is_file()
    assert len(archives) == 1
    assert archives[0].joinpath("session_state.json").is_file()
    assert archives[0].joinpath("llm", "evidence.txt").read_text(
        encoding="utf-8"
    ) == "failed response"
    assert archives[0].joinpath("overview", "evidence.log").read_text(
        encoding="utf-8"
    ) == "failed craterstats"
    assert state.state_path.is_file()


def test_failed_manual_preview_can_be_retried_without_stale_copy(
    tmp_path: Path,
) -> None:
    initial = start_workflow(
        _write_inputs(tmp_path / "input", crater_count=0),
        _settings(tmp_path), tmp_path / "outputs", clock=_clock,
    )

    def fake_detector(workspace, settings, on_line=None):
        _set_dbf_count(workspace.crater_shp.with_suffix(".dbf"), 3)
        log_path = workspace.logs_dir / "detection.log"
        log_path.write_text("detected", encoding="utf-8")
        return DetectionRunResult(workspace.crater_shp, 3, log_path, ("detector",))

    reviewed = run_automatic_detection(
        initial, detection_runner=fake_detector, preview_renderer=_fake_preview
    )
    manual_request = _write_inputs(tmp_path / "manual", crater_count=2)

    with pytest.raises(DatingError, match="preview failed"):
        import_manual_revision(
            reviewed, manual_request.crater_shp,
            preview_renderer=lambda *args, **kwargs: (_ for _ in ()).throw(
                DatingError("preview failed")
            ),
        )

    retried = import_manual_revision(
        reviewed, manual_request.crater_shp, preview_renderer=_fake_preview
    )
    assert retried.phase is WorkflowPhase.MANUAL_REVIEW
