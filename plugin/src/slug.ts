/**
 * Title -> kebab-case ASCII slug. Falls back to "video" when stripping leaves nothing.
 *
 * Mirrors worker/src/worker/text.py::slugify so filenames match end-to-end.
 */
export function slugify(title: string, maxLen = 60): string {
  if (!title) return "video";
  // Normalize, drop combining marks, drop non-ASCII.
  const ascii = title
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    // eslint-disable-next-line no-control-regex
    .replace(/[^\x00-\x7f]/g, "");
  let s = ascii.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (!s) return "video";
  s = s.slice(0, maxLen).replace(/-+$/, "");
  return s || "video";
}

export function todayIsoDate(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function filenameFor(title: string, now: Date = new Date()): string {
  return `${todayIsoDate(now)}-${slugify(title)}.md`;
}
