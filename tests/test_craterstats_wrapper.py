from __future__ import annotations

import os
import shlex
from pathlib import Path

import pytest

from crater_dating_agent.craterstats_wrapper import invoke_craterstats
from crater_dating_agent.models import DatingError


def write_config(config_path: Path, output_stem: Path) -> None:
    config_path.write_text(f"-o {shlex.quote(str(output_stem))}\n-f png csv\n", encoding="utf-8")


def output_stem_from_config(config_path: Path) -> Path:
    args = shlex.split(config_path.read_text(encoding="utf-8"))
    return Path(args[args.index("-o") + 1])


def test_invoke_craterstats_restores_cwd_and_verifies_real_outputs(tmp_path: Path) -> None:
    config_path = (tmp_path / "SID9_dating.cs").resolve()
    output_stem = (tmp_path / "SID9_csfd").resolve()
    write_config(config_path, output_stem)
    original_cwd = Path.cwd()

    def fake_cli(argv: list[str]) -> None:
        assert argv == ["-i", str(config_path)]
        stem = output_stem_from_config(config_path)
        stem.with_suffix(".png").write_bytes(b"png")
        stem.with_suffix(".csv").write_text("csv", encoding="utf-8")
        print("fake craterstats complete")
        os.chdir(tmp_path)

    result = invoke_craterstats(config_path, output_stem, cli_main=fake_cli)

    assert Path.cwd() == original_cwd
    assert result.plot_path == output_stem.with_suffix(".png")
    assert result.csv_path == output_stem.with_suffix(".csv")
    assert result.log_path.read_text(encoding="utf-8").strip() == "fake craterstats complete"
    assert "fake craterstats complete" in result.stdout
    assert result.stderr == ""


def test_invoke_craterstats_reports_nonzero_system_exit(tmp_path: Path) -> None:
    config_path = (tmp_path / "SID9_dating.cs").resolve()
    output_stem = (tmp_path / "SID9_csfd").resolve()
    write_config(config_path, output_stem)

    def failing_cli(argv: list[str]) -> None:
        print("invalid plot", file=__import__("sys").stderr)
        raise SystemExit(2)

    with pytest.raises(DatingError, match="退出码 2"):
        invoke_craterstats(config_path, output_stem, cli_main=failing_cli)

    assert "invalid plot" in output_stem.with_suffix(".log").read_text(encoding="utf-8")


def test_invoke_craterstats_converts_string_system_exit_and_keeps_log(tmp_path: Path) -> None:
    config_path = (tmp_path / "SID9_dating.cs").resolve()
    output_stem = (tmp_path / "SID9_csfd").resolve()
    write_config(config_path, output_stem)

    def failing_cli(argv: list[str]) -> None:
        print("bad configuration")
        raise SystemExit("invalid range")

    with pytest.raises(DatingError, match="invalid range"):
        invoke_craterstats(config_path, output_stem, cli_main=failing_cli)

    assert "bad configuration" in output_stem.with_suffix(".log").read_text(encoding="utf-8")


def test_invoke_craterstats_rejects_missing_csv_output(tmp_path: Path) -> None:
    config_path = (tmp_path / "SID9_dating.cs").resolve()
    output_stem = (tmp_path / "SID9_csfd").resolve()
    write_config(config_path, output_stem)

    def incomplete_cli(argv: list[str]) -> None:
        output_stem.with_suffix(".png").write_bytes(b"png")

    with pytest.raises(DatingError, match=r"SID9_csfd\.csv"):
        invoke_craterstats(config_path, output_stem, cli_main=incomplete_cli)
