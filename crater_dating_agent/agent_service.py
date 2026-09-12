from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

from .agent_models import (
    AgentRequest,
    AgentSession,
    CsfdBin,
    CsfdSummary,
    SessionPhase,
    ValidatedRangeCandidate,
)
from .confirmation import verify_confirmation, write_confirmation
from .deepseek_client import DeepSeekRangeClient
from .models import DatingError, DatingRequest, ResolvedInputs
from .overview import CratercountFactory, extract_csfd_summary, generate_global_overview
from .path_resolver import resolve_agent_inputs
from .range_candidates import (
    load_agent_config,
    validate_candidates,
    validate_manual_range,
)
from .session_store import (
    append_transcript,
    create_session,
    create_session_at,
    load_session,
    restore_session,
    transition,
)
from .service import run_single_dating
from .tool_registry import ToolDefinition, ToolRegistry


EMPTY_SCHEMA = {
    "type": "object", "properties": {}, "required": [], "additionalProperties": False
}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _inputs(session: AgentSession) -> ResolvedInputs:
    return ResolvedInputs(
        session.case_id, session.crater_shp, session.area_shp, session.image_tif,
        session.input_crater_count,
    )


def _summary_from_file(path: Path) -> CsfdSummary:
    data = json.loads(path.read_text(encoding="utf-8"))
    bins = tuple(CsfdBin(**item) for item in data.pop("bins"))
    return CsfdSummary(**data, bins=bins)


def prepare_agent_session(
    request: AgentRequest,
    *,
    output_root: Path | None = None,
    session_dir: Path | None = None,
    cli_main=None,
    cratercount_factory: CratercountFactory | None = None,
    clock=None,
) -> AgentSession:
    inputs = resolve_agent_inputs(request)
    root = Path(output_root or request.output_dir or Path(__file__).resolve().parent.parent / "outputs")
    session = (
        create_session_at(inputs, session_dir, clock=clock)
        if session_dir is not None
        else create_session(inputs, root, clock=clock)
    )
    session = transition(session, SessionPhase.INPUTS_VALIDATED, clock=clock)
    return continue_preparing_session(
        session.state_path,
        cli_main=cli_main,
        cratercount_factory=cratercount_factory,
        clock=clock,
    )


def continue_preparing_session(
    session_path: Path,
    *,
    cli_main=None,
    cratercount_factory: CratercountFactory | None = None,
    clock=None,
) -> AgentSession:
    session = load_session(session_path)
    if session.phase is not SessionPhase.INPUTS_VALIDATED:
        raise DatingError("只有已验证输入的会话可以生成全局 CSFD 图")
    inputs = _inputs(session)
    try:
        overview = generate_global_overview(
            inputs, session.session_dir / "overview", cli_main=cli_main
        )
        summary = extract_csfd_summary(
            inputs, cratercount_factory=cratercount_factory
        )
        _write_json(overview.summary_path, asdict(summary))
        return transition(session, SessionPhase.OVERVIEW_READY, clock=clock)
    except Exception as exc:
        transition(session, SessionPhase.FAILED, error=exc, clock=clock)
        raise


def _registry(session: AgentSession, summary_payload: dict[str, object]) -> ToolRegistry:
    registry = ToolRegistry()
    definitions = (
        ("validate_case", "验证输入", frozenset({SessionPhase.CREATED}), lambda a, c: {"valid": True}),
        ("generate_global_csfd", "生成全局图", frozenset({SessionPhase.INPUTS_VALIDATED}), lambda a, c: {"ready": True}),
        ("get_csfd_summary", "读取结构化 CSFD 数据", frozenset({SessionPhase.ANALYZING}), lambda a, c: summary_payload),
        ("get_session_state", "读取会话状态", frozenset(SessionPhase), lambda a, c: {"phase": session.phase.value}),
        ("run_confirmed_dating", "执行确认后的定年", frozenset({SessionPhase.CONFIRMED}), lambda a, c: {"confirmed": True}),
    )
    for name, description, phases, executor in definitions:
        registry.register(ToolDefinition(name, description, EMPTY_SCHEMA, phases, executor))
    return registry


