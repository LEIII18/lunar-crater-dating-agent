from __future__ import annotations

import json
from pathlib import Path

import pytest

from crater_dating_agent.agent_models import AgentRequest, RangeProposal, RawRangeCandidate, SessionPhase
from crater_dating_agent.agent_service import (
    analyze_session,
    complete_confirmed_session,
    confirm_candidate,
    prepare_agent_session,
)


ROOT = Path(r"E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N")


class FixedRangeClient:
    def analyze(self, session, registry, context):
        summary = registry.execute("get_csfd_summary", {}, context, session.phase)
        assert summary["total_event_count"] == 1545
        return RangeProposal(
            (
                RawRangeCandidate(0.03, 0.10, "medium", "SID9 小直径对照", ()),
                RawRangeCandidate(0.04, 0.15, "high", "SID9 较大坑优先", ()),
                RawRangeCandidate(0.05, 0.10, "medium", "SID9 稳健区间", ()),
            ),
            "离线集成测试",
            True,
        )


@pytest.mark.integration
def test_real_sid9_requires_confirmation_between_global_and_final_plots(tmp_path: Path) -> None:
    request = AgentRequest(
        ROOT / "date" / "CRATER_SID9.shp",
        ROOT / "date" / "AREA_SID9.shp",
        ROOT / "3M_DOM" / "63_61E8_08N.tif",
        tmp_path,
    )

    prepared = prepare_agent_session(request)

    global_plot = prepared.session_dir / "overview" / "SID9_global_csfd.png"
    assert prepared.phase is SessionPhase.OVERVIEW_READY
    assert global_plot.is_file() and global_plot.stat().st_size > 0
    assert not list(prepared.session_dir.rglob("*_age_result.json"))
    global_config = (prepared.session_dir / "overview" / "SID9_global.cs").read_text(encoding="utf-8")
    assert global_config.count("-p ") == 1
    assert "type=data" in global_config
    assert "range=" not in global_config

    analyzed = analyze_session(prepared.state_path, client=FixedRangeClient())
    assert len(list((prepared.session_dir / "previews_zero").rglob("*_age_result.json"))) == 3
    assert len(list((prepared.session_dir / "previews_zero").rglob("*_csfd.png"))) == 3
    assert not (prepared.session_dir / "final").exists()
    confirmed = confirm_candidate(analyzed.state_path, 1)
    completed = complete_confirmed_session(confirmed.state_path)

    result = json.loads((completed.session_dir / "final" / "SID9_age_result.json").read_text(encoding="utf-8"))
    assert completed.phase is SessionPhase.COMPLETED
    assert result["crater_count"] > 0
    assert result["age_ga"] > 0
    final_config = (completed.session_dir / "final" / "SID9_dating.cs").read_text(encoding="utf-8")
    assert final_config.count("-p ") == 2
    assert "range=[0.03,0.1]" in final_config
    assert "name=plot 2" in final_config
