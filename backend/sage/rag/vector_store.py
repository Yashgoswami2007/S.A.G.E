import os
import json
import math
import sqlite3
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import logging

logger = logging.getLogger("sage.rag.vector_store")

class BaseVectorStore(ABC):
    @abstractmethod
    def add_documents(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
        collection: str = "default"
    ) -> int:
        """Stores document chunks with their corresponding dense embeddings."""
        pass

    @abstractmethod
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Finds the most similar document chunks using vector similarity."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Returns statistics on indexed collections and total chunks."""
        pass

    @abstractmethod
    def delete_collection(self, collection: str) -> bool:
        """Deletes all chunks associated with a specific collection."""
        pass


class SQLiteVectorStore(BaseVectorStore):
    """
    Zero-dependency, persistent SQLite vector store.
    Stores chunks and embeddings in a local SQLite file with cosine similarity search.
    Guarantees 100% air-gapped, zero-install reliability.
    """

    def __init__(self, db_path: str = "./workspace/vector_db/sage_rag.db"):
        self.db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY,
                    collection TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rag_col ON rag_chunks(collection)")
            conn.commit()

    def add_documents(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
        collection: str = "default"
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunks and embeddings lists must be of equal length.")

        count = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                meta = chunk.get("metadata", {})
                chunk_id = f"{collection}_{meta.get('filename', 'doc')}_{meta.get('page', 1)}_{meta.get('chunk_index', i)}_{os.urandom(4).hex()}"
                
                cursor.execute("""
                    INSERT OR REPLACE INTO rag_chunks (id, collection, text, metadata_json, embedding_json)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    chunk_id,
                    collection,
                    chunk["text"],
                    json.dumps(meta),
                    json.dumps(emb)
                ))
                count += 1
            conn.commit()
        return count

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if collection:
                cursor.execute("SELECT id, collection, text, metadata_json, embedding_json FROM rag_chunks WHERE collection = ?", (collection,))
            else:
                cursor.execute("SELECT id, collection, text, metadata_json, embedding_json FROM rag_chunks")
            
            rows = cursor.fetchall()
            if not rows:
                return []

            scored: List[Dict[str, Any]] = []
            for row in rows:
                emb = json.loads(row["embedding_json"])
                sim = self._cosine_similarity(query_embedding, emb)
                scored.append({
                    "id": row["id"],
                    "collection": row["collection"],
                    "text": row["text"],
                    "metadata": json.loads(row["metadata_json"]),
                    "score": sim
                })

            # Sort descending by cosine similarity score
            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT collection, COUNT(*) as count FROM rag_chunks GROUP BY collection")
            rows = cursor.fetchall()
            collections = {row["collection"]: row["count"] for row in rows}
            total = sum(collections.values())
            return {
                "total_chunks": total,
                "collections": collections,
                "backend": "sqlite"
            }

    def delete_collection(self, collection: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rag_chunks WHERE collection = ?", (collection,))
            conn.commit()
            return cursor.rowcount > 0


def get_vector_store(persist_dir: Optional[str] = None) -> BaseVectorStore:
    """
    Returns the active vector store.
    Tries ChromaDB if installed; otherwise defaults to SQLiteVectorStore.
    """
    path = persist_dir or "./workspace/vector_db"
    try:
        # pyrefly: ignore [missing-import]
        import chromadb
        # If chromadb is installed and functional
        class ChromaVectorStore(BaseVectorStore):
            def __init__(self, c_path: str):
                self.client = chromadb.PersistentClient(path=c_path)

            def add_documents(self, chunks: List[Dict[str, Any]], embeddings: List[List[float]], collection: str = "default") -> int:
                col = self.client.get_or_create_collection(name=collection)
                ids = [f"{c['metadata'].get('filename', 'doc')}_{i}_{os.urandom(4).hex()}" for i, c in enumerate(chunks)]
                docs = [c["text"] for c in chunks]
                metas = [c.get("metadata", {}) for c in chunks]
                col.add(ids=ids, documents=docs, embeddings=embeddings, metadatas=metas)
                return len(chunks)

            def search(self, query_embedding: List[float], top_k: int = 5, collection: Optional[str] = None) -> List[Dict[str, Any]]:
                col_name = collection or "default"
                col = self.client.get_or_create_collection(name=col_name)
                res = col.query(query_embeddings=[query_embedding], n_results=top_k)
                output = []
                if res and res.get("documents"):
                    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
                        output.append({
                            "text": doc,
                            "metadata": meta,
                            "score": 1.0 - dist
                        })
                return output

            def get_stats(self) -> Dict[str, Any]:
                cols = self.client.list_collections()
                counts = {c.name: c.count() for c in cols}
                return {"total_chunks": sum(counts.values()), "collections": counts, "backend": "chromadb"}

            def delete_collection(self, collection: str) -> bool:
                try:
                    self.client.delete_collection(name=collection)
                    return True
                except Exception:
                    return False

        return ChromaVectorStore(path)
    except Exception:
        # Seamless fallback to persistent SQLite vector store
        db_file = os.path.join(path, "sage_rag.db")
        return SQLiteVectorStore(db_file)
