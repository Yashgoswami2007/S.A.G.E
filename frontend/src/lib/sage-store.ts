import { useCallback, useEffect, useState } from "react";

export type Attachment = {
  id: string;
  name: string;
  mime: string;
  size: number;
  /** data URL for images, plain text for text files */
  data: string;
  kind: "image" | "text";
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachments?: Attachment[];
  createdAt: number;
};

export type Chat = {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
};

export type Connector = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
};

export const DEFAULT_MODELS = [
  { id: "default", name: "Local Model", blurb: "Default local model" },
];

export function useModels() {
  const [models, setModels] = useState<{id: string, name: string, blurb: string}[]>(DEFAULT_MODELS);

  useEffect(() => {
    fetch("/api/models")
      .then((res) => res.json())
      .then((data) => {
        if (data && data.data && data.data.length > 0) {
          setModels(
            data.data.map((m: any) => ({
              id: m.id,
              name: m.id,
              blurb: "Local model loaded in llama-server",
            }))
          );
        }
      })
      .catch(console.error);
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

function write(key: string, value: unknown) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* quota */
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
