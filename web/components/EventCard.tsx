"use client";

import type { StreamEvent } from "@/hooks/useEventStream";
import { TaskBoard }        from "@/components/generative/TaskBoard";
import { FileCard }         from "@/components/generative/FileCard";
import { QAVerdict }        from "@/components/generative/QAVerdict";

interface Props {
  event: StreamEvent;
}

/**
 * Dispatches a stream event to the appropriate rich "generative" card,
 * or returns null if no special rendering is needed for this event type.
 *
 * Consumers should render the plain timeline row regardless; this component
 * provides an *additional* card beneath the row for qualifying events.
 */
export function EventCard({ event }: Props) {
  const { type, data } = event;

  switch (type) {
    case "ceo.plan_created":
      return <TaskBoard data={data} />;

    case "architect.file_written":
      return <FileCard data={data} />;

    case "evaluator.pass":
    case "evaluator.fail":
      return <QAVerdict passed={type === "evaluator.pass"} data={data} />;

    case "qa.pass":
    case "qa.fail":
      return <QAVerdict passed={type === "qa.pass"} data={data} />;

    default:
      return null;
  }
}
