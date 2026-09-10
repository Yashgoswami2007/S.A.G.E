import { createFileRoute } from "@tanstack/react-router";

type Part = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };
type Msg = { role: "user" | "assistant" | "system"; content: string | Part[] };

type Body = {
  messages?: Msg[];
  model?: string;
  model_id?: string;
  style?: string;
  profile?: string;
  connectors?: string[];
  granted_paths?: any[];
  file_attachments?: string[];
};

export const Route = createFileRoute("/api/chat")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const body = (await request.json()) as Body;
        const messages = body.messages;
        if (!Array.isArray(messages) || messages.length === 0) {
          return new Response("Messages are required", { status: 400 });
        }

        // We use the most recent user message as the prompt for the agent
        const lastMessage = messages[messages.length - 1]!;
        let prompt = "";
        let file_attachments: string[] = body.file_attachments || [];

        if (typeof lastMessage.content === "string") {
          prompt = lastMessage.content;
        } else if (Array.isArray(lastMessage.content)) {
          const textParts = lastMessage.content.filter(p => p.type === "text").map(p => (p as any).text);
          prompt = textParts.join("\n");
          // Extract image URLs for the vision model if no file_attachments already provided
          const imageParts = lastMessage.content.filter(p => p.type === "image_url");
          if (imageParts.length > 0 && file_attachments.length === 0) {
            // Images are base64 data URLs — the backend will handle them via the prompt context
            prompt += "\n\n[User attached " + imageParts.length + " image(s)]";
          }
        }

        const history = messages.slice(0, -1).map((msg) => ({
          role: msg.role,
          content:
            typeof msg.content === "string"
              ? msg.content
              : msg.content
                  .filter((part: any) => part.type === "text")
                  .map((part: any) => part.text)
                  .join("\n"),
        })).filter(msg => msg.content && msg.content.trim().length > 0);

        console.log("[PROXY] Sending upstream request to /api/chat/stream...");
        console.log("[PROXY] file_attachments:", file_attachments);

        let upstream: Response;
        try {
          upstream = await fetch("http://127.0.0.1:8000/api/chat/stream", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              prompt: prompt,
              profile: body.profile || "general",
              style: body.style || "normal",
              model_id: body.model_id || null,
              granted_paths: body.granted_paths,
              file_attachments: file_attachments,
              history: history,
            }),
          });
        } catch (fetchErr: any) {
          console.error("[PROXY] Failed to connect to SAGE backend:", fetchErr);
          return new Response(
            JSON.stringify({
              error: {
                code: "BACKEND_UNAVAILABLE",
                message: "Unable to connect to SAGE backend server at http://127.0.0.1:8000. Please ensure the backend is running.",
                details: { error: String(fetchErr) },
              },
              detail: "Unable to connect to SAGE backend server at http://127.0.0.1:8000. Please ensure the backend is running.",
            }),
            {
              status: 503,
              headers: { "Content-Type": "application/json" },
            }
          );
        }

        if (!upstream.ok || !upstream.body) {
          const rawText = await upstream.text().catch(() => "");
          console.error("[PROXY] Upstream error:", upstream.status, rawText);
          let errorPayload: any;
          try {
            errorPayload = JSON.parse(rawText);
          } catch {
            errorPayload = {
              error: {
                code: `UPSTREAM_${upstream.status}`,
                message: rawText || "SAGE backend returned an error.",
              },
              detail: rawText || "SAGE backend returned an error.",
            };
          }
          return new Response(JSON.stringify(errorPayload), {
            status: upstream.status || 500,
            headers: { "Content-Type": "application/json" },
          });
        }

        console.log("[PROXY] Upstream stream initiated successfully. Forwarding...");

        const headers = new Headers();
        headers.set("Content-Type", "text/event-stream");
        headers.set("Cache-Control", "no-cache");
        headers.set("Connection", "keep-alive");
        headers.set("X-Accel-Buffering", "no");

        return new Response(upstream.body, {
          status: upstream.status,
          headers: headers,
        });

      },
    },
  },
});
