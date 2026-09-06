import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Wrench,
  CheckCircle2,
  XCircle,
  FileText,
  Terminal,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ListTodo,
  Loader2,
  Edit3,
  Brain,
  Code2,
  FileOutput,
  Clock,
} from "lucide-react";
import type { AgentEvent } from "@/lib/agent-events";

export function AgentEventRenderer({ events }: { events: AgentEvent[] }) {
  return (
    <div className="flex flex-col gap-3 my-4">
      {events.map((evt, idx) => (
        <EventSwitch key={idx} event={evt} />
      ))}
    </div>
  );
}

function EventSwitch({ event }: { event: AgentEvent }) {
  switch (event.type) {
    case "PLAN_CREATED":
      return <PlanCard event={event} />;
    case "TOOL_CALL":
      return <ToolCallChip event={event} />;
    case "TOOL_RESULT":
      return <ToolResultCard event={event} />;
    case "THINKING":
      return <ThinkingBlock event={event} />;
    case "FILE_CREATED":
      return <FileCreatedBadge event={event} />;
    case "FILE_MODIFIED":
      return <FileModifiedBadge event={event} />;
    case "COMMAND_STARTED":
    case "COMMAND_FINISHED":
      return <CommandBlock event={event} />;
    case "SANDBOX_STARTED":
    case "SANDBOX_FINISHED":
      return <SandboxBlock event={event} />;
    case "DOCUMENT_GENERATED":
      return <DocumentGeneratedBadge event={event} />;
    case "ERROR":
      return <ErrorBanner event={event} />;
    case "CONFIRMATION_REQUIRED":
      // Confirmations are usually handled by a modal at the page level
      return (
        <div className="rounded-lg border border-orange-500/30 bg-orange-500/10 p-3 text-sm text-orange-600 dark:text-orange-400">
          <div className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="h-4 w-4" />
            Action requires your approval
          </div>
          <div className="mt-1 opacity-90">{event.description}</div>
        </div>
      );
    case "FINAL":
    case "TOKEN":
      return null;
    default:
      return null;
  }
}

