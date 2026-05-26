/**
 * HTTP client to the Pitch dispatcher. Uses Obsidian's requestUrl to bypass CORS.
 * Imports are dynamic so unit tests can run without the Obsidian module loaded.
 */
import type { RequestUrlResponse } from "obsidian";

export type JobStatus =
  | "pending"
  | "claimed"
  | "fetching"
  | "transcribing"
  | "extracting"
  | "understanding"
  | "rendering"
  | "done"
  | "failed";

export interface Attachment {
  filename: string;
  base64: string;
}

export interface JobView {
  id: string;
  status: JobStatus;
  progress_message: string | null;
  result_markdown: string | null;
  result_title: string | null;
  result_slug: string | null;
  error: string | null;
  user_guidance: string | null;
  result_attachments: Attachment[];
}

export interface SubmitResponse {
  id: string;
  status: JobStatus;
}

export interface PitchHttp {
  request(opts: {
    url: string;
    method: string;
    headers?: Record<string, string>;
    body?: string;
  }): Promise<{ status: number; text: string; json: unknown }>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class AuthError extends ApiError {
  constructor() {
    super(401, "Invalid or missing API key");
  }
}

export class PitchClient {
  constructor(
    private baseUrl: string,
    private apiKey: string,
    private http: PitchHttp,
  ) {}

  private endpoint(path: string): string {
    const trimmed = this.baseUrl.replace(/\/+$/, "");
    return `${trimmed}${path}`;
  }

  private headers(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
    };
  }

  async submitUrl(url: string, topicHint?: string): Promise<SubmitResponse> {
    const r = await this.http.request({
      url: this.endpoint("/jobs"),
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ url, topic_hint: topicHint ?? null }),
    });
    if (r.status === 401) throw new AuthError();
    if (r.status >= 400) throw new ApiError(r.status, r.text);
    return r.json as SubmitResponse;
  }

  async getJob(id: string): Promise<JobView> {
    const r = await this.http.request({
      url: this.endpoint(`/jobs/${encodeURIComponent(id)}`),
      method: "GET",
      headers: this.headers(),
    });
    if (r.status === 401) throw new AuthError();
    if (r.status === 404) throw new ApiError(404, "Job not found");
    if (r.status >= 400) throw new ApiError(r.status, r.text);
    return r.json as JobView;
  }
}

/** Adapter that wraps Obsidian's requestUrl in our PitchHttp shape. */
export function obsidianHttp(
  requestUrl: (req: {
    url: string;
    method?: string;
    headers?: Record<string, string>;
    body?: string;
    throw?: boolean;
  }) => Promise<RequestUrlResponse>,
): PitchHttp {
  return {
    async request({ url, method, headers, body }) {
      const r = await requestUrl({ url, method, headers, body, throw: false });
      return {
        status: r.status,
        text: r.text,
        json: safeJson(r.text),
      };
    },
  };
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
