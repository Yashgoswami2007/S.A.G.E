import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/models")({
  server: {
    handlers: {
      GET: async () => {
        try {
          const upstream = await fetch("http://127.0.0.1:8080/v1/models");
          // Fetch from SAGE backend's live model registry (includes auto-discovered models)
          const upstream = await fetch("http://127.0.0.1:8000/api/admin/models/available");
          if (!upstream.ok) {
            const raw = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ models: [], error: raw || "Upstream model service error" }),
              { status: upstream.status || 502, headers: { "Content-Type": "application/json" } }
            );
          }
          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: {
              "Content-Type": "application/json",
            },
          });
        } catch (error) {
          return new Response(
            JSON.stringify({ models: [], error: "Cannot connect to SAGE backend server" }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      },

    },
  },
});

