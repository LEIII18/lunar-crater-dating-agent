from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .agent_models import AgentSession, SessionPhase
from .models import DatingError, ResolvedInputs


Clock = Callable[[], datetime]
SCHEMA_VERSION = 1

_ALLOWED: dict[SessionPhase, frozenset[SessionPhase]] = {
    SessionPhase.CREATED: frozenset(
        {SessionPhase.INPUTS_VALIDATED, SessionPhase.CANCELLED, SessionPhase.FAILED}
    ),
    SessionPhase.INPUTS_VALIDATED: frozenset(
        {SessionPhase.OVERVIEW_READY, SessionPhase.CANCELLED, SessionPhase.FAILED}
    ),
    SessionPhase.OVERVIEW_READY: frozenset(
        {SessionPhase.ANALYZING, SessionPhase.CANCELLED, SessionPhase.FAILED}
    ),
    SessionPhase.ANALYZING: frozenset(
        {
            SessionPhase.AWAITING_CONFIRMATION,
            SessionPhase.OVERVIEW_READY,
            SessionPhase.CANCELLED,
            SessionPhase.FAILED,
        }
    ),
    SessionPhase.AWAITING_CONFIRMATION: frozenset(
        {SessionPhase.CONFIRMED, SessionPhase.CANCELLED, SessionPhase.FAILED}
    ),
    SessionPhase.CONFIRMED: frozenset(
        {SessionPhase.COMPLETED, SessionPhase.CANCELLED, SessionPhase.FAILED}
    ),
    SessionPhase.COMPLETED: frozenset(),
    SessionPhase.CANCELLED: frozenset(),
    SessionPhase.FAILED: frozenset(),
}

_RESTORE_ALLOWED: dict[SessionPhase, frozenset[SessionPhase]] = {
    SessionPhase.ANALYZING: frozenset({SessionPhase.OVERVIEW_READY}),
    SessionPhase.FAILED: frozenset(
        {SessionPhase.OVERVIEW_READY, SessionPhase.CONFIRMED}
    ),
    SessionPhase.AWAITING_CONFIRMATION: frozenset({SessionPhase.OVERVIEW_READY}),
    SessionPhase.CONFIRMED: frozenset({SessionPhase.AWAITING_CONFIRMATION}),
    SessionPhase.COMPLETED: frozenset({SessionPhase.AWAITING_CONFIRMATION}),
}


def _now(clock: Clock | None) -> datetime:
    value = (clock or (lambda: datetime.now().astimezone()))()
    return value if value.tzinfo is not None else value.astimezone()


def _payload(session: AgentSession) -> dict[str, object]:
    return {
        "schema_version": session.schema_version,
        "session_id": session.session_id,
        "case_id": session.case_id,
        "phase": session.phase.value,
        "session_dir": str(session.session_dir),
        "state_path": str(session.state_path),
        "transcript_path": str(session.transcript_path),
        "inputs": {
            "crater_shp": str(session.crater_shp),
            "area_shp": str(session.area_shp),
            "image_tif": str(session.image_tif),
        },
        "input_crater_count": session.input_crater_count,
        "started_at": session.started_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "error_type": session.error_type,
        "error_message": session.error_message,
    }


