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
