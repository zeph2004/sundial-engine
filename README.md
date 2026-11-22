<div align="center">

```text
                                   \          |          /                                   
                                    \     .─█████─.     /                                    
                              `.     \ .─'  ░░░░░  `─. /     .'                              
                                `─.  ██  ░░░░░░░░░░░  ██  .─'                                
                                  .─'  ░░░░░░ ▲ ░░░░░░  `─.                                  
                                 ╱   ░░░░░░░░ ║ ░░░░░░░░   ╲                                 
                      ─────────███ ░░░░░░░░░░ ║ ░░░░░░░░░░ ███─────────                      
                  ════════════╡  S U N D I A L - E N G I N E  ╞════════════                  
                      ─────────███ ░░░░░░░░░░ ║ ░░░░░░░░░░ ███─────────                      
                                 ╲   ░░░░░░░░ ║ ░░░░░░░░   ╱                                 
                                  `─.  ░░░░░░ ▼ ░░░░░░  `─.                                  
                                .─'  ██  ░░░░░░░░░░░  ██  .─'                                
                              .'     / `─.  ░░░░░  .─' \     `.                              
                                    /     `─█████─'     \                                    
                                   /          |          \                                   
                [ First-Principles CSP & Optimization Timetabling Engine ]                 
```

</div>

# Sundial Engine (v1.0)

**Sundial Engine** is an institution-agnostic **University Course Timetabling CSP & Optimization Engine** written in pure Python 3 (zero external solver dependencies in `src/csp/`), packaged as a self-hosted web application (**FastAPI** backend + **React / Vite** frontend).

Every institutional rule—calendar grid, breaks, Full-Time/Evening streams, venue compatibility, departmental affinity pools, soft-constraint weights, and optimiser parameters—lives declaratively in JSON (`configs/institution_schema.json`).

---

## Key Features (v1.0)

- **2-Stage Solving Pipeline (`src/csp/` — 100% pure Python stdlib):**
  1. **Phase 3 — Exact CSP Solver (`solver.py`):** Encodes the `6 days × 18 periods` (`108`-slot) weekly grid into a Python integer bitmask for $O(1)$ overlap checks. Uses weekday-aware MRV + conflict-graph degree + block-duration ordering, 3-tier departmental venue affinity (with hard lab/workshop sub-pool locking), a strict 2-condition Saturday fallback (Mon–Fri default), and reversible eager forward checking (`undo_log`, zero `deepcopy`).
  2. **Phase 4 — Pluggable Soft-Constraint Optimiser (`optimizer.py`):** Declarative JSON-configured `@register_soft_constraint` registry with 7 built-in rules plus custom runtime rules, optimised via hard-constraint-preserving **Simulated Annealing** (`40,000` iterations) with $O(1)$ incremental $\Delta E$ scoring.
- **Course Allocations (`hours_per_week`) & Auto-Chunker (`src/api/chunker.py`):** Registrars can upload weekly course hours (`hours_per_week`), `weekly_periods`, or legacy pre-split `duration_periods`. Sundial automatically converts hours using the institution's period duration and splits them into balanced teaching blocks (with optional `split_override` such as `3+3` and non-blocking rounding notices).
- **Theory-Only Institution Support:** Pre-flight validation and solving cleanly handle institutions with zero Lab/Workshop venues or sessions.
- **Registrar Solver Studio (`/studio`):**
  - **Interactive Session Pinning:** Click any timetable block to lock/unlock it in its exact `(day, start_period, venue_id)` slot across both Phase 3 and Phase 4, with instant 108-bit clash validation and one-click *Clear all pins*.
  - **Docked Soft-Constraint Drawer:** Toggle rules on/off, adjust priorities via a 10-tier weight scale, edit rule parameters, or switch to **Advanced (JSON)** mode with live syntax validation and reset-to-defaults.
  - **Scorecard & Saturday Transparency Modal:** Displays Before (Phase 3) vs. After (Phase 4) penalty breakdowns and Condition 1/2 explanations for every cohort with Saturday sessions.
- **Noticeboard A4 Landscape PDF Exports (`src/api/pdf_export.py`):**
  - **Public Single PDF (`/`):** One-tap A4 Landscape download for any Cohort, Lecturer, or Venue with official branding, dedicated shaded **TEA** and **LUNCH** break columns, lecturer names in every cell, and `Page X of Y` footers.
  - **Master Bulk PDF (`/studio`):** Protected multi-page noticeboard export for *All Cohorts*, *All Lecturers*, or *All Venues*.

---

## Verified Benchmarks (ATC Dataset)

Evaluated on the **Arusha Technical College (ATC)** master timetable (`75` venues, `175` lecturers, `121` active cohorts, `18` periods/day). See **[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md)** for the full breakdown including Phase 3 vs. Phase 4 comparisons and API/PDF latency.

| Metric | Mode A: Clean Primary (`1,233` sessions) | Mode B: Full Master (`1,299` sessions) | Raw ATC Ground Truth (`1,299` sessions) |
| :--- | :---: | :---: | :---: |
| **Phase 3 CSP Solve Time** | `916.2 ms` | `1,064.5 ms` | Human-authored |
| **Phase 4 SA Optimization (`40,000` iter)** | `446.0 ms` (`1.36 s` total) | `451.3 ms` (`1.52 s` total) | — |
| **Backtracks** | **`0`** | **`0`** | — |
| **Hard Constraint Violations** | **`0`** (`0` Lec / `0` Coh / `0` Ven) | **`0`** (`0` Lec / `0` Coh / `0` Ven) | `224` (`71` Lec / `71` Coh / `77` Ven / `5` Unary) |
| **Soft-Objective Reduction (SA)** | **`-41.2%`** (`37,877.5` $\to$ `22,287.5`) | **`-29.4%`** (`45,143.8` $\to$ `31,862.5`) | — |
| **100% Saturday-Free Cohorts (Phase 3 / Phase 4)** | **`111 / 121` (`91.7%`)** / `108 / 121` (`89.3%`) | **`107 / 121` (`88.4%`)** / `100 / 121` (`82.6%`) | `86 / 121` (`71.1%`) |
| **Saturday Theory Sessions (Phase 4)** | **`2`** *(down from 17)* | **`9`** *(down from 23)* | `17` |
| **Tier-1 Departmental Venue Affinity** | **`99.8%`** *(Tier 1A exact: `84.9%`)* | **`99.8%`** *(Tier 1A exact: `82.5%`)* | `100.0%` |
| **Noticeboard PDF Export** | `33.0 ms` (single) / `2.24 s` (121-page master) | — | — |

---

## Repository Structure

```text
sundial-engine/
├── configs/
│   ├── institution_schema.json      # Calendar grid, streams, venue rules, soft constraints & SA config
│   └── atc_venue_affinity.json      # 3-tier departmental venue affinity & hard lab sub-pools
├── data/
│   ├── raw/atc/                     # Raw ATC benchmark JSON datasets (used for first-boot preload)
│   └── processed/                   # Runtime app_state.json (gitignored) & view data bundle
├── docs/
│   └── BENCHMARKS.md                # Full Mode A / Mode B & API/PDF benchmark report
├── src/
│   ├── csp/                         # 100% pure Python 3 stdlib engine (zero external deps)
│   │   ├── domain.py                # Declarative domain builder & pigeonhole pre-flight checks
│   │   ├── constraints.py           # Conflict graph builder & ground-truth clash auditor
│   │   ├── affinity.py              # 3-tier venue affinity resolver & specialized lab lock
│   │   ├── solver.py                # Phase 3 108-bit backtracking CSP solver with session pinning
│   │   └── optimizer.py             # Phase 4 pluggable soft-constraint engine & SA optimizer
│   ├── api/                         # Self-hosted FastAPI backend
│   │   ├── main.py                  # App factory, CORS, auth/pin routes & router mounting
│   │   ├── auth.py                  # Stateless HMAC-SHA256 single-admin bearer auth (24h expiry)
│   │   ├── state.py                 # Thread-safe persistent workspace manager (app_state.json)
│   │   ├── chunker.py               # hours_per_week -> balanced session auto-chunker
│   │   ├── pdf_export.py            # ReportLab A4 Landscape university noticeboard PDF renderer
│   │   ├── routes_settings.py       # Branding, logo upload & schema configuration routes
│   │   ├── routes_onboarding.py     # Independent CSV/JSON upload, templates & row validation
│   │   ├── routes_solve.py          # Phase 3 + Phase 4 solve endpoint & Saturday explanations
│   │   ├── routes_export.py         # Public single PDF & protected Master Bulk PDF routes
│   │   └── routes_public.py         # Public unauthenticated timetable consumer endpoint
│   └── viz/                         # Standalone static HTML timetable exporter & viewer
├── frontend/                        # React + TypeScript + Vite web application
│   ├── vite.config.ts               # Dev proxy (/api -> http://localhost:8000)
│   └── src/
│       ├── api/client.ts            # Typed fetch wrapper with Bearer token & PDF download helpers
│       ├── components/              # TimetableGrid, SearchableSelect, ConstraintDrawer, SolveDetailsModal, SundialMark, CardioidBackdrop
│       └── pages/                   # PublicLookup (/), AdminLogin (/login), StudioShell (/studio), SolverStudio, DataOnboarding, InstitutionSettings
├── scripts/
│   └── verify_sprint2.py            # Live HTTP end-to-end API smoke test suite
└── tests/
    ├── test_chunker.py              # Course allocation auto-chunker & Theory-only API tests
    ├── test_optimizer.py            # Phase 4 soft-constraint & SA unit tests
    ├── test_pdf_export.py           # Public single PDF & protected Master Bulk PDF tests
    ├── test_pinning_and_api.py      # Session pinning, auth, state & API unit tests
    └── test_solver_invariants.py    # Mode A/B 0-backtrack, delta parity & pinning invariant tests
