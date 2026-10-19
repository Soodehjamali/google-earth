const API_BASE = '/api/v1';

export interface ApiErrorPayload {
  error?: string;
  code?: string;
  reason?: string;
  detail?: any;
  status: number;
}

export class ApiError extends Error {
  code: string;
  reason: string;
  detail: any;
  status: number;

  constructor(payload: ApiErrorPayload) {
    const msg = payload.reason || payload.error || `HTTP ${payload.status}`;
    super(msg);
    this.name = 'ApiError';
    this.code =
      payload.code ||
      (payload.status === 404
        ? 'ERR_RECORD_NOT_FOUND'
        : payload.status === 429
          ? 'ERR_RATE_LIMIT_EXCEEDED'
          : payload.status === 503 || payload.status === 502
            ? 'ERR_GEE_UNAVAILABLE'
            : payload.status === 504
              ? 'ERR_GEE_TIMEOUT'
              : payload.status === 400 || payload.status === 422
                ? 'ERR_VALIDATION_FAILED'
                : 'ERR_INTERNAL_SERVER_ERROR');
    this.reason = payload.reason || payload.error || 'Server communication error';
    this.detail = payload.detail;
    this.status = payload.status;
  }
}

async function extractError(response: Response): Promise<ApiError> {
  let body: any = {};
  try {
    body = await response.json();
  } catch {
    body = { error: 'Network error', code: 'ERR_NETWORK', reason: 'Network communication failure' };
  }

  const code = body.code || (body.detail && typeof body.detail === 'object' ? body.detail.code : undefined);
  const reason = body.reason || (body.detail && typeof body.detail === 'object' ? body.detail.reason : undefined);
  const errorMsg = body.error || (typeof body.detail === 'string' ? body.detail : undefined);

  return new ApiError({
    error: errorMsg,
    code,
    reason,
    detail: body.detail,
    status: response.status,
  });
}

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token =
    typeof import.meta !== 'undefined' &&
    import.meta.env &&
    (import.meta.env.VITE_ADMIN_API_KEY as string);
  if (token) {
    headers['X-Admin-Token'] = token;
  }
  return headers;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw await extractError(response);
  }
  return response.json();
}

export async function apiPost<T>(path: string, data: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    throw await extractError(response);
  }
  return response.json();
}

export async function apiPut<T>(path: string, data: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    throw await extractError(response);
  }
  return response.json();
}

export async function apiPatch<T>(path: string, data: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    throw await extractError(response);
  }
  return response.json();
}

export async function apiDelete(path: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!response.ok && response.status !== 204) {
    throw await extractError(response);
  }
}
