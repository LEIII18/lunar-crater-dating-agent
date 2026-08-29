from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from .models import DatingError, DatingRequest, DatingResult
from .service import run_single_dating


Runner = Callable[[DatingRequest], DatingResult]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="不启动 GUI，使用 Craterstats 对一组月球撞击坑执行单次定年。"
    )
    parser.add_argument("--crater-shp", required=True, type=Path, help="CRATER_*.shp 路径")
    parser.add_argument("--area-shp", required=True, type=Path, help="配套 AREA_*.shp 路径")
    parser.add_argument("--image-tif", required=True, type=Path, help="上游遥感 TIFF 溯源路径")
    parser.add_argument("--range-min", required=True, type=float, help="拟合直径下限（km）")
    parser.add_argument("--range-max", required=True, type=float, help="拟合直径上限（km）")
    parser.add_argument("--output-dir", type=Path, help="输出根目录；默认使用项目 outputs")
    return parser


def main(argv: list[str] | None = None, *, _run: Runner = run_single_dating) -> int:
    args = build_parser().parse_args(argv)
    request = DatingRequest(
        crater_shp=args.crater_shp,
        area_shp=args.area_shp,
        image_tif=args.image_tif,
        range_min_km=args.range_min,
        range_max_km=args.range_max,
        output_dir=args.output_dir,
    )
    try:
        result = _run(request)
    except DatingError as exc:
        print(f"定年失败：{exc}", file=sys.stderr)
        return 2

    print("定年完成")
    print(
        f"年龄：{result.age.age_ga:g} Ga "
        f"(-{result.age.age_minus_ga:g}/+{result.age.age_plus_ga:g} Ga)"
    )
    print(f"CSFD 图：{result.plot_path}")
    print(f"结果 JSON：{result.result_json_path}")
    print(f"运行目录：{result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

