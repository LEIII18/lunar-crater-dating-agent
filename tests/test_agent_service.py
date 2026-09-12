from __future__ import annotations

import json
import shlex
import struct
from pathlib import Path

import numpy as np
import pytest

from crater_dating_agent.agent_models import AgentRequest, RangeProposal, RawRangeCandidate, SessionPhase
from crater_dating_agent.agent_service import (
    analyze_session,
    complete_confirmed_session,
    continue_preparing_session,
    confirm_candidate,
    confirm_manual_range,
    prepare_agent_session,
    recover_interrupted_session,
    undo_last_step,
)
from crater_dating_agent.session_store import create_session, load_session, transition
from crater_dating_agent.models import DatingError
from crater_dating_agent.path_resolver import resolve_agent_inputs


def request(tmp_path: Path) -> AgentRequest:
    date = tmp_path / "date"
    date.mkdir()
    for stem, count in (("CRATER_SID9", 63), ("AREA_SID9", 1)):
        for suffix in (".shp", ".shx", ".prj"):
            (date / f"{stem}{suffix}").write_bytes(b"fixture")
        header = bytearray(32)
        header[4:8] = struct.pack("<I", count)
        (date / f"{stem}.dbf").write_bytes(header)
    image = tmp_path / "image.tif"
    image.write_bytes(b"image")
    return AgentRequest(date / "CRATER_SID9.shp", date / "AREA_SID9.shp", image, tmp_path / "out")


class FakeCount:
    area = 10.0
    perimeter = 4.0
    binned = {
        "d_min": np.array([0.06, 0.07, 0.08, 0.09, 0.10]),
        "d_max": np.array([0.07, 0.08, 0.09, 0.10, 0.20]),
        "d_mean": np.array([0.065, 0.075, 0.085, 0.095, 0.141]),
        "bin_width": np.array([0.01, 0.01, 0.01, 0.01, 0.10]),
        "n": np.array([20.0, 20.0, 10.0, 8.0, 5.0]),
        "n_event": np.array([20, 20, 10, 8, 5]),
        "ncum": np.array([63.0, 43.0, 23.0, 13.0, 5.0]),
    }

    def apply_binning(self, value):
        assert value == "pseudo-log"


def global_cli(argv: list[str]) -> None:
    args = shlex.split(Path(argv[1]).read_text(encoding="utf-8"))
    Path(args[args.index("-o") + 1]).with_suffix(".png").write_bytes(b"global")


def all_stage_cli(argv: list[str]) -> None:
    config = Path(argv[1])
    args = shlex.split(config.read_text(encoding="utf-8"))
    stem = Path(args[args.index("-o") + 1])
    stem.with_suffix(".png").write_bytes(b"plot")
    if "csv" in args:
        stem.with_suffix(".csv").write_text(
            "Name,Method,N,N_event,Age,Age-,Age+\n"
            "SID9,b-poisson,63,63,0.376,0.331,0.425\n",
            encoding="utf-8",
        )


class FakeClient:
    def analyze(self, session, registry, context):
        assert session.phase is SessionPhase.ANALYZING
        assert any(tool["function"]["name"] == "get_csfd_summary" for tool in registry.schemas_for(session.phase))
        return RangeProposal((RawRangeCandidate(0.06, 0.2, "high", "连续稳定", ()),), "测试", True)


class ThreeRangeClient:
    def analyze(self, session, registry, context):
        return RangeProposal(
            (
                RawRangeCandidate(0.06, 0.09, "medium", "较小直径对照", ()),
                RawRangeCandidate(0.07, 0.20, "high", "优先覆盖较大坑", ()),
                RawRangeCandidate(0.06, 0.20, "medium", "大坑端稳健性检查", ()),
            ),
            "优先比较较大直径区间",
            True,
        )


class WarningCandidateClient:
    def analyze(self, session, registry, context):
        return RangeProposal(
            (RawRangeCandidate(0.10, 0.20, "low", "低统计候选", ()),),
            "候选需要人工复核",
            True,
        )


