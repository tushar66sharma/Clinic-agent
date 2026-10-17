// Typed API client. Every call has a timeout and returns a normalised ApiError on failure,
// so pages can always show a clear message instead of a blank screen.

import type {
  Evaluation, Health, InboxEntry, Job, ProcessedItem, RunLog, Schedule,
} from "./types";

// Empty in development (Vite proxies /api) and in the single-service deployment.
// Set VITE_API_BASE_URL when the dashboard is hosted separately (e.g. Vercel + Render).
export const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const TOKEN_KEY = "edvak_access_token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields?: { field: string; message: string }[],
  ) {
    super(message);
  }
}

export function getToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(value: string): void {
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): token just won't persist */
  }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["X-Access-Token"] = token;
  try {
    const res = await fetch(`${BASE}${path}`, { ...init, headers, signal: controller.signal });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const err = data?.error ?? {};
      throw new ApiError(res.status, err.code ?? "http_error",
        err.message ?? `Request failed (${res.status}).`, err.fields);
    }
    return data as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error).name === "AbortError") {
      throw new ApiError(0, "timeout", "The server took too long to respond. It may be waking up; try again in a minute.");
    }
    throw new ApiError(0, "network", "Cannot reach the server. Check that the API is running.");
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request<Health>("/api/health", {}, 70000), // free hosts can take ~1 min to wake
  clinic: () => request<Record<string, unknown>>("/api/clinic"),
  inbox: (set: string) => request<{ set: string; messages: InboxEntry[] }>(`/api/inbox/${set}`),
  results: () => request<{ items: ProcessedItem[] }>("/api/results"),
  result: (id: string) => request<ProcessedItem>(`/api/results/${encodeURIComponent(id)}`),
  processMessage: (body: Record<string, string>) =>
    request<ProcessedItem>("/api/messages/process", { method: "POST", body: JSON.stringify(body) }, 180000),
  startRun: (set: string, ids?: string[], resetFirst = true) =>
    request<Job>("/api/runs", { method: "POST", body: JSON.stringify({ set, ids, reset_first: resetFirst }) }),
  run: (id: string) => request<Job>(`/api/runs/${id}`),
  queues: () => request<RunLog>("/api/queues"),
  schedule: (day?: string) => request<Schedule>(`/api/schedule${day ? `?day=${day}` : ""}`),
  reports: () => request<{ items: { name: string; headline: Evaluation["headline"] }[] }>("/api/reports"),
  report: (name: string) =>
    request<{ name: string; evaluation: Evaluation; summary: Record<string, unknown> }>(`/api/reports/${encodeURIComponent(name)}`),
  reset: () => request<{ ok: boolean }>("/api/state/reset", { method: "POST" }),
};
