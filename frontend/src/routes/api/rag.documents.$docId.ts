import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/rag/documents/$docId")({
  server: {
    handlers: {
      GET: async ({ request, params }: { request: Request; params: { docId: string } }) => {
        try {
          const upstream = await fetch(`http://127.0.0.1:8000/api/rag/documents/${params.docId}`);

          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "Document not found" }),
              { status: upstream.status, headers: { "Content-Type": "application/json" } },
            );
          }

          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error fetching RAG document:", error);
          return new Response(
            JSON.stringify({ error: "Failed to connect to SAGE backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }
      },

      DELETE: async ({ request, params }: { request: Request; params: { docId: string } }) => {
        try {
          const upstream = await fetch(`http://127.0.0.1:8000/api/rag/documents/${params.docId}`, {
            method: "DELETE",
          });

          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "Failed to delete document" }),
              { status: upstream.status, headers: { "Content-Type": "application/json" } },
            );
          }

          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error deleting RAG document:", error);
          return new Response(
            JSON.stringify({ error: "Failed to connect to SAGE backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }
      },
    },
  },
});
