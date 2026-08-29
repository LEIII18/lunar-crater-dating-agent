from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from crater_dating_agent.agent_models import SessionPhase
from crater_dating_agent.agent_service import (
    analyze_session,
    complete_confirmed_session,
    confirm_candidate,
    confirm_manual_range,
    continue_preparing_session,
    recover_interrupted_session,
    undo_last_step,
)
from crater_dating_agent.deepseek_client import DeepSeekRangeClient, DeepSeekSettings
from crater_dating_agent.i18n import Language, tr
from crater_dating_agent.models import DatingError
from crater_dating_agent.overlay_preview import render_overlay_preview
from crater_dating_agent.pipeline_runner import DetectionSettings
from crater_dating_agent.session_store import load_session
from crater_dating_agent.workflow_models import WorkflowPhase, WorkflowRequest
from crater_dating_agent.workflow_inputs import read_crater_statistics
from crater_dating_agent.workflow_service import (
    accept_automatic_result,
    accept_manual_revision,
    import_manual_revision,
    load_workflow_state,
    run_automatic_detection,
    start_dating_session,
    start_workflow,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_local_path(value: str) -> Path:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    return Path(cleaned)


def _workflow_state_path(value: str | Path) -> Path:
    path = parse_local_path(str(value))
    return path / "workflow_state.json" if path.is_dir() else path


def _restore_web_task(value: str | Path) -> None:
    state = load_workflow_state(_workflow_state_path(value))
    st.session_state.workflow_state = state
    session_path = state.workspace.root / "session_state.json"
    if session_path.is_file():
        st.session_state.agent_session = load_session(session_path)
    else:
        st.session_state.pop("agent_session", None)
    st.query_params["task"] = str(state.state_path)


def _language() -> Language:
    choice = st.radio(
        "语言 / Language", ["中文", "English"], horizontal=True,
        label_visibility="collapsed", key="language_choice",
    )
    return Language.EN if choice == "English" else Language.ZH


def _error(exc: Exception) -> None:
    st.error(str(exc))


def _source_label(source: str | None, language: Language) -> str:
    return tr(f"source_{source}", language) if source else "—"


def _settings(language: Language) -> tuple[DetectionSettings, Path]:
    defaults = DetectionSettings.from_env()
    with st.expander(tr("advanced_settings", language)):
        arcpy = st.text_input(tr("arcpy_python", language), str(defaults.arcpy_python))
        model_python = st.text_input(
            tr("model_python", language), str(defaults.model_python)
        )
        model_dir = st.text_input(tr("model_dir", language), str(defaults.model_dir))
        output_root = st.text_input(
            tr("output_root", language), str(PROJECT_ROOT / "outputs")
        )
    return (
        DetectionSettings(
            arcpy_python=parse_local_path(arcpy),
            model_python=parse_local_path(model_python),
            model_dir=parse_local_path(model_dir),
            pipeline_script=defaults.pipeline_script,
        ),
        parse_local_path(output_root),
    )


def _overlay(state, language: Language, *, manual: bool) -> None:
    crater = state.manual_crater_shp if manual else state.automatic_crater_shp
    if crater is None:
        return
    title = tr("manual_review" if manual else "automatic_review", language)
    st.subheader(title)
    output = state.workspace.detection_preview_dir / (
        "manual_overlay.png" if manual else "automatic_overlay.png"
    )
    preview = render_overlay_preview(
        state.workspace.image_tif, state.workspace.area_shp, crater,
        output, state.case_id,
    )
    st.plotly_chart(preview.figure, width="stretch", key=f"overlay_{manual}")
    statistics = read_crater_statistics(crater)
    columns = st.columns(3)
    columns[0].metric(tr("crater_count", language), statistics.count)
    columns[1].metric(tr("one_km_count", language), statistics.at_least_one_km)
    diameter_span = (
        "—" if statistics.minimum_diameter_km is None
        else f"{statistics.minimum_diameter_km:g}–{statistics.maximum_diameter_km:g}"
    )
    columns[2].metric(tr("diameter_span", language), diameter_span)


def _prepare_dating(state, language: Language) -> None:
    st.subheader(tr("dating", language))
    st.write(
        f"{tr('source', language)}: **{_source_label(state.data_source, language)}**"
    )
    if "agent_session" not in st.session_state:
        if st.button(tr("start_dating", language), type="primary"):
            try:
                with st.spinner(tr("start_dating", language)):
                    st.session_state.agent_session = start_dating_session(state)
                st.rerun()
            except Exception as exc:
                _error(exc)
        return
    session = st.session_state.agent_session
    try:
        session = load_session(session.state_path)
        st.session_state.agent_session = session
    except Exception as exc:
        _error(exc)
        return
    global_plot = session.session_dir / "overview" / f"{session.case_id}_global_csfd.png"
    if global_plot.is_file():
        st.caption(tr("global_plot", language))
        st.image(str(global_plot))
    _agent_stage(session, language)


def _agent_stage(session, language: Language) -> None:
    st.caption(
        f"{tr('session_phase', language)}: `{session.phase.value}`"
    )
    if session.phase in {SessionPhase.ANALYZING, SessionPhase.FAILED}:
        st.warning(
            tr(
                "analysis_interrupted" if session.phase is SessionPhase.ANALYZING
                else "session_failed",
                language,
            )
        )
        if session.error_message:
            st.error(session.error_message)
        if st.button(tr("recover_session", language), type="primary"):
            try:
                st.session_state.agent_session = recover_interrupted_session(
                    session.state_path
                )
                st.rerun()
            except Exception as exc:
                _error(exc)
        return
    if session.phase is SessionPhase.INPUTS_VALIDATED:
        if st.button(tr("start_dating", language), type="primary"):
            try:
                with st.spinner(tr("start_dating", language)):
                    st.session_state.agent_session = continue_preparing_session(
                        session.state_path
                    )
                st.rerun()
            except Exception as exc:
                _error(exc)
        return
    if session.phase in {
        SessionPhase.AWAITING_CONFIRMATION,
        SessionPhase.CONFIRMED,
        SessionPhase.COMPLETED,
    }:
        if st.button(tr("undo_step", language)):
            try:
                st.session_state.agent_session = undo_last_step(session.state_path)
                st.rerun()
            except Exception as exc:
                _error(exc)
    if session.phase is SessionPhase.OVERVIEW_READY:
        env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        api_key = env_key or st.text_input(
            tr("api_key", language), type="password", key="deepseek_api_key"
        )
        if st.button(tr("analyze_ranges", language), type="primary"):
            if not api_key:
                _error(DatingError("DEEPSEEK_API_KEY is required"))
                return
            try:
                progress = st.empty()
                settings = DeepSeekSettings.from_env(
                    {"DEEPSEEK_API_KEY": api_key,
                     "DEEPSEEK_MODEL": "deepseek-v4-flash-vision-exp"}
                )
                client = DeepSeekRangeClient(
                    settings, response_language=language,
                    progress_callback=progress.info,
                )
                updated = analyze_session(session.state_path, client=client)
                st.session_state.agent_session = updated
                st.rerun()
            except Exception as exc:
                _error(exc)
        return
    if session.phase is SessionPhase.AWAITING_CONFIRMATION:
        _candidate_stage(session, language)
    elif session.phase is SessionPhase.CONFIRMED:
        _complete(session, language)
    elif session.phase is SessionPhase.COMPLETED:
        _final_result(session, language)


def _candidate_stage(session, language: Language) -> None:
    path = session.session_dir / "llm" / "range_candidates.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    st.info(data.get("overall_observation", ""))
    for index, candidate in enumerate(data.get("candidates", []), 1):
        with st.container(border=True):
            st.subheader(tr("candidate", language, index=index))
            st.write(
                f"{tr('range_km', language)}: "
                f"{candidate['range_min_km']:g}–{candidate['range_max_km']:g}"
            )
            preview = candidate.get("preview", {})
            if preview.get("plot_path"):
                st.image(preview["plot_path"])
            if "age_ga" in preview:
                st.write(f"{tr('age_ga', language)}: {preview['age_ga']:.4g}")
            st.write(f"{tr('reason', language)}: {candidate.get('reason', '')}")
            risks = candidate.get("risks", []) + candidate.get("warnings", [])
            if risks:
                st.warning(f"{tr('risks', language)}: " + "; ".join(risks))
            override = st.checkbox(
                tr("warning_override", language), key=f"override_{index}"
            ) if candidate.get("warnings") else False
            if st.button(
                tr("confirm_candidate", language, index=index), key=f"candidate_{index}"
            ):
                try:
                    confirmed = confirm_candidate(
                        session.state_path, index, warning_override=override
                    )
                    st.session_state.agent_session = complete_confirmed_session(
                        confirmed.state_path
                    )
                    st.rerun()
                except Exception as exc:
                    _error(exc)
    with st.expander(tr("manual_range", language)):
        lower = st.number_input(tr("lower", language), min_value=0.0, value=1.0)
        upper = st.number_input(tr("upper", language), min_value=0.0, value=10.0)
        override = st.checkbox(tr("warning_override", language), key="manual_override")
        if st.button(tr("generate_final", language), key="manual_final"):
            try:
                confirmed = confirm_manual_range(
                    session.state_path, lower, upper, warning_override=override
                )
                st.session_state.agent_session = complete_confirmed_session(
                    confirmed.state_path
                )
                st.rerun()
            except Exception as exc:
                _error(exc)


def _complete(session, language: Language) -> None:
    if st.button(tr("generate_final", language), type="primary"):
        try:
            st.session_state.agent_session = complete_confirmed_session(
                session.state_path
            )
            st.rerun()
        except Exception as exc:
            _error(exc)


def _final_result(session, language: Language) -> None:
    st.success(tr("completed", language))
    st.subheader(tr("final_result", language))
    plot = session.session_dir / "final" / f"{session.case_id}_csfd.png"
    result = session.session_dir / "final" / f"{session.case_id}_age_result.json"
    if plot.is_file():
        st.image(str(plot))
    if result.is_file():
        st.json(json.loads(result.read_text(encoding="utf-8")))
    st.code(str(session.session_dir / "final"))


def render_app() -> None:
    st.set_page_config(page_title="Crater Dating Agent", layout="wide")
    language = _language()
    st.title(tr("page_title", language))
    st.header(tr("new_task", language))
    settings, output_root = _settings(language)
    area = st.text_input(tr("area_path", language), key="area_path")
    crater = st.text_input(tr("crater_path", language), key="crater_path")
    image = st.text_input(tr("image_path", language), key="image_path")
    if st.button(tr("validate_inputs", language), type="primary"):
        try:
            state = start_workflow(
                WorkflowRequest(
                    parse_local_path(area),
                    parse_local_path(crater),
                    parse_local_path(image),
                ),
                settings, output_root,
            )
            st.session_state.workflow_state = state
            st.session_state.pop("agent_session", None)
            st.session_state.pop("show_manual", None)
            st.query_params["task"] = str(state.state_path)
            st.rerun()
        except Exception as exc:
            _error(exc)
    query_task = st.query_params.get("task", "")
    with st.expander(tr("resume_task", language)):
        resume_path = st.text_input(
            "workflow_state.json",
            value=str(query_task),
            key="resume_workflow_path",
        )
        if st.button(tr("resume_task", language), key="resume_task_button"):
            try:
                _restore_web_task(resume_path)
                st.rerun()
            except Exception as exc:
                _error(exc)
    if "workflow_state" not in st.session_state and query_task:
        try:
            _restore_web_task(query_task)
        except Exception as exc:
            _error(exc)
    state = st.session_state.get("workflow_state")
    if state is None:
        return
    st.success(tr("status_ready", language))
    cols = st.columns(3)
    cols[0].metric(tr("case_id", language), state.case_id)
    cols[1].metric(tr("crater_count", language), state.current_crater_count)
    cols[2].write(f"**{tr('task_dir', language)}**\n\n{state.workspace.root}")
    if state.phase is WorkflowPhase.DETECTION_READY:
        st.info(tr("empty_crater_route", language))
        st.warning(tr("detection_interruption_warning", language))
        if st.button(tr("start_detection", language), type="primary"):
            lines: list[str] = []
            log = st.empty()
            try:
                def on_line(line: str) -> None:
                    lines.append(line)
                    log.code("\n".join(lines[-30:]))
                st.session_state.workflow_state = run_automatic_detection(
                    state, on_line=on_line
                )
                st.rerun()
            except Exception as exc:
                _error(exc)
    elif state.phase is WorkflowPhase.DETECTION_REVIEW:
        _overlay(state, language, manual=False)
        left, right = st.columns(2)
        if left.button(tr("accept_automatic", language), type="primary"):
            try:
                st.session_state.workflow_state = accept_automatic_result(state)
                st.rerun()
            except Exception as exc:
                _error(exc)
        if right.button(tr("revise_automatic", language)):
            st.session_state.show_manual = True
        if st.session_state.get("show_manual"):
            manual_path = st.text_input(
                tr("manual_revision_path", language, case_id=state.case_id),
                key="manual_path",
            )
            if st.button(tr("validate_manual", language), type="primary"):
                try:
                    st.session_state.workflow_state = import_manual_revision(
                        state, parse_local_path(manual_path)
                    )
                    st.rerun()
                except Exception as exc:
                    _error(exc)
    elif state.phase is WorkflowPhase.MANUAL_REVIEW:
        _overlay(state, language, manual=True)
        if st.button(tr("accept_manual", language), type="primary"):
            try:
                st.session_state.workflow_state = accept_manual_revision(state)
                st.rerun()
            except Exception as exc:
                _error(exc)
    elif state.phase in {WorkflowPhase.DATING_READY, WorkflowPhase.DATING_STARTED}:
        if state.route.value == "use_existing":
            st.info(tr("existing_route", language))
        _prepare_dating(state, language)
    elif state.phase is WorkflowPhase.FAILED:
        st.error(state.error_message or "Workflow failed")


if __name__ == "__main__":
    render_app()
