"""
orchestrator/llm_client.py

Multi-LLM abstraction layer for Agent Farm.
Priority: Ollama (local/free) → Groq (cloud/free tier) → Claude (paid fallback)

Usage:
    client = LLMClient()
    response = client.complete("Write a haiku", level="simple")
    response = client.complete("Analyze this business idea...", level="complex")
"""

import os
import time
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class LLMLevel(str, Enum):
    SIMPLE  = "simple"   # llama3.2:3b — text, formatting, summaries
    MEDIUM  = "medium"   # mistral:7b  — code simple, analysis
    COMPLEX = "complex"  # llama3.1:8b — reasoning, planning
    CLOUD   = "cloud"    # Groq 70b    — fast cloud backup
    CLAUDE  = "claude"   # Claude Haiku/Sonnet — critical decisions


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    tokens_used: int
    cost_usd: float
    latency_ms: int


# Cost per 1K tokens (USD) — approximate
COST_TABLE = {
    "ollama":       0.0,
    "groq":         0.0,          # free tier
    "claude-haiku": 0.001,        # ~$0.001/1K tokens
    "claude-sonnet":0.015,
}

# Model routing by level
MODEL_ROUTING = {
    LLMLevel.SIMPLE:  {"ollama": "llama3.2:3b",        "groq": "llama-3.1-8b-instant"},
    LLMLevel.MEDIUM:  {"ollama": "mistral:7b",          "groq": "mixtral-8x7b-32768"},
    LLMLevel.COMPLEX: {"ollama": "llama3.1:8b",         "groq": "llama-3.3-70b-versatile"},
    LLMLevel.CLOUD:   {"groq":   "llama-3.3-70b-versatile"},
    LLMLevel.CLAUDE:  {"claude": "claude-haiku-4-5-20251001"},
}


class OllamaProvider:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._available_models: Optional[list[str]] = None

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def get_available_models(self) -> list[str]:
        if self._available_models is not None:
            return self._available_models
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            data = r.json()
            self._available_models = [m["name"] for m in data.get("models", [])]
            return self._available_models
        except Exception:
            return []

    def complete(self, prompt: str, model: str,
                 system_prompt: str = "", max_tokens: int = 2048) -> LLMResponse:
        t0 = time.monotonic()
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        r = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        latency = int((time.monotonic() - t0) * 1000)
        tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
        return LLMResponse(
            content=data.get("response", ""),
            model=model,
            provider="ollama",
            tokens_used=tokens,
            cost_usd=0.0,
            latency_ms=latency,
        )


class GroqProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8),
           retry=retry_if_exception_type(httpx.HTTPStatusError))
    def complete(self, prompt: str, model: str,
                 system_prompt: str = "", max_tokens: int = 2048) -> LLMResponse:
        t0 = time.monotonic()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": max_tokens},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        latency = int((time.monotonic() - t0) * 1000)
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)
        content = data["choices"][0]["message"]["content"]
        return LLMResponse(
            content=content,
            model=model,
            provider="groq",
            tokens_used=tokens,
            cost_usd=0.0,
            latency_ms=latency,
        )


class ClaudeProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def complete(self, prompt: str, model: str,
                 system_prompt: str = "", max_tokens: int = 2048) -> LLMResponse:
        import anthropic
        t0 = time.monotonic()
        client = anthropic.Anthropic(api_key=self.api_key)

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        msg = client.messages.create(**kwargs)
        latency = int((time.monotonic() - t0) * 1000)
        tokens = msg.usage.input_tokens + msg.usage.output_tokens

        # Estimate cost
        provider_key = "claude-haiku" if "haiku" in model else "claude-sonnet"
        cost = (tokens / 1000) * COST_TABLE.get(provider_key, 0.001)

        return LLMResponse(
            content=msg.content[0].text,
            model=model,
            provider="claude",
            tokens_used=tokens,
            cost_usd=cost,
            latency_ms=latency,
        )


