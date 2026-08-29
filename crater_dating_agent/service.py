from __future__ import annotations

import json
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable

from .config_generator import load_scientific_config, render_cs
from .craterstats_wrapper import CliMain, invoke_craterstats
from .models import DatingError, DatingRequest, DatingResult
from .path_resolver import REQUIRED_SHAPEFILE_SUFFIXES, resolve_inputs
from .result_parser import parse_age_csv


Clock = Callable[[], datetime]


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _craterstats_version() -> str:
    try:
        return version("craterstats")
    except PackageNotFoundError:
        return "not-installed"


def _agent_version() -> str:
    try:
        return version("crater-dating-agent")
    except PackageNotFoundError:
        return "0.1.0"


def _aware_local(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.astimezone()


def _allocate_run_dir(base_output: Path, case_id: str, started: datetime) -> Path:
    case_dir = (base_output / case_id).resolve()
    try:
        case_dir.mkdir(parents=True, exist_ok=True)
        stem = started.strftime("%Y%m%d_%H%M%S_%f")
        for suffix in ("", *(f"_{index:02d}" for index in range(1, 1000))):
            candidate = case_dir / f"{stem}{suffix}"
            try:
                candidate.mkdir(exist_ok=False)
                return candidate
            except FileExistsError:
                continue
    except OSError as exc:
        raise DatingError(f"无法创建运行目录：{exc}") from exc
    raise DatingError(f"无法为 {case_id} 分配唯一运行目录")


def _input_file_metadata(paths: tuple[Path, ...]) -> list[dict[str, object]]:
    metadata = []
    for path in paths:
        stat = path.stat()
        metadata.append(
            {
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        )
    return metadata


def run_single_dating(
    request: DatingRequest,
    *,
    clock: Clock | None = None,
    cli_main: CliMain | None = None,
    run_dir: Path | None = None,
) -> DatingResult:
    clock = clock or (lambda: datetime.now().astimezone())
    started = _aware_local(clock())
    inputs = resolve_inputs(request)
    base_output = (
        Path(request.output_dir).resolve()
        if request.output_dir is not None
        else Path(__file__).resolve().parent.parent / "outputs"
    )
    if run_dir is None:
        run_dir = _allocate_run_dir(base_output, inputs.case_id, started)
    else:
        run_dir = Path(run_dir).resolve()
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise DatingError(f"无法创建指定运行目录：{exc}") from exc

    config_path = run_dir / f"{inputs.case_id}_dating.cs"
    output_stem = run_dir / f"{inputs.case_id}_csfd"
    log_path = output_stem.with_suffix(".log")
    result_json_path = run_dir / f"{inputs.case_id}_age_result.json"
    manifest_path = run_dir / "run_manifest.json"
    log_path.write_text("", encoding="utf-8")
    manifest: dict[str, object] = {
        "status": "running",
        "case_id": inputs.case_id,
        "started_at": started.isoformat(),
        "agent_version": _agent_version(),
        "craterstats_version": _craterstats_version(),
        "inputs": {
            "crater_shp": str(inputs.crater_shp),
            "area_shp": str(inputs.area_shp),
            "image_tif": str(inputs.image_tif),
        },
        "input_crater_count": inputs.crater_count,
    }
    _write_json(manifest_path, manifest)

    try:
        scientific = load_scientific_config()
        config_path.write_text(
            render_cs(request, inputs, output_stem, scientific), encoding="utf-8"
        )
        overplots: list[dict[str, object]] = [
            {
                "source": str(inputs.crater_shp),
                "range": [request.range_min_km, request.range_max_km],
                "type": scientific.fit_type,
                "binning": scientific.binning,
                "symbol": scientific.fit_symbol,
            },
            {
                "source": str(inputs.crater_shp),
                "name": scientific.overview_name,
                "type": scientific.overview_type,
                "binning": scientific.binning,
                "symbol": scientific.overview_symbol,
            },
        ]
        component_paths = tuple(
            path.with_suffix(suffix)
            for path in (inputs.crater_shp, inputs.area_shp)
            for suffix in REQUIRED_SHAPEFILE_SUFFIXES
        ) + (inputs.image_tif,)
        manifest.update(
            {
                "input_files": _input_file_metadata(component_paths),
                "scientific_config": {
                    "schema_version": scientific.schema_version,
                    "body": scientific.body,
                    "chronology_system": {
                        "label": scientific.chronology_label,
                        "cli": scientific.chronology_cli,
                    },
                    "epochs": {
                        "label": scientific.epochs_label,
                        "cli": scientific.epochs_cli,
                    },
                    "equilibrium": scientific.equilibrium,
                    "presentation": scientific.presentation,
                    "binning": scientific.binning,
                    "formats": list(scientific.formats),
                },
                "overplots": overplots,
                "craterstats_argv": ["-i", str(config_path)],
            }
        )
        _write_json(manifest_path, manifest)
        invocation = invoke_craterstats(config_path, output_stem, cli_main=cli_main)
        age = parse_age_csv(invocation.csv_path)
        result_payload: dict[str, object] = {
            "case_id": inputs.case_id,
            "inputs": manifest["inputs"],
            "chronology_system": scientific.chronology_label,
            "epochs": scientific.epochs_label,
            "method": scientific.fit_type,
            "range_km": [request.range_min_km, request.range_max_km],
            "crater_count": age.crater_count,
            "age_ga": age.age_ga,
            "age_lower_ga": age.age_lower_ga,
            "age_upper_ga": age.age_upper_ga,
            "age_minus_ga": age.age_minus_ga,
            "age_plus_ga": age.age_plus_ga,
            "plot_path": str(invocation.plot_path),
            "csv_path": str(invocation.csv_path),
            "config_path": str(config_path),
        }
        _write_json(result_json_path, result_payload)
        manifest.update(
            {
                "status": "success",
                "finished_at": _aware_local(clock()).isoformat(),
                "generated_files": [
                    str(config_path),
                    str(invocation.plot_path),
                    str(invocation.csv_path),
                    str(invocation.log_path),
                    str(result_json_path),
                    str(manifest_path),
                ],
            }
        )
        _write_json(manifest_path, manifest)
        return DatingResult(
            case_id=inputs.case_id,
            output_dir=run_dir,
            config_path=config_path,
            plot_path=invocation.plot_path,
            csv_path=invocation.csv_path,
            log_path=invocation.log_path,
            result_json_path=result_json_path,
            manifest_path=manifest_path,
            age=age,
        )
    except Exception as exc:
        manifest.update(
            {
                "status": "failed",
                "finished_at": _aware_local(clock()).isoformat(),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
        )
        _write_json(manifest_path, manifest)
        raise
