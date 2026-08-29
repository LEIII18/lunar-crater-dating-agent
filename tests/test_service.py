from __future__ import annotations

import json
import shlex
import struct
from datetime import datetime
from pathlib import Path

import pytest

from crater_dating_agent.models import DatingError, DatingRequest
from crater_dating_agent.service import run_single_dating
import crater_dating_agent.service as service_module


def write_dbf(path: Path, record_count: int) -> None:
    header = bytearray(32)
    header[4:8] = struct.pack("<I", record_count)
    path.write_bytes(header)


def create_inputs(tmp_path: Path, records: int = 1545) -> DatingRequest:
    date_dir = tmp_path / "date"
    date_dir.mkdir()
    for stem, count in (("CRATER_SID9", records), ("AREA_SID9", 1)):
        for suffix in (".shp", ".shx", ".prj"):
            (date_dir / f"{stem}{suffix}").write_bytes(b"fixture")
        write_dbf(date_dir / f"{stem}.dbf", count)
    image = tmp_path / "3M_DOM" / "63_61E8_08N.tif"
    image.parent.mkdir()
    image.write_bytes(b"tif")
    return DatingRequest(
        crater_shp=date_dir / "CRATER_SID9.shp",
        area_shp=date_dir / "AREA_SID9.shp",
        image_tif=image,
        range_min_km=0.06,
        range_max_km=0.2,
        output_dir=tmp_path / "outputs",
    )


def parse_config(config_path: Path) -> tuple[list[str], Path]:
    args = shlex.split(config_path.read_text(encoding="utf-8"))
    return args, Path(args[args.index("-o") + 1])


def successful_cli(argv: list[str]) -> None:
    assert argv[0] == "-i"
    config_path = Path(argv[1])
    args, output_stem = parse_config(config_path)
    overplots = [args[index + 1] for index, item in enumerate(args) if item == "-p"]
    assert len(overplots) == 2
    assert "range=[0.06,0.2]" in overplots[0]
    assert "type=b-poisson" in overplots[0]
    assert "name=plot 2" in overplots[1]
    assert "type=data" in overplots[1]
    assert "range=" not in overplots[1]
    output_stem.with_suffix(".png").write_bytes(b"fresh png")
    output_stem.with_suffix(".csv").write_text(
        "preamble\n"
        "Name,Method,N,N_event,Age,Age-,Age+\n"
        "CRATER_SID9,b-poisson,63,63,0.376,0.331,0.425\n",
        encoding="utf-8",
    )


def test_run_single_dating_writes_reproducible_success_artifacts(tmp_path: Path) -> None:
    request = create_inputs(tmp_path)

    result = run_single_dating(
        request,
        clock=lambda: datetime(2026, 8, 24, 20, 0, 0),
        cli_main=successful_cli,
    )

    expected_dir = (tmp_path / "outputs" / "SID9" / "20260824_200000_000000").resolve()
    assert result.output_dir == expected_dir
    assert result.age.age_ga == pytest.approx(0.376)
    assert result.age.crater_count == 63
    assert result.plot_path.read_bytes() == b"fresh png"
    age_json = json.loads(result.result_json_path.read_text(encoding="utf-8"))
    assert age_json["inputs"] == {
        "area_shp": str(request.area_shp.resolve()),
        "crater_shp": str(request.crater_shp.resolve()),
        "image_tif": str(request.image_tif.resolve()),
    }
    assert age_json["age_ga"] == pytest.approx(0.376)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["input_crater_count"] == 1545
    assert manifest["craterstats_argv"] == ["-i", str(result.config_path)]
    assert len(manifest["overplots"]) == 2
    assert "range" not in manifest["overplots"][1]
    assert manifest["agent_version"] == "0.1.0"
    assert manifest["scientific_config"] == {
        "schema_version": 1,
        "body": "Moon",
        "chronology_system": {
            "label": "Moon, Neukum (1983)",
            "cli": "MoonNeukum1983",
        },
        "epochs": {
            "label": "Moon, Guo et al (2024)",
            "cli": "MoonGuoetal2024",
        },
        "equilibrium": None,
        "presentation": "differential",
        "binning": "pseudo-log",
        "formats": ["png", "csv"],
    }
    assert "+" in manifest["started_at"]


def test_run_single_dating_preserves_failed_manifest_without_age_json(tmp_path: Path) -> None:
    request = create_inputs(tmp_path)

    def failing_cli(argv: list[str]) -> None:
        raise SystemExit(3)

    with pytest.raises(DatingError, match="退出码 3"):
        run_single_dating(
            request,
            clock=lambda: datetime(2026, 8, 24, 20, 1, 0),
            cli_main=failing_cli,
        )

    run_dir = (tmp_path / "outputs" / "SID9" / "20260824_200100_000000").resolve()
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error_type"] == "DatingError"
    assert (run_dir / "SID9_csfd.log").is_file()
    assert not (run_dir / "SID9_age_result.json").exists()


def test_run_single_dating_allocates_unique_directories_for_same_second(tmp_path: Path) -> None:
    request = create_inputs(tmp_path)
    clock = lambda: datetime(2026, 8, 24, 20, 2, 0)

    first = run_single_dating(request, clock=clock, cli_main=successful_cli)
    second = run_single_dating(request, clock=clock, cli_main=successful_cli)

    assert first.output_dir != second.output_dir
    assert first.output_dir.name == "20260824_200200_000000"
    assert second.output_dir.name == "20260824_200200_000000_01"


def test_run_single_dating_records_config_failure_in_manifest_and_log(
    tmp_path: Path, monkeypatch
) -> None:
    request = create_inputs(tmp_path)

    def invalid_config():
        raise DatingError("月球年代学配置无效")

    monkeypatch.setattr(service_module, "load_scientific_config", invalid_config)

    with pytest.raises(DatingError, match="年代学配置"):
        run_single_dating(
            request,
            clock=lambda: datetime(2026, 8, 24, 20, 3, 0),
            cli_main=successful_cli,
        )

    run_dir = (tmp_path / "outputs" / "SID9" / "20260824_200300_000000").resolve()
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error_type"] == "DatingError"
    assert (run_dir / "SID9_csfd.log").is_file()


def test_run_single_dating_can_write_to_confirmed_agent_final_directory(tmp_path: Path) -> None:
    request = create_inputs(tmp_path)
    final_dir = tmp_path / "agent-session" / "final"

    result = run_single_dating(
        request,
        run_dir=final_dir,
        clock=lambda: datetime(2026, 8, 24, 20, 4, 0),
        cli_main=successful_cli,
    )

    assert result.output_dir == final_dir.resolve()
    assert result.result_json_path.parent == final_dir.resolve()
