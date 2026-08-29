from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import DatingError
from .workflow_models import WorkflowInputs, WorkflowWorkspace


Clock = Callable[[], datetime]
SHAPEFILE_SUFFIXES = frozenset(
    {
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
        ".sbn",
        ".sbx",
        ".qix",
        ".xml",
    }
)


def _components(source: Path) -> tuple[Path, ...]:
    source = Path(source).resolve()
    if source.suffix.lower() != ".shp" or not source.is_file():
        raise DatingError(f"Shapefile 不存在：{source}")
    matches = tuple(
        item
        for item in source.parent.iterdir()
        if item.is_file()
        and item.stem.casefold() == source.stem.casefold()
        and item.suffix.lower() in SHAPEFILE_SUFFIXES
    )
    if any(item.is_symlink() for item in matches):
        raise DatingError(f"Shapefile 配套文件不能是符号链接：{source}")
    return tuple(sorted(matches, key=lambda item: item.suffix.lower()))


def copy_shapefile_set(source: Path, destination_dir: Path) -> Path:
    source = Path(source).resolve()
    destination = Path(destination_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    components = _components(source)
    for component in components:
        target = destination / component.name
        if target.exists():
            raise DatingError(f"目标 Shapefile 配套文件已存在：{target}")
        shutil.copy2(component, target)
    copied_shp = destination / source.name
    if not copied_shp.is_file():
        raise DatingError(f"复制后缺少 Shapefile：{copied_shp}")
    return copied_shp


def _allocate_root(
    output_root: Path, case_id: str, started: datetime
) -> Path:
    case_dir = (Path(output_root).resolve() / case_id).resolve()
    case_dir.mkdir(parents=True, exist_ok=True)
    stem = started.strftime("%Y%m%d_%H%M%S_%f")
    for index in range(1000):
        name = stem if index == 0 else f"{stem}_{index:02d}"
        candidate = case_dir / name
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise DatingError(f"无法为 {case_id} 分配唯一工作目录")


def create_workflow_workspace(
    inputs: WorkflowInputs,
    output_root: Path,
    *,
    clock: Clock | None = None,
) -> WorkflowWorkspace:
    started = (clock or (lambda: datetime.now().astimezone()))()
    root = _allocate_root(output_root, inputs.case_id, started)
    source_dir = root / "source_copy"
    detection_work_dir = root / "detection_work"
    detection_preview_dir = root / "detection_preview"
    manual_revision_dir = root / "manual_revision"
    logs_dir = root / "logs"
    for directory in (
        source_dir,
        detection_work_dir,
        detection_preview_dir,
        manual_revision_dir,
        logs_dir,
    ):
        directory.mkdir()
    try:
        area_shp = copy_shapefile_set(inputs.area_shp, source_dir)
        crater_shp = copy_shapefile_set(inputs.crater_shp, source_dir)
    except Exception:
        # Preserve the allocated directory as failure evidence; never touch sources.
        raise
    return WorkflowWorkspace(
        root=root,
        source_dir=source_dir,
        detection_work_dir=detection_work_dir,
        detection_preview_dir=detection_preview_dir,
        manual_revision_dir=manual_revision_dir,
        logs_dir=logs_dir,
        area_shp=area_shp,
        crater_shp=crater_shp,
        image_tif=inputs.image_tif,
    )
