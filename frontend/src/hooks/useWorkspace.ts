import { useState, useCallback, useEffect } from "react";
import { toast } from "sonner";

export interface WorkspaceInfo {
  default_workspace: string;
  active_workspace: string;
  workspace_id: string;
  mode: "default" | "custom";
  exists: boolean;
  readable: boolean;
  writable: boolean;
  free_space_bytes: number | null;
}

export interface WorkspaceValidation {
  valid: boolean;
  path: string;
  exists: boolean;
  is_directory: boolean;
  readable: boolean;
  writable: boolean;
  free_space_bytes: number | null;
  reason: string | null;
}

export function useWorkspace() {
  const [workspaceInfo, setWorkspaceInfo] = useState<WorkspaceInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [recentWorkspaces, setRecentWorkspaces] = useState<string[]>([]);
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<WorkspaceValidation | null>(null);

  const fetchWorkspace = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const res = await fetch("/api/workspace");
      if (!res.ok) {
        const text = await res.text();
        setError(text || "Failed to load workspace");
        return;
      }
      const data = await res.json();
      setWorkspaceInfo(data);
    } catch (err: any) {
      setError(err.message || "Failed to connect");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchRecent = useCallback(async () => {
    try {
      const res = await fetch("/api/workspace/recent");
      if (res.ok) {
        const data = await res.json();
        setRecentWorkspaces(data);
      }
    } catch (err) {
      console.error("Failed to load recent workspaces", err);
    }
  }, []);

  useEffect(() => {
    fetchWorkspace();
    fetchRecent();
  }, [fetchWorkspace, fetchRecent]);

  const validatePath = async (path: string) => {
    setIsValidating(true);
    try {
      const res = await fetch("/api/workspace/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const data = await res.json();
      if (!res.ok) {
        setValidationResult({
            valid: false,
            path: path,
            exists: false,
            is_directory: false,
            readable: false,
            writable: false,
            free_space_bytes: null,
            reason: data.detail || data.error?.message || "Validation failed"
        });
        return;
      }
      setValidationResult(data);
      return data;
    } catch (err: any) {
      setValidationResult(null);
      toast.error(err.message || "Failed to validate path");
    } finally {
      setIsValidating(false);
    }
  };

  const setWorkspace = async (path: string) => {
    try {
      const res = await fetch("/api/workspace/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || data.error?.message || "Failed to set workspace");
        return null;
      }
      setWorkspaceInfo(data);
      fetchRecent();
      toast.success("Workspace updated successfully");
      return data;
    } catch (err: any) {
      toast.error(err.message || "Failed to set workspace");
      return null;
    }
  };

  const resetWorkspace = async () => {
    try {
      const res = await fetch("/api/workspace/reset", {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) {
        toast.error(data.detail || data.error?.message || "Failed to reset workspace");
        return null;
      }
      setWorkspaceInfo(data);
      fetchRecent();
      toast.success("Workspace reset to default");
      return data;
    } catch (err: any) {
      toast.error(err.message || "Failed to reset workspace");
      return null;
    }
  };

  const removeRecent = async (path: string) => {
    try {
      const res = await fetch("/api/workspace/recent", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (res.ok) {
        setRecentWorkspaces(prev => prev.filter(p => p !== path));
      }
    } catch (err) {
      console.error("Failed to remove recent workspace", err);
    }
  };

  const openInExplorer = async () => {
    try {
      await fetch("/api/workspace/open-folder", { method: "POST" });
    } catch (err) {
      console.error("Failed to open folder", err);
      toast.error("Failed to open folder");
    }
  };

  const copyPath = () => {
    if (workspaceInfo) {
      navigator.clipboard.writeText(workspaceInfo.active_workspace);
      toast.success("Path copied to clipboard");
    }
  };

  return {
    workspaceInfo,
    isLoading,
    error,
    validationResult,
    isValidating,
    recentWorkspaces,
    fetchWorkspace,
    validatePath,
    setWorkspace,
    resetWorkspace,
    refreshWorkspace: fetchWorkspace,
    removeRecent,
    copyPath,
    openInExplorer,
  };
}
