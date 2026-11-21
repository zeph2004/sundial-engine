export interface Branding {
  institution_name: string;
  semester_title: string;
  logo_url: string | null;
}

export interface PeriodSlot {
  period: number;
  start: string;
  end: string;
  stream: string;
}

export interface StreamBoundaries {
  full_time_min: number;
  full_time_max: number;
  evening_min: number;
  evening_max: number;
  twilight_periods: number[];
}

export interface GridConfig {
  days: string[];
  periods_per_day: number;
  period_duration_minutes: number;
  periods: PeriodSlot[];
  break_slots: number[];
  stream_boundaries: StreamBoundaries;
}

export interface EntityOption {
  id: string;
  label: string;
}

export interface PublicSession {
  session_id: string;
  module_code: string;
  module_name: string;
  session_type: string;
  day_idx: number;
  day: string;
  start_period: number;
  duration_periods: number;
  venue_id: number | string;
  venue_name: string;
  venue_tier?: string;
  cohorts: string[];
  lecturers: string[];
  is_evening_stream: boolean;
  is_twilight?: boolean;
  is_pinned?: boolean;
  saturday_reason?: string;
}

export interface PublicTimetableResponse {
  branding: Branding;
  grid_config: GridConfig;
  has_timetable: boolean;
  generated_at: string | null;
  entities: {
    cohorts: EntityOption[];
    lecturers: EntityOption[];
    venues: EntityOption[];
  };
  sessions: PublicSession[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface AdminMeResponse {
  authenticated: boolean;
  admin: {
    sub: string;
    role: string;
    iat: number;
    exp: number;
  };
}

export type LensType = "cohort" | "lecturer" | "venue";

const TOKEN_KEY = "sundial_admin_token";

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function logoutAdmin(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(options.headers || {});

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(path, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let detail: unknown = null;
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      detail = data?.detail ?? data;
      if (typeof data?.detail === "string") {
        message = data.detail;
      } else if (typeof data?.message === "string") {
        message = data.message;
      }
    } catch {
      // ignore JSON parse failure on non-JSON error
    }
    throw new ApiError(res.status, message, detail);
  }

  return (await res.json()) as T;
}

export async function getPublicTimetable(): Promise<PublicTimetableResponse> {
  return apiFetch<PublicTimetableResponse>("/api/public/timetable");
}

export async function loginAdmin(
  username: string,
  password: string
): Promise<LoginResponse> {
  const data = await apiFetch<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  setStoredToken(data.access_token);
  return data;
}

export async function getAdminMe(): Promise<AdminMeResponse> {
  return apiFetch<AdminMeResponse>("/api/auth/me");
}
