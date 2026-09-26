import re
from typing import List
from sage.rag.retriever import RetrievedChunk

def format_citations(chunks: List[RetrievedChunk]) -> str:
    """
    Format retrieved chunks as a context block with deterministic citations.
    """
    if not chunks:
        return ""

    context_blocks = []
    
    for i, chunk in enumerate(chunks, start=1):
        source_info = []
        source_info.append(chunk.document_filename)
        
        if chunk.page_number is not None:
            source_info.append(f"Page {chunk.page_number}")
            
        if chunk.section is not None:
            source_info.append(f"§{chunk.section}")
            
        header = f"[Source {i}: {', '.join(source_info)}]"
        context_blocks.append(f"{header}\n{chunk.content}")
        
    return "---\n" + "\n\n".join(context_blocks) + "\n---"
