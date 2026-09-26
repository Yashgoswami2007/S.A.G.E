import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/rag/upload")({
  server: {
    handlers: {
      POST: async ({ request }: { request: Request }) => {
        try {
          // Forward the multipart form data directly to the backend
          const bodyBuffer = await request.arrayBuffer();
          const contentType = request.headers.get("Content-Type");

          if (!contentType) {
            return new Response(JSON.stringify({ error: "Missing Content-Type header" }), {
              status: 400,
              headers: { "Content-Type": "application/json" },
            });
          }

          const upstream = await fetch("http://127.0.0.1:8000/api/rag/upload", {
            method: "POST",
            body: bodyBuffer,
            headers: { "Content-Type": contentType },
          });

          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "RAG upload failed" }),
              {
                status: upstream.status,
                headers: { "Content-Type": "application/json" },
              },
            );
          }

          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error uploading to knowledge base:", error);
          return new Response(
            JSON.stringify({ error: "Failed to forward RAG upload to SAGE backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }
      },
    },
  },
});
