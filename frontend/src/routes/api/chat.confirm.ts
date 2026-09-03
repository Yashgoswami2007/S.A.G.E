import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/chat/confirm")({
  server: {
    handlers: {
      POST: async ({ request }: { request: Request }) => {
        try {
          const body = await request.json();
          const upstream = await fetch("http://127.0.0.1:8000/api/chat/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });

          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(JSON.stringify({ error: text || "Upstream confirmation error" }), {
              status: upstream.status,
              headers: { "Content-Type": "application/json" },
            });
          }

          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error confirming action:", error);
          return new Response(
            JSON.stringify({ error: "Failed to forward confirmation to SAGE backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          );
        }
      },
    },
  },
});