class LLMClient:
    """
    Smart multi-provider LLM client with automatic fallback.

    Routing strategy:
    1. Try Ollama (local, free) if model is available
    2. Fall back to Groq (cloud, free tier)
    3. Fall back to Claude (paid, only if necessary)
    """

    def __init__(self):
        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        groq_key   = os.environ.get("GROQ_API_KEY", "")
        claude_key = os.environ.get("ANTHROPIC_API_KEY", "")

        self.ollama = OllamaProvider(ollama_url)
        self.groq   = GroqProvider(groq_key)
        self.claude = ClaudeProvider(claude_key)

        self._ollama_up: Optional[bool] = None

    def _check_ollama(self) -> bool:
        if self._ollama_up is None:
            self._ollama_up = self.ollama.is_available()
        return self._ollama_up

    def complete(self, prompt: str,
                 level: str = "medium",
                 system_prompt: str = "",
                 max_tokens: int = 2048,
                 force_provider: Optional[str] = None) -> LLMResponse:
        """
        Run an LLM completion.

        Args:
            prompt: User message
            level: "simple" | "medium" | "complex" | "cloud" | "claude"
            system_prompt: Optional system/context instructions
            max_tokens: Max output tokens
            force_provider: Force "ollama" | "groq" | "claude"
        """
        try:
            lvl = LLMLevel(level)
        except ValueError:
            lvl = LLMLevel.MEDIUM

        routing = MODEL_ROUTING[lvl]

        # Force specific provider
        if force_provider:
            return self._route_forced(prompt, system_prompt, max_tokens,
                                       force_provider, routing)

        # Auto routing: prefer local
        if "ollama" in routing and self._check_ollama():
            model = routing["ollama"]
            available = self.ollama.get_available_models()
            # Check if exact model or base model available
            matched = next(
                (m for m in available if m.startswith(model.split(":")[0])),
                None
            )
            if matched:
                try:
                    logger.debug(f"Using Ollama model: {matched}")
                    return self.ollama.complete(prompt, matched, system_prompt, max_tokens)
                except Exception as e:
                    logger.warning(f"Ollama failed: {e}, trying fallback")

        # Groq fallback
        if "groq" in routing and self.groq.is_available():
            model = routing.get("groq", "llama-3.3-70b-versatile")
            try:
                logger.debug(f"Using Groq model: {model}")
                return self.groq.complete(prompt, model, system_prompt, max_tokens)
            except Exception as e:
                logger.warning(f"Groq failed: {e}, trying Claude fallback")

        # Claude final fallback
        if self.claude.is_available():
            model = routing.get("claude", "claude-haiku-4-5-20251001")
            logger.debug(f"Using Claude model: {model}")
            return self.claude.complete(prompt, model, system_prompt, max_tokens)

        raise RuntimeError(
            "No LLM provider available. "
            "Check Ollama is running, or set GROQ_API_KEY / ANTHROPIC_API_KEY."
        )

    def _route_forced(self, prompt: str, system_prompt: str, max_tokens: int,
                       provider: str, routing: dict) -> LLMResponse:
        if provider == "ollama":
            model = routing.get("ollama", "llama3.2:3b")
            return self.ollama.complete(prompt, model, system_prompt, max_tokens)
        if provider == "groq":
            model = routing.get("groq", "llama-3.3-70b-versatile")
            return self.groq.complete(prompt, model, system_prompt, max_tokens)
        if provider == "claude":
            model = routing.get("claude", "claude-haiku-4-5-20251001")
            return self.claude.complete(prompt, model, system_prompt, max_tokens)
        raise ValueError(f"Unknown provider: {provider}")

    def get_status(self) -> dict:
        """Returns availability status of all providers."""
        return {
            "ollama": {
                "available": self._check_ollama(),
                "models": self.ollama.get_available_models() if self._check_ollama() else [],
            },
            "groq": {"available": self.groq.is_available()},
            "claude": {"available": self.claude.is_available()},
        }
