from __future__ import annotations

import struct
from pathlib import Path

import pytest

from crater_dating_agent.models import DatingError, DatingRequest
from crater_dating_agent.path_resolver import resolve_inputs


def write_dbf(path: Path, record_count: int) -> None:
    header = bytearray(32)
    header[0] = 3
    header[4:8] = struct.pack("<I", record_count)
    header[8:10] = struct.pack("<H", 32)
    header[10:12] = struct.pack("<H", 1)
    path.write_bytes(header)


def create_shapefile_set(directory: Path, stem: str, records: int) -> Path:
    shp = directory / f"{stem}.shp"
    for suffix in (".shp", ".shx", ".prj"):
        (directory / f"{stem}{suffix}").write_bytes(b"fixture")
    write_dbf(directory / f"{stem}.dbf", records)
    return shp


def valid_request(tmp_path: Path, *, crater_records: int = 63) -> DatingRequest:
    crater = create_shapefile_set(tmp_path, "CRATER_SID9", crater_records)
    area = create_shapefile_set(tmp_path, "AREA_SID9", 1)
    image = tmp_path / "63_61E8_08N.tif"
    image.write_bytes(b"tif")
    return DatingRequest(
        crater_shp=crater,
        area_shp=area,
        image_tif=image,
        range_min_km=0.06,
        range_max_km=0.2,
    )


def test_resolve_inputs_returns_case_and_real_crater_count(tmp_path: Path) -> None:
    request = valid_request(tmp_path, crater_records=63)

    resolved = resolve_inputs(request)

    assert resolved.case_id == "SID9"
    assert resolved.crater_count == 63
    assert resolved.crater_shp == request.crater_shp.resolve()
    assert resolved.area_shp == request.area_shp.resolve()
    assert resolved.image_tif == request.image_tif.resolve()


def test_resolve_inputs_allows_matching_area_and_crater_in_separate_directories(
    tmp_path: Path,
) -> None:
    area_dir = tmp_path / "source_copy"
    crater_dir = tmp_path / "manual_revision"
    area_dir.mkdir()
    crater_dir.mkdir()
    area = create_shapefile_set(area_dir, "AREA_SID80", 1)
    crater = create_shapefile_set(crater_dir, "CRATER_SID80", 6443)
    image = tmp_path / "162_69E44_17N.tif"
    image.write_bytes(b"tif")

    resolved = resolve_inputs(DatingRequest(crater, area, image, 0.1, 1.0))

    assert resolved.case_id == "SID80"
    assert resolved.area_shp == area.resolve()
    assert resolved.crater_shp == crater.resolve()
    assert resolved.crater_count == 6443


def test_resolve_inputs_rejects_missing_area_sidecar(tmp_path: Path) -> None:
    request = valid_request(tmp_path)
    request.area_shp.with_suffix(".shx").unlink()

    with pytest.raises(DatingError, match=r"AREA.*\.shx"):
        resolve_inputs(request)


def test_resolve_inputs_rejects_mismatched_area_name(tmp_path: Path) -> None:
    request = valid_request(tmp_path)
    other_area = create_shapefile_set(tmp_path, "AREA_OTHER", 1)
    request = DatingRequest(
        crater_shp=request.crater_shp,
        area_shp=other_area,
        image_tif=request.image_tif,
        range_min_km=0.06,
        range_max_km=0.2,
    )

    with pytest.raises(DatingError, match="AREA_SID9"):
        resolve_inputs(request)


def test_resolve_inputs_rejects_missing_tif(tmp_path: Path) -> None:
    request = valid_request(tmp_path)
    request.image_tif.unlink()

    with pytest.raises(DatingError, match="TIFF"):
        resolve_inputs(request)


def test_resolve_inputs_rejects_empty_crater_catalog(tmp_path: Path) -> None:
    request = valid_request(tmp_path, crater_records=0)

    with pytest.raises(DatingError, match="CRATER 数据为空"):
        resolve_inputs(request)


@pytest.mark.parametrize(
    ("range_min", "range_max"),
    [
        (0.0, 0.2),
        (-0.1, 0.2),
        (0.2, 0.2),
        (0.3, 0.2),
        (float("nan"), 0.2),
        (0.06, float("nan")),
        (float("inf"), 0.2),
        (0.06, float("inf")),
        (float("-inf"), 0.2),
    ],
)
def test_resolve_inputs_rejects_invalid_range(
    tmp_path: Path, range_min: float, range_max: float
) -> None:
    request = valid_request(tmp_path)
    request = DatingRequest(
        crater_shp=request.crater_shp,
        area_shp=request.area_shp,
        image_tif=request.image_tif,
        range_min_km=range_min,
        range_max_km=range_max,
    )

    with pytest.raises(DatingError, match="range"):
        resolve_inputs(request)


def test_resolve_inputs_rejects_empty_case_id(tmp_path: Path) -> None:
    crater = create_shapefile_set(tmp_path, "CRATER_", 1)
    area = create_shapefile_set(tmp_path, "AREA_", 1)
    image = tmp_path / "image.tif"
    image.write_bytes(b"tif")
    request = DatingRequest(crater, area, image, 0.06, 0.2)

    with pytest.raises(DatingError, match="样区标识"):
        resolve_inputs(request)
