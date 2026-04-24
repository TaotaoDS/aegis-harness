"use client";

import { useEffect, useRef } from "react";
import type { StreamEvent } from "@/hooks/useEventStream";
import { EventCard }        from "@/components/EventCard";
import { RICH_EVENTS }      from "@/lib/eventLabels";
import { formatTime }       from "@/lib/utils";
import { useT }             from "@/lib/i18n";

interface Props {
  events: StreamEvent[];
  /** Auto-scroll to latest event when true */
  autoScroll?: boolean;
}

/** Map event type prefix to a colour class for the dot on the timeline. */
function dotColor(type: string): string {
  if (type.startsWith("pipeline.error") || type.startsWith("evaluator.fail") || type.startsWith("qa.fail"))
    return "bg-red-500";
  if (type.startsWith("pipeline.complete") || type.startsWith("evaluator.pass") || type.startsWith("qa.pass"))
    return "bg-green-500";
  if (type.startsWith("hitl."))
    return "bg-yellow-500";
  if (type.startsWith("architect."))
    return "bg-blue-500";
  if (type.startsWith("ceo."))
    return "bg-purple-500";
  if (type.startsWith("resilience."))
    return "bg-orange-500";
  return "bg-slate-500";
}

/**
 * Vertical event timeline.
 *
 * Each row shows: coloured dot · label · timestamp
 * Rich events (plan_created, file_written, qa result…) also render
 * an EventCard below their row.
 */
export function Timeline({ events, autoScroll = true }: Props) {
  const t = useT();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events.length, autoScroll]);

  if (events.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <div className="text-center">
          <div className="live-dot w-2 h-2 bg-blue-500 rounded-full mx-auto mb-3" />
          <p className="text-sm">{t.timeline.waiting}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {events.map((event, idx) => {
        const isLast    = idx === events.length - 1;
        const hasCard   = RICH_EVENTS.has(event.type);
        const color     = dotColor(event.type);

        return (
          <div key={`${event.type}::${event.timestamp}::${idx}`} className="flex gap-4">
            {/* Left gutter: dot + vertical line */}
            <div className="flex flex-col items-center shrink-0 pt-2.5">
              <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${color}`} />
              {!isLast && (
                <div className="w-px flex-1 bg-slate-700/60 mt-1" />
              )}
            </div>

            {/* Right content */}
            <div className="flex-1 pb-4 min-w-0">
              {/* Row: label + timestamp */}
              <div className="flex items-start justify-between gap-2">
                <span className="text-slate-200 text-sm leading-snug">
                  {event.label}
                </span>
                <span className="text-slate-500 text-xs shrink-0 mt-0.5">
                  {formatTime(event.timestamp)}
                </span>
              </div>

              {/* Rich card (if any) */}
              {hasCard && (
                <div className="mt-2">
                  <EventCard event={event} />
                </div>
              )}
            </div>
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
