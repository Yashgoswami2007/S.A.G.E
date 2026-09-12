import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { parseAgentEvent, type AgentEvent } from "@/lib/agent-events";
import { PanelLeft, Plus, FolderOpen } from "lucide-react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/sage/Sidebar";
import { WorkspaceSidebar } from "@/components/sage/WorkspaceSidebar";
import { Composer } from "@/components/sage/Composer";
import { MessageItem } from "@/components/sage/Messages";
import { ConnectorsDialog } from "@/components/sage/ConnectorsDialog";
import { SettingsPanel } from "@/components/sage/SettingsPanel";
import { SageMark } from "@/components/sage/SageLogo";
import {
  flushChats,
  titleFrom,
  uid,
  useChats,
  useConnectors,
  useModels,
  type Attachment,
  type Chat,
  type ChatMessage,
} from "@/lib/sage-store";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "SAGE — Your AI thinking partner" },
      {
        name: "description",
        content:
          "SAGE is an AI chat workspace with file uploads, connectors, response styles and streaming answers.",
      },
      { property: "og:title", content: "SAGE — Your AI thinking partner" },
      {
        property: "og:description",
        content:
          "Chat with SAGE: streaming answers, file uploads, MCP-style connectors and multiple models.",
      },
    ],
  }),
  component: SagePage,
});

const SUGGESTIONS = [
  { label: "Write", prompt: "Help me write a short, warm launch announcement for my product." },
  { label: "Learn", prompt: "Explain how vector databases work, with a simple analogy." },
  { label: "Code", prompt: "Write a TypeScript debounce hook and explain the tricky parts." },
  { label: "Plan", prompt: "Plan a focused 5-day sprint for shipping a landing page." },
];

export const PROFILES = [
  { id: "auto", name: "Auto", blurb: "Auto-detect from prompt" },
  { id: "general", name: "General", blurb: "General purpose agent" },
  { id: "coder", name: "Coder", blurb: "Writes and runs code" },
  { id: "analyst", name: "Analyst", blurb: "Data and spreadsheet analysis" },
  { id: "inspector", name: "Inspector", blurb: "Diagrams and OCR" },
  { id: "documentor", name: "Documentor", blurb: "Generates reports and docs" }
];

