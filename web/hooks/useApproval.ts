"use client";

import { useCallback, useState } from "react";

export interface PendingApproval {
  reason: string;           // "update_mode" | "sensitive_file"
  description: string;      // human-readable explanation
  files_to_modify?: string[];
  requirement?: string;
  filepath?: string;
}

interface UseApprovalResult {
  pending: PendingApproval | null;
  submitting: boolean;
  setPending: (info: PendingApproval) => void;
  respond: (approved: boolean, note?: string) => Promise<void>;
}

/**
 * Manages the HITL approval lifecycle for a single job.
 *
 * Call `setPending(info)` when a `hitl.approval_required` event arrives.
 * Call `respond(approved, note)` when the user clicks Approve / Reject.
 */
export function useApproval(jobId: string): UseApprovalResult {
  const [pending, setPendingState] = useState<PendingApproval | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const setPending = useCallback((info: PendingApproval) => {
    setPendingState(info);
  }, []);

  const respond = useCallback(
    async (approved: boolean, note = "") => {
      setSubmitting(true);
      try {
        await fetch(`/api/proxy/jobs/${jobId}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved, note }),
        });
      } catch {
        // swallow — the backend HITL gate will time out gracefully after 10 min
      } finally {
        setSubmitting(false);
        setPendingState(null);
      }
    },
    [jobId],
  );

  return { pending, submitting, setPending, respond };
}
