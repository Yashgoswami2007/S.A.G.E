import { useRef, useState } from "react";
import {
  ArrowUp,
  Blocks,
  ChevronDown,
  FileText,
  Image as ImageIcon,
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
import { STYLES, uid, type Attachment } from "@/lib/sage-store";
import { toast } from "sonner";

const MAX_BYTES = 4 * 1024 * 1024;

export function Composer({
  onSend,
  onStop,
  streaming,
  models,
  model,
  onModelChange,
  style,
  onStyleChange,
  onOpenConnectors,
  connectedCount,
  compact,
}: {
  onSend: (text: string, attachments: Attachment[]) => void;
  onStop: () => void;
  streaming: boolean;
  models: {id: string, name: string, blurb: string}[];
  model: string;
  onModelChange: (id: string) => void;
  style: string;
  onStyleChange: (id: string) => void;
  onOpenConnectors: () => void;
  connectedCount: number;
  compact?: boolean;
}) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const activeModel = models.find((m) => m.id === model) ?? models[0] ?? { name: "Local Model" };
  const activeStyle = STYLES.find((s) => s.id === style) ?? STYLES[0];

  async function handleFiles(list: FileList | null) {
    if (!list) return;
    const next: Attachment[] = [];
    for (const file of Array.from(list)) {
      if (file.size > MAX_BYTES) {
        toast.error(`${file.name} is larger than 4 MB`);
        continue;
      }
      const isImage = file.type.startsWith("image/");
      const data = isImage ? await readAsDataUrl(file) : await file.text();
      next.push({
        id: uid(),
        name: file.name,
        mime: file.type || "text/plain",
        size: file.size,
        data,
        kind: isImage ? "image" : "text",
      });
    }
    if (next.length) setAttachments((prev) => [...prev, ...next]);
  }

  function submit() {
    const trimmed = text.trim();
    if (!trimmed && attachments.length === 0) return;
    if (streaming) return;
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
                <span className="max-w-36 truncate text-xs">{a.name}</span>
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
              <DropdownMenuItem onSelect={() => imageRef.current?.click()}>
                <ImageIcon className="h-4 w-4" /> Add photos
              </DropdownMenuItem>
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

          <div className="ml-auto flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 gap-1 rounded-full px-2.5 text-xs">
                  {activeModel.name}
                  <ChevronDown className="h-3.5 w-3.5" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel>Model</DropdownMenuLabel>
                {models.map((m) => (
                  <DropdownMenuItem key={m.id} onSelect={() => onModelChange(m.id)}>
                    <div>
                      <p className="text-sm">{m.name}</p>
                      <p className="text-xs text-muted-foreground">{m.blurb}</p>
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
