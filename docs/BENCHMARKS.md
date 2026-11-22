# Sundial Engine — Benchmark Report

**Dataset:** Arusha Technical College (ATC) Master Timetable Benchmark
**Engine Architecture:** Pure-Python CSP Backtracking Solver (Phase 3) + O(1) Delta Simulated Annealing Optimiser (Phase 4)
**Measurement Date:** 22 November 2026

---

## 1. Dataset Overview

Sundial operates on a declarative weekly grid (`configs/institution_schema.json`) encoded into a 108-bit integer bitmask per resource (6 days × 18 periods).

| Property | Mode A (Clean Primary) | Mode B (Full Master) |
| :--- | ---: | ---: |
| **Sessions (`\|X\|`)** | 1,233 | 1,299 |
| **Cohorts** | 121 | 121 |
| **Lecturers** | 175 | 175 |
| **Venues** | 75 | 75 |
| **Grid dimensions** | 6 days × 18 periods (108 slots) | 6 days × 18 periods (108 slots) |
| **Full-Time stream** | P1–P12 (07:30–16:55, 45 min/period) | P1–P12 (07:30–16:55, 45 min/period) |
| **Evening stream + twilight** | P13–P18 (twilight buffer P11–P12) | P13–P18 (twilight buffer P11–P12) |
| **Break boundaries** | Tea after P4, Lunch after P6 | Tea after P4, Lunch after P6 |

---

## 2. Solver & Optimiser Comparison

Every number below was freshly measured against the current `src/csp/` engine with `configs/institution_schema.json` and `configs/atc_venue_affinity.json`.

### Mode A — ATC Clean Primary Dataset (`1,233` sessions)

| Metric | Ground Truth (Hand-Built) | Phase 3 (CSP) | Phase 4 (CSP + SA) |
| :--- | ---: | ---: | ---: |
| **Runtime** | Manual (weeks) | **916.2 ms** | **1,362.2 ms** *(916.2 ms CSP + 446.0 ms SA)* |
| **Backtracks** | — | **0** | **0** |
| **Hard-constraint violations** | 5 *(unary)* | **0** | **0** |
| **Soft-objective penalty** | — | 37,877.5 | **22,287.5** (**-41.2%**) |
| **Saturday-free cohorts** | 86 / 121 (71.1%) | **111 / 121 (91.7%)** | **108 / 121 (89.3%)** |
| **Saturday total sessions** | 35 | **17** | **17** |
| **Saturday Theory sessions** | 16 | 17 | **2** |
| **Evening twilight sessions** | 34 | **22** | **22** |
| **Tier-1 venue affinity** | 100.0% | **100.0%** | **99.8%** *(Tier 1A exact: 84.9%)* |

### Mode B — ATC Full Master Dataset (`1,299` sessions)

| Metric | Ground Truth (Hand-Built) | Phase 3 (CSP) | Phase 4 (CSP + SA) |
| :--- | ---: | ---: | ---: |
| **Runtime** | Manual (weeks) | **1,064.5 ms** | **1,515.8 ms** *(1,064.5 ms CSP + 451.3 ms SA)* |
| **Backtracks** | — | **0** | **0** |
| **Hard-constraint violations** | **224** *(71 lec, 71 coh, 77 ven, 5 unary)* | **0** | **0** |
| **Soft-objective penalty** | — | 45,143.8 | **31,862.5** (**-29.4%**) |
| **Saturday-free cohorts** | 86 / 121 (71.1%) | **107 / 121 (88.4%)** | **100 / 121 (82.6%)** |
| **Saturday total sessions** | 40 | **39** | 40 |
| **Saturday Theory sessions** | 17 | 23 | **9** |
| **Evening twilight sessions** | 35 | **24** | 25 |
| **Tier-1 venue affinity** | 100.0% | **99.9%** | **99.8%** *(Tier 1A exact: 82.5%)* |

---

## 3. API & Noticeboard PDF Export Performance

Measured on the live FastAPI backend (`src/api/`) with ReportLab A4 Landscape rendering (`src/api/pdf_export.py`):

| Operation | Scope | Measured Latency | Payload Size |
| :--- | :--- | ---: | ---: |
| `POST /api/solve` | ATC Mode A (`1,233` sessions, Phase 3 + Phase 4 + verification + persistence) | **~1.58 s** | JSON response |
| `GET /api/public/export/pdf` | Single cohort A4 Landscape noticeboard PDF (`L7-2CS`) | **33.0 ms** | 3.8 KB (1 page) |
| `GET /api/export/master-pdf?lens=cohort` | Master Cohorts noticeboard PDF (all 121 cohorts) | **2,236.0 ms** | 324.0 KB (121 pages) |

---

## 4. Verified Invariants

All invariants are enforced continuously by the automated test suite (`python3 -m unittest discover -s tests -v`):

1. **Zero backtracks & zero hard clashes** on both ATC Mode A (`1,233` sessions) and Mode B (`1,299` sessions).
2. **Exact O(1) delta scoring parity** between incremental Simulated Annealing updates and full soft-objective re-evaluation.
3. **Hard session pinning** preserved identically across both Phase 3 CSP placement and Phase 4 Simulated Annealing optimisation.
4. **Pure Python standard library core** — `src/csp/` has zero third-party dependencies.
