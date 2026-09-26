import { useCallback, useEffect, useMemo, useState } from "react";
import {
  X,
  Settings,
  RotateCcw,
  Save,
  Loader2,
  AlertTriangle,
  ChevronRight,
  Undo2,
  Shield,
  Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";

// ── Types ──────────────────────────────────────────────────────────────────

type SettingSchema = {
  key: string;
  label: string;
  description: string;
  type: string;
  control: string;
  value: any;
  default: any;
  options: string[] | null;
  runtime: boolean;
  persist: boolean;
  restart_required: boolean;
  security_sensitive: boolean;
  requires_confirmation: boolean;
  min: number | null;
  max: number | null;
};

type Section = {
  id: string;
  label: string;
  security_sensitive: boolean;
  settings: SettingSchema[];
};

type SettingsResponse = {
  sections: Section[];
};

type SaveResult = {
  applied: string[];
  persisted: string[];
  restart_required: string[];
  errors: Record<string, string>;
  security_confirmations: string[];
  settings: SettingsResponse;
  _status?: string;
};

// ── Section Icons ──────────────────────────────────────────────────────────

const SECTION_ICONS: Record<string, string> = {
  general: "⚙",
  gpu: "🖥",
  ocr: "📄",
  tool_factory: "🔧",
  tool_factory_timeouts: "⏱",
  tool_security: "🛡",
  server: "🌐",
  rag: "📚",
};

// ── Component ──────────────────────────────────────────────────────────────

export function SettingsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [sections, setSections] = useState<Section[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [activeSection, setActiveSection] = useState<string>("");
  const [localChanges, setLocalChanges] = useState<Record<string, any>>({});
  const [saveResult, setSaveResult] = useState<SaveResult | null>(null);

  // Security confirmation dialog state
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    key: string;
    label: string;
    description: string;
    value: any;
  }>({ open: false, key: "", label: "", description: "", value: null });

  // Reset all confirmation
  const [resetAllDialog, setResetAllDialog] = useState(false);

  // ── Fetch settings ──────────────────────────────────────────────────

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings");
      if (!res.ok) {
        toast.error("Failed to load settings");
        return;
      }
      const data: SettingsResponse = await res.json();
      setSections(data.sections || []);
      if (data.sections?.length > 0 && !activeSection) {
        setActiveSection(data.sections[0]!.id);
      }
    } catch {
      toast.error("Cannot connect to settings service");
    } finally {
      setLoading(false);
    }
  }, [activeSection]);

  useEffect(() => {
    if (open) {
      fetchSettings();
      setLocalChanges({});
      setErrors({});
      setSaveResult(null);
    }
  }, [open, fetchSettings]);

  // ── Change tracking ─────────────────────────────────────────────────

  const hasChanges = useMemo(
    () => Object.keys(localChanges).length > 0,
    [localChanges]
  );

  const changeCount = Object.keys(localChanges).length;

  const getEffectiveValue = useCallback(
    (key: string, serverValue: any) => {
      return key in localChanges ? localChanges[key] : serverValue;
    },
    [localChanges]
  );

  const isModified = useCallback(
    (key: string) => key in localChanges,
    [localChanges]
  );

  // ── Setting change handler (with security confirmation) ─────────────

  const handleChange = useCallback(
    (setting: SettingSchema, newValue: any) => {
      // Check if this needs security confirmation
      if (
        setting.requires_confirmation &&
        setting.security_sensitive &&
        newValue !== setting.default
      ) {
        setConfirmDialog({
          open: true,
          key: setting.key,
          label: setting.label,
          description: setting.description,
          value: newValue,
        });
        return;
      }

      applyLocalChange(setting.key, newValue, setting.value);
    },
    []
  );

  const applyLocalChange = useCallback(
    (key: string, newValue: any, serverValue: any) => {
      setLocalChanges((prev) => {
        // If value matches server value, remove from local changes
        if (newValue === serverValue) {
          const next = { ...prev };
          delete next[key];
          return next;
        }
        return { ...prev, [key]: newValue };
      });
      // Clear any error for this key
      setErrors((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    },
    []
  );

  const confirmSecurityChange = useCallback(() => {
    const { key, value } = confirmDialog;
    // Find the server value
    const serverValue = sections
      .flatMap((s) => s.settings)
      .find((s) => s.key === key)?.value;
    applyLocalChange(key, value, serverValue);
    setConfirmDialog((d) => ({ ...d, open: false }));
  }, [confirmDialog, sections, applyLocalChange]);

  // ── Save ────────────────────────────────────────────────────────────

  const handleSave = useCallback(async () => {
    if (!hasChanges) return;
    setSaving(true);
    setSaveResult(null);
    setErrors({});

    try {
      const res = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changes: localChanges }),
      });

      const data: SaveResult = await res.json();

      if (data.errors && Object.keys(data.errors).length > 0) {
        setErrors(data.errors);
        toast.error("Some settings have invalid values");
        setSaving(false);
        return;
      }

      // Update sections from response
      if (data.settings?.sections) {
        setSections(data.settings.sections);
      }

      setLocalChanges({});
      setSaveResult(data);

      // Show result toast
      const appliedCount = data.applied?.length ?? 0;
      const restartCount = data.restart_required?.length ?? 0;

      if (restartCount > 0) {
        toast.success(
          `${appliedCount + restartCount} setting${appliedCount + restartCount !== 1 ? "s" : ""} saved. ${restartCount} require${restartCount === 1 ? "s" : ""} restart.`,
          { duration: 5000 }
        );
      } else {
        toast.success(
          `${appliedCount} setting${appliedCount !== 1 ? "s" : ""} saved and applied.`
        );
      }
    } catch {
      toast.error("Failed to save settings");
    } finally {
      setSaving(false);
    }
  }, [hasChanges, localChanges]);

  // ── Discard ─────────────────────────────────────────────────────────

  const handleDiscard = useCallback(() => {
    setLocalChanges({});
    setErrors({});
    setSaveResult(null);
  }, []);

  // ── Reset single setting ────────────────────────────────────────────

  const handleResetSetting = useCallback(
    (setting: SettingSchema) => {
      applyLocalChange(setting.key, setting.default, setting.value);
    },
    [applyLocalChange]
  );

  // ── Reset all ───────────────────────────────────────────────────────

  const handleResetAll = useCallback(async () => {
    setResetAllDialog(false);
    setSaving(true);
    try {
      const res = await fetch("/api/settings/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ all: true }),
      });
      const data = await res.json();
      if (data.settings?.sections) {
        setSections(data.settings.sections);
      }
      setLocalChanges({});
      setErrors({});
      toast.success("All settings reset to defaults");
    } catch {
      toast.error("Failed to reset settings");
    } finally {
      setSaving(false);
    }
  }, []);

  // ── Active section ──────────────────────────────────────────────────

  const currentSection = useMemo(
    () => sections.find((s) => s.id === activeSection),
    [sections, activeSection]
  );

  // ── Render ──────────────────────────────────────────────────────────

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-foreground/10 backdrop-blur-[2px]"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col border-l border-border bg-background shadow-xl transition-transform duration-200 animate-in slide-in-from-right">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2.5">
            <Settings className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold tracking-tight">Settings</h2>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1">
          {/* Section nav */}
          <nav className="w-48 shrink-0 border-r border-border bg-card/50 py-3">
            {sections.map((section) => (
              <button
                key={section.id}
                type="button"
                onClick={() => setActiveSection(section.id)}
                className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm transition-colors ${
                  activeSection === section.id
                    ? "bg-accent text-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                }`}
              >
                <span className="text-sm">
                  {SECTION_ICONS[section.id] || "•"}
                </span>
                <span className="truncate">{section.label}</span>
                {section.security_sensitive && (
                  <Shield className="ml-auto h-3 w-3 text-amber-500" />
                )}
              </button>
            ))}

            {/* Reset all button */}
            <div className="mt-4 border-t border-border px-3 pt-3">
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-start gap-2 text-muted-foreground hover:text-destructive"
                onClick={() => setResetAllDialog(true)}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset all
              </Button>
            </div>
          </nav>

          {/* Settings content */}
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : currentSection ? (
              <div>
                <h3 className="text-base font-semibold">
                  {currentSection.label}
                </h3>

                {/* Security warning banner */}
                {currentSection.security_sensitive && (
                  <div className="mt-3 flex items-start gap-2.5 rounded-lg border border-amber-300/50 bg-amber-50 px-3.5 py-3 text-sm dark:border-amber-500/30 dark:bg-amber-950/30">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                    <p className="text-amber-800 dark:text-amber-200">
                      Changing these settings may reduce SAGE's security
                      restrictions for dynamically generated tools.
                    </p>
                  </div>
                )}

                {/* Settings list */}
                <div className="mt-5 space-y-5">
                  {currentSection.settings.map((setting) => (
                    <SettingRow
                      key={setting.key}
                      setting={setting}
                      effectiveValue={getEffectiveValue(
                        setting.key,
                        setting.value
                      )}
                      modified={isModified(setting.key)}
                      error={errors[setting.key]}
                      onChange={(val) => handleChange(setting, val)}
                      onReset={() => handleResetSetting(setting)}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Select a section from the sidebar.
              </p>
            )}
          </div>
        </div>

        {/* Footer — save bar */}
        {hasChanges && (
          <div className="flex items-center justify-between border-t border-border bg-card/80 px-5 py-3">
            <p className="text-sm text-muted-foreground">
              {changeCount} unsaved change{changeCount !== 1 ? "s" : ""}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDiscard}
                disabled={saving}
              >
                <Undo2 className="mr-1.5 h-3.5 w-3.5" />
                Discard
              </Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                {saving ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="mr-1.5 h-3.5 w-3.5" />
                )}
                Save & Apply
              </Button>
            </div>
          </div>
        )}

        {/* Save result banner */}
        {saveResult &&
          !hasChanges &&
          (saveResult.restart_required?.length ?? 0) > 0 && (
            <div className="flex items-start gap-2.5 border-t border-amber-300/50 bg-amber-50 px-5 py-3 text-sm dark:border-amber-500/30 dark:bg-amber-950/30">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <div>
                <p className="font-medium text-amber-800 dark:text-amber-200">
                  {saveResult.restart_required.length} setting
                  {saveResult.restart_required.length !== 1 ? "s" : ""} saved
                  but require restart
                </p>
                <p className="mt-0.5 text-amber-700 dark:text-amber-300">
                  {saveResult.restart_required.join(", ")} — restart SAGE to
                  apply.
                </p>
              </div>
            </div>
          )}
      </div>

      {/* Security confirmation dialog */}
      <AlertDialog
        open={confirmDialog.open}
        onOpenChange={(open) =>
          setConfirmDialog((d) => ({ ...d, open }))
        }
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-amber-500" />
              Security Setting Change
            </AlertDialogTitle>
            <AlertDialogDescription className="text-left">
              <span className="block mt-2">
                You are about to change{" "}
                <strong>{confirmDialog.label}</strong>:
              </span>
              <span className="block mt-2 text-muted-foreground">
                {confirmDialog.description}
              </span>
              <span className="block mt-3 font-medium text-amber-700 dark:text-amber-300">
                This may reduce SAGE's security restrictions.
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmSecurityChange}
              className="bg-amber-600 hover:bg-amber-700 text-white"
            >
              I understand
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Reset all confirmation dialog */}
      <AlertDialog open={resetAllDialog} onOpenChange={setResetAllDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset All Settings</AlertDialogTitle>
            <AlertDialogDescription>
              This will reset every setting to its factory default. Any custom
              values in your configuration will be overwritten. This action
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleResetAll}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Reset all settings
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// ── Individual Setting Row ──────────────────────────────────────────────────

