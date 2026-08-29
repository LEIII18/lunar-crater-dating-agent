from __future__ import annotations

from pathlib import Path

import pytest
import shapefile
from pyproj import CRS

from crater_dating_agent.models import DatingError
from crater_dating_agent.workflow_inputs import (
    read_crater_statistics,
    validate_manual_crater,
    validate_workflow_inputs,
)
from crater_dating_agent.workflow_models import WorkflowRoute


WGS84_WKT = CRS.from_epsg(4326).to_wkt()
WEB_MERCATOR_WKT = CRS.from_epsg(3857).to_wkt()


def _write_area(
    directory: Path,
    stem: str = "AREA_SID9",
    *,
    projection: str = WGS84_WKT,
) -> Path:
    shp = directory / f"{stem}.shp"
    with shapefile.Writer(str(shp), shapeType=shapefile.POLYGON) as writer:
        writer.field("Area", "F", size=19, decimal=11)
        writer.field("Area_Name", "C", size=30)
        writer.poly([[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]])
        writer.record(4.0, stem)
    shp.with_suffix(".prj").write_text(projection, encoding="utf-8")
    return shp


def _write_crater(
    directory: Path,
    stem: str = "CRATER_SID9",
    *,
    count: int = 0,
    projection: str = WGS84_WKT,
    shape_type: int = shapefile.POLYGON,
    include_tag: bool = True,
) -> Path:
    shp = directory / f"{stem}.shp"
    with shapefile.Writer(str(shp), shapeType=shape_type) as writer:
        writer.field("Diam_km", "F", size=19, decimal=11)
        writer.field("x_coord", "F", size=19, decimal=11)
        writer.field("y_coord", "F", size=19, decimal=11)
        if include_tag:
            writer.field("tag", "C", size=8)
        for index in range(count):
            x = 0.25 + index * 0.25
            if shape_type == shapefile.POLYGON:
                writer.poly([[[x, x], [x + 0.1, x], [x + 0.1, x + 0.1], [x, x],]])
            else:
                writer.point(x, x)
            values = [0.1 + index, x, x]
            if include_tag:
                values.append("standard")
            writer.record(*values)
    shp.with_suffix(".prj").write_text(projection, encoding="utf-8")
    return shp


def _write_tiff(directory: Path) -> Path:
    path = directory / "63_61E8_08N.tif"
    path.write_bytes(b"TIFF fixture; raster content is validated by preview tests")
    return path


def test_empty_crater_routes_to_automatic_detection(tmp_path: Path) -> None:
    area = _write_area(tmp_path)
    crater = _write_crater(tmp_path, count=0)
    image = _write_tiff(tmp_path)

    result = validate_workflow_inputs(area, crater, image)

    assert result.case_id == "SID9"
    assert result.crater_count == 0
    assert result.route is WorkflowRoute.AUTO_DETECT


def test_nonempty_crater_routes_directly_to_dating(tmp_path: Path) -> None:
    area = _write_area(tmp_path)
    crater = _write_crater(tmp_path, count=3)
    image = _write_tiff(tmp_path)

    result = validate_workflow_inputs(area, crater, image)

    assert result.crater_count == 3
    assert result.route is WorkflowRoute.USE_EXISTING


def test_crater_statistics_include_one_km_priority_counts(tmp_path: Path) -> None:
    crater = _write_crater(tmp_path, count=3)

    stats = read_crater_statistics(crater)

    assert stats.count == 3
    assert stats.at_least_one_km == 2
    assert stats.minimum_diameter_km == pytest.approx(0.1)
    assert stats.maximum_diameter_km == pytest.approx(2.1)


@pytest.mark.parametrize(
    ("area_stem", "crater_stem"),
    [
        ("area_SID9", "CRATER_SID9"),
        ("AREA_SID9", "crater_SID9"),
        ("AREA_SID9", "CRATER_SID10"),
        ("AREA_Sid9", "CRATER_SID9"),
    ],
)
def test_names_require_exact_prefixes_and_matching_case_id(
    tmp_path: Path, area_stem: str, crater_stem: str
) -> None:
    area = _write_area(tmp_path, area_stem)
    crater = _write_crater(tmp_path, crater_stem)
    image = _write_tiff(tmp_path)

    with pytest.raises(DatingError, match="AREA_|CRATER_|任务编号"):
        validate_workflow_inputs(area, crater, image)


def test_crater_requires_standard_fields(tmp_path: Path) -> None:
    area = _write_area(tmp_path)
    crater = _write_crater(tmp_path, include_tag=False)
    image = _write_tiff(tmp_path)

    with pytest.raises(DatingError, match="tag"):
        validate_workflow_inputs(area, crater, image)


def test_area_and_crater_must_be_polygons(tmp_path: Path) -> None:
    area = _write_area(tmp_path)
    crater = _write_crater(tmp_path, shape_type=shapefile.POINT)
    image = _write_tiff(tmp_path)

    with pytest.raises(DatingError, match="Polygon"):
        validate_workflow_inputs(area, crater, image)


def test_area_and_crater_must_use_the_same_crs(tmp_path: Path) -> None:
    area = _write_area(tmp_path, projection=WGS84_WKT)
    crater = _write_crater(tmp_path, projection=WEB_MERCATOR_WKT)
    image = _write_tiff(tmp_path)

    with pytest.raises(DatingError, match="坐标系"):
        validate_workflow_inputs(area, crater, image)


def test_missing_required_shapefile_sidecar_is_rejected(tmp_path: Path) -> None:
    area = _write_area(tmp_path)
    crater = _write_crater(tmp_path)
    image = _write_tiff(tmp_path)
    crater.with_suffix(".shx").unlink()

    with pytest.raises(DatingError, match=r"CRATER.*\.shx"):
        validate_workflow_inputs(area, crater, image)


def test_manual_revision_must_be_nonempty_and_match_case(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    manual_dir = tmp_path / "manual"
    source_dir.mkdir()
    manual_dir.mkdir()
    area = _write_area(source_dir)
    empty_manual = _write_crater(manual_dir, count=0)

    with pytest.raises(DatingError, match="至少包含一个撞击坑"):
        validate_manual_crater(area, empty_manual, "SID9")

    nonempty_manual = _write_crater(manual_dir, count=2)
    assert validate_manual_crater(area, nonempty_manual, "SID9") == 2


def test_manual_revision_cannot_change_case_id(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    manual_dir = tmp_path / "manual"
    source_dir.mkdir()
    manual_dir.mkdir()
    area = _write_area(source_dir)
    crater = _write_crater(manual_dir, "CRATER_OTHER", count=1)

    with pytest.raises(DatingError, match="任务编号"):
        validate_manual_crater(area, crater, "SID9")
