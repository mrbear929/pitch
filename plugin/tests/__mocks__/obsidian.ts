// Stand-in for the obsidian module so non-Obsidian tests can import freely.
// Only types touched by tests need to be present.

export interface RequestUrlResponse {
  status: number;
  text: string;
  json: unknown;
}

export const requestUrl = async (): Promise<RequestUrlResponse> => {
  throw new Error("requestUrl is not implemented in tests; inject your own http");
};

export class Plugin {}
export class Modal {
  contentEl: { empty(): void; createEl(): unknown; createDiv(): unknown } = {
    empty: () => {},
    createEl: () => ({}),
    createDiv: () => ({}),
  };
}
export class PluginSettingTab {}
export class Notice {
  constructor(public message: string) {}
}
export class Setting {
  constructor() {}
  setName() { return this; }
  setDesc() { return this; }
  addText() { return this; }
  addButton() { return this; }
  addToggle() { return this; }
}
export type App = unknown;
export type TFile = unknown;
