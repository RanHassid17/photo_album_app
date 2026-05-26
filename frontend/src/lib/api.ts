const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export interface Health {
  status: string;
  service: string;
  version: string;
}

export async function fetchHealth(): Promise<Health> {
  const r = await fetch(`${BASE_URL}/healthz`);
  if (!r.ok) throw new Error(`Health check failed: ${r.status}`);
  return (await r.json()) as Health;
}
