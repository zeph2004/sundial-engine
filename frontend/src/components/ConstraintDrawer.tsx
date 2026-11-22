import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  ChevronRight,
  Code2,
  RotateCcw,
  SlidersHorizontal,
} from "lucide-react";
import {
  resetSchema,
  type OptimizerConfig,
  type SchemaConfig,
  type SoftConstraintRuleConfig,
} from "../api/client";

export interface ConstraintMeta {
  title: string;
  description: string;
}

export const SOFT_CONSTRAINT_META: Record<string, ConstraintMeta> = {
  minimize_saturday_theory: {
    title: "Keep theory off Saturday",
    description:
      "Prioritises placing lectures and tutorials on Monday–Friday.",
  },
  keep_theory_off_saturday: {
    title: "Keep theory off Saturday",
    description:
      "Prioritises placing lectures and tutorials on Monday–Friday.",
  },
  minimize_saturday_overflow: {
    title: "Minimise Saturday overflow",
    description:
      "Keeps Saturday free unless weekly cohort or venue load forces overflow.",
  },
  prefer_shared_practicals_on_saturday: {
    title: "Prefer shared practicals on Saturday",
    description:
      "When Saturday is required, moves shared multi-cohort practicals first.",
  },
  minimize_evening_twilight: {
    title: "Avoid twilight periods",
    description:
      "Prefers P13–P18 over the P11–P12 twilight buffer for evening sessions.",
  },
  avoid_twilight_periods: {
    title: "Avoid twilight periods",
    description:
      "Prefers P13–P18 over the P11–P12 twilight buffer for evening sessions.",
  },
  minimize_cohort_idle_gaps: {
    title: "Minimise cohort idle gaps",
    description:
      "Reduces empty periods between classes for student cohorts on weekdays.",
  },
  balance_weekly_workload: {
    title: "Balance weekly workload",
    description:
      "Spreads teaching load evenly across Monday–Friday for cohorts and lecturers.",
  },
  prefer_exact_module_venue: {
    title: "Prefer exact & department venues",
    description:
      "Keeps specialised labs and modules in their primary department rooms.",
  },
};

