"""
V14-B LLM Client 多 Provider 抽象层

支持:
  - AnthropicClient  (claude-sonnet-4-6)
  - OpenAIClient     (gpt-4o / o3-mini)
  - OllamaClient     (本地 qwen2.5:14b / llama3.2:latest)
  - DoubaoClient     (豆包 doubao-seed-2-0-pro-260215)

使用方法:
    client = LLMClient.from_env()
    result = client.extract("你的 prompt", max_tokens=1024)

环境变量:
    LLM_PROVIDER=anthropic|openai|ollama|doubao
    ANTHROPIC_API_KEY=...
    OPENAI_API_KEY=...
    OLLAMA_BASE_URL=http://localhost:11434
    DOUBAO_API_KEY=...
    DOUBAO_API_ENDPOINT=https://ark.cn-beijing.volces.com/api/v3/responses
"""
from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Optional

try:
    import httpx
    _HTTPX_TIMEOUT = httpx.Timeout(connect=15.0, read=90.0, write=30.0, pool=15.0)
except ImportError:
    _HTTPX_TIMEOUT = 90.0

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 成本追踪器
# ---------------------------------------------------------------------------

class CostTracker:
    """全局 token 计数 + 成本估算"""

    def __init__(self) -> None:
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.provider: str = "unknown"

    def record(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

    def estimate_usd(self) -> float:
        from echelon.v14b.config import TOKEN_COST
        if self.provider not in TOKEN_COST:
            return 0.0
        rates = TOKEN_COST[self.provider]
        return (
            self.total_input_tokens  * rates["input"]  / 1_000_000
            + self.total_output_tokens * rates["output"] / 1_000_000
        )

    def summary(self) -> str:
        usd = self.estimate_usd()
        return (
            f"provider={self.provider} "
            f"input_tokens={self.total_input_tokens:,} "
            f"output_tokens={self.total_output_tokens:,} "
            f"est_cost=${usd:.4f}"
        )


# 全局单例
_global_tracker = CostTracker()


def get_cost_tracker() -> CostTracker:
    return _global_tracker


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

class BaseLLMClient(ABC):
    """统一 LLM 接口基类"""

    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self._tracker = _global_tracker

    @abstractmethod
    def _call(self, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        """
        子类实现原始调用。

        Returns:
            (response_text, input_tokens, output_tokens)
        """
        ...

    def extract(self, prompt: str, max_tokens: int = 1024) -> str:
        """
        带指数退避重试的调用接口。

        Args:
            prompt:     提示词
            max_tokens: 最大输出 token 数

        Returns:
            LLM 响应文本
        """
        call_timeout = float(os.environ.get("V14B_LLM_CALL_TIMEOUT", "120"))
        delay = self.initial_delay
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self._call, prompt, max_tokens)
                    text, in_tok, out_tok = future.result(timeout=call_timeout)
                self._tracker.record(in_tok, out_tok)
                return text
            except FuturesTimeoutError as exc:
                last_exc = APIError(f"LLM call timed out after {call_timeout}s")
                wait = min(delay * (2 ** (attempt - 1)), self.max_delay)
                logger.warning(
                    "LLM timeout (attempt %d/%d), waiting %.1fs",
                    attempt, self.max_retries, wait,
                )
                time.sleep(wait)
            except RateLimitError as exc:
                last_exc = exc
                wait = min(delay * (2 ** (attempt - 1)), self.max_delay)
                logger.warning(
                    "Rate limit (attempt %d/%d), waiting %.1fs: %s",
                    attempt, self.max_retries, wait, exc,
                )
                time.sleep(wait)
            except (APIError, ConnectionError) as exc:
                last_exc = exc
                wait = min(delay * (2 ** (attempt - 1)), self.max_delay)
                logger.warning(
                    "API error (attempt %d/%d), waiting %.1fs: %s",
                    attempt, self.max_retries, wait, exc,
                )
                time.sleep(wait)

        raise last_exc or RuntimeError("LLM call failed after all retries")

    def extract_json(self, prompt: str, max_tokens: int = 1024) -> dict:
        """
        调用 LLM 并解析 JSON 响应。

        Returns:
            解析后的 dict,失败时返回空 dict
        """
        import re
        text = self.extract(prompt, max_tokens=max_tokens)
        # 去除 markdown code fences
        cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning("JSON parse failed: %s", text[:200])
            return {}


# ---------------------------------------------------------------------------
# 异常类
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """API 速率限制"""


class APIError(Exception):
    """API 通用错误"""


# ---------------------------------------------------------------------------
# Anthropic Provider
# ---------------------------------------------------------------------------

class AnthropicClient(BaseLLMClient):
    """
    Anthropic Claude 客户端 (claude-sonnet-4-6)

    环境变量: ANTHROPIC_API_KEY
    """

    def __init__(self, model: Optional[str] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        from echelon.v14b.config import ANTHROPIC_MODEL
        self.model = model or ANTHROPIC_MODEL
        self._tracker.provider = "anthropic"

        try:
            import anthropic as _anthropic
            self._client = _anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY")
            )
        except ImportError as exc:
            raise ImportError(
                "anthropic SDK not installed. Run: pip install anthropic"
            ) from exc

    def _call(self, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        import anthropic

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            return text, in_tok, out_tok

        except anthropic.RateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
        except anthropic.APIError as exc:
            raise APIError(str(exc)) from exc


# ---------------------------------------------------------------------------
# OpenAI Provider
# ---------------------------------------------------------------------------

class OpenAIClient(BaseLLMClient):
    """
    OpenAI GPT-4o / o3-mini 客户端

    环境变量: OPENAI_API_KEY
    """

    def __init__(self, model: Optional[str] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        from echelon.v14b.config import OPENAI_MODEL
        self.model = model or OPENAI_MODEL
        cost_key = "openai_o3mini" if "o3" in self.model else "openai_gpt4o"
        self._tracker.provider = cost_key

        try:
            import openai as _openai
            self._client = _openai.OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY")
            )
        except ImportError as exc:
            raise ImportError(
                "openai SDK not installed. Run: pip install openai"
            ) from exc

    def _call(self, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        import openai

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content or ""
            in_tok = response.usage.prompt_tokens if response.usage else 0
            out_tok = response.usage.completion_tokens if response.usage else 0
            return text, in_tok, out_tok

        except openai.RateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
        except openai.APIError as exc:
            raise APIError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Ollama Provider
# ---------------------------------------------------------------------------

class OllamaClient(BaseLLMClient):
    """
    Ollama 本地模型客户端 (qwen2.5:14b / llama3.2:latest)

    环境变量: OLLAMA_BASE_URL (默认 http://localhost:11434)
    """

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        from echelon.v14b.config import OLLAMA_MODEL, OLLAMA_BASE_URL
        self.model = model or os.environ.get("OLLAMA_MODEL", OLLAMA_MODEL)
        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL", OLLAMA_BASE_URL)
        self._tracker.provider = "ollama"

        try:
            import httpx
            self._http = httpx.Client(base_url=self.base_url, timeout=_HTTPX_TIMEOUT)
        except ImportError as exc:
            raise ImportError(
                "httpx not installed. Run: pip install httpx"
            ) from exc

    def _call(self, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        try:
            resp = self._http.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "")
            # Ollama 不提供精确 token 计数,用字符估算
            in_tok = len(prompt) // 4
            out_tok = len(text) // 4
            return text, in_tok, out_tok
        except Exception as exc:
            if "429" in str(exc):
                raise RateLimitError(str(exc)) from exc
            raise APIError(f"Ollama error: {exc}") from exc

    def __del__(self):
        try:
            self._http.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Doubao Provider
# ---------------------------------------------------------------------------

class DoubaoClient(BaseLLMClient):
    """
    豆包 (ByteDance Doubao) 客户端

    环境变量:
        DOUBAO_API_KEY: 豆包 API Key
        DOUBAO_API_ENDPOINT: API 端点 (默认 https://ark.cn-beijing.volces.com/api/v3/responses)
        DOUBAO_MODEL: 模型名 (默认 doubao-seed-2-0-pro-260215)
    """

    def __init__(self, model: Optional[str] = None, api_endpoint: Optional[str] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model = model or os.environ.get("DOUBAO_MODEL", "doubao-seed-2-0-pro-260215")
        self.api_endpoint = api_endpoint or os.environ.get(
            "DOUBAO_API_ENDPOINT",
            "https://ark.cn-beijing.volces.com/api/v3/responses"
        )
        self.api_key = os.environ.get("DOUBAO_API_KEY", "")
        self._tracker.provider = "doubao"

        if not self.api_key:
            raise ValueError("DOUBAO_API_KEY environment variable not set")

        try:
            import httpx
            self._http = httpx.Client(timeout=_HTTPX_TIMEOUT)
        except ImportError as exc:
            raise ImportError(
                "httpx not installed. Run: pip install httpx"
            ) from exc

    @staticmethod
    def _parse_doubao_response_text(data: dict) -> str:
        """从豆包 responses JSON 提取 assistant 文本。"""
        parts: list[str] = []
        for item in data.get("output") or []:
            if item.get("type") == "reasoning":
                continue
            for block in item.get("content") or []:
                block_text = block.get("text") or block.get("output_text") or ""
                if block_text:
                    parts.append(block_text)
        if parts:
            return "\n".join(parts)
        return data.get("text", "") or ""

    def _call(self, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        }

        try:
            resp = self._http.post(
                self.api_endpoint,
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            # 豆包 responses API: output[0] 常为 reasoning，实际文本在 type=message 项
            text = self._parse_doubao_response_text(data)

            # 获取 token 计数 (如果可用)
            usage = data.get("usage", {})
            in_tok = usage.get("input_tokens", len(prompt) // 4)
            out_tok = usage.get("output_tokens", len(text) // 4)

            return text, in_tok, out_tok

        except Exception as exc:
            if "429" in str(exc) or "rate" in str(exc).lower():
                raise RateLimitError(str(exc)) from exc
            raise APIError(f"Doubao API error: {exc}") from exc

    def __del__(self):
        try:
            self._http.close()
        except Exception:
            pass


class LLMClient:
    """
    LLM 客户端工厂。

    用法:
        client = LLMClient.from_env()
        text = client.extract("问题", max_tokens=512)
    """

    @staticmethod
    def from_env() -> BaseLLMClient:
        """
        根据环境变量 LLM_PROVIDER 自动选择并初始化客户端。

        LLM_PROVIDER=anthropic → AnthropicClient
        LLM_PROVIDER=openai    → OpenAIClient
        LLM_PROVIDER=ollama    → OllamaClient
        LLM_PROVIDER=doubao    → DoubaoClient
        """
        provider = os.environ.get("LLM_PROVIDER", "anthropic").lower().strip()

        if provider == "anthropic":
            return AnthropicClient()
        elif provider == "openai":
            model = os.environ.get("OPENAI_MODEL_OVERRIDE", None)
            return OpenAIClient(model=model)
        elif provider == "ollama":
            return OllamaClient()
        elif provider == "doubao":
            return DoubaoClient()
        else:
            raise ValueError(
                f"Unknown LLM_PROVIDER={provider!r}. "
                "Expected: anthropic | openai | ollama | doubao"
            )

    @staticmethod
    def from_provider(
        provider: str,
        model: Optional[str] = None,
    ) -> BaseLLMClient:
        """显式指定 provider 创建客户端"""
        if provider == "anthropic":
            return AnthropicClient(model=model)
        elif provider == "openai":
            return OpenAIClient(model=model)
        elif provider == "ollama":
            return OllamaClient(model=model)
        elif provider == "doubao":
            return DoubaoClient(model=model)
        else:
            raise ValueError(f"Unknown provider: {provider!r}")
