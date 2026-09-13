from typing import Any, Optional, AsyncGenerator
import httpx
import json
from sage.core.exceptions import ModelError, CircuitBreakerOpenError
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
        max_tokens: int = 12288,  # increased: Qwen3 needs room for <think> + answer
        stream: bool = False,
        circuit_breaker_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Calls OpenAI-compatible /v1/chat/completions endpoint.
        Used by vLLM and llama.cpp server.

        `model` is the value sent in the API payload — llama-server requires the
        absolute GGUF file path here.  `circuit_breaker_key` is the logical model
        ID used for circuit-breaker state (defaults to `model` when not provided,
        which preserves backwards-compatible behaviour for callers that already
        pass a short ID).
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

        # Use the logical model ID for circuit-breaker state, never the file path.
        cb_key = circuit_breaker_key if circuit_breaker_key is not None else model

        if global_circuit_breaker.is_open(cb_key):
            remaining = global_circuit_breaker.get_remaining_recovery_time(cb_key)
            raise CircuitBreakerOpenError(
                message=f"Model '{cb_key}' is temporarily unavailable due to repeated failures (circuit breaker open). Recovery attempt in {remaining}s.",
                model_id=cb_key,
                recovery_seconds=remaining,
            )

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    raise ModelError(
                        f"Model server error ({response.status_code}): {response.text}",
                        details={"model_id": cb_key, "status_code": response.status_code, "url": url}
                    )
                global_circuit_breaker.record_success(cb_key)
                resp_data = response.json()
                
                # Check for truncation
                choices = resp_data.get("choices", [])
                if choices:
                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason == "length":
                        resp_data["_truncated"] = True
                        
                return resp_data
        except Exception as e:
            global_circuit_breaker.record_failure(cb_key)
            if isinstance(e, ModelError):
                raise
            if isinstance(e, httpx.ConnectError):
                raise ModelError(
                    f"Could not connect to model server at {url}. Ensure model process is running.",
                    details={"model_id": cb_key, "url": url, "error": str(e)}
                )
            if isinstance(e, httpx.TimeoutException):
                raise ModelError(
                    f"Model inference timed out after 600s at {url}.",
                    details={"model_id": cb_key, "url": url, "error": str(e)}
                )
            raise ModelError(
                f"Failed to communicate with model server at {url}: {str(e)}",
                details={"model_id": cb_key, "url": url, "error": str(e)}
            )

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: Optional[list] = None,
        temperature: float = 0.2,
        max_tokens: int = 12288,  # increased: Qwen3 needs room for <think> + answer
        circuit_breaker_key: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streams responses from the OpenAI-compatible /v1/chat/completions endpoint.

        `model` is the value sent in the API payload.  `circuit_breaker_key` is the
        logical model ID used for circuit-breaker state (defaults to `model`).
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

        # Use the logical model ID for circuit-breaker state, never the file path.
        cb_key = circuit_breaker_key if circuit_breaker_key is not None else model

        if global_circuit_breaker.is_open(cb_key):
            remaining = global_circuit_breaker.get_remaining_recovery_time(cb_key)
            raise CircuitBreakerOpenError(
                message=f"Model '{cb_key}' is temporarily unavailable due to repeated failures (circuit breaker open). Recovery attempt in {remaining}s.",
                model_id=cb_key,
                recovery_seconds=remaining,
            )

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise ModelError(
                            f"Model server error ({response.status_code}): {error_text.decode('utf-8', errors='replace')}",
                            details={"model_id": cb_key, "status_code": response.status_code, "url": url}
                        )

                    global_circuit_breaker.record_success(cb_key)

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
                                        
                                    finish_reason = choices[0].get("finish_reason")
                                    if finish_reason == "length":
                                        yield "\n\n[TRUNCATED_DUE_TO_LENGTH_LIMIT]"
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            global_circuit_breaker.record_failure(cb_key)
            if isinstance(e, ModelError):
                raise
            if isinstance(e, httpx.ConnectError):
                raise ModelError(
                    f"Could not connect to model stream server at {url}. Ensure model process is running.",
                    details={"model_id": cb_key, "url": url, "error": str(e)}
                )
            if isinstance(e, httpx.TimeoutException):
                raise ModelError(
                    f"Model stream timed out after 600s at {url}.",
                    details={"model_id": cb_key, "url": url, "error": str(e)}
                )
            raise ModelError(
                f"Failed to stream from model server at {url}: {str(e)}",
                details={"model_id": cb_key, "url": url, "error": str(e)}
            )