function SagePage() {
  const { chats, setChats, hydrated } = useChats();
  const { connectors, toggle } = useConnectors();
  const models = useModels();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [workspaceSidebarOpen, setWorkspaceSidebarOpen] = useState(false);
  const [connectorsOpen, setConnectorsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [model, setModel] = useState<string>("");
  const [style, setStyle] = useState("normal");
  const [profile, setProfile] = useState("auto");
  const [streaming, setStreaming] = useState(false);
  const [modelLoading, setModelLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const retryCountRef = useRef(0);
  const MAX_RETRIES = 2;

  const activeChat = useMemo(
    () => chats.find((c) => c.id === activeId) ?? null,
    [chats, activeId],
  );
  const messages = activeChat?.messages ?? [];

  useEffect(() => {
    if (typeof window !== "undefined" && window.innerWidth < 768) setSidebarOpen(false);
  }, []);

  const lastMessageContent = messages[messages.length - 1]?.content;
  useEffect(() => {
    if (streaming && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "auto" });
    } else {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length, streaming, lastMessageContent]);

  useEffect(() => {
    if (!model && models.length > 0) {
      setModel(models[0]!.id);
    }
  }, [models, model]);

  const updateChat = useCallback(
    (id: string, updater: (chat: Chat) => Chat) => {
      const next = chatsRef.current.map((c) => (c.id === id ? { ...updater(c), updatedAt: Date.now() } : c));
      chatsRef.current = next;
      setChats(next);
    },
    [setChats],
  );

  // keep a ref of latest chats so streaming updates don't stale-close
  const chatsRef = useRef<Chat[]>(chats);
  useEffect(() => {
    chatsRef.current = chats;
  }, [chats]);

  const run = useCallback(
    async (chatId: string, history: ChatMessage[], resolvedProfile: string) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);

      const assistantId = uid();
      let intentionallyAborted = false;
      updateChat(chatId, (chat) => ({
        ...chat,
        messages: [
          ...history,
          { id: assistantId, role: "assistant", content: "", events: [], createdAt: Date.now() },
        ],
      }));

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            model,
            style,
            profile: resolvedProfile,
            connectors: connectors.filter((c) => c.enabled).map((c) => c.name),
            messages: history.map((m) => toApiMessage(m)),
            model_id: model,
            file_attachments: history.flatMap((m) =>
              (m.attachments ?? []).map((a) => a.serverPath).filter(Boolean)
            ),
          }),
        });

        if (!response.ok || !response.body) {
          let detail = "";
          try {
            const errObj = await response.json();
            detail = errObj?.error?.message || errObj?.detail || (typeof errObj?.error === "string" ? errObj.error : "");
          } catch {
            detail = await response.text().catch(() => "");
          }
          if (response.status === 429) toast.error("Rate limit reached — try again in a moment.");
          else if (response.status === 402) toast.error("AI credits exhausted. Add credits to continue.");
          else toast.error(detail || `SAGE server error (${response.status})`);

          // Keep assistant message in thread with an ERROR event and retry ability
          updateChat(chatId, (chat) => ({
            ...chat,
            messages: chat.messages.map((m) =>
              m.id === assistantId
                ? {
                  ...m,
                  events: [
                    ...(m.events || []),
                    {
                      type: "ERROR",
                      message: detail || `Request failed with status ${response.status}. Please check backend logs or retry.`,
                      recoverable: true,
                    },
                  ],
                }
                : m
            ),
          }));
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let acc = "";

        const processLines = (linesToProcess: string[]) => {
          let chunkTokens = "";
          const chunkEvents: AgentEvent[] = [];

          for (const line of linesToProcess) {
            if (!line.trim()) continue;
            console.log("[FRONTEND] raw SSE event received:", line);
            const event = parseAgentEvent(line);
            if (!event) {
              console.log("[FRONTEND] parsing failed or event was ignored");
              continue;
            }
            console.log("[FRONTEND] parsed event.type:", event.type);

            if (event.type === "TOKEN") {
              chunkTokens += event.token;
            } else {
              chunkEvents.push(event);
            }
          }

          if (chunkTokens || chunkEvents.length > 0) {
            updateChat(chatId, (chat) => ({
              ...chat,
              messages: chat.messages.map((m) => {
                if (m.id !== assistantId) return m;
                let newContent = m.content || "";
                if (chunkTokens) {
                  newContent += chunkTokens;
                }
                let newEvents = [...(m.events || [])];
                for (const evt of chunkEvents) {
                  if (evt.type === "FINAL") {
                    console.log("[FRONTEND] FINAL content:", evt.content);
                    // Defense-in-depth: strip any residual <think> tags
                    const cleaned = evt.content.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
                    // Only overwrite accumulated tokens if FINAL has meaningful content
                    if (cleaned) {
                      newContent = cleaned;
                    }
                    newEvents.push(evt);
                  } else if (evt.type === "CONFIRMATION_REQUIRED") {
                    // Render the event — user will approve/reject via the UI
                    newEvents.push(evt);
                  } else {
                    newEvents.push(evt);
                  }
                }
                console.log("[FRONTEND] accumulated content length:", newContent.length);
                return { ...m, content: newContent, events: newEvents };
              }),
            }));
          }
        };

        for (; ;) {
          const { done, value } = await reader.read();
          if (value) {
            acc += decoder.decode(value, { stream: true });
            const lines = acc.split(/\r?\n/);
            acc = lines.pop() ?? "";
            processLines(lines);
          }
          if (done) {
            if (acc) {
              processLines([acc]);
            }
            break;
          }
        }
      } catch (error) {
        const isAbort = (error as Error)?.name === "AbortError";
        if (isAbort) {
          intentionallyAborted = true;
        } else {
          const errMsg = (error as Error)?.message || "Connection interrupted.";
          toast.error(errMsg);
          updateChat(chatId, (chat) => ({
            ...chat,
            messages: chat.messages.map((m) => {
              if (m.id !== assistantId) return m;
              const events = [...(m.events || [])];
              if (!events.some((e) => e.type === "ERROR")) {
                events.push({
                  type: "ERROR",
                  message: `Stream interrupted: ${errMsg}. You can retry this request.`,
                  recoverable: true,
                });
              }
              return { ...m, events };
            }),
          }));
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
        flushChats(chatsRef.current);

        if (intentionallyAborted) {
          retryCountRef.current = 0;
          return;
        }

        // ── Response confirmation: auto-retry on empty response ──
        const finalChat = chatsRef.current.find((c) => c.id === chatId);
        const lastMsg = finalChat?.messages[finalChat.messages.length - 1];
        if (
          lastMsg?.role === "assistant" &&
          retryCountRef.current < MAX_RETRIES
        ) {
          try {
            const resp = await fetch("/api/chat/confirm-response", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                task_id: chatId,
                prompt: "Auto-retry", // Not fully used on backend yet
                response_content: lastMsg.content,
              }),
            });

            if (resp.ok) {
              const data = await resp.json();
              if (data.needs_retry) {
                retryCountRef.current += 1;
                console.log(
                  `[SAGE] Empty/invalid response detected via backend. Auto-retrying (${retryCountRef.current}/${MAX_RETRIES})...`
                );
                toast.info(`Retrying... (attempt ${retryCountRef.current + 1})`);

                // Remove the failed assistant message and re-run
                const trimmed = finalChat!.messages.filter((m) => m.id !== lastMsg.id);
                updateChat(chatId, (chat) => ({ ...chat, messages: trimmed }));
                // Small delay before retry
                await new Promise((r) => setTimeout(r, 500));
                void run(chatId, trimmed, resolvedProfile);
                return;
              }
            }
          } catch (e) {
            console.error("Failed to confirm response:", e);
          }
        }
        // Reset retry counter on successful response
        retryCountRef.current = 0;
      }
    },
    [connectors, model, style, updateChat],
  );

  const send = useCallback(
    (text: string, attachments: Attachment[]) => {
      const userMessage: ChatMessage = {
        id: uid(),
        role: "user",
        content: text,
        attachments,
        createdAt: Date.now(),
      };

      let resolvedProfile = profile;
      if (profile === "auto") {
        const lower = text.toLowerCase();
        if (attachments.some((a) => a.kind === "image")) resolvedProfile = "inspector";
        else if (lower.includes("code") || lower.includes("python") || lower.includes("script") || lower.includes("bug")) resolvedProfile = "coder";
        else if (lower.includes("excel") || lower.includes("csv") || lower.includes("data") || lower.includes("calculate")) resolvedProfile = "analyst";
        else if (lower.includes("report") || lower.includes("doc") || lower.includes("ppt")) resolvedProfile = "documentor";
        else resolvedProfile = "general";
      }

      let chatId = activeId;
      if (!chatId || !chatsRef.current.some((c) => c.id === chatId)) {
        chatId = uid();
        const chat: Chat = {
          id: chatId,
          title: titleFrom(text || attachments[0]?.name || "New chat"),
          messages: [],
          createdAt: Date.now(),
          updatedAt: Date.now(),
        };
        const next = [chat, ...chatsRef.current];
        chatsRef.current = next;
        setChats(next);
        setActiveId(chatId);
      }

      const current = chatsRef.current.find((c) => c.id === chatId);
      const history = [...(current?.messages ?? []), userMessage];
      updateChat(chatId, (chat) => ({
        ...chat,
        title: chat.messages.length === 0 ? titleFrom(text || userMessage.attachments?.[0]?.name || "New chat") : chat.title,
        messages: history,
      }));
      void run(chatId, history, resolvedProfile);
    },
    [activeId, run, setChats, updateChat, profile],
  );

  const retry = useCallback(() => {
    if (!activeChat) return;
    const trimmed = [...activeChat.messages];
    while (trimmed.length && trimmed[trimmed.length - 1]?.role === "assistant") trimmed.pop();
    if (!trimmed.length) return;
    updateChat(activeChat.id, (chat) => ({ ...chat, messages: trimmed }));

    // Simplistic retry using current profile setting or general
    void run(activeChat.id, trimmed, profile === "auto" ? "general" : profile);
  }, [activeChat, run, updateChat, profile]);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    retryCountRef.current = 0;
    setActiveId(null);
  }, []);

  // ── Model activation handler ──
  const handleModelChange = useCallback(
    async (newModelId: string) => {
      if (newModelId === model) return;
      // Find the target model to check if it needs activation
      const targetModel = models.find((m) => m.id === newModelId);
      if (targetModel && targetModel.status !== "READY") {
        setModelLoading(true);
        try {
          const resp = await fetch("/api/models/activate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_id: newModelId }),
          });
          if (!resp.ok) {
            const detail = await resp.text().catch(() => "");
            toast.error(`Failed to load model: ${detail || "Unknown error"}`);
            return;
          }
          toast.success(`${targetModel.name} is now active.`);
        } catch {
          toast.error("Failed to activate model.");
          return;
        } finally {
          setModelLoading(false);
        }
      }
      setModel(newModelId);
    },
    [model, models],
  );

  const deleteChat = useCallback(
    (id: string) => {
      const next = chatsRef.current.filter((c) => c.id !== id);
      chatsRef.current = next;
      setChats(next);
      if (activeId === id) setActiveId(null);
    },
    [activeId, setChats],
  );

  const connectedCount = connectors.filter((c) => c.enabled).length;

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-background text-foreground">
      <Sidebar
        chats={hydrated ? chats : []}
        activeId={activeId}
        onSelect={(id) => {
          abortRef.current?.abort();
          setActiveId(id);
          if (typeof window !== "undefined" && window.innerWidth < 768) setSidebarOpen(false);
        }}
        onNew={newChat}
        onDelete={deleteChat}
        onOpenConnectors={() => setConnectorsOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((v) => !v)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-2 px-3 py-2.5">
          <div className="flex items-center gap-2">
            {!sidebarOpen && (
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setSidebarOpen(true)}>
                <PanelLeft className="h-4 w-4" />
              </Button>
            )}
          </div>
          {!workspaceSidebarOpen && (
            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" onClick={() => setWorkspaceSidebarOpen(true)}>
              <FolderOpen className="h-4 w-4" />
            </Button>
          )}
        </header>

        {messages.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center px-4">
            <div className="w-full max-w-2xl">
              <div className="mb-6 flex items-center justify-center gap-3">
                <SageMark className="h-7 w-7 text-primary" />
                <h1 className="font-serif text-3xl tracking-tight">Good to see you</h1>
              </div>
              <Composer
                onSend={send}
                onStop={() => abortRef.current?.abort()}
                streaming={streaming}
                models={models}
                model={model || (models[0]?.id ?? "")}
                onModelChange={handleModelChange}
                style={style}
                onStyleChange={setStyle}
                profile={profile}
                onProfileChange={setProfile}
                onOpenConnectors={() => setConnectorsOpen(true)}
                connectedCount={connectedCount}
                modelLoading={modelLoading}
              />
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => send(s.prompt, [])}
                    className="rounded-full border border-border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-3xl space-y-7 px-4 py-6">
                {messages.map((message, index) => (
                  <MessageItem
                    key={message.id}
                    message={message}
                    streaming={streaming && index === messages.length - 1}
                    {...(message.role === "assistant" && index === messages.length - 1 ? { onRetry: retry } : {})}
                  />
                ))}
                <div ref={bottomRef} />
              </div>
            </div>
            <div className="px-4 pb-4">
              <div className="mx-auto w-full max-w-3xl">
                <Composer
                  compact
                  onSend={send}
                  onStop={() => abortRef.current?.abort()}
                  streaming={streaming}
                  models={models}
                  model={model || (models[0]?.id ?? "")}
                  onModelChange={handleModelChange}
                  style={style}
                  onStyleChange={setStyle}
                  profile={profile}
                  onProfileChange={setProfile}
                  onOpenConnectors={() => setConnectorsOpen(true)}
                  connectedCount={connectedCount}
                  modelLoading={modelLoading}
                />
                <p className="mt-2 text-center text-xs text-muted-foreground">
                  SAGE can make mistakes. Please double-check responses.
                </p>
              </div>
            </div>
          </>
        )}
      </main>

      <WorkspaceSidebar
        open={workspaceSidebarOpen}
        onToggle={() => setWorkspaceSidebarOpen((v) => !v)}
      />

      <ConnectorsDialog
        open={connectorsOpen}
        onOpenChange={setConnectorsOpen}
        connectors={connectors}
        onToggle={toggle}
      />
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
      <Toaster />
    </div>
  );
}

function toApiMessage(message: ChatMessage) {
  const images = (message.attachments ?? []).filter((a) => a.kind === "image");
  const texts = (message.attachments ?? []).filter((a) => a.kind === "text");
  const docs = (message.attachments ?? []).filter((a) => a.kind === "document");
  const textBody = [
    message.content,
    ...texts.map((t) => `\n\n--- File: ${t.name} ---\n${t.data.slice(0, 20000)}`),
    ...docs.map((d) => `\n\n[Attached file: ${d.name}${d.serverPath ? ` (path: ${d.serverPath})` : ""}]`),
  ]
    .filter(Boolean)
    .join("");

  if (images.length === 0) {
    return { role: message.role, content: textBody || "(empty message)" };
  }

  return {
    role: message.role,
    content: [
      { type: "text", text: textBody || "Please look at the attached image(s)." },
      ...images.map((img) => ({ type: "image_url", image_url: { url: img.data } })),
    ],
  };
}
