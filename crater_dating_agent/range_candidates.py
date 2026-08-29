from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib.resources import files

import yaml

from .agent_models import (
    CsfdSummary,
    RangeProposal,
    RawRangeCandidate,
    ValidatedRangeCandidate,
)
from .models import DatingError


@dataclass(frozen=True)
class RangeAgentConfig:
    schema_version: int
    default_model: str
    default_base_url: str
    min_event_count: int
    min_occupied_bins: int
    proposal_repair_attempts: int
    api_timeout_seconds: float
    api_max_retries: int


def load_agent_config() -> RangeAgentConfig:
    resource = files("crater_dating_agent").joinpath("configs/range_agent.yaml")
    try:
        data = yaml.safe_load(resource.read_text(encoding="utf-8"))
        config = RangeAgentConfig(
            schema_version=int(data["schema_version"]),
            default_model=str(data["default_model"]),
            default_base_url=str(data["default_base_url"]),
            min_event_count=int(data["min_event_count"]),
            min_occupied_bins=int(data["min_occupied_bins"]),
            proposal_repair_attempts=int(data["proposal_repair_attempts"]),
            api_timeout_seconds=float(data["api_timeout_seconds"]),
            api_max_retries=int(data["api_max_retries"]),
        )
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise DatingError(f"range 智能体配置无效：{exc}") from exc
    if (
        config.schema_version != 1
        or config.min_event_count < 1
        or config.min_occupied_bins < 1
        or config.proposal_repair_attempts < 0
        or not math.isfinite(config.api_timeout_seconds)
        or config.api_timeout_seconds <= 0
        or config.api_max_retries < 0
    ):
        raise DatingError("range 智能体配置数值无效")
    return config


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DatingError(f"候选 {field} 必须为数值")
    result = float(value)
    if not math.isfinite(result):
        raise DatingError(f"候选 {field} 必须为有限数值")
    return result


def parse_proposal_json(text: str) -> RangeProposal:
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise TypeError("顶层必须是对象")
        if payload.get("needs_human_review") is not True:
            raise DatingError("候选结果必须要求人工复核")
        raw_candidates = payload.get("candidates", payload.get("candidate_intervals"))
        if not isinstance(raw_candidates, list) or len(raw_candidates) > 3:
            raise DatingError("候选数量必须为 0–3")
        observation = payload.get("overall_observation", payload.get("notes"))
        if not isinstance(observation, str):
            raise DatingError("候选总体观察必须是文本")
        candidates: list[RawRangeCandidate] = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                raise DatingError("候选必须是对象")
            lower = _finite_number(
                item.get("range_min_km", item.get("d_min_km")), "下限"
            )
            upper = _finite_number(
                item.get("range_max_km", item.get("d_max_km")), "上限"
            )
            if lower <= 0 or upper <= lower:
                raise DatingError("候选数值范围无效")
            confidence = item.get("confidence", "medium")
            if confidence not in {"high", "medium", "low"}:
                raise DatingError("候选置信度无效")
            reason = item.get("reason", item.get("rationale"))
            risks = item.get("risks")
            if not isinstance(reason, str) or not reason.strip():
                raise DatingError("候选理由必须是非空文本")
            if not isinstance(risks, list) or not all(isinstance(x, str) for x in risks):
                raise DatingError("候选风险必须是文本列表")
            candidates.append(
                RawRangeCandidate(lower, upper, confidence, reason, tuple(risks))
            )
        return RangeProposal(tuple(candidates), observation, True)
    except DatingError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise DatingError(f"候选 JSON 无效：{exc}") from exc


def _snap_range(lower: float, upper: float, summary: CsfdSummary) -> tuple[float, float] | None:
    if lower < summary.diameter_min_km or upper > summary.diameter_max_km:
        return None
    lower_bin = next(
        (item for item in summary.bins if item.d_min_km <= lower < item.d_max_km),
        None,
    )
    upper_bin = next(
        (item for item in summary.bins if item.d_min_km < upper <= item.d_max_km),
        None,
    )
    if lower_bin is None or upper_bin is None:
        return None
    return lower_bin.d_min_km, upper_bin.d_max_km


def _range_warnings(
    selected: tuple,
    config: RangeAgentConfig,
) -> tuple[str, ...]:
    event_count = sum(item.event_count for item in selected)
    warnings: list[str] = []
    if event_count < config.min_event_count:
        warnings.append("LOW_EVENT_COUNT")
    if len(selected) < config.min_occupied_bins:
        warnings.append("LOW_OCCUPIED_BINS")
    if any(
        not math.isclose(left.d_max_km, right.d_min_km, rel_tol=1e-9, abs_tol=1e-12)
        for left, right in zip(selected, selected[1:])
    ):
        warnings.append("NONCONTIGUOUS_BINS")
    return tuple(warnings)


def validate_manual_range(
    lower: float,
    upper: float,
    summary: CsfdSummary,
    config: RangeAgentConfig,
) -> ValidatedRangeCandidate:
    lower = _finite_number(lower, "下限")
    upper = _finite_number(upper, "上限")
    if lower <= 0 or upper <= lower:
        raise DatingError("人工输入区间数值无效")
    selected = tuple(
        item for item in summary.bins if lower < item.d_mean_km < upper
    )
    if not selected:
        raise DatingError("人工输入区间内没有有效撞击坑分箱")
    return ValidatedRangeCandidate(
        lower,
        upper,
        "low",
        "人工输入区间",
        (),
        sum(item.event_count for item in selected),
        len(selected),
        _range_warnings(selected, config),
    )


def validate_candidates(
    proposal: RangeProposal,
    summary: CsfdSummary,
    config: RangeAgentConfig,
    *,
    strict: bool = False,
) -> tuple[ValidatedRangeCandidate, ...]:
    result: list[ValidatedRangeCandidate] = []
    seen: set[tuple[float, float]] = set()
    for raw in proposal.candidates:
        normalized = _snap_range(raw.range_min_km, raw.range_max_km, summary)
        if normalized is None or normalized in seen:
            continue
        lower, upper = normalized
        selected = tuple(
            item
            for item in summary.bins
            if item.d_min_km >= lower and item.d_max_km <= upper
        )
        if not selected:
            continue
        event_count = sum(item.event_count for item in selected)
        warnings = _range_warnings(selected, config)
        if strict and warnings:
            continue
        result.append(
            ValidatedRangeCandidate(
                lower,
                upper,
                raw.confidence,
                raw.reason,
                raw.risks,
                event_count,
                len(selected),
                warnings,
            )
        )
        seen.add(normalized)
    return tuple(result)
