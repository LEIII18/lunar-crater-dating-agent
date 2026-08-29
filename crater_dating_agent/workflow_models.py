from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plotly.graph_objects import Figure
    from .pipeline_runner import DetectionSettings


class WorkflowRoute(str, Enum):
    AUTO_DETECT = "auto_detect"
    USE_EXISTING = "use_existing"


class WorkflowPhase(str, Enum):
    DETECTION_READY = "detection_ready"
    DETECTION_REVIEW = "detection_review"
    MANUAL_REVIEW = "manual_review"
    DATING_READY = "dating_ready"
    DATING_STARTED = "dating_started"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WorkflowRequest:
    area_shp: Path
    crater_shp: Path
    image_tif: Path


@dataclass(frozen=True)
class WorkflowInputs:
    case_id: str
    area_shp: Path
    crater_shp: Path
    image_tif: Path
    crater_count: int
    route: WorkflowRoute


@dataclass(frozen=True)
class WorkflowWorkspace:
    root: Path
    source_dir: Path
    detection_work_dir: Path
    detection_preview_dir: Path
    manual_revision_dir: Path
    logs_dir: Path
    area_shp: Path
    crater_shp: Path
    image_tif: Path


@dataclass(frozen=True)
class DetectionRunResult:
    crater_shp: Path
    crater_count: int
    log_path: Path
    argv: tuple[str, ...]


@dataclass(frozen=True)
class CraterStatistics:
    count: int
    at_least_one_km: int
    minimum_diameter_km: float | None
    maximum_diameter_km: float | None


@dataclass(frozen=True)
class OverlayPreview:
    png_path: Path
    figure: "Figure"
    width: int
    height: int


@dataclass(frozen=True)
class WorkflowState:
    schema_version: int
    case_id: str
    phase: WorkflowPhase
    route: WorkflowRoute
    workspace: WorkflowWorkspace
    settings: "DetectionSettings"
    state_path: Path
    input_crater_count: int
    current_crater_count: int
    automatic_crater_shp: Path | None
    manual_crater_shp: Path | None
    selected_crater_shp: Path | None
    automatic_preview_path: Path | None
    manual_preview_path: Path | None
    data_source: str | None
    started_at: str
    updated_at: str
    error_message: str | None = None