```

---

## API Reference (`src/api/`)

Interactive OpenAPI / Swagger UI documentation is available when the backend is running at **`http://localhost:8000/docs`** (ReDoc at `http://localhost:8000/redoc`).

### Health, Public Consumer & PDF Exports

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/health` | Public | Returns server status, active dataset mode, session count, and pin count. |
| `GET` | `/api/public/timetable` | Public | Returns branding, grid config, sorted `entities` (`cohorts`, `lecturers`, `venues`), and scheduled `sessions`. |
| `GET` | `/api/public/logo` | Public | Serves the uploaded institution logo image (`404` if none uploaded). |
| `GET` | `/api/public/export/pdf` | Public | Downloads a single-page A4 Landscape noticeboard PDF (`?lens=cohort\|lecturer\|venue&id=<id>`). |
| `GET` | `/api/export/master-pdf` | Admin Bearer | Downloads a multi-page A4 Landscape Master PDF for all entities (`?lens=cohort\|lecturer\|venue`). |

### Authentication

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/login` | Public | Verifies single-admin credentials and returns a 24-hour HMAC-SHA256 bearer token. |
| `GET` | `/api/auth/me` | Admin Bearer | Validates the bearer token and returns the authenticated admin claims. |

### Institution Settings & Branding

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/settings` | Admin Bearer | Returns `branding` and `schema_config` from `app_state.json`. |
| `PUT` | `/api/settings/branding` | Admin Bearer | Updates `institution_name` and `semester_title` and persists state. |
| `POST` | `/api/settings/logo` | Admin Bearer | Uploads a PNG/JPG/SVG/WEBP logo (max 2 MB) to `data/uploads/logo.<ext>` and sets `logo_url`. |
| `PUT` | `/api/settings/schema` | Admin Bearer | Validates and persists an updated `schema_config` (returns `400` with field errors if invalid). |
| `POST` | `/api/settings/schema/reset` | Admin Bearer | Resets `schema_config` back to `configs/institution_schema.json`. |

### Data Onboarding & Pre-Flight Validation

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/onboarding/status` | Admin Bearer | Returns filename, row count (`row_count` + `input_rows` if expanded), timestamp, and source per entity. |
| `GET` | `/api/onboarding/templates/{entity}` | Admin Bearer | Downloads a CSV template (`venues`, `lecturers`, or `sessions` in Course Allocations `hours_per_week` format). |
| `POST` | `/api/onboarding/upload/{entity}` | Admin Bearer | Uploads a `.csv` or `.json` file independently. Auto-detects `hours_per_week`, `weekly_periods`, or legacy `duration_periods` for `sessions`. |
| `POST` | `/api/onboarding/validate` | Admin Bearer | Runs pigeonhole pre-flight and referential integrity checks (Theory-only safe), returning row-level `errors` and `warnings`. |