export function formatRuleTitle(key: string): string {
  if (SOFT_CONSTRAINT_META[key]) return SOFT_CONSTRAINT_META[key].title;
  return key
    .split("_")
    .filter(Boolean)
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

function formatParamLabel(key: string): string {
  return key
    .split("_")
    .filter(Boolean)
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

// 10-tier weight scale mapped cleanly onto ATC default weights (10..150)
const TIER_WEIGHTS = [5, 10, 20, 30, 50, 65, 80, 100, 125, 150];

function weightToTier(weight: number): number {
  let bestIdx = 0;
  let bestDiff = Math.abs(TIER_WEIGHTS[0] - weight);
  for (let i = 1; i < TIER_WEIGHTS.length; i++) {
    const diff = Math.abs(TIER_WEIGHTS[i] - weight);
    if (diff < bestDiff) {
      bestDiff = diff;
      bestIdx = i;
    }
  }
  return bestIdx + 1;
}

function tierToWeight(tier: number): number {
  const clamped = Math.min(10, Math.max(1, Math.round(tier)));
  return TIER_WEIGHTS[clamped - 1];
}

export interface ConstraintDrawerProps {
  schema: SchemaConfig | null;
  onSchemaChange: (nextSchema: SchemaConfig) => void;
  onJsonValidityChange: (isValid: boolean) => void;
  onCollapse?: () => void;
  disabled?: boolean;
}

export const ConstraintDrawer: React.FC<ConstraintDrawerProps> = ({
  schema,
  onSchemaChange,
  onJsonValidityChange,
  onCollapse,
  disabled = false,
}) => {
  const [advancedMode, setAdvancedMode] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [customJsonActive, setCustomJsonActive] = useState(false);

  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  useEffect(() => {
    if (!schema || advancedMode) return;
    setRawJson(
      JSON.stringify(
        {
          soft_constraints: schema.soft_constraints || {},
          optimizer: schema.optimizer || {},
        },
        null,
        2
      )
    );
  }, [schema, advancedMode]);

  const handleEnterAdvanced = () => {
    if (!schema) return;
    setRawJson(
      JSON.stringify(
        {
          soft_constraints: schema.soft_constraints || {},
          optimizer: schema.optimizer || {},
        },
        null,
        2
      )
    );
    setJsonError(null);
    onJsonValidityChange(true);
    setAdvancedMode(true);
  };

  const handleExitAdvanced = () => {
    if (jsonError) return;
    setAdvancedMode(false);
  };

  const handleRawJsonChange = (text: string) => {
    setRawJson(text);
    if (!schema) return;
    try {
      const parsed = JSON.parse(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Root JSON must be an object.");
      }
      if (
        parsed.soft_constraints !== undefined &&
        (typeof parsed.soft_constraints !== "object" ||
          parsed.soft_constraints === null ||
          Array.isArray(parsed.soft_constraints))
      ) {
        throw new Error("'soft_constraints' must be a JSON object.");
      }
      if (
        parsed.optimizer !== undefined &&
        (typeof parsed.optimizer !== "object" ||
          parsed.optimizer === null ||
          Array.isArray(parsed.optimizer))
      ) {
        throw new Error("'optimizer' must be a JSON object.");
      }

      setJsonError(null);
      onJsonValidityChange(true);
      setCustomJsonActive(true);
      onSchemaChange({
        ...schema,
        soft_constraints:
          (parsed.soft_constraints as Record<
            string,
            SoftConstraintRuleConfig
          >) ?? schema.soft_constraints,
        optimizer: (parsed.optimizer as OptimizerConfig) ?? schema.optimizer,
      });
    } catch (err) {
      setJsonError(
        err instanceof Error ? err.message : "Invalid JSON syntax."
      );
      onJsonValidityChange(false);
    }
  };

  const updateRule = (
    ruleKey: string,
    patch: Partial<SoftConstraintRuleConfig>
  ) => {
    if (!schema) return;
    const current = schema.soft_constraints || {};
    const existing = current[ruleKey] || { enabled: true, weight: 20 };
    onSchemaChange({
      ...schema,
      soft_constraints: {
        ...current,
        [ruleKey]: {
          ...existing,
          ...patch,
        },
      },
    });
  };

  const updateRuleParam = (
    ruleKey: string,
    paramKey: string,
    value: number | boolean
  ) => {
    if (!schema) return;
    const current = schema.soft_constraints || {};
    const existing = current[ruleKey] || { enabled: true, weight: 20 };
    onSchemaChange({
      ...schema,
      soft_constraints: {
        ...current,
        [ruleKey]: {
          ...existing,
          params: {
            ...(existing.params || {}),
            [paramKey]: value,
          },
        },
      },
    });
  };

  const handleConfirmReset = async () => {
    setResetting(true);
    setResetError(null);
    try {
      const res = await resetSchema();
      onSchemaChange(res.schema_config);
      setCustomJsonActive(false);
      setJsonError(null);
      onJsonValidityChange(true);
      setConfirmReset(false);
      if (advancedMode) {
        setRawJson(
          JSON.stringify(
            {
              soft_constraints: res.schema_config.soft_constraints || {},
              optimizer: res.schema_config.optimizer || {},
            },
            null,
            2
          )
        );
      }
    } catch (err) {
      setResetError(
        err instanceof Error ? err.message : "Could not reset default rules."
      );
    } finally {
      setResetting(false);
    }
  };

  const rules = schema?.soft_constraints || {};
  const ruleKeys = Object.keys(rules);

  return (
    <aside className="constraint-drawer" aria-label="Soft constraint rules">
      <div className="drawer-head">
        <div className="drawer-head-text">
          <h3>Preferences &amp; weights</h3>
          <p>Adjust priorities before generating.</p>
        </div>
        <div className="drawer-head-actions">
          <button
            type="button"
            className={`btn btn-sm ${
              advancedMode ? "btn-primary" : "btn-secondary"
            }`}
            disabled={disabled || (advancedMode && Boolean(jsonError))}
            onClick={advancedMode ? handleExitAdvanced : handleEnterAdvanced}
          >
            {advancedMode ? (
              <>
                <SlidersHorizontal size={13} />
                <span>Guided</span>
              </>
            ) : (
              <>
                <Code2 size={13} />
                <span>JSON</span>
              </>
            )}
          </button>
          {onCollapse && (
            <button
              type="button"
              className="icon-btn"
              title="Collapse panel"
              aria-label="Collapse Preferences & weights panel"
              onClick={onCollapse}
            >
              <ChevronRight size={15} />
            </button>
          )}
        </div>
      </div>

      <div className="drawer-scroll-body">
        {customJsonActive && (
          <div className="custom-json-badge" style={{ marginBottom: 12 }}>
            <Code2 size={12} />
            <span>Custom JSON active</span>
          </div>
        )}

        {!schema ? (
          <div className="drawer-empty">Loading rules...</div>
        ) : advancedMode ? (
          <div className="drawer-json-body">
            <label className="field-label" htmlFor="soft-constraints-json">
              soft_constraints &amp; optimizer JSON
            </label>
            <textarea
              id="soft-constraints-json"
              className={`json-editor-area ${jsonError ? "has-error" : ""}`}
              value={rawJson}
              onChange={(e) => handleRawJsonChange(e.target.value)}
              spellCheck={false}
              disabled={disabled}
              rows={20}
            />
            {jsonError ? (
              <div
                className="inline-alert alert-clash"
                role="alert"
                style={{ marginTop: 8, marginBottom: 0 }}
              >
                <AlertCircle size={14} />
                <span>{jsonError}</span>
              </div>
            ) : (
              <p className="field-hint">
                Valid JSON. Changes apply on next Generate Timetable run.
              </p>
            )}
          </div>
        ) : (
          <div className="drawer-rules-list">
            {ruleKeys.map((key) => {
              const cfg = rules[key];
              const meta = SOFT_CONSTRAINT_META[key];
              const tier = weightToTier(cfg.weight ?? 0);
              const editableParams = Object.entries(cfg.params || {}).filter(
                ([, val]) => typeof val === "number" || typeof val === "boolean"
              );

              return (
                <div
                  key={key}
                  className={`rule-item ${cfg.enabled ? "" : "is-disabled"}`}
                >
                  <div className="rule-item-top">
                    <label className="rule-toggle-label">
                      <input
                        type="checkbox"
                        checked={Boolean(cfg.enabled)}
                        disabled={disabled}
                        onChange={(e) =>
                          updateRule(key, { enabled: e.target.checked })
                        }
                      />
                      <span className="rule-title">
                        {meta?.title || formatRuleTitle(key)}
                      </span>
                    </label>
                    <span
                      className="rule-tier-pill mono-num"
                      title={`Underlying numeric weight: ${cfg.weight}`}
                    >
                      T{tier}/10 · w={cfg.weight}
                    </span>
                  </div>

                  {meta?.description && (
                    <p className="rule-desc">{meta.description}</p>
                  )}

                  {cfg.enabled && (
                    <div className="rule-slider-row">
                      <input
                        type="range"
                        min={1}
                        max={10}
                        step={1}
                        value={tier}
                        disabled={disabled}
                        aria-label={`${formatRuleTitle(key)} priority tier`}
                        onChange={(e) =>
                          updateRule(key, {
                            weight: tierToWeight(Number(e.target.value)),
                          })
                        }
                        className="tier-slider"
                      />
                      <div className="tier-scale-labels mono-num">
                        <span>1 (Low)</span>
                        <span>10 (Strict)</span>
                      </div>
                    </div>
                  )}

                  {cfg.enabled && editableParams.length > 0 && (
                    <div className="rule-params-grid">
                      {editableParams.map(([pKey, pVal]) =>
                        typeof pVal === "boolean" ? (
                          <label
                            key={pKey}
                            className="inline-check rule-param-row"
                          >
                            <input
                              type="checkbox"
                              checked={pVal}
                              disabled={disabled}
                              onChange={(e) =>
                                updateRuleParam(key, pKey, e.target.checked)
                              }
                            />
                            <span>{formatParamLabel(pKey)}</span>
                          </label>
                        ) : (
                          <label key={pKey} className="rule-param-field">
                            <span>{formatParamLabel(pKey)}</span>
                            <input
                              type="number"
                              step="any"
                              className="table-input mono-num rule-param-input"
                              value={pVal as number}
                              disabled={disabled}
                              onChange={(e) => {
                                const num = Number(e.target.value);
                                if (!Number.isNaN(num)) {
                                  updateRuleParam(key, pKey, num);
                                }
                              }}
                            />
                          </label>
                        )
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {resetError && (
          <div
            className="inline-alert alert-clash"
            role="alert"
            style={{ marginTop: 12, marginBottom: 0 }}
          >
            <AlertCircle size={14} />
            <span>{resetError}</span>
          </div>
        )}
      </div>

      <div className="drawer-footer">
        {!confirmReset ? (
          <button
            type="button"
            className="btn btn-ghost btn-full"
            disabled={disabled || resetting}
            onClick={() => setConfirmReset(true)}
          >
            <RotateCcw size={14} />
            <span>Reset to defaults</span>
          </button>
        ) : (
          <div className="drawer-reset-confirm">
            <span>Restore default weights?</span>
            <div className="drawer-reset-btns">
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={resetting}
                onClick={handleConfirmReset}
              >
                {resetting ? "Resetting..." : "Confirm"}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={resetting}
                onClick={() => setConfirmReset(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
};
