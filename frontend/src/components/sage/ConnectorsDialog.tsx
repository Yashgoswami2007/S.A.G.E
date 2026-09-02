import { Blocks, Check, Plug } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { Connector } from "@/lib/sage-store";

export function ConnectorsDialog({
  open,
  onOpenChange,
  connectors,
  onToggle,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectors: Connector[];
  onToggle: (id: string) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-serif text-xl">
            <Blocks className="h-5 w-5 text-primary" /> Connectors
          </DialogTitle>
          <DialogDescription>
            Connect MCP tools and apps so SAGE can work with your data in chat.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-1 max-h-[55vh] space-y-2 overflow-y-auto pr-1">
          {connectors.map((connector) => (
            <div
              key={connector.id}
              className="flex items-center gap-3 rounded-xl border border-border bg-card p-3"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
                <Plug className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{connector.name}</p>
                <p className="truncate text-xs text-muted-foreground">{connector.description}</p>
              </div>
              <Button
                size="sm"
                variant={connector.enabled ? "secondary" : "outline"}
                onClick={() => onToggle(connector.id)}
              >
                {connector.enabled ? (
                  <>
                    <Check className="h-3.5 w-3.5" /> Connected
                  </>
                ) : (
                  "Connect"
                )}
              </Button>
            </div>
          ))}
        </div>

        <p className="text-xs text-muted-foreground">
          Connectors are configured locally in this demo. SAGE is told which ones are active and
          will reason about them in its answers.
        </p>
      </DialogContent>
    </Dialog>
  );
}
