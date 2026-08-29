from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from typing import Mapping
from typing import Callable

from PIL import Image, UnidentifiedImageError

from .agent_models import AgentSession, RangeProposal
from .i18n import Language
from .models import DatingError
from .range_candidates import load_agent_config, parse_proposal_json
from .session_store import append_transcript
from .tool_registry import ToolRegistry


VISION_MODEL = "deepseek-v4-flash-vision-exp"
MAX_INLINE_IMAGE_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 90.0
    max_retries: int = 1

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DeepSeekSettings":
        values = os.environ if environ is None else environ
        config = load_agent_config()
        api_key = values.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise DatingError("未设置 DEEPSEEK_API_KEY，无法调用 DeepSeek")
        return cls(
            api_key=api_key,
            base_url=values.get("DEEPSEEK_BASE_URL", config.default_base_url).strip(),
            model=values.get("DEEPSEEK_MODEL", config.default_model).strip(),
            timeout_seconds=float(
                values.get("DEEPSEEK_TIMEOUT_SECONDS", config.api_timeout_seconds)
            ),
            max_retries=int(
                values.get("DEEPSEEK_MAX_RETRIES", config.api_max_retries)
            ),
        )


class DeepSeekRangeClient:
    def __init__(
        self,
        settings: DeepSeekSettings,
        *,
        sdk_client=None,
        progress_callback: Callable[[str], None] | None = None,
        response_language: Language = Language.ZH,
    ) -> None:
        self.settings = settings
        self._progress = progress_callback or (lambda message: None)
        self.response_language = response_language
        if sdk_client is None:
            from openai import OpenAI

            sdk_client = OpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
                timeout=settings.timeout_seconds,
                max_retries=settings.max_retries,
            )
        self._client = sdk_client

    @staticmethod
    def _json_content(content: str) -> str:
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1 : -3].strip()
        return stripped

    def _save_raw_attempt(self, session, attempt: int, content: str) -> None:
        if not hasattr(session, "session_dir"):
            return
        path = session.session_dir / "llm" / f"raw_response_attempt_{attempt}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"model": self.settings.model, "content": content},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def _global_plot_data_url(self, session: AgentSession) -> str:
        if self.settings.model != VISION_MODEL:
            raise DatingError(
                f"全局 CSFD 图需要 DeepSeek 视觉模型 {VISION_MODEL}，"
                f"当前模型为 {self.settings.model}"
            )
        try:
            state_path = Path(session.state_path)
            if state_path.is_symlink():
                raise DatingError("会话状态文件不能是符号链接")
            trusted_session_dir = state_path.resolve(strict=True).parent
            stored_session_dir = Path(session.session_dir).resolve(strict=True)
            if stored_session_dir != trusted_session_dir:
                raise DatingError("会话目录与 session_state.json 实际位置不一致")
            overview_candidate = trusted_session_dir / "overview"
            if overview_candidate.is_symlink():
                raise DatingError("全局图目录不能是符号链接")
            overview_dir = overview_candidate.resolve(strict=True)
            if overview_dir.parent != trusted_session_dir:
                raise DatingError("全局图目录超出当前会话")
            plot_candidate = overview_dir / f"{session.case_id}_global_csfd.png"
            if plot_candidate.is_symlink():
                raise DatingError("全局 CSFD PNG 不能是符号链接")
            plot_path = plot_candidate.resolve(strict=True)
            if plot_path.parent != overview_dir:
                raise DatingError("全局 CSFD PNG 超出当前会话")
            image = plot_path.read_bytes()
        except DatingError:
            raise
        except OSError as exc:
            raise DatingError(f"无法安全读取全局 CSFD PNG：{exc}") from exc
        if len(image) > MAX_INLINE_IMAGE_BYTES:
            raise DatingError(
                f"全局 CSFD PNG 超过 DeepSeek Base64 单图 32 MiB 限制：{plot_path}"
            )
        try:
            with Image.open(BytesIO(image)) as decoded:
                image_format = decoded.format
                width, height = decoded.size
                decoded.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
            raise DatingError(f"全局 CSFD 图不是有效 PNG：{plot_path}") from exc
        if image_format != "PNG":
            raise DatingError(f"全局 CSFD 图实际格式不是 PNG：{plot_path}")
        if width > 8192 or height > 8192:
            raise DatingError(
                f"全局 CSFD PNG 尺寸超过 DeepSeek 8192 像素边长限制："
                f"{width}×{height}"
            )
        encoded = base64.b64encode(image).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _assistant_message(message) -> dict[str, object]:
        if hasattr(message, "model_dump"):
            data = message.model_dump()
        else:
            data = {
                "role": "assistant",
                "content": getattr(message, "content", None),
                "tool_calls": getattr(message, "tool_calls", None),
                "reasoning_content": getattr(message, "reasoning_content", None),
            }
        data["role"] = "assistant"
        if data.get("content") is None:
            data["content"] = ""
        return data

    def analyze(
        self,
        session: AgentSession,
        registry: ToolRegistry,
        context: object,
    ) -> RangeProposal:
        prompt = files("crater_dating_agent").joinpath(
            "prompts/range_selector.txt"
        ).read_text(encoding="utf-8")
        image_url = self._global_plot_data_url(session)
        language_instruction = (
            "Write overall_observation, reason, and risks in English. "
            if self.response_language is Language.EN
            else "请使用中文撰写 overall_observation、reason 和 risks。"
        )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请结合所附全局 CSFD 图与工具返回的结构化 CSFD 数据分析拟合区间。"
                            "图像用于识别趋势、转折和异常形态，精确数值、坑数与分箱连续性"
                            "以结构化数据为准；两者冲突时必须说明。请先调用允许的工具读取"
                            "结构化 CSFD 数据，再给出候选区间 JSON。"
                            f"{language_instruction}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url, "detail": "original"},
                    },
                ],
            },
        ]
        repair_attempts = load_agent_config().proposal_repair_attempts
        repairs_used = 0
        request_number = 0
        final_attempt = 0
        for _ in range(20):
            request_number += 1
            self._progress(f"正在调用 DeepSeek（第 {request_number} 次请求）……")
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    tools=registry.schemas_for(session.phase),
                    response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": "enabled"}},
                )
            except Exception as exc:
                raise DatingError(
                    f"DeepSeek API 调用失败（模型 {self.settings.model}）：{type(exc).__name__}"
                ) from exc
            self._progress(f"DeepSeek 已返回第 {request_number} 次响应。")
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                messages.append(self._assistant_message(message))
                for call in tool_calls:
                    try:
                        arguments = json.loads(call.function.arguments)
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise DatingError(f"DeepSeek 工具参数不是有效 JSON：{call.function.name}") from exc
                    result = registry.execute(
                        call.function.name, arguments, context, session.phase
                    )
                    if hasattr(session, "transcript_path"):
                        append_transcript(
                            session,
                            {"event": "tool_call", "id": call.id,
                             "tool": call.function.name, "arguments": arguments},
                        )
                        append_transcript(
                            session,
                            {"event": "tool_result", "id": call.id,
                             "tool": call.function.name, "result": result},
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(
                                result, ensure_ascii=False, separators=(",", ":")
                            ),
                        }
                    )
                continue
            content = getattr(message, "content", None) or ""
            final_attempt += 1
            self._save_raw_attempt(session, final_attempt, content)
            try:
                proposal = parse_proposal_json(self._json_content(content))
                if hasattr(session, "session_dir"):
                    raw_path = session.session_dir / "llm" / "raw_response.json"
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_text(
                        json.dumps(
                            {"model": self.settings.model, "content": content},
                            ensure_ascii=False, indent=2,
                        ) + "\n",
                        encoding="utf-8",
                    )
                return proposal
            except DatingError:
                if repairs_used >= repair_attempts:
                    raise
                repairs_used += 1
                messages.append(self._assistant_message(message))
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "上一个响应不符合候选 JSON 契约。请只返回修正后的 JSON，"
                            "精确使用以下字段：candidates；每个候选使用 range_min_km、"
                            "range_max_km、confidence（high、medium 或 low）、reason、risks；"
                            "顶层还必须包含 overall_observation 和 needs_human_review=true。"
                        ),
                    }
                )
        raise DatingError("DeepSeek 工具调用轮次超过限制")
