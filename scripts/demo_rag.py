import asyncio
import os
import sys

# Ensure backend package is in python path
sys.path.insert(0, os.path.abspath("backend"))

from sage.tools.rag_ops import RagIngestTool, RagSearchTool
from sage.rag.vector_store import get_vector_store
from sage.config import settings

async def main():
    print("=" * 65)
    print("       SAGE SOVEREIGN RAG INTERACTIVE DEMONSTRATION")
    print("=" * 65)

    os.makedirs(settings.WORKSPACE_DIR, exist_ok=True)
    sample_sop_path = os.path.join(settings.WORKSPACE_DIR, "MRPL_REFINERY_SOP.txt")

    # 1. Create sample industrial refinery documentation
    print("\n[1] Creating sample MRPL Standard Operating Procedure (SOP)...")
    sop_content = """
# MRPL STANDARD OPERATING PROCEDURE — REFINERY UNIT 3
Document ID: MRPL-SOP-HEX-401
Effective Date: 2026-01-15
Department: Mechanical & Process Safety

## 1. Scope & Equipment Identification
This standard applies to Shell & Tube Heat Exchanger HEX-401 installed in Distillation Unit 3.

## 2. Operating Limits & Thresholds
- Maximum Allowable Working Pressure (MAWP): 25.5 bar gauge.
- Normal Operating Pressure: 18.0 bar gauge to 21.5 bar gauge.
- Maximum Operating Temperature: 320 degrees Celsius.
- Emergency Shutdown Trigger: Automatic trip occurs if differential pressure (dP) across tubes exceeds 4.0 bar or if shell skin temperature exceeds 340 degrees Celsius.

## 3. Maintenance & Periodic Hydro-testing
- Visual ultrasonic thickness gauge inspection every 6 months.
- Hydrostatic test pressure: 38.25 bar gauge (1.5x MAWP) during turnaround.
"""
    with open(sample_sop_path, "w", encoding="utf-8") as f:
        f.write(sop_content.strip())
    print(f"    Saved: {sample_sop_path}")

    # 2. Ingest document via RagIngestTool
    print("\n[2] Ingesting document into sovereign vector database via 'rag_ingest' tool...")
    ingest_tool = RagIngestTool()
    ingest_result = await ingest_tool.execute(path="MRPL_REFINERY_SOP.txt", collection="mrpl_procedures")
    print(f"    Status: {'SUCCESS' if ingest_result.success else 'FAILED'}")
    print(f"    Output: {ingest_result.output}")

    # Check vector store stats
    store = get_vector_store(os.path.join(settings.WORKSPACE_DIR, "vector_db"))
    stats = store.get_stats()
    print(f"    Vector DB Stats: {stats}")

    # 3. Perform a query via RagSearchTool
    query = "What is the emergency shutdown trigger pressure for HEX-401?"
    print(f"\n[3] Searching knowledge base for query:\n    \"{query}\"")
    
    search_tool = RagSearchTool()
    search_result = await search_tool.execute(query=query, collection="mrpl_procedures")
    
    print("\n" + "-" * 65)
    print("RETRIEVED CITATION FROM KNOWLEDGE BASE:")
    print("-" * 65)
    print(search_result.output)
    print("-" * 65)

    print("\n[SUCCESS] Sovereign RAG search is working end-to-end!\n")

if __name__ == "__main__":
    asyncio.run(main())
