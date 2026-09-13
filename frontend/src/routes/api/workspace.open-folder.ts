import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/workspace/open-folder")({
  server: {
    handlers: {
      POST: async () => {
        try {
          const upstream = await fetch("http://127.0.0.1:8000/api/workspace/open-folder", {
            method: "POST",
          });
          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            return new Response(
              JSON.stringify({ error: text || "Failed to open workspace folder" }),
              { status: upstream.status, headers: { "Content-Type": "application/json" } }
            );
          }
          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error opening workspace folder:", error);
          return new Response(
            JSON.stringify({ error: "Failed to connect to backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      },
    },
  },
});
