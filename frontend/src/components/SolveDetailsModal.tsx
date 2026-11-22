import React, { useEffect } from "react";
import { CheckCircle2, X } from "lucide-react";
import type { SolveResponse } from "../api/client";
import { formatRuleTitle } from "./ConstraintDrawer";

export interface SolveDetailsModalProps {
  open: boolean;
  onClose: () => void;
  solveResult: SolveResponse | null;
}

export const SolveDetailsModal: React.FC<SolveDetailsModalProps> = ({
  open,
  onClose,
  solveResult,
}) => {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open || !solveResult) return null;

  const { kpis, scorecard, saturday_explanations } = solveResult;
  const totalSeconds = (
    (solveResult.solve_ms + solveResult.optimize_ms) /
    1000
  ).toFixed(2);
  const improvementPct =
    scorecard?.improvementPct ?? kpis?.objective_improvement_pct ?? 0;

  const initialByRule = scorecard?.initialBreakdown?.weightedByRule || {};
  const finalByRule = scorecard?.finalBreakdown?.weightedByRule || {};
  const weightsByRule =
    scorecard?.finalBreakdown?.weightsByRule ||
    scorecard?.initialBreakdown?.weightsByRule ||
    {};

  const ruleKeys = Array.from(
    new Set([...Object.keys(initialByRule), ...Object.keys(finalByRule)])
  );

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="solve-details-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-card">
        <div className="modal-head">
          <div>
            <h2 id="solve-details-title">Solver scorecard &amp; Saturday report</h2>
            <p>
              Phase 3 constraint placement and Phase 4 simulated annealing
              breakdown.
            </p>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label="Close details"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        <div className="modal-body">
          {/* Executive KPIs Row */}
          <div className="kpi-grid">
            <div
              className={`kpi-tile ${
                solveResult.hard_violations === 0 ? "kpi-clear" : "kpi-clash"
              }`}
            >
              <span className="kpi-label">Hard clashes</span>
              <span className="kpi-value mono-num">
                {solveResult.hard_violations} Clashes
              </span>
              <span className="kpi-sub">
                {kpis.assigned_sessions.toLocaleString()} /{" "}
                {kpis.total_sessions.toLocaleString()} placed
              </span>
            </div>

            <div className="kpi-tile">
              <span className="kpi-label">Total runtime</span>
              <span className="kpi-value mono-num">{totalSeconds}s</span>
              <span className="kpi-sub mono-num">
                CSP {solveResult.solve_ms.toFixed(0)}ms · SA{" "}
                {solveResult.optimize_ms.toFixed(0)}ms
              </span>
            </div>

            <div className="kpi-tile">
              <span className="kpi-label">Objective reduction</span>
              <span className="kpi-value mono-num">
                {improvementPct >= 0
                  ? `-${improvementPct.toFixed(1)}%`
                  : `+${Math.abs(improvementPct).toFixed(1)}%`}
              </span>
              <span className="kpi-sub">
                {scorecard?.enabled
                  ? `${(scorecard.iterations || 0).toLocaleString()} SA steps`
                  : "Optimiser disabled"}
              </span>
            </div>

            <div className="kpi-tile">
              <span className="kpi-label">Saturday-free cohorts</span>
              <span className="kpi-value mono-num">
                {kpis.saturday_free_cohorts_pct.toFixed(1)}%
              </span>
              <span className="kpi-sub mono-num">
                {kpis.saturday_free_cohorts} of {kpis.total_cohorts} cohorts
              </span>
            </div>

            <div className="kpi-tile">
              <span className="kpi-label">Preferred room affinity</span>
              <span className="kpi-value mono-num">
                {kpis.tier1_affinity_pct.toFixed(1)}%
              </span>
              <span className="kpi-sub mono-num">
                Tier 1A exact: {kpis.tier1a_exact_pct.toFixed(1)}%
              </span>
            </div>
          </div>

          {/* Before vs. After Scorecard Table */}
          <section className="modal-section">
            <h3>Before vs. after scorecard</h3>
            {ruleKeys.length > 0 ? (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Soft rule</th>
                      <th style={{ width: 90, textAlign: "right" }}>Weight</th>
                      <th style={{ width: 140, textAlign: "right" }}>
                        Before (Phase 3)
                      </th>
                      <th style={{ width: 140, textAlign: "right" }}>
                        After (Phase 4)
                      </th>
                      <th style={{ width: 110, textAlign: "right" }}>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ruleKeys.map((key) => {
                      const before = Number(initialByRule[key] ?? 0);
                      const after = Number(finalByRule[key] ?? 0);
                      const delta = after - before;
                      const weight = weightsByRule[key];
                      return (
                        <tr key={key}>
                          <td>{formatRuleTitle(key)}</td>
                          <td className="mono-cell" style={{ textAlign: "right" }}>
                            {weight !== undefined ? weight : "—"}
                          </td>
                          <td className="mono-cell" style={{ textAlign: "right" }}>
                            {before.toLocaleString(undefined, {
                              maximumFractionDigits: 1,
                            })}
                          </td>
                          <td className="mono-cell" style={{ textAlign: "right" }}>
                            {after.toLocaleString(undefined, {
                              maximumFractionDigits: 1,
                            })}
                          </td>
                          <td
                            className={`mono-cell ${
                              delta < 0 ? "text-clear" : ""
                            }`}
                            style={{ textAlign: "right", fontWeight: 600 }}
                          >
                            {delta === 0
                              ? "0"
                              : delta < 0
                                ? delta.toLocaleString(undefined, {
                                    maximumFractionDigits: 1,
                                  })
                                : `+${delta.toLocaleString(undefined, {
                                    maximumFractionDigits: 1,
                                  })}`}
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="table-total-row">
                      <td>
                        <strong>Total weighted penalty</strong>
                      </td>
                      <td />
                      <td className="mono-cell" style={{ textAlign: "right" }}>
                        <strong>
                          {(scorecard?.initialObjective ?? 0).toLocaleString(
                            undefined,
                            { maximumFractionDigits: 1 }
                          )}
                        </strong>
                      </td>
                      <td className="mono-cell" style={{ textAlign: "right" }}>
                        <strong>
                          {(scorecard?.finalObjective ?? 0).toLocaleString(
                            undefined,
                            { maximumFractionDigits: 1 }
                          )}
                        </strong>
                      </td>
                      <td
                        className="mono-cell text-clear"
                        style={{ textAlign: "right" }}
                      >
                        <strong>-{improvementPct.toFixed(1)}%</strong>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="field-hint">
                Run Generate Timetable with the optimiser enabled to inspect
                per-rule penalty reductions.
              </p>
            )}
          </section>

          {/* Why Saturday Was Used (Condition 1 Explanations) */}
          <section className="modal-section">
            <h3>Why Saturday was used</h3>
            {saturday_explanations.length === 0 ? (
              <div className="inline-alert alert-clear" style={{ marginBottom: 0 }}>
                <CheckCircle2 size={16} />
                <span>All cohorts fit within Monday–Friday capacity.</span>
              </div>
            ) : (
              <div className="data-table-wrap modal-sat-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: 110 }}>Cohort</th>
                      <th style={{ width: 95 }}>Stream</th>
                      <th style={{ width: 95, textAlign: "right" }}>Total</th>
                      <th style={{ width: 110, textAlign: "right" }}>
                        Mon–Fri limit
                      </th>
                      <th style={{ width: 90, textAlign: "right" }}>
                        Overflow
                      </th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {saturday_explanations.map((ex) => (
                      <tr key={ex.cohort}>
                        <td className="mono-cell">
                          <strong>{ex.cohort}</strong>
                        </td>
                        <td>{ex.stream}</td>
                        <td className="mono-cell" style={{ textAlign: "right" }}>
                          {ex.total_periods}p
                        </td>
                        <td className="mono-cell" style={{ textAlign: "right" }}>
                          {ex.weekday_limit}p
                        </td>
                        <td className="mono-cell" style={{ textAlign: "right" }}>
                          {ex.overflow_periods > 0
                            ? `+${ex.overflow_periods}p`
                            : "0p"}
                        </td>
                        <td>{ex.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <div className="modal-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
