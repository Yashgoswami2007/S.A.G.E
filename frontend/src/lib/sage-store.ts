import { useCallback, useEffect, useState } from "react";
import type { AgentEvent } from "./agent-events";

export type Attachment = {
  id: string;
  name: string;
  mime: string;
  size: number;
  /** data URL for images, plain text for text files, status text for uploaded docs */
  data: string;
  kind: "image" | "text" | "document";
  /** Workspace-relative path on the server after upload */
  serverPath?: string | undefined;
};

export type ServerAttachment = {
  path: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  events?: AgentEvent[];
  createdAt: number;
};

export type GrantedPath = {
  id: string;
  path: string;
  permission: "read" | "readwrite";
  grantedAt: number;
  label: string;
};

export type Chat = {
  id: string;
  title: string;
  messages: ChatMessage[];
  grantedPaths?: GrantedPath[];
  createdAt: number;
  updatedAt: number;
};

export type Connector = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
};

export type ModelInfo = {
  id: string;
  name: string;
  status: "READY" | "DEGRADED" | "UNAVAILABLE";
  capabilities: string[];
  supports_vision: boolean;
  supports_image_upload: boolean;
  supports_files: boolean;
  min_vram_gb: number;
  context_length: number;
  is_default: boolean;
  blurb: string;
};

export const DEFAULT_MODELS: ModelInfo[] = [
  {
    id: "default",
    name: "Local Model",
    status: "UNAVAILABLE",
    capabilities: ["reasoning", "general"],
    supports_vision: false,
    supports_image_upload: false,
    supports_files: true,
    min_vram_gb: 5,
    context_length: 8192,
    is_default: true,
    blurb: "Default local model",
  },
];

function _makeBlurb(m: { capabilities: string[]; min_vram_gb: number; status: string; is_default: boolean }): string {
  const caps = m.capabilities.filter(c => c !== "general");
  const parts: string[] = [];
  if (caps.includes("vision")) parts.push("Vision");
  if (caps.includes("coding")) parts.push("Coding");
  if (caps.includes("reasoning")) parts.push("Reasoning");
  let blurb = parts.join(" · ") || "General purpose";
  blurb += ` · ~${m.min_vram_gb}GB`;
  if (m.is_default) blurb += " · Default";
  return blurb;
}

export function useModels() {
  const [models, setModels] = useState<ModelInfo[]>(DEFAULT_MODELS);

  useEffect(() => {
    let isMounted = true;
    fetch("/api/models")
      .then(async (res) => {
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          console.warn("[useModels] Server returned non-OK status:", res.status, errData);
          return null;
        }
        return res.json().catch(() => null);
      })
      .then((data) => {
        if (!isMounted || !data) return;
        if (Array.isArray(data.models) && data.models.length > 0) {
          const mapped: ModelInfo[] = data.models.map((m: any) => ({
            id: m.id,
            name: m.name,
            status: m.status || "UNAVAILABLE",
            capabilities: m.capabilities || ["reasoning", "general"],
            supports_vision: m.supports_vision ?? false,
            supports_image_upload: m.supports_image_upload ?? false,
            supports_files: m.supports_files ?? true,
            min_vram_gb: m.min_vram_gb ?? 5,
            context_length: m.context_length ?? 8192,
            is_default: m.is_default ?? false,
            blurb: _makeBlurb(m),
          }));
          // Sort: default model first, then by READY status, then by priority
          mapped.sort((a, b) => {
            if (a.is_default && !b.is_default) return -1;
            if (!a.is_default && b.is_default) return 1;
            if (a.status === "READY" && b.status !== "READY") return -1;
            if (a.status !== "READY" && b.status === "READY") return 1;
            return 0;
          });
          setModels(mapped);
        }
      })
      .catch((err) => {
        console.warn("[useModels] Network or parsing error fetching models, retaining fallback models:", err);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return models;
}

export const STYLES = [
  { id: "normal", name: "Normal", blurb: "Default responses" },
  { id: "concise", name: "Concise", blurb: "Shorter responses" },
  { id: "explanatory", name: "Explanatory", blurb: "Educational responses" },
  { id: "formal", name: "Formal", blurb: "Clear and polished" },
] as const;

export const DEFAULT_CONNECTORS: Connector[] = [
  { id: "gdrive", name: "Google Drive", description: "Search and read docs & sheets", enabled: false },
  { id: "github", name: "GitHub", description: "Browse repos, issues and PRs", enabled: false },
  { id: "slack", name: "Slack", description: "Search channels and threads", enabled: false },
  { id: "notion", name: "Notion", description: "Read pages and databases", enabled: false },
  { id: "linear", name: "Linear", description: "Track issues and projects", enabled: false },
  { id: "websearch", name: "Web search", description: "Look things up on the web", enabled: true },
];

const CHATS_KEY = "sage.chats.v1";
const CONNECTORS_KEY = "sage.connectors.v1";

export const uid = () => Math.random().toString(36).slice(2, 10);

function read<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

let writeTimeouts: Record<string, any> = {};

function write(key: string, value: unknown, immediate: boolean = false) {
  if (typeof window === "undefined") return;
  if (writeTimeouts[key]) {
    clearTimeout(writeTimeouts[key]);
    delete writeTimeouts[key];
  }
  const doWrite = () => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* quota */
    }
  };
  if (immediate) {
    doWrite();
  } else {
    writeTimeouts[key] = setTimeout(doWrite, 150);
  }
}

export function useChats() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setChats(read<Chat[]>(CHATS_KEY, []));
    setHydrated(true);
  }, []);

  const persist = useCallback((next: Chat[]) => {
    setChats(next);
    write(CHATS_KEY, next);
  }, []);

  return { chats, setChats: persist, hydrated };
}

export function flushChats(chats: Chat[]) {
  write(CHATS_KEY, chats, true);
}

export function useConnectors() {
  const [connectors, setConnectors] = useState<Connector[]>(DEFAULT_CONNECTORS);

  useEffect(() => {
    setConnectors(read<Connector[]>(CONNECTORS_KEY, DEFAULT_CONNECTORS));
  }, []);

  const update = useCallback((next: Connector[]) => {
    setConnectors(next);
    write(CONNECTORS_KEY, next);
  }, []);

  const toggle = useCallback(
    (id: string) => {
      setConnectors((prev) => {
        const next = prev.map((c) => (c.id === id ? { ...c, enabled: !c.enabled } : c));
        write(CONNECTORS_KEY, next);
        return next;
      });
    },
    [],
  );

  return { connectors, setConnectors: update, toggle };
}

export function titleFrom(text: string) {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > 48 ? `${clean.slice(0, 48)}…` : clean || "New chat";
}

export function groupChats(chats: Chat[]) {
  const now = Date.now();
  const day = 86_400_000;
  const today: Chat[] = [];
  const week: Chat[] = [];
  const older: Chat[] = [];
  for (const chat of [...chats].sort((a, b) => b.updatedAt - a.updatedAt)) {
    const age = now - chat.updatedAt;
    if (age < day) today.push(chat);
    else if (age < day * 7) week.push(chat);
    else older.push(chat);
  }
  return [
    { label: "Today", items: today },
    { label: "Previous 7 days", items: week },
    { label: "Older", items: older },
  ].filter((g) => g.items.length > 0);
}