function PlanCard({ event }: { event: Extract<AgentEvent, { type: "PLAN_CREATED" }> }) {
  const [open, setOpen] = useState(true);
  
  return (
    <div className="rounded-xl border border-border bg-card text-sm">
      <button 
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between p-3 hover:bg-muted/50 rounded-xl transition-colors"
      >
        <div className="flex items-center gap-2 font-medium">
          <ListTodo className="h-4 w-4 text-primary" />
          Plan Created
        </div>
        {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
      </button>
      {open && (
        <div className="border-t border-border p-3 text-muted-foreground space-y-3">
          <p className="text-[13px] leading-relaxed">{event.plan.summary}</p>
          <ul className="space-y-2">
            {event.plan.steps.map((step) => (
              <li key={step.id} className="flex gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-medium text-foreground">
                  {step.id}
                </span>
                <div className="flex flex-col">
                  <span className="text-[13px]">{step.description}</span>
                  {step.tool && (
                    <span className="text-[11px] font-mono text-primary/80 mt-0.5">
                      {step.tool}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ToolCallChip({ event }: { event: Extract<AgentEvent, { type: "TOOL_CALL" }> }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground">
      <Wrench className="h-3.5 w-3.5 text-primary animate-pulse" />
      <span>Using tool <strong className="font-mono">{event.tool_name}</strong>...</span>
    </div>
  );
}

function ToolResultCard({ event }: { event: Extract<AgentEvent, { type: "TOOL_RESULT" }> }) {
  const [open, setOpen] = useState(false);
  const isSuccess = event.success;

  return (
    <div className="rounded-xl border border-border bg-card text-sm">
      <button 
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between p-3 hover:bg-muted/50 rounded-xl transition-colors"
      >
        <div className="flex items-center gap-2">
          {isSuccess ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <XCircle className="h-4 w-4 text-red-500" />
          )}
          <span className="font-medium text-foreground">
            {event.tool_name} {isSuccess ? "succeeded" : "failed"}
          </span>
        </div>
        {open ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
      </button>
      {open && (
        <div className="border-t border-border p-3 bg-muted/30">
          <pre className="whitespace-pre-wrap font-mono text-[11px] text-muted-foreground overflow-x-auto max-h-60">
            {event.error ? event.error : event.output}
          </pre>
        </div>
      )}
    </div>
  );
}

function ThinkingBlock({ event }: { event: Extract<AgentEvent, { type: "THINKING" }> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border/50 bg-muted/30 text-xs text-muted-foreground overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between p-2.5 hover:bg-muted/50 transition-colors"
      >
        <span className="font-medium flex items-center gap-1.5 truncate">
          <Brain className="h-3.5 w-3.5 text-primary shrink-0" />
          <span>Thought: {event.content.slice(0, 60)}{event.content.length > 60 ? "..." : ""}</span>
        </span>
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
      </button>
      {open && (
        <div className="border-t border-border/40 p-3 bg-background/50 font-mono text-[12px] leading-relaxed">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{event.content}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

function FileCreatedBadge({ event }: { event: Extract<AgentEvent, { type: "FILE_CREATED" }> }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-600 dark:text-emerald-400">
      <FileText className="h-3.5 w-3.5" />
      <span>Created <strong>{event.path.split('/').pop() || event.path.split('\\').pop()}</strong></span>
      <span className="opacity-70 text-[10px]">({Math.round(event.size_bytes / 1024)} KB)</span>
    </div>
  );
}

function FileModifiedBadge({ event }: { event: Extract<AgentEvent, { type: "FILE_MODIFIED" }> }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-yellow-500/30 bg-yellow-500/10 px-3 py-1.5 text-xs text-yellow-600 dark:text-yellow-400">
      <Edit3 className="h-3.5 w-3.5" />
      <span>Modified <strong>{event.path.split('/').pop() || event.path.split('\\').pop()}</strong></span>
    </div>
  );
}

function CommandBlock({ event }: { event: Extract<AgentEvent, { type: "COMMAND_STARTED" | "COMMAND_FINISHED" }> }) {
  const isFinished = event.type === "COMMAND_FINISHED";
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-xl overflow-hidden border border-border bg-[#0d1117] text-gray-300 font-mono text-[12px]">
      <div className="flex items-center justify-between bg-black/40 px-3 py-2 border-b border-border/50">
        <div className="flex items-center gap-2">
          <Terminal className="h-3.5 w-3.5" />
          <span>{event.type === "COMMAND_STARTED" ? event.command : "Command execution"}</span>
        </div>
        {!isFinished && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      </div>
      {isFinished && (
        <div className="p-3 overflow-x-auto max-h-60">
          {(event as any).stdout && <div className="whitespace-pre-wrap mb-2">{(event as any).stdout}</div>}
          {(event as any).stderr && <div className="whitespace-pre-wrap text-red-400">{(event as any).stderr}</div>}
          <div className={`mt-2 ${((event as any).exit_code === 0) ? 'text-emerald-400' : 'text-red-400'}`}>
            Exited with code {(event as any).exit_code}
          </div>
        </div>
      )}
    </div>
  );
}

function ErrorBanner({ event }: { event: Extract<AgentEvent, { type: "ERROR" }> }) {
  return (
    <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3.5 text-sm text-red-600 dark:text-red-400 flex items-start gap-3">
      <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-red-500" />
      <div className="flex-1 space-y-1">
        <div className="flex items-center justify-between gap-2 font-semibold">
          <span>{event.recoverable ? "Generation Issue" : "System Error"}</span>
          {event.recoverable && (
            <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-medium text-amber-500">
              Recoverable
            </span>
          )}
        </div>
        <div className="text-[13px] leading-relaxed opacity-95">{event.message}</div>
      </div>
    </div>
  );
}

function SandboxBlock({ event }: { event: Extract<AgentEvent, { type: "SANDBOX_STARTED" | "SANDBOX_FINISHED" }> }) {
  const isFinished = event.type === "SANDBOX_FINISHED";
  const [open, setOpen] = useState(true);

  return (
    <div className="rounded-xl overflow-hidden border border-border bg-[#0d1117] text-gray-300 font-mono text-[12px]">
      <div className="flex items-center justify-between bg-black/40 px-3 py-2 border-b border-border/50">
        <div className="flex items-center gap-2">
          <Code2 className="h-3.5 w-3.5 text-primary" />
          <span>
            {event.type === "SANDBOX_STARTED"
              ? `Running ${(event as any).language} code...`
              : "Code execution"}
          </span>
          {isFinished && (
            <span className="flex items-center gap-1 text-[10px] text-gray-500">
              <Clock className="h-3 w-3" />
              {((event as any).duration_ms / 1000).toFixed(2)}s
            </span>
          )}
        </div>
        {!isFinished ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
        ) : (
          <button onClick={() => setOpen(!open)}>
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        )}
      </div>

      {/* Show code preview for SANDBOX_STARTED */}
      {event.type === "SANDBOX_STARTED" && (event as any).code && (
        <div className="p-3 overflow-x-auto max-h-40 border-b border-border/30 bg-[#161b22]">
          <pre className="whitespace-pre-wrap text-blue-300">{(event as any).code}</pre>
        </div>
      )}

      {/* Show output for SANDBOX_FINISHED */}
      {isFinished && open && (
        <div className="p-3 overflow-x-auto max-h-60">
          {(event as any).stdout && (
            <div className="whitespace-pre-wrap mb-2">{(event as any).stdout}</div>
          )}
          {(event as any).stderr && (
            <div className="whitespace-pre-wrap text-red-400 mb-2">{(event as any).stderr}</div>
          )}
          <div className={`mt-1 text-[11px] ${(event as any).exit_code === 0 ? "text-emerald-400" : "text-red-400"}`}>
            Exit code: {(event as any).exit_code}
          </div>
          {(event as any).files_created?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {(event as any).files_created.map((f: string, i: number) => (
                <span key={i} className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 text-[10px] text-emerald-400">
                  <FileOutput className="h-3 w-3" />
                  {f.split('/').pop() || f.split('\\').pop()}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DocumentGeneratedBadge({ event }: { event: Extract<AgentEvent, { type: "DOCUMENT_GENERATED" }> }) {
  const typeLabel: Record<string, string> = {
    docx: "📄 Word",
    xlsx: "📊 Excel",
    pptx: "📽️ PowerPoint",
    pdf: "📕 PDF",
  };
  const label = typeLabel[event.doc_type] || `📎 ${event.doc_type.toUpperCase()}`;
  const filename = event.path.split('/').pop() || event.path.split('\\').pop();

  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs text-primary">
      <FileOutput className="h-3.5 w-3.5" />
      <span>{label}: <strong>{filename}</strong></span>
      <span className="opacity-60 text-[10px]">({Math.round(event.size_bytes / 1024)} KB)</span>
    </div>
  );
}
