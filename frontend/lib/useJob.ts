"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJob } from "./api";
import type { Job } from "./types";

const POLL_MS = 800;

export interface JobHandle {
  job: Job | null;
  /** A job started here but not yet resolved, or a job still running. */
  active: boolean;
  error: string | null;
  /** Start polling a job id returned by run/improve/fix. */
  track: (jobId: string, label?: string) => void;
  /** What the job was started for, so the UI can label the progress bar. */
  label: string | null;
  clear: () => void;
}

/**
 * Poll GET /jobs/{id} until it reaches a terminal state. One job at a time,
 * which is all any page here needs.
 */
export function useJob(onDone?: (job: Job) => void): JobHandle {
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [label, setLabel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const next = await getJob(jobId);
        if (cancelled) return;
        setJob(next);
        if (next.status === "done" || next.status === "error") {
          if (next.status === "error") setError(next.error ?? "The job failed.");
          onDoneRef.current?.(next);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        return;
      }
      timer = setTimeout(tick, POLL_MS);
    };

    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  const track = useCallback((id: string, jobLabel?: string) => {
    setError(null);
    setJob(null);
    setLabel(jobLabel ?? null);
    setJobId(id);
  }, []);

  const clear = useCallback(() => {
    setJobId(null);
    setJob(null);
    setLabel(null);
    setError(null);
  }, []);

  const active = Boolean(jobId) && job?.status !== "done" && job?.status !== "error";

  return { job, active, error, track, label, clear };
}
