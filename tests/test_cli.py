from __future__ import annotations

from pathlib import Path

from crater_dating_agent.main import main
from crater_dating_agent.models import AgeEstimate, DatingError, DatingResult


def argv(tmp_path: Path, range_min: str = "0.06", range_max: str = "0.2") -> list[str]:
    return [
        "--crater-shp",
        str(tmp_path / "CRATER_SID9.shp"),
        "--area-shp",
        str(tmp_path / "AREA_SID9.shp"),
        "--image-tif",
        str(tmp_path / "image.tif"),
        "--range-min",
        range_min,
        "--range-max",
        range_max,
        "--output-dir",
        str(tmp_path / "outputs"),
    ]


def result(tmp_path: Path) -> DatingResult:
    run_dir = tmp_path / "outputs" / "SID9" / "run"
    return DatingResult(
        case_id="SID9",
        output_dir=run_dir,
        config_path=run_dir / "SID9_dating.cs",
        plot_path=run_dir / "SID9_csfd.png",
        csv_path=run_dir / "SID9_csfd.csv",
        log_path=run_dir / "SID9_csfd.log",
        result_json_path=run_dir / "SID9_age_result.json",
        manifest_path=run_dir / "run_manifest.json",
        age=AgeEstimate(63, 0.376, 0.331, 0.425, 0.045, 0.049),
    )


def test_main_prints_age_and_artifact_paths_on_success(tmp_path: Path, capsys) -> None:
    expected = result(tmp_path)

    exit_code = main(argv(tmp_path), _run=lambda request: expected)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "0.376 Ga" in captured.out
    assert str(expected.plot_path) in captured.out
    assert str(expected.result_json_path) in captured.out
    assert captured.err == ""


def test_main_prints_actionable_dating_error_to_stderr(tmp_path: Path, capsys) -> None:
    def failing_run(request):
        raise DatingError("CRATER 数据为空")

    exit_code = main(argv(tmp_path), _run=failing_run)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "CRATER 数据为空" in captured.err
    assert "定年完成" not in captured.out


def test_main_passes_invalid_range_to_domain_validation(tmp_path: Path, capsys) -> None:
    def validating_run(request):
        if request.range_max_km <= request.range_min_km:
            raise DatingError("range 上限必须大于下限")
        return result(tmp_path)

    exit_code = main(argv(tmp_path, "0.2", "0.06"), _run=validating_run)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "range 上限必须大于下限" in captured.err
