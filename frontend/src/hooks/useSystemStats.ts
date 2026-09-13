import { useState, useEffect } from "react";

export type SystemStats = {
  cpu: {
    usage_percent: number;
    core_count: number;
    thread_count: number;
    model: string;
  };
  memory: {
    used_gb: number;
    total_gb: number;
    usage_percent: number;
  };
  gpu: {
    available: boolean;
    name?: string;
    vram_total_mb?: number;
    utilization_percent?: number;
    vram_used_mb?: number;
    temperature_c?: number;
    power_watts?: number;
  };
};

export function useSystemStats(enabled: boolean) {
  const [data, setData] = useState<SystemStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let mounted = true;
    let failureCount = 0;
    
    // Initial fetch
    setLoading(true);
    
    const fetchStats = async () => {
      try {
        const res = await fetch("/api/system/stats");
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const json = await res.json();
        
        if (mounted) {
          setData(json);
          setError(null);
          failureCount = 0; // reset on success
        }
      } catch (e: any) {
        if (mounted) {
          setError(e);
          failureCount++;
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    fetchStats();

    // Setup polling interval
    // If we've failed repeatedly, slow down the polling to 5s instead of 1s
    const pollInterval = setInterval(fetchStats, failureCount >= 3 ? 5000 : 1000);

    return () => {
      mounted = false;
      clearInterval(pollInterval);
    };
  }, [enabled]);

  return { data, loading, error };
}
