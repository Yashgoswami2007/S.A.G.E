import unittest
import os
import tempfile
import asyncio
from sage.rag.chunker import DocumentChunker
from sage.rag.embedder import LocalEmbedder
from sage.rag.vector_store import SQLiteVectorStore
from sage.rag.retriever import HybridRetriever
from sage.tools.rag_ops import RagSearchTool, RagIngestTool
from sage.tools.base import ToolPermission
from sage.agent.profiles import ProfileManager

class TestRAGPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_rag.db")
        self.vector_store = SQLiteVectorStore(self.db_path)
        self.embedder = LocalEmbedder()
        self.retriever = HybridRetriever(vector_store=self.vector_store, embedder=self.embedder)
        self.chunker = DocumentChunker(chunk_size=50, overlap=10)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_document_chunker(self):
        sample_doc = (
            "# Section 1: Overview\n\n"
            "The MRPL refinery operates continuous atmospheric and vacuum distillation units. "
            "Safety protocols mandate regular inspection of piping and pressure safety valves.\n\n"
            "# Section 2: Heat Exchanger HEX-401\n\n"
            "Operating pressure for HEX-401 must not exceed 25.5 bar gauge. "
            "Emergency shutdown triggers if differential pressure exceeds 4.0 bar."
        )
        chunks = self.chunker.chunk_text(
            text=sample_doc,
            metadata={"page": 1},
            source_name="MRPL_SOP_01.md"
        )
        self.assertGreaterEqual(len(chunks), 1)
        # Verify metadata
        first_chunk = chunks[0]
        self.assertIn("metadata", first_chunk)
        self.assertEqual(first_chunk["metadata"]["filename"], "MRPL_SOP_01.md")
        self.assertEqual(first_chunk["metadata"]["page"], 1)

    def test_local_embedder(self):
        text_a = "Heat exchanger maximum operating pressure threshold is 25 bar."
        text_b = "Heat exchanger pressure limits and emergency shutdown."
        text_c = "Chocolate chip cookie recipe with melted butter and sugar."

        vec_a = self.embedder.embed_text(text_a)
        vec_b = self.embedder.embed_text(text_b)
        vec_c = self.embedder.embed_text(text_c)

        self.assertEqual(len(vec_a), 384)
        self.assertEqual(len(vec_b), 384)

        # Cosine similarities
        def cos_sim(v1, v2):
            return sum(x * y for x, y in zip(v1, v2))

        sim_ab = cos_sim(vec_a, vec_b)
        sim_ac = cos_sim(vec_a, vec_c)

        # Related industrial texts should have higher similarity than cookie recipe
        self.assertGreater(sim_ab, sim_ac)

    def test_vector_store_crud(self):
        chunks = [
            {
                "text": "SOP-01: Pump P-101 maintenance should be performed every 6 months.",
                "metadata": {"filename": "sop_pumps.txt", "page": 1, "section": "Pumps"}
            },
            {
                "text": "SOP-02: Heat Exchanger HEX-401 test pressure is 35 bar hydro-tested.",
                "metadata": {"filename": "sop_hex.txt", "page": 3, "section": "Exchangers"}
            }
        ]
        embeddings = self.embedder.embed_batch([c["text"] for c in chunks])
        added = self.vector_store.add_documents(chunks, embeddings, collection="refinery_sops")
        self.assertEqual(added, 2)

        # Stats
        stats = self.vector_store.get_stats()
        self.assertEqual(stats["total_chunks"], 2)
        self.assertIn("refinery_sops", stats["collections"])

        # Query
        query_vec = self.embedder.embed_text("HEX-401 hydro test pressure")
        results = self.vector_store.search(query_vec, top_k=1, collection="refinery_sops")
        self.assertEqual(len(results), 1)
        self.assertIn("HEX-401", results[0]["text"])

        # Delete collection
        deleted = self.vector_store.delete_collection("refinery_sops")
        self.assertTrue(deleted)
        stats_after = self.vector_store.get_stats()
        self.assertEqual(stats_after["total_chunks"], 0)

    def test_hybrid_retriever_with_industrial_tag_boosting(self):
        chunks = [
            {
                "text": "General maintenance guidelines for cooling water heat exchangers.",
                "metadata": {"filename": "general_cooling.txt", "page": 1}
            },
            {
                "text": "Specific inspection procedures for unit HEX-401 tube bundle corrosion.",
                "metadata": {"filename": "hex401_procedure.txt", "page": 4}
            }
        ]
        embeddings = self.embedder.embed_batch([c["text"] for c in chunks])
        self.vector_store.add_documents(chunks, embeddings, collection="sops")

        # Query with exact tag HEX-401
        results = self.retriever.search(query="Corrosion guidelines for HEX-401", collection="sops", top_k=2)
        self.assertEqual(len(results), 2)
        # The specific HEX-401 document should be ranked first due to tag match
        self.assertIn("HEX-401", results[0]["text"])

        citations = self.retriever.format_citations(results)
        self.assertIn("[Citation #1 | Source: hex401_procedure.txt (Page 4", citations)

    def test_rag_tools_execution(self):
        async def _test_tools():
            from sage.config import settings
            orig_workspace = settings.WORKSPACE_DIR
            settings.WORKSPACE_DIR = self.temp_dir.name

            try:
                # 1. Create a test SOP file in the workspace
                sop_file_path = os.path.join(self.temp_dir.name, "MRPL_SOP_VALVES.txt")
                with open(sop_file_path, "w", encoding="utf-8") as f:
                    f.write(
                        "MRPL SOP-VALVE-09:\n"
                        "Pressure Safety Valve PSV-201 lift pressure is calibrated to 18.2 bar.\n"
                        "Annual inspection requires acoustic leak detection."
                    )

                # 2. Ingest file using RagIngestTool
                ingest_tool = RagIngestTool()
                res_ingest = await ingest_tool.execute(path="MRPL_SOP_VALVES.txt", collection="valves")
                self.assertTrue(res_ingest.success)
                self.assertIn("Successfully indexed", res_ingest.output)

                # 3. Search using RagSearchTool
                search_tool = RagSearchTool()
                res_search = await search_tool.execute(query="PSV-201 lift pressure calibration", collection="valves")
                self.assertTrue(res_search.success)
                self.assertIn("PSV-201", res_search.output)
                self.assertIn("18.2 bar", res_search.output)
            finally:
                settings.WORKSPACE_DIR = orig_workspace

        asyncio.run(_test_tools())

    def test_profile_permissions_for_rag(self):
        profile_mgr = ProfileManager()
        analyst = profile_mgr.get_profile("analyst")
        coder = profile_mgr.get_profile("coder")
        general = profile_mgr.get_profile("general")
        inspector = profile_mgr.get_profile("inspector")

        # All profiles have rag_search allowed
        self.assertTrue(analyst.is_tool_allowed("rag_search", ToolPermission.SAFE))
        self.assertTrue(coder.is_tool_allowed("rag_search", ToolPermission.SAFE))
        self.assertTrue(general.is_tool_allowed("rag_search", ToolPermission.SAFE))
        self.assertTrue(inspector.is_tool_allowed("rag_search", ToolPermission.SAFE))

        # Analyst & Coder have rag_ingest allowed
        self.assertTrue(analyst.is_tool_allowed("rag_ingest", ToolPermission.MODIFY))
        self.assertTrue(coder.is_tool_allowed("rag_ingest", ToolPermission.MODIFY))


if __name__ == "__main__":
    unittest.main()
