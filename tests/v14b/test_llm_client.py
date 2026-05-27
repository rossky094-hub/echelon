"""
tests/v14b/test_llm_client.py

LLM Client 测试 (3 provider mock)
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from echelon.v14b.llm_client import (
    AnthropicClient,
    OpenAIClient,
    OllamaClient,
    LLMClient,
    RateLimitError,
    APIError,
    CostTracker,
    get_cost_tracker,
)


# ---------------------------------------------------------------------------
# CostTracker 测试
# ---------------------------------------------------------------------------

class TestCostTracker:
    def test_initial_state(self):
        tracker = CostTracker()
        assert tracker.total_input_tokens == 0
        assert tracker.total_output_tokens == 0

    def test_record(self):
        tracker = CostTracker()
        tracker.record(100, 50)
        assert tracker.total_input_tokens == 100
        assert tracker.total_output_tokens == 50

    def test_record_accumulates(self):
        tracker = CostTracker()
        tracker.record(100, 50)
        tracker.record(200, 80)
        assert tracker.total_input_tokens == 300
        assert tracker.total_output_tokens == 130

    def test_estimate_usd_anthropic(self):
        tracker = CostTracker()
        tracker.provider = "anthropic"
        tracker.record(1_000_000, 0)  # 1M input tokens
        cost = tracker.estimate_usd()
        assert cost == pytest.approx(3.0, rel=0.01)

    def test_estimate_usd_ollama_free(self):
        tracker = CostTracker()
        tracker.provider = "ollama"
        tracker.record(1_000_000, 1_000_000)
        cost = tracker.estimate_usd()
        assert cost == 0.0

    def test_summary_format(self):
        tracker = CostTracker()
        tracker.provider = "anthropic"
        tracker.record(1000, 200)
        summary = tracker.summary()
        assert "provider=anthropic" in summary
        assert "input_tokens=1,000" in summary


# ---------------------------------------------------------------------------
# LLMClient factory 测试
# ---------------------------------------------------------------------------

class TestLLMClientFactory:
    def test_from_env_anthropic(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test"}):
            with patch("anthropic.Anthropic"):
                client = LLMClient.from_env()
                assert isinstance(client, AnthropicClient)

    def test_from_env_openai(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test"}):
            with patch("openai.OpenAI"):
                client = LLMClient.from_env()
                assert isinstance(client, OpenAIClient)

    def test_from_env_ollama(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            with patch("httpx.Client"):
                client = LLMClient.from_env()
                assert isinstance(client, OllamaClient)

    def test_from_env_invalid_raises(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "unknown_provider"}):
            with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
                LLMClient.from_env()

    def test_from_provider_anthropic(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}):
            with patch("anthropic.Anthropic"):
                client = LLMClient.from_provider("anthropic")
                assert isinstance(client, AnthropicClient)

    def test_from_provider_openai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            with patch("openai.OpenAI"):
                client = LLMClient.from_provider("openai")
                assert isinstance(client, OpenAIClient)


# ---------------------------------------------------------------------------
# AnthropicClient mock 测试
# ---------------------------------------------------------------------------

class TestAnthropicClient:
    def _make_client(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
            mock_anthropic = MagicMock()
            with patch("anthropic.Anthropic", return_value=mock_anthropic):
                client = AnthropicClient()
                client._client = mock_anthropic
                return client, mock_anthropic

    def test_extract_success(self):
        client, mock_ant = self._make_client()

        # Mock response
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="Hello World")]
        mock_msg.usage.input_tokens = 10
        mock_msg.usage.output_tokens = 5
        mock_ant.messages.create.return_value = mock_msg

        result = client.extract("test prompt", max_tokens=100)
        assert result == "Hello World"

    def test_extract_rate_limit_retry(self):
        import anthropic
        client, mock_ant = self._make_client()
        client.initial_delay = 0.01  # Fast retry for test

        # First call raises rate limit, second succeeds
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="Success")]
        mock_msg.usage.input_tokens = 10
        mock_msg.usage.output_tokens = 5

        mock_ant.messages.create.side_effect = [
            anthropic.RateLimitError(
                message="Rate limit", response=MagicMock(status_code=429), body={}
            ),
            mock_msg,
        ]

        result = client.extract("test", max_tokens=100)
        assert result == "Success"
        assert mock_ant.messages.create.call_count == 2

    def test_extract_json(self):
        client, mock_ant = self._make_client()

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"key": "value", "num": 42}')]
        mock_msg.usage.input_tokens = 10
        mock_msg.usage.output_tokens = 5
        mock_ant.messages.create.return_value = mock_msg

        result = client.extract_json("test")
        assert result == {"key": "value", "num": 42}

    def test_extract_json_with_markdown_fence(self):
        client, mock_ant = self._make_client()

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='```json\n{"a": 1}\n```')]
        mock_msg.usage.input_tokens = 10
        mock_msg.usage.output_tokens = 5
        mock_ant.messages.create.return_value = mock_msg

        result = client.extract_json("test")
        assert result == {"a": 1}

    def test_extract_json_invalid_returns_empty(self):
        client, mock_ant = self._make_client()

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="This is not JSON")]
        mock_msg.usage.input_tokens = 10
        mock_msg.usage.output_tokens = 5
        mock_ant.messages.create.return_value = mock_msg

        result = client.extract_json("test")
        assert result == {}


# ---------------------------------------------------------------------------
# OpenAIClient mock 测试
# ---------------------------------------------------------------------------

class TestOpenAIClient:
    def _make_client(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test_key"}):
            mock_openai = MagicMock()
            with patch("openai.OpenAI", return_value=mock_openai):
                client = OpenAIClient()
                client._client = mock_openai
                return client, mock_openai

    def test_extract_success(self):
        client, mock_oa = self._make_client()

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="OpenAI response"))]
        mock_resp.usage.prompt_tokens = 20
        mock_resp.usage.completion_tokens = 10
        mock_oa.chat.completions.create.return_value = mock_resp

        result = client.extract("test")
        assert result == "OpenAI response"

    def test_model_override(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "OPENAI_MODEL_OVERRIDE": "o3-mini"}):
            with patch("openai.OpenAI"):
                client = OpenAIClient(model="o3-mini")
                assert client.model == "o3-mini"


# ---------------------------------------------------------------------------
# OllamaClient mock 测试
# ---------------------------------------------------------------------------

class TestOllamaClient:
    def _make_client(self):
        mock_http = MagicMock()
        with patch("httpx.Client", return_value=mock_http):
            client = OllamaClient()
            client._http = mock_http
            return client, mock_http

    def test_extract_success(self):
        client, mock_http = self._make_client()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Ollama response"}
        mock_http.post.return_value = mock_resp

        result = client.extract("test prompt")
        assert result == "Ollama response"

    def test_model_default(self):
        with patch("httpx.Client"):
            client = OllamaClient()
            assert "qwen" in client.model or "llama" in client.model

    def test_custom_model(self):
        with patch("httpx.Client"):
            client = OllamaClient(model="llama3.2:latest")
            assert client.model == "llama3.2:latest"
