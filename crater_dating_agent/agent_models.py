from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class SessionPhase(str, Enum):
    CREATED = "created"
    INPUTS_VALIDATED = "inputs_validated"
    OVERVIEW_READY = "overview_ready"
    ANALYZING = "analyzing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentRequest:
    crater_shp: Path
    area_shp: Path
    image_tif: Path
    output_dir: Path | None = None


@dataclass(frozen=True)
class GlobalOverview:
    plot_path: Path
    config_path: Path
    log_path: Path
    summary_path: Path


@dataclass(frozen=True)
class CsfdBin:
    d_min_km: float
    d_max_km: float
    d_mean_km: float
    weighted_count: float
    event_count: int
    cumulative_count: float
    differential_density: float
    uncertainty: float


@dataclass(frozen=True)
class CsfdSummary:
    area_km2: float
    perimeter_km: float
    total_event_count: int
    diameter_min_km: float
    diameter_max_km: float
    bins: tuple[CsfdBin, ...]


@dataclass(frozen=True)
class RawRangeCandidate:
    range_min_km: float
    range_max_km: float
    confidence: str
    reason: str
    risks: tuple[str, ...]


@dataclass(frozen=True)
class RangeProposal:
    candidates: tuple[RawRangeCandidate, ...]
    overall_observation: str
    needs_human_review: bool


@dataclass(frozen=True)
class ValidatedRangeCandidate:
    range_min_km: float
    range_max_km: float
    confidence: str
    reason: str
    risks: tuple[str, ...]
    event_count: int
    occupied_bin_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class HumanConfirmation:
    session_id: str
    range_min_km: float
    range_max_km: float
    method: str
    warning_override: bool
    confirmed_at: datetime


@dataclass(frozen=True)
class AgentSession:
    schema_version: int
    session_id: str
    case_id: str
    phase: SessionPhase
    session_dir: Path
    state_path: Path
    transcript_path: Path
    crater_shp: Path
    area_shp: Path
    image_tif: Path
    input_crater_count: int
    started_at: datetime
    updated_at: datetime
    error_type: str | None = None
    error_message: str | None = None
