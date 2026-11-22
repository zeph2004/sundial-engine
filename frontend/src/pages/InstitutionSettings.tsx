import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Image as ImageIcon,
  Plus,
  RotateCcw,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import {
  ApiError,
  getSettings,
  resetSchema,
  updateBranding,
  updateSchema,
  uploadLogo,
  type Branding,
  type PeriodSlot,
  type SchemaConfig,
  type SchemaPeriodRow,
} from "../api/client";

const ALL_DAYS = [
  "MONDAY",
  "TUESDAY",
  "WEDNESDAY",
  "THURSDAY",
  "FRIDAY",
  "SATURDAY",
] as const;

const DAY_LABELS: Record<string, string> = {
  MONDAY: "Monday",
  TUESDAY: "Tuesday",
  WEDNESDAY: "Wednesday",
  THURSDAY: "Thursday",
  FRIDAY: "Friday",
  SATURDAY: "Saturday",
};

const MAX_LOGO_BYTES = 2 * 1024 * 1024;

type SaturdayPolicy = "fallback" | "half_day" | "weekdays_only";

export interface InstitutionSettingsProps {
  initialPeriods?: PeriodSlot[];
  logoCacheKey: number;
  onBrandingUpdated: (branding: Branding, nextLogoCacheKey: number) => void;
  onSchemaUpdated?: () => void;
}

function addMinutesToHHMM(hhmm: string, minutes: number): string {
  const match = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!match) return "07:30";
  const total = Number(match[1]) * 60 + Number(match[2]) + minutes;
  const wrapped = ((total % 1440) + 1440) % 1440;
  const h = Math.floor(wrapped / 60);
  const m = wrapped % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function buildPeriodRows(
  schema: SchemaConfig,
  fallbackPeriods: PeriodSlot[] = []
): SchemaPeriodRow[] {
  const count = Math.max(1, schema.calendar_grid?.periods_per_day || 18);
  const duration = schema.calendar_grid?.period_duration_minutes || 45;
  const stored = schema.calendar_grid?.periods;

  const fallbackMap = new Map<number, { start: string; end: string }>();
  for (const p of fallbackPeriods) {
    fallbackMap.set(p.period, { start: p.start, end: p.end });
  }
  const storedMap = new Map<number, { start: string; end: string }>();
  if (Array.isArray(stored)) {
    for (const p of stored) {
      storedMap.set(p.period_number, {
        start: p.start_time,
        end: p.end_time,
      });
    }
  }

  const rows: SchemaPeriodRow[] = [];
  let cursor = "07:30";
  for (let i = 1; i <= count; i++) {
    const fromStored = storedMap.get(i);
    const fromFallback = fallbackMap.get(i);
    if (fromStored) {
      rows.push({
        period_number: i,
        start_time: fromStored.start,
        end_time: fromStored.end,
      });
      cursor = fromStored.end;
    } else if (fromFallback) {
      rows.push({
        period_number: i,
        start_time: fromFallback.start,
        end_time: fromFallback.end,
      });
      cursor = fromFallback.end;
    } else {
      const start = cursor;
      const end = addMinutesToHHMM(start, duration);
      rows.push({
        period_number: i,
        start_time: start,
        end_time: end,
      });
      cursor = end;
    }
  }
  return rows;
}

function deriveSaturdayPolicy(schema: SchemaConfig): {
  policy: SaturdayPolicy;
  halfDayMax: number;
} {
  const activeDays = schema.calendar_grid?.active_days || [];
  const satOverride = schema.calendar_grid?.day_overrides?.SATURDAY;
  const hasSaturday = activeDays.includes("SATURDAY");
  const halfDayMax =
    typeof satOverride?.max_period === "number" && satOverride.max_period > 0
      ? satOverride.max_period
      : 6;

  if (!hasSaturday || (satOverride?.apply_override && satOverride?.day_active === false)) {
    return { policy: "weekdays_only", halfDayMax };
  }
  if (satOverride?.apply_override && satOverride?.day_active !== false) {
    return { policy: "half_day", halfDayMax };
  }
  return { policy: "fallback", halfDayMax };
}

