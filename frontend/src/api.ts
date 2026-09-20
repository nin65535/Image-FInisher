export type HealthResponse = { status: "ok"; application: "image-finisher" };

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/health", { signal });
  if (!response.ok) throw new Error(`API health check failed: ${response.status}`);
  return (await response.json()) as HealthResponse;
}