def save_session(session: AgentSession) -> None:
    temporary = session.state_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(_payload(session), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(session.state_path)


def _allocate_session_dir(output_root: Path, case_id: str, started: datetime) -> Path:
    case_dir = (output_root / case_id).resolve()
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
    raise DatingError(f"无法为 {case_id} 分配唯一会话目录")


def create_session(
    inputs: ResolvedInputs, output_root: Path, *, clock: Clock | None = None
) -> AgentSession:
    started = _now(clock)
    session_dir = _allocate_session_dir(Path(output_root), inputs.case_id, started)
    transcript_path = session_dir / "llm" / "tool_transcript.jsonl"
    transcript_path.parent.mkdir()
    transcript_path.write_text("", encoding="utf-8")
    session = AgentSession(
        schema_version=SCHEMA_VERSION,
        session_id=session_dir.name,
        case_id=inputs.case_id,
        phase=SessionPhase.CREATED,
        session_dir=session_dir,
        state_path=session_dir / "session_state.json",
        transcript_path=transcript_path,
        crater_shp=inputs.crater_shp,
        area_shp=inputs.area_shp,
        image_tif=inputs.image_tif,
        input_crater_count=inputs.crater_count,
        started_at=started,
        updated_at=started,
    )
    save_session(session)
    return session


def create_session_at(
    inputs: ResolvedInputs, session_dir: Path, *, clock: Clock | None = None
) -> AgentSession:
    requested = Path(session_dir)
    if requested.is_symlink():
        raise DatingError("预分配会话目录不能是符号链接")
    try:
        actual_dir = requested.resolve(strict=True)
    except OSError as exc:
        raise DatingError(f"预分配会话目录不存在：{requested}") from exc
    if not actual_dir.is_dir():
        raise DatingError(f"预分配会话路径不是目录：{actual_dir}")
    state_path = actual_dir / "session_state.json"
    if state_path.exists():
        raise DatingError(f"预分配目录已存在会话状态：{state_path}")
    transcript_path = actual_dir / "llm" / "tool_transcript.jsonl"
    if transcript_path.parent.exists():
        raise DatingError(f"预分配目录已存在 llm 目录：{transcript_path.parent}")
    transcript_path.parent.mkdir()
    transcript_path.write_text("", encoding="utf-8")
    started = _now(clock)
    session = AgentSession(
        schema_version=SCHEMA_VERSION,
        session_id=actual_dir.name,
        case_id=inputs.case_id,
        phase=SessionPhase.CREATED,
        session_dir=actual_dir,
        state_path=state_path,
        transcript_path=transcript_path,
        crater_shp=inputs.crater_shp,
        area_shp=inputs.area_shp,
        image_tif=inputs.image_tif,
        input_crater_count=inputs.crater_count,
        started_at=started,
        updated_at=started,
    )
    save_session(session)
    return session


def _parse_aware(value: str, field: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise DatingError(f"会话字段 {field} 缺少时区")
    return parsed


def load_session(path: Path) -> AgentSession:
    try:
        requested_path = Path(path)
        if requested_path.is_symlink():
            raise DatingError("会话状态文件不能是符号链接")
        actual_state_path = requested_path.resolve(strict=True)
        actual_session_dir = actual_state_path.parent
        data = json.loads(actual_state_path.read_text(encoding="utf-8"))
        if data["schema_version"] != SCHEMA_VERSION:
            raise DatingError(f"不支持的会话 schema：{data['schema_version']}")
        declared_state_path = Path(data["state_path"]).resolve(strict=True)
        declared_session_dir = Path(data["session_dir"]).resolve(strict=True)
        if declared_state_path != actual_state_path:
            raise DatingError("会话状态内嵌路径与实际路径不一致")
        if declared_session_dir != actual_session_dir:
            raise DatingError("会话目录与实际 session_state.json 目录不一致")
        expected_transcript = (
            actual_session_dir / "llm" / "tool_transcript.jsonl"
        ).resolve(strict=True)
        declared_transcript = Path(data["transcript_path"]).resolve(strict=True)
        if declared_transcript != expected_transcript:
            raise DatingError("会话 transcript 路径超出当前会话")
        inputs = data["inputs"]
        return AgentSession(
            schema_version=data["schema_version"],
            session_id=data["session_id"],
            case_id=data["case_id"],
            phase=SessionPhase(data["phase"]),
            session_dir=actual_session_dir,
            state_path=actual_state_path,
            transcript_path=expected_transcript,
            crater_shp=Path(inputs["crater_shp"]),
            area_shp=Path(inputs["area_shp"]),
            image_tif=Path(inputs["image_tif"]),
            input_crater_count=int(data["input_crater_count"]),
            started_at=_parse_aware(data["started_at"], "started_at"),
            updated_at=_parse_aware(data["updated_at"], "updated_at"),
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
        )
    except DatingError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DatingError(f"无法读取会话状态：{exc}") from exc


def transition(
    session: AgentSession,
    target: SessionPhase,
    *,
    error: Exception | None = None,
    clock: Clock | None = None,
) -> AgentSession:
    if target not in _ALLOWED[session.phase]:
        raise DatingError(f"非法状态转换：{session.phase.value} -> {target.value}")
    updated = replace(
        session,
        phase=target,
        updated_at=_now(clock),
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
    )
    save_session(updated)
    return updated


def restore_session(
    session: AgentSession,
    target: SessionPhase,
    *,
    clock: Clock | None = None,
) -> AgentSession:
    if target not in _RESTORE_ALLOWED.get(session.phase, frozenset()):
        raise DatingError(f"不允许恢复状态：{session.phase.value} -> {target.value}")
    updated = replace(
        session,
        phase=target,
        updated_at=_now(clock),
        error_type=None,
        error_message=None,
    )
    save_session(updated)
    return updated


def append_transcript(session: AgentSession, event: dict[str, object]) -> None:
    with session.transcript_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
