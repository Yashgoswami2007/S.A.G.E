import { useState, useEffect, useCallback, useRef } from "react";
import {
  FolderOpen, X, RefreshCw, Folder, Trash2, CheckCircle2, AlertCircle,
  ChevronRight, ChevronDown, FileText, FileCode, FileImage, FileSpreadsheet,
  File as FileIcon, ArrowLeft, Settings2, FolderTree, BookOpen
} from "lucide-react";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "@/hooks/useWorkspace";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────
interface FileEntry {
  name: string;
  type: "file" | "dir";
  size: number | null;
  modified: number | null;
}

interface TreeNode extends FileEntry {
  path: string;
  children?: TreeNode[];
  loaded?: boolean;
  expanded?: boolean;
}

interface FileContent {
  type: "text" | "markdown" | "image" | "pdf" | "docx" | "spreadsheet" | "binary";
  content?: string;
  html?: string | null;
  mime?: string;
  name: string;
  size: number;
  reason?: string;
  truncated?: boolean;
}

interface WorkspaceSidebarProps {
  open: boolean;
  onToggle: () => void;
}

// ── Constants ────────────────────────────────────────────────────────────
const MIN_WIDTH = 280;
const MAX_WIDTH_VW = 50; // as percent of viewport
const DEFAULT_WIDTH = 340;

