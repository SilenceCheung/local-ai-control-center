import { useCallback, useEffect, useRef, useState } from "react";

/** Gentle polling for status data. SSE covers high-frequency metrics;
 *  this is for slow-changing state (default every 6 s, pauses when hidden). */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs = 6000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      const d = await fetcherRef.current();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const tick = () => { if (!document.hidden) void refresh(); };
    void refresh();
    timer = setInterval(tick, intervalMs);
    const onVis = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [intervalMs, refresh]);

  return { data, error, loading, refresh };
}
