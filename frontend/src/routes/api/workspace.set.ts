import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/workspace/set")({
  server: {
    handlers: {
      POST: async ({ request }: { request: Request }) => {
        try {
          const body = await request.json();
          const upstream = await fetch("http://127.0.0.1:8000/api/workspace/set", {
            method: "POST",
            body: JSON.stringify(body),
            headers: { "Content-Type": "application/json" },
          });
          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "Failed to set workspace" }),
              { status: upstream.status, headers: { "Content-Type": "application/json" } }
            );
          }
          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error setting workspace:", error);
          return new Response(
            JSON.stringify({ error: "Failed to connect to backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      },
    },
  },
});
