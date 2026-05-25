import { Plugin, requestUrl } from "obsidian";

import { obsidianHttp, PitchClient } from "./api";
import { IngestUrlModal } from "./modal";
import { PitchSettingsTab } from "./settings-tab";
import { DEFAULT_SETTINGS, PitchSettings } from "./settings";

export default class PitchPlugin extends Plugin {
  settings: PitchSettings = DEFAULT_SETTINGS;

  async onload() {
    await this.loadSettings();
    this.addSettingTab(new PitchSettingsTab(this.app, this));

    this.addCommand({
      id: "pitch-ingest-url",
      name: "Ingest URL",
      callback: () => {
        const client = new PitchClient(
          this.settings.serverUrl,
          this.settings.apiKey,
          obsidianHttp(requestUrl),
        );
        new IngestUrlModal(this.app, client, this.settings).open();
      },
    });
  }

  async loadSettings() {
    this.settings = { ...DEFAULT_SETTINGS, ...((await this.loadData()) ?? {}) };
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
}
