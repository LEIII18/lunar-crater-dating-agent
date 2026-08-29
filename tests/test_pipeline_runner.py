from __future__ import annotations

import io
import struct
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
import shapefile
from pyproj import CRS

from crater_dating_agent.models import DatingError
from crater_dating_agent.pipeline_runner import (
    DetectionSettings,
    build_detection_argv,
    run_detection,
)
from crater_dating_agent.workflow_inputs import validate_workflow_inputs
from crater_dating_agent.workflow_workspace import create_workflow_workspace


def _workspace(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    wkt = CRS.from_epsg(4326).to_wkt()
    area = source / "AREA_SID9.shp"
    with shapefile.Writer(str(area), shapeType=shapefile.POLYGON) as writer:
        writer.field("Area", "F", size=19, decimal=11)
        writer.field("Area_Name", "C", size=30)
        writer.poly([[[0, 0], [1, 0], [1, 1], [0, 0]]])
        writer.record(0.5, "SID9")
    area.with_suffix(".prj").write_text(wkt, encoding="utf-8")
    crater = source / "CRATER_SID9.shp"
    with shapefile.Writer(str(crater), shapeType=shapefile.POLYGON) as writer:
        writer.field("Diam_km", "F", size=19, decimal=11)
        writer.field("x_coord", "F", size=19, decimal=11)
        writer.field("y_coord", "F", size=19, decimal=11)
        writer.field("tag", "C", size=8)
    crater.with_suffix(".prj").write_text(wkt, encoding="utf-8")
    image = source / "63_61E8_08N.tif"
    image.write_bytes(b"tif")
    inputs = validate_workflow_inputs(area, crater, image)
    return create_workflow_workspace(
        inputs,
        tmp_path / "outputs",
        clock=lambda: datetime(2026, 8, 25, 12, 0, 0).astimezone(),
    )


def _settings(tmp_path: Path) -> DetectionSettings:
    arcpy_python = tmp_path / "ArcGIS" / "python.exe"
    model_python = tmp_path / "model-env" / "python.exe"
    model_dir = tmp_path / "wangyiranCode"
    weight = model_dir / "model_data" / "moon" / "weights" / "moon.onnx"
    arcpy_python.parent.mkdir()
    model_python.parent.mkdir()
    weight.parent.mkdir(parents=True)
    arcpy_python.write_bytes(b"exe")
    model_python.write_bytes(b"exe")
    (model_dir / "predict_onnx.py").write_text("# fixture", encoding="utf-8")
    weight.write_bytes(b"onnx")
    return DetectionSettings(
        arcpy_python=arcpy_python,
        model_python=model_python,
        model_dir=model_dir,
    )


def _set_dbf_count(dbf_path: Path, count: int) -> None:
    data = bytearray(dbf_path.read_bytes())
    data[4:8] = struct.pack("<I", count)
    dbf_path.write_bytes(data)


class _FakeProcess:
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.stdout = io.StringIO(output)

    def wait(self) -> int:
        return self.returncode


def test_detection_argv_passes_task_copy_to_stable_pipeline(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    settings = _settings(tmp_path)

    argv = build_detection_argv(workspace, settings)

    assert argv[0] == str(settings.arcpy_python.resolve())
    assert argv[1].endswith("part1_code\\auto_crater_detection_pipeline.py")
    assert argv[argv.index("--area-shp") + 1] == str(workspace.area_shp)
    assert argv[argv.index("--target-shp") + 1] == str(workspace.crater_shp)
    assert argv[argv.index("--image-tif") + 1] == str(workspace.image_tif)
    assert argv[argv.index("--work-dir") + 1] == str(workspace.detection_work_dir)
    assert argv[argv.index("--model-python") + 1] == str(settings.model_python.resolve())
    assert argv[argv.index("--model-dir") + 1] == str(settings.model_dir.resolve())
    assert "--overwrite" in argv


def test_run_detection_streams_output_and_requires_nonempty_result(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    settings = _settings(tmp_path)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    displayed: list[str] = []

    def fake_popen(argv, **kwargs):
        calls.append((tuple(argv), kwargs))
        _set_dbf_count(workspace.crater_shp.with_suffix(".dbf"), 2)
        return _FakeProcess(0, "Clipping raster\nInserted 2 detected craters\n")

    result = run_detection(
        workspace, settings, on_line=displayed.append, popen_factory=fake_popen
    )

    assert result.crater_count == 2
    assert result.crater_shp == workspace.crater_shp
    assert result.log_path.read_text(encoding="utf-8") == (
        "Clipping raster\nInserted 2 detected craters\n"
    )
    assert displayed == ["Clipping raster", "Inserted 2 detected craters"]
    assert calls[0][1]["shell"] is False


def test_run_detection_reports_nonzero_exit_and_log_path(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    settings = _settings(tmp_path)

    with pytest.raises(DatingError, match=r"退出码 7.*detection\.log"):
        run_detection(
            workspace,
            settings,
            popen_factory=lambda argv, **kwargs: _FakeProcess(7, "ArcPy failed\n"),
        )

    assert "ArcPy failed" in (
        workspace.logs_dir / "detection.log"
    ).read_text(encoding="utf-8")


def test_run_detection_rejects_missing_model_weight_before_process_start(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    settings = _settings(tmp_path)
    missing_weight = settings.model_dir / "model_data" / "moon" / "weights" / "moon.onnx"
    missing_weight.unlink()
    process_started = False

    def forbidden_popen(argv, **kwargs):
        nonlocal process_started
        process_started = True
        return _FakeProcess(0, "")

    with pytest.raises(DatingError, match="moon.onnx"):
        run_detection(workspace, settings, popen_factory=forbidden_popen)

    assert process_started is False


def test_settings_can_be_overridden_without_changing_source_code(tmp_path: Path) -> None:
    settings = DetectionSettings.from_env(
        {
            "ARCPY_PYTHON": str(tmp_path / "arc-python.exe"),
            "CRATER_MODEL_PYTHON": str(tmp_path / "model-python.exe"),
            "CRATER_MODEL_DIR": str(tmp_path / "model"),
        }
    )

    assert settings.arcpy_python == tmp_path / "arc-python.exe"
    assert settings.model_python == tmp_path / "model-python.exe"
    assert settings.model_dir == tmp_path / "model"
