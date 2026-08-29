from __future__ import annotations

import shlex
from pathlib import Path

from crater_dating_agent.config_generator import render_cs
from crater_dating_agent.models import DatingRequest, ResolvedInputs


def test_render_cs_preserves_global_overview_without_range(tmp_path: Path) -> None:
    source = tmp_path / "input with space" / "CRATER_SID9.shp"
    area = source.with_name("AREA_SID9.shp")
    image = tmp_path / "63_61E8_08N.tif"
    request = DatingRequest(source, area, image, 0.06, 0.2)
    inputs = ResolvedInputs("SID9", source, area, image, 63)
    output_stem = tmp_path / "result with space" / "SID9_csfd"

    rendered = render_cs(request, inputs, output_stem)
    args = shlex.split(rendered)
    overplots = [args[index + 1] for index, value in enumerate(args) if value == "-p"]

    assert args[:10] == [
        "-o",
        str(output_stem),
        "-f",
        "png",
        "csv",
        "-cs",
        "MoonNeukum1983",
        "-ep",
        "MoonGuoetal2024",
        "-pr",
    ]
    assert args[10] == "differential"
    assert len(overplots) == 2
    assert overplots[0] == (
        f"source={source},range=[0.06,0.2],type=b-poisson,"
        "binning=pseudo-log,psym=fo"
    )
    assert overplots[1] == (
        f"source={source},name=plot 2,type=data,binning=pseudo-log,psym=o"
    )
    assert "range=" not in overplots[1]


def test_render_cs_formats_range_without_binary_float_noise(tmp_path: Path) -> None:
    source = tmp_path / "CRATER_SID9.shp"
    area = tmp_path / "AREA_SID9.shp"
    image = tmp_path / "image.tif"
    request = DatingRequest(source, area, image, 0.0600, 0.2000)
    inputs = ResolvedInputs("SID9", source, area, image, 63)

    rendered = render_cs(request, inputs, tmp_path / "out")

    assert "range=[0.06,0.2]" in rendered
    assert "0.200000" not in rendered
