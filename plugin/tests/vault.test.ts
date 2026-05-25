import { uniquePath } from "../src/vault";

describe("uniquePath", () => {
  test("returns base when no collision", async () => {
    const p = await uniquePath("notes", "x.md", async () => false);
    expect(p).toBe("notes/x.md");
  });

  test("adds -2 then -3 on collision", async () => {
    const taken = new Set(["notes/x.md", "notes/x-2.md"]);
    const p = await uniquePath("notes", "x.md", async (path) => taken.has(path));
    expect(p).toBe("notes/x-3.md");
  });

  test("strips trailing slash on folder", async () => {
    const p = await uniquePath("notes/", "y.md", async () => false);
    expect(p).toBe("notes/y.md");
  });

  test("works with no extension", async () => {
    const p = await uniquePath("notes", "noext", async () => false);
    expect(p).toBe("notes/noext");
  });
});