// Map file extensions to icons
function fileIcon(name: string) {
  const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
  const codeExts = new Set([".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml", ".html", ".css", ".go", ".rs", ".java", ".c", ".cpp", ".rb", ".sh", ".bat", ".sql", ".vue", ".svelte"]);
  const imageExts = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"]);
  const spreadsheetExts = new Set([".csv", ".xlsx", ".xls"]);

  if (codeExts.has(ext)) return <FileCode className="h-4 w-4 shrink-0 text-blue-400" />;
  if (imageExts.has(ext)) return <FileImage className="h-4 w-4 shrink-0 text-emerald-400" />;
  if (spreadsheetExts.has(ext)) return <FileSpreadsheet className="h-4 w-4 shrink-0 text-green-400" />;
  if (ext === ".md" || ext === ".txt") return <FileText className="h-4 w-4 shrink-0 text-yellow-400" />;
  if (ext === ".pdf") return <FileText className="h-4 w-4 shrink-0 text-red-400" />;
  if (ext === ".docx") return <FileText className="h-4 w-4 shrink-0 text-blue-500" />;
  return <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />;
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── File Tree Item ───────────────────────────────────────────────────────
function TreeItem({
  node,
  depth,
  onToggleDir,
  onClickFile,
  isIndexed,
  onAddToKnowledgeBase,
  onRemoveFromKnowledgeBase,
}: {
  node: TreeNode;
  depth: number;
  onToggleDir: (node: TreeNode) => void;
  onClickFile: (node: TreeNode) => void;
  isIndexed?: boolean;
  onAddToKnowledgeBase?: (path: string) => void;
  onRemoveFromKnowledgeBase?: (path: string) => void;
}) {
  const isDir = node.type === "dir";

  const isIndexable = !isDir && [".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"].some(ext => node.name.toLowerCase().endsWith(ext));

  const InnerNode = (
    <div className={cn("flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-sm transition-colors", "hover:bg-sidebar-accent/70 active:bg-sidebar-accent", "group cursor-pointer")} style={{ paddingLeft: `${depth * 16 + 8}px` }} onClick={() => (isDir ? onToggleDir(node) : onClickFile(node))}>
        {isDir ? (
          <>
            {node.expanded ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )}
            <Folder className="h-4 w-4 shrink-0 text-amber-400" />
          </>
        ) : (
          <>
            <span className="w-3.5 shrink-0" />
            {fileIcon(node.name)}
          </>
        )}
        <span className="truncate flex-1">{node.name}</span>
        {!isDir && isIndexed && (
          <span title="In Knowledge Base"><BookOpen className="h-3 w-3 shrink-0 text-blue-500 mr-1" /></span>
        )}
        {!isDir && node.size != null && (
          <span className="text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity tabular-nums shrink-0">
            {formatBytes(node.size)}
          </span>
        )}
    </div>
  );

  return (
    <div>
      {isIndexable ? (
        <ContextMenu>
          <ContextMenuTrigger asChild>
            {InnerNode}
          </ContextMenuTrigger>
          <ContextMenuContent>
            {isIndexed ? (
              <ContextMenuItem onClick={() => onRemoveFromKnowledgeBase?.(node.path)}>
                Remove from Knowledge Base
              </ContextMenuItem>
            ) : (
              <ContextMenuItem onClick={() => onAddToKnowledgeBase?.(node.path)}>
                Add to Knowledge Base
              </ContextMenuItem>
            )}
          </ContextMenuContent>
        </ContextMenu>
      ) : (
        InnerNode
      )}

      {/* Children */}
      {isDir && node.expanded && (
        <div>
          {node.loaded === false ? (
            <div style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }} className="py-1">
              <RefreshCw className="h-3 w-3 animate-spin text-muted-foreground" />
            </div>
          ) : (
            node.children?.map((child) => (
              <TreeItem
                key={child.path}
                node={child}
                depth={depth + 1}
                onToggleDir={onToggleDir}
                onClickFile={onClickFile}
                {...(isIndexed != null ? { isIndexed } : {})}
                {...(onAddToKnowledgeBase ? { onAddToKnowledgeBase } : {})}
                {...(onRemoveFromKnowledgeBase ? { onRemoveFromKnowledgeBase } : {})}
              />
            ))
          )}
          {node.loaded && (!node.children || node.children.length === 0) && (
            <div
              style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
              className="py-1 text-xs text-muted-foreground italic"
            >
              Empty folder
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── File Viewer ──────────────────────────────────────────────────────────
function FileViewer({ file, onBack }: { file: FileContent | null; loading: boolean; onBack: () => void }) {
  if (!file) {
    return (
      <div className="flex flex-1 items-center justify-center p-4">
        <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-sidebar-border px-3 py-2 shrink-0">
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex flex-col min-w-0">
          <span className="text-sm font-medium truncate">{file.name}</span>
          <span className="text-[10px] text-muted-foreground">{formatBytes(file.size)}</span>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-3">
        {file.type === "text" && (
          <pre className="whitespace-pre-wrap break-words text-xs font-mono leading-relaxed text-sidebar-foreground bg-sidebar-accent/30 rounded-lg p-3 border border-sidebar-border">
            {file.content}
          </pre>
        )}

        {file.type === "markdown" && (
          file.html ? (
            <div
              className="sage-prose text-sm"
              dangerouslySetInnerHTML={{ __html: file.html }}
            />
          ) : (
            <pre className="whitespace-pre-wrap break-words text-xs font-mono leading-relaxed text-sidebar-foreground bg-sidebar-accent/30 rounded-lg p-3 border border-sidebar-border">
              {file.content}
            </pre>
          )
        )}

        {file.type === "image" && (
          <div className="flex justify-center">
            <img
              src={`data:${file.mime || "image/png"};base64,${file.content}`}
              alt={file.name}
              className="max-w-full rounded-lg border border-sidebar-border shadow-sm"
            />
          </div>
        )}

        {file.type === "pdf" && (
          <iframe
            src={`data:application/pdf;base64,${file.content}`}
            title={file.name}
            className="w-full rounded-lg border border-sidebar-border"
            style={{ height: "calc(100vh - 160px)", minHeight: "400px" }}
          />
        )}

        {file.type === "docx" && (
          <div
            className="sage-prose text-sm bg-white dark:bg-sidebar-accent/30 rounded-lg p-4 border border-sidebar-border"
            dangerouslySetInnerHTML={{ __html: file.content || "" }}
          />
        )}

        {file.type === "spreadsheet" && (
          <div
            className="text-xs overflow-auto [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:border-sidebar-border [&_th]:bg-sidebar-accent [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_td]:border [&_td]:border-sidebar-border [&_td]:px-2 [&_td]:py-1 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4"
            dangerouslySetInnerHTML={{ __html: file.content || "" }}
          />
        )}

        {file.type === "binary" && (
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-muted-foreground">
            <FileIcon className="h-12 w-12 opacity-30" />
            <p className="text-sm font-medium">Preview not available</p>
            <p className="text-xs text-center max-w-[200px]">
              {file.reason || "This file type cannot be previewed inline."}
            </p>
            <p className="text-xs">{formatBytes(file.size)}</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────
export function WorkspaceSidebar({ open, onToggle }: WorkspaceSidebarProps) {
  const {
    workspaceInfo,
    isLoading,
    recentWorkspaces,
    validatePath,
    validationResult,
    isValidating,
    setWorkspace,
    resetWorkspace,
    removeRecent,
    openInExplorer,
    copyPath,
  } = useWorkspace();

  const [inputPath, setInputPath] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  // File tree state
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);

  // File viewer state
  const [viewingFile, setViewingFile] = useState<string | null>(null); // relative path
  const [fileContent, setFileContent] = useState<FileContent | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [indexedFiles, setIndexedFiles] = useState<Set<string>>(new Set());

  // Resize state
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const resizing = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(DEFAULT_WIDTH);

  // Update input when workspaceInfo loads
  useEffect(() => {
    if (workspaceInfo && !inputPath) {
      setInputPath(workspaceInfo.active_workspace);
    }
  }, [workspaceInfo]);

  // Load root tree when sidebar opens or workspace changes
  const workspacePath = workspaceInfo?.active_workspace;
  useEffect(() => {
    if (open && workspacePath) {
      loadDirectory("", null);
      // Reset file viewer when workspace changes
      setViewingFile(null);
      setFileContent(null);
    }
  }, [open, workspacePath]);

  // ── Directory loading ──
  const loadDirectory = useCallback(async (dirPath: string, parentPath: string | null) => {
    if (parentPath === null) setTreeLoading(true);
    try {
      const res = await fetch(`/api/workspace/files?path=${encodeURIComponent(dirPath)}`);
      if (!res.ok) return;
      const entries: FileEntry[] = await res.json();
      const nodes: TreeNode[] = entries.map((e): TreeNode => {
        const base = {
          ...e,
          path: dirPath ? `${dirPath}/${e.name}` : e.name,
          expanded: false,
        };
        if (e.type === "dir") {
          return { ...base, children: [], loaded: false };
        }
        return base;
      });

      if (parentPath === null) {
        // Root level
        const sorted = nodes.sort((a: any, b: any) => {
          if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
          return a.name.localeCompare(b.name);
        });
        
        fetch("/api/rag/documents").then(res => {
          if (res.ok) {
            res.json().then(docs => {
              const paths = new Set<string>();
              docs.forEach((d: any) => paths.add(d.file_path));
              setIndexedFiles(paths);
            });
          }
        }).catch(() => {});

        setTree(sorted);
      } else {
        // Update nested node
        setTree((prev) => updateNode(prev, parentPath, (n) => ({
          ...n,
          children: nodes,
          loaded: true,
          expanded: true,
        })));
      }
    } catch (err) {
      console.error("Failed to load directory:", err);
    } finally {
      if (parentPath === null) setTreeLoading(false);
    }
  }, []);

  // ── Recursive tree update helper ──
  function updateNode(nodes: TreeNode[], targetPath: string, updater: (n: TreeNode) => TreeNode): TreeNode[] {
    return nodes.map((n) => {
      if (n.path === targetPath) return updater(n);
      if (n.children) return { ...n, children: updateNode(n.children, targetPath, updater) };
      return n;
    });
  }

  const handleToggleDir = useCallback((node: TreeNode) => {
    if (node.expanded) {
      // Collapse
      setTree((prev) => updateNode(prev, node.path, (n) => ({ ...n, expanded: false })));
    } else if (node.loaded) {
      // Already loaded, just expand
      setTree((prev) => updateNode(prev, node.path, (n) => ({ ...n, expanded: true })));
    } else {
      // Mark as expanding, then load
      setTree((prev) => updateNode(prev, node.path, (n) => ({ ...n, expanded: true, loaded: false })));
      loadDirectory(node.path, node.path);
    }
  }, [loadDirectory]);

  const handleClickFile = useCallback(async (node: TreeNode) => {
    setViewingFile(node.path);
    setFileContent(null);
    setFileLoading(true);
    try {
      const res = await fetch(`/api/workspace/files/read?path=${encodeURIComponent(node.path)}`);
      if (!res.ok) {
        setFileContent({ type: "binary", name: node.name, size: node.size || 0, reason: "Failed to load file." });
        return;
      }
      const data: FileContent = await res.json();
      setFileContent(data);
    } catch (err) {
      console.error("Failed to read file:", err);
      setFileContent({ type: "binary", name: node.name, size: node.size || 0, reason: "Network error." });
    } finally {
      setFileLoading(false);
    }
  }, []);

  const handleBack = () => {
    setViewingFile(null);
    setFileContent(null);
  };

  // ── Resize logic ──
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    resizing.current = true;
    startX.current = e.clientX;
    startWidth.current = width;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: MouseEvent) => {
      if (!resizing.current) return;
      const delta = startX.current - ev.clientX; // dragging left = wider
      const maxW = window.innerWidth * (MAX_WIDTH_VW / 100);
      const newW = Math.min(maxW, Math.max(MIN_WIDTH, startWidth.current + delta));
      setWidth(newW);
    };

    const onUp = () => {
      resizing.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [width]);

  const handleAddToKnowledgeBase = async (path: string) => {
    try {
      const absPath = workspaceInfo?.active_workspace ? `${workspaceInfo.active_workspace}\\${path}`.replace(/\\\\/g, '\\').replace(/\//g, '\\') : path;
      const res = await fetch("/api/rag/index", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: absPath })
      });
      if (res.ok) {
        setIndexedFiles(prev => new Set(prev).add(absPath));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleRemoveFromKnowledgeBase = async (path: string) => {
    try {
      const absPath = workspaceInfo?.active_workspace ? `${workspaceInfo.active_workspace}\\${path}`.replace(/\\\\/g, '\\').replace(/\//g, '\\') : path;
      const resDocs = await fetch("/api/rag/documents");
      if (resDocs.ok) {
        const docs = await resDocs.json();
        const doc = docs.find((d: any) => d.file_path === absPath || d.filename === path.split(/[/\\]/).pop());
        if (doc) {
          await fetch(`/api/rag/documents/${doc.id}`, { method: "DELETE" });
          setIndexedFiles(prev => {
            const next = new Set(prev);
            next.delete(absPath);
            return next;
          });
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  // ── Workspace management handlers ──
  const handleValidate = async () => {
    if (!inputPath.trim()) return;
    await validatePath(inputPath);
  };

  const handleApply = async () => {
    if (validationResult?.valid) {
      await setWorkspace(validationResult.path);
    }
  };

  const handleReset = async () => {
    await resetWorkspace();
    setInputPath("");
  };

  const handleRefresh = () => {
    loadDirectory("", null);
  };

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close workspace sidebar"
          className="fixed inset-0 z-30 bg-foreground/20 md:hidden"
          onClick={onToggle}
        />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 right-0 z-40 flex flex-col border-l border-sidebar-border bg-sidebar transition-transform duration-200 md:static md:translate-x-0",
          open ? "translate-x-0" : "translate-x-full",
          open ? "" : "md:w-0 md:overflow-hidden md:border-l-0"
        )}
        style={{ width: open ? `${width}px` : undefined }}
      >
        {/* Resize handle (left edge) */}
        {open && (
          <div
            className="absolute inset-y-0 left-0 w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-50"
            onMouseDown={handleResizeStart}
          />
        )}

        {/* Header */}
        <div className="flex h-12 items-center justify-between border-b border-sidebar-border px-3 shrink-0">
          <div className="flex items-center gap-2 font-semibold text-sm">
            <FolderOpen className="h-4 w-4" />
            Workspace
          </div>
          <div className="flex items-center gap-0.5">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={handleRefresh}
              title="Refresh file tree"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className={cn("h-7 w-7", showSettings && "bg-sidebar-accent")}
              onClick={() => setShowSettings((v) => !v)}
              title="Workspace settings"
            >
              <Settings2 className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onToggle}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Workspace path bar */}
        <div className="flex items-center gap-2 border-b border-sidebar-border px-3 py-1.5 shrink-0">
          <FolderTree className="h-3 w-3 text-muted-foreground shrink-0" />
          <span className="truncate text-[11px] font-mono text-muted-foreground flex-1">
            {workspaceInfo?.active_workspace || "Loading..."}
          </span>
          <div className="flex items-center gap-0.5 shrink-0">
            <Button variant="ghost" size="sm" className="h-5 text-[10px] px-1.5" onClick={openInExplorer}>
              Open
            </Button>
            <Button variant="ghost" size="sm" className="h-5 text-[10px] px-1.5" onClick={copyPath}>
              Copy
            </Button>
          </div>
        </div>

        {/* Collapsible settings panel */}
        {showSettings && (
          <div className="border-b border-sidebar-border p-3 space-y-3 shrink-0 bg-sidebar-accent/20">
            {isLoading ? (
              <div className="flex justify-center p-2"><RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" /></div>
            ) : (
              <>
                {/* Change Workspace */}
                <div className="space-y-2">
                  <h3 className="text-xs font-medium text-sidebar-foreground">Change Workspace</h3>
                  <input
                    type="text"
                    value={inputPath}
                    onChange={(e) => setInputPath(e.target.value)}
                    className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 py-1 text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    placeholder="Enter absolute path..."
                    onKeyDown={(e) => e.key === "Enter" && handleValidate()}
                  />
                  <div className="flex gap-1.5">
                    <Button className="flex-1 h-7 text-xs" variant="outline" onClick={handleValidate} disabled={isValidating || !inputPath}>
                      {isValidating ? <RefreshCw className="h-3 w-3 animate-spin mr-1" /> : null}
                      Validate
                    </Button>
                    <Button className="flex-1 h-7 text-xs" onClick={handleApply} disabled={!validationResult?.valid || validationResult?.path !== inputPath}>
                      Apply
                    </Button>
                  </div>

                  {validationResult && (
                    <div className={cn("text-[11px] p-1.5 rounded-md flex items-start gap-1.5",
                      validationResult.valid ? "bg-green-500/10 text-green-600 dark:text-green-400" : "bg-destructive/10 text-destructive"
                    )}>
                      {validationResult.valid ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> : <AlertCircle className="h-3.5 w-3.5 shrink-0" />}
                      <span>{validationResult.valid ? "Valid workspace directory." : validationResult.reason}</span>
                    </div>
                  )}

                  {workspaceInfo?.mode === "custom" && (
                    <Button variant="ghost" size="sm" className="w-full text-xs text-muted-foreground" onClick={handleReset}>
                      Reset to Default Workspace
                    </Button>
                  )}
                </div>

                {/* Recent Workspaces */}
                {recentWorkspaces.length > 0 && (
                  <div className="space-y-1.5 pt-1.5 border-t border-sidebar-border">
                    <h3 className="text-xs font-medium text-sidebar-foreground">Recent</h3>
                    <div className="space-y-0.5">
                      {recentWorkspaces.map((path) => (
                        <div key={path} className="group flex items-center justify-between rounded-md px-1.5 py-1 hover:bg-sidebar-accent cursor-pointer" onClick={() => {
                          setInputPath(path);
                          validatePath(path);
                        }}>
                          <div className="flex items-center gap-1.5 overflow-hidden text-muted-foreground">
                            <Folder className="h-3 w-3 shrink-0" />
                            <span className="truncate text-[11px]">{path}</span>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 opacity-0 group-hover:opacity-100 shrink-0"
                            onClick={(e) => {
                              e.stopPropagation();
                              removeRecent(path);
                            }}
                          >
                            <Trash2 className="h-3 w-3 text-muted-foreground" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Main content area */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {viewingFile ? (
            <FileViewer file={fileContent} loading={fileLoading} onBack={handleBack} />
          ) : (
            /* File Tree */
            <div className="flex-1 overflow-y-auto py-1">
              {treeLoading ? (
                <div className="flex justify-center p-6">
                  <RefreshCw className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : tree.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted-foreground">
                  <Folder className="h-8 w-8 opacity-30" />
                  <p className="text-xs">Workspace is empty</p>
                </div>
              ) : (
                tree.map((node) => (
                  <TreeItem
                    key={node.path}
                    node={node}
                    depth={0}
                    onToggleDir={handleToggleDir}
                    onClickFile={handleClickFile}
                    isIndexed={
                      Array.from(indexedFiles).some(p => p.endsWith(node.path) || p.endsWith(node.name))
                    }
                    onAddToKnowledgeBase={handleAddToKnowledgeBase}
                    onRemoveFromKnowledgeBase={handleRemoveFromKnowledgeBase}
                  />
                ))
              )}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
