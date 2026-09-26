import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/rag/documents")({
  server: {
    handlers: {
      GET: async ({ request }: { request: Request }) => {
        try {
          const url = new URL(request.url);
          const params = url.searchParams.toString();
          const target = `http://127.0.0.1:8000/api/rag/documents${params ? `?${params}` : ""}`;

          const upstream = await fetch(target);

          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "Failed to fetch documents" }),
              { status: upstream.status, headers: { "Content-Type": "application/json" } },
            );
          }

          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error fetching RAG documents:", error);
          return new Response(
            JSON.stringify({ error: "Failed to connect to SAGE backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }
      },
    },
  },
});
