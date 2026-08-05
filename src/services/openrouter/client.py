from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from loguru import logger

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-2.5-flash-lite"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# prompt 丰富度，env LLM_PROMPT_MODE 控制。low 是默认值，行为与增强前逐字符一致；
# high 把 MAL / BGM 两侧已有但没用上的字段全喂进去，input token 约 2.5~3 倍。
PROMPT_MODE_LOW = "low"
PROMPT_MODE_HIGH = "high"
DEFAULT_PROMPT_MODE = PROMPT_MODE_LOW

SUMMARY_MAX_CHARS = 80
SUMMARY_MAX_CHARS_HIGH = 240
SYNOPSIS_MAX_CHARS_HIGH = 300
MAX_TAGS_HIGH = 5
REASON_MAX_CHARS = 60

# 输出上限。输出按实际生成量计费，上限放宽本身不花钱；被 finish_reason=length
# 砍断才是纯亏——token 全付了、JSON 解析失败、结果按「无匹配」丢掉，还得重跑。
# 推理模型的 reasoning_tokens 也吃这个额度且完全不可控：gemini-3.6-flash 在
# suggest_search 这种「想不出关键词」的输入上实测能把 512 吃满（真正的 JSON 只有
# 二三十 token）。所以这里一律按 reasoning 的最坏情况留余量，别再往下调。
MAX_TOKENS_MATCH = 2048
MAX_TOKENS_MATCH_HIGH = 3072
MAX_TOKENS_SUGGEST = 2048

# 动漫匹配系统提示（固定以最大化缓存命中）
MATCH_SYSTEM_PROMPT = (
    "匹配MAL动漫与Bangumi候选。续作必须季数一致（2nd/第2期/II等）。"
    "MAL格式：英文名|日文名|媒体类型。BGM候选格式：bgm_id:日文名|中文名|首播日期|简介(可选)。"
    "输出JSON数组，每个候选含bgm_id和confidence(0.0-1.0)，无匹配输出空数组："
    '[{"bgm_id":数字,"confidence":0.9}]'
)

# high 模式的匹配提示（同样写死为常量以命中 prompt 缓存）
MATCH_SYSTEM_PROMPT_HIGH = (
    "匹配MAL动漫与Bangumi候选。判定规则：\n"
    "1.续作季数必须一致（2nd/第2期/II等），季数不同判否。\n"
    "2.首播日期应接近，相差超过半年需有同一作品不同发行的确证才可匹配。\n"
    "3.媒体类型与BGM platform冲突（movie对TV连载、TV对剧场版）判否。\n"
    "4.简介须描述同一作品：角色、设定、剧情一致；同系列的不同作品判否。\n"
    "MAL格式：英文名|日文名|媒体类型|首播日期|集数|原作|制作公司|简介\n"
    "BGM候选格式：bgm_id:日文名|中文名|首播日期|platform|tags|简介\n"
    "（字段缺失时该段省略，不留空管道）\n"
    "输出JSON数组，按confidence降序，无匹配输出空数组：\n"
    '[{"bgm_id":数字,"confidence":0.9,"reason":"20字以内的判定依据"}]'
)

# 搜索关键词提取系统提示
SUGGEST_SYSTEM_PROMPT = (
    "从MAL动画标题提取用于Bangumi(日本动画数据库)搜索的关键词。只返回JSON。\n"
    "规则:\n"
    '1.JA标题含韩文(한글)或全中文→{"skip":true}\n'
    "2.否则从JA标题提取关键词:去掉劇場版/映画前缀、续集标记(第N期/Season)、副标题(～xx～/-xx-/『』)，"
    '保留最具辨识度的日文部分→{"keywords":["关键词"]}\n'
    "例:\n"
    'JA:新劇場版 銀魂 -吉原大炎上-→{"keywords":["銀魂 吉原大炎上"]}\n'
    'JA:프린세스 캐치! 티니핑→{"skip":true}\n'
    'JA:劇場版『ゾンビランドサガ ゆめぎんがパラダイス』→{"keywords":["ゾンビランドサガ"]}'
)


@dataclass
class MalBrief:
    """喂给匹配 prompt 的 MAL 侧信息。

    前三个字段 low / high 都用，其余只在 high 模式进 prompt。
    """

    title: str
    title_ja: str | None = None
    media_type: str | None = None
    start_date: str | None = None
    num_episodes: int | None = None
    source: str | None = None
    studios: list[str] | None = None
    synopsis: str | None = None


@dataclass
class BgmCandidate:
    """喂给匹配 prompt 的单个 BGM 候选。

    `platform` / `tags` 只在 high 模式进 prompt；搜索结果常缺这两项，
    调用方会用 `bgm_subject` 里已同步的详情补齐（见 processor）。
    """

    bgm_id: int
    name: str
    name_cn: str | None = None
    date: str | None = None
    summary: str | None = None
    platform: str | None = None
    tags: list[str] | None = None


