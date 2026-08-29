from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from crater_dating_agent.models import DatingRequest
from crater_dating_agent.service import run_single_dating


SID9_ROOT = Path(
    r"E:\DiHuaSuo\2026\paper\csfd_agent\test_crater\SID9_FID3451_63_61E8_08N"
)


@pytest.mark.integration
def test_real_craterstats_dates_sid9_with_global_overview(tmp_path: Path) -> None:
    request = DatingRequest(
        crater_shp=SID9_ROOT / "date" / "CRATER_SID9.shp",
        area_shp=SID9_ROOT / "date" / "AREA_SID9.shp",
        image_tif=SID9_ROOT / "3M_DOM" / "63_61E8_08N.tif",
        range_min_km=0.06,
        range_max_km=0.2,
        output_dir=tmp_path,
    )

    result = run_single_dating(request)

    assert result.plot_path.is_file() and result.plot_path.stat().st_size > 0
    assert result.csv_path.is_file() and result.csv_path.stat().st_size > 0
    assert result.age.crater_count > 0
    assert result.age.age_ga > 0
    assert result.age.age_lower_ga < result.age.age_ga < result.age.age_upper_ga

    config_args = shlex.split(result.config_path.read_text(encoding="utf-8"))
    overplots = [
        config_args[index + 1]
        for index, value in enumerate(config_args)
        if value == "-p"
    ]
    assert len(overplots) == 2
    assert "range=[0.06,0.2]" in overplots[0]
    assert "type=b-poisson" in overplots[0]
    assert "name=plot 2" in overplots[1]
    assert "type=data" in overplots[1]
    assert "range=" not in overplots[1]

    result_json = json.loads(result.result_json_path.read_text(encoding="utf-8"))
    assert result_json["inputs"] == {
        "area_shp": str(request.area_shp.resolve()),
        "crater_shp": str(request.crater_shp.resolve()),
        "image_tif": str(request.image_tif.resolve()),
    }
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["input_crater_count"] == 1545
    assert manifest["craterstats_version"] == "3.6.7"
