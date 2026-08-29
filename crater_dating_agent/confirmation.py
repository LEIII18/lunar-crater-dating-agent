from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from .agent_models import AgentSession, HumanConfirmation, SessionPhase, ValidatedRangeCandidate
from .models import DatingError, ResolvedInputs
from .session_store import transition


Clock = Callable[[], datetime]


def _aware_now(clock: Clock | None) -> datetime:
    value = (clock or (lambda: datetime.now().astimezone()))()
    return value if value.tzinfo is not None else value.astimezone()


def _fingerprints(inputs: ResolvedInputs) -> list[dict[str, object]]:
    result = []
    for path in (inputs.crater_shp, inputs.area_shp, inputs.image_tif):
        stat = path.stat()
        result.append({"path": str(path.resolve()), "size": stat.st_size, "modified_ns": stat.st_mtime_ns})
    return result


def _session_inputs(session: AgentSession) -> ResolvedInputs:
    return ResolvedInputs(
        session.case_id, session.crater_shp, session.area_shp, session.image_tif,
        session.input_crater_count,
    )


def write_confirmation(
    session: AgentSession,
    candidate: ValidatedRangeCandidate,
    method: str,
    *,
    warning_override: bool,
    clock: Clock | None = None,
) -> HumanConfirmation:
    if session.phase is not SessionPhase.AWAITING_CONFIRMATION:
        raise DatingError("当前会话尚未进入人工确认阶段")
    if candidate.warnings and not warning_override:
        raise DatingError("候选区间存在统计警告，需要明确覆盖警告")
    confirmed_at = _aware_now(clock)
    record = HumanConfirmation(
        session.session_id,
        candidate.range_min_km,
        candidate.range_max_km,
        method,
        warning_override,
        confirmed_at,
    )
    payload = {
        "schema_version": 1,
        "session_id": session.session_id,
        "range_km": [record.range_min_km, record.range_max_km],
        "method": method,
        "warnings": list(candidate.warnings),
        "warning_override": warning_override,
        "confirmed_at": confirmed_at.isoformat(),
        "input_files": _fingerprints(_session_inputs(session)),
    }
    path = session.session_dir / "confirmation.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    transition(session, SessionPhase.CONFIRMED, clock=lambda: confirmed_at)
    return record


def verify_confirmation(
    session: AgentSession,
    inputs: ResolvedInputs,
    requested_range: tuple[float, float],
) -> HumanConfirmation:
    path = session.session_dir / "confirmation.json"
    if session.phase is not SessionPhase.CONFIRMED or not path.is_file():
        raise DatingError("当前会话尚未人工确认")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["session_id"] != session.session_id:
            raise DatingError("人工确认不属于当前会话")
        if data["input_files"] != _fingerprints(inputs):
            raise DatingError("人工确认后输入文件已发生变化")
        stored_range = tuple(float(value) for value in data["range_km"])
        if stored_range != tuple(requested_range):
            raise DatingError("人工确认区间与请求区间不一致")
        confirmed_at = datetime.fromisoformat(data["confirmed_at"])
        if confirmed_at.tzinfo is None:
            raise DatingError("人工确认时间缺少时区")
        return HumanConfirmation(
            session.session_id,
            stored_range[0], stored_range[1], data["method"],
            bool(data["warning_override"]), confirmed_at,
        )
    except DatingError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DatingError(f"人工确认记录无效：{exc}") from exc
