export const API_URL =
  process.env.NEXT_PUBLIC_APP_API_URL || "http://localhost:8000/api";

// Backend serves uploads (e.g. avatars) from its origin, not under /api.
export const API_ORIGIN = API_URL.replace(/\/api\/?$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    // Raw parsed JSON body, when the failing response had one — lets callers
    // read structured fields a rejection carries beyond the display message
    // (e.g. RecordingRejectedSchema's appeal_token/appeal_prompt).
    public body?: unknown,
  ) {
    super(message);
  }
}

// Error bodies vary by handler: AppError-based errors (coaching/conversation/
// session-memory/interview-coach) come back as {"status", "message"}; auth/user
// errors as {"error": "..."}; Pydantic validation failures as
// {"error": {"fieldErrors": {...}}} — see Backend/middlewares/error_handler.py.
function extractErrorMessage(data: unknown): string {
  const record = data as {
    error?: unknown;
    detail?: unknown;
    message?: unknown;
  } | null;

  if (typeof record?.message === "string") return record.message;

  const err = record?.error ?? record?.detail;

  if (typeof err === "string") return err;

  if (err && typeof err === "object") {
    const { fieldErrors, formErrors } = err as {
      fieldErrors?: Record<string, string[]>;
      formErrors?: string[];
    };
    const firstFieldError = Object.values(fieldErrors ?? {}).flat()[0];
    if (firstFieldError) return firstFieldError;
    if (formErrors?.[0]) return formErrors[0];
  }

  return "Request failed";
}

// Access tokens are short-lived (30min default) and refresh tokens rotate on
// use — the backend revokes ALL of a user's tokens if a stale/already-used
// refresh token is presented (reuse-detection). So a single in-flight
// refresh call must be shared across every concurrent 401, never one per
// request, or a burst of parallel calls would race each other into that
// revocation path and force-logout the user for no reason.
let refreshPromise: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then((response) => response.ok)
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function api<T>(
  endpoint: string,
  options: RequestInit = {},
  _isRetry = false,
): Promise<T> {
  const isFormData = options.body instanceof FormData;

  const response = await fetch(`${API_URL}${endpoint}`, {
    credentials: "include", // always send auth cookies
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers ?? {}),
    },
    ...options,
  });

  if (!response.ok) {
    // Transparent session restore: an expired (not missing/invalid) access
    // token should refresh silently rather than surface as an error, so a
    // session doesn't die mid-use just because 30 minutes passed. Auth-flow
    // endpoints are excluded — a 401 there means something flow-specific
    // (bad credentials, no refresh cookie yet), not "session expired".
    if (
      response.status === 401 &&
      !_isRetry &&
      !endpoint.startsWith("/auth/")
    ) {
      const refreshed = await refreshSession();
      if (refreshed) {
        return api<T>(endpoint, options, true);
      }
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("speeky:session-expired"));
      }
    }

    const data = await response.json().catch(() => null);
    throw new ApiError(extractErrorMessage(data), response.status, data);
    // throw new ApiError(extractErrorMessage(data), response.status);
  }

  const data = await response.json().catch(() => null);
  return data as T;
}
