const API_BASE = '/api/v1';

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Network error' }));
    throw new Error(error.error || error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function apiPost<T>(path: string, data: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Network error' }));
    throw new Error(error.error || error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

export async function apiDelete(path: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
  });
  if (!response.ok && response.status !== 204) {
    const error = await response.json().catch(() => ({ error: 'Network error' }));
    throw new Error(error.error || error.detail || `HTTP ${response.status}`);
  }
}
