import { App, Modal, Notice, Setting } from "obsidian";

import { ApiError, AuthError, PitchClient } from "./api";
import { JobTracker } from "./job-tracker";

/**
 * Submit a URL, then close. Polling continues in the background via JobTracker;
 * the user sees an Obsidian Notice when the note lands or fails. The modal does
 * NOT block Obsidian or stay open through processing.
 */
export class IngestUrlModal extends Modal {
  private url = "";
  private topicHint = "";
  private submitting = false;

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
      new Notice(`Pitch [${label}]: queued (${sub.id.slice(0, 6)}). I'll notify when done.`, 5_000);
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
    this.contentEl.empty();
  }
}
