import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/rag/status")({
  server: {
    handlers: {
      GET: async () => {
        try {
          const upstream = await fetch("http://127.0.0.1:8000/api/rag/status");

          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "Failed to fetch RAG status" }),
              { status: upstream.status, headers: { "Content-Type": "application/json" } },
            );
          }

          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error fetching RAG status:", error);
          return new Response(
            JSON.stringify({ error: "Failed to connect to SAGE backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }
      },
    },
  },
});
