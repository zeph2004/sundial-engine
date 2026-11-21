import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Calendar,
  Database,
  ExternalLink,
  LogOut,
  Settings,
} from "lucide-react";
import {
  getAdminMe,
  getPublicTimetable,
  logoutAdmin,
  type LensType,
  type PublicTimetableResponse,
} from "../api/client";
import { SearchableSelect } from "../components/SearchableSelect";
import { SundialMark } from "../components/SundialMark";
import { TimetableGrid } from "../components/TimetableGrid";

type StudioTab = "timetable" | "onboarding" | "settings";

export const StudioShell: React.FC = () => {
  const navigate = useNavigate();
  const [authChecked, setAuthChecked] = useState(false);
  const [adminUser, setAdminUser] = useState<string>("admin");
  const [activeTab, setActiveTab] = useState<StudioTab>("timetable");

  const [timetable, setTimetable] = useState<PublicTimetableResponse | null>(
    null
  );
  const [lens, setLens] = useState<LensType>("cohort");
  const [selectedId, setSelectedId] = useState<string>("");

  useEffect(() => {
    let active = true;
    getAdminMe()
      .then((res) => {
        if (!active) return;
        setAdminUser(res.admin.sub);
        setAuthChecked(true);
        return getPublicTimetable();
      })
      .then((tt) => {
        if (!active || !tt) return;
        setTimetable(tt);
        const firstCohort = tt.entities.cohorts[0]?.id ?? "";
        setSelectedId(firstCohort);
      })
      .catch(() => {
        if (!active) return;
        logoutAdmin();
        navigate("/login", { replace: true });
      });

    return () => {
      active = false;
    };
  }, [navigate]);

  const handleLogout = () => {
    logoutAdmin();
    navigate("/login", { replace: true });
  };

  const entityOptions = useMemo(() => {
    if (!timetable) return [];
    if (lens === "cohort") return timetable.entities.cohorts;
    if (lens === "lecturer") return timetable.entities.lecturers;
    return timetable.entities.venues;
  }, [timetable, lens]);

  const filteredSessions = useMemo(() => {
    if (!timetable || !selectedId) return [];
    if (lens === "cohort") {
      return timetable.sessions.filter((s) => s.cohorts.includes(selectedId));
    }
    if (lens === "lecturer") {
      return timetable.sessions.filter((s) => s.lecturers.includes(selectedId));
    }
    return timetable.sessions.filter(
      (s) => String(s.venue_id) === String(selectedId)
    );
  }, [timetable, lens, selectedId]);

  if (!authChecked) {
    return (
      <div className="page-shell">
        <div className="status-panel">Verifying registrar session...</div>
      </div>
    );
  }

  return (
    <div className="studio-shell">
      <header className="studio-header">
        <div className="studio-header-inner">
          <div className="studio-brand">
            <SundialMark size={24} />
            <span className="studio-wordmark">sundial</span>
            <span className="studio-divider">/</span>
            <span className="studio-inst">
              {timetable?.branding.institution_name || "Registrar Studio"}
            </span>
          </div>

          <nav className="studio-nav" aria-label="Studio sections">
            <button
              type="button"
              className={`studio-nav-tab ${
                activeTab === "timetable" ? "is-active" : ""
              }`}
              onClick={() => setActiveTab("timetable")}
            >
              <Calendar size={15} />
              <span>Timetable &amp; Solver</span>
            </button>
            <button
              type="button"
              className={`studio-nav-tab ${
                activeTab === "onboarding" ? "is-active" : ""
              }`}
              onClick={() => setActiveTab("onboarding")}
            >
              <Database size={15} />
              <span>Data Onboarding</span>
            </button>
            <button
              type="button"
              className={`studio-nav-tab ${
                activeTab === "settings" ? "is-active" : ""
              }`}
              onClick={() => setActiveTab("settings")}
            >
              <Settings size={15} />
              <span>Institution Settings</span>
            </button>
          </nav>

          <div className="studio-actions">
            <span className="studio-user-pill">{adminUser}</span>
            <Link to="/" className="btn btn-ghost">
              <ExternalLink size={14} />
              <span>Public View</span>
            </Link>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleLogout}
            >
              <LogOut size={14} />
              <span>Logout</span>
            </button>
          </div>
        </div>
      </header>

      <main className="studio-main">
        {activeTab === "timetable" && timetable && (
          <section className="studio-panel">
            <div className="studio-panel-head">
              <div>
                <h2>Timetable preview</h2>
                <p>
                  {timetable.sessions.length.toLocaleString()} sessions placed ·{" "}
                  <strong className="text-clear">0 clashes</strong>
                </p>
              </div>

              <div className="studio-preview-controls">
                <div className="lens-tabs">
                  {(["cohort", "lecturer", "venue"] as LensType[]).map((l) => (
                    <button
                      key={l}
                      type="button"
                      className={`lens-tab ${lens === l ? "is-active" : ""}`}
                      onClick={() => {
                        setLens(l);
                        const nextList =
                          l === "cohort"
                            ? timetable.entities.cohorts
                            : l === "lecturer"
                              ? timetable.entities.lecturers
                              : timetable.entities.venues;
                        setSelectedId(nextList[0]?.id ?? "");
                      }}
                    >
                      {l.charAt(0).toUpperCase() + l.slice(1)}
                    </button>
                  ))}
                </div>
                <div style={{ minWidth: 260 }}>
                  <SearchableSelect
                    options={entityOptions}
                    value={selectedId}
                    onChange={setSelectedId}
                    placeholder={`Search ${lens}...`}
                  />
                </div>
              </div>
            </div>

            <TimetableGrid
              sessions={filteredSessions}
              gridConfig={timetable.grid_config}
              lens={lens}
            />
          </section>
        )}

        {activeTab === "onboarding" && (
          <section className="studio-placeholder">
            <Database size={26} strokeWidth={1.5} />
            <h2>Data onboarding</h2>
            <p>
              Upload venues, lecturers, and sessions via CSV or JSON and run
              pre-flight checks. Scheduled for Sprint 4.
            </p>
          </section>
        )}

        {activeTab === "settings" && (
          <section className="studio-placeholder">
            <Settings size={26} strokeWidth={1.5} />
            <h2>Institution settings</h2>
            <p>
              Configure institution branding, logo, calendar periods, soft
              rules, and solver weights. Scheduled for Sprint 4.
            </p>
          </section>
        )}
      </main>
    </div>
  );
};
