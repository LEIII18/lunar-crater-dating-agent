from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from crater_dating_agent.agent_models import SessionPhase
from crater_dating_agent.models import DatingError, ResolvedInputs
from crater_dating_agent.session_store import (
    append_transcript,
    create_session,
    create_session_at,
    load_session,
    transition,
)


def resolved_inputs(tmp_path: Path) -> ResolvedInputs:
    date_dir = tmp_path / "date"
    date_dir.mkdir()
    crater = date_dir / "CRATER_SID9.shp"
    area = date_dir / "AREA_SID9.shp"
    image = tmp_path / "3M_DOM" / "63_61E8_08N.tif"
    image.parent.mkdir()
    crater.write_bytes(b"crater")
    area.write_bytes(b"area")
    image.write_bytes(b"image")
    return ResolvedInputs("SID9", crater.resolve(), area.resolve(), image.resolve(), 1545)


def fixed_clock() -> datetime:
    return datetime(2026, 8, 24, 21, 0, 0).astimezone()


def test_session_is_atomic_and_timezone_aware(tmp_path: Path) -> None:
    session = create_session(resolved_inputs(tmp_path), tmp_path / "outputs", clock=fixed_clock)

    loaded = load_session(session.state_path)

    assert loaded.phase is SessionPhase.CREATED
    assert loaded.session_id == "20260824_210000_000000"
    assert loaded.started_at.utcoffset() is not None
    assert loaded.input_crater_count == 1545
    assert not session.state_path.with_suffix(".tmp").exists()
    payload = json.loads(session.state_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1


def test_sessions_with_the_same_clock_get_unique_directories(tmp_path: Path) -> None:
    inputs = resolved_inputs(tmp_path)

    first = create_session(inputs, tmp_path / "outputs", clock=fixed_clock)
    second = create_session(inputs, tmp_path / "outputs", clock=fixed_clock)

    assert first.session_id == "20260824_210000_000000"
    assert second.session_id == "20260824_210000_000000_01"
    assert first.session_dir != second.session_dir


def test_create_session_at_uses_preallocated_workflow_directory(tmp_path: Path) -> None:
    inputs = resolved_inputs(tmp_path)
    workflow_dir = tmp_path / "outputs" / "SID9" / "preallocated"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "source_copy").mkdir()

    session = create_session_at(inputs, workflow_dir, clock=fixed_clock)

    assert session.session_dir == workflow_dir.resolve()
    assert session.state_path == workflow_dir.resolve() / "session_state.json"
    assert session.transcript_path.is_file()
    assert load_session(session.state_path).session_dir == workflow_dir.resolve()


def test_create_session_at_refuses_existing_session_state(tmp_path: Path) -> None:
    inputs = resolved_inputs(tmp_path)
    workflow_dir = tmp_path / "outputs" / "SID9" / "preallocated"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "session_state.json").write_text("{}", encoding="utf-8")

    with pytest.raises(DatingError, match="已存在"):
        create_session_at(inputs, workflow_dir, clock=fixed_clock)


def test_load_session_rejects_embedded_paths_pointing_to_another_session(
    tmp_path: Path,
) -> None:
    inputs = resolved_inputs(tmp_path)
    first = create_session(inputs, tmp_path / "outputs", clock=fixed_clock)
    second = create_session(inputs, tmp_path / "outputs", clock=fixed_clock)
    payload = json.loads(first.state_path.read_text(encoding="utf-8"))
    payload["session_dir"] = str(second.session_dir)
    payload["state_path"] = str(second.state_path)
    payload["transcript_path"] = str(second.transcript_path)
    first.state_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatingError, match="实际路径|会话目录"):
        load_session(first.state_path)


def test_illegal_transition_cannot_skip_human_confirmation(tmp_path: Path) -> None:
    session = create_session(resolved_inputs(tmp_path), tmp_path / "outputs", clock=fixed_clock)

    with pytest.raises(DatingError, match="非法状态转换"):
        transition(session, SessionPhase.COMPLETED, clock=fixed_clock)

    assert load_session(session.state_path).phase is SessionPhase.CREATED


def test_legal_transition_is_persisted(tmp_path: Path) -> None:
    session = create_session(resolved_inputs(tmp_path), tmp_path / "outputs", clock=fixed_clock)

    updated = transition(session, SessionPhase.INPUTS_VALIDATED, clock=fixed_clock)

    assert updated.phase is SessionPhase.INPUTS_VALIDATED
    assert load_session(session.state_path).phase is SessionPhase.INPUTS_VALIDATED


def test_transcript_appends_one_json_event_per_line(tmp_path: Path) -> None:
    session = create_session(resolved_inputs(tmp_path), tmp_path / "outputs", clock=fixed_clock)

    append_transcript(session, {"event": "tool_call", "tool": "validate_case"})
    append_transcript(session, {"event": "tool_result", "ok": True})

    events = [json.loads(line) for line in session.transcript_path.read_text(encoding="utf-8").splitlines()]
    assert events == [
        {"event": "tool_call", "tool": "validate_case"},
        {"event": "tool_result", "ok": True},
    ]
