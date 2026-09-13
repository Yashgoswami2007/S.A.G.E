import re
from typing import List, Dict, Any, Optional
from sage.rag.embedder import LocalEmbedder
from sage.rag.vector_store import BaseVectorStore, get_vector_store

class HybridRetriever:
    """
    Hybrid retriever combining dense vector semantic search with keyword/tag matching.
    Specially tuned for industrial queries containing specific equipment IDs,
    procedure codes (e.g. SOP-04, HEX-101, API-650), and operational limits.
    """

    def __init__(
        self,
        vector_store: Optional[BaseVectorStore] = None,
        embedder: Optional[LocalEmbedder] = None
    ):
        self.vector_store = vector_store or get_vector_store()
        self.embedder = embedder or LocalEmbedder()

    def search(
        self,
        query: str,
        collection: Optional[str] = None,
        top_k: int = 5,
        dense_weight: float = 0.65,
        keyword_weight: float = 0.35
    ) -> List[Dict[str, Any]]:
        """
        Executes hybrid retrieval:
        1. Embed query and fetch top candidate chunks from vector store.
        2. Score candidates against exact keyword and equipment tag matches.
        3. Re-rank combined results and return top_k with citation metadata.
        """
        query_vec = self.embedder.embed_text(query)
        # Fetch a slightly wider candidate pool for re-ranking
        candidates = self.vector_store.search(
            query_embedding=query_vec,
            top_k=min(top_k * 3, 20),
            collection=collection
        )

        if not candidates:
            return []

        query_tokens = set(re.findall(r'\b\w+\b', query.lower()))
        # Detect exact industrial tag patterns (e.g., HEX-401, P-102A, SOP-05, API-650)
        industrial_tags = set(re.findall(r'[A-Za-z]+[-_]\d+[A-Za-z]?', query))

        scored_results = []
        for item in candidates:
            text = item["text"]
            text_lower = text.lower()
            dense_score = max(0.0, float(item.get("score", 0.0)))

            # Keyword matching score
            text_tokens = set(re.findall(r'\b\w+\b', text_lower))
            overlap = len(query_tokens.intersection(text_tokens))
            kw_score = overlap / max(len(query_tokens), 1)

            # Equipment code bonus (if query specifies HEX-401 and text contains it, boost heavily)
            tag_bonus = 0.0
            for tag in industrial_tags:
                if tag.lower() in text_lower:
                    tag_bonus += 0.3

            final_score = (dense_weight * dense_score) + (keyword_weight * kw_score) + tag_bonus
            scored_results.append({
                **item,
                "hybrid_score": final_score
            })

        scored_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return scored_results[:top_k]

    def format_citations(self, results: List[Dict[str, Any]]) -> str:
        """
        Formats search results into structured, grounded text with clean source citations
        suitable for feeding into the LLM or agent tool observations.
        """
        if not results:
            return "No matching documentation or standard operating procedures found."

        formatted_blocks = []
        for i, res in enumerate(results, 1):
            meta = res.get("metadata", {})
            filename = meta.get("filename", "document")
            page = meta.get("page", 1)
            section = meta.get("section", "General")
            score = round(res.get("hybrid_score", res.get("score", 0.0)), 3)

            header = f"[Citation #{i} | Source: {filename} (Page {page}, Section: {section}) | Relevance: {score}]"
            content = res["text"].strip()
            formatted_blocks.append(f"{header}\n{content}")

        return "\n\n" + "\n\n---\n\n".join(formatted_blocks)
