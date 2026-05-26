import { App, Modal, Notice, Setting } from "obsidian";

import { ApiError, AuthError, PitchClient } from "./api";
import { ActiveJob, formatElapsed, JobTracker } from "./job-tracker";

/**
 * Submit one or many URLs (one per line), then close. Polling continues
 * in the background via JobTracker.
 *
 * Multi-URL paste pattern: copy a column from a doc/screenshot list and paste
 * straight in. Empty lines and #comments are ignored. Schemeless URLs (e.g.
 * `douyin.com/video/123`) are accepted — the worker normalizes them.
 */
export class IngestUrlModal extends Modal {
  private urlsRaw = "";
  private topicHint = "";
  private submitting = false;
  private statusEl: HTMLElement | null = null;
  private refreshInterval: number | null = null;
  private unsubscribe: (() => void) | null = null;

  constructor(
    app: App,
    private client: PitchClient,
    private tracker: JobTracker,
  ) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h2", { text: "Pitch: Ingest URLs" });

    this.statusEl = contentEl.createEl("div", { cls: "pitch-status-panel" });
    this.renderStatus();
    this.unsubscribe = this.tracker.onChange(() => this.renderStatus());
    this.refreshInterval = window.setInterval(() => this.renderStatus(), 1000);

    new Setting(contentEl)
      .setName("Video URLs")
      .setDesc(
        "Paste one URL per line. Douyin, YouTube, or any yt-dlp-supported link. " +
          "Schemeless URLs are fine.",
      )
      .addTextArea((t) => {
        t.inputEl.classList.add("pitch-modal-textarea");
        t.inputEl.rows = 6;
        t.inputEl.setAttribute("autofocus", "true");
        t.inputEl.placeholder = "douyin.com/video/123\ndouyin.com/video/456\n...";
        t.onChange((v) => (this.urlsRaw = v));
        // Cmd/Ctrl+Enter submits; plain Enter inserts a newline.
        t.inputEl.addEventListener("keydown", (e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            this.submit();
          }
        });
      });

    new Setting(contentEl)
      .setName("Topic hint (optional)")
      .setDesc("Applied to all URLs in this batch.")
      .addText((t) => {
        t.inputEl.classList.add("pitch-modal-input");
        t.onChange((v) => (this.topicHint = v.trim()));
      });

    new Setting(contentEl).addButton((b) =>
      b
        .setButtonText("Send to Pitch")
        .setCta()
        .onClick(() => this.submit()),
    );

    contentEl.createEl("div", {
      cls: "pitch-progress",
      text: "Cmd/Ctrl+Enter submits. Jobs run in parallel; you'll get a Notice per job.",
    });
  }

  private renderStatus(): void {
    if (!this.statusEl) return;
    const jobs = this.tracker.getActive();
    this.statusEl.empty();
    if (jobs.length === 0) return;

    this.statusEl.createEl("div", {
      cls: "pitch-status-header",
      text: `Active jobs (${jobs.length})`,
    });
    const list = this.statusEl.createEl("ul", { cls: "pitch-status-list" });
    for (const job of jobs) this.renderJobRow(list, job);
  }

  private renderJobRow(parent: HTMLElement, job: ActiveJob): void {
    const li = parent.createEl("li", { cls: "pitch-status-row" });
    li.createEl("span", { cls: "pitch-status-label", text: job.label });
    const stateText = job.message ? `${job.status} — ${job.message}` : job.status;
    li.createEl("span", { cls: "pitch-status-state", text: stateText });
    li.createEl("span", {
      cls: "pitch-status-elapsed",
      text: formatElapsed(job.startedAt),
    });
  }

  private async submit() {
    if (this.submitting) return;
    const urls = parseUrlList(this.urlsRaw);
    if (urls.length === 0) {
      new Notice("Pitch: paste at least one URL");
      return;
    }
    this.submitting = true;

    let queued = 0;
    const failed: string[] = [];
    for (const url of urls) {
      try {
        const sub = await this.client.submitUrl(
          url,
          this.topicHint || undefined,
        );
        this.tracker.track(sub.id, this.shortLabel(url));
        queued += 1;
      } catch (e) {
        failed.push(this.errMessage(url, e));
      }
    }

    if (queued > 0) {
      new Notice(
        `Pitch: queued ${queued} job${queued === 1 ? "" : "s"}. I'll notify per job.`,
        5_000,
      );
    }
    for (const msg of failed) new Notice(msg, 8_000);
    if (queued > 0) this.close();
    else this.submitting = false;
  }

  private errMessage(url: string, e: unknown): string {
    const tail = this.shortLabel(url);
    if (e instanceof AuthError) return `Pitch [${tail}]: API key rejected.`;
    if (e instanceof ApiError) return `Pitch [${tail}]: server ${e.status}.`;
    return `Pitch [${tail}]: ${(e as Error).message}`;
  }

  private shortLabel(url: string): string {
    const normalized = url.includes("://") ? url : `https://${url}`;
    try {
      const u = new URL(normalized);
      const host = u.hostname.replace(/^www\./, "");
      const tail = u.pathname.split("/").filter(Boolean).pop() || "";
      return tail ? `${host}/${tail.slice(0, 24)}` : host;
    } catch {
      return url.slice(0, 40);
    }
  }

  onClose() {
    if (this.refreshInterval !== null) {
      window.clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    this.contentEl.empty();
  }
}

/**
 * Pure: split a multi-line paste into one URL per non-empty, non-comment line.
 * Trims whitespace. Drops # comments and blank lines. Dedupes preserving order.
 */
export function parseUrlList(raw: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (seen.has(trimmed)) continue;
    seen.add(trimmed);
    out.push(trimmed);
  }
  return out;
}
