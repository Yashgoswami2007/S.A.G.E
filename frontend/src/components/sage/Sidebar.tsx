import { Blocks, MessageSquare, PanelLeft, Plus, Search, Settings, Trash2 } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { SageWordmark } from "./SageLogo";
import { groupChats, type Chat } from "@/lib/sage-store";
import { Button } from "@/components/ui/button";
import { SystemMonitor } from "./SystemMonitor";

export function Sidebar({
  chats,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onOpenConnectors,
  onOpenSettings,
  open,
  onToggle,
}: {
  chats: Chat[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onOpenConnectors: () => void;
  onOpenSettings: () => void;
  open: boolean;
  onToggle: () => void;
}) {
  const [query, setQuery] = useState("");
  const [monitorOpen, setMonitorOpen] = useState(false);
  const hoverTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const handleMouseEnter = () => {
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
    }
    setMonitorOpen(true);
  };

  const handleMouseLeave = () => {
    hoverTimeoutRef.current = setTimeout(() => {
      setMonitorOpen(false);
    }, 200);
  };

  useEffect(() => {
    return () => {
      if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
    };
  }, []);

  const filtered = query
    ? chats.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()))
    : chats;
  const groups = groupChats(filtered);

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Close sidebar"
          className="fixed inset-0 z-30 bg-foreground/20 md:hidden"
          onClick={onToggle}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-sidebar-border bg-sidebar transition-transform duration-200 md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        } ${open ? "" : "md:w-0 md:overflow-hidden md:border-r-0"}`}
      >
        <div className="flex items-center justify-between px-3 py-3">
          <SageWordmark className="text-sidebar-foreground" />
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onToggle}>
            <PanelLeft className="h-4 w-4" />
          </Button>
        </div>

        <div className="space-y-1 px-3">
          <button
            type="button"
            onClick={onNew}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium text-primary transition-colors hover:bg-sidebar-accent"
          >
            <Plus className="h-4 w-4" /> New chat
          </button>

          <div className="flex items-center gap-2 rounded-lg px-2 py-1.5 focus-within:bg-sidebar-accent">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search chats"
              className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>

          <button
            type="button"
            onClick={onOpenConnectors}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm transition-colors hover:bg-sidebar-accent"
          >
            <Blocks className="h-4 w-4 text-muted-foreground" /> Connectors
          </button>
        </div>

        <div className="mt-3 flex-1 space-y-4 overflow-y-auto px-3 pb-4">
          {groups.length === 0 && (
            <p className="px-2 pt-4 text-xs text-muted-foreground">No chats yet.</p>
          )}
          {groups.map((group) => (
            <div key={group.label}>
              <p className="px-2 pb-1 text-xs font-medium text-muted-foreground">{group.label}</p>
              <ul className="space-y-0.5">
                {group.items.map((chat) => (
                  <li key={chat.id} className="group/item relative">
                    <button
                      type="button"
                      onClick={() => onSelect(chat.id)}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 pr-8 text-left text-sm transition-colors hover:bg-sidebar-accent ${
                        chat.id === activeId
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground"
                      }`}
                    >
                      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">{chat.title}</span>
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete ${chat.title}`}
                      onClick={() => onDelete(chat.id)}
                      className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-background hover:text-destructive group-hover/item:block"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="border-t border-sidebar-border p-3 relative">
          <div 
            className="absolute bottom-full left-3 right-3 mb-2 transition-all duration-200 z-50"
            style={{ 
              opacity: monitorOpen ? 1 : 0, 
              pointerEvents: monitorOpen ? 'auto' : 'none',
              transform: monitorOpen ? 'translateY(0)' : 'translateY(10px)'
            }}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
          >
            <SystemMonitor enabled={monitorOpen} />
          </div>

          <div className="flex items-center gap-2">
            <div 
              className="flex flex-1 items-center gap-2 cursor-pointer hover:bg-sidebar-accent p-2 -m-2 rounded-lg transition-colors"
              onMouseEnter={handleMouseEnter}
              onMouseLeave={handleMouseLeave}
            >
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                Y
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm">You</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onOpenSettings}
              className="ml-auto rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
              aria-label="Settings"
            >
              <Settings className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}
