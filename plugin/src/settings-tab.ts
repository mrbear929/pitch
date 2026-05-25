import { App, PluginSettingTab, Setting } from "obsidian";

import type PitchPlugin from "./main";

export class PitchSettingsTab extends PluginSettingTab {
  constructor(
    app: App,
    private plugin: PitchPlugin,
  ) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Pitch" });

    new Setting(containerEl)
      .setName("Server URL")
      .setDesc("Pitch dispatcher base URL, e.g. https://tools.mrbear929.com/pitch")
      .addText((t) =>
        t
          .setPlaceholder("https://...")
          .setValue(this.plugin.settings.serverUrl)
          .onChange(async (v) => {
            this.plugin.settings.serverUrl = v.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("API key")
      .setDesc("Bearer token for the dispatcher (client role).")
      .addText((t) => {
        t.inputEl.type = "password";
        t.setValue(this.plugin.settings.apiKey).onChange(async (v) => {
          this.plugin.settings.apiKey = v.trim();
          await this.plugin.saveSettings();
        });
      });

    new Setting(containerEl)
      .setName("Output folder")
      .setDesc("Vault-relative folder where notes will be created.")
      .addText((t) =>
        t
          .setValue(this.plugin.settings.outputFolder)
          .onChange(async (v) => {
            this.plugin.settings.outputFolder = v.trim().replace(/^\/+|\/+$/g, "");
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Poll interval (ms)")
      .addText((t) =>
        t
          .setValue(String(this.plugin.settings.pollIntervalMs))
          .onChange(async (v) => {
            const n = parseInt(v, 10);
            if (!Number.isNaN(n) && n >= 500) {
              this.plugin.settings.pollIntervalMs = n;
              await this.plugin.saveSettings();
            }
          }),
      );

    new Setting(containerEl)
      .setName("Poll timeout (ms)")
      .setDesc("Give up if the worker hasn't finished within this time.")
      .addText((t) =>
        t
          .setValue(String(this.plugin.settings.pollTimeoutMs))
          .onChange(async (v) => {
            const n = parseInt(v, 10);
            if (!Number.isNaN(n) && n >= 60_000) {
              this.plugin.settings.pollTimeoutMs = n;
              await this.plugin.saveSettings();
            }
          }),
      );
  }
}
