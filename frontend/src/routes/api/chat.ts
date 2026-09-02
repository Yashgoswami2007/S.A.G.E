import { createFileRoute } from "@tanstack/react-router";

type Part = { type: "text"; text: string } | { type: "image_url"; image_url: { url: string } };
type Msg = { role: "user" | "assistant" | "system"; content: string | Part[] };

type Body = {
  messages?: Msg[];
  model?: string;
  style?: string;
  connectors?: string[];
};

const STYLES: Record<string, string> = {
  normal: "Respond in your default, balanced voice.",
  concise: "Respond concisely, with fewer words and no filler.",
  explanatory: "Respond in an educational tone, explaining concepts along the way.",
  formal: "Respond in clear, polished, professional prose.",
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

        const connectors = body.connectors?.length
          ? `\nThe user has these connectors enabled: ${body.connectors.join(", ")}. You cannot call them live yet — if a request needs one, say what you would fetch from it.`
          : "";

        const system = `You are SAGE, a thoughtful, helpful AI assistant. You are direct, warm and precise. Use markdown for structure and fenced code blocks with language tags for code.${connectors}\n${STYLES[body.style ?? "normal"] ?? ""}`;

        const upstream = await fetch("http://127.0.0.1:8001/v1/chat/completions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: body.model || "default",
            stream: true,
            messages: [{ role: "system", content: system }, ...messages],
          }),
        });

        if (!upstream.ok || !upstream.body) {
          const text = await upstream.text().catch(() => "");
          return new Response(text || "Upstream error", { status: upstream.status || 500 });
        }

        const encoder = new TextEncoder();
        const decoder = new TextDecoder();
        const reader = upstream.body.getReader();

        let buffer = "";
        let inReasoning = false;

        const stream = new ReadableStream<Uint8Array>({
          async pull(controller) {
            const { done, value } = await reader.read();
            if (done) {
              if (inReasoning) {
                controller.enqueue(encoder.encode("</think>\n\n"));
              }
              controller.close();
              return;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) {
              const trimmed = line.trim();
              if (!trimmed.startsWith("data:")) continue;
              const payload = trimmed.slice(5).trim();
              if (payload === "[DONE]") continue;
              try {
                const json = JSON.parse(payload);
                const delta = json?.choices?.[0]?.delta;
                if (delta) {
                  let text = "";
                  if (delta.reasoning_content) {
                    if (!inReasoning) {
                      inReasoning = true;
                      text += "<think>\n";
                    }
                    text += delta.reasoning_content;
                  } else if (delta.content !== undefined && delta.content !== null) {
                    if (inReasoning) {
                      inReasoning = false;
                      text += "\n</think>\n\n";
                    }
                    text += delta.content;
                  }
                  if (text) controller.enqueue(encoder.encode(text));
                }
              } catch {
                // partial chunk; ignored
              }
            }
          },
          cancel() {
            void reader.cancel();
          },
        });

        return new Response(stream, {
          headers: {
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "no-cache",
          },
        });
      },
    },
  },
});
