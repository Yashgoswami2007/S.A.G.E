import hashlib
import os
from sage.tools.base import BaseTool, ToolPermission, ToolResult
from sage.rag.retriever import Retriever
from sage.rag.store import VectorStore
from sage.rag.citations import format_citations
from sage.models.embedding_client import EmbeddingClient

class RagSearchTool(BaseTool):
    name = "rag_search"
    description = (
        "Search the workspace knowledge base for relevant information from indexed documents. "
        "Returns relevant text excerpts with source citations (document name, page number, section). "
        "Use when the user asks about uploaded documents, policies, reports, or reference materials."
    )
    permission = ToolPermission.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query describing what information to find",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return. Default: 5",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, top_k: int = 5) -> ToolResult:
        from sage.config import settings
        if not settings.RAG_ENABLED:
            return ToolResult(success=False, output="", error="RAG is disabled in settings.")

        # 1. Get workspace_id
        import sage.api.workspace as _ws
        # Wait, the tool is executed inside an Agent runtime. 
        # The workspace state is managed globally or per request. Let's use the active workspace from manager.
        workspace_path = _ws.workspace_manager.get_active_workspace()
        if not workspace_path:
            return ToolResult(success=False, output="", error="No active workspace.")
            
        workspace_id = hashlib.sha256(workspace_path.encode()).hexdigest()[:16]

        # 2. Retrieve
        from sage.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            retriever = Retriever(VectorStore())
            try:
                results = await retriever.retrieve(db, query, workspace_id, top_k)
            except Exception as e:
                return ToolResult(success=False, output="", error=f"Retrieval failed: {str(e)}")

        if not results:
            return ToolResult(success=True, output="No relevant documents found in the knowledge base.")

        # 3. Format with citations
        context = format_citations(results)
        return ToolResult(
            success=True,
            output=context,
            data={"chunks_retrieved": len(results)},
        )
