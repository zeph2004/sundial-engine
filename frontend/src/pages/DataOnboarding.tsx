import React, { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Building2,
  CalendarClock,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  ShieldCheck,
  Upload,
  Users,
} from "lucide-react";
import {
  downloadTemplate,
  getOnboardingStatus,
  runPreflightValidation,
  uploadEntityFile,
  type OnboardingEntityKey,
  type OnboardingStatusResponse,
  type PreflightValidationResponse,
} from "../api/client";

export interface DataOnboardingProps {
  onProceedToSolver: () => void;
  onDataChanged?: () => void;
}

interface EntityCardConfig {
  key: OnboardingEntityKey;
  title: string;
  description: string;
  icon: React.ReactNode;
}

const ENTITY_CARDS: EntityCardConfig[] = [
  {
    key: "venues",
    title: "Venues",
    description: "Lecture halls, labs, workshops, capacities, and categories.",
    icon: <Building2 size={18} strokeWidth={1.6} />,
  },
  {
    key: "lecturers",
    title: "Lecturers",
    description: "Teaching staff catalogue and department affiliations.",
    icon: <Users size={18} strokeWidth={1.6} />,
  },
  {
    key: "sessions",
    title: "Sessions / Course Allocations",
    description:
      "Upload weekly hours (hours_per_week) and Sundial automatically splits them into balanced blocks using your period duration.",
    icon: <CalendarClock size={18} strokeWidth={1.6} />,
  },
];

interface CardFeedback {
  type: "clear" | "clash";
  message: string;
  warnings?: string[];
}

