/**
 * Background polling for in-flight Pitch jobs.
 *
 * The modal hands a job off here and closes. JobTracker keeps polling on its
 * own, fires Obsidian Notices on transitions, and writes the note when done.
 * Survives across modal opens/closes; lives for the lifetime of the plugin.
 */
import { Notice, TFile } from "obsidian";

import { ApiError, AuthError, JobView, PitchClient } from "./api";
import { pollUntilDone } from "./poll";
import { PitchSettings } from "./settings";
import { filenameFor } from "./slug";
import { uniquePath } from "./vault";

export interface JobTrackerDeps {
  app: { vault: { getAbstractFileByPath: (p: string) => unknown; create: (p: string, data: string) => Promise<unknown>; createFolder: (p: string) => Promise<unknown> }; workspace: { getLeaf: (newLeaf: boolean) => { openFile: (f: TFile) => Promise<unknown> } } };
  client: PitchClient;
  settings: PitchSettings;
}

export class JobTracker {
  private active = new Map<string, AbortController>();

  constructor(private deps: JobTrackerDeps) {}

  /** Returns the count of currently-tracked jobs. Useful for status indicators. */
  get activeCount(): number {
    return this.active.size;
  }

  /**
   * Track a freshly-submitted job. Non-blocking: returns immediately. Polling
   * runs in the background; the user is notified by Notice on terminal state.
   */
  track(jobId: string, label: string): void {
    if (this.active.has(jobId)) return;
    const ac = new AbortController();
    this.active.set(jobId, ac);
    this.runInBackground(jobId, label, ac.signal).finally(() => {
      this.active.delete(jobId);
    });
  }

  /** Cancel polling for a job (does not cancel processing on the server). */
  cancel(jobId: string): void {
    this.active.get(jobId)?.abort();
  }

  /** Cancel everything — call from plugin onunload. */
  cancelAll(): void {
    for (const ac of this.active.values()) ac.abort();
    this.active.clear();
  }

  private async runInBackground(jobId: string, label: string, signal: AbortSignal): Promise<void> {
    let lastStatus = "";
    try {
      const job = await pollUntilDone(this.deps.client, jobId, {
        intervalMs: this.deps.settings.pollIntervalMs,
        timeoutMs: this.deps.settings.pollTimeoutMs,
        onStatus: (j) => {
          if (signal.aborted) return;
          if (j.status !== lastStatus) {
            lastStatus = j.status;
            // Quiet status updates — no notice flood. Could surface in a status bar later.
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
    const file = (await this.deps.app.vault.create(path, job.result_markdown)) as TFile;
    await this.deps.app.workspace.getLeaf(true).openFile(file);
  }

  private async ensureFolder(path: string): Promise<void> {
    const existing = this.deps.app.vault.getAbstractFileByPath(path);
    if (existing) return;
    await this.deps.app.vault.createFolder(path);
  }
}
