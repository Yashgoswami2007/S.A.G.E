import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/models")({
  server: {
    handlers: {
      GET: async () => {
        try {
          const upstream = await fetch("http://127.0.0.1:8001/v1/models");
          if (!upstream.ok) {
            return new Response("Upstream error", { status: upstream.status || 500 });
          }
          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: {
              "Content-Type": "application/json",
            },
          });
        } catch (error) {
          return new Response(JSON.stringify({ error: "Failed to fetch models" }), { status: 500 });
        }
      },
    },
  },
});
