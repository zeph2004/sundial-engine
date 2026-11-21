import React, { useMemo, useState } from "react";
import { Lock } from "lucide-react";
import type { GridConfig, LensType, PublicSession } from "../api/client";

export interface TimetableGridProps {
  sessions: PublicSession[];
  gridConfig: GridConfig;
  lens: LensType;
  pinnedSessionIds?: Set<string>;
  onSessionClick?: (session: PublicSession) => void;
}

interface DayRowCell {
  startPeriod: number;
  endPeriod: number;
  colspan: number;
  sessions: PublicSession[];
}

const SHORT_DAY: Record<string, string> = {
  MONDAY: "Mon",
  TUESDAY: "Tue",
  WEDNESDAY: "Wed",
  THURSDAY: "Thu",
  FRIDAY: "Fri",
  SATURDAY: "Sat",
  SUNDAY: "Sun",
};

export const TimetableGrid: React.FC<TimetableGridProps> = ({
  sessions,
  gridConfig,
  lens,
  pinnedSessionIds,
  onSessionClick,
}) => {
  const [hovered, setHovered] = useState<{
    session: PublicSession;
    x: number;
    y: number;
  } | null>(null);

  const breakSet = useMemo(
    () => new Set(gridConfig.break_slots || [4, 6]),
    [gridConfig.break_slots]
  );

  const periodLookup = useMemo(() => {
    const map = new Map<number, { start: string; end: string; stream: string }>();
    for (const p of gridConfig.periods || []) {
      map.set(p.period, { start: p.start, end: p.end, stream: p.stream });
    }
    return map;
  }, [gridConfig.periods]);

  // Automatically determine active period range for the selected entity's stream
  const { visiblePeriods, streamLabel } = useMemo(() => {
    const sb = gridConfig.stream_boundaries;
    const total = gridConfig.periods_per_day || 18;
    const allPeriods = Array.from({ length: total }, (_, i) => i + 1);

    if (sessions.length === 0) {
      return {
        visiblePeriods: allPeriods.slice(0, sb.full_time_max),
        streamLabel: "Full-Time (P1–P12)",
      };
    }

    const hasFT = sessions.some((s) => !s.is_evening_stream);
    const hasEve = sessions.some((s) => s.is_evening_stream);

    if (lens === "cohort" && hasFT && !hasEve) {
      return {
        visiblePeriods: allPeriods.filter(
          (p) => p >= sb.full_time_min && p <= sb.full_time_max
        ),
        streamLabel: `Full-Time (P${sb.full_time_min}–P${sb.full_time_max})`,
      };
    }

    if (lens === "cohort" && hasEve && !hasFT) {
      const minEve =
        sb.twilight_periods && sb.twilight_periods.length > 0
          ? Math.min(sb.evening_min, ...sb.twilight_periods)
          : sb.evening_min;
      return {
        visiblePeriods: allPeriods.filter(
          (p) => p >= minEve && p <= sb.evening_max
        ),
        streamLabel: `Evening (P${minEve}–P${sb.evening_max})`,
      };
    }

    // Mixed or Lecturer/Venue: trim to actual used stream range if strictly one stream
    if (hasFT && !hasEve) {
      return {
        visiblePeriods: allPeriods.filter(
          (p) => p >= sb.full_time_min && p <= sb.full_time_max
        ),
        streamLabel: `Full-Time (P${sb.full_time_min}–P${sb.full_time_max})`,
      };
    }
    if (hasEve && !hasFT) {
      const minEve =
        sb.twilight_periods && sb.twilight_periods.length > 0
          ? Math.min(sb.evening_min, ...sb.twilight_periods)
          : sb.evening_min;
      return {
        visiblePeriods: allPeriods.filter(
          (p) => p >= minEve && p <= sb.evening_max
        ),
        streamLabel: `Evening (P${minEve}–P${sb.evening_max})`,
      };
    }

    return {
      visiblePeriods: allPeriods,
      streamLabel: `Full-Time & Evening (P1–P${total})`,
    };
  }, [sessions, gridConfig, lens]);

  // Hide SATURDAY automatically if the selected entity has 0 Saturday sessions
  const visibleDays = useMemo(() => {
    const hasSaturday = sessions.some((s) => s.day === "SATURDAY");
    return gridConfig.days
      .map((day, idx) => ({ day, idx }))
      .filter(({ day }) => day !== "SATURDAY" || hasSaturday);
  }, [gridConfig.days, sessions]);

  const firstVisibleP = visiblePeriods[0] ?? 1;
  const lastVisibleP = visiblePeriods[visiblePeriods.length - 1] ?? 12;

  const buildRowCells = (dayName: string): DayRowCell[] => {
    const daySessions = sessions
      .filter((s) => s.day === dayName)
      .sort(
        (a, b) =>
          a.start_period - b.start_period ||
          b.duration_periods - a.duration_periods
      );

    const cells: DayRowCell[] = [];
    let p = firstVisibleP;
    let idx = 0;

    while (p <= lastVisibleP) {
      // Skip any sessions that ended before p
      while (
        idx < daySessions.length &&
        daySessions[idx].start_period + daySessions[idx].duration_periods - 1 < p
      ) {
        idx++;
      }

      const group: PublicSession[] = [];
      let groupEnd = p;

      while (idx < daySessions.length && daySessions[idx].start_period <= p) {
        const s = daySessions[idx];
        group.push(s);
        const sEnd = Math.min(
          lastVisibleP,
          s.start_period + s.duration_periods - 1
        );
        if (sEnd > groupEnd) groupEnd = sEnd;
        idx++;
      }

      if (group.length === 0) {
        cells.push({
          startPeriod: p,
          endPeriod: p,
          colspan: 1,
          sessions: [],
        });
        p += 1;
      } else {
        while (
          idx < daySessions.length &&
          daySessions[idx].start_period <= groupEnd
        ) {
          const s = daySessions[idx];
          group.push(s);
          const sEnd = Math.min(
            lastVisibleP,
            s.start_period + s.duration_periods - 1
          );
          if (sEnd > groupEnd) groupEnd = sEnd;
          idx++;
        }
        cells.push({
          startPeriod: p,
          endPeriod: groupEnd,
          colspan: groupEnd - p + 1,
          sessions: group,
        });
        p = groupEnd + 1;
      }
    }

    return cells;
  };

  const formatTimeRange = (s: PublicSession): string => {
    const startInfo = periodLookup.get(s.start_period);
    const endP = s.start_period + s.duration_periods - 1;
    const endInfo = periodLookup.get(endP);
    if (startInfo && endInfo) {
      return `P${s.start_period}–P${endP} (${startInfo.start}–${endInfo.end})`;
    }
    return `P${s.start_period}–P${endP}`;
  };

  const handleMouseEnter = (
    e: React.MouseEvent<HTMLDivElement>,
    session: PublicSession
  ) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setHovered({
      session,
      x: Math.min(window.innerWidth - 310, Math.max(12, rect.left)),
      y:
        rect.bottom + 180 > window.innerHeight
          ? Math.max(12, rect.top - 165)
          : rect.bottom + 6,
    });
  };

  return (
    <div className="tt-grid-wrapper">
      <div className="tt-grid-meta no-print">
        <span className="tt-grid-stream-tag">{streamLabel}</span>
        <span className="tt-grid-legend">
          <span className="tt-legend-item">
            <span className="tt-swatch tt-swatch-ft" /> Full-Time
          </span>
          <span className="tt-legend-item">
            <span className="tt-swatch tt-swatch-eve" /> Evening
          </span>
          <span className="tt-legend-item">
            <span className="tt-break-swatch" /> Break after P4 &amp; P6
          </span>
        </span>
      </div>

      <div className="tt-scroll">
        <table className="tt-table">
          <thead>
            <tr>
              <th className="tt-corner-th">Day</th>
              {visiblePeriods.map((p) => {
                const info = periodLookup.get(p);
                const isBreakAfter = breakSet.has(p) && p !== lastVisibleP;
                const isBoundaryAfter =
                  p === gridConfig.stream_boundaries.full_time_max &&
                  p !== lastVisibleP;
                const isTwilight = (
                  gridConfig.stream_boundaries.twilight_periods || []
                ).includes(p);
                const classes = [
                  "tt-period-th",
                  isBreakAfter ? "tt-break-after" : "",
                  isBoundaryAfter ? "tt-boundary-after" : "",
                  isTwilight ? "tt-twilight-th" : "",
                ]
                  .filter(Boolean)
                  .join(" ");

                return (
                  <th key={p} className={classes}>
                    <div className="tt-p-num">P{p}</div>
                    {info && (
                      <div className="tt-p-time">
                        {info.start}
                        <span>{info.end}</span>
                      </div>
                    )}
                    {isBreakAfter && (
                      <div className="tt-break-label">
                        {p === 4 ? "Tea" : p === 6 ? "Lunch" : "Break"}
                      </div>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody>
            {visibleDays.map(({ day }) => {
              const cells = buildRowCells(day);
              const dayPeriods = sessions
                .filter((s) => s.day === day)
                .reduce((acc, s) => acc + s.duration_periods, 0);

              return (
                <tr key={day} className={day === "SATURDAY" ? "tt-sat-row" : ""}>
                  <td className="tt-day-td">
                    <div className="tt-day-name">
                      {SHORT_DAY[day] || day.slice(0, 3)}
                      {day === "SATURDAY" && (
                        <span className="tt-sat-tag">Sat</span>
                      )}
                    </div>
                    <div className="tt-day-count">{dayPeriods}p</div>
                  </td>

                  {cells.map((cell) => {
                    const isBreakAfter =
                      breakSet.has(cell.endPeriod) &&
                      cell.endPeriod !== lastVisibleP;
                    const isBoundaryAfter =
                      cell.endPeriod ===
                        gridConfig.stream_boundaries.full_time_max &&
                      cell.endPeriod !== lastVisibleP;
                    const tdClasses = [
                      "tt-slot-td",
                      cell.sessions.length === 0 ? "tt-empty-td" : "",
                      isBreakAfter ? "tt-break-after" : "",
                      isBoundaryAfter ? "tt-boundary-after" : "",
                    ]
                      .filter(Boolean)
                      .join(" ");

                    return (
                      <td
                        key={`${day}-${cell.startPeriod}`}
                        colSpan={cell.colspan}
                        className={tdClasses}
                      >
                        {cell.sessions.length > 0 && (
                          <div className="tt-cell-stack">
                            {cell.sessions.map((s) => {
                              const isPinned =
                                Boolean(s.is_pinned) ||
                                Boolean(pinnedSessionIds?.has(s.session_id));
                              const secondaryText =
                                lens === "venue"
                                  ? s.cohorts.join(", ")
                                  : s.venue_name;
                              const cardClasses = [
                                "tt-session-card",
                                s.is_evening_stream
                                  ? "tt-stream-eve"
                                  : "tt-stream-ft",
                                isPinned ? "tt-is-pinned" : "",
                                onSessionClick ? "tt-clickable" : "",
                              ]
                                .filter(Boolean)
                                .join(" ");

                              return (
                                <div
                                  key={s.session_id}
                                  className={cardClasses}
                                  role={onSessionClick ? "button" : undefined}
                                  tabIndex={onSessionClick ? 0 : undefined}
                                  onClick={() => onSessionClick?.(s)}
                                  onKeyDown={(e) => {
                                    if (
                                      onSessionClick &&
                                      (e.key === "Enter" || e.key === " ")
                                    ) {
                                      e.preventDefault();
                                      onSessionClick(s);
                                    }
                                  }}
                                  onMouseEnter={(e) => handleMouseEnter(e, s)}
                                  onMouseLeave={() => setHovered(null)}
                                >
                                  <div className="tt-card-row-top">
                                    <span className="tt-mod-code">
                                      {s.module_code}
                                    </span>
                                    <span className="tt-card-badges">
                                      {isPinned && (
                                        <span
                                          className="tt-pin-icon"
                                          title="Pinned session"
                                        >
                                          <Lock size={10} />
                                        </span>
                                      )}
                                      <span className="tt-type-badge">
                                        {s.session_type}
                                      </span>
                                    </span>
                                  </div>
                                  <div className="tt-card-venue">
                                    {secondaryText}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Hover Popover Tooltip (Full Module Name, Lecturer(s), Cohorts, Time Range, Venue) */}
      {hovered && (
        <div
          className="tt-popover no-print"
          style={{ left: hovered.x, top: hovered.y }}
          role="tooltip"
        >
          <div className="tt-pop-head">
            <span className="tt-pop-code">{hovered.session.module_code}</span>
            <span className="tt-pop-type">{hovered.session.session_type}</span>
          </div>
          <div className="tt-pop-name">
            {hovered.session.module_name || hovered.session.module_code}
          </div>
          <dl className="tt-pop-dl">
            <div>
              <dt>Time</dt>
              <dd>
                {SHORT_DAY[hovered.session.day] || hovered.session.day},{" "}
                {formatTimeRange(hovered.session)}
              </dd>
            </div>
            <div>
              <dt>Venue</dt>
              <dd>{hovered.session.venue_name}</dd>
            </div>
            <div>
              <dt>Lecturer</dt>
              <dd>
                {hovered.session.lecturers.length > 0
                  ? hovered.session.lecturers.join(", ")
                  : "Unassigned"}
              </dd>
            </div>
            <div>
              <dt>Cohorts</dt>
              <dd>{hovered.session.cohorts.join(", ") || "—"}</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
};
