import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/settings/reset")({
  server: {
    handlers: {
      POST: async ({ request }: { request: Request }) => {
        try {
          const body = await request.json();
          const upstream = await fetch("http://127.0.0.1:8000/api/settings/reset", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            status: upstream.status,
            headers: { "Content-Type": "application/json" },
          });
        } catch (error) {
          return new Response(
            JSON.stringify({ error: "Cannot connect to SAGE backend server" }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      },
    },
  },
});
