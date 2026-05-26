import { App, Modal, Notice, Setting } from "obsidian";

import { ApiError, AuthError, PitchClient } from "./api";
import { ActiveJob, formatElapsed, JobTracker } from "./job-tracker";

/**
 * Submit a URL, then close. Polling continues in the background via JobTracker.
 *
 * If there are jobs already running when this modal opens, show them at the top
 * with live status — this is how the user knows something is in flight without
 * needing a permanent status-bar widget.
 */
export class IngestUrlModal extends Modal {
  private url = "";
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
    contentEl.createEl("h2", { text: "Pitch: Ingest URL" });

    // Status panel — only renders when there's something to show.
    this.statusEl = contentEl.createEl("div", { cls: "pitch-status-panel" });
    this.renderStatus();
    this.unsubscribe = this.tracker.onChange(() => this.renderStatus());
    // Tick every second so elapsed times update while modal is open.
    this.refreshInterval = window.setInterval(() => this.renderStatus(), 1000);

    new Setting(contentEl)
      .setName("Video URL")
      .setDesc("Douyin, YouTube, or any yt-dlp-compatible link.")
      .addText((t) => {
        t.inputEl.classList.add("pitch-modal-input");
        t.inputEl.setAttribute("autofocus", "true");
        t.onChange((v) => (this.url = v.trim()));
        t.inputEl.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            this.submit();
          }
        });
      });

    new Setting(contentEl)
      .setName("Topic hint (optional)")
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
      text: "Submission runs in the background. You'll see a Notice when the note is ready.",
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
    for (const job of jobs) {
      this.renderJobRow(list, job);
    }
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
    if (!this.url) {
      new Notice("Pitch: paste a URL first");
      return;
    }
    this.submitting = true;

    try {
      const sub = await this.client.submitUrl(this.url, this.topicHint || undefined);
      const label = this.shortLabel(this.url);
      this.tracker.track(sub.id, label);
      new Notice(`Pitch [${label}]: queued. I'll notify when done.`, 5_000);
      this.close();
    } catch (e) {
      if (e instanceof AuthError) {
        new Notice("Pitch: API key rejected. Check Settings → Pitch.", 8_000);
      } else if (e instanceof ApiError) {
        new Notice(`Pitch: server returned ${e.status}: ${e.message.slice(0, 200)}`, 8_000);
      } else {
        new Notice(`Pitch: ${(e as Error).message}`, 8_000);
      }
      this.submitting = false;
    }
  }

  private shortLabel(url: string): string {
    try {
      const u = new URL(url);
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
