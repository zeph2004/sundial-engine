import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  FileDown,
  Loader2,
  PanelRightClose,
  PanelRightOpen,
  Pin,
  PinOff,
  Play,
  X,
} from "lucide-react";
import {
  ApiError,
  clearAllPins,
  downloadMasterPdf,
  getPins,
  getSettings,
  pinSession,
  runSolve,
  unpinSession,
  type LensType,
  type PublicSession,
  type PublicTimetableResponse,
  type SchemaConfig,
  type SolveResponse,
} from "../api/client";
import { ConstraintDrawer } from "../components/ConstraintDrawer";
import { SearchableSelect } from "../components/SearchableSelect";
import { SolveDetailsModal } from "../components/SolveDetailsModal";
import {
  TimetableGrid,
  type MergedSession,
} from "../components/TimetableGrid";

export interface SolverStudioProps {
  timetable: PublicTimetableResponse;
  onTimetableUpdated: (nextSessions: PublicSession[]) => void;
  onOpenOnboarding: () => void;
}

const SHORT_DAY: Record<string, string> = {
  MONDAY: "Monday",
  TUESDAY: "Tuesday",
  WEDNESDAY: "Wednesday",
  THURSDAY: "Thursday",
  FRIDAY: "Friday",
  SATURDAY: "Saturday",
  SUNDAY: "Sunday",
};

interface ActivePopover {
  session: MergedSession;
  x: number;
  y: number;
}

