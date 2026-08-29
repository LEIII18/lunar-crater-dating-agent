from __future__ import annotations

from datetime import datetime
from pathlib import Path

import shapefile
from pyproj import CRS

from crater_dating_agent.workflow_inputs import validate_workflow_inputs
from crater_dating_agent.workflow_workspace import (
    copy_shapefile_set,
    create_workflow_workspace,
)


def _write_inputs(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    projection = CRS.from_epsg(4326).to_wkt()
    area = root / "AREA_SID9.shp"
    with shapefile.Writer(str(area), shapeType=shapefile.POLYGON) as writer:
        writer.field("Area", "F", size=19, decimal=11)
        writer.field("Area_Name", "C", size=30)
        writer.poly([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]])
        writer.record(4.0, "SID9")
    area.with_suffix(".prj").write_text(projection, encoding="utf-8")
    area.with_suffix(".cpg").write_text("UTF-8", encoding="ascii")

    crater = root / "CRATER_SID9.shp"
    with shapefile.Writer(str(crater), shapeType=shapefile.POLYGON) as writer:
        writer.field("Diam_km", "F", size=19, decimal=11)
        writer.field("x_coord", "F", size=19, decimal=11)
        writer.field("y_coord", "F", size=19, decimal=11)
        writer.field("tag", "C", size=8)
    crater.with_suffix(".prj").write_text(projection, encoding="utf-8")
    crater.with_suffix(".CPG").write_text("UTF-8", encoding="ascii")

    image = root / "63_61E8_08N.tif"
    image.write_bytes(b"original tif")
    return validate_workflow_inputs(area, crater, image)


def _fixed_clock() -> datetime:
    return datetime(2026, 8, 25, 12, 0, 0).astimezone()


def test_workspace_copies_inputs_into_unique_task_directory(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path / "source")

    workspace = create_workflow_workspace(
        inputs, tmp_path / "outputs", clock=_fixed_clock
    )

    assert workspace.root == (
        tmp_path / "outputs" / "SID9" / "20260825_120000_000000"
    ).resolve()
    assert workspace.area_shp == workspace.source_dir / "AREA_SID9.shp"
    assert workspace.crater_shp == workspace.source_dir / "CRATER_SID9.shp"
    assert workspace.image_tif == inputs.image_tif
    assert workspace.detection_work_dir.is_dir()
    assert workspace.detection_preview_dir.is_dir()
    assert workspace.manual_revision_dir.is_dir()
    assert workspace.logs_dir.is_dir()


def test_workspace_preserves_source_bytes_and_uppercase_sidecar(
    tmp_path: Path,
) -> None:
    inputs = _write_inputs(tmp_path / "source")
    original_components = {
        path.name: path.read_bytes()
        for path in inputs.crater_shp.parent.iterdir()
        if path.stem == inputs.crater_shp.stem
    }

    workspace = create_workflow_workspace(
        inputs, tmp_path / "outputs", clock=_fixed_clock
    )

    assert (workspace.source_dir / "CRATER_SID9.CPG").is_file()
    assert {
        path.name: path.read_bytes()
        for path in inputs.crater_shp.parent.iterdir()
        if path.stem == inputs.crater_shp.stem
    } == original_components


def test_same_timestamp_allocates_a_second_directory(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path / "source")

    first = create_workflow_workspace(inputs, tmp_path / "outputs", clock=_fixed_clock)
    second = create_workflow_workspace(inputs, tmp_path / "outputs", clock=_fixed_clock)

    assert first.root.name == "20260825_120000_000000"
    assert second.root.name == "20260825_120000_000000_01"


def test_manual_copy_uses_its_own_directory_and_keeps_exact_filename(
    tmp_path: Path,
) -> None:
    inputs = _write_inputs(tmp_path / "source")
    manual_source = tmp_path / "manual_source"
    manual_source.mkdir()
    for component in inputs.crater_shp.parent.iterdir():
        if component.stem == inputs.crater_shp.stem:
            (manual_source / component.name).write_bytes(component.read_bytes())
    workspace = create_workflow_workspace(
        inputs, tmp_path / "outputs", clock=_fixed_clock
    )

    copied = copy_shapefile_set(
        manual_source / "CRATER_SID9.shp", workspace.manual_revision_dir
    )

    assert copied == workspace.manual_revision_dir / "CRATER_SID9.shp"
    assert copied.is_file()
    assert copied != workspace.crater_shp
