import { useSystemStats } from "@/hooks/useSystemStats";
import { Progress } from "@/components/ui/progress";
import { Cpu, MemoryStick, Monitor, AlertCircle } from "lucide-react";

export function SystemMonitor({ enabled }: { enabled: boolean }) {
  const { data, loading, error } = useSystemStats(enabled);

  if (!enabled) return null;

  return (
    <div className="w-full space-y-4 rounded-xl border border-sidebar-border bg-sidebar-accent p-3 text-sm shadow-sm transition-opacity duration-200">
      <div className="flex items-center justify-between border-b border-sidebar-border pb-2">
        <span className="text-xs font-semibold tracking-wide text-muted-foreground flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${error ? 'bg-destructive' : 'bg-green-500'}`}></span>
            <span className={`relative inline-flex rounded-full h-2 w-2 ${error ? 'bg-destructive' : 'bg-green-500'}`}></span>
          </span>
          SYSTEM HEALTH
        </span>
      </div>

      {error ? (
        <div className="flex flex-col items-center justify-center py-4 text-muted-foreground gap-2">
          <AlertCircle className="h-5 w-5 text-destructive/70" />
          <span className="text-xs">Metrics Unavailable</span>
        </div>
      ) : (
        <div className="space-y-4">
          {/* CPU Section */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-sidebar-foreground">
                <Cpu className="h-3.5 w-3.5" />
                <span className="font-medium text-xs">CPU</span>
              </div>
              <span className="text-xs font-mono text-muted-foreground">
                {data ? `${data.cpu.usage_percent.toFixed(0)}%` : "—"}
              </span>
            </div>
            <Progress value={data?.cpu.usage_percent ?? 0} className="h-1.5" />
            <div className="text-[10px] text-muted-foreground">
              {data ? `${data.cpu.thread_count} Threads` : "..."}
            </div>
          </div>

          {/* RAM Section */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-sidebar-foreground">
                <MemoryStick className="h-3.5 w-3.5" />
                <span className="font-medium text-xs">RAM</span>
              </div>
              <span className="text-xs font-mono text-muted-foreground">
                {data ? `${data.memory.usage_percent.toFixed(0)}%` : "—"}
              </span>
            </div>
            <Progress value={data?.memory.usage_percent ?? 0} className="h-1.5" />
            <div className="text-[10px] text-muted-foreground">
              {data ? `${data.memory.used_gb.toFixed(1)} / ${data.memory.total_gb.toFixed(1)} GB` : "..."}
            </div>
          </div>

          {/* GPU Section */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-sidebar-foreground">
                <Monitor className="h-3.5 w-3.5" />
                <span className="font-medium text-xs">GPU</span>
              </div>
              <span className="text-xs font-mono text-muted-foreground">
                {data && data.gpu.available
                  ? `${data.gpu.utilization_percent?.toFixed(0)}%`
                  : "—"}
              </span>
            </div>
            <Progress value={data?.gpu.available ? data.gpu.utilization_percent : 0} className="h-1.5" />
            
            {data?.gpu.available ? (
              <div className="flex flex-col gap-0.5 text-[10px] text-muted-foreground">
                <span className="truncate" title={data.gpu.name}>{data.gpu.name}</span>
                <div className="flex justify-between">
                  <span>
                    {(data.gpu.vram_used_mb! / 1024).toFixed(1)} / {(data.gpu.vram_total_mb! / 1024).toFixed(1)} GB VRAM
                  </span>
                  <span>
                    {data.gpu.temperature_c}°C
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-[10px] text-muted-foreground">GPU unavailable</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
