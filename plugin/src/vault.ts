/**
 * Compute a unique target path inside the vault output folder, ensuring no overwrite.
 * Pure: takes the existence-check function as input.
 */
export async function uniquePath(
  folder: string,
  baseFilename: string,
  exists: (path: string) => Promise<boolean>,
): Promise<string> {
  const cleanFolder = folder.replace(/\/+$/, "");
  const dot = baseFilename.lastIndexOf(".");
  const stem = dot === -1 ? baseFilename : baseFilename.slice(0, dot);
  const ext = dot === -1 ? "" : baseFilename.slice(dot);

  let candidate = `${cleanFolder}/${stem}${ext}`;
  if (!(await exists(candidate))) return candidate;

  for (let i = 2; i < 100; i++) {
    candidate = `${cleanFolder}/${stem}-${i}${ext}`;
    if (!(await exists(candidate))) return candidate;
  }
  throw new Error(`Could not find a unique filename for ${baseFilename} in ${folder}`);
}
