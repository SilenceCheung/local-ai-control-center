import { useEffect, useRef, useState } from "react";
import type { Advisory, Sample } from "../api/client";

/** Subscribes to the backend SSE metrics stream (no polling). */
export function useMetricsStream(maxSamples = 300) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [memoryAdvisory, setMemoryAdvisory] = useState<Advisory | null>(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource("/api/monitor/stream");
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "snapshot") {
          setSamples(msg.samples.slice(-maxSamples));
        } else if (msg.type === "sample") {
          setSamples((prev) => [...prev.slice(-(maxSamples - 1)), msg.sample]);
          setMemoryAdvisory(msg.memory_advisory ?? null);
        }
      } catch { /* ignore malformed */ }
    };
    return () => es.close();
  }, [maxSamples]);

  return { samples, memoryAdvisory, connected, latest: samples[samples.length - 1] };
}
