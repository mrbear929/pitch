import { JobView, PitchClient, PitchHttp } from "../src/api";
import { pollUntilDone } from "../src/poll";

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

const partial = (over: Partial<JobView>): JobView => ({
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

describe("pollUntilDone", () => {
  test("returns when status=done", async () => {
    const c = buildClient([
      partial({ status: "pending" }),
      partial({ status: "transcribing" }),
      partial({ status: "done", result_markdown: "# hi" }),
    ]);
    const onStatus = jest.fn();
    const job = await pollUntilDone(c, "j", {
      intervalMs: 1,
      timeoutMs: 10_000,
      onStatus,
      sleep: () => Promise.resolve(),
    });
    expect(job.status).toBe("done");
    expect(onStatus).toHaveBeenCalledTimes(3);
  });

  test("returns when status=failed", async () => {
    const c = buildClient([partial({ status: "failed", error: "boom" })]);
    const job = await pollUntilDone(c, "j", {
      intervalMs: 1,
      timeoutMs: 10_000,
      sleep: () => Promise.resolve(),
    });
    expect(job.status).toBe("failed");
  });

  test("times out", async () => {
    const c = buildClient([partial({ status: "pending" })]);
    let t = 0;
    await expect(
      pollUntilDone(c, "j", {
        intervalMs: 100,
        timeoutMs: 50,
        now: () => (t += 200),
        sleep: () => Promise.resolve(),
      }),
    ).rejects.toThrow(/timed out/);
  });
});