export const InstitutionSettings: React.FC<InstitutionSettingsProps> = ({
  initialPeriods = [],
  logoCacheKey,
  onBrandingUpdated,
  onSchemaUpdated,
}) => {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Branding state
  const [institutionName, setInstitutionName] = useState("");
  const [semesterTitle, setSemesterTitle] = useState("");
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [logoBroken, setLogoBroken] = useState(false);
  const [savingBranding, setSavingBranding] = useState(false);
  const [brandingFeedback, setBrandingFeedback] = useState<{
    type: "clear" | "clash";
    text: string;
  } | null>(null);

  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [logoFeedback, setLogoFeedback] = useState<{
    type: "clear" | "clash";
    text: string;
  } | null>(null);
  const logoInputRef = useRef<HTMLInputElement | null>(null);

  // Schema state (keep full baseSchema so soft_constraints & optimizer stay untouched)
  const [baseSchema, setBaseSchema] = useState<SchemaConfig | null>(null);
  const [activeDays, setActiveDays] = useState<string[]>([
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
  ]);
  const [satPolicy, setSatPolicy] = useState<SaturdayPolicy>("fallback");
  const [satHalfDayMax, setSatHalfDayMax] = useState<number>(6);
  const [periodDuration, setPeriodDuration] = useState<number>(45);
  const [periods, setPeriods] = useState<SchemaPeriodRow[]>([]);
  const [breakSlots, setBreakSlots] = useState<number[]>([4, 6]);

  // Stream boundaries
  const [ftMin, setFtMin] = useState<number>(1);
  const [ftMax, setFtMax] = useState<number>(12);
  const [eveMin, setEveMin] = useState<number>(13);
  const [eveMax, setEveMax] = useState<number>(18);
  const [twilightEnabled, setTwilightEnabled] = useState<boolean>(true);
  const [twilightMin, setTwilightMin] = useState<number>(11);
  const [twilightMax, setTwilightMax] = useState<number>(12);

  // Session Block Sizing (Auto-Chunker) state
  const [chunkMinPeriods, setChunkMinPeriods] = useState<number>(2);
  const [chunkDefaultPref, setChunkDefaultPref] = useState<number>(2);
  const [chunkDefaultMax, setChunkDefaultMax] = useState<number>(3);
  const [chunkTypeRows, setChunkTypeRows] = useState<
    Array<{ id: number; type: string; preferred: number; max: number }>
  >([
    { id: 1, type: "Theory", preferred: 2, max: 2 },
    { id: 2, type: "Tutorial", preferred: 1, max: 2 },
    { id: 3, type: "Lab", preferred: 3, max: 4 },
    { id: 4, type: "Workshop", preferred: 4, max: 4 },
  ]);
  const nextChunkRowId = useRef(10);

  // Schema save / reset feedback
  const [savingSchema, setSavingSchema] = useState(false);
  const [resettingSchema, setResettingSchema] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [schemaSuccess, setSchemaSuccess] = useState<string | null>(null);
  const [schemaErrors, setSchemaErrors] = useState<string[]>([]);

  const hydrateFromSchema = (schema: SchemaConfig) => {
    setBaseSchema(schema);
    setActiveDays(
      Array.isArray(schema.calendar_grid?.active_days)
        ? [...schema.calendar_grid.active_days]
        : [...ALL_DAYS]
    );
    const derivedSat = deriveSaturdayPolicy(schema);
    setSatPolicy(derivedSat.policy);
    setSatHalfDayMax(derivedSat.halfDayMax);
    setPeriodDuration(schema.calendar_grid?.period_duration_minutes || 45);
    setPeriods(buildPeriodRows(schema, initialPeriods));
    setBreakSlots(
      Array.isArray(schema.calendar_grid?.breaks_after_periods)
        ? [...schema.calendar_grid.breaks_after_periods]
        : [4, 6]
    );

    const ft = schema.streams?.full_time;
    const eve = schema.streams?.evening;
    const twi = eve?.twilight_buffer;
    setFtMin(ft?.min_period ?? 1);
    setFtMax(ft?.max_period ?? 12);
    setEveMin(eve?.min_period ?? 13);
    setEveMax(eve?.max_period ?? 18);
    setTwilightEnabled(twi?.enabled ?? true);
    setTwilightMin(twi?.buffer_min_period ?? 11);
    setTwilightMax(twi?.buffer_max_period ?? 12);

    const sc = schema.session_chunking;
    setChunkMinPeriods(sc?.min_periods ?? 2);
    setChunkDefaultPref(sc?.default?.preferred ?? 2);
    setChunkDefaultMax(sc?.default?.max ?? 3);
    const entries = Object.entries(
      sc?.by_type || {
        Theory: { preferred: 2, max: 2 },
        Tutorial: { preferred: 1, max: 2 },
        Lab: { preferred: 3, max: 4 },
        Workshop: { preferred: 4, max: 4 },
      }
    );
    setChunkTypeRows(
      entries.map(([type, rule], idx) => ({
        id: idx + 1,
        type,
        preferred: rule.preferred ?? 2,
        max: rule.max ?? 3,
      }))
    );
    nextChunkRowId.current = entries.length + 10;
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    getSettings()
      .then((res) => {
        if (!active) return;
        setInstitutionName(res.branding.institution_name || "");
        setSemesterTitle(res.branding.semester_title || "");
        setLogoUrl(res.branding.logo_url);
        setLogoBroken(false);
        hydrateFromSchema(res.schema_config);
        setLoadError(null);
      })
      .catch((err) => {
        if (!active) return;
        setLoadError(
          err instanceof Error
            ? err.message
            : "Could not load institution settings."
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const breakSet = useMemo(() => new Set(breakSlots), [breakSlots]);

  const handleSaveBranding = async (e: React.FormEvent) => {
    e.preventDefault();
    setBrandingFeedback(null);
    if (!institutionName.trim() || !semesterTitle.trim()) {
      setBrandingFeedback({
        type: "clash",
        text: "Institution name and semester title cannot be empty.",
      });
      return;
    }

    setSavingBranding(true);
    try {
      const res = await updateBranding({
        institution_name: institutionName.trim(),
        semester_title: semesterTitle.trim(),
      });
      setInstitutionName(res.branding.institution_name);
      setSemesterTitle(res.branding.semester_title);
      setLogoUrl(res.branding.logo_url);
      onBrandingUpdated(res.branding, logoCacheKey);
      setBrandingFeedback({
        type: "clear",
        text: "Branding saved. Header and public timetable view updated.",
      });
    } catch (err) {
      setBrandingFeedback({
        type: "clash",
        text:
          err instanceof Error ? err.message : "Could not save branding.",
      });
    } finally {
      setSavingBranding(false);
    }
  };

  const handleLogoFileChange = async (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLogoFeedback(null);

    if (file.size > MAX_LOGO_BYTES) {
      setLogoFeedback({
        type: "clash",
        text: "Logo exceeds 2 MB. Choose a smaller PNG, JPG, SVG, or WEBP file.",
      });
      e.target.value = "";
      return;
    }

    setUploadingLogo(true);
    try {
      const res = await uploadLogo(file);
      const nextKey = Date.now();
      setLogoUrl(res.branding.logo_url);
      setLogoBroken(false);
      onBrandingUpdated(res.branding, nextKey);
      setLogoFeedback({
        type: "clear",
        text: `Uploaded ${res.filename}. Logo preview updated.`,
      });
    } catch (err) {
      setLogoFeedback({
        type: "clash",
        text: err instanceof Error ? err.message : "Logo upload failed.",
      });
    } finally {
      setUploadingLogo(false);
      e.target.value = "";
    }
  };

  const toggleDay = (day: string) => {
    setSchemaSuccess(null);
    setSchemaErrors([]);
    setActiveDays((prev) => {
      const exists = prev.includes(day);
      const next = exists
        ? prev.filter((d) => d !== day)
        : ALL_DAYS.filter((d) => prev.includes(d) || d === day);

      if (day === "SATURDAY") {
        setSatPolicy(exists ? "weekdays_only" : "fallback");
      }
      return next;
    });
  };

  const handleSatPolicyChange = (nextPolicy: SaturdayPolicy) => {
    setSchemaSuccess(null);
    setSchemaErrors([]);
    setSatPolicy(nextPolicy);
    if (nextPolicy === "weekdays_only") {
      setActiveDays((prev) => prev.filter((d) => d !== "SATURDAY"));
    } else {
      setActiveDays((prev) =>
        prev.includes("SATURDAY")
          ? prev
          : ALL_DAYS.filter((d) => prev.includes(d) || d === "SATURDAY")
      );
    }
  };

  const toggleBreakAfter = (periodNum: number) => {
    setSchemaSuccess(null);
    setBreakSlots((prev) =>
      prev.includes(periodNum)
        ? prev.filter((p) => p !== periodNum)
        : [...prev, periodNum].sort((a, b) => a - b)
    );
  };

  const updatePeriodField = (
    periodNum: number,
    field: "start_time" | "end_time",
    value: string
  ) => {
    setSchemaSuccess(null);
    setPeriods((prev) =>
      prev.map((row) =>
        row.period_number === periodNum ? { ...row, [field]: value } : row
      )
    );
  };

  const handleAddPeriod = () => {
    setSchemaSuccess(null);
    setSchemaErrors([]);
    setPeriods((prev) => {
      const nextNum = prev.length + 1;
      const prevEnd = prev.length > 0 ? prev[prev.length - 1].end_time : "07:30";
      const nextEnd = addMinutesToHHMM(prevEnd, periodDuration || 45);
      return [
        ...prev,
        {
          period_number: nextNum,
          start_time: prevEnd,
          end_time: nextEnd,
        },
      ];
    });
  };

  const handleRemovePeriod = (periodNum: number) => {
    if (periods.length <= 1) return;
    setSchemaSuccess(null);
    setSchemaErrors([]);
    setPeriods((prev) => {
      const filtered = prev.filter((p) => p.period_number !== periodNum);
      return filtered.map((p, idx) => ({
        ...p,
        period_number: idx + 1,
      }));
    });
    setBreakSlots((prev) =>
      prev
        .filter((b) => b !== periodNum)
        .map((b) => (b > periodNum ? b - 1 : b))
    );
  };

  const getStreamBadge = (pNum: number): { label: string; cls: string } => {
    if (twilightEnabled && pNum >= twilightMin && pNum <= twilightMax) {
      return { label: "Twilight", cls: "badge-twilight" };
    }
    if (pNum >= eveMin && pNum <= eveMax) {
      return { label: "Evening", cls: "badge-evening" };
    }
    if (pNum >= ftMin && pNum <= ftMax) {
      return { label: "Full-Time", cls: "badge-ft" };
    }
    return { label: "Unassigned", cls: "badge-neutral" };
  };

  const handleSaveSchema = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!baseSchema) return;

    setSchemaSuccess(null);
    setSchemaErrors([]);

    const clientErrors: string[] = [];
    if (activeDays.length === 0) {
      clientErrors.push("Select at least one active teaching day.");
    }
    if (periods.length < 1 || periods.length > 30) {
      clientErrors.push("Period grid must contain between 1 and 30 periods.");
    }
    if (ftMin < 1 || ftMax < ftMin) {
      clientErrors.push(
        "Full-Time stream start period must be >= 1 and <= end period."
      );
    }
    if (eveMin < 1 || eveMax < eveMin) {
      clientErrors.push(
        "Evening stream start period must be >= 1 and <= end period."
      );
    }
    if (twilightEnabled && (twilightMin < 1 || twilightMax < twilightMin)) {
      clientErrors.push(
        "Twilight buffer start period must be >= 1 and <= end period."
      );
    }
    if (chunkMinPeriods < 1) {
      clientErrors.push("Session chunking minimum block size must be >= 1.");
    }
    if (chunkDefaultPref < 1 || chunkDefaultMax < chunkDefaultPref) {
      clientErrors.push(
        "Session chunking fallback default max must be >= preferred (>= 1)."
      );
    }
    const byTypeMap: Record<string, { preferred: number; max: number }> = {};
    for (const row of chunkTypeRows) {
      const label = row.type.trim();
      if (!label) {
        clientErrors.push("Every session block sizing row must have a session type name.");
        break;
      }
      if (row.preferred < 1 || row.max < row.preferred) {
        clientErrors.push(
          `Session type '${label}': max periods (${row.max}) must be >= preferred (${row.preferred}).`
        );
      }
      byTypeMap[label] = {
        preferred: row.preferred,
        max: row.max,
      };
    }

    if (clientErrors.length > 0) {
      setSchemaErrors(clientErrors);
      return;
    }

    const existingOverrides = baseSchema.calendar_grid?.day_overrides || {};
    const existingSat = existingOverrides.SATURDAY || {};

    const updatedSatOverride =
      satPolicy === "fallback"
        ? {
            ...existingSat,
            apply_override: false,
            day_active: true,
            max_period: satHalfDayMax,
          }
        : satPolicy === "half_day"
          ? {
              ...existingSat,
              apply_override: true,
              day_active: true,
              max_period: satHalfDayMax,
            }
          : {
              ...existingSat,
              apply_override: true,
              day_active: false,
              max_period: 0,
            };

    // Preserve soft_constraints, optimizer, venue_rules, and all other keys untouched
    const nextSchema: SchemaConfig = {
      ...baseSchema,
      calendar_grid: {
        ...baseSchema.calendar_grid,
        active_days: activeDays,
        periods_per_day: periods.length,
        period_duration_minutes: periodDuration,
        breaks_after_periods: breakSlots
          .filter((b) => b >= 1 && b < periods.length)
          .sort((a, b) => a - b),
        periods,
        day_overrides: {
          ...existingOverrides,
          SATURDAY: updatedSatOverride,
        },
      },
      streams: {
        ...baseSchema.streams,
        full_time: {
          ...baseSchema.streams.full_time,
          min_period: ftMin,
          max_period: ftMax,
        },
        evening: {
          ...baseSchema.streams.evening,
          min_period: eveMin,
          max_period: eveMax,
          twilight_buffer: {
            ...(baseSchema.streams.evening.twilight_buffer || {}),
            enabled: twilightEnabled,
            buffer_min_period: twilightMin,
            buffer_max_period: twilightMax,
          },
        },
      },
      session_chunking: {
        min_periods: chunkMinPeriods,
        by_type: byTypeMap,
        default: {
          preferred: chunkDefaultPref,
          max: chunkDefaultMax,
        },
      },
    };

    setSavingSchema(true);
    try {
      const res = await updateSchema(nextSchema);
      hydrateFromSchema(res.schema_config);
      setSchemaSuccess(
        `Clock and stream rules saved (${res.schema_config.calendar_grid.active_days.length} active days, ${res.schema_config.calendar_grid.periods_per_day} periods/day).`
      );
      onSchemaUpdated?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        const parts = err.message
          .split(";")
          .map((s) => s.trim())
          .filter(Boolean);
        setSchemaErrors(parts.length > 0 ? parts : [err.message]);
      } else {
        setSchemaErrors([
          err instanceof Error
            ? err.message
            : "Could not save clock and stream rules.",
        ]);
      }
    } finally {
      setSavingSchema(false);
    }
  };

  const handleConfirmReset = async () => {
    setResettingSchema(true);
    setSchemaSuccess(null);
    setSchemaErrors([]);
    try {
      const res = await resetSchema();
      hydrateFromSchema(res.schema_config);
      setConfirmReset(false);
      setSchemaSuccess("Default institution schema restored (18 periods, Mon–Sat fallback).");
      onSchemaUpdated?.();
    } catch (err) {
      setSchemaErrors([
        err instanceof Error
          ? err.message
          : "Could not reset schema to defaults.",
      ]);
    } finally {
      setResettingSchema(false);
    }
  };

  if (loading) {
    return (
      <div className="status-panel">Loading institution settings...</div>
    );
  }

  if (loadError) {
    return (
      <div className="status-panel status-error">
        <strong>Could not load settings.</strong> {loadError}
      </div>
    );
  }

  return (
    <div className="settings-page">
      <div className="studio-panel-head">
        <div>
          <h2>Institution settings</h2>
          <p>
            Configure official branding, teaching days, period clock, break
            slots, and stream boundaries.
          </p>
        </div>
      </div>

      {/* Section A: Official Branding & Identity */}
      <section className="studio-card">
        <div className="studio-card-head">
          <div>
            <h3>Official branding &amp; identity</h3>
            <p>
              Displayed on the Studio header, public timetable lookup, and
              printed A4 sheets.
            </p>
          </div>
        </div>

        <div className="branding-grid">
          <form className="branding-form" onSubmit={handleSaveBranding}>
            <label className="field-label">
              Institution name
              <input
                type="text"
                className="field-input"
                value={institutionName}
                onChange={(e) => {
                  setInstitutionName(e.target.value);
                  setBrandingFeedback(null);
                }}
                placeholder="e.g. Arusha Technical College"
                required
              />
            </label>

            <label className="field-label">
              Semester title
              <input
                type="text"
                className="field-input"
                value={semesterTitle}
                onChange={(e) => {
                  setSemesterTitle(e.target.value);
                  setBrandingFeedback(null);
                }}
                placeholder="e.g. Academic Year 2026/27 — Semester 1"
                required
              />
            </label>

            {brandingFeedback && (
              <div
                className={`inline-alert ${
                  brandingFeedback.type === "clear"
                    ? "alert-clear"
                    : "alert-clash"
                }`}
                role="status"
              >
                {brandingFeedback.type === "clear" ? (
                  <CheckCircle2 size={15} />
                ) : (
                  <AlertCircle size={15} />
                )}
                <span>{brandingFeedback.text}</span>
              </div>
            )}

            <div className="card-actions-row">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={savingBranding}
              >
                <Save size={15} />
                <span>{savingBranding ? "Saving..." : "Save branding"}</span>
              </button>
            </div>
          </form>

          <div className="logo-panel">
            <div className="field-label" style={{ marginBottom: 8 }}>
              Institution logo
            </div>
            <div className="logo-preview-box">
              {logoUrl && !logoBroken ? (
                <img
                  src={`${logoUrl}?v=${logoCacheKey}`}
                  alt={`${institutionName || "Institution"} logo`}
                  className="logo-preview-img"
                  onError={() => setLogoBroken(true)}
                />
              ) : (
                <div className="logo-empty-state">
                  <ImageIcon size={22} strokeWidth={1.5} />
                  <span>No logo uploaded</span>
                </div>
              )}
            </div>

            <input
              ref={logoInputRef}
              type="file"
              accept=".png,.jpg,.jpeg,.svg,.webp,image/png,image/jpeg,image/svg+xml,image/webp"
              onChange={handleLogoFileChange}
              className="sr-only"
              aria-label="Upload institution logo"
            />

            <button
              type="button"
              className="btn btn-secondary btn-full"
              disabled={uploadingLogo}
              onClick={() => logoInputRef.current?.click()}
            >
              <Upload size={15} />
              <span>
                {uploadingLogo ? "Uploading logo..." : "Upload logo"}
              </span>
            </button>
            <p className="field-hint">PNG, JPG, SVG, or WEBP. Maximum 2 MB.</p>

            {logoFeedback && (
              <div
                className={`inline-alert ${
                  logoFeedback.type === "clear" ? "alert-clear" : "alert-clash"
                }`}
                role="status"
                style={{ marginTop: 10, marginBottom: 0 }}
              >
                {logoFeedback.type === "clear" ? (
                  <CheckCircle2 size={15} />
                ) : (
                  <AlertCircle size={15} />
                )}
                <span>{logoFeedback.text}</span>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Section B: University Clock, Breaks & Stream Rules */}
      <section className="studio-card">
        <div className="studio-card-head">
          <div>
            <h3>University clock, breaks &amp; stream rules</h3>
            <p>
              Defines the weekly timetable grid. Soft constraint weights and
              optimiser settings are preserved unchanged.
            </p>
          </div>
          <span className="mono-chip">
            <Clock size={13} />
            {activeDays.length} days · {periods.length} periods/day
          </span>
        </div>

        <form onSubmit={handleSaveSchema} className="schema-form">
          {/* Active Days & Saturday Policy */}
          <div className="schema-subsection">
            <h4 className="subsection-title">Active teaching days</h4>
            <div className="day-checkbox-row">
              {ALL_DAYS.map((day) => {
                const checked = activeDays.includes(day);
                return (
                  <label
                    key={day}
                    className={`day-pill ${checked ? "is-checked" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleDay(day)}
                    />
                    <span>{DAY_LABELS[day]}</span>
                  </label>
                );
              })}
            </div>

            <div className="saturday-policy-box">
              <div className="saturday-policy-head">
                <strong>2-Condition Saturday Fallback Policy</strong>
                <span>
                  Controls how Saturday slots are used when weekly load exceeds
                  Monday–Friday capacity.
                </span>
              </div>
              <div className="policy-options">
                <label
                  className={`policy-option ${
                    satPolicy === "fallback" ? "is-selected" : ""
                  }`}
                >
                  <input
                    type="radio"
                    name="satPolicy"
                    checked={satPolicy === "fallback"}
                    onChange={() => handleSatPolicyChange("fallback")}
                  />
                  <div>
                    <div className="policy-title">
                      2-Condition Fallback (Mon–Fri default)
                    </div>
                    <div className="policy-desc">
                      Places sessions Mon–Fri first; opens Saturday only when
                      cohort or venue numbers require it.
                    </div>
                  </div>
                </label>

                <label
                  className={`policy-option ${
                    satPolicy === "half_day" ? "is-selected" : ""
                  }`}
                >
                  <input
                    type="radio"
                    name="satPolicy"
                    checked={satPolicy === "half_day"}
                    onChange={() => handleSatPolicyChange("half_day")}
                  />
                  <div>
                    <div className="policy-title">Half-day Saturday cap</div>
                    <div className="policy-desc">
                      Limits Saturday placements to morning periods only.
                    </div>
                    {satPolicy === "half_day" && (
                      <div className="inline-num-field">
                        <span>Max Saturday period:</span>
                        <input
                          type="number"
                          min={1}
                          max={periods.length}
                          value={satHalfDayMax}
                          onChange={(e) =>
                            setSatHalfDayMax(
                              Math.max(1, Number(e.target.value) || 1)
                            )
                          }
                          className="field-input field-input-sm mono-num"
                        />
                      </div>
                    )}
                  </div>
                </label>

                <label
                  className={`policy-option ${
                    satPolicy === "weekdays_only" ? "is-selected" : ""
                  }`}
                >
                  <input
                    type="radio"
                    name="satPolicy"
                    checked={satPolicy === "weekdays_only"}
                    onChange={() => handleSatPolicyChange("weekdays_only")}
                  />
                  <div>
                    <div className="policy-title">Monday–Friday only</div>
                    <div className="policy-desc">
                      Disables Saturday completely across all streams.
                    </div>
                  </div>
                </label>
              </div>
            </div>
          </div>

          {/* Stream Boundaries */}
          <div className="schema-subsection">
            <h4 className="subsection-title">Stream boundaries</h4>
            <div className="stream-bounds-grid">
              <div className="stream-box stream-box-ft">
                <div className="stream-box-title">Full-Time stream</div>
                <div className="stream-pair">
                  <label className="field-label">
                    Start period
                    <input
                      type="number"
                      min={1}
                      max={30}
                      className="field-input mono-num"
                      value={ftMin}
                      onChange={(e) => setFtMin(Number(e.target.value) || 1)}
                    />
                  </label>
                  <label className="field-label">
                    End period
                    <input
                      type="number"
                      min={1}
                      max={30}
                      className="field-input mono-num"
                      value={ftMax}
                      onChange={(e) => setFtMax(Number(e.target.value) || 1)}
                    />
                  </label>
                </div>
              </div>

              <div className="stream-box stream-box-eve">
                <div className="stream-box-title">Evening stream</div>
                <div className="stream-pair">
                  <label className="field-label">
                    Start period
                    <input
                      type="number"
                      min={1}
                      max={30}
                      className="field-input mono-num"
                      value={eveMin}
                      onChange={(e) => setEveMin(Number(e.target.value) || 1)}
                    />
                  </label>
                  <label className="field-label">
                    End period
                    <input
                      type="number"
                      min={1}
                      max={30}
                      className="field-input mono-num"
                      value={eveMax}
                      onChange={(e) => setEveMax(Number(e.target.value) || 1)}
                    />
                  </label>
                </div>
              </div>

              <div className="stream-box">
                <div className="stream-box-head-row">
                  <div className="stream-box-title">Twilight buffer</div>
                  <label className="inline-check">
                    <input
                      type="checkbox"
                      checked={twilightEnabled}
                      onChange={(e) => setTwilightEnabled(e.target.checked)}
                    />
                    <span>Enabled</span>
                  </label>
                </div>
                <div className="stream-pair">
                  <label className="field-label">
                    Buffer start
                    <input
                      type="number"
                      min={1}
                      max={30}
                      className="field-input mono-num"
                      value={twilightMin}
                      disabled={!twilightEnabled}
                      onChange={(e) =>
                        setTwilightMin(Number(e.target.value) || 1)
                      }
                    />
                  </label>
                  <label className="field-label">
                    Buffer end
                    <input
                      type="number"
                      min={1}
                      max={30}
                      className="field-input mono-num"
                      value={twilightMax}
                      disabled={!twilightEnabled}
                      onChange={(e) =>
                        setTwilightMax(Number(e.target.value) || 1)
                      }
                    />
                  </label>
                </div>
              </div>
            </div>
          </div>

          {/* Session Block Sizing (Auto-Chunker) */}
          <div className="schema-subsection">
            <div className="subsection-head-row">
              <div>
                <h4 className="subsection-title" style={{ marginBottom: 2 }}>
                  Session block sizing (Auto-Chunker)
                </h4>
                <p className="field-hint" style={{ margin: 0 }}>
                  Controls how weekly hours uploaded in Data Onboarding are
                  split into teaching blocks per session type.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setSchemaSuccess(null);
                  setChunkTypeRows((prev) => [
                    ...prev,
                    {
                      id: nextChunkRowId.current++,
                      type: "",
                      preferred: chunkDefaultPref,
                      max: chunkDefaultMax,
                    },
                  ]);
                }}
              >
                <Plus size={15} />
                <span>Add session type</span>
              </button>
            </div>

            <div className="stream-bounds-grid">
              <div className="stream-box">
                <div className="stream-box-title">Minimum block size</div>
                <label className="field-label">
                  Min periods
                  <input
                    type="number"
                    min={1}
                    max={12}
                    className="field-input mono-num"
                    value={chunkMinPeriods}
                    onChange={(e) => {
                      setSchemaSuccess(null);
                      setChunkMinPeriods(Math.max(1, Number(e.target.value) || 1));
                    }}
                  />
                </label>
              </div>

              <div className="stream-box" style={{ gridColumn: "span 2" }}>
                <div className="stream-box-title">
                  Fallback default (unlisted session types)
                </div>
                <div className="stream-pair">
                  <label className="field-label">
                    Preferred periods
                    <input
                      type="number"
                      min={1}
                      max={12}
                      className="field-input mono-num"
                      value={chunkDefaultPref}
                      onChange={(e) => {
                        setSchemaSuccess(null);
                        setChunkDefaultPref(Math.max(1, Number(e.target.value) || 1));
                      }}
                    />
                  </label>
                  <label className="field-label">
                    Max periods
                    <input
                      type="number"
                      min={1}
                      max={12}
                      className="field-input mono-num"
                      value={chunkDefaultMax}
                      onChange={(e) => {
                        setSchemaSuccess(null);
                        setChunkDefaultMax(Math.max(1, Number(e.target.value) || 1));
                      }}
                    />
                  </label>
                </div>
              </div>
            </div>

            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Session type</th>
                    <th style={{ width: 160 }}>Preferred periods</th>
                    <th style={{ width: 160 }}>Max periods</th>
                    <th style={{ width: 70, textAlign: "right" }}>Remove</th>
                  </tr>
                </thead>
                <tbody>
                  {chunkTypeRows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <input
                          type="text"
                          className="table-input"
                          style={{ width: "100%", maxWidth: 260 }}
                          placeholder="e.g. Studio, Seminar, Clinical"
                          value={row.type}
                          onChange={(e) => {
                            setSchemaSuccess(null);
                            const val = e.target.value;
                            setChunkTypeRows((prev) =>
                              prev.map((r) =>
                                r.id === row.id ? { ...r, type: val } : r
                              )
                            );
                          }}
                          aria-label="Session type name"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min={1}
                          max={12}
                          className="table-input mono-num"
                          value={row.preferred}
                          onChange={(e) => {
                            setSchemaSuccess(null);
                            const val = Math.max(1, Number(e.target.value) || 1);
                            setChunkTypeRows((prev) =>
                              prev.map((r) =>
                                r.id === row.id ? { ...r, preferred: val } : r
                              )
                            );
                          }}
                          aria-label={`${row.type || "Session type"} preferred periods`}
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          min={1}
                          max={12}
                          className="table-input mono-num"
                          value={row.max}
                          onChange={(e) => {
                            setSchemaSuccess(null);
                            const val = Math.max(1, Number(e.target.value) || 1);
                            setChunkTypeRows((prev) =>
                              prev.map((r) =>
                                r.id === row.id ? { ...r, max: val } : r
                              )
                            );
                          }}
                          aria-label={`${row.type || "Session type"} max periods`}
                        />
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="icon-btn"
                          title={`Remove ${row.type || "row"}`}
                          aria-label={`Remove ${row.type || "row"}`}
                          onClick={() => {
                            setSchemaSuccess(null);
                            setChunkTypeRows((prev) =>
                              prev.filter((r) => r.id !== row.id)
                            );
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Period Grid Table */}
          <div className="schema-subsection">
            <div className="subsection-head-row">
              <div>
                <h4 className="subsection-title" style={{ marginBottom: 2 }}>
                  Period grid &amp; break slots
                </h4>
                <p className="field-hint" style={{ margin: 0 }}>
                  Mark breaks after periods (for example, Tea Break after P4 and
                  Lunch Break after P6). Sessions cannot span across a break.
                </p>
              </div>
              <div className="period-controls-right">
                <label className="inline-num-field">
                  <span>Minutes / period:</span>
                  <input
                    type="number"
                    min={15}
                    max={180}
                    className="field-input field-input-sm mono-num"
                    value={periodDuration}
                    onChange={(e) =>
                      setPeriodDuration(Math.max(15, Number(e.target.value) || 45))
                    }
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleAddPeriod}
                  disabled={periods.length >= 30}
                >
                  <Plus size={15} />
                  <span>Add period</span>
                </button>
              </div>
            </div>

            <div className="data-table-wrap period-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: 90 }}>Period</th>
                    <th style={{ width: 150 }}>Start time</th>
                    <th style={{ width: 150 }}>End time</th>
                    <th style={{ width: 130 }}>Stream</th>
                    <th>Break after period</th>
                    <th style={{ width: 70, textAlign: "right" }}>Remove</th>
                  </tr>
                </thead>
                <tbody>
                  {periods.map((row) => {
                    const isBreak = breakSet.has(row.period_number);
                    const badge = getStreamBadge(row.period_number);
                    return (
                      <tr key={row.period_number}>
                        <td className="mono-cell">P{row.period_number}</td>
                        <td>
                          <input
                            type="text"
                            className="table-input mono-num"
                            value={row.start_time}
                            onChange={(e) =>
                              updatePeriodField(
                                row.period_number,
                                "start_time",
                                e.target.value
                              )
                            }
                            aria-label={`Period ${row.period_number} start time`}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className="table-input mono-num"
                            value={row.end_time}
                            onChange={(e) =>
                              updatePeriodField(
                                row.period_number,
                                "end_time",
                                e.target.value
                              )
                            }
                            aria-label={`Period ${row.period_number} end time`}
                          />
                        </td>
                        <td>
                          <span className={`stream-pill ${badge.cls}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td>
                          <label className="inline-check">
                            <input
                              type="checkbox"
                              checked={isBreak}
                              onChange={() =>
                                toggleBreakAfter(row.period_number)
                              }
                            />
                            <span>
                              {isBreak
                                ? row.period_number === 4
                                  ? "Break after P4 (Tea Break)"
                                  : row.period_number === 6
                                    ? "Break after P6 (Lunch Break)"
                                    : `Break after P${row.period_number}`
                                : "No break"}
                            </span>
                          </label>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <button
                            type="button"
                            className="icon-btn"
                            title={`Remove P${row.period_number}`}
                            aria-label={`Remove P${row.period_number}`}
                            disabled={periods.length <= 1}
                            onClick={() =>
                              handleRemovePeriod(row.period_number)
                            }
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Feedback messages */}
          {schemaErrors.length > 0 && (
            <div className="inline-alert alert-clash alert-stack" role="alert">
              <div className="alert-head">
                <AlertCircle size={15} />
                <strong>Could not save schema. Fix the following rules:</strong>
              </div>
              <ul className="error-bullet-list">
                {schemaErrors.map((msg, i) => (
                  <li key={i}>{msg}</li>
                ))}
              </ul>
            </div>
          )}

          {schemaSuccess && (
            <div className="inline-alert alert-clear" role="status">
              <CheckCircle2 size={15} />
              <span>{schemaSuccess}</span>
            </div>
          )}

          {/* Save & Reset Actions */}
          <div className="schema-actions-bar">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={savingSchema || resettingSchema}
            >
              <Save size={15} />
              <span>
                {savingSchema ? "Saving..." : "Save clock & rules"}
              </span>
            </button>

            {!confirmReset ? (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={savingSchema || resettingSchema}
                onClick={() => setConfirmReset(true)}
              >
                <RotateCcw size={15} />
                <span>Reset to default schema</span>
              </button>
            ) : (
              <div className="reset-confirm-bar">
                <span>Restore default ATC clock and rules?</span>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={resettingSchema}
                  onClick={handleConfirmReset}
                >
                  {resettingSchema ? "Resetting..." : "Confirm reset"}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={resettingSchema}
                  onClick={() => setConfirmReset(false)}
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </form>
      </section>
    </div>
  );
};
