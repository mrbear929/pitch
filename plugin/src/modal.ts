import { App, Modal, Notice, Setting, TFile } from "obsidian";

import { ApiError, AuthError, JobView, PitchClient } from "./api";
import { pollUntilDone } from "./poll";
import { PitchSettings } from "./settings";
import { filenameFor } from "./slug";
import { uniquePath } from "./vault";

export class IngestUrlModal extends Modal {
  private url = "";
  private topicHint = "";
  private progressEl?: HTMLElement;
  private submitting = false;

  constructor(
    app: App,
    private client: PitchClient,
    private settings: PitchSettings,
  ) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h2", { text: "Pitch: Ingest URL" });

    new Setting(contentEl)
      .setName("Video URL")
      .setDesc("Paste a Douyin, YouTube, or other supported link.")
      .addText((t) => {
        t.inputEl.classList.add("pitch-modal-input");
        t.inputEl.setAttribute("autofocus", "true");
        t.onChange((v) => (this.url = v.trim()));
      });

    new Setting(contentEl)
      .setName("Topic hint")
      .setDesc("Optional. Helps the worker pick a slug.")
      .addText((t) => {
        t.inputEl.classList.add("pitch-modal-input");
        t.onChange((v) => (this.topicHint = v.trim()));
      });

    new Setting(contentEl).addButton((b) =>
      b
        .setButtonText("Ingest")
        .setCta()
        .onClick(() => this.submit()),
    );

    this.progressEl = contentEl.createEl("div", { cls: "pitch-progress" });
  }

  private setProgress(text: string) {
    if (this.progressEl) this.progressEl.setText(text);
  }

  private async submit() {
    if (this.submitting) return;
    if (!this.url) {
      new Notice("Pitch: please paste a URL");
      return;
    }
    if (!this.settings.apiKey) {
      new Notice("Pitch: set the API key in Settings → Pitch");
      return;
    }

    this.submitting = true;
    this.setProgress("Submitting…");

    try {
      const sub = await this.client.submitUrl(this.url, this.topicHint || undefined);
      this.setProgress(`Submitted. Job ${sub.id}. Polling…`);

      const job = await pollUntilDone(this.client, sub.id, {
        intervalMs: this.settings.pollIntervalMs,
        timeoutMs: this.settings.pollTimeoutMs,
        onStatus: (j) => this.setProgress(this.statusLine(j)),
      });

      if (job.status === "failed") {
        new Notice(
          `Pitch: ${job.user_guidance || job.error || "Job failed."}`,
          12_000,
        );
        this.close();
        return;
      }
      await this.writeNote(job);
      new Notice(`Pitch: note saved.`, 4_000);
      this.close();
    } catch (e) {
      if (e instanceof AuthError) {
        new Notice("Pitch: API key rejected. Check Settings → Pitch.", 8_000);
      } else if (e instanceof ApiError) {
        new Notice(`Pitch: server returned ${e.status}: ${e.message.slice(0, 200)}`, 8_000);
      } else {
        new Notice(`Pitch: ${(e as Error).message}`, 8_000);
      }
    } finally {
      this.submitting = false;
    }
  }

  private statusLine(j: JobView): string {
    const tail = j.progress_message ? ` — ${j.progress_message}` : "";
    return `${j.status}${tail}`;
  }

  private async writeNote(job: JobView): Promise<void> {
    if (!job.result_markdown) {
      throw new Error("Job done but no markdown returned");
    }
    const folder = this.settings.outputFolder;
    await this.ensureFolder(folder);
    const filename = filenameFor(job.result_title || "video");
    const path = await uniquePath(folder, filename, async (p) =>
      this.app.vault.getAbstractFileByPath(p) !== null,
    );
    const file = await this.app.vault.create(path, job.result_markdown);
    await this.app.workspace.getLeaf(true).openFile(file as TFile);
  }

  private async ensureFolder(path: string): Promise<void> {
    const existing = this.app.vault.getAbstractFileByPath(path);
    if (existing) return;
    await this.app.vault.createFolder(path);
  }

  onClose() {
    this.contentEl.empty();
  }
}
