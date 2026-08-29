from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .agent_models import AgentRequest
from .models import DatingError
from .overlay_preview import render_overlay_preview
from .pipeline_runner import DetectionSettings, run_detection
from .workflow_inputs import validate_manual_crater, validate_workflow_inputs
from .workflow_models import (
    WorkflowPhase,
    WorkflowRequest,
    WorkflowRoute,
    WorkflowState,
    WorkflowWorkspace,
)
from .workflow_workspace import copy_shapefile_set, create_workflow_workspace


WORKFLOW_SCHEMA_VERSION = 1


def _now(clock=None) -> str:
    value = (clock or (lambda: datetime.now().astimezone()))()
    return (value if value.tzinfo is not None else value.astimezone()).isoformat()


def _optional_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _timestamp_token(clock=None) -> str:
    value = (clock or (lambda: datetime.now().astimezone()))()
    return value.strftime("%Y%m%d_%H%M%S_%f")


def _archive_failed_agent_attempt(workspace_root: Path, *, clock=None) -> Path | None:
    state_path = workspace_root / "session_state.json"
    if not state_path.exists():
        return None
    try:
        phase = json.loads(state_path.read_text(encoding="utf-8")).get("phase")
    except (OSError, json.JSONDecodeError) as exc:
        raise DatingError(f"无法读取已有定年会话状态：{state_path}") from exc
    if phase != "failed":
        raise DatingError(f"任务目录中已有未结束的定年会话：{state_path}")

    archive_root = workspace_root / "failed_attempts"
    archive_root.mkdir(exist_ok=True)
    archive_dir = archive_root / _timestamp_token(clock)
    counter = 1
    while archive_dir.exists():
        archive_dir = archive_root / f"{_timestamp_token(clock)}_{counter}"
        counter += 1
    archive_dir.mkdir()
    for name in (
        "session_state.json",
        "llm",
        "overview",
        "previews",
        "final",
        "confirmation.json",
    ):
        source = workspace_root / name
        if source.exists():
            if source.is_symlink():
                raise DatingError(f"拒绝归档符号链接：{source}")
            shutil.move(str(source), str(archive_dir / name))
    return archive_dir


def _payload(state: WorkflowState) -> dict[str, object]:
    workspace = state.workspace
    return {
        "schema_version": state.schema_version,
        "case_id": state.case_id,
        "phase": state.phase.value,
        "route": state.route.value,
        "workspace": {
            "root": str(workspace.root),
            "source_dir": str(workspace.source_dir),
            "detection_work_dir": str(workspace.detection_work_dir),
            "detection_preview_dir": str(workspace.detection_preview_dir),
            "manual_revision_dir": str(workspace.manual_revision_dir),
            "logs_dir": str(workspace.logs_dir),
            "area_shp": str(workspace.area_shp),
            "crater_shp": str(workspace.crater_shp),
            "image_tif": str(workspace.image_tif),
        },
        "settings": {
            "arcpy_python": str(state.settings.arcpy_python),
            "model_python": str(state.settings.model_python),
            "model_dir": str(state.settings.model_dir),
        },
        "input_crater_count": state.input_crater_count,
        "current_crater_count": state.current_crater_count,
        "automatic_crater_shp": _optional_path(state.automatic_crater_shp),
        "manual_crater_shp": _optional_path(state.manual_crater_shp),
        "selected_crater_shp": _optional_path(state.selected_crater_shp),
        "automatic_preview_path": _optional_path(state.automatic_preview_path),
        "manual_preview_path": _optional_path(state.manual_preview_path),
        "data_source": state.data_source,
        "started_at": state.started_at,
        "updated_at": state.updated_at,
        "error_message": state.error_message,
    }


