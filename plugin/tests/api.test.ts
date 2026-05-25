import { ApiError, AuthError, PitchClient, PitchHttp } from "../src/api";

function fakeHttp(handler: PitchHttp["request"]): PitchHttp {
  return { request: handler };
}

describe("PitchClient", () => {
  test("submitUrl posts JSON with bearer", async () => {
    const calls: unknown[] = [];
    const http = fakeHttp(async (req) => {
      calls.push(req);
      return { status: 200, text: "{}", json: { id: "abc", status: "pending" } };
    });
    const c = new PitchClient("https://h/p", "sek", http);
    const r = await c.submitUrl("https://x");
    expect(r.id).toBe("abc");
    expect(calls).toEqual([
      {
        url: "https://h/p/jobs",
        method: "POST",
        headers: {
          Authorization: "Bearer sek",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: "https://x", topic_hint: null }),
      },
    ]);
  });

  test("trims trailing slash on baseUrl", async () => {
    const calls: unknown[] = [];
    const http = fakeHttp(async (req) => {
      calls.push(req);
      return { status: 200, text: "", json: {} };
    });
    const c = new PitchClient("https://h/p/", "sek", http);
    await c.getJob("xx");
    expect((calls[0] as { url: string }).url).toBe("https://h/p/jobs/xx");
  });

  test("401 -> AuthError", async () => {
    const http = fakeHttp(async () => ({ status: 401, text: "nope", json: null }));
    const c = new PitchClient("https://h", "k", http);
    await expect(c.getJob("x")).rejects.toBeInstanceOf(AuthError);
  });

  test("404 on getJob -> ApiError", async () => {
    const http = fakeHttp(async () => ({ status: 404, text: "", json: null }));
    const c = new PitchClient("https://h", "k", http);
    await expect(c.getJob("x")).rejects.toBeInstanceOf(ApiError);
  });

  test("submit forwards topic hint", async () => {
    const calls: { body?: string }[] = [];
    const http = fakeHttp(async (req) => {
      calls.push(req as { body?: string });
      return { status: 200, text: "", json: { id: "1", status: "pending" } };
    });
    const c = new PitchClient("https://h", "k", http);
    await c.submitUrl("https://v", "rust");
    expect(JSON.parse(calls[0].body as string)).toEqual({
      url: "https://v",
      topic_hint: "rust",
    });
  });
});