export const SolverStudio: React.FC<SolverStudioProps> = ({
  timetable,
  onTimetableUpdated,
  onOpenOnboarding,
}) => {
  const [lens, setLens] = useState<LensType>("cohort");
  const [selectedId, setSelectedId] = useState<string>(
    () => timetable.entities.cohorts[0]?.id ?? ""
  );

  // Draft schema for right-hand Soft-Constraint Drawer
  const [draftSchema, setDraftSchema] = useState<SchemaConfig | null>(null);
  const [jsonValid, setJsonValid] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(true);

  // Pins state
  const [pinnedIds, setPinnedIds] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    for (const s of timetable.sessions) {
      if (s.is_pinned) initial.add(s.session_id);
    }
    return initial;
  });
  const [clearingPins, setClearingPins] = useState(false);

  // Solve state
  const [solving, setSolving] = useState(false);
  const [solveResult, setSolveResult] = useState<SolveResponse | null>(null);
  const [solveError, setSolveError] = useState<{
    message: string;
    isPreflight: boolean;
  } | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  // Master PDF export dropdown state
  const [pdfMenuOpen, setPdfMenuOpen] = useState(false);
  const [exportingLens, setExportingLens] = useState<LensType | null>(null);
  const pdfMenuRef = useRef<HTMLDivElement | null>(null);

  // Session pinning popover state
  const [popover, setPopover] = useState<ActivePopover | null>(null);
  const [pinBusy, setPinBusy] = useState(false);
  const [pinError, setPinError] = useState<string | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  // Keep selectedId valid if timetable entities change
  useEffect(() => {
    const list =
      lens === "cohort"
        ? timetable.entities.cohorts
        : lens === "lecturer"
          ? timetable.entities.lecturers
          : timetable.entities.venues;
    if (!selectedId || !list.some((e) => e.id === selectedId)) {
      setSelectedId(list[0]?.id ?? "");
    }
  }, [timetable.entities, lens, selectedId]);

  // Load schema_config and current pins on mount
  useEffect(() => {
    let active = true;
    Promise.all([getSettings(), getPins()])
      .then(([settingsRes, pinsRes]) => {
        if (!active) return;
        setDraftSchema(settingsRes.schema_config);
        setPinnedIds(new Set(Object.keys(pinsRes.pinned_assignments || {})));
      })
      .catch(() => {
        // Non-fatal: user can still view timetable
      });
    return () => {
      active = false;
    };
  }, []);

  // Close Master PDF dropdown on outside click
  useEffect(() => {
    if (!pdfMenuOpen) return;
    const handleOutside = (e: MouseEvent) => {
      if (
        pdfMenuRef.current &&
        !pdfMenuRef.current.contains(e.target as Node)
      ) {
        setPdfMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [pdfMenuOpen]);

  const handleExportMasterPdf = async (targetLens: LensType) => {
    setPdfMenuOpen(false);
    setExportingLens(targetLens);
    setSolveError(null);
    try {
      await downloadMasterPdf(targetLens);
    } catch (err) {
      setSolveError({
        message:
          err instanceof Error
            ? err.message
            : `Could not export master ${targetLens} PDF.`,
        isPreflight: false,
      });
    } finally {
      setExportingLens(null);
    }
  };

  // Close pin popover on Escape or outside click
  useEffect(() => {
    if (!popover) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setPopover(null);
        setPinError(null);
      }
    };
    const handleOutside = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setPopover(null);
        setPinError(null);
      }
    };
    window.addEventListener("keydown", handleKey);
    document.addEventListener("mousedown", handleOutside);
    return () => {
      window.removeEventListener("keydown", handleKey);
      document.removeEventListener("mousedown", handleOutside);
    };
  }, [popover]);

  const entityOptions = useMemo(() => {
    if (lens === "cohort") return timetable.entities.cohorts;
    if (lens === "lecturer") return timetable.entities.lecturers;
    return timetable.entities.venues;
  }, [timetable.entities, lens]);

  const filteredSessions = useMemo(() => {
    if (!selectedId) return [];
    if (lens === "cohort") {
      return timetable.sessions.filter((s) => s.cohorts.includes(selectedId));
    }
    if (lens === "lecturer") {
      return timetable.sessions.filter((s) => s.lecturers.includes(selectedId));
    }
    return timetable.sessions.filter(
      (s) => String(s.venue_id) === String(selectedId)
    );
  }, [timetable.sessions, lens, selectedId]);

  const handleGenerate = async () => {
    if (!jsonValid) return;
    setSolving(true);
    setSolveError(null);
    setPopover(null);
    try {
      const res = await runSolve({
        schema_override: draftSchema,
        use_pins: true,
      });
      setSolveResult(res);
      onTimetableUpdated(res.timetable);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        let msg = err.message;
        let isPreflight = false;
        const detail = err.detail as Record<string, unknown> | null;
        if (detail && typeof detail === "object") {
          if (Array.isArray(detail.errors) && detail.errors.length > 0) {
            isPreflight = true;
            const first = detail.errors[0] as Record<string, unknown>;
            const firstMsg =
              typeof first === "string"
                ? first
                : String(first?.message || "Pre-flight check failed.");
            msg = `Pre-flight check failed (${detail.errors.length} ${
              detail.errors.length === 1 ? "error" : "errors"
            }): ${firstMsg}`;
          } else if (typeof detail.message === "string") {
            msg = detail.message;
          }
        }
        setSolveError({ message: msg, isPreflight });
      } else {
        setSolveError({
          message:
            err instanceof Error
              ? err.message
              : "Could not generate timetable.",
          isPreflight: false,
        });
      }
    } finally {
      setSolving(false);
    }
  };

  const handleSessionClick = (
    session: MergedSession,
    anchorRect?: DOMRect
  ) => {
    setPinError(null);
    const width = 310;
    const height = 225;
    const x = anchorRect
      ? Math.min(window.innerWidth - width - 16, Math.max(16, anchorRect.left))
      : Math.max(16, window.innerWidth / 2 - width / 2);
    const y = anchorRect
      ? anchorRect.bottom + height > window.innerHeight
        ? Math.max(16, anchorRect.top - height - 8)
        : anchorRect.bottom + 8
      : 140;
    setPopover({ session, x, y });
  };

  const handleTogglePin = async () => {
    if (!popover) return;
    const s = popover.session;
    const constituents =
      s.mergedSessions && s.mergedSessions.length > 0 ? s.mergedSessions : [s];
    const currentlyPinned = constituents.some((item) =>
      pinnedIds.has(item.session_id)
    );
    setPinBusy(true);
    setPinError(null);
    try {
      if (currentlyPinned) {
        for (const item of constituents) {
          if (pinnedIds.has(item.session_id)) {
            await unpinSession(item.session_id);
          }
        }
        setPinnedIds((prev) => {
          const next = new Set(prev);
          for (const item of constituents) {
            next.delete(item.session_id);
          }
          return next;
        });
      } else {
        for (const item of constituents) {
          await pinSession(item.session_id, {
            day_idx: item.day_idx,
            start_period: item.start_period,
            venue_id: item.venue_id,
          });
        }
        setPinnedIds((prev) => {
          const next = new Set(prev);
          for (const item of constituents) {
            next.add(item.session_id);
          }
          return next;
        });
      }
      setPopover(null);
    } catch (err) {
      setPinError(
        err instanceof Error
          ? err.message
          : "Could not update session pin."
      );
    } finally {
      setPinBusy(false);
    }
  };

  const handleClearAllPins = async () => {
    setClearingPins(true);
    try {
      await clearAllPins();
      setPinnedIds(new Set());
      setPopover(null);
    } catch {
      // ignore transient error
    } finally {
      setClearingPins(false);
    }
  };

  const pinnedCount = pinnedIds.size;
  const totalSec = solveResult
    ? ((solveResult.solve_ms + solveResult.optimize_ms) / 1000).toFixed(2)
    : null;

  return (
    <div className="solver-workspace">
      <div className="solver-main-col">
        {/* Studio Toolbar */}
        <div className="solver-toolbar">
          <div className="solver-toolbar-left">
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
            <div className="solver-select-wrap">
              <SearchableSelect
                options={entityOptions}
                value={selectedId}
                onChange={setSelectedId}
                placeholder={`Search ${lens}...`}
              />
            </div>
          </div>

          <div className="solver-toolbar-right">
            <div
              className={`status-pill ${
                solveResult && solveResult.hard_violations > 0
                  ? "status-pill-clash"
                  : "status-pill-clear"
              }`}
              role="status"
            >
              <CheckCircle2 size={14} />
              <span className="mono-num">
                {solveResult
                  ? `${solveResult.hard_violations} Clashes · ${solveResult.kpis.saturday_free_cohorts_pct.toFixed(1)}% Sat-Free · ${totalSec}s`
                  : `0 Clashes · ${timetable.sessions.length.toLocaleString()} sessions`}
              </span>
            </div>

            <button
              type="button"
              className="btn btn-secondary"
              disabled={!solveResult}
              title={
                solveResult
                  ? "View Before/After scorecard and Saturday explanations"
                  : "Generate a timetable to view detailed scorecard"
              }
              onClick={() => setDetailsOpen(true)}
            >
              <BarChart3 size={15} />
              <span>Show details</span>
            </button>

            {pinnedCount > 0 && (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={clearingPins || solving}
                onClick={handleClearAllPins}
              >
                <PinOff size={14} />
                <span>Clear all pins ({pinnedCount})</span>
              </button>
            )}

            <div className="pdf-menu-wrap" ref={pdfMenuRef}>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={exportingLens !== null || solving}
                aria-haspopup="menu"
                aria-expanded={pdfMenuOpen}
                onClick={() => setPdfMenuOpen((prev) => !prev)}
              >
                {exportingLens ? (
                  <>
                    <Loader2 size={14} className="spin-icon" />
                    <span>Exporting {exportingLens}s...</span>
                  </>
                ) : (
                  <>
                    <FileDown size={15} />
                    <span>Master PDF</span>
                    <ChevronDown size={13} />
                  </>
                )}
              </button>
              {pdfMenuOpen && (
                <div className="pdf-dropdown-menu" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    className="pdf-dropdown-item"
                    onClick={() => handleExportMasterPdf("cohort")}
                  >
                    All Cohorts (Master PDF)
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="pdf-dropdown-item"
                    onClick={() => handleExportMasterPdf("lecturer")}
                  >
                    All Lecturers (Master PDF)
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="pdf-dropdown-item"
                    onClick={() => handleExportMasterPdf("venue")}
                  >
                    All Venues (Master PDF)
                  </button>
                </div>
              )}
            </div>

            <button
              type="button"
              className="btn btn-primary"
              disabled={solving || !jsonValid}
              onClick={handleGenerate}
            >
              {solving ? (
                <>
                  <Loader2 size={15} className="spin-icon" />
                  <span>Generating...</span>
                </>
              ) : (
                <>
                  <Play size={15} />
                  <span>Generate timetable</span>
                </>
              )}
            </button>

            <button
              type="button"
              className={`btn ${
                drawerOpen ? "btn-ghost" : "btn-secondary"
              }`}
              title={
                drawerOpen
                  ? "Collapse Preferences & weights panel"
                  : "Open Preferences & weights panel"
              }
              aria-expanded={drawerOpen}
              onClick={() => setDrawerOpen((prev) => !prev)}
            >
              {drawerOpen ? (
                <PanelRightClose size={15} />
              ) : (
                <PanelRightOpen size={15} />
              )}
              <span>Preferences</span>
            </button>
          </div>
        </div>

        {/* Solve Error Banner */}
        {solveError && (
          <div className="inline-alert alert-clash solver-error-bar" role="alert">
            <div className="alert-head">
              <AlertCircle size={16} />
              <span>{solveError.message}</span>
            </div>
            {solveError.isPreflight && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={onOpenOnboarding}
              >
                <span>Open Data Onboarding</span>
                <ArrowRight size={13} />
              </button>
            )}
          </div>
        )}

        <div className="solver-grid-hint">
          Click any session block on the timetable to pin or unpin it in its
          current slot.
        </div>

        <div className="solver-grid-frame">
          <TimetableGrid
            sessions={filteredSessions}
            gridConfig={timetable.grid_config}
            lens={lens}
            pinnedSessionIds={pinnedIds}
            activePopoverSessionId={popover?.session.session_id ?? null}
            onSessionClick={handleSessionClick}
          />
        </div>
      </div>

      {/* Right-hand Soft-Constraint Drawer */}
      {drawerOpen && (
        <ConstraintDrawer
          schema={draftSchema}
          onSchemaChange={setDraftSchema}
          onJsonValidityChange={setJsonValid}
          onCollapse={() => setDrawerOpen(false)}
          disabled={solving}
        />
      )}

      {/* Session Pin Action Popover */}
      {popover && (
        <div
          ref={popoverRef}
          className="pin-popover"
          style={{ left: popover.x, top: popover.y }}
          role="dialog"
          aria-label="Session pin actions"
        >
          <div className="pin-pop-head">
            <div>
              <span className="pin-pop-code mono-num">
                {popover.session.module_code}
              </span>
              {(popover.session.mergedSessions || [popover.session]).some(
                (item) => pinnedIds.has(item.session_id)
              ) && (
                <span className="pin-pop-badge">
                  <Pin size={10} /> Pinned
                </span>
              )}
            </div>
            <button
              type="button"
              className="icon-btn"
              aria-label="Close popover"
              onClick={() => {
                setPopover(null);
                setPinError(null);
              }}
            >
              <X size={14} />
            </button>
          </div>

          <div className="pin-pop-title">
            {popover.session.module_name || popover.session.module_code}
          </div>

          <dl className="pin-pop-dl">
            <div>
              <dt>Day &amp; periods</dt>
              <dd className="mono-num">
                {SHORT_DAY[popover.session.day] || popover.session.day}, P
                {popover.session.start_period}–P
                {popover.session.start_period +
                  popover.session.duration_periods -
                  1}
              </dd>
            </div>
            <div>
              <dt>Venue</dt>
              <dd>{popover.session.venue_name}</dd>
            </div>
            <div>
              <dt>Lecturer</dt>
              <dd>
                {popover.session.lecturers.length > 0
                  ? popover.session.lecturers.join(", ")
                  : "Unassigned"}
              </dd>
            </div>
          </dl>

          {pinError && (
            <div
              className="inline-alert alert-clash"
              role="alert"
              style={{ marginTop: 10, marginBottom: 0, fontSize: 12.5 }}
            >
              <AlertCircle size={14} />
              <span>{pinError}</span>
            </div>
          )}

          <div className="pin-pop-actions">
            {(popover.session.mergedSessions || [popover.session]).some(
              (item) => pinnedIds.has(item.session_id)
            ) ? (
              <button
                type="button"
                className="btn btn-secondary btn-full"
                disabled={pinBusy}
                onClick={handleTogglePin}
              >
                <PinOff size={14} />
                <span>{pinBusy ? "Unpinning..." : "Unpin session"}</span>
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary btn-full"
                disabled={pinBusy}
                onClick={handleTogglePin}
              >
                <Pin size={14} />
                <span>
                  {pinBusy ? "Pinning..." : "Pin session in this slot"}
                </span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Scorecard & Saturday Modal */}
      <SolveDetailsModal
        open={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        solveResult={solveResult}
      />
    </div>
  );
};
