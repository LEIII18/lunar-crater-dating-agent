from __future__ import annotations

import struct
from math import isfinite
from pathlib import Path

from .agent_models import AgentRequest
from .models import DatingError, DatingRequest, ResolvedInputs


REQUIRED_SHAPEFILE_SUFFIXES = (".shp", ".shx", ".dbf", ".prj")


def read_dbf_record_count(path: Path) -> int:
    try:
        with path.open("rb") as stream:
            header = stream.read(32)
    except OSError as exc:
        raise DatingError(f"无法读取 DBF：{path}（{exc}）") from exc
    if len(header) < 32:
        raise DatingError(f"DBF 文件头不完整：{path}")
    return struct.unpack("<I", header[4:8])[0]


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise DatingError(f"缺少 {label} 文件：{path}")


def _require_shapefile_set(shp_path: Path, label: str) -> None:
    for suffix in REQUIRED_SHAPEFILE_SUFFIXES:
        _require_file(shp_path.with_suffix(suffix), f"{label} {suffix}")


def _resolve_files(crater_path: Path, area_path: Path, image_path: Path) -> ResolvedInputs:
    crater_shp = Path(crater_path).resolve()
    area_shp = Path(area_path).resolve()
    image_tif = Path(image_path).resolve()

    if crater_shp.suffix.lower() != ".shp" or not crater_shp.stem.lower().startswith("crater_"):
        raise DatingError(f"CRATER 输入必须是 CRATER_*.shp：{crater_shp}")

    case_id = crater_shp.stem[len("CRATER_") :]
    if not case_id:
        raise DatingError("CRATER 文件名缺少样区标识")
    expected_area_name = f"AREA_{case_id}.shp"
    if area_shp.name.lower() != expected_area_name.lower():
        raise DatingError(
            f"AREA 文件名应为：{expected_area_name}；当前为：{area_shp.name}"
        )

    _require_shapefile_set(crater_shp, "CRATER")
    _require_shapefile_set(area_shp, "AREA")

    if image_tif.suffix.lower() not in (".tif", ".tiff"):
        raise DatingError(f"影像必须是 TIFF：{image_tif}")
    _require_file(image_tif, "TIFF")

    crater_count = read_dbf_record_count(crater_shp.with_suffix(".dbf"))
    if crater_count < 1:
        raise DatingError(f"CRATER 数据为空：{crater_shp}")

    return ResolvedInputs(case_id, crater_shp, area_shp, image_tif, crater_count)


def resolve_inputs(request: DatingRequest) -> ResolvedInputs:
    if not isfinite(request.range_min_km) or not isfinite(request.range_max_km):
        raise DatingError("range 上下限必须是有限数值")
    if request.range_min_km <= 0:
        raise DatingError("range 下限必须大于 0 km")
    if request.range_max_km <= request.range_min_km:
        raise DatingError("range 上限必须大于下限")

    return _resolve_files(request.crater_shp, request.area_shp, request.image_tif)


def resolve_agent_inputs(request: AgentRequest) -> ResolvedInputs:
    return _resolve_files(request.crater_shp, request.area_shp, request.image_tif)
