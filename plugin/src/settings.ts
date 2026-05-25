export interface PitchSettings {
  serverUrl: string;
  apiKey: string;
  outputFolder: string;
  pollIntervalMs: number;
  pollTimeoutMs: number;
}

export const DEFAULT_SETTINGS: PitchSettings = {
  serverUrl: "https://tools.mrbear929.com/pitch",
  apiKey: "",
  outputFolder: "_todo/ideas/vibe-coding",
  pollIntervalMs: 3000,
  pollTimeoutMs: 30 * 60 * 1000, // 30 minutes
};
