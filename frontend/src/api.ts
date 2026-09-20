export type HealthResponse = { status: "ok"; application: "image-finisher" };

export type PlannedImage = {
  source_name: string;
  source_path: string;
  group: string;
  output_name: string;
  output_path: string;
  width: number | null;
  height: number | null;
};

export type ScanResult = {
  input_folder: string;
  output_folder: string;
  target_count: number;
  excluded_count: number;
  can_start: boolean;
  groups: Array<{ name: string; count: number; examples: PlannedImage[] }>;
  images: PlannedImage[];
  errors: Array<{ code: string; message: string; path: string | null }>;
};

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancel_requested" | "cancelled";
export type Job = {
  id: string;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  input_folder: string;
  output_folder: string;
  enabled_steps: string[];
  settings: Record<string, unknown>;
  error: string | null;
  total_count: number;
  processed_count: number;
  counts: Record<string, number>;
  images: Array<{
    id: number; source_name: string; group_name: string; output_name: string;
    status: JobStatus; error: string | null;
    steps: Array<{ id: number; name: string; status: JobStatus; error: string | null }>;
  }>;
};

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/health", { signal });
  if (!response.ok) throw new Error(`API health check failed: ${response.status}`);
  return (await response.json()) as HealthResponse;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
    throw new Error(body?.error?.message ?? `API request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function selectFolder(): Promise<string | null> {
  const response = await fetch("/api/folders/select", { method: "POST" });
  const body = await parseResponse<{ path: string | null }>(response);
  return body.path;
}

export async function scanFolder(path: string): Promise<ScanResult> {
  const response = await fetch("/api/folders/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path })
  });
  return parseResponse<ScanResult>(response);
}

export async function createTestJob(inputFolder: string): Promise<Job> {
  const response = await fetch("/api/jobs/test", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_folder: inputFolder })
  });
  return parseResponse<Job>(response);
}

export async function fetchJobs(): Promise<Job[]> {
  return parseResponse<Job[]>(await fetch("/api/jobs"));
}

export async function clearJobHistory(): Promise<number> {
  const body = await parseResponse<{ deleted_count: number }>(await fetch("/api/jobs", { method: "DELETE" }));
  return body.deleted_count;
}

export async function cancelJob(jobId: string): Promise<Job> {
  return parseResponse<Job>(await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" }));
}
