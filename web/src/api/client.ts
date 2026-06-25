import type { Job, JobFilesResponse, JobListResponse, WorkflowEvent } from "../types/api";

export function normalizeApiBase(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function buildUrl(apiBase: string, path: string): string {
  const normalized = normalizeApiBase(apiBase);
  if (!normalized) {
    return path;
  }
  return `${normalized}${path}`;
}

export async function requestJson<T>(apiBase: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(apiBase, path), init);
  const text = await response.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    const detail = typeof data === "object" && data && "detail" in data ? String((data as { detail: unknown }).detail) : response.statusText;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return data as T;
}

export function listJobs(apiBase: string): Promise<JobListResponse> {
  return requestJson<JobListResponse>(apiBase, "/api/jobs");
}

export function getJob(apiBase: string, jobId: string): Promise<Job> {
  return requestJson<Job>(apiBase, `/api/jobs/${encodeURIComponent(jobId)}`);
}

export function listJobFiles(apiBase: string, jobId: string): Promise<JobFilesResponse> {
  return requestJson<JobFilesResponse>(apiBase, `/api/jobs/${encodeURIComponent(jobId)}/files`);
}

export async function createJob(apiBase: string, file: File, videoType: string): Promise<Job> {
  const form = new FormData();
  form.append("file", file);
  form.append("video_type", videoType);
  return requestJson<Job>(apiBase, "/api/jobs", {
    method: "POST",
    body: form
  });
}

export async function packageVideo(apiBase: string, jobId: string, outputFilename: string, audioFile?: File | null): Promise<unknown> {
  const params = new URLSearchParams({ output_filename: outputFilename || "final_en.mp4" });
  const init: RequestInit = { method: "POST" };
  if (audioFile) {
    const form = new FormData();
    form.append("audio_file", audioFile);
    init.body = form;
  }
  return requestJson(apiBase, `/api/jobs/${encodeURIComponent(jobId)}/video/package?${params.toString()}`, init);
}

export function jobFileDownloadUrl(apiBase: string, jobId: string, relativePath: string): string {
  return buildUrl(apiBase, `/api/jobs/${encodeURIComponent(jobId)}/files/download?path=${encodeURIComponent(relativePath)}`);
}

export function artifactsDownloadUrl(apiBase: string, jobId: string): string {
  return buildUrl(apiBase, `/api/jobs/${encodeURIComponent(jobId)}/artifacts/download`);
}

export async function streamEvents(
  apiBase: string,
  path: string,
  init: RequestInit,
  onEvent: (event: WorkflowEvent) => void
): Promise<void> {
  const response = await fetch(buildUrl(apiBase, path), init);
  if (!response.ok || !response.body) {
    throw new Error(response.statusText || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\n\n/);
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.split(/\r?\n/).find((entry) => entry.startsWith("data:"));
      if (!line) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      onEvent(JSON.parse(payload) as WorkflowEvent);
    }
  }
}
