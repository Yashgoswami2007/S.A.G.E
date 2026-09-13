import math
import hashlib
import re
from typing import List, Optional
import logging

logger = logging.getLogger("sage.rag.embedder")

class LocalEmbedder:
    """
    Sovereign local embedder for SAGE.
    Uses sentence-transformers locally when available, with a deterministic 
    zero-dependency hashing fallback for offline/air-gapped minimal environments.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", dim: int = 384):
        self.model_name = model_name
        self.dim = dim
        self._model = None
        self._use_fallback = False

        try:
            # pyrefly: ignore [missing-import]
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            logger.info(f"Loaded sentence-transformers model: {self.model_name}")
        except Exception as e:
            logger.warning(
                f"Could not load sentence-transformers ({e}). "
                "Activating sovereign zero-dependency local embedding fallback."
            )
            self._use_fallback = True

    def embed_text(self, text: str) -> List[float]:
        """Generates a normalized dense embedding for a single string."""
        if not self._use_fallback and self._model is not None:
            try:
                emb = self._model.encode(text, normalize_embeddings=True)
                return emb.tolist()
            except Exception as e:
                logger.warning(f"Error in model inference ({e}), falling back to deterministic vector.")

        return self._deterministic_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generates normalized dense embeddings for a batch of strings."""
        if not self._use_fallback and self._model is not None:
            try:
                embs = self._model.encode(texts, normalize_embeddings=True, batch_size=32)
                return [e.tolist() for e in embs]
            except Exception as e:
                logger.warning(f"Batch embedding failed ({e}), using fallback.")

        return [self._deterministic_embed(t) for t in texts]

    def _deterministic_embed(self, text: str) -> List[float]:
        """
        Generates a normalized, dense 384-dimensional vector using term-hash projection.
        Words with similar semantic stems hash to overlapping projection bins,
        guaranteeing stable cosine similarity even in minimal/air-gapped python runs.
        """
        vec = [0.0] * self.dim
        tokens = re.findall(r'\b\w+\b', text.lower())
        if not tokens:
            return vec

        for token in tokens:
            # Word-level hash projection
            h = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
            idx1 = h % self.dim
            idx2 = (h >> 16) % self.dim
            sign1 = 1.0 if (h & 1) else -1.0
            sign2 = 1.0 if (h & 2) else -1.0
            
            vec[idx1] += sign1
            vec[idx2] += sign2 * 0.5

            # Subword / 3-gram projections for partial match robustness
            for i in range(len(token) - 2):
                ngram = token[i:i+3]
                nh = int(hashlib.md5(ngram.encode("utf-8")).hexdigest(), 16)
                nidx = nh % self.dim
                vec[nidx] += 0.2 if (nh & 1) else -0.2

        # L2 Normalize vector
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]

        return vec