def test_warning_candidate_is_retained_and_requires_explicit_override(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )

    analyzed = analyze_session(
        prepared.state_path, client=WarningCandidateClient(), preview_cli_main=all_stage_cli
    )

    candidates = json.loads(
        (analyzed.session_dir / "llm" / "range_candidates.json").read_text(encoding="utf-8")
    )["candidates"]
    assert analyzed.phase is SessionPhase.AWAITING_CONFIRMATION
    assert len(candidates) == 1
    assert candidates[0]["warnings"] == ["LOW_EVENT_COUNT", "LOW_OCCUPIED_BINS"]

    with pytest.raises(DatingError, match="统计警告"):
        confirm_candidate(analyzed.state_path, 1)

    confirmed = confirm_candidate(analyzed.state_path, 1, warning_override=True)
    assert confirmed.phase is SessionPhase.CONFIRMED


def test_prepare_analyze_and_confirm_are_separate_persisted_stages(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )

    assert prepared.phase is SessionPhase.OVERVIEW_READY
    assert (prepared.session_dir / "overview" / "SID9_global_csfd.png").read_bytes() == b"global"
    assert (prepared.session_dir / "overview" / "csfd_summary.json").is_file()
    assert not (prepared.session_dir / "confirmation.json").exists()


def test_inputs_validated_session_can_resume_global_overview(tmp_path: Path) -> None:
    session = create_session(
        resolve_agent_inputs(request(tmp_path)), tmp_path / "outputs"
    )
    session = transition(session, SessionPhase.INPUTS_VALIDATED)

    resumed = continue_preparing_session(
        session.state_path, cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )

    assert resumed.phase is SessionPhase.OVERVIEW_READY
    assert (resumed.session_dir / "overview" / "SID9_global_csfd.png").is_file()
    assert not list(resumed.session_dir.rglob("*_age_result.json"))

    analyzed = analyze_session(
        resumed.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )
    assert analyzed.phase is SessionPhase.AWAITING_CONFIRMATION
    candidates = json.loads((analyzed.session_dir / "llm" / "range_candidates.json").read_text(encoding="utf-8"))
    assert candidates["candidates"][0]["event_count"] == 63

    confirmed = confirm_candidate(analyzed.state_path, 1)
    assert confirmed.phase is SessionPhase.CONFIRMED
    assert load_session(confirmed.state_path).phase is SessionPhase.CONFIRMED


def test_analyze_generates_three_unconfirmed_candidate_previews(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )

    analyzed = analyze_session(
        prepared.state_path, client=ThreeRangeClient(), preview_cli_main=all_stage_cli
    )

    data = json.loads(
        (analyzed.session_dir / "llm" / "range_candidates.json").read_text(encoding="utf-8")
    )
    assert analyzed.phase is SessionPhase.AWAITING_CONFIRMATION
    assert len(data["candidates"]) == 3
    for index, candidate in enumerate(data["candidates"], 1):
        preview = candidate["preview"]
        assert preview["status"] == "unconfirmed_candidate_preview"
        assert preview["age_ga"] == 0.376
        assert Path(preview["plot_path"]).is_file()
        assert Path(preview["result_json_path"]).is_file()
        config = analyzed.session_dir / "previews" / f"candidate_{index}" / "SID9_dating.cs"
        text = config.read_text(encoding="utf-8")
        assert text.count("-p ") == 2
        assert "name=plot 2" in text
    assert not (analyzed.session_dir / "final").exists()


def test_final_directory_age_is_created_only_after_confirmation(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=all_stage_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )
    analyzed = analyze_session(
        prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )

    assert list((prepared.session_dir / "previews").rglob("*_age_result.json"))
    assert not (prepared.session_dir / "final").exists()
    confirmed = confirm_candidate(analyzed.state_path, 1)
    completed = complete_confirmed_session(confirmed.state_path, cli_main=all_stage_cli)

    assert completed.phase is SessionPhase.COMPLETED
    assert (completed.session_dir / "final" / "SID9_age_result.json").is_file()
    assert (completed.session_dir / "final" / "SID9_csfd.png").is_file()


def test_manual_range_confirmation_preserves_exact_user_endpoints(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )
    analyzed = analyze_session(
        prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )

    confirmed = confirm_manual_range(analyzed.state_path, 0.061, 0.199)

    record = json.loads(
        (confirmed.session_dir / "confirmation.json").read_text(encoding="utf-8")
    )
    assert confirmed.phase is SessionPhase.CONFIRMED
    assert record["range_km"] == [0.061, 0.199]


