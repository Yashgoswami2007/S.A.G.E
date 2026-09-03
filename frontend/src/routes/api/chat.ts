import { createFileRoute } from "@tanstack/react-router";

type Part = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };
type Msg = { role: "user" | "assistant" | "system"; content: string | Part[] };

type Body = {
  messages?: Msg[];
  model?: string;
  style?: string;
  profile?: string;
  connectors?: string[];
  granted_paths?: any[];
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
        let file_attachments: string[] = [];

        if (typeof lastMessage.content === "string") {
          prompt = lastMessage.content;
        } else if (Array.isArray(lastMessage.content)) {
          const textParts = lastMessage.content.filter(p => p.type === "text").map(p => (p as any).text);
          prompt = textParts.join("\n");
          // TODO: handle images properly if sending to agent backend
        }

        console.log("[PROXY] Sending upstream request to /api/chat/stream...");
        const upstream = await fetch("http://127.0.0.1:8000/api/chat/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            prompt: prompt,
            profile: body.profile || "general",
            style: body.style || "normal",
            granted_paths: body.granted_paths,
            file_attachments: file_attachments
          }),
        });

        if (!upstream.ok || !upstream.body) {
          const text = await upstream.text().catch(() => "");
          console.error("[PROXY] Upstream error:", upstream.status, text);
          return new Response(text || "Upstream error", { status: upstream.status || 500 });
        }

        console.log("[PROXY] Upstream stream initiated successfully. Forwarding...");

        const { readable, writable } = new TransformStream({
          transform(chunk, controller) {
            console.log("[PROXY] upstream event received, length:", chunk.length);
            console.log("[PROXY] event forwarded");
            controller.enqueue(chunk);
          }
        });

        upstream.body.pipeTo(writable).catch((err: Error) => {
          console.error("[PROXY] pipe error:", err);
        });

        const headers = new Headers();
        headers.set("Content-Type", "text/event-stream");
        headers.set("Cache-Control", "no-cache");
        headers.set("Connection", "keep-alive");
        headers.set("X-Accel-Buffering", "no");

        return new Response(readable, {
          status: upstream.status,
          headers: headers,
        });
      },
    },
  },
});
