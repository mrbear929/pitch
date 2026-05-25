/**
 * Poll a Pitch job until it reaches a terminal state, with progress callbacks.
 * Pure async function — Obsidian API is injected, so this is testable.
 */
import { JobView, PitchClient } from "./api";

export interface PollOptions {
  intervalMs: number;
  timeoutMs: number;
  /** Called every poll. Use to update modal text, etc. */
  onStatus?: (job: JobView) => void;
  /** Returns ms-since-epoch. Injectable for tests. */
  now?: () => number;
  /** Sleep for ms. Injectable for tests. */
  sleep?: (ms: number) => Promise<void>;
}

export async function pollUntilDone(
  client: PitchClient,
  jobId: string,
  opts: PollOptions,
): Promise<JobView> {
  const now = opts.now ?? (() => Date.now());
  const sleep = opts.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
  const deadline = now() + opts.timeoutMs;

  for (;;) {
    const job = await client.getJob(jobId);
    opts.onStatus?.(job);
    if (job.status === "done" || job.status === "failed") {
      return job;
    }
    if (now() >= deadline) {
      throw new Error("Pitch job timed out before completing");
    }
    await sleep(opts.intervalMs);
  }
}
