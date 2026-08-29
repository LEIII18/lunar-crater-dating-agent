from __future__ import annotations

from pathlib import Path

import shapefile
from pyproj import CRS

from .models import DatingError
from .workflow_models import CraterStatistics, WorkflowInputs, WorkflowRoute


REQUIRED_SHAPEFILE_SUFFIXES = (".shp", ".shx", ".dbf", ".prj")
AREA_FIELDS = frozenset({"Area", "Area_Name"})
CRATER_FIELDS = frozenset({"Diam_km", "x_coord", "y_coord", "tag"})
POLYGON_TYPES = frozenset(
    {shapefile.POLYGON, shapefile.POLYGONM, shapefile.POLYGONZ}
)


def _require_regular_file(path: Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if Path(path).is_symlink() or not resolved.is_file():
        raise DatingError(f"缺少 {label} 文件：{path}")
    return resolved


def _require_shapefile_set(path: Path, label: str) -> Path:
    if path.suffix.lower() != ".shp":
        raise DatingError(f"{label} 输入必须是 .shp：{path}")
    resolved = _require_regular_file(path, f"{label} .shp")
    for suffix in REQUIRED_SHAPEFILE_SUFFIXES[1:]:
        _require_regular_file(resolved.with_suffix(suffix), f"{label} {suffix}")
    return resolved


def _case_id(area_shp: Path, crater_shp: Path) -> str:
    if not area_shp.stem.startswith("AREA_"):
        raise DatingError(f"AREA 文件名必须以 AREA_ 开头：{area_shp.name}")
    if not crater_shp.stem.startswith("CRATER_"):
        raise DatingError(f"CRATER 文件名必须以 CRATER_ 开头：{crater_shp.name}")
    area_case = area_shp.stem[len("AREA_") :]
    crater_case = crater_shp.stem[len("CRATER_") :]
    if not area_case or not crater_case:
        raise DatingError("AREA/CRATER 文件名缺少任务编号")
    if area_case != crater_case:
        raise DatingError(
            f"AREA 与 CRATER 任务编号必须完全一致：{area_case} != {crater_case}"
        )
    return area_case


def _read_shapefile(path: Path, label: str) -> shapefile.Reader:
    try:
        return shapefile.Reader(str(path))
    except (OSError, shapefile.ShapefileException) as exc:
        raise DatingError(f"无法读取 {label} Shapefile：{path}（{exc}）") from exc


def _validate_schema(path: Path, label: str, required_fields: frozenset[str]) -> int:
    reader = _read_shapefile(path, label)
    try:
        if reader.shapeType not in POLYGON_TYPES:
            raise DatingError(f"{label} 几何类型必须是 Polygon：{path}")
        actual_fields = {field.name for field in reader.fields[1:]}
        missing = sorted(required_fields - actual_fields)
        if missing:
            raise DatingError(f"{label} 缺少字段：{', '.join(missing)}")
        return len(reader)
    finally:
        reader.close()


def _read_crs(path: Path, label: str) -> CRS:
    try:
        text = path.with_suffix(".prj").read_text(encoding="utf-8")
        return CRS.from_wkt(text)
    except (OSError, ValueError) as exc:
        raise DatingError(f"无法读取 {label} 坐标系：{path.with_suffix('.prj')}") from exc


def _validate_pair(area_path: Path, crater_path: Path) -> tuple[str, Path, Path, int]:
    area_shp = _require_shapefile_set(Path(area_path), "AREA")
    crater_shp = _require_shapefile_set(Path(crater_path), "CRATER")
    case_id = _case_id(area_shp, crater_shp)
    _validate_schema(area_shp, "AREA", AREA_FIELDS)
    crater_count = _validate_schema(crater_shp, "CRATER", CRATER_FIELDS)
    area_crs = _read_crs(area_shp, "AREA")
    crater_crs = _read_crs(crater_shp, "CRATER")
    if not area_crs.equals(crater_crs):
        raise DatingError("AREA 与 CRATER 坐标系不一致")
    return case_id, area_shp, crater_shp, crater_count


def validate_workflow_inputs(
    area_shp: Path, crater_shp: Path, image_tif: Path
) -> WorkflowInputs:
    case_id, area, crater, crater_count = _validate_pair(area_shp, crater_shp)
    image = Path(image_tif)
    if image.suffix.lower() not in {".tif", ".tiff"}:
        raise DatingError(f"影像必须是 TIFF：{image}")
    image = _require_regular_file(image, "TIFF")
    route = (
        WorkflowRoute.AUTO_DETECT
        if crater_count == 0
        else WorkflowRoute.USE_EXISTING
    )
    return WorkflowInputs(case_id, area, crater, image, crater_count, route)


def validate_manual_crater(
    area_shp: Path, crater_shp: Path, expected_case_id: str
) -> int:
    case_id, _area, _crater, crater_count = _validate_pair(area_shp, crater_shp)
    if case_id != expected_case_id:
        raise DatingError(
            f"人工修订 CRATER 任务编号必须是 {expected_case_id}：当前为 {case_id}"
        )
    if crater_count < 1:
        raise DatingError("人工修订 CRATER 至少包含一个撞击坑")
    return crater_count


def read_crater_statistics(crater_shp: Path) -> CraterStatistics:
    path = _require_shapefile_set(Path(crater_shp), "CRATER")
    reader = _read_shapefile(path, "CRATER")
    try:
        fields = [field.name for field in reader.fields[1:]]
        try:
            diameter_index = fields.index("Diam_km")
        except ValueError as exc:
            raise DatingError(f"CRATER 缺少字段：Diam_km") from exc
        try:
            diameters = tuple(
                float(record[diameter_index]) for record in reader.iterRecords()
            )
        except (TypeError, ValueError) as exc:
            raise DatingError(f"CRATER 的 Diam_km 包含无效值：{path}") from exc
    finally:
        reader.close()
    return CraterStatistics(
        count=len(diameters),
        at_least_one_km=sum(value >= 1.0 for value in diameters),
        minimum_diameter_km=min(diameters) if diameters else None,
        maximum_diameter_km=max(diameters) if diameters else None,
    )
