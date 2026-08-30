import httpx
import json
from typing import Any, Optional, AsyncGenerator
from sage.core.exceptions import ModelError
from sage.models.circuit_breaker import ModelCircuitBreaker

global_circuit_breaker = ModelCircuitBreaker()

class OpenAICompatibleClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: Optional[list] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,  # increased: Qwen3 needs room for <think> + answer
        stream: bool = False
    ) -> dict[str, Any]:
        """
        Calls OpenAI-compatible /v1/chat/completions endpoint.
        Used by vLLM and llama.cpp server.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        if tools:
            payload["tools"] = tools

        headers = {"Content-Type": "application/json"}

        if global_circuit_breaker.is_open(model):
            raise ModelError(f"Circuit breaker is OPEN for model {model}")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    raise ModelError(f"Model server error ({response.status_code}): {response.text}")
                global_circuit_breaker.record_success(model)
                return response.json()
        except Exception as e:
            global_circuit_breaker.record_failure(model)
            if isinstance(e, ModelError):
                raise
            raise ModelError(f"Failed to communicate with model server at {url}: {str(e)}")

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: Optional[list] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096  # increased: Qwen3 needs room for <think> + answer
    ) -> AsyncGenerator[str, None]:
        """
        Streams responses from the OpenAI-compatible /v1/chat/completions endpoint.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True
        }
        if tools:
            payload["tools"] = tools

        headers = {"Content-Type": "application/json"}

        if global_circuit_breaker.is_open(model):
            raise ModelError(f"Circuit breaker is OPEN for model {model}")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise ModelError(f"Model server error ({response.status_code}): {error_text.decode('utf-8', errors='replace')}")
                    
                    global_circuit_breaker.record_success(model)
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            global_circuit_breaker.record_failure(model)
            if isinstance(e, ModelError):
                raise
            raise ModelError(f"Failed to stream from model server at {url}: {str(e)}")
