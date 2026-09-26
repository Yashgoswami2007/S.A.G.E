import { useEffect, useState, useRef, useCallback } from "react";
import {
  BookOpen,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Trash2,
  UploadCloud,
  RefreshCw,
  FileText,
  FileSpreadsheet,
  FileImage,
  FileCode,
  File,
  Search,
  X,
  Database,
  HardDrive,
  Clock,
  Layers,
  AlertTriangle,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { toast } from "sonner";

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface RagDocument {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: "pending" | "indexing" | "indexed" | "failed";
  error: string | null;
  created_at: string;
  updated_at: string | null;
  chunk_count: number;
  page_count: number;
}

interface QueueStatus {
  status: "running" | "not_running";
  pending_count?: number;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMs / 3600000);
  const diffDay = Math.floor(diffMs / 86400000);

  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function getFileIcon(fileType: string) {
  switch (fileType) {
    case "pdf":
      return <FileText className="h-5 w-5 text-red-400" />;
    case "docx":
      return <FileText className="h-5 w-5 text-blue-400" />;
    case "xlsx":
      return <FileSpreadsheet className="h-5 w-5 text-emerald-400" />;
    case "pptx":
      return <FileImage className="h-5 w-5 text-orange-400" />;
    case "md":
      return <FileCode className="h-5 w-5 text-purple-400" />;
    case "txt":
      return <FileText className="h-5 w-5 text-muted-foreground" />;
    default:
      return <File className="h-5 w-5 text-muted-foreground" />;
  }
}

function getStatusBadge(status: string, error: string | null) {
  switch (status) {
    case "indexed":
      return (
        <Badge
          variant="outline"
          className="gap-1 border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
        >
          <CheckCircle2 className="h-3 w-3" />
          Indexed
        </Badge>
      );
    case "indexing":
      return (
        <Badge
          variant="outline"
          className="gap-1 border-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-400"
        >
          <Loader2 className="h-3 w-3 animate-spin" />
          Indexing
        </Badge>
      );
    case "pending":
      return (
        <Badge
          variant="outline"
          className="gap-1 border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400"
        >
          <Clock className="h-3 w-3" />
          Pending
        </Badge>
      );
    case "failed":
      return (
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Badge
                variant="outline"
                className="gap-1 border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400 cursor-help"
              >
                <AlertCircle className="h-3 w-3" />
                Failed
              </Badge>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs">
              <p className="text-xs">{error || "Unknown error"}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      );
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

/* ── Main Component ────────────────────────────────────────────────────── */

export function KnowledgeDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [documents, setDocuments] = useState<RagDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /* ── Data fetching ──────────────────────────────────────────────────── */

  const fetchDocuments = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch("/api/rag/documents");
      if (res.ok) {
        const data = await res.json();
        setDocuments(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      console.error("Failed to fetch knowledge base documents", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchQueueStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/rag/status");
      if (res.ok) {
        setQueueStatus(await res.json());
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (open) {
      fetchDocuments();
      fetchQueueStatus();
    }
  }, [open, fetchDocuments, fetchQueueStatus]);

  // Poll for pending/indexing documents
  useEffect(() => {
    if (!open) return;
    const hasPending = documents.some(
      (d) => d.status === "pending" || d.status === "indexing"
    );
    if (!hasPending) return;

    const timer = setInterval(() => {
      fetchDocuments();
      fetchQueueStatus();
    }, 3000);
    return () => clearInterval(timer);
  }, [open, documents, fetchDocuments, fetchQueueStatus]);

  /* ── Upload handling ────────────────────────────────────────────────── */

  const uploadFiles = async (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    setUploading(true);
    setUploadProgress(0);

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    try {
      // Simulate progress for UX
      const progressInterval = setInterval(() => {
        setUploadProgress((prev) => Math.min(prev + 8, 90));
      }, 200);

      const res = await fetch("/api/rag/upload", {
        method: "POST",
        body: formData,
      });

      clearInterval(progressInterval);
      setUploadProgress(100);

      if (res.ok) {
        const data = await res.json();
        const count = data.documents?.length || 0;
        const errCount = data.errors?.length || 0;

        if (count > 0) {
          toast.success(
            `${count} document${count > 1 ? "s" : ""} uploaded successfully`,
            {
              description: "Indexing will begin shortly.",
            }
          );
        }
        if (errCount > 0) {
          toast.error(`${errCount} file${errCount > 1 ? "s" : ""} failed to upload`);
        }

        // Refresh the list
        setTimeout(fetchDocuments, 800);
      } else {
        const text = await res.text();
        console.error("Upload failed:", text);
        toast.error("Upload failed", { description: "Check the console for details." });
      }
    } catch (err) {
      console.error("Upload error:", err);
      toast.error("Upload failed", { description: "Network error or server unreachable." });
    } finally {
      setTimeout(() => {
        setUploading(false);
        setUploadProgress(0);
      }, 600);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      await uploadFiles(e.target.files);
    }
  };

  /* ── Drag & Drop ────────────────────────────────────────────────────── */

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await uploadFiles(e.dataTransfer.files);
    }
  };

  /* ── Delete ─────────────────────────────────────────────────────────── */

  const handleDelete = async (docId: string, filename: string) => {
    setDeletingId(docId);
    try {
      const res = await fetch(`/api/rag/documents/${docId}`, { method: "DELETE" });
      if (res.ok) {
        setDocuments((docs) => docs.filter((d) => d.id !== docId));
        toast.success(`Removed "${filename}" from knowledge base`);
      } else {
        toast.error("Failed to delete document");
      }
    } catch (e) {
      console.error("Failed to delete document", e);
      toast.error("Failed to delete document");
    } finally {
      setDeletingId(null);
    }
  };

  /* ── Filtered + Stats ───────────────────────────────────────────────── */

  const filtered = searchQuery
    ? documents.filter((d) =>
        d.filename.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : documents;

  const stats = {
    total: documents.length,
    indexed: documents.filter((d) => d.status === "indexed").length,
    pending: documents.filter(
      (d) => d.status === "pending" || d.status === "indexing"
    ).length,
    failed: documents.filter((d) => d.status === "failed").length,
    totalChunks: documents.reduce((acc, d) => acc + (d.chunk_count || 0), 0),
    totalSize: documents.reduce((acc, d) => acc + (d.file_size || 0), 0),
  };

  /* ── Render ─────────────────────────────────────────────────────────── */

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-3xl p-0 gap-0 overflow-hidden"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {/* Drag overlay */}
        {dragOver && (
          <div className="absolute inset-0 z-50 flex items-center justify-center bg-primary/5 backdrop-blur-sm border-2 border-dashed border-primary rounded-lg">
            <div className="flex flex-col items-center gap-3 text-primary">
              <UploadCloud className="h-12 w-12 animate-bounce" />
              <p className="text-lg font-medium">Drop files to add to Knowledge Base</p>
              <p className="text-sm text-muted-foreground">
                PDF, DOCX, XLSX, PPTX, TXT, MD
              </p>
            </div>
          </div>
        )}

        {/* Upload progress bar */}
        {uploading && (
          <div className="absolute top-0 left-0 right-0 z-40">
            <Progress value={uploadProgress} className="h-1 rounded-none" />
          </div>
        )}

        {/* ── Header ───────────────────────────────────────────────────── */}
        <DialogHeader className="px-6 pt-6 pb-4 border-b border-border/50">
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <DialogTitle className="flex items-center gap-2.5 text-xl font-semibold tracking-tight">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                  <BookOpen className="h-4.5 w-4.5 text-primary" />
                </div>
                Knowledge Base
              </DialogTitle>
              <p className="text-sm text-muted-foreground">
                Upload documents for RAG-powered retrieval. SAGE searches these
                when answering your questions.
              </p>
              <DialogDescription className="sr-only">
                Manage documents in the SAGE knowledge base for retrieval-augmented generation.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* ── Stats Bar ────────────────────────────────────────────────── */}
        {documents.length > 0 && (
          <div className="px-6 py-3 border-b border-border/50 bg-muted/30">
            <div className="flex items-center gap-5 text-xs text-muted-foreground">
              <TooltipProvider delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center gap-1.5 cursor-default">
                      <Database className="h-3.5 w-3.5" />
                      <span className="font-medium text-foreground">{stats.total}</span>{" "}
                      document{stats.total !== 1 ? "s" : ""}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>Total documents in knowledge base</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center gap-1.5 cursor-default">
                      <Layers className="h-3.5 w-3.5" />
                      <span className="font-medium text-foreground">
                        {stats.totalChunks.toLocaleString()}
                      </span>{" "}
                      chunks
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>Total indexed text chunks</TooltipContent>
                </Tooltip>

                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center gap-1.5 cursor-default">
                      <HardDrive className="h-3.5 w-3.5" />
                      {formatBytes(stats.totalSize)}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>Total file size</TooltipContent>
                </Tooltip>
              </TooltipProvider>

              {stats.pending > 0 && (
                <div className="flex items-center gap-1.5 text-amber-600 dark:text-amber-400">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {stats.pending} processing
                </div>
              )}
              {stats.failed > 0 && (
                <div className="flex items-center gap-1.5 text-red-500">
                  <AlertTriangle className="h-3 w-3" />
                  {stats.failed} failed
                </div>
              )}

              {queueStatus?.status === "running" && (
                <div className="ml-auto flex items-center gap-1.5">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="text-emerald-600 dark:text-emerald-400">
                    Indexer active
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Toolbar ──────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 px-6 py-3 border-b border-border/50">
          <Button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            size="sm"
            className="gap-2 rounded-lg shadow-sm"
          >
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <UploadCloud className="h-4 w-4" />
            )}
            {uploading ? "Uploading…" : "Upload Documents"}
          </Button>

          <div className="flex-1 relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter documents…"
              className="w-full rounded-lg border border-border bg-background pl-8 pr-8 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring transition-shadow"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => {
                    fetchDocuments();
                    fetchQueueStatus();
                  }}
                  disabled={loading}
                  className="h-8 w-8 rounded-lg"
                >
                  <RefreshCw
                    className={`h-4 w-4 ${loading ? "animate-spin" : ""}`}
                  />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Refresh</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <input
            type="file"
            multiple
            ref={fileInputRef}
            className="hidden"
            onChange={handleFileChange}
            accept=".txt,.md,.pdf,.docx,.xlsx,.pptx"
          />
        </div>

        {/* ── Document List ────────────────────────────────────────────── */}
        <div className="max-h-[50vh] min-h-[200px] overflow-y-auto">
          {loading && documents.length === 0 ? (
            /* Loading skeleton */
            <div className="space-y-1 p-4">
              {[...Array(3)].map((_, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 rounded-lg p-3 animate-pulse"
                >
                  <div className="h-9 w-9 rounded-lg bg-muted" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3.5 w-40 rounded bg-muted" />
                    <div className="h-3 w-24 rounded bg-muted" />
                  </div>
                  <div className="h-6 w-16 rounded-md bg-muted" />
                </div>
              ))}
            </div>
          ) : filtered.length === 0 ? (
            /* Empty state */
            <div className="flex flex-col items-center justify-center py-16 px-8">
              {documents.length === 0 ? (
                <>
                  <div className="relative mb-4">
                    <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/60">
                      <UploadCloud className="h-8 w-8 text-muted-foreground" />
                    </div>
                    <div className="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      <span className="text-xs font-bold">+</span>
                    </div>
                  </div>
                  <p className="text-sm font-medium mb-1">No documents yet</p>
                  <p className="text-xs text-muted-foreground text-center max-w-xs mb-4">
                    Upload PDF, DOCX, XLSX, PPTX, TXT, or Markdown files.
                    SAGE will chunk and embed them for intelligent retrieval.
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <UploadCloud className="h-4 w-4" />
                    Upload your first document
                  </Button>
                </>
              ) : (
                <>
                  <Search className="h-8 w-8 text-muted-foreground mb-2" />
                  <p className="text-sm text-muted-foreground">
                    No documents match "{searchQuery}"
                  </p>
                </>
              )}
            </div>
          ) : (
            /* Document cards */
            <div className="space-y-0.5 p-2">
              {filtered.map((doc) => (
                <div
                  key={doc.id}
                  className="group flex items-center gap-3 rounded-xl px-4 py-3 transition-all duration-150 hover:bg-muted/50"
                >
                  {/* File icon */}
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted/60 transition-colors group-hover:bg-muted">
                    {getFileIcon(doc.file_type)}
                  </div>

                  {/* File info */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p
                        className="truncate text-sm font-medium"
                        title={doc.filename}
                      >
                        {doc.filename}
                      </p>
                    </div>
                    <div className="mt-0.5 flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{formatBytes(doc.file_size)}</span>
                      <span className="text-border">·</span>
                      <span>{doc.file_type.toUpperCase()}</span>
                      {doc.chunk_count > 0 && (
                        <>
                          <span className="text-border">·</span>
                          <span>{doc.chunk_count} chunks</span>
                        </>
                      )}
                      <span className="text-border">·</span>
                      <span>{formatDate(doc.created_at)}</span>
                    </div>
                  </div>

                  {/* Status badge */}
                  <div className="shrink-0">
                    {getStatusBadge(doc.status, doc.error)}
                  </div>

                  {/* Delete button */}
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 shrink-0 rounded-lg opacity-0 transition-all group-hover:opacity-100 text-muted-foreground hover:text-red-500 hover:bg-red-500/10"
                          onClick={() => handleDelete(doc.id, doc.filename)}
                          disabled={deletingId === doc.id}
                        >
                          {deletingId === doc.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Remove from knowledge base</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── Footer ───────────────────────────────────────────────────── */}
        <div className="px-6 py-3 border-t border-border/50 bg-muted/20">
          <p className="text-xs text-muted-foreground text-center">
            Drag & drop files anywhere on this dialog to upload •
            Supported: PDF, DOCX, XLSX, PPTX, TXT, MD
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
