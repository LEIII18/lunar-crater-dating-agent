from __future__ import annotations

import json
from pathlib import Path

import pytest

from crater_dating_agent.agent_models import CsfdBin, CsfdSummary
from crater_dating_agent.models import DatingError
from crater_dating_agent.range_candidates import (
    load_agent_config,
    parse_proposal_json,
    validate_candidates,
    validate_manual_range,
)


FIXTURE = Path(__file__).parent / "fixtures" / "deepseek_range_response.json"


def summary() -> CsfdSummary:
    rows = (
        (0.05, 0.06, 5),
        (0.06, 0.07, 30),
        (0.07, 0.08, 30),
        (0.08, 0.10, 30),
        (0.10, 0.20, 150),
        (0.20, 0.30, 2),
    )
    bins = tuple(
        CsfdBin(a, b, (a * b) ** 0.5, float(n), n, float(n), 1.0, 0.1)
        for a, b, n in rows
    )
    return CsfdSummary(79.899, 55.5, 247, 0.05, 0.30, bins)


def test_candidates_snap_to_real_boundaries_deduplicate_and_recount() -> None:
    proposal = parse_proposal_json(FIXTURE.read_text(encoding="utf-8"))

    candidates = validate_candidates(proposal, summary(), load_agent_config())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert (candidate.range_min_km, candidate.range_max_km) == (0.06, 0.20)
    assert candidate.event_count == 240
    assert candidate.occupied_bin_count == 4
    assert candidate.warnings == ()


def test_empty_candidate_list_is_valid_for_manual_review() -> None:
    proposal = parse_proposal_json(
        json.dumps(
            {
                "candidates": [],
                "overall_observation": "没有可靠区间",
                "needs_human_review": True,
            }
        )
    )

    assert validate_candidates(proposal, summary(), load_agent_config()) == ()


def test_parser_accepts_deepseek_candidate_interval_aliases() -> None:
    proposal = parse_proposal_json(
        json.dumps(
            {
                "candidate_intervals": [
                    {
                        "d_min_km": 0.03,
                        "d_max_km": 0.10,
                        "rationale": "中部区间分箱连续且计数充足",
                        "risks": ["端部计数下降"],
                    }
                ],
                "notes": "需要人工检查小直径端完整性",
                "needs_human_review": True,
            },
            ensure_ascii=False,
        )
    )

    assert len(proposal.candidates) == 1
    candidate = proposal.candidates[0]
    assert (candidate.range_min_km, candidate.range_max_km) == (0.03, 0.10)
    assert candidate.confidence == "medium"
    assert candidate.reason == "中部区间分箱连续且计数充足"
    assert candidate.risks == ("端部计数下降",)
    assert proposal.overall_observation == "需要人工检查小直径端完整性"


def test_low_statistics_produce_both_deterministic_warnings() -> None:
    proposal = parse_proposal_json(
        json.dumps(
            {
                "candidates": [{
                    "range_min_km": 0.20,
                    "range_max_km": 0.30,
                    "confidence": "low",
                    "reason": "测试低统计区间",
                    "risks": []
                }],
                "overall_observation": "测试",
                "needs_human_review": True,
            }
        )
    )

    candidate = validate_candidates(proposal, summary(), load_agent_config())[0]

    assert candidate.event_count == 2
    assert candidate.occupied_bin_count == 1
    assert candidate.warnings == ("LOW_EVENT_COUNT", "LOW_OCCUPIED_BINS")


def test_strict_automatic_candidates_drop_low_statistics_and_bin_gaps() -> None:
    proposal = parse_proposal_json(json.dumps({
        "candidates": [
            {"range_min_km": 0.20, "range_max_km": 0.30, "confidence": "low",
             "reason": "低统计", "risks": []},
            {"range_min_km": 0.08, "range_max_km": 0.30, "confidence": "medium",
             "reason": "跨空分箱", "risks": []},
            {"range_min_km": 0.06, "range_max_km": 0.10, "confidence": "high",
             "reason": "连续可靠", "risks": []},
        ],
        "overall_observation": "测试",
        "needs_human_review": True,
    }))

    original = summary()
    gapped = CsfdSummary(
        original.area_km2, original.perimeter_km, original.total_event_count,
        original.diameter_min_km, original.diameter_max_km,
        tuple(item for item in original.bins if item.d_min_km != 0.10),
    )
    candidates = validate_candidates(proposal, gapped, load_agent_config(), strict=True)

    assert [(item.range_min_km, item.range_max_km) for item in candidates] == [
        (0.06, 0.10)
    ]


def test_manual_range_preserves_craterstats_endpoints_across_empty_bins() -> None:
    rows = (
        (0.8, 0.9, 7),
        (0.9, 1.0, 7),
        (1.0, 1.1, 3),
        (7.0, 8.0, 1),
        (10.0, 11.0, 1),
    )
    gapped = CsfdSummary(
        2236.8,
        410.8,
        19,
        0.05,
        20.0,
        tuple(
            CsfdBin(a, b, (a * b) ** 0.5, float(n), n, float(n), 1.0, 0.1)
            for a, b, n in rows
        ),
    )

    candidate = validate_manual_range(0.8, 10.0, gapped, load_agent_config())

    assert (candidate.range_min_km, candidate.range_max_km) == (0.8, 10.0)
    assert candidate.event_count == 18
    assert candidate.occupied_bin_count == 4
    assert candidate.warnings == ("LOW_EVENT_COUNT", "NONCONTIGUOUS_BINS")


@pytest.mark.parametrize(
    "change",
    [
        {"needs_human_review": False},
        {"candidates": [{"range_min_km": "NaN", "range_max_km": 0.2,
                         "confidence": "high", "reason": "x", "risks": []}]},
        {"candidates": [{"range_min_km": 0.2, "range_max_km": 0.1,
                         "confidence": "high", "reason": "x", "risks": []}]},
        {"candidates": [{"range_min_km": 0.06, "range_max_km": 0.2,
                         "confidence": "certain", "reason": "x", "risks": []}]},
    ],
)
def test_proposal_parser_rejects_invalid_contract(change: dict[str, object]) -> None:
    payload = {
        "candidates": [],
        "overall_observation": "测试",
        "needs_human_review": True,
    }
    payload.update(change)

    with pytest.raises(DatingError, match="候选|人工复核|置信度|数值"):
        parse_proposal_json(json.dumps(payload))
