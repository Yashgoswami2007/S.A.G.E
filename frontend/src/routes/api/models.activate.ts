import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/models/activate")({
  server: {
    handlers: {
      POST: async ({ request }: { request: Request }) => {
        try {
          const body = await request.json() as { model_id: string };
          if (!body.model_id) {
            return new Response(JSON.stringify({ error: "model_id is required" }), {
              status: 400,
              headers: { "Content-Type": "application/json" },
            });
          }

          const upstream = await fetch(
            `http://127.0.0.1:8000/api/admin/models/${encodeURIComponent(body.model_id)}/activate`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
            }
          );

          if (!upstream.ok) {
            const text = await upstream.text().catch(() => "");
            let message = "Failed to activate model";
            try {
              const parsed = JSON.parse(text);
              message = parsed.detail || parsed.error?.message || (typeof parsed.error === "string" ? parsed.error : message);
            } catch {
              if (text) message = text;
            }
            return new Response(
              JSON.stringify({ error: message }),
              {
                status: upstream.status,
                headers: { "Content-Type": "application/json" },
              }
            );
          }


          const data = await upstream.json();
          return new Response(JSON.stringify(data), {
            headers: { "Content-Type": "application/json" },
          });
        } catch (error: any) {
          console.error("Error activating model:", error);
          return new Response(
            JSON.stringify({ error: "Failed to forward activation to SAGE backend" }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        }
      },
    },
  },
});
