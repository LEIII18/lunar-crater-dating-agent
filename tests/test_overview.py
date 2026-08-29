from __future__ import annotations

import shlex
from pathlib import Path

from crater_dating_agent.models import ResolvedInputs
from crater_dating_agent.overview import generate_global_overview, render_global_cs


def inputs(tmp_path: Path) -> ResolvedInputs:
    crater = (tmp_path / "date" / "CRATER_SID9.shp").resolve()
    area = crater.with_name("AREA_SID9.shp")
    image = (tmp_path / "3M_DOM" / "image.tif").resolve()
    return ResolvedInputs("SID9", crater, area, image, 1545)


def test_global_config_has_one_unrestricted_data_plot(tmp_path: Path) -> None:
    args = shlex.split(render_global_cs(inputs(tmp_path), tmp_path / "SID9_global_csfd"))
    plots = [args[index + 1] for index, value in enumerate(args) if value == "-p"]

    assert len(plots) == 1
    assert "name=plot 2" in plots[0]
    assert "type=data" in plots[0]
    assert "binning=pseudo-log" in plots[0]
    assert "psym=o" in plots[0]
    assert "range=" not in plots[0]
    assert "b-poisson" not in plots[0]
    assert args[args.index("-f") + 1] == "png"


def test_global_overview_requires_png_but_not_age_csv(tmp_path: Path) -> None:
    resolved = inputs(tmp_path)

    def png_only_cli(argv: list[str]) -> None:
        config = Path(argv[1])
        args = shlex.split(config.read_text(encoding="utf-8"))
        stem = Path(args[args.index("-o") + 1])
        stem.with_suffix(".png").write_bytes(b"global png")

    overview = generate_global_overview(
        resolved, tmp_path / "overview", cli_main=png_only_cli
    )

    assert overview.plot_path.read_bytes() == b"global png"
    assert overview.config_path.is_file()
    assert overview.log_path.is_file()
    assert not overview.plot_path.with_suffix(".csv").exists()
