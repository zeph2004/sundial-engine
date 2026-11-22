import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Building2,
  Calendar,
  Download,
  Eye,
  GraduationCap,
  LogIn,
  SlidersHorizontal,
  User,
} from "lucide-react";
import {
  getPublicPdfUrl,
  getPublicTimetable,
  getStoredToken,
  type LensType,
  type PublicTimetableResponse,
} from "../api/client";
import { SearchableSelect } from "../components/SearchableSelect";
import { SundialMark } from "../components/SundialMark";
import { TimetableGrid } from "../components/TimetableGrid";

const LENS_TABS: { key: LensType; label: string; icon: React.ReactNode }[] = [
  { key: "cohort", label: "Cohort", icon: <GraduationCap size={15} /> },
  { key: "lecturer", label: "Lecturer", icon: <User size={15} /> },
  { key: "venue", label: "Venue", icon: <Building2 size={15} /> },
];

export const PublicLookup: React.FC = () => {
  const [data, setData] = useState<PublicTimetableResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [lens, setLens] = useState<LensType>("cohort");
  const [selectedId, setSelectedId] = useState<string>("");
  const [showMobileGrid, setShowMobileGrid] = useState(false);

  const isLoggedIn = Boolean(getStoredToken());

  useEffect(() => {
    let active = true;
    setLoading(true);
    getPublicTimetable()
      .then((res) => {
        if (!active) return;
        setData(res);
        setError(null);
        // Default to first cohort (preferring L7-2CS or CS7-2 if present)
        const cohorts = res.entities.cohorts;
        if (cohorts.length > 0) {
          const preferred =
            cohorts.find(
              (c) =>
                c.id.toUpperCase() === "CS7-2" ||
                c.id.toUpperCase() === "L7-2CS"
            ) || cohorts[0];
          setSelectedId(preferred.id);
        }
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Could not load timetable.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const currentEntities = useMemo(() => {
    if (!data) return [];
    if (lens === "cohort") return data.entities.cohorts;
    if (lens === "lecturer") return data.entities.lecturers;
    return data.entities.venues;
  }, [data, lens]);

  const handleLensChange = (nextLens: LensType) => {
    setLens(nextLens);
    setShowMobileGrid(false);
    if (!data) return;
    const list =
      nextLens === "cohort"
        ? data.entities.cohorts
        : nextLens === "lecturer"
          ? data.entities.lecturers
          : data.entities.venues;
    setSelectedId(list[0]?.id ?? "");
  };

  const selectedEntity = useMemo(
    () => currentEntities.find((e) => e.id === selectedId) ?? null,
    [currentEntities, selectedId]
  );

  const filteredSessions = useMemo(() => {
    if (!data || !selectedId) return [];
    if (lens === "cohort") {
      return data.sessions.filter((s) => s.cohorts.includes(selectedId));
    }
    if (lens === "lecturer") {
      return data.sessions.filter((s) => s.lecturers.includes(selectedId));
    }
    return data.sessions.filter((s) => String(s.venue_id) === String(selectedId));
  }, [data, lens, selectedId]);

  const entitySummary = useMemo(() => {
    const totalPeriods = filteredSessions.reduce(
      (acc, s) => acc + s.duration_periods,
      0
    );
    const hasFT = filteredSessions.some((s) => !s.is_evening_stream);
    const hasEve = filteredSessions.some((s) => s.is_evening_stream);
    const stream =
      hasFT && hasEve
        ? "Full-Time & Evening"
        : hasEve
          ? "Evening"
          : "Full-Time";
    const satCount = filteredSessions.filter((s) => s.day === "SATURDAY").length;
    return {
      sessionCount: filteredSessions.length,
      totalPeriods,
      stream,
      satCount,
    };
  }, [filteredSessions]);

  const formattedDate = useMemo(() => {
    if (!data?.generated_at) return "";
    try {
      return new Date(data.generated_at).toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
    } catch {
      return data.generated_at;
    }
  }, [data?.generated_at]);

  if (loading) {
    return (
      <div className="page-shell">
        <div className="status-panel">Loading timetable...</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page-shell">
        <div className="status-panel status-error">
          <strong>Unable to load timetable.</strong>
          <p>{error || "The timetable service did not respond."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page-shell">
      {/* Top Institution Header (University brand leads on public output) */}
      <header className="pub-header">
        <div className="pub-header-inner">
          <div className="pub-brand">
            {data.branding.logo_url ? (
              <img
                src={data.branding.logo_url}
                alt={data.branding.institution_name}
                className="pub-logo-img"
              />
            ) : (
              <SundialMark size={30} />
            )}
            <div>
              <h1 className="pub-inst-name">{data.branding.institution_name}</h1>
              <p className="pub-sem-title">{data.branding.semester_title}</p>
            </div>
          </div>

          <div className="pub-header-actions no-print">
            {isLoggedIn ? (
              <Link to="/studio" className="btn btn-secondary">
                <SlidersHorizontal size={15} />
                <span>Open Studio</span>
              </Link>
            ) : (
              <Link to="/login" className="btn btn-ghost">
                <LogIn size={15} />
                <span>Registrar Login</span>
              </Link>
            )}
          </div>
        </div>
      </header>

      <main className="pub-main">
        {!data.has_timetable ? (
          <section className="empty-state-card">
            <Calendar size={28} strokeWidth={1.5} />
            <h2>No timetable has been published yet.</h2>
            <p>
              Sign in as a registrar to upload timetable data and generate a
              clash-free schedule.
            </p>
            <Link to="/login" className="btn btn-primary">
              Registrar Login
            </Link>
          </section>
        ) : (
          <>
            {/* Searchable Lookup Bar */}
            <section className="lookup-bar no-print" aria-label="Timetable lookup">
              <div className="lens-tabs" role="tablist" aria-label="View by">
                {LENS_TABS.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    role="tab"
                    aria-selected={lens === tab.key}
                    className={`lens-tab ${lens === tab.key ? "is-active" : ""}`}
                    onClick={() => handleLensChange(tab.key)}
                  >
                    {tab.icon}
                    <span>{tab.label}</span>
                  </button>
                ))}
              </div>

              <div className="lookup-select-wrap">
                <SearchableSelect
                  options={currentEntities}
                  value={selectedId}
                  onChange={setSelectedId}
                  placeholder={`Search ${lens}...`}
                  ariaLabel={`Select ${lens}`}
                />
              </div>

              <a
                href={selectedId ? getPublicPdfUrl(lens, selectedId) : "#"}
                download
                className={`btn btn-primary ${!selectedId ? "is-disabled-link" : ""}`}
                onClick={(e) => {
                  if (!selectedId) e.preventDefault();
                }}
              >
                <Download size={15} />
                <span>Download PDF</span>
              </a>
            </section>

            {/* Print-Only Formal Sheet Header */}
            <div className="print-sheet-header">
              <div>
                <div className="print-inst">
                  {data.branding.institution_name} — {data.branding.semester_title}
                </div>
                <div className="print-entity">
                  {lens.charAt(0).toUpperCase() + lens.slice(1)}:{" "}
                  {selectedEntity ? selectedEntity.label : selectedId}
                </div>
              </div>
              <div className="print-meta">
                <span>{entitySummary.sessionCount} sessions</span>
                <span>{entitySummary.totalPeriods} periods / week</span>
                <span>0 clashes</span>
              </div>
            </div>

            {/* Selected Entity Summary Strip (Desktop) */}
            <section className="entity-strip no-print">
              <div className="entity-strip-title">
                <h2>{selectedEntity ? selectedEntity.label : "Select an entry"}</h2>
              </div>
              <div className="entity-strip-metrics">
                <span className="metric-pill metric-clear">0 clashes</span>
                <span className="metric-pill">
                  {entitySummary.sessionCount} sessions ·{" "}
                  {entitySummary.totalPeriods} periods
                </span>
                <span className="metric-pill">{entitySummary.stream}</span>
                {entitySummary.satCount > 0 && (
                  <span className="metric-pill metric-caution">
                    {entitySummary.satCount} Saturday
                  </span>
                )}
              </div>
            </section>

            {/* Mobile (<768px) Focused Download Card */}
            <section className="mobile-download-card no-print">
              <div className="mobile-card-kicker">
                {lens.charAt(0).toUpperCase() + lens.slice(1)} timetable
              </div>
              <h2 className="mobile-card-title">
                {selectedEntity ? selectedEntity.label : selectedId}
              </h2>
              <div className="mobile-card-stats">
                <span>
                  <strong>{entitySummary.sessionCount}</strong> weekly sessions
                </span>
                <span>
                  <strong>{entitySummary.totalPeriods}</strong> periods
                </span>
                <span>{entitySummary.stream}</span>
              </div>
              <a
                href={selectedId ? getPublicPdfUrl(lens, selectedId) : "#"}
                download
                className={`btn btn-primary btn-full ${!selectedId ? "is-disabled-link" : ""}`}
                onClick={(e) => {
                  if (!selectedId) e.preventDefault();
                }}
              >
                <Download size={16} />
                <span>Download PDF</span>
              </a>
              <button
                type="button"
                className="btn btn-ghost btn-full"
                onClick={() => setShowMobileGrid((prev) => !prev)}
              >
                <Eye size={15} />
                <span>
                  {showMobileGrid ? "Hide Grid" : "View Grid Anyway"}
                </span>
              </button>
            </section>

            {/* Full Timetable Grid (Always visible on Desktop >=768px & Print; toggled on Mobile) */}
            <section
              className={`grid-section ${
                showMobileGrid ? "mobile-grid-visible" : "mobile-grid-hidden"
              }`}
            >
              <TimetableGrid
                sessions={filteredSessions}
                gridConfig={data.grid_config}
                lens={lens}
              />
            </section>
          </>
        )}
      </main>

      <footer className="pub-footer">
        <div className="pub-footer-inner">
          <span className="footer-credit">
            <SundialMark size={14} />
            <span>Scheduled with Sundial</span>
          </span>
          <span className="footer-meta">
            {formattedDate ? `Published ${formattedDate}` : ""}
          </span>
        </div>
      </footer>
    </div>
  );
};