def test_api_failure_returns_session_to_resumable_overview_state(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )

    class FailingClient:
        def analyze(self, session, registry, context):
            raise DatingError("DeepSeek API 调用失败")

    with pytest.raises(DatingError, match="DeepSeek"):
        analyze_session(prepared.state_path, client=FailingClient())

    assert load_session(prepared.state_path).phase is SessionPhase.OVERVIEW_READY
    assert (prepared.session_dir / "overview" / "SID9_global_csfd.png").is_file()


def test_interrupted_analysis_can_be_recovered_to_overview(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )
    transition(prepared, SessionPhase.ANALYZING)

    recovered = recover_interrupted_session(prepared.state_path)

    assert recovered.phase is SessionPhase.OVERVIEW_READY
    events = [
        json.loads(line)
        for line in recovered.transcript_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == "session_recovered"
    assert events[-1]["from_phase"] == "analyzing"


def test_candidate_stage_and_completed_result_can_undo_to_previous_choice(
    tmp_path: Path,
) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )
    analyzed = analyze_session(
        prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )

    back_to_overview = undo_last_step(analyzed.state_path)
    assert back_to_overview.phase is SessionPhase.OVERVIEW_READY

    analyzed_again = analyze_session(
        prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )
    confirmed = confirm_candidate(analyzed_again.state_path, 1)
    completed = complete_confirmed_session(confirmed.state_path, cli_main=all_stage_cli)

    back_to_candidates = undo_last_step(completed.state_path)
    assert back_to_candidates.phase is SessionPhase.AWAITING_CONFIRMATION
    assert back_to_candidates.session_dir.joinpath("confirmation.json").is_file()
    assert back_to_candidates.session_dir.joinpath("final", "SID9_csfd.png").is_file()


def test_preview_failure_returns_to_overview_and_can_retry(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )

    def failing_preview_cli(argv):
        raise SystemExit(3)

    with pytest.raises(DatingError, match="Craterstats"):
        analyze_session(
            prepared.state_path, client=FakeClient(),
            preview_cli_main=failing_preview_cli,
        )

    assert load_session(prepared.state_path).phase is SessionPhase.OVERVIEW_READY
    retried = analyze_session(
        prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )
    assert retried.phase is SessionPhase.AWAITING_CONFIRMATION


def test_corrupt_summary_returns_session_to_resumable_overview(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )
    (prepared.session_dir / "overview" / "csfd_summary.json").write_text(
        "not json", encoding="utf-8"
    )

    with pytest.raises(DatingError, match="分析阶段"):
        analyze_session(
            prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
        )

    assert load_session(prepared.state_path).phase is SessionPhase.OVERVIEW_READY


@pytest.mark.parametrize("selection", [0, -1, 2])
def test_confirm_candidate_rejects_out_of_range_service_selection(
    tmp_path: Path, selection: int
) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )
    analyzed = analyze_session(
        prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )

    with pytest.raises(DatingError, match="候选编号"):
        confirm_candidate(analyzed.state_path, selection)


def test_failed_final_dating_can_retry_from_confirmed_session(tmp_path: Path) -> None:
    prepared = prepare_agent_session(
        request(tmp_path), cli_main=global_cli,
        cratercount_factory=lambda crater, area: FakeCount(),
    )
    analyzed = analyze_session(
        prepared.state_path, client=FakeClient(), preview_cli_main=all_stage_cli
    )
    confirmed = confirm_candidate(analyzed.state_path, 1)

    def failing_final_cli(argv):
        raise SystemExit(3)

    with pytest.raises(DatingError, match="Craterstats"):
        complete_confirmed_session(confirmed.state_path, cli_main=failing_final_cli)
    assert load_session(confirmed.state_path).phase is SessionPhase.CONFIRMED

    completed = complete_confirmed_session(
        confirmed.state_path, cli_main=all_stage_cli
    )
    assert completed.phase is SessionPhase.COMPLETED


def test_craterstats_prepare_failure_is_persisted_as_failed_session(tmp_path: Path) -> None:
    agent_request = request(tmp_path)

    def failing_cli(argv):
        raise SystemExit(3)

    with pytest.raises(DatingError, match="退出码 3"):
        prepare_agent_session(
            agent_request, cli_main=failing_cli,
            cratercount_factory=lambda crater, area: FakeCount(),
        )

    state_path = next((agent_request.output_dir / "SID9").glob("*/session_state.json"))
    failed = load_session(state_path)
    assert failed.phase is SessionPhase.FAILED
    assert failed.error_type == "DatingError"