def analyze_session(
    session_path: Path,
    *,
    client: DeepSeekRangeClient,
    preview_cli_main=None,
    clock=None,
) -> AgentSession:
    session = load_session(session_path)
    if session.phase is not SessionPhase.OVERVIEW_READY:
        raise DatingError("只有全局图准备完成的会话可以开始分析")
    session = transition(session, SessionPhase.ANALYZING, clock=clock)
    summary_path = session.session_dir / "overview" / "csfd_summary.json"
    try:
        summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        proposal = client.analyze(session, _registry(session, summary_payload), None)
        candidates = validate_candidates(
            proposal, _summary_from_file(summary_path), load_agent_config(), strict=False
        )
        preview_root = (session.session_dir / "previews").resolve()
        if preview_root.exists():
            if preview_root.parent != session.session_dir.resolve():
                raise DatingError("候选预览目录超出当前会话")
            try:
                shutil.rmtree(preview_root)
            except OSError as exc:
                raise DatingError(f"无法清理旧候选预览：{exc}") from exc
        candidate_payloads: list[dict[str, object]] = []
        for index, candidate in enumerate(candidates, 1):
            preview_dir = preview_root / f"candidate_{index}"
            preview_request = DatingRequest(
                session.crater_shp,
                session.area_shp,
                session.image_tif,
                candidate.range_min_km,
                candidate.range_max_km,
                preview_dir,
            )
            result = run_single_dating(
                preview_request,
                run_dir=preview_dir,
                cli_main=preview_cli_main,
                clock=clock,
            )
            payload = asdict(candidate)
            payload["preview"] = {
                "status": "unconfirmed_candidate_preview",
                "plot_path": str(result.plot_path),
                "result_json_path": str(result.result_json_path),
                "age_ga": result.age.age_ga,
                "age_lower_ga": result.age.age_lower_ga,
                "age_upper_ga": result.age.age_upper_ga,
            }
            candidate_payloads.append(payload)
        _write_json(
            session.session_dir / "llm" / "range_candidates.json",
            {"overall_observation": proposal.overall_observation,
             "candidates": candidate_payloads},
        )
    except BaseException as exc:
        if not isinstance(exc, Exception):
            append_transcript(
                session,
                {
                    "event": "analysis_interrupted",
                    "error_type": type(exc).__name__,
                },
            )
            transition(session, SessionPhase.OVERVIEW_READY, clock=clock)
            raise
        failure = (
            exc if isinstance(exc, DatingError)
            else DatingError(f"智能体分析阶段失败：{type(exc).__name__}: {exc}")
        )
        append_transcript(
            session,
            {"event": "analysis_error", "error_type": type(failure).__name__,
             "error_message": str(failure)},
        )
        transition(session, SessionPhase.OVERVIEW_READY, clock=clock)
        if failure is exc:
            raise
        raise failure from exc
    return transition(session, SessionPhase.AWAITING_CONFIRMATION, clock=clock)


def recover_interrupted_session(
    session_path: Path,
    *,
    clock=None,
) -> AgentSession:
    session = load_session(session_path)
    if session.phase is SessionPhase.ANALYZING:
        target = SessionPhase.OVERVIEW_READY
    elif session.phase is SessionPhase.FAILED:
        if (session.session_dir / "confirmation.json").is_file():
            target = SessionPhase.CONFIRMED
        else:
            target = SessionPhase.OVERVIEW_READY
    else:
        raise DatingError("当前会话不处于可恢复的中断或失败状态")
    if target is SessionPhase.OVERVIEW_READY:
        required = (
            session.session_dir / "overview" / "csfd_summary.json",
            session.session_dir / "overview" / f"{session.case_id}_global_csfd.png",
        )
        if not all(path.is_file() for path in required):
            raise DatingError("当前失败会话缺少完整全局图，不能从分析阶段恢复")
    recovered = restore_session(session, target, clock=clock)
    append_transcript(
        recovered,
        {
            "event": "session_recovered",
            "from_phase": session.phase.value,
            "to_phase": target.value,
        },
    )
    return recovered


