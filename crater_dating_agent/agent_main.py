from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from .agent_models import AgentRequest, SessionPhase
from .agent_service import (
    analyze_session,
    cancel_session,
    complete_confirmed_session,
    confirm_candidate,
    confirm_manual_range,
    preview_manual_range,
    prepare_agent_session,
)
from .deepseek_client import DeepSeekRangeClient, DeepSeekSettings
from .models import DatingError
from .session_store import load_session


class AgentCliServices:
    def __init__(self, output_fn: Callable[[str], None] = print) -> None:
        self._output_fn = output_fn

    def start(self, request: AgentRequest):
        return prepare_agent_session(request)

    def resume(self, path: Path):
        return load_session(path)

    def analyze(self, path: Path):
        client = DeepSeekRangeClient(
            DeepSeekSettings.from_env(), progress_callback=self._output_fn
        )
        return analyze_session(path, client=client)

    confirm = staticmethod(confirm_candidate)
    preview_manual = staticmethod(preview_manual_range)
    confirm_manual = staticmethod(confirm_manual_range)
    cancel = staticmethod(cancel_session)
    complete = staticmethod(complete_confirmed_session)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepSeek 辅助选择 CSFD 拟合区间，并经人工确认后定年。")
    parser.add_argument("--crater-shp", type=Path)
    parser.add_argument("--area-shp", type=Path)
    parser.add_argument("--image-tif", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume-session", type=Path, help="已有 session_state.json")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    services=None,
) -> int:
    args = build_parser().parse_args(argv)
    services = services or AgentCliServices(output_fn)
    try:
        if args.resume_session:
            session = services.resume(args.resume_session)
        else:
            if not all((args.crater_shp, args.area_shp, args.image_tif)):
                raise DatingError("新会话必须提供 CRATER、AREA 和 TIFF")
            session = services.start(AgentRequest(
                args.crater_shp, args.area_shp, args.image_tif, args.output_dir
            ))
        if session.phase is SessionPhase.OVERVIEW_READY:
            plot = next((session.session_dir / "overview").glob("*_global_csfd.png"))
            output_fn(f"全局 CSFD 图：{plot}")
            output_fn(f"可恢复会话：{session.state_path}")
            session = services.analyze(session.state_path)
        if session.phase is SessionPhase.CONFIRMED:
            completed = services.complete(session.state_path)
            output_fn("最终定年完成")
            output_fn(f"运行目录：{completed.session_dir / 'final'}")
            return 0
        if session.phase is not SessionPhase.AWAITING_CONFIRMATION:
            raise DatingError(f"会话当前状态不能确认区间：{session.phase.value}")

        plot = next((session.session_dir / "overview").glob("*_global_csfd.png"))
        output_fn(f"全局 CSFD 图：{plot}")
        data = json.loads((session.session_dir / "llm" / "range_candidates.json").read_text(encoding="utf-8"))
        observation = data.get("overall_observation")
        if observation:
            output_fn(f"总体观察：{observation}")
        for index, item in enumerate(data["candidates"], 1):
            output_fn(
                f"候选 {index}：{item['range_min_km']:g}–{item['range_max_km']:g} km，"
                f"{item['event_count']} 个坑，{item['occupied_bin_count']} 个非空 bin；"
                f"理由：{item['reason']}"
            )
            if item["risks"]:
                output_fn("风险：" + "；".join(item["risks"]))
            if item["warnings"]:
                output_fn("警告：" + ", ".join(item["warnings"]))
            preview = item.get("preview")
            if preview:
                output_fn(
                    "候选预览，未经人工确认："
                    f"{preview['age_ga']:g} Ga "
                    f"（{preview['age_lower_ga']:g}–{preview['age_upper_ga']:g} Ga）"
                )
                output_fn(f"候选拟合图：{preview['plot_path']}")

        candidate_count = len(data["candidates"])
        if candidate_count:
            candidate_label = "1" if candidate_count == 1 else f"1–{candidate_count}"
            choice_prompt = f"请选择 {candidate_label}，输入 e 手工设置，输入 q 取消："
        else:
            choice_prompt = "没有有效候选；输入 e 手工设置，输入 q 取消："
        choice = input_fn(choice_prompt).strip().lower()
        if choice == "q":
            services.cancel(session.state_path)
            output_fn("已取消，未执行最终定年。")
            return 0
        manual_range: tuple[float, float] | None = None
        selection: int | None = None
        override = False
        if choice == "e":
            lower = float(input_fn("输入 range 下限（km）："))
            upper = float(input_fn("输入 range 上限（km）："))
            preview = services.preview_manual(session.state_path, lower, upper)
            manual_range = (preview.range_min_km, preview.range_max_km)
            output_fn(
                f"人工区间对齐为：{preview.range_min_km:g}–{preview.range_max_km:g} km"
            )
            if preview.warnings:
                output_fn("警告：" + ", ".join(preview.warnings))
                override = input_fn("该区间低于统计阈值，仍要覆盖警告吗？[y/N]：").strip().lower() == "y"
                if not override:
                    output_fn("未覆盖统计警告，未确认区间。")
                    return 0
        else:
            if not choice.isdigit() or not 1 <= int(choice) <= candidate_count:
                raise DatingError("候选编号无效")
            selection = int(choice)
            selected = data["candidates"][selection - 1]
            if selected["warnings"]:
                override = input_fn("该区间低于统计阈值，仍要覆盖警告吗？[y/N]：").strip().lower() == "y"
        if input_fn("确认使用该区间执行最终定年吗？[y/N]：").strip().lower() != "y":
            output_fn("未确认区间，未执行最终定年。")
            return 0
        if manual_range is not None:
            session = services.confirm_manual(
                session.state_path, manual_range[0], manual_range[1],
                warning_override=override,
            )
        else:
            session = services.confirm(
                session.state_path, selection, warning_override=override
            )
        completed = services.complete(session.state_path)
        output_fn("最终定年完成")
        output_fn(f"运行目录：{completed.session_dir / 'final'}")
        return 0
    except (DatingError, ValueError, IndexError, StopIteration) as exc:
        output_fn(f"智能体运行失败：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
