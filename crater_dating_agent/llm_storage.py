from __future__ import annotations

import json
from pathlib import Path


MODE_DIRECTORIES = {
    "zero_shot": "llm_zero",
    "few_shot": "llm_few",
}


def prompt_mode_value(mode: object | None) -> str:
    value = getattr(mode, "value", mode)
    return value if value in MODE_DIRECTORIES else "zero_shot"


def llm_output_dir(session_dir: Path, mode: object | None) -> Path:
    return Path(session_dir) / MODE_DIRECTORIES[prompt_mode_value(mode)]


def preview_output_dir(session_dir: Path, mode: object | None) -> Path:
    suffix = "zero" if prompt_mode_value(mode) == "zero_shot" else "few"
    return Path(session_dir) / f"previews_{suffix}"


def active_mode_path(session_dir: Path) -> Path:
    return Path(session_dir) / "llm" / "active_prompt_mode.json"


def write_active_mode(session_dir: Path, mode: object | None) -> None:
    path = active_mode_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"prompt_mode": prompt_mode_value(mode)}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def active_llm_output_dir(session_dir: Path) -> Path:
    path = active_mode_path(session_dir)
    try:
        mode = json.loads(path.read_text(encoding="utf-8")).get("prompt_mode")
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return Path(session_dir) / "llm"
    return llm_output_dir(session_dir, mode)


def active_candidates_path(session_dir: Path) -> Path:
    return active_llm_output_dir(session_dir) / "range_candidates.json"
