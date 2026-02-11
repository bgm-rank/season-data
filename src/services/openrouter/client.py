from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-2.5-flash-lite"
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# 动漫匹配系统提示（固定以最大化缓存命中）
MATCH_SYSTEM_PROMPT = '匹配MAL动漫与Bangumi候选。续作必须季数一致（2nd/第2期/II等）。输出JSON：{"id":数字或null}'


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
            if end != -1:
                return after_start[:end].strip()

    return trimmed


class OpenRouterClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self.model = model
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
        url = f"{BASE_URL}/chat/completions"

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

        raise last_error  # type: ignore[misc]

    def match_anime(
        self,
        mal_title: str,
        mal_title_ja: str | None,
        candidates: list[tuple[int, str, str | None]],
    ) -> int | None:
        """动漫匹配验证。

        返回匹配的 Bangumi ID，无匹配返回 None。

        Args:
            mal_title: MAL 英文标题
            mal_title_ja: MAL 日文标题
            candidates: [(bgm_id, name, name_cn), ...]
        """
        if not candidates:
            return None

        # 构建精简的用户输入
        parts = [f"MAL:{mal_title}"]
        if mal_title_ja:
            parts[0] += f"|{mal_title_ja}"
        parts.append("BGM:")
        for bgm_id, name, name_cn in candidates:
            line = f"{bgm_id}:{name}"
            if name_cn:
                line += f"|{name_cn}"
            parts.append(line)
        user_input = "\n".join(parts)

        request = ChatRequest(
            messages=[
                Message.system(MATCH_SYSTEM_PROMPT),
                Message.user(user_input),
            ],
            model=self.model,
        ).with_max_tokens(32)

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

        # 解析 {"id": 123} 或 {"id": null}
        json_str = extract_json(content)
        try:
            result = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON: {content} - {e}") from e

        return result.get("id")
