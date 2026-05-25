import { filenameFor, slugify, todayIsoDate } from "../src/slug";

describe("slugify", () => {
  test("ascii basic", () => {
    expect(slugify("Hello World")).toBe("hello-world");
  });
  test("strips punctuation", () => {
    expect(slugify("My Vibe Coding!!!")).toBe("my-vibe-coding");
  });
  test("mixed CJK keeps ascii words", () => {
    expect(slugify("vibe coding 教程")).toBe("vibe-coding");
  });
  test("pure CJK falls back to video", () => {
    expect(slugify("纯中文标题")).toBe("video");
  });
  test("truncates", () => {
    const s = slugify("a".repeat(200));
    expect(s.length).toBeLessThanOrEqual(60);
  });
});

describe("todayIsoDate", () => {
  test("formats yyyy-mm-dd", () => {
    expect(todayIsoDate(new Date(2026, 4, 25))).toBe("2026-05-25");
  });
});

describe("filenameFor", () => {
  test("combines date and slug with .md", () => {
    expect(filenameFor("Hello World", new Date(2026, 4, 25))).toBe("2026-05-25-hello-world.md");
  });
  test("CJK fallback", () => {
    expect(filenameFor("纯中文", new Date(2026, 4, 25))).toBe("2026-05-25-video.md");
  });
});
