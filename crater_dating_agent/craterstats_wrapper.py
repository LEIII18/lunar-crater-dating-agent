from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Callable

from .models import DatingError, InvocationResult


CliMain = Callable[[list[str]], None]


def _load_cli_main() -> CliMain:
    try:
        from craterstats.cli import main
    except ImportError as exc:
        raise DatingError(
            "无法导入 craterstats；请在项目 Python 环境中安装 craterstats。"
        ) from exc
    return main


def invoke_craterstats(
    config_path: Path,
    output_stem: Path,
    cli_main: CliMain | None = None,
    *,
    required_formats: tuple[str, ...] = ("png", "csv"),
) -> InvocationResult:
    config_path = Path(config_path).resolve()
    output_stem = Path(output_stem).resolve()
    plot_path = output_stem.with_suffix(".png")
    csv_path = output_stem.with_suffix(".csv")
    log_path = output_stem.with_suffix(".log")
    cli_main = cli_main or _load_cli_main()

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    original_cwd = Path.cwd()
    exit_failure: object | None = None
    failure: Exception | None = None
    try:
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            cli_main(["-i", str(config_path)])
    except SystemExit as exc:
        if exc.code not in (None, 0):
            exit_failure = exc.code
    except Exception as exc:  # third-party boundary
        failure = exc
    finally:
        os.chdir(original_cwd)

    stdout = stdout_buffer.getvalue()
    stderr = stderr_buffer.getvalue()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_text = stdout
    if stderr:
        log_text += ("\n" if log_text and not log_text.endswith("\n") else "") + stderr
    log_path.write_text(log_text, encoding="utf-8")

    if failure is not None:
        raise DatingError(f"Craterstats 执行失败：{failure}") from failure
    if exit_failure is not None:
        raise DatingError(f"Craterstats 执行失败，退出码 {exit_failure}；详见 {log_path}")
    expected_by_format = {"png": plot_path, "csv": csv_path}
    try:
        expected_paths = tuple(expected_by_format[item] for item in required_formats)
    except KeyError as exc:
        raise DatingError(f"不支持的 Craterstats 输出格式：{exc.args[0]}") from exc
    for expected in expected_paths:
        if not expected.is_file():
            raise DatingError(f"Craterstats 未生成预期输出：{expected}")

    return InvocationResult(
        config_path=config_path,
        plot_path=plot_path,
        csv_path=csv_path,
        log_path=log_path,
        stdout=stdout,
        stderr=stderr,
    )
