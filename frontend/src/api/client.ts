interface ApiErrorBody {
  error?: string;
  message?: string;
  fields?: Record<string, string>;
  reason?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly fields?: Record<string, string>,
    readonly reason?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const defaultApiBaseUrl = import.meta.env.DEV
  ? "/api/v1"
  : "http://localhost:5000/api/v1";
const API_BASE_URL = (configuredApiBaseUrl || defaultApiBaseUrl).replace(
  /\/+$/,
  "",
);

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      "TeamFlow could not reach the server. Check that the backend is running and try again.",
      0,
      "network_error",
    );
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const body = payload as ApiErrorBody | null;
    throw new ApiError(
      body?.message ?? "The request could not be completed.",
      response.status,
      body?.error,
      body?.fields,
      typeof body?.reason === "string" ? body.reason : undefined,
    );
  }

  return payload as T;
}

export async function csrfHeaders(): Promise<Record<string, string>> {
  const result = await apiRequest<{ csrf_token: string }>("/auth/csrf", {
    cache: "no-store",
  });
  return { "X-CSRF-Token": result.csrf_token };
}
