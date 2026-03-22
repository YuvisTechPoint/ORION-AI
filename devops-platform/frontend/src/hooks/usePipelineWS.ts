import { useEffect, useRef, useState } from "react";

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

export type WsEvent = {
  type: string;
  stage?: string;
  level?: string;
  message?: string;
  timestamp?: string;
  [k: string]: unknown;
};

export function usePipelineWS(
  pipelineId: string | null,
  onEvent?: (ev: WsEvent) => void,
) {
  const [connected, setConnected] = useState(false);
  const attemptsRef = useRef(0);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!pipelineId) return;
    let cancelled = false;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const open = () => {
      if (cancelled) return;
      const url = `${WS_BASE.replace(/^http/, "ws")}/ws/${pipelineId}`;
      ws = new WebSocket(url);
      ws.onopen = () => {
        setConnected(true);
        attemptsRef.current = 0;
      };
      ws.onclose = () => {
        setConnected(false);
        if (cancelled) return;
        if (attemptsRef.current >= 5) return;
        const delay = Math.min(1000 * 2 ** attemptsRef.current, 16000);
        attemptsRef.current += 1;
        timer = setTimeout(open, delay);
      };
      ws.onmessage = (ev) => {
        try {
          const parsed = JSON.parse(ev.data) as WsEvent;
          onEventRef.current?.(parsed);
        } catch {
          /* ignore */
        }
      };
      ws.onerror = () => ws?.close();
    };

    open();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [pipelineId]);

  return { connected };
}
