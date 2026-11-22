import React, { useEffect, useState } from "react";
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
  type Branding,
  type PublicSession,
  type PublicTimetableResponse,
} from "../api/client";
import { SundialMark } from "../components/SundialMark";
import { DataOnboarding } from "./DataOnboarding";
import { InstitutionSettings } from "./InstitutionSettings";
import { SolverStudio } from "./SolverStudio";

type StudioTab = "timetable" | "onboarding" | "settings";

export const StudioShell: React.FC = () => {
  const navigate = useNavigate();
  const [authChecked, setAuthChecked] = useState(false);
  const [adminUser, setAdminUser] = useState<string>("admin");
  const [activeTab, setActiveTab] = useState<StudioTab>("timetable");

  const [timetable, setTimetable] = useState<PublicTimetableResponse | null>(
    null
  );
  const [branding, setBranding] = useState<Branding | null>(null);
  const [logoCacheKey, setLogoCacheKey] = useState<number>(() => Date.now());
  const [logoBroken, setLogoBroken] = useState(false);

  const refreshTimetable = () => {
    getPublicTimetable()
      .then((tt) => {
        setTimetable(tt);
        setBranding(tt.branding);
      })
      .catch(() => {
        // Keep existing timetable view on transient error
      });
  };

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
        setBranding(tt.branding);
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

  const handleBrandingUpdated = (
    nextBranding: Branding,
    nextLogoCacheKey: number
  ) => {
    setBranding(nextBranding);
    setLogoCacheKey(nextLogoCacheKey);
    setLogoBroken(false);
    setTimetable((prev) =>
      prev ? { ...prev, branding: nextBranding } : prev
    );
  };

  const handleTimetableUpdated = (nextSessions: PublicSession[]) => {
    setTimetable((prev) =>
      prev ? { ...prev, sessions: nextSessions, has_timetable: true } : prev
    );
    // Also refresh entities/grid_config in background
    refreshTimetable();
  };

  const handleLogout = () => {
    logoutAdmin();
    navigate("/login", { replace: true });
  };

  if (!authChecked) {
    return (
      <div className="page-shell">
        <div className="status-panel">Verifying registrar session...</div>
      </div>
    );
  }

  const isSolverView = activeTab === "timetable";

  return (
    <div className={`studio-shell ${isSolverView ? "is-solver-view" : ""}`}>
      <header className="studio-header">
        <div
          className={`studio-header-inner ${
            isSolverView ? "is-full-bleed" : ""
          }`}
        >
          <div className="studio-brand">
            <SundialMark size={24} />
            <span className="studio-wordmark">sundial</span>
            <span className="studio-divider">/</span>
            {branding?.logo_url && !logoBroken && (
              <img
                src={`${branding.logo_url}?v=${logoCacheKey}`}
                alt=""
                className="studio-inst-logo"
                onError={() => setLogoBroken(true)}
              />
            )}
            <span className="studio-inst">
              {branding?.institution_name || "Registrar Studio"}
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

      <main className={isSolverView ? "studio-main-solver" : "studio-main"}>
        {activeTab === "timetable" && timetable && (
          <SolverStudio
            timetable={timetable}
            onTimetableUpdated={handleTimetableUpdated}
            onOpenOnboarding={() => setActiveTab("onboarding")}
          />
        )}

        {activeTab === "onboarding" && (
          <DataOnboarding
            onProceedToSolver={() => {
              refreshTimetable();
              setActiveTab("timetable");
            }}
            onDataChanged={refreshTimetable}
          />
        )}

        {activeTab === "settings" && (
          <InstitutionSettings
            initialPeriods={timetable?.grid_config.periods}
            logoCacheKey={logoCacheKey}
            onBrandingUpdated={handleBrandingUpdated}
            onSchemaUpdated={refreshTimetable}
          />
        )}
      </main>
    </div>
  );
};
