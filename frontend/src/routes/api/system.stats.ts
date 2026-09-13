import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/system/stats")({
  server: {
    handlers: {
      GET: async () => {
        try {
          const upstream = await fetch("http://127.0.0.1:8000/api/system/stats");
          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "Failed to fetch system stats" }),
              { status: upstream.status, headers: { "Content-Type": "application/json" } }
            );
          }
          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error fetching system stats:", error);
          return new Response(
            JSON.stringify({ error: "Failed to connect to backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      },
    },
  },
});