def _save(state: WorkflowState) -> None:
    temporary = state.state_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(_payload(state), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(state.state_path)


def load_workflow_state(path: Path) -> WorkflowState:
    requested = Path(path)
    if requested.is_symlink():
        raise DatingError("工作流状态文件不能是符号链接")
    try:
        state_path = requested.resolve(strict=True)
        root = state_path.parent
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if data["schema_version"] != WORKFLOW_SCHEMA_VERSION:
            raise DatingError(f"不支持的工作流 schema：{data['schema_version']}")
        workspace_data = data["workspace"]
        declared_root = Path(workspace_data["root"]).resolve(strict=True)
        if declared_root != root:
            raise DatingError("工作流状态中的任务根目录与状态文件位置不一致")

        expected_dirs = {
            "source_dir": root / "source_copy",
            "detection_work_dir": root / "detection_work",
            "detection_preview_dir": root / "detection_preview",
            "manual_revision_dir": root / "manual_revision",
            "logs_dir": root / "logs",
        }
        resolved_dirs: dict[str, Path] = {}
        for field, expected in expected_dirs.items():
            actual = Path(workspace_data[field]).resolve(strict=True)
            if actual != expected.resolve(strict=True) or not actual.is_dir():
                raise DatingError(f"工作流状态目录无效：{field}")
            resolved_dirs[field] = actual

        def task_file(value: object, field: str) -> Path:
            actual = Path(str(value)).resolve(strict=True)
            if not actual.is_file() or not actual.is_relative_to(root):
                raise DatingError(f"工作流状态文件超出任务目录：{field}")
            return actual

        def optional_task_file(value: object, field: str) -> Path | None:
            return None if value is None else task_file(value, field)

        workspace = WorkflowWorkspace(
            root=root,
            source_dir=resolved_dirs["source_dir"],
            detection_work_dir=resolved_dirs["detection_work_dir"],
            detection_preview_dir=resolved_dirs["detection_preview_dir"],
            manual_revision_dir=resolved_dirs["manual_revision_dir"],
            logs_dir=resolved_dirs["logs_dir"],
            area_shp=task_file(workspace_data["area_shp"], "area_shp"),
            crater_shp=task_file(workspace_data["crater_shp"], "crater_shp"),
            image_tif=Path(workspace_data["image_tif"]).resolve(strict=True),
        )
        settings_data = data["settings"]
        settings = DetectionSettings(
            arcpy_python=Path(settings_data["arcpy_python"]),
            model_python=Path(settings_data["model_python"]),
            model_dir=Path(settings_data["model_dir"]),
        )
        return WorkflowState(
            schema_version=int(data["schema_version"]),
            case_id=str(data["case_id"]),
            phase=WorkflowPhase(data["phase"]),
            route=WorkflowRoute(data["route"]),
            workspace=workspace,
            settings=settings,
            state_path=state_path,
            input_crater_count=int(data["input_crater_count"]),
            current_crater_count=int(data["current_crater_count"]),
            automatic_crater_shp=optional_task_file(
                data.get("automatic_crater_shp"), "automatic_crater_shp"
            ),
            manual_crater_shp=optional_task_file(
                data.get("manual_crater_shp"), "manual_crater_shp"
            ),
            selected_crater_shp=optional_task_file(
                data.get("selected_crater_shp"), "selected_crater_shp"
            ),
            automatic_preview_path=optional_task_file(
                data.get("automatic_preview_path"), "automatic_preview_path"
            ),
            manual_preview_path=optional_task_file(
                data.get("manual_preview_path"), "manual_preview_path"
            ),
            data_source=data.get("data_source"),
            started_at=str(data["started_at"]),
            updated_at=str(data["updated_at"]),
            error_message=data.get("error_message"),
        )
    except DatingError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DatingError(f"无法读取工作流状态：{exc}") from exc


def _updated(state: WorkflowState, phase: WorkflowPhase, *, clock=None, **changes) -> WorkflowState:
    result = replace(state, phase=phase, updated_at=_now(clock), **changes)
    _save(result)
    return result


def start_workflow(
    request: WorkflowRequest,
    settings: DetectionSettings,
    output_root: Path,
    *,
    clock=None,
) -> WorkflowState:
    inputs = validate_workflow_inputs(
        request.area_shp, request.crater_shp, request.image_tif
    )
    workspace = create_workflow_workspace(inputs, output_root, clock=clock)
    phase = (
        WorkflowPhase.DETECTION_READY
        if inputs.route is WorkflowRoute.AUTO_DETECT
        else WorkflowPhase.DATING_READY
    )
    selected = workspace.crater_shp if phase is WorkflowPhase.DATING_READY else None
    source = "existing" if selected is not None else None
    timestamp = _now(clock)
    state = WorkflowState(
        schema_version=WORKFLOW_SCHEMA_VERSION,
        case_id=inputs.case_id,
        phase=phase,
        route=inputs.route,
        workspace=workspace,
        settings=settings,
        state_path=workspace.root / "workflow_state.json",
        input_crater_count=inputs.crater_count,
        current_crater_count=inputs.crater_count,
        automatic_crater_shp=None,
        manual_crater_shp=None,
        selected_crater_shp=selected,
        automatic_preview_path=None,
        manual_preview_path=None,
        data_source=source,
        started_at=timestamp,
        updated_at=timestamp,
    )
    _save(state)
    return state


def run_automatic_detection(
    state: WorkflowState,
    *,
    on_line: Callable[[str], None] | None = None,
    detection_runner=run_detection,
    preview_renderer=render_overlay_preview,
    clock=None,
) -> WorkflowState:
    if state.phase is not WorkflowPhase.DETECTION_READY:
        raise DatingError("只有空 CRATER 的待识坑任务可以运行自动识别")
    try:
        result = detection_runner(state.workspace, state.settings, on_line=on_line)
        preview = preview_renderer(
            state.workspace.image_tif,
            state.workspace.area_shp,
            result.crater_shp,
            state.workspace.detection_preview_dir / "automatic_overlay.png",
            state.case_id,
        )
    except Exception as exc:
        _updated(state, WorkflowPhase.FAILED, error_message=str(exc), clock=clock)
        raise
    return _updated(
        state,
        WorkflowPhase.DETECTION_REVIEW,
        current_crater_count=result.crater_count,
        automatic_crater_shp=result.crater_shp,
        automatic_preview_path=preview.png_path,
        error_message=None,
        clock=clock,
    )


def accept_automatic_result(state: WorkflowState, *, clock=None) -> WorkflowState:
    if (
        state.phase is not WorkflowPhase.DETECTION_REVIEW
        or state.automatic_crater_shp is None
    ):
        raise DatingError("自动识坑结果尚未准备好，不能确认")
    return _updated(
        state,
        WorkflowPhase.DATING_READY,
        selected_crater_shp=state.automatic_crater_shp,
        data_source="automatic",
        clock=clock,
    )


def import_manual_revision(
    state: WorkflowState,
    crater_shp: Path,
    *,
    preview_renderer=render_overlay_preview,
    clock=None,
) -> WorkflowState:
    if state.phase is not WorkflowPhase.DETECTION_REVIEW:
        raise DatingError("只有待确认的自动识坑结果可以导入人工修订文件")
    count = validate_manual_crater(
        state.workspace.area_shp, Path(crater_shp), state.case_id
    )
    destination = state.workspace.manual_revision_dir
    existing_files = {item.resolve() for item in destination.iterdir()}
    preview_path = state.workspace.detection_preview_dir / "manual_overlay.png"
    preview_existed = preview_path.exists()
    try:
        copied = copy_shapefile_set(Path(crater_shp), destination)
        copy_shapefile_set(state.workspace.area_shp, destination)
        preview = preview_renderer(
            state.workspace.image_tif,
            state.workspace.area_shp,
            copied,
            preview_path,
            state.case_id,
        )
    except Exception:
        for item in destination.iterdir():
            if item.is_file() and item.resolve() not in existing_files:
                item.unlink(missing_ok=True)
        if not preview_existed:
            preview_path.unlink(missing_ok=True)
        raise
    return _updated(
        state,
        WorkflowPhase.MANUAL_REVIEW,
        current_crater_count=count,
        manual_crater_shp=copied,
        manual_preview_path=preview.png_path,
        selected_crater_shp=None,
        data_source=None,
        clock=clock,
    )


def accept_manual_revision(state: WorkflowState, *, clock=None) -> WorkflowState:
    if state.phase is not WorkflowPhase.MANUAL_REVIEW or state.manual_crater_shp is None:
        raise DatingError("人工修订预览尚未确认")
    return _updated(
        state,
        WorkflowPhase.DATING_READY,
        selected_crater_shp=state.manual_crater_shp,
        data_source="manual",
        clock=clock,
    )


def start_dating_session(
    state: WorkflowState,
    *,
    prepare_session=None,
    clock=None,
):
    if state.phase is not WorkflowPhase.DATING_READY or state.selected_crater_shp is None:
        raise DatingError("必须先确认用于定年的 CRATER")
    if prepare_session is None:
        from .agent_service import prepare_agent_session

        prepare_session = prepare_agent_session
    request = AgentRequest(
        crater_shp=state.selected_crater_shp,
        area_shp=state.workspace.area_shp,
        image_tif=state.workspace.image_tif,
        output_dir=state.workspace.root,
    )
    _archive_failed_agent_attempt(state.workspace.root, clock=clock)
    session = prepare_session(request, session_dir=state.workspace.root, clock=clock)
    _updated(state, WorkflowPhase.DATING_STARTED, clock=clock)
    return session
