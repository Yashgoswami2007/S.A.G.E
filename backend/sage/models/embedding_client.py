"""
SAGE Embedding Client — calls /v1/embeddings on a llama-server
started with the --embedding flag.

API contract (OpenAI-compatible):
  Request:  POST /v1/embeddings {"model": "...", "input": ["text1", "text2", ...]}
  Response: {"data": [{"embedding": [0.1, ...], "index": 0}, ...], "model": "...", "usage": {...}}
"""

import httpx
import logging
from typing import List, Optional
from sage.core.exceptions import ModelError
from sage.models.client import global_circuit_breaker

logger = logging.getLogger("sage.models.embedding_client")

class EmbeddingClient:
    """Client for the OpenAI-compatible /v1/embeddings endpoint."""

    def __init__(self, base_url: str, model: str, dimension: int = 384):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimension = dimension

    async def embed(
        self,
        texts: List[str],
        circuit_breaker_key: Optional[str] = None,
    ) -> List[List[float]]:
        """
        Embed a batch of texts. Returns list of embedding vectors.

        Args:
            texts: List of strings to embed.
            circuit_breaker_key: Logical model ID for circuit breaker state.

        Returns:
            List of float vectors, one per input text, ordered by input index.

        Raises:
            ModelError: If the embedding server is unreachable or returns an error.
        """
        url = f"{self.base_url}/v1/embeddings"
        payload = {
            "model": self.model,
            "input": texts,
        }
        cb_key = circuit_breaker_key or self.model

        if global_circuit_breaker.is_open(cb_key):
            remaining = global_circuit_breaker.get_remaining_recovery_time(cb_key)
            raise ModelError(
                f"Embedding model '{cb_key}' is temporarily unavailable "
                f"(circuit breaker open). Recovery in {remaining}s.",
                details={"model_id": cb_key, "recovery_seconds": remaining},
            )

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    raise ModelError(
                        f"Embedding server error ({resp.status_code}): {resp.text}",
                        details={"model_id": cb_key, "status_code": resp.status_code},
                    )
                global_circuit_breaker.record_success(cb_key)
                data = resp.json()

            # Sort by index to guarantee order matches input
            embeddings = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in embeddings]

        except ModelError:
            global_circuit_breaker.record_failure(cb_key)
            raise
        except httpx.ConnectError:
            global_circuit_breaker.record_failure(cb_key)
            raise ModelError(
                f"Cannot connect to embedding server at {url}. "
                "Ensure the embedding model is running with --embedding flag.",
                details={"model_id": cb_key, "url": url},
            )
        except httpx.TimeoutException:
            global_circuit_breaker.record_failure(cb_key)
            raise ModelError(
                f"Embedding request timed out after 120s at {url}.",
                details={"model_id": cb_key, "url": url},
            )
        except Exception as e:
            global_circuit_breaker.record_failure(cb_key)
            raise ModelError(
                f"Embedding request failed: {e}",
                details={"model_id": cb_key, "url": url, "error": str(e)},
            )

    async def embed_single(self, text: str, **kwargs) -> List[float]:
        """Convenience: embed a single text and return one vector."""
        results = await self.embed([text], **kwargs)
        return results[0]
