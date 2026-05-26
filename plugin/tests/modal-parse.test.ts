import { parseUrlList } from "../src/modal";

describe("parseUrlList", () => {
  test("single line", () => {
    expect(parseUrlList("douyin.com/video/1")).toEqual(["douyin.com/video/1"]);
  });

  test("multi-line trimmed", () => {
    expect(
      parseUrlList(
        "  douyin.com/video/1\ndouyin.com/video/2  \n\nhttps://youtube.com/x\n",
      ),
    ).toEqual(["douyin.com/video/1", "douyin.com/video/2", "https://youtube.com/x"]);
  });

  test("blank lines and comments dropped", () => {
    expect(
      parseUrlList(
        "douyin.com/video/1\n\n# a comment\n   \ndouyin.com/video/2\n",
      ),
    ).toEqual(["douyin.com/video/1", "douyin.com/video/2"]);
  });

  test("dedupe preserving order", () => {
    expect(
      parseUrlList(
        "douyin.com/video/1\ndouyin.com/video/2\ndouyin.com/video/1\n",
      ),
    ).toEqual(["douyin.com/video/1", "douyin.com/video/2"]);
  });

  test("empty input -> empty list", () => {
    expect(parseUrlList("")).toEqual([]);
    expect(parseUrlList("   \n\n  ")).toEqual([]);
  });

  test("CRLF newlines handled", () => {
    expect(parseUrlList("a\r\nb\r\nc")).toEqual(["a", "b", "c"]);
  });
});
