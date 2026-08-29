from __future__ import annotations

import locale
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .models import DatingError
from .path_resolver import read_dbf_record_count
from .workflow_models import DetectionRunResult, WorkflowWorkspace


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARCPY_PYTHON = Path(r"C:\Python27\ArcGIS10.8\python.exe")
DEFAULT_MODEL_PYTHON = Path(
    r"C:\ProgramData\Anaconda3\envs\crater_model_py39\python.exe"
)
DEFAULT_MODEL_DIR = PROJECT_ROOT / "crater_detect_model"
DEFAULT_PIPELINE_SCRIPT = PROJECT_ROOT / "part1_code" / "auto_crater_detection_pipeline.py"


@dataclass(frozen=True)
class DetectionSettings:
    arcpy_python: Path = DEFAULT_ARCPY_PYTHON
    model_python: Path = DEFAULT_MODEL_PYTHON
    model_dir: Path = DEFAULT_MODEL_DIR
    pipeline_script: Path = DEFAULT_PIPELINE_SCRIPT

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> "DetectionSettings":
        values = os.environ if environ is None else environ
        return cls(
            arcpy_python=Path(values.get("ARCPY_PYTHON", str(DEFAULT_ARCPY_PYTHON))),
            model_python=Path(
                values.get("CRATER_MODEL_PYTHON", str(DEFAULT_MODEL_PYTHON))
            ),
            model_dir=Path(values.get("CRATER_MODEL_DIR", str(DEFAULT_MODEL_DIR))),
        )


def build_detection_argv(
    workspace: WorkflowWorkspace, settings: DetectionSettings
) -> tuple[str, ...]:
    return (
        str(Path(settings.arcpy_python).resolve()),
        str(Path(settings.pipeline_script).resolve()),
        "--area-shp",
        str(workspace.area_shp),
        "--image-tif",
        str(workspace.image_tif),
        "--target-shp",
        str(workspace.crater_shp),
        "--model-dir",
        str(Path(settings.model_dir).resolve()),
        "--model-python",
        str(Path(settings.model_python).resolve()),
        "--work-dir",
        str(workspace.detection_work_dir),
        "--overwrite",
    )


def _require_runtime(settings: DetectionSettings) -> None:
    required = (
        (Path(settings.arcpy_python), "ArcPy Python"),
        (Path(settings.model_python), "识别模型 Python"),
        (Path(settings.pipeline_script), "自动识坑编排脚本"),
        (Path(settings.model_dir) / "predict_onnx.py", "predict_onnx.py"),
        (
            Path(settings.model_dir)
            / "model_data"
            / "moon"
            / "weights"
            / "moon.onnx",
            "moon.onnx",
        ),
    )
    for path, label in required:
        if path.is_symlink() or not path.is_file():
            raise DatingError(f"缺少 {label}：{path}")


def run_detection(
    workspace: WorkflowWorkspace,
    settings: DetectionSettings,
    *,
    on_line: Callable[[str], None] | None = None,
    popen_factory=subprocess.Popen,
) -> DetectionRunResult:
    _require_runtime(settings)
    argv = build_detection_argv(workspace, settings)
    log_path = workspace.logs_dir / "detection.log"
    encoding = locale.getpreferredencoding(False) or "utf-8"
    try:
        process = popen_factory(
            argv,
            cwd=str(PROJECT_ROOT),
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
            bufsize=1,
        )
        with log_path.open("w", encoding="utf-8", newline="") as log:
            if process.stdout is None:
                raise DatingError("自动识坑进程没有可读取的输出流")
            for raw_line in process.stdout:
                log.write(raw_line)
                log.flush()
                line = raw_line.rstrip("\r\n")
                if line and on_line is not None:
                    on_line(line)
        return_code = process.wait()
    except DatingError:
        raise
    except OSError as exc:
        raise DatingError(f"无法启动撞击坑自动识别模型：{exc}") from exc
    if return_code != 0:
        raise DatingError(
            f"撞击坑自动识别模型运行失败，退出码 {return_code}；日志：{log_path}"
        )
    crater_count = read_dbf_record_count(workspace.crater_shp.with_suffix(".dbf"))
    if crater_count < 1:
        raise DatingError(
            f"撞击坑自动识别模型没有生成有效撞击坑；日志：{log_path}"
        )
    return DetectionRunResult(
        crater_shp=workspace.crater_shp,
        crater_count=crater_count,
        log_path=log_path,
        argv=argv,
    )