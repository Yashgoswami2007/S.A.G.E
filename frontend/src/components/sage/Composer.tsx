import { useRef, useState } from "react";
import {
  ArrowUp,
  Blocks,
  ChevronDown,
  FileText,
  Image as ImageIcon,
  Loader2,
  Paperclip,
  Plus,
  Settings2,
  Square,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { STYLES, uid, type Attachment, type ModelInfo, DEFAULT_MODELS } from "@/lib/sage-store";
import { PROFILES } from "@/routes/index";
import { toast } from "sonner";



export function Composer({
  onSend,
  onStop,
  streaming,
  models,
  model,
  onModelChange,
  style,
  onStyleChange,
  profile,
  onProfileChange,
  onOpenConnectors,
  connectedCount,
  compact,
  modelLoading,
}: {
  onSend: (text: string, attachments: Attachment[]) => void;
  onStop: () => void;
  streaming: boolean;
  models: ModelInfo[];
  model: string;
  onModelChange: (id: string) => void;
  style: string;
  onStyleChange: (id: string) => void;
  profile: string;
  onProfileChange: (id: string) => void;
  onOpenConnectors: () => void;
  connectedCount: number;
  compact?: boolean;
  modelLoading?: boolean;
}) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const activeModel = models.find((m) => m.id === model) ?? models[0] ?? { name: "Local Model", supports_image_upload: false, supports_vision: false, status: "UNAVAILABLE" };
  const selectedModel: ModelInfo = models.find((m) => m.id === model) ?? models[0] ?? DEFAULT_MODELS[0]!;
  const activeStyle = STYLES.find((s) => s.id === style) ?? STYLES[0];

  async function handleFiles(list: FileList | null) {
    if (!list) return;
    const next: Attachment[] = [];
    for (const file of Array.from(list)) {
      const isImage = file.type.startsWith("image/");
      const isText = file.type.startsWith("text/") || /\.(txt|md|py|js|ts|json|csv|xml|yaml|yml|toml|ini|cfg|log|sh|bat|ps1|rb|go|rs|c|cpp|h|java|sql)$/i.test(file.name);

      let data = "";
      let kind: "image" | "text" | "document" = "document";
      let serverPath: string | undefined;

      if (isImage) {
        // Images: read as data URL for inline preview AND upload to server
        data = await readAsDataUrl(file);
        kind = "image";
      } else if (isText) {
        // Text files: read content for inline display
        data = await file.text();
        kind = "text";
      } else {
        // Documents (PDF, DOCX, XLSX, etc.): upload to server only
        data = `[${file.name}] (${formatSize(file.size)})`;
        kind = "document";
      }

      // Upload file to backend server
      try {
        const formData = new FormData();
        formData.append("files", file);
        formData.append("session_id", "default");
        const uploadResp = await fetch("/api/upload", { method: "POST", body: formData });
        if (uploadResp.ok) {
          const uploadData = await uploadResp.json();
          if (uploadData.paths && uploadData.paths.length > 0) {
            serverPath = uploadData.paths[0];
          }
        } else {
          toast.error(`Failed to upload ${file.name}`);
        }
      } catch (err) {
        toast.error(`Upload error: ${file.name}`);
        console.error("Upload error:", err);
      }

      next.push({
        id: uid(),
        name: file.name,
        mime: file.type || "application/octet-stream",
        size: file.size,
        data,
        kind,
        serverPath: serverPath || undefined,
      });
    }
    if (next.length) setAttachments((prev) => [...prev, ...next]);
  }

  function submit() {
    const trimmed = text.trim();
    if (!trimmed && attachments.length === 0) return;
    if (streaming || modelLoading) return;
    onSend(trimmed, attachments);
    setText("");
    setAttachments([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  }

  return (
    <div className="w-full">
      <div className="rounded-3xl border border-border bg-card shadow-[0_2px_16px_-8px_oklch(0_0_0/0.25)]">
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 px-3 pt-3">
            {attachments.map((a) => (
              <div
                key={a.id}
                className="flex items-center gap-2 rounded-xl border border-border bg-secondary px-2.5 py-1.5"
              >
                {a.kind === "image" ? (
                  <img src={a.data} alt={a.name} className="h-8 w-8 rounded-md object-cover" />
                ) : (
                  <FileText className="h-4 w-4 text-muted-foreground" />
                )}
                <div className="flex flex-col">
                  <span className="max-w-36 truncate text-xs">{a.name}</span>
                  {a.serverPath && (
                    <span className="text-[10px] text-emerald-500">✓ Uploaded</span>
                  )}
                </div>
                <button
                  type="button"
                  aria-label={`Remove ${a.name}`}
                  className="text-muted-foreground transition-colors hover:text-foreground"
                  onClick={() => setAttachments((prev) => prev.filter((x) => x.id !== a.id))}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={text}
          rows={1}
          placeholder={compact ? "Reply to SAGE…" : "How can SAGE help you today?"}
          onChange={(e) => {
            setText(e.target.value);
            const el = e.currentTarget;
            el.style.height = "auto";
            el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="max-h-64 w-full resize-none bg-transparent px-4 pt-4 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground"
        />

        <div className="flex items-center gap-1 px-2.5 pb-2.5 pt-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full border border-border"
                aria-label="Add content"
              >
                <Plus className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-60">
              <DropdownMenuItem onSelect={() => fileRef.current?.click()}>
                <Paperclip className="h-4 w-4" /> Upload a file
              </DropdownMenuItem>
              {selectedModel.supports_image_upload && (
                <DropdownMenuItem onSelect={() => imageRef.current?.click()}>
                  <ImageIcon className="h-4 w-4" /> Add photos
                </DropdownMenuItem>
              )}
              {!selectedModel.supports_image_upload && (
                <DropdownMenuItem disabled className="opacity-50">
                  <ImageIcon className="h-4 w-4" /> Add photos
                  <span className="ml-auto text-[10px] text-muted-foreground">Vision model required</span>
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={onOpenConnectors}>
                <Blocks className="h-4 w-4" /> Connectors
                <span className="ml-auto text-xs text-muted-foreground">{connectedCount}</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 gap-1 rounded-full px-2.5 text-xs">
                <Settings2 className="h-3.5 w-3.5" />
                {activeStyle.name}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-60">
              <DropdownMenuLabel>Response style</DropdownMenuLabel>
              {STYLES.map((s) => (
                <DropdownMenuItem key={s.id} onSelect={() => onStyleChange(s.id)}>
                  <div>
                    <p className="text-sm">{s.name}</p>
                    <p className="text-xs text-muted-foreground">{s.blurb}</p>
                  </div>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 gap-1 rounded-full px-2.5 text-xs">
                {PROFILES.find(p => p.id === profile)?.name || "Auto"}
                <ChevronDown className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-60">
              <DropdownMenuLabel>Agent Profile</DropdownMenuLabel>
              {PROFILES.map((p) => (
                <DropdownMenuItem key={p.id} onSelect={() => onProfileChange(p.id)}>
                  <div>
                    <p className="text-sm">{p.name}</p>
                    <p className="text-xs text-muted-foreground">{p.blurb}</p>
                  </div>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="ml-auto flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 gap-1 rounded-full px-2.5 text-xs">
                  {modelLoading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <span
                      className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${
                        selectedModel.status === "READY" ? "bg-emerald-500" :
                        selectedModel.status === "DEGRADED" ? "bg-amber-500" :
                        "bg-zinc-400"
                      }`}
                    />
                  )}
                  {modelLoading ? "Loading…" : activeModel.name}
                  <ChevronDown className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuLabel>Model</DropdownMenuLabel>
                {models.map((m) => (
                  <DropdownMenuItem key={m.id} onSelect={() => onModelChange(m.id)} disabled={modelLoading === true}>
                    <div className="flex w-full items-start gap-2">
                      <span
                        className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${
                          m.status === "READY" ? "bg-emerald-500" :
                          m.status === "DEGRADED" ? "bg-amber-500" :
                          "bg-zinc-400"
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">{m.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {m.blurb}
                          {m.status !== "READY" && " · Click to load"}
                        </p>
                      </div>
                    </div>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            {streaming ? (
              <Button
                size="icon"
                className="h-8 w-8 rounded-full"
                onClick={onStop}
                aria-label="Stop response"
              >
                <Square className="h-3.5 w-3.5" />
              </Button>
            ) : modelLoading ? (
              <Button
                size="icon"
                className="h-8 w-8 rounded-full"
                disabled
                aria-label="Loading model"
              >
                <Loader2 className="h-4 w-4 animate-spin" />
              </Button>
            ) : (
              <Button
                size="icon"
                className="h-8 w-8 rounded-full"
                onClick={submit}
                disabled={!text.trim() && attachments.length === 0}
                aria-label="Send message"
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </div>

      <input
        ref={fileRef}
        type="file"
        multiple
        accept=".pdf,.docx,.doc,.xlsx,.xls,.csv,.txt,.md,.py,.js,.ts,.json,.xml,.yaml,.yml,.png,.jpg,.jpeg,.gif,.webp,.bmp,.tiff,.pptx,.ppt,.zip,.tar,.gz"
        className="hidden"
        onChange={(e) => {
          void handleFiles(e.target.files);
          e.target.value = "";
        }}
      />
      <input
        ref={imageRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => {
          void handleFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function readAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
