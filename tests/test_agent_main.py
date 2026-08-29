from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from crater_dating_agent.agent_main import AgentCliServices, main
import crater_dating_agent.agent_main as agent_main_module
from crater_dating_agent.agent_models import SessionPhase
from crater_dating_agent.models import DatingError


def fake_services(tmp_path: Path):
    session_dir = tmp_path / "session"
    (session_dir / "llm").mkdir(parents=True)
    (session_dir / "overview").mkdir()
    (session_dir / "overview" / "SID9_global_csfd.png").write_bytes(b"png")
    (session_dir / "llm" / "range_candidates.json").write_text(json.dumps({
        "overall_observation": "D ≥ 1 km 区间样本稀疏，需要谨慎解释",
        "candidates": [{
            "range_min_km": 0.06, "range_max_km": 0.2,
            "confidence": "high", "reason": "连续稳定", "risks": [],
            "event_count": 63, "occupied_bin_count": 5, "warnings": [],
            "preview": {
                "status": "unconfirmed_candidate_preview",
                "plot_path": str(session_dir / "previews" / "candidate_1" / "SID9_csfd.png"),
                "result_json_path": str(session_dir / "previews" / "candidate_1" / "SID9_age_result.json"),
                "age_ga": 0.376, "age_lower_ga": 0.331, "age_upper_ga": 0.425,
            },
        }]
    }), encoding="utf-8")
    state = session_dir / "session_state.json"
    state.write_text("{}", encoding="utf-8")
    session = SimpleNamespace(session_dir=session_dir, state_path=state,
                              phase=SessionPhase.AWAITING_CONFIRMATION)
    calls = []
    return SimpleNamespace(
        start=lambda request: session,
        resume=lambda path: session,
        confirm=lambda path, selection, warning_override=False: calls.append(("confirm", selection)) or session,
        preview_manual=lambda path, lower, upper: SimpleNamespace(
            range_min_km=lower, range_max_km=upper, warnings=()
        ),
        confirm_manual=lambda path, lower, upper, warning_override=False: calls.append(("manual", lower, upper)) or session,
        cancel=lambda path: calls.append(("cancel",)) or session,
        complete=lambda path: calls.append(("complete",)) or session,
        calls=calls,
    )


def argv(tmp_path: Path) -> list[str]:
    return [
        "--crater-shp", str(tmp_path / "CRATER_SID9.shp"),
        "--area-shp", str(tmp_path / "AREA_SID9.shp"),
        "--image-tif", str(tmp_path / "x.tif"),
    ]


def test_terminal_selects_candidate_then_requires_final_yes(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    answers = iter(["1", "y"])
    output = []

    code = main(argv(tmp_path), input_fn=lambda prompt: next(answers),
                output_fn=output.append, services=services)

    assert code == 0
    assert services.calls == [("confirm", 1), ("complete",)]
    assert any("全局 CSFD 图" in line for line in output)
    assert any("最终定年完成" in line for line in output)


def test_terminal_can_cancel_without_final_dating(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    code = main(argv(tmp_path), input_fn=lambda prompt: "q",
                output_fn=lambda text: None, services=services)
    assert code == 0
    assert services.calls == [("cancel",)]


def test_terminal_shows_candidate_preview_before_dynamic_choice_prompt(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    output = []
    prompts = []

    def answer(prompt: str) -> str:
        prompts.append(prompt)
        return "q"

    code = main(argv(tmp_path), input_fn=answer, output_fn=output.append, services=services)

    assert code == 0
    assert any("总体观察" in line and "D ≥ 1 km" in line for line in output)
    assert any("候选预览，未经人工确认" in line and "0.376" in line for line in output)
    assert any("SID9_csfd.png" in line for line in output)
    assert prompts == ["请选择 1，输入 e 手工设置，输入 q 取消："]


def test_terminal_accepts_manual_range(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    answers = iter(["e", "0.07", "0.18", "y"])
    code = main(argv(tmp_path), input_fn=lambda prompt: next(answers),
                output_fn=lambda text: None, services=services)
    assert code == 0
    assert services.calls == [("manual", 0.07, 0.18), ("complete",)]


def test_declining_final_confirmation_writes_no_confirmation(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    answers = iter(["e", "0.07", "0.18", "n"])

    code = main(argv(tmp_path), input_fn=lambda prompt: next(answers),
                output_fn=lambda text: None, services=services)

    assert code == 0
    assert services.calls == []


def test_api_failure_still_shows_resumable_session_and_global_plot(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    services.start = lambda request: SimpleNamespace(
        session_dir=services.resume(None).session_dir,
        state_path=services.resume(None).state_path,
        phase=SessionPhase.OVERVIEW_READY,
    )
    services.analyze = lambda path: (_ for _ in ()).throw(DatingError("API unavailable"))
    output = []

    code = main(argv(tmp_path), input_fn=lambda prompt: "q",
                output_fn=output.append, services=services)

    assert code == 2
    assert any("全局 CSFD 图" in line for line in output)
    assert any("session_state.json" in line for line in output)


def test_low_statistics_manual_range_requires_warning_override(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    services.preview_manual = lambda path, lower, upper: SimpleNamespace(
        range_min_km=0.2, range_max_km=0.3,
        warnings=("LOW_EVENT_COUNT", "LOW_OCCUPIED_BINS"),
    )
    original = services.confirm_manual
    services.confirm_manual = lambda path, lower, upper, warning_override=False: (
        services.calls.append(("override", warning_override)) or
        original(path, lower, upper, warning_override=warning_override)
    )
    answers = iter(["e", "0.2", "0.3", "y", "y"])

    code = main(argv(tmp_path), input_fn=lambda prompt: next(answers),
                output_fn=lambda text: None, services=services)

    assert code == 0
    assert ("override", True) in services.calls


def test_production_services_forward_deepseek_progress_to_terminal(
    tmp_path: Path, monkeypatch
) -> None:
    output = []
    expected = object()

    class FakeClient:
        def __init__(self, settings, *, progress_callback):
            self.progress_callback = progress_callback

    monkeypatch.setattr(agent_main_module.DeepSeekSettings, "from_env", lambda: object())
    monkeypatch.setattr(agent_main_module, "DeepSeekRangeClient", FakeClient)
    monkeypatch.setattr(
        agent_main_module,
        "analyze_session",
        lambda path, client: client.progress_callback("正在调用 DeepSeek……") or expected,
    )

    services = AgentCliServices(output_fn=output.append)

    assert services.analyze(tmp_path / "session_state.json") is expected
    assert output == ["正在调用 DeepSeek……"]


def test_confirmed_resume_retries_final_without_reasking_for_range(tmp_path: Path) -> None:
    services = fake_services(tmp_path)
    confirmed = SimpleNamespace(
        session_dir=services.resume(None).session_dir,
        state_path=services.resume(None).state_path,
        phase=SessionPhase.CONFIRMED,
    )
    services.resume = lambda path: confirmed
    output = []

    code = main(
        ["--resume-session", str(confirmed.state_path)],
        input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError(prompt)),
        output_fn=output.append,
        services=services,
    )

    assert code == 0
    assert services.calls == [("complete",)]
    assert "最终定年完成" in output
