import { JobView, PitchClient, PitchHttp } from "../src/api";
import { formatElapsed, JobTracker } from "../src/job-tracker";

function buildClient(jobs: JobView[]): PitchClient {
  let i = 0;
  const http: PitchHttp = {
    async request() {
      const j = jobs[Math.min(i, jobs.length - 1)];
      i += 1;
      return { status: 200, text: "", json: j };
    },
  };
  return new PitchClient("http://x", "k", http);
}

const jobView = (over: Partial<JobView> = {}): JobView => ({
  id: "j",
  status: "pending",
  progress_message: null,
  result_markdown: null,
  result_title: null,
  result_slug: null,
  error: null,
  user_guidance: null,
  result_attachments: [],
  ...over,
});

function fakeApp() {
  const created: { path: string; data: string }[] = [];
  const createdBinary: { path: string; size: number }[] = [];
  const folders: string[] = [];
  return {
    created,
    createdBinary,
    folders,
    vault: {
      getAbstractFileByPath: () => null,
      create: async (p: string, data: string) => {
        created.push({ path: p, data });
        return { path: p };
      },
      createBinary: async (p: string, data: ArrayBuffer) => {
        createdBinary.push({ path: p, size: data.byteLength });
        return { path: p };
      },
      createFolder: async (p: string) => {
        folders.push(p);
      },
    },
    workspace: {
      getLeaf: () => ({ openFile: async () => undefined }),
    },
  };
}

describe("JobTracker", () => {
  test("track returns immediately and writes note when job completes", async () => {
    const client = buildClient([
      jobView({ status: "pending" }),
      jobView({ status: "done", result_markdown: "# hi", result_title: "Hi" }),
    ]);
    const app = fakeApp();
    const tracker = new JobTracker({
      app,
      client,
      settings: {
        serverUrl: "x",
        apiKey: "k",
        outputFolder: "notes",
        pollIntervalMs: 1,
        pollTimeoutMs: 10_000,
      },
    });

    expect(tracker.activeCount).toBe(0);
    tracker.track("j", "test");
    expect(tracker.activeCount).toBe(1); // active immediately

    // wait for the background poll to complete
    await new Promise((r) => setTimeout(r, 50));

    expect(tracker.activeCount).toBe(0);
    expect(app.created).toHaveLength(1);
    expect(app.created[0].path).toMatch(/^notes\/\d{4}-\d{2}-\d{2}-hi\.md$/);
    expect(app.created[0].data).toBe("# hi");
    expect(app.folders).toEqual(["notes"]);
  });

  test("cancel stops polling without writing", async () => {
    const client = buildClient([jobView({ status: "pending" })]);
    const app = fakeApp();
    const tracker = new JobTracker({
      app,
      client,
      settings: {
        serverUrl: "x",
        apiKey: "k",
        outputFolder: "notes",
        pollIntervalMs: 5,
        pollTimeoutMs: 10_000,
      },
    });
    tracker.track("j", "test");
    tracker.cancel("j");
    await new Promise((r) => setTimeout(r, 30));
    expect(app.created).toHaveLength(0);
  });

  test("multiple concurrent jobs allowed", () => {
    const client = buildClient([jobView()]);
    const tracker = new JobTracker({
      app: fakeApp(),
      client,
      settings: {
        serverUrl: "x",
        apiKey: "k",
        outputFolder: "n",
        pollIntervalMs: 999_999,
        pollTimeoutMs: 999_999,
      },
    });
    tracker.track("a", "alpha");
    tracker.track("b", "beta");
    tracker.track("c", "gamma");
    expect(tracker.activeCount).toBe(3);
    expect(tracker.getActive()).toHaveLength(3);
    tracker.cancelAll();
    expect(tracker.activeCount).toBe(0);
    expect(tracker.getActive()).toHaveLength(0);
  });

  test("attachments are written as binaries before the markdown file", async () => {
    const client = buildClient([
      jobView({
        status: "done",
        result_markdown: "# hi\n![](attachments/pitch/post-slug/01.jpg)",
        result_title: "Hi",
        result_slug: "post-slug",
        result_attachments: [
          { filename: "01.jpg", base64: "AAAA" },
          { filename: "02.jpg", base64: "BBBB" },
        ],
      }),
    ]);
    const app = fakeApp();
    const tracker = new JobTracker({
      app,
      client,
      settings: {
        serverUrl: "x",
        apiKey: "k",
        outputFolder: "notes",
        pollIntervalMs: 1,
        pollTimeoutMs: 10_000,
      },
    });
    tracker.track("j", "test");
    await new Promise((r) => setTimeout(r, 50));

    expect(app.createdBinary).toHaveLength(2);
    expect(app.createdBinary[0].path).toBe("notes/attachments/pitch/post-slug/01.jpg");
    expect(app.createdBinary[1].path).toBe("notes/attachments/pitch/post-slug/02.jpg");
    expect(app.created).toHaveLength(1);
    expect(app.created[0].data).toContain("![](attachments/pitch/post-slug/01.jpg)");
    expect(app.folders).toContain("notes/attachments/pitch/post-slug");
  });
});

describe("formatElapsed", () => {
  test("under a minute", () => {
    expect(formatElapsed(0, 5_000)).toBe("5s");
    expect(formatElapsed(0, 59_999)).toBe("59s");
  });
  test("over a minute", () => {
    expect(formatElapsed(0, 60_000)).toBe("1m");
    expect(formatElapsed(0, 83_000)).toBe("1m 23s");
  });
});
