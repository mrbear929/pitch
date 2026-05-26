/**
 * Background polling for in-flight Pitch jobs.
 *
 * The modal hands a job off here and closes. JobTracker keeps polling on its
 * own, fires Obsidian Notices on transitions, and writes the note (plus any
 * binary attachments) when done. Lives for the lifetime of the plugin.
 */
import { Notice, TFile } from "obsidian";

import { ApiError, AuthError, JobView, PitchClient } from "./api";
import { pollUntilDone } from "./poll";
import { PitchSettings } from "./settings";
import { filenameFor } from "./slug";
import { uniquePath } from "./vault";

export interface ActiveJob {
  id: string;
  label: string;
  status: string;
  message: string;
  startedAt: number;
}

export interface JobTrackerDeps {
  app: {
    vault: {
      getAbstractFileByPath: (p: string) => unknown;
      create: (p: string, data: string) => Promise<unknown>;
      createBinary: (p: string, data: ArrayBuffer) => Promise<unknown>;
      createFolder: (p: string) => Promise<unknown>;
    };
    workspace: {
      getLeaf: (newLeaf: boolean) => { openFile: (f: TFile) => Promise<unknown> };
    };
  };
  client: PitchClient;
  settings: PitchSettings;
}

export class JobTracker {
  private active = new Map<string, AbortController>();
  private state = new Map<string, ActiveJob>();
  private listeners = new Set<() => void>();

  constructor(private deps: JobTrackerDeps) {}

  get activeCount(): number {
    return this.active.size;
  }

  /** Snapshot of currently in-flight jobs (for the modal status panel). */
  getActive(): ActiveJob[] {
    return Array.from(this.state.values()).sort((a, b) => a.startedAt - b.startedAt);
  }

  /** Subscribe to active-job updates. Returns unsubscribe fn. */
  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private notifyChange(): void {
    for (const fn of this.listeners) {
      try {
        fn();
      } catch {
        // listener errors don't stop tracking
      }
    }
  }

  track(jobId: string, label: string): void {
    if (this.active.has(jobId)) return;
    const ac = new AbortController();
    this.active.set(jobId, ac);
    this.state.set(jobId, {
      id: jobId,
      label,
      status: "pending",
      message: "",
      startedAt: Date.now(),
    });
    this.notifyChange();
    this.runInBackground(jobId, label, ac.signal).finally(() => {
      this.active.delete(jobId);
      this.state.delete(jobId);
      this.notifyChange();
    });
  }

  cancel(jobId: string): void {
    this.active.get(jobId)?.abort();
  }

  cancelAll(): void {
    for (const ac of this.active.values()) ac.abort();
    this.active.clear();
    this.state.clear();
    this.notifyChange();
  }

  private async runInBackground(jobId: string, label: string, signal: AbortSignal): Promise<void> {
    try {
      const job = await pollUntilDone(this.deps.client, jobId, {
        intervalMs: this.deps.settings.pollIntervalMs,
        timeoutMs: this.deps.settings.pollTimeoutMs,
        onStatus: (j) => {
          if (signal.aborted) return;
          const st = this.state.get(jobId);
          if (st) {
            st.status = j.status;
            st.message = j.progress_message || "";
            this.notifyChange();
          }
        },
        sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      });
      if (signal.aborted) return;
      if (job.status === "failed") {
        new Notice(`Pitch [${label}]: ${job.user_guidance || job.error || "failed"}`, 12_000);
        return;
      }
      await this.writeNote(job);
      new Notice(`Pitch [${label}]: note saved.`, 6_000);
    } catch (e) {
      if (signal.aborted) return;
      if (e instanceof AuthError) {
        new Notice(`Pitch [${label}]: API key rejected.`, 8_000);
      } else if (e instanceof ApiError) {
        new Notice(`Pitch [${label}]: server error ${e.status}.`, 8_000);
      } else {
        new Notice(`Pitch [${label}]: ${(e as Error).message}`, 8_000);
      }
    }
  }

  private async writeNote(job: JobView): Promise<void> {
    if (!job.result_markdown) {
      throw new Error("Job done but no markdown returned");
    }
    const folder = this.deps.settings.outputFolder;
    await this.ensureFolder(folder);

    const filename = filenameFor(job.result_title || "video");
    const path = await uniquePath(folder, filename, async (p) =>
      this.deps.app.vault.getAbstractFileByPath(p) !== null,
    );

    // Save attachments first so the markdown's image refs resolve immediately.
    if (job.result_attachments && job.result_attachments.length > 0) {
      const slug = job.result_slug || "post";
      const attachFolder = `${folder}/attachments/pitch/${slug}`;
      await this.ensureFolder(`${folder}/attachments`);
      await this.ensureFolder(`${folder}/attachments/pitch`);
      await this.ensureFolder(attachFolder);
      for (const att of job.result_attachments) {
        const target = `${attachFolder}/${att.filename}`;
        // Skip if it already exists (rare, but be safe).
        if (this.deps.app.vault.getAbstractFileByPath(target)) continue;
        await this.deps.app.vault.createBinary(target, base64ToArrayBuffer(att.base64));
      }
    }

    const file = (await this.deps.app.vault.create(path, job.result_markdown)) as TFile;
    await this.deps.app.workspace.getLeaf(true).openFile(file);
  }

  private async ensureFolder(path: string): Promise<void> {
    const existing = this.deps.app.vault.getAbstractFileByPath(path);
    if (existing) return;
    try {
      await this.deps.app.vault.createFolder(path);
    } catch {
      // Race with another job creating the same folder — ignore.
    }
  }
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const len = binary.length;
  const buf = new ArrayBuffer(len);
  const view = new Uint8Array(buf);
  for (let i = 0; i < len; i++) view[i] = binary.charCodeAt(i);
  return buf;
}

/** Format an elapsed duration as "1m 23s" or "47s". */
export function formatElapsed(startedAt: number, now: number = Date.now()): string {
  const s = Math.max(0, Math.floor((now - startedAt) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? `${m}m ${rem}s` : `${m}m`;
}
