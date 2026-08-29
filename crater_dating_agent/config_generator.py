from __future__ import annotations

import shlex
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import yaml

from .models import DatingError, DatingRequest, ResolvedInputs


@dataclass(frozen=True)
class ScientificConfig:
    schema_version: int
    body: str
    chronology_label: str
    chronology_cli: str
    epochs_label: str
    epochs_cli: str
    equilibrium: str | None
    presentation: str
    binning: str
    fit_type: str
    fit_symbol: str
    overview_name: str
    overview_type: str
    overview_symbol: str
    formats: tuple[str, ...]


def load_scientific_config() -> ScientificConfig:
    resource = files("crater_dating_agent").joinpath("configs/moon_neukum.yaml")
    try:
        data = yaml.safe_load(resource.read_text(encoding="utf-8"))
        return ScientificConfig(
            schema_version=int(data["schema_version"]),
            body=str(data["body"]),
            chronology_label=str(data["chronology_system"]["label"]),
            chronology_cli=str(data["chronology_system"]["cli"]),
            epochs_label=str(data["epochs"]["label"]),
            epochs_cli=str(data["epochs"]["cli"]),
            equilibrium=(
                None if data.get("equilibrium") is None else str(data["equilibrium"])
            ),
            presentation=str(data["presentation"]),
            binning=str(data["binning"]),
            fit_type=str(data["fit"]["type"]),
            fit_symbol=str(data["fit"]["symbol"]),
            overview_name=str(data["overview"]["name"]),
            overview_type=str(data["overview"]["type"]),
            overview_symbol=str(data["overview"]["symbol"]),
            formats=tuple(str(item) for item in data["formats"]),
        )
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise DatingError(f"月球年代学配置无效：{exc}") from exc


def _format_number(value: float) -> str:
    return format(value, ".12g")


def render_cs(
    request: DatingRequest,
    inputs: ResolvedInputs,
    output_stem: Path,
    config: ScientificConfig | None = None,
) -> str:
    config = config or load_scientific_config()
    source = str(inputs.crater_shp)
    fit = ",".join(
        (
            f"source={source}",
            f"range=[{_format_number(request.range_min_km)},{_format_number(request.range_max_km)}]",
            f"type={config.fit_type}",
            f"binning={config.binning}",
            f"psym={config.fit_symbol}",
        )
    )
    overview = ",".join(
        (
            f"source={source}",
            f"name={config.overview_name}",
            f"type={config.overview_type}",
            f"binning={config.binning}",
            f"psym={config.overview_symbol}",
        )
    )
    lines = (
        f"-o {shlex.quote(str(output_stem))}",
        f"-f {' '.join(config.formats)}",
        f"-cs {config.chronology_cli}",
        f"-ep {config.epochs_cli}",
        f"-pr {config.presentation}",
        f"-p {shlex.quote(fit)}",
        f"-p {shlex.quote(overview)}",
    )
    return "\n".join(lines) + "\n"
