import { useState } from "react";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { Check, Copy, FileText, RefreshCw, Brain, ChevronDown, ChevronRight } from "lucide-react";
import { SageMark } from "./SageLogo";
import { AgentEventRenderer } from "./AgentEventRenderer";
import type { ChatMessage } from "@/lib/sage-store";

export function MessageItem({
  message,
  onRetry,
  streaming,
}: {
  message: ChatMessage;
  onRetry?: () => void;
  streaming?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] space-y-2">
          {message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap justify-end gap-2">
              {message.attachments.map((a) =>
                a.kind === "image" ? (
                  <img
                    key={a.id}
                    src={a.data}
                    alt={a.name}
                    className="max-h-44 rounded-xl border border-border object-cover"
                  />
                ) : (
                  <div
                    key={a.id}
                    className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs"
                  >
                    <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                    {a.name}
                  </div>
                ),
              )}
            </div>
          )}
          {message.content && (
            <div className="rounded-2xl bg-user-bubble px-4 py-3 text-[15px] leading-relaxed text-user-bubble-foreground">
              <p className="whitespace-pre-wrap">{message.content}</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <SageMark className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        {message.events && message.events.length > 0 && (
          <AgentEventRenderer events={message.events} />
        )}
        
        {message.content ? (
          <div className="sage-prose text-[15px] text-foreground space-y-4">
            {(() => {
              const parts = message.content.split(/(<think>|<\/think>)/);
              let inThink = false;
              return parts.map((part, i) => {
                if (part === "<think>") {
                  inThink = true;
                  return null;
                }
                if (part === "</think>") {
                  inThink = false;
                  return null;
                }
                if (!part.trim() && !inThink) return null;
                
                if (inThink) {
                  const isLive = Boolean(streaming && (i === parts.length - 1 || (i === parts.length - 2 && !parts[parts.length - 1])));
                  return (
                    <ThinkingSection
                      key={i}
                      content={part}
                      isLive={isLive}
                    />
                  );
                }
                const isLastPart = i === parts.length - 1 || (i === parts.length - 2 && !parts[parts.length - 1]);
                return (
                  <div key={i} className="relative">
                    <MarkdownRenderer content={part} />
                    {streaming && isLastPart && (
                      <span className="inline-block w-1.5 h-4 ml-1 bg-primary animate-pulse align-middle" />
                    )}
                  </div>
                );
              });
            })()}
          </div>
        ) : (
          !message.events || message.events.length === 0 || (message.events[message.events.length - 1]!.type !== "FINAL" && message.events[message.events.length - 1]!.type !== "ERROR") ? (
            <ThinkingDots />
          ) : null
        )}

        {!streaming && message.content && (
          <div className="mt-2 flex items-center gap-1 text-muted-foreground">
            <button
              type="button"
              aria-label="Copy response"
              className="rounded-md p-1.5 transition-colors hover:bg-accent hover:text-foreground"
              onClick={() => {
                void navigator.clipboard.writeText(message.content);
                setCopied(true);
                setTimeout(() => setCopied(false), 1600);
              }}
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
            {onRetry && (
              <button
                type="button"
                aria-label="Retry response"
                className="rounded-md p-1.5 transition-colors hover:bg-accent hover:text-foreground"
                onClick={onRetry}
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ThinkingSection({
  content,
  isLive,
}: {
  content: string;
  isLive: boolean;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-xl border border-border/70 bg-card/60 overflow-hidden text-sm transition-all shadow-xs my-2">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between px-3.5 py-2 hover:bg-muted/50 transition-colors text-muted-foreground select-none"
      >
        <div className="flex items-center gap-2 text-xs font-medium">
          <Brain className={`h-3.5 w-3.5 text-primary ${isLive ? "animate-pulse" : ""}`} />
          <span className="text-foreground/90 font-medium">Thinking Process</span>
          {isLive ? (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/10 text-primary">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-ping" />
              Thinking live...
            </span>
          ) : (
            <span className="text-[11px] text-muted-foreground/70 font-normal">
              (click to {open ? "collapse" : "expand"})
            </span>
          )}
        </div>
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
      </button>
      {open && (
        <div className="border-t border-border/40 px-3.5 py-3 text-muted-foreground font-mono text-[12.5px] leading-relaxed max-h-96 overflow-y-auto bg-muted/20">
          <MarkdownRenderer content={content} />
          {isLive && (
            <span className="inline-block w-1.5 h-3.5 ml-1 bg-primary animate-pulse align-middle" />
          )}
        </div>
      )}
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5 py-1 text-sm text-muted-foreground">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.2s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.1s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
    </div>
  );
}
