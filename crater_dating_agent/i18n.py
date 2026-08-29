from __future__ import annotations

from enum import Enum


class Language(str, Enum):
    ZH = "zh"
    EN = "en"


_MESSAGES: dict[Language, dict[str, str]] = {
    Language.ZH: {
        "page_title": "月球撞击坑智能定年系统",
        "new_task": "新建定年任务",
        "language": "语言 / Language",
        "area_path": "AREA_<编号>.shp 本机绝对路径",
        "crater_path": "CRATER_<编号>.shp 本机绝对路径",
        "image_path": "原始 GeoTIFF 本机绝对路径",
        "validate_inputs": "验证输入并新建任务",
        "resume_task": "恢复已有任务",
        "start_detection": "开始自动识坑",
        "accept_automatic": "满意，直接使用自动结果",
        "revise_automatic": "不满意，导入人工修订文件",
        "manual_revision_path": "人工修订 CRATER_{case_id}.shp 的本机路径",
        "validate_manual": "校验并生成新预览",
        "accept_manual": "满意，使用人工修订结果",
        "start_dating": "生成全局 CSFD 图",
        "analyze_ranges": "调用 DeepSeek 推荐拟合区间",
        "manual_range": "手工设置拟合区间",
        "generate_final": "确认并生成最终定年结果",
        "final_result": "最终定年结果",
        "advanced_settings": "高级设置",
        "arcpy_python": "ArcPy Python 2.7",
        "model_python": "识别模型 Python",
        "model_dir": "撞击坑自动识别模型目录",
        "output_root": "任务输出根目录",
        "api_key": "DeepSeek API Key（仅保存在当前内存）",
        "case_id": "任务编号",
        "crater_count": "撞击坑数量",
        "one_km_count": "直径 ≥ 1 km",
        "diameter_span": "直径范围（km）",
        "existing_route": "已检测到撞击坑，将跳过自动识别",
        "task_dir": "独立任务目录",
        "automatic_review": "自动识坑叠加检查",
        "manual_review": "人工修订叠加检查",
        "dating": "智能区间推荐与定年",
        "global_plot": "无年龄拟合的全局 CSFD 图",
        "candidate": "候选 {index}",
        "range_km": "拟合区间（km）",
        "age_ga": "暂定年龄（Ga）",
        "reason": "推荐理由",
        "risks": "风险",
        "warning_override": "我已阅读并接受统计警告",
        "lower": "最小直径（km）",
        "upper": "最大直径（km）",
        "confirm_candidate": "选择候选 {index} 并生成最终结果",
        "status_ready": "输入验证成功，任务副本已建立。",
        "source": "当前定年数据来源",
        "source_existing": "用户提供的已有撞击坑",
        "source_automatic": "撞击坑自动识别结果",
        "source_manual": "人工修订结果",
        "process_log": "运行日志",
        "completed": "定年已完成。",
        "area_legend": "AREA_{case_id} 定年区域",
        "empty_crater_route": "CRATER 为空，将调用撞击坑自动识别模型",
        "session_phase": "当前会话状态",
        "analysis_interrupted": "上次 DeepSeek 分析被中断，可恢复到分析前并重新调用。",
        "session_failed": "当前会话失败；如已有可用阶段产物，可以恢复后继续。",
        "recover_session": "恢复到上一步并继续",
        "undo_step": "撤回上一步",
    },
    Language.EN: {
        "page_title": "Lunar Crater Intelligent Dating System",
        "new_task": "New dating task",
        "language": "语言 / Language",
        "area_path": "Local absolute path to AREA_<ID>.shp",
        "crater_path": "Local absolute path to CRATER_<ID>.shp",
        "image_path": "Local absolute path to the source GeoTIFF",
        "validate_inputs": "Validate inputs and create task",
        "resume_task": "Resume existing task",
        "start_detection": "Start automatic crater detection",
        "accept_automatic": "Accept the automatic result",
        "revise_automatic": "Import a manually revised CRATER file",
        "manual_revision_path": "Local path to revised CRATER_{case_id}.shp",
        "validate_manual": "Validate and create a new preview",
        "accept_manual": "Accept the manually revised result",
        "start_dating": "Generate global CSFD plot",
        "analyze_ranges": "Ask DeepSeek to recommend fitting ranges",
        "manual_range": "Set a fitting range manually",
        "generate_final": "Confirm and generate final dating result",
        "final_result": "Final dating result",
        "advanced_settings": "Advanced settings",
        "arcpy_python": "ArcPy Python 2.7",
        "model_python": "Detection-model Python",
        "model_dir": "Automatic crater detection model directory",
        "output_root": "Task output root",
        "api_key": "DeepSeek API Key (kept in memory only)",
        "case_id": "Case ID",
        "crater_count": "Crater count",
        "one_km_count": "Diameter ≥ 1 km",
        "diameter_span": "Diameter span (km)",
        "existing_route": "Crater records found; automatic detection will be skipped",
        "task_dir": "Isolated task directory",
        "automatic_review": "Automatic detection overlay review",
        "manual_review": "Manual revision overlay review",
        "dating": "Intelligent range recommendation and dating",
        "global_plot": "Global CSFD plot without an age fit",
        "candidate": "Candidate {index}",
        "range_km": "Fitting range (km)",
        "age_ga": "Preliminary age (Ga)",
        "reason": "Rationale",
        "risks": "Risks",
        "warning_override": "I have read and accept the statistical warnings",
        "lower": "Minimum diameter (km)",
        "upper": "Maximum diameter (km)",
        "confirm_candidate": "Choose candidate {index} and generate the final result",
        "status_ready": "Inputs validated and an isolated task copy was created.",
        "source": "Current dating data source",
        "source_existing": "Crater data supplied by the user",
        "source_automatic": "Automatic crater detection result",
        "source_manual": "Manually revised result",
        "process_log": "Process log",
        "completed": "Dating completed.",
        "area_legend": "AREA_{case_id} dating area",
        "empty_crater_route": (
            "CRATER is empty; the automatic crater detection model will run"
        ),
        "session_phase": "Current session phase",
        "analysis_interrupted": (
            "The previous DeepSeek analysis was interrupted. Restore the prior "
            "stage and retry the request."
        ),
        "session_failed": (
            "This session failed. If usable stage artifacts exist, restore and continue."
        ),
        "recover_session": "Restore previous stage and continue",
        "undo_step": "Undo previous step",
    },
}


def tr(key: str, language: Language, **values: object) -> str:
    try:
        template = _MESSAGES[language][key]
    except KeyError as exc:
        raise KeyError(f"Missing translation key: {key}") from exc
    return template.format(**values)
