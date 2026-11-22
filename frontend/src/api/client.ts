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

export interface SchemaPeriodRow {
  period_number: number;
  start_time: string;
  end_time: string;
}

export interface DayOverrideConfig {
  apply_override?: boolean;
  day_active?: boolean;
  blocked_periods?: number[];
  additional_breaks_after_periods?: number[];
  max_period?: number;
  comment?: string;
  [key: string]: unknown;
}

export interface SchemaCalendarGrid {
  active_days: string[];
  periods_per_day: number;
  period_duration_minutes?: number;
  breaks_after_periods: number[];
  enforce_odd_start_alignment_for_multi_period?: boolean;
  periods?: SchemaPeriodRow[];
  day_overrides?: Record<string, DayOverrideConfig>;
  [key: string]: unknown;
}

export interface SchemaStreamConfig {
  is_evening_stream?: boolean;
  min_period: number;
  max_period: number;
  supported_durations: number[];
  allow_stream_boundary_crossing?: boolean;
  twilight_buffer?: {
    enabled: boolean;
    buffer_min_period: number;
    buffer_max_period: number;
    allow_bridge_into_evening?: boolean;
    soft_penalty_weight?: number;
    comment?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface SoftConstraintRuleConfig {
  enabled: boolean;
  weight: number;
  params?: Record<string, unknown>;
}

export interface OptimizerConfig {
  enabled?: boolean;
  max_iterations?: number;
  initial_temperature?: number;
  cooling_rate?: number;
  min_temperature?: number;
  swap_probability?: number;
  guided_proposal_probability?: number;
  random_seed?: number;
  [key: string]: unknown;
}

export interface SessionChunkingRule {
  preferred: number;
  max: number;
}

export interface SessionChunkingConfig {
  min_periods: number;
  by_type: Record<string, SessionChunkingRule>;
  default: SessionChunkingRule;
}

export interface SchemaConfig {
  schema_version?: string;
  institution?: Record<string, unknown>;
  calendar_grid: SchemaCalendarGrid;
  streams: {
    full_time: SchemaStreamConfig;
    evening: SchemaStreamConfig;
    [key: string]: unknown;
  };
  venue_rules: {
    compatibility_map: Record<string, unknown>;
    [key: string]: unknown;
  };
  soft_constraints?: Record<string, SoftConstraintRuleConfig>;
  optimizer?: OptimizerConfig;
  session_chunking?: SessionChunkingConfig;
  [key: string]: unknown;
}

export interface SolveKPIs {
  total_sessions: number;
  assigned_sessions: number;
  backtracks: number;
  hard_violations: number;
  tier1_affinity_pct: number;
  tier1a_exact_pct: number;
  saturday_sessions: number;
  saturday_theory_sessions: number;
  saturday_free_cohorts: number;
  total_cohorts: number;
  saturday_free_cohorts_pct: number;
  evening_twilight_sessions: number;
  objective_improvement_pct: number;
}

export interface SoftObjectiveBreakdown {
  totalObjective: number;
  weightedByRule: Record<string, number>;
  rawByRule: Record<string, number>;
  countsByRule: Record<string, number>;
  weightsByRule: Record<string, number>;
  enabledRules: string[];
}

export interface SolveScorecard {
  enabled: boolean;
  iterations?: number;
  runtimeMs?: number;
  initialObjective?: number;
  finalObjective?: number;
  bestObjective?: number;
  improvementPct?: number;
  acceptedMoves?: number;
  improvingMoves?: number;
  uphillMoves?: number;
  rejectedMoves?: number;
  initialBreakdown?: SoftObjectiveBreakdown;
  finalBreakdown?: SoftObjectiveBreakdown;
}

export interface SaturdayExplanation {
  cohort: string;
  stream: string;
  total_periods: number;
  weekday_limit: number;
  overflow_periods: number;
  saturday_sessions: number;
  reason: string;
}

export interface SolveResponse {
  status: string;
  generated_at: string;
  solve_ms: number;
  optimize_ms: number;
  hard_violations: number;
  kpis: SolveKPIs;
  scorecard: SolveScorecard;
  saturday_explanations: SaturdayExplanation[];
  pinned_count: number;
  timetable: PublicSession[];
}

export interface PinEntry {
  session_id: string;
  day: string;
  day_idx: number;
  start_period: number;
  venue_id: number | string;
}

export interface PinsListResponse {
  pinned_count: number;
  pinned_assignments: Record<string, PinEntry>;
}

export interface PinUpsertResponse {
  status: string;
  pin: PinEntry;
}

export interface PinDeleteResponse {
  status: string;
  session_id: string;
}

export interface ClearPinsResponse {
  status: string;
  cleared_count: number;
}

export interface SettingsResponse {
  branding: Branding;
  schema_config: SchemaConfig;
}

export interface BrandingUpdatePayload {
  institution_name?: string;
  semester_title?: string;
}

export interface BrandingUpdateResponse {
  status: string;
  branding: Branding;
}

export interface LogoUploadResponse {
  status: string;
  filename: string;
  branding: Branding;
}

export interface SchemaUpdateResponse {
  status: string;
  schema_config: SchemaConfig;
}

export type OnboardingEntityKey = "venues" | "lecturers" | "sessions";

export interface OnboardingSourceInfo {
  filename: string;
  row_count: number;
  input_rows?: number;
  mode?: string;
  period_duration_minutes?: number;
  updated_at: string;
  source: "preloaded_atc" | "custom_upload" | string;
}

export interface OnboardingStatusResponse {
  dataset_mode: string;
  entities: {
    venues?: OnboardingSourceInfo;
    lecturers?: OnboardingSourceInfo;
    sessions?: OnboardingSourceInfo;
    affinity?: OnboardingSourceInfo;
    [key: string]: OnboardingSourceInfo | undefined;
  };
}

export interface UploadEntityResponse {
  entity: string;
  mode?: "allocations_hours" | "allocations_periods" | "legacy_sessions" | string;
  input_rows?: number;
  rows_loaded: number;
  period_duration_minutes?: number;
  warnings: string[];
}

export interface PreflightIssue {
  entity: string;
  row: number | null;
  id: string | null;
  code: string;
  message: string;
}

export interface PreflightValidationResponse {
  passed: boolean;
  summary: {
    sessions: number;
    cohorts: number;
    lecturers: number;
    venues: number;
  };
  errors: PreflightIssue[];
  warnings: PreflightIssue[];
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

/* ==========================================================================
   Settings & Branding Endpoints (Sprint 2 / Sprint 4)
   ========================================================================== */

export async function getSettings(): Promise<SettingsResponse> {
  return apiFetch<SettingsResponse>("/api/settings");
}

export async function updateBranding(
  payload: BrandingUpdatePayload
): Promise<BrandingUpdateResponse> {
  return apiFetch<BrandingUpdateResponse>("/api/settings/branding", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function uploadLogo(file: File): Promise<LogoUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<LogoUploadResponse>("/api/settings/logo", {
    method: "POST",
    body: formData,
  });
}

export async function updateSchema(
  schemaConfig: SchemaConfig
): Promise<SchemaUpdateResponse> {
  return apiFetch<SchemaUpdateResponse>("/api/settings/schema", {
    method: "PUT",
    body: JSON.stringify({ schema_config: schemaConfig }),
  });
}

export async function resetSchema(): Promise<SchemaUpdateResponse> {
  return apiFetch<SchemaUpdateResponse>("/api/settings/schema/reset", {
    method: "POST",
  });
}

/* ==========================================================================
   Data Onboarding & Pre-Flight Endpoints (Sprint 2 / Sprint 4)
   ========================================================================== */

export async function getOnboardingStatus(): Promise<OnboardingStatusResponse> {
  return apiFetch<OnboardingStatusResponse>("/api/onboarding/status");
}

export async function downloadTemplate(
  entity: OnboardingEntityKey
): Promise<void> {
  const token = getStoredToken();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`/api/onboarding/templates/${entity}`, {
    method: "GET",
    headers,
  });

  if (!res.ok) {
    let message = `Could not download ${entity} template (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") {
        message = data.detail;
      }
    } catch {
      // ignore non-JSON body
    }
    throw new ApiError(res.status, message);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${entity}_template.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export async function uploadEntityFile(
  entity: OnboardingEntityKey,
  file: File
): Promise<UploadEntityResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<UploadEntityResponse>(`/api/onboarding/upload/${entity}`, {
    method: "POST",
    body: formData,
  });
}

export async function runPreflightValidation(): Promise<PreflightValidationResponse> {
  return apiFetch<PreflightValidationResponse>("/api/onboarding/validate", {
    method: "POST",
  });
}

/* ==========================================================================
   Solver & Session Pinning Endpoints (Sprint 5)
   ========================================================================== */

export async function runSolve(payload?: {
  schema_override?: SchemaConfig | null;
  use_pins?: boolean;
  run_optimizer?: boolean;
  max_iterations?: number;
}): Promise<SolveResponse> {
  return apiFetch<SolveResponse>("/api/solve", {
    method: "POST",
    body: JSON.stringify({
      schema_override: payload?.schema_override ?? null,
      use_pins: payload?.use_pins ?? true,
      run_optimizer: payload?.run_optimizer ?? true,
      ...(payload?.max_iterations !== undefined
        ? { max_iterations: payload.max_iterations }
        : {}),
    }),
  });
}

export async function getPins(): Promise<PinsListResponse> {
  return apiFetch<PinsListResponse>("/api/pins");
}

export async function pinSession(
  sessionId: string,
  payload: { day_idx: number; start_period: number; venue_id: string | number }
): Promise<PinUpsertResponse> {
  return apiFetch<PinUpsertResponse>(
    `/api/pins/${encodeURIComponent(sessionId)}`,
    {
      method: "PUT",
      body: JSON.stringify({
        day: payload.day_idx,
        start_period: payload.start_period,
        venue_id: payload.venue_id,
      }),
    }
  );
}

export async function unpinSession(
  sessionId: string
): Promise<PinDeleteResponse> {
  return apiFetch<PinDeleteResponse>(
    `/api/pins/${encodeURIComponent(sessionId)}`,
    {
      method: "DELETE",
    }
  );
}

export async function clearAllPins(): Promise<ClearPinsResponse> {
  return apiFetch<ClearPinsResponse>("/api/pins", {
    method: "DELETE",
  });
}

/* ==========================================================================
   Noticeboard PDF Export Endpoints (Sprint 6)
   ========================================================================== */

export function getPublicPdfUrl(lens: LensType, entityId: string): string {
  return `/api/public/export/pdf?lens=${encodeURIComponent(lens)}&id=${encodeURIComponent(entityId)}`;
}

export async function downloadMasterPdf(lens: LensType): Promise<void> {
  const token = getStoredToken();
  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(
    `/api/export/master-pdf?lens=${encodeURIComponent(lens)}`,
    {
      method: "GET",
      headers,
    }
  );

  if (!res.ok) {
    let message = `Could not generate master ${lens} PDF (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") {
        message = data.detail;
      }
    } catch {
      // ignore non-JSON body
    }
    throw new ApiError(res.status, message);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `master_${lens}_timetables.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