def undo_last_step(session_path: Path, *, clock=None) -> AgentSession:
    session = load_session(session_path)
    if session.phase is SessionPhase.ANALYZING:
        return recover_interrupted_session(session_path, clock=clock)
    targets = {
        SessionPhase.AWAITING_CONFIRMATION: SessionPhase.OVERVIEW_READY,
        SessionPhase.CONFIRMED: SessionPhase.AWAITING_CONFIRMATION,
        SessionPhase.COMPLETED: SessionPhase.AWAITING_CONFIRMATION,
    }
    target = targets.get(session.phase)
    if target is None:
        raise DatingError("当前阶段没有可撤回的上一步")
    if target is SessionPhase.AWAITING_CONFIRMATION and not (
        session.session_dir / "llm" / "range_candidates.json"
    ).is_file():
        raise DatingError("候选区间记录不存在，不能撤回到候选选择阶段")
    restored = restore_session(session, target, clock=clock)
    append_transcript(
        restored,
        {
            "event": "step_undone",
            "from_phase": session.phase.value,
            "to_phase": target.value,
        },
    )
    return restored


def confirm_candidate(
    session_path: Path,
    selection: int,
    *,
    warning_override: bool = False,
    clock=None,
) -> AgentSession:
    session = load_session(session_path)
    data = json.loads((session.session_dir / "llm" / "range_candidates.json").read_text(encoding="utf-8"))
    try:
        if not isinstance(selection, int) or isinstance(selection, bool):
            raise IndexError
        if not 1 <= selection <= len(data["candidates"]):
            raise IndexError
        candidate_data = dict(data["candidates"][selection - 1])
        candidate_data.pop("preview", None)
        candidate = ValidatedRangeCandidate(**candidate_data)
    except (IndexError, KeyError, TypeError) as exc:
        raise DatingError("候选编号无效") from exc
    write_confirmation(
        session, candidate, f"candidate_{selection}",
        warning_override=warning_override, clock=clock,
    )
    return load_session(session.state_path)


def preview_manual_range(
    session_path: Path,
    lower: float,
    upper: float,
) -> ValidatedRangeCandidate:
    session = load_session(session_path)
    summary = _summary_from_file(session.session_dir / "overview" / "csfd_summary.json")
    return validate_manual_range(lower, upper, summary, load_agent_config())


def confirm_manual_range(
    session_path: Path,
    lower: float,
    upper: float,
    *,
    warning_override: bool = False,
    clock=None,
) -> AgentSession:
    session = load_session(session_path)
    candidate = preview_manual_range(session_path, lower, upper)
    write_confirmation(
        session, candidate, "manual", warning_override=warning_override, clock=clock
    )
    return load_session(session.state_path)


def cancel_session(session_path: Path, *, clock=None) -> AgentSession:
    session = load_session(session_path)
    return transition(session, SessionPhase.CANCELLED, clock=clock)


def complete_confirmed_session(
    session_path: Path,
    *,
    cli_main=None,
    clock=None,
) -> AgentSession:
    session = load_session(session_path)
    confirmation_path = session.session_dir / "confirmation.json"
    try:
        confirmation_data = json.loads(confirmation_path.read_text(encoding="utf-8"))
        requested_range = tuple(float(value) for value in confirmation_data["range_km"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DatingError(f"无法读取人工确认区间：{exc}") from exc
    inputs = _inputs(session)
    verify_confirmation(session, inputs, requested_range)
    request = DatingRequest(
        inputs.crater_shp,
        inputs.area_shp,
        inputs.image_tif,
        requested_range[0],
        requested_range[1],
        session.session_dir / "final",
    )
    final_dir = (session.session_dir / "final").resolve()
    if final_dir.exists():
        if final_dir.parent != session.session_dir.resolve():
            raise DatingError("最终定年目录超出当前会话")
        try:
            shutil.rmtree(final_dir)
        except OSError as exc:
            raise DatingError(f"无法清理失败的最终定年目录：{exc}") from exc
    run_single_dating(
        request,
        run_dir=final_dir,
        cli_main=cli_main,
        clock=clock,
    )
    return transition(session, SessionPhase.COMPLETED, clock=clock)