### Solver & Session Pinning

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/solve` | Admin Bearer | Validates data, runs Phase 3 CSP + Phase 4 SA (honoring active pins), persists `active_timetable`, and returns KPIs, scorecard, and Condition 1 `saturday_explanations`. |
| `GET` | `/api/pins` | Public | Lists all currently pinned sessions and their locked `(day, start_period, venue_id)` slots. |
| `PUT` | `/api/pins/{session_id}` | Admin Bearer | Validates (unary + pairwise 108-bit clash check) and pins `session_id` to `(day, start_period, venue_id)`. *(Also accepts `POST /api/pins` with `session_id` in the body.)* |
| `DELETE` | `/api/pins/{session_id}` | Admin Bearer | Removes the pin for a specific `session_id`. |
| `DELETE` | `/api/pins` | Admin Bearer | Clears all active session pins. |

---

## How to Run the System

### 1. Prerequisites
- **Python 3.11+** (tested on Python 3.14 in `.venv`)
- **Node.js 18+** and `npm`

### 2. Backend Setup & Start (FastAPI)

```bash
# Activate virtual environment and install dependencies
source .venv/bin/activate
pip install -r requirements.txt

# Optional environment variables (defaults shown below)
export SUNDIAL_ADMIN_USER="admin"
export SUNDIAL_ADMIN_PASS="sundial-admin"
export SUNDIAL_SECRET_KEY="sundial-dev-secret-key-change-in-production"

# Start FastAPI backend on http://localhost:8000 (Swagger docs at /docs)
uvicorn src.api.main:app --reload --port 8000
```

On first boot, `data/processed/app_state.json` is automatically initialized with the preloaded ATC Clean Primary Dataset (Mode A, `1,233` sessions).

### 3. Frontend Setup & Start (React + Vite)

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on **`http://localhost:5173`** and automatically proxies `/api/*` requests to `http://localhost:8000`:
- Public Timetable Front Door & PDF Download: `http://localhost:5173/`
- Registrar Login: `http://localhost:5173/login`
- Protected Registrar Studio: `http://localhost:5173/studio`

### 4. Standalone Pure-Python Engine & Automated Test Suite

```bash
# Run standalone pure-Python CSP + SA benchmark (Mode A & Mode B)
python3 src/csp/solver.py

# Run the complete automated test suite (20 tests across solver, chunker, optimizer, API & PDFs)
python3 -m unittest discover -s tests -v

# Build production frontend bundle
cd frontend && npm run build
```