function formatTimestamp(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const DataOnboarding: React.FC<DataOnboardingProps> = ({
  onProceedToSolver,
  onDataChanged,
}) => {
  const [status, setStatus] = useState<OnboardingStatusResponse | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [uploading, setUploading] = useState<
    Record<OnboardingEntityKey, boolean>
  >({
    venues: false,
    lecturers: false,
    sessions: false,
  });
  const [downloading, setDownloading] = useState<
    Record<OnboardingEntityKey, boolean>
  >({
    venues: false,
    lecturers: false,
    sessions: false,
  });
  const [dragOver, setDragOver] = useState<OnboardingEntityKey | null>(null);
  const [cardFeedback, setCardFeedback] = useState<
    Partial<Record<OnboardingEntityKey, CardFeedback>>
  >({});

  // Pre-flight state
  const [validating, setValidating] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [preflightResult, setPreflightResult] =
    useState<PreflightValidationResponse | null>(null);

  const fileInputs = useRef<
    Record<OnboardingEntityKey, HTMLInputElement | null>
  >({
    venues: null,
    lecturers: null,
    sessions: null,
  });

  const loadStatus = async () => {
    try {
      const res = await getOnboardingStatus();
      setStatus(res);
      setStatusError(null);
    } catch (err) {
      setStatusError(
        err instanceof Error
          ? err.message
          : "Could not load onboarding status."
      );
    } finally {
      setLoadingStatus(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleDownloadTemplate = async (entity: OnboardingEntityKey) => {
    setDownloading((prev) => ({ ...prev, [entity]: true }));
    try {
      await downloadTemplate(entity);
    } catch (err) {
      setCardFeedback((prev) => ({
        ...prev,
        [entity]: {
          type: "clash",
          message:
            err instanceof Error
              ? err.message
              : `Could not download ${entity} template.`,
        },
      }));
    } finally {
      setDownloading((prev) => ({ ...prev, [entity]: false }));
    }
  };

  const handleUploadFile = async (entity: OnboardingEntityKey, file: File) => {
    setUploading((prev) => ({ ...prev, [entity]: true }));
    setCardFeedback((prev) => {
      const next = { ...prev };
      delete next[entity];
      return next;
    });

    try {
      const res = await uploadEntityFile(entity, file);
      let message = `Loaded ${res.rows_loaded.toLocaleString()} ${entity} from ${file.name}.`;
      if (
        entity === "sessions" &&
        res.mode &&
        res.mode !== "legacy_sessions" &&
        typeof res.input_rows === "number"
      ) {
        const gridNote = res.period_duration_minutes
          ? ` (${res.period_duration_minutes}-min grid)`
          : "";
        message = `Expanded ${res.input_rows.toLocaleString()} allocations → ${res.rows_loaded.toLocaleString()} schedulable sessions${gridNote}.`;
      }
      setCardFeedback((prev) => ({
        ...prev,
        [entity]: {
          type: "clear",
          message,
          warnings: res.warnings,
        },
      }));
      // Refresh status without wiping feedback of other cards
      await loadStatus();
      onDataChanged?.();
    } catch (err) {
      setCardFeedback((prev) => ({
        ...prev,
        [entity]: {
          type: "clash",
          message:
            err instanceof Error ? err.message : `Upload failed for ${entity}.`,
        },
      }));
    } finally {
      setUploading((prev) => ({ ...prev, [entity]: false }));
      const inputEl = fileInputs.current[entity];
      if (inputEl) inputEl.value = "";
    }
  };

  const handleRunPreflight = async () => {
    setValidating(true);
    setPreflightError(null);
    try {
      const res = await runPreflightValidation();
      setPreflightResult(res);
    } catch (err) {
      setPreflightError(
        err instanceof Error
          ? err.message
          : "Could not run pre-flight validation."
      );
    } finally {
      setValidating(false);
    }
  };

  if (loadingStatus) {
    return (
      <div className="status-panel">Loading workspace datasets...</div>
    );
  }

  if (statusError) {
    return (
      <div className="status-panel status-error">
        <strong>Could not load onboarding status.</strong> {statusError}
      </div>
    );
  }

  const affinityInfo = status?.entities?.affinity;

  return (
    <div className="onboarding-page">
      <div className="studio-panel-head">
        <div>
          <h2>Data onboarding</h2>
          <p>
            Upload venues, lecturers, and sessions independently as CSV or JSON.
            Each file is validated on its own without clearing the others.
          </p>
        </div>

        {affinityInfo && (
          <div className="affinity-status-badge" title={affinityInfo.filename}>
            <FileSpreadsheet size={14} />
            <span>
              Venue affinity:{" "}
              <strong>
                {affinityInfo.source === "preloaded_atc"
                  ? "Preloaded ATC"
                  : "Custom"}
              </strong>{" "}
              ·{" "}
              <span className="mono-num">
                {affinityInfo.row_count.toLocaleString()} rules
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Section A: Independent Entity Upload Cards */}
      <div className="onboarding-cards-grid">
        {ENTITY_CARDS.map((card) => {
          const info = status?.entities?.[card.key];
          const isPreloaded = info?.source === "preloaded_atc";
          const isUploading = uploading[card.key];
          const isDownloading = downloading[card.key];
          const feedback = cardFeedback[card.key];

          return (
            <article key={card.key} className="entity-card">
              <div className="entity-card-top">
                <div className="entity-card-title-wrap">
                  <span className="entity-card-icon">{card.icon}</span>
                  <div>
                    <h3>{card.title}</h3>
                    <p>{card.description}</p>
                  </div>
                </div>
                <span
                  className={`source-badge ${
                    isPreloaded ? "source-atc" : "source-custom"
                  }`}
                >
                  {isPreloaded ? "Preloaded ATC" : "Custom Upload"}
                </span>
              </div>

              <div className="entity-stats-box">
                <div className="entity-stat-primary">
                  <span className="entity-stat-label">Rows loaded</span>
                  <span className="entity-stat-count mono-num">
                    {info ? info.row_count.toLocaleString() : "0"}
                  </span>
                </div>
                <dl className="entity-meta-dl">
                  {card.key === "sessions" &&
                    typeof info?.input_rows === "number" && (
                      <div>
                        <dt>Allocations</dt>
                        <dd className="mono-cell">
                          {info.input_rows.toLocaleString()} rows
                          {info.period_duration_minutes
                            ? ` (${info.period_duration_minutes}-min grid)`
                            : ""}
                        </dd>
                      </div>
                    )}
                  <div>
                    <dt>Active file</dt>
                    <dd className="mono-cell" title={info?.filename || "—"}>
                      {info?.filename || "—"}
                    </dd>
                  </div>
                  <div>
                    <dt>Last updated</dt>
                    <dd>{formatTimestamp(info?.updated_at)}</dd>
                  </div>
                </dl>
              </div>

              <div
                className={`upload-dropzone ${
                  dragOver === card.key ? "is-dragover" : ""
                }`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(card.key);
                }}
                onDragLeave={() => setDragOver(null)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(null);
                  const file = e.dataTransfer.files?.[0];
                  if (file) {
                    handleUploadFile(card.key, file);
                  }
                }}
              >
                <input
                  ref={(el) => {
                    fileInputs.current[card.key] = el;
                  }}
                  type="file"
                  accept=".csv,.json,text/csv,application/json"
                  className="sr-only"
                  aria-label={`Upload ${card.title} CSV or JSON`}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) handleUploadFile(card.key, file);
                  }}
                />
                <button
                  type="button"
                  className="btn btn-secondary btn-full"
                  disabled={isUploading}
                  onClick={() => fileInputs.current[card.key]?.click()}
                >
                  <Upload size={15} />
                  <span>
                    {isUploading
                      ? `Uploading ${card.key}...`
                      : `Upload ${card.title} (.csv / .json)`}
                  </span>
                </button>
                <span className="dropzone-hint">
                  Or drag and drop a file here
                </span>
              </div>

              <div className="entity-card-footer">
                <button
                  type="button"
                  className="btn btn-ghost btn-full"
                  disabled={isDownloading}
                  onClick={() => handleDownloadTemplate(card.key)}
                >
                  <Download size={14} />
                  <span>
                    {isDownloading
                      ? "Downloading..."
                      : `Download ${card.key} CSV template`}
                  </span>
                </button>
              </div>

              {feedback && (
                <>
                  <div
                    className={`inline-alert ${
                      feedback.type === "clear" ? "alert-clear" : "alert-clash"
                    }`}
                    role={feedback.type === "clash" ? "alert" : "status"}
                    style={{ marginTop: 10, marginBottom: 0 }}
                  >
                    {feedback.type === "clear" ? (
                      <CheckCircle2 size={15} />
                    ) : (
                      <AlertCircle size={15} />
                    )}
                    <span>{feedback.message}</span>
                  </div>
                  {feedback.warnings && feedback.warnings.length > 0 && (
                    <div
                      className="inline-alert alert-caution alert-stack"
                      role="status"
                      style={{ marginTop: 8, marginBottom: 0 }}
                    >
                      <div className="alert-head">
                        <AlertTriangle size={14} />
                        <strong>
                          {feedback.warnings.length}{" "}
                          {feedback.warnings.length === 1
                            ? "rounding / upload notice"
                            : "rounding / upload notices"}
                        </strong>
                      </div>
                      <ul className="upload-warn-list">
                        {feedback.warnings.slice(0, 5).map((w, idx) => (
                          <li key={idx}>{w}</li>
                        ))}
                        {feedback.warnings.length > 5 && (
                          <li>
                            +{feedback.warnings.length - 5} more notices
                          </li>
                        )}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </article>
          );
        })}
      </div>

      {/* Section B: Pre-Flight Validation Panel */}
      <section className="studio-card preflight-panel">
        <div className="preflight-head">
          <div>
            <h3>Pre-flight validation</h3>
            <p>
              Checks that there is enough time and space before running the
              solver, and verifies every session duration, venue category, and
              cohort capacity ceiling.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={validating}
            onClick={handleRunPreflight}
          >
            <ShieldCheck size={16} />
            <span>
              {validating ? "Running check..." : "Run pre-flight check"}
            </span>
          </button>
        </div>

        {preflightError && (
          <div className="inline-alert alert-clash" role="alert">
            <AlertCircle size={15} />
            <span>{preflightError}</span>
          </div>
        )}

        {preflightResult && (
          <div className="preflight-results">
            {preflightResult.passed ? (
              <div className="preflight-banner banner-pass" role="status">
                <div className="banner-left">
                  <CheckCircle2 size={20} />
                  <div>
                    <div className="banner-title">
                      Pre-flight check passed
                    </div>
                    <div className="banner-counts">
                      <span className="metric-pill">
                        {preflightResult.summary.sessions.toLocaleString()}{" "}
                        sessions
                      </span>
                      <span className="metric-pill">
                        {preflightResult.summary.cohorts.toLocaleString()}{" "}
                        cohorts
                      </span>
                      <span className="metric-pill">
                        {preflightResult.summary.lecturers.toLocaleString()}{" "}
                        lecturers
                      </span>
                      <span className="metric-pill">
                        {preflightResult.summary.venues.toLocaleString()} venues
                      </span>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={onProceedToSolver}
                >
                  <span>Proceed to Timetable &amp; Solver</span>
                  <ArrowRight size={15} />
                </button>
              </div>
            ) : (
              <div className="preflight-fail-wrap">
                <div className="preflight-banner banner-fail" role="alert">
                  <div className="banner-left">
                    <AlertCircle size={20} />
                    <div>
                      <div className="banner-title">
                        Pre-flight check failed —{" "}
                        {preflightResult.errors.length.toLocaleString()}{" "}
                        {preflightResult.errors.length === 1
                          ? "error"
                          : "errors"}{" "}
                        found
                      </div>
                      <div className="banner-sub">
                        Fix the listed rows in your spreadsheet and re-upload
                        only the affected file.
                      </div>
                    </div>
                  </div>
                  <div className="banner-counts">
                    <span className="metric-pill">
                      {preflightResult.summary.sessions.toLocaleString()}{" "}
                      sessions
                    </span>
                    <span className="metric-pill">
                      {preflightResult.summary.cohorts.toLocaleString()} cohorts
                    </span>
                    <span className="metric-pill">
                      {preflightResult.summary.lecturers.toLocaleString()}{" "}
                      lecturers
                    </span>
                    <span className="metric-pill">
                      {preflightResult.summary.venues.toLocaleString()} venues
                    </span>
                  </div>
                </div>

                <div className="data-table-wrap preflight-error-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th style={{ width: 100 }}>Entity</th>
                        <th style={{ width: 80 }}>Row #</th>
                        <th style={{ width: 130 }}>ID</th>
                        <th style={{ width: 200 }}>Code</th>
                        <th>Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preflightResult.errors.map((err, idx) => (
                        <tr key={`${err.entity}-${err.row}-${err.code}-${idx}`}>
                          <td className="entity-cell">{err.entity}</td>
                          <td className="mono-cell">
                            {err.row !== null ? err.row : "—"}
                          </td>
                          <td className="mono-cell">{err.id || "—"}</td>
                          <td className="mono-cell code-clash">{err.code}</td>
                          <td>{err.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {preflightResult.warnings.length > 0 && (
              <div className="preflight-warnings">
                <div className="warnings-head">
                  <AlertTriangle size={15} />
                  <strong>
                    Warnings ({preflightResult.warnings.length.toLocaleString()})
                  </strong>
                  <span>
                    Non-blocking notices — you can still run the solver.
                  </span>
                </div>
                <ul className="warnings-list">
                  {preflightResult.warnings.map((w, idx) => (
                    <li key={`${w.entity}-${w.row}-${idx}`}>
                      <span className="mono-cell">
                        [{w.entity}
                        {w.row !== null ? ` #${w.row}` : ""}
                        {w.id ? ` · ${w.id}` : ""}]
                      </span>{" "}
                      <span>{w.message}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
};
