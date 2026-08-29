from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class DatingError(RuntimeError):
    """A user-actionable dating workflow error."""


@dataclass(frozen=True)
class DatingRequest:
    crater_shp: Path
    area_shp: Path
    image_tif: Path
    range_min_km: float
    range_max_km: float
    output_dir: Path | None = None


@dataclass(frozen=True)
class ResolvedInputs:
    case_id: str
    crater_shp: Path
    area_shp: Path
    image_tif: Path
    crater_count: int


@dataclass(frozen=True)
class InvocationResult:
    config_path: Path
    plot_path: Path
    csv_path: Path
    log_path: Path
    stdout: str
    stderr: str


@dataclass(frozen=True)
class AgeEstimate:
    crater_count: int
    age_ga: float
    age_lower_ga: float
    age_upper_ga: float
    age_minus_ga: float
    age_plus_ga: float


@dataclass(frozen=True)
class DatingResult:
    case_id: str
    output_dir: Path
    config_path: Path
    plot_path: Path
    csv_path: Path
    log_path: Path
    result_json_path: Path
    manifest_path: Path
    age: AgeEstimate