@dataclass
class Message:
    """聊天消息。"""

    role: str  # "system" | "user" | "assistant"
    content: str

    @staticmethod
    def system(content: str) -> Message:
        return Message(role="system", content=content)

    @staticmethod
    def user(content: str) -> Message:
        return Message(role="user", content=content)

    @staticmethod
    def assistant(content: str) -> Message:
        return Message(role="assistant", content=content)

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatRequest:
    """聊天请求。"""

    messages: list[Message]
    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    max_tokens: int = 256
    stream: bool = False

    def with_max_tokens(self, max_tokens: int) -> ChatRequest:
        self.max_tokens = max_tokens
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [m.to_dict() for m in self.messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": self.stream,
        }


@dataclass
class Usage:
    """Token 使用统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Choice:
    """响应选项。"""

    index: int
    message: Message
    finish_reason: str | None = None


@dataclass
class ChatResponse:
    """聊天响应。"""

    id: str
    model: str
    choices: list[Choice]
    usage: Usage = field(default_factory=Usage)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ChatResponse:
        choices = []
        for c in data.get("choices", []):
            msg = c.get("message", {})
            choices.append(
                Choice(
                    index=c.get("index", 0),
                    message=Message(
                        role=msg.get("role", "assistant"),
                        content=msg.get("content", ""),
                    ),
                    finish_reason=c.get("finish_reason"),
                )
            )
        usage_data = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        return ChatResponse(
            id=data.get("id", ""),
            model=data.get("model", ""),
            choices=choices,
            usage=usage,
        )

    def content(self) -> str | None:
        """获取第一条响应内容。"""
        if self.choices:
            return self.choices[0].message.content
        return None


def _warn_if_truncated(where: str, response: ChatResponse) -> None:
    """输出被 max_tokens 砍断时明确报警。

    截断的后果是 JSON 解析失败 → 静默降级成「无匹配」，钱花了活没干。
    推理模型（reasoning_tokens 也占 max_tokens）特别容易踩到，不出声就查不出来。
    """
    if response.choices and response.choices[0].finish_reason == "length":
        logger.warning(
            "{}: 输出被 max_tokens 截断（模型 {}，completion {} tokens），结果不可用",
            where,
            response.model,
            response.usage.completion_tokens,
        )


def _squash(text: str) -> str:
    """把简介压成单行——BGM summary 和 MAL synopsis 都带换行，会撑破一行一候选的格式。"""
    return " ".join(text.split())


def extract_json(content: str) -> str:
    """从 LLM 响应中提取 JSON 内容。

    处理以下情况：
    - 纯 JSON: `{"id": 123}`
    - markdown 代码块: ```json\n{"id": 123}\n```
    - 带语言标记或不带: ```\n{"id": 123}\n```
    """
    trimmed = content.strip()

    if trimmed.startswith("```"):
        # 找到第一个换行符后的内容
        start = trimmed.find("\n")
        if start != -1:
            after_start = trimmed[start + 1 :]
            end = after_start.rfind("```")
            # 收尾的 ``` 可能不存在（模型漏写，或输出被 max_tokens 截断），
            # 这时也要把开头的围栏剥掉，别整段当成 JSON 去解析
            return after_start[:end].strip() if end != -1 else after_start.strip()

    return trimmed


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = BASE_URL,
        prompt_mode: str | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        # env 在这里读而不是在三处 provider 选择块里各读一遍；各入口都已先跑 load_dotenv()
        mode = (prompt_mode or os.getenv("LLM_PROMPT_MODE") or DEFAULT_PROMPT_MODE).strip().lower()
        if mode not in (PROMPT_MODE_LOW, PROMPT_MODE_HIGH):
            logger.warning("未知的 LLM_PROMPT_MODE={!r}，退回 {}", mode, DEFAULT_PROMPT_MODE)
            mode = DEFAULT_PROMPT_MODE
        self.prompt_mode = mode
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> OpenRouterClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def chat(self, request: ChatRequest) -> ChatResponse:
        """发送聊天请求（带重试逻辑）。"""
        url = f"{self.base_url}/chat/completions"

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.client.post(url, json=request.to_dict())
                if not resp.is_success:
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}: {resp.text}",
                        request=resp.request,
                        response=resp,
                    )
                return ChatResponse.from_dict(resp.json())
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "请求失败 ({}), 第 {}/{} 次重试...",
                        e,
                        attempt,
                        MAX_RETRIES,
                    )
                    time.sleep(RETRY_DELAY)

        # mypy can't prove last_error is non-None here: loop runs MAX_RETRIES times and
        # always assigns last_error in the except branch, but flow analysis doesn't track that.
        raise last_error  # type: ignore[misc]

    def _build_match_input(self, mal: MalBrief, candidates: list[BgmCandidate]) -> str:
        """组装匹配 prompt 的用户输入。

        low 分支与增强前逐字符一致，改动只发生在 high 分支。
        """
        high = self.prompt_mode == PROMPT_MODE_HIGH
        summary_max = SUMMARY_MAX_CHARS_HIGH if high else SUMMARY_MAX_CHARS

        parts = [f"MAL:{mal.title}"]
        if mal.title_ja:
            parts[0] += f"|{mal.title_ja}"
        if mal.media_type:
            parts[0] += f"|{mal.media_type}"
        if high:
            if mal.start_date:
                parts[0] += f"|{mal.start_date}"
            if mal.num_episodes:
                parts[0] += f"|{mal.num_episodes}话"
            if mal.source:
                parts[0] += f"|{mal.source}"
            if mal.studios:
                parts[0] += f"|{'、'.join(mal.studios)}"
            if mal.synopsis:
                parts[0] += f"|{_squash(mal.synopsis)[:SYNOPSIS_MAX_CHARS_HIGH]}"

        parts.append("BGM:")
        for c in candidates:
            line = f"{c.bgm_id}:{c.name}"
            if c.name_cn:
                line += f"|{c.name_cn}"
            if c.date:
                line += f"|{c.date}"
            if high:
                if c.platform:
                    line += f"|{c.platform}"
                if c.tags:
                    line += f"|{'、'.join(c.tags[:MAX_TAGS_HIGH])}"
            if c.summary:
                line += f"|{_squash(c.summary)[:summary_max] if high else c.summary[:summary_max]}"
            parts.append(line)

        return "\n".join(parts)

    def match_anime(
        self,
        mal: MalBrief,
        candidates: list[BgmCandidate],
    ) -> list[dict[str, Any]]:
        """动漫匹配验证，返回带 confidence 的候选列表。

        返回 [{"bgm_id": int, "confidence": float | None, "reason": str | None}]，无匹配返回 []。
        `reason` 只有 high 模式的 prompt 会要求模型输出，low 模式一般是 None。
        """
        if not candidates:
            return []

        high = self.prompt_mode == PROMPT_MODE_HIGH
        user_input = self._build_match_input(mal, candidates)

        request = ChatRequest(
            messages=[
                Message.system(MATCH_SYSTEM_PROMPT_HIGH if high else MATCH_SYSTEM_PROMPT),
                Message.user(user_input),
            ],
            model=self.model,
        ).with_max_tokens(MAX_TOKENS_MATCH_HIGH if high else MAX_TOKENS_MATCH)

        response = self.chat(request)
        content = response.content()
        if content is None:
            raise RuntimeError("No response content")

        logger.debug(
            "anime match: input={}, output={}, tokens={}",
            user_input,
            content,
            response.usage.total_tokens,
        )
        _warn_if_truncated("match_anime", response)

        json_str = extract_json(content)
        if not json_str:
            logger.warning("match_anime: 模型返回空响应")
            return []
        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("match_anime: 无效 JSON: {!r}", content)
            return []

        if not isinstance(result, list):
            return []

        out: list[dict[str, Any]] = []
        for item in result:
            bgm_id = item.get("bgm_id")
            confidence = item.get("confidence")
            reason = item.get("reason")
            if bgm_id is None:
                continue
            out.append(
                {
                    "bgm_id": int(bgm_id),
                    "confidence": float(confidence) if confidence is not None else None,
                    "reason": str(reason)[:REASON_MAX_CHARS] if reason else None,
                }
            )
        return out

    def suggest_search(
        self,
        mal_title_ja: str,
        media_type: str,
    ) -> dict[str, Any]:
        """让 LLM 提取搜索关键词或判断是否跳过。

        返回:
            {"keywords": ["关键词1", ...]} — 建议的搜索关键词
            {"skip": true} — 非日本动画，建议跳过
        """
        user_input = f"JA: {mal_title_ja}\nType: {media_type}"

        request = ChatRequest(
            messages=[
                Message.system(SUGGEST_SYSTEM_PROMPT),
                Message.user(user_input),
            ],
            model=self.model,
        ).with_max_tokens(MAX_TOKENS_SUGGEST)

        response = self.chat(request)
        content = response.content()
        if content is None:
            return {"keywords": []}

        logger.debug(
            "suggest search: input={}, output={}, tokens={}",
            user_input,
            content,
            response.usage.total_tokens,
        )
        _warn_if_truncated("suggest_search", response)

        json_str = extract_json(content)
        try:
            return cast(dict[str, Any], json.loads(json_str))
        except json.JSONDecodeError:
            logger.warning("suggest_search: 无效 JSON: {!r}", content)
            return {"keywords": []}
