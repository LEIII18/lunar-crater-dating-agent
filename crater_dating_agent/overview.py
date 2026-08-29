from __future__ import annotations

import shlex
import math
from pathlib import Path
from typing import Callable, Protocol

from .agent_models import CsfdBin, CsfdSummary, GlobalOverview
from .config_generator import ScientificConfig, load_scientific_config
from .craterstats_wrapper import CliMain, invoke_craterstats
from .models import DatingError, ResolvedInputs


class CratercountLike(Protocol):
    area: float
    perimeter: float
    binned: dict[str, object]

    def apply_binning(self, binning: str) -> None: ...


CratercountFactory = Callable[[str, str], CratercountLike]


def render_global_cs(
    inputs: ResolvedInputs,
    output_stem: Path,
    config: ScientificConfig | None = None,
) -> str:
    config = config or load_scientific_config()
    overplot = ",".join(
        (
            f"source={inputs.crater_shp}",
            f"name={config.overview_name}",
            f"type={config.overview_type}",
            f"binning={config.binning}",
            f"psym={config.overview_symbol}",
        )
    )
    return "\n".join(
        (
            f"-o {shlex.quote(str(Path(output_stem).resolve()))}",
            "-f png",
            f"-cs {config.chronology_cli}",
            f"-ep {config.epochs_cli}",
            f"-pr {config.presentation}",
            f"-p {shlex.quote(overplot)}",
        )
    ) + "\n"


def generate_global_overview(
    inputs: ResolvedInputs,
    overview_dir: Path,
    *,
    cli_main: CliMain | None = None,
) -> GlobalOverview:
    overview_dir = Path(overview_dir).resolve()
    overview_dir.mkdir(parents=True, exist_ok=True)
    output_stem = overview_dir / f"{inputs.case_id}_global_csfd"
    config_path = overview_dir / f"{inputs.case_id}_global.cs"
    config_path.write_text(render_global_cs(inputs, output_stem), encoding="utf-8")
    invocation = invoke_craterstats(
        config_path,
        output_stem,
        cli_main=cli_main,
        required_formats=("png",),
    )
    return GlobalOverview(
        plot_path=invocation.plot_path,
        config_path=config_path,
        log_path=invocation.log_path,
        summary_path=overview_dir / "csfd_summary.json",
    )


def _default_cratercount_factory(crater: str, area: str) -> CratercountLike:
    import craterstats

    return craterstats.Cratercount(crater, area)


def extract_csfd_summary(
    inputs: ResolvedInputs,
    *,
    cratercount_factory: CratercountFactory | None = None,
) -> CsfdSummary:
    factory = cratercount_factory or _default_cratercount_factory
    try:
        count = factory(str(inputs.crater_shp), str(inputs.area_shp))
        count.apply_binning("pseudo-log")
    except SystemExit as exc:
        raise DatingError(f"Craterstats 无法读取撞击坑统计：{exc}") from exc
    except Exception as exc:
        raise DatingError(f"Craterstats 无法生成撞击坑统计：{exc}") from exc

    area = float(count.area)
    perimeter = float(count.perimeter)
    if not math.isfinite(area) or not math.isfinite(perimeter):
        raise DatingError("CSFD 面积和周长必须为有限数值")
    if area <= 0:
        raise DatingError("CSFD 统计面积必须大于零")

    keys = ("d_min", "d_max", "d_mean", "bin_width", "n", "n_event", "ncum")
    try:
        arrays = {key: list(count.binned[key]) for key in keys}
    except (KeyError, TypeError) as exc:
        raise DatingError(f"Craterstats 分箱字段缺失：{exc}") from exc
    lengths = {len(values) for values in arrays.values()}
    if len(lengths) != 1:
        raise DatingError("Craterstats 分箱数组长度不一致")

    bins: list[CsfdBin] = []
    for values in zip(*(arrays[key] for key in keys)):
        d_min, d_max, d_mean, width, weighted, event, cumulative = map(float, values)
        if not all(math.isfinite(value) for value in values):
            raise DatingError("Craterstats 分箱数据必须为有限数值")
        if d_min <= 0 or d_max <= d_min or d_mean <= 0 or width <= 0:
            raise DatingError("Craterstats 分箱直径或宽度无效")
        if weighted < 0 or event < 0 or cumulative < 0 or not event.is_integer():
            raise DatingError("Craterstats 分箱坑数无效")
        if event == 0:
            continue
        density = weighted / width / area
        uncertainty = density / math.sqrt(event)
        bins.append(
            CsfdBin(
                d_min_km=d_min,
                d_max_km=d_max,
                d_mean_km=d_mean,
                weighted_count=weighted,
                event_count=int(event),
                cumulative_count=cumulative,
                differential_density=density,
                uncertainty=uncertainty,
            )
        )
    if not bins:
        raise DatingError("Craterstats 没有生成非空 pseudo-log 分箱")
    return CsfdSummary(
        area_km2=area,
        perimeter_km=perimeter,
        total_event_count=sum(item.event_count for item in bins),
        diameter_min_km=bins[0].d_min_km,
        diameter_max_km=bins[-1].d_max_km,
        bins=tuple(bins),
    )