function SettingRow({
  setting,
  effectiveValue,
  modified,
  error,
  onChange,
  onReset,
}: {
  setting: SettingSchema;
  effectiveValue: any;
  modified: boolean;
  error?: string | undefined;
  onChange: (value: any) => void;
  onReset: () => void;
}) {
  const isDefault = effectiveValue === setting.default;

  return (
    <div
      className={`rounded-lg border px-4 py-3.5 transition-colors ${
        modified
          ? "border-primary/30 bg-primary/[0.03]"
          : "border-border bg-transparent"
      } ${error ? "border-destructive/50" : ""}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Label className="text-sm font-medium">{setting.label}</Label>
            {setting.restart_required && (
              <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                Restart required
              </span>
            )}
            {setting.security_sensitive && (
              <Shield className="h-3 w-3 text-amber-500" />
            )}
            {modified && (
              <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                Modified
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
            {setting.description}
          </p>
        </div>

        {/* Control */}
        <div className="shrink-0">
          {setting.control === "toggle" && (
            <Switch
              checked={effectiveValue === true}
              onCheckedChange={(checked) => onChange(checked)}
            />
          )}
          {setting.control === "select" && setting.options && (
            <Select
              value={String(effectiveValue)}
              onValueChange={(val) => onChange(val)}
            >
              <SelectTrigger className="w-36 h-8 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {setting.options.map((opt) => (
                  <SelectItem key={opt} value={opt}>
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {setting.control === "number" && (
            <Input
              type="number"
              value={effectiveValue ?? ""}
              onChange={(e) => {
                const raw = e.target.value;
                if (raw === "") return;
                const num = parseInt(raw, 10);
                if (!isNaN(num)) onChange(num);
              }}
              min={setting.min ?? undefined}
              max={setting.max ?? undefined}
              className="w-28 h-8 text-sm"
            />
          )}
          {setting.control === "text" && (
            <Input
              type="text"
              value={effectiveValue ?? ""}
              onChange={(e) => onChange(e.target.value)}
              className="w-36 h-8 text-sm"
            />
          )}
        </div>
      </div>

      {/* Error message */}
      {error && (
        <p className="mt-2 text-xs text-destructive">{error}</p>
      )}

      {/* Default indicator + reset button */}
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">
          Default: {String(setting.default)}
        </span>
        {!isDefault && (
          <button
            type="button"
            onClick={onReset}
            className="flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
          >
            <RotateCcw className="h-3 w-3" />
            Reset to default
          </button>
        )}
      </div>
    </div>
  );
}
