from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from crater_dating_agent.agent_models import SessionPhase, ValidatedRangeCandidate
from crater_dating_agent.confirmation import verify_confirmation, write_confirmation
from crater_dating_agent.models import DatingError, ResolvedInputs
from crater_dating_agent.session_store import create_session, load_session, transition


def setup(tmp_path: Path):
    crater, area, image = (tmp_path / name for name in ("CRATER_SID9.shp", "AREA_SID9.shp", "x.tif"))
    for path, data in ((crater, b"c"), (area, b"a"), (image, b"i")):
        path.write_bytes(data)
    inputs = ResolvedInputs("SID9", crater.resolve(), area.resolve(), image.resolve(), 63)
    session = create_session(inputs, tmp_path / "out")
    session = transition(session, SessionPhase.INPUTS_VALIDATED)
    session = transition(session, SessionPhase.OVERVIEW_READY)
    session = transition(session, SessionPhase.ANALYZING)
    session = transition(session, SessionPhase.AWAITING_CONFIRMATION)
    candidate = ValidatedRangeCandidate(0.06, 0.2, "high", "稳定", (), 63, 5, ())
    return inputs, session, candidate


def test_final_gate_rejects_unconfirmed_session(tmp_path: Path) -> None:
    inputs, session, _ = setup(tmp_path)
    with pytest.raises(DatingError, match="尚未人工确认"):
        verify_confirmation(session, inputs, (0.06, 0.2))


def test_matching_confirmation_passes_and_changes_session_phase(tmp_path: Path) -> None:
    inputs, session, candidate = setup(tmp_path)
    written = write_confirmation(
        session, candidate, "candidate_1", warning_override=False,
        clock=lambda: datetime(2026, 8, 24, 22, 0).astimezone(),
    )
    confirmed = load_session(session.state_path)

    record = verify_confirmation(confirmed, inputs, (0.06, 0.2))

    assert confirmed.phase is SessionPhase.CONFIRMED
    assert written == record
    assert record.range_min_km == 0.06
    assert record.confirmed_at.utcoffset() is not None


def test_confirmation_rejects_changed_input_or_range(tmp_path: Path) -> None:
    inputs, session, candidate = setup(tmp_path)
    write_confirmation(session, candidate, "candidate_1", warning_override=False)
    confirmed = load_session(session.state_path)

    inputs.crater_shp.write_bytes(b"changed")
    with pytest.raises(DatingError, match="输入文件"):
        verify_confirmation(confirmed, inputs, (0.06, 0.2))
    with pytest.raises(DatingError, match="输入文件|区间"):
        verify_confirmation(confirmed, inputs, (0.07, 0.2))


def test_warning_candidate_requires_explicit_override(tmp_path: Path) -> None:
    _, session, candidate = setup(tmp_path)
    warned = ValidatedRangeCandidate(**{**candidate.__dict__, "warnings": ("LOW_EVENT_COUNT",)})

    with pytest.raises(DatingError, match="警告"):
        write_confirmation(session, warned, "manual", warning_override=False)
