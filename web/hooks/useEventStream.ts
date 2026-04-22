"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { TERMINAL_EVENTS } from "@/lib/eventLabels";

export interface StreamEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
  job_id: string;
  label: string;
}

interface UseEventStreamResult {
  events: StreamEvent[];
  connected: boolean;
  done: boolean;
}

/**
 * Connects to the SSE stream for a job and returns the accumulated event list.
 *
 * - Reconnects automatically on network error (3-second back-off).
 * - Stops reconnecting once a terminal event has been received.
 * - Pre-existing events are replayed by the backend on each new connection,
 *   so de-duplication by timestamp+type is applied.
 */
export function useEventStream(jobId: string): UseEventStreamResult {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);

  // Keep mutable refs for values used inside the EventSource callbacks
  // so we never need to re-run the effect on every state change.
  const esRef   = useRef<EventSource | null>(null);
  const doneRef = useRef(false);
  const seenRef = useRef(new Set<string>());

  const connect = useCallback(() => {
    if (doneRef.current) return;
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    const es = new EventSource(`/api/proxy/jobs/${jobId}/stream`);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (e: MessageEvent<string>) => {
      let event: StreamEvent;
      try {
        event = JSON.parse(e.data) as StreamEvent;
      } catch {
        return; // ignore malformed frames
      }

      // De-duplicate: backend replays history on reconnect
      const key = `${event.type}::${event.timestamp}`;
      if (seenRef.current.has(key)) return;
      seenRef.current.add(key);

      setEvents((prev) => [...prev, event]);

      if (TERMINAL_EVENTS.has(event.type)) {
        doneRef.current = true;
        setDone(true);
        setConnected(false);
        es.close();
        esRef.current = null;
      }
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      esRef.current = null;
      if (!doneRef.current) {
        // Exponential back-off (simple version: flat 3 s)
        setTimeout(connect, 3000);
      }
    };
  }, [jobId]);

  useEffect(() => {
    // Reset state if jobId changes (unlikely but correct)
    setEvents([]);
    setConnected(false);
    setDone(false);
    doneRef.current = false;
    seenRef.current = new Set();

    connect();

    return () => {
      esRef.current?.close();
      esRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return { events, connected, done };
}
