import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/settings")({
  server: {
    handlers: {
      GET: async () => {
        try {
          const upstream = await fetch("http://127.0.0.1:8000/api/settings");
          if (!upstream.ok) {
            const raw = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ sections: [], error: raw || "Settings service error" }),
              { status: upstream.status || 502, headers: { "Content-Type": "application/json" } }
            );
          }
          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error) {
          return new Response(
            JSON.stringify({ sections: [], error: "Cannot connect to SAGE backend server" }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      },

      PATCH: async ({ request }: { request: Request }) => {
        try {
          const body = await request.json();
          const upstream = await fetch("http://127.0.0.1:8000/api/settings", {
            method: "PATCH",
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
