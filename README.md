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
                                .─'  ██  ░░░░░░░░░░░  ██  `─.                                
                              .'     / `─.  ░░░░░  .─' \     `.                              
                                    /     `─█████─'     \                                    
                                   /          |          \                                   
                [ First-Principles CSP & Optimization Timetabling Engine ]                 
```

</div>

# Sundial Engine

**Sundial Engine** is an institution-agnostic **University Course Timetabling CSP & Optimization Engine** written in pure Python 3 (zero external solver dependencies in `src/csp/`), packaged as a self-hosted web application (**FastAPI** backend + **React / Vite** frontend).

Every institutional rule—calendar grid, breaks, Full-Time/Evening streams, venue compatibility, departmental affinity pools, soft-constraint weights, and optimizer parameters—lives declaratively in JSON (`configs/institution_schema.json`).

### 2-Stage Solving Pipeline

1. **Phase 3 — Exact CSP Solver (`src/csp/solver.py`):**
   - Encodes the `6 days × 18 periods` (`108`-slot) weekly grid into a single Python integer bitmask for $O(1)$ overlap and venue-availability checks.
   - Uses weekday-aware MRV + conflict-graph degree + block-duration ordering, 3-tier departmental venue affinity (with hard lab/workshop sub-pool locking), a strict 2-condition Saturday fallback (Mon–Fri default), and reversible eager forward checking (`undo_log`, zero `deepcopy`).
   - Supports pre-solve **session pinning** (`pinned_assignments`) with unary/pairwise 108-bit validation before search begins.
2. **Phase 4 — Pluggable Soft-Constraint Optimizer (`src/csp/optimizer.py`):**
   - Declarative JSON-configured `@register_soft_constraint` registry supporting 7 built-in rules (`minimize_saturday_theory`, `minimize_saturday_overflow`, `prefer_shared_practicals_on_saturday`, `minimize_evening_twilight`, `minimize_cohort_idle_gaps`, `balance_weekly_workload`, `prefer_exact_module_venue`) plus custom runtime rules.
   - Runs hard-constraint-preserving **Simulated Annealing** (`40,000` iterations) with $O(1)$ incremental $\Delta E$ scoring across guided single-session relocates and compatible pairwise swaps, strictly honoring `pinned_session_ids`.

---

## Verified Benchmarks (ATC Dataset)

Evaluated on the **Arusha Technical College (ATC)** master timetable (`75` venues, `175` lecturers, `121` active cohorts, `18` periods/day):

| Metric | Mode A: Clean Primary (`1,233` sessions) | Mode B: Full Stress-Test (`1,299` sessions) | Raw ATC Ground Truth (`1,299` sessions) |
| :--- | :---: | :---: | :---: |
| **Phase 3 CSP Solve Time** | `0.99 s` (`992.54 ms`) | `1.05 s` (`1,051.79 ms`) | Human-authored |
| **Phase 4 SA Optimization (`40,000` iter)** | `0.62 s` (`620.94 ms`) | `0.49 s` (`490.67 ms`) | — |
| **Backtracks** | **`0`** | **`0`** | — |
| **Hard Constraint Violations** | **`0`** (`0` Lec / `0` Coh / `0` Ven) | **`0`** (`0` Lec / `0` Coh / `0` Ven) | `81` conflicting pairs |
| **Soft-Objective Reduction (SA)** | **`-41.16%`** (`37,877.5` $\to$ `22,287.5`) | **`-29.42%`** (`45,143.8` $\to$ `31,862.5`) | — |
| **100% Saturday-Free Cohorts** | **`111 / 121` (`91.7%`)** | **`107 / 121` (`88.4%`)** | `86 / 121` (`71.1%`) |
| **Tier-1 Departmental Venue Affinity** | **`1,230 / 1,233` (`99.8%`)** | **`1,296 / 1,299` (`99.8%`)** | — |
| **Specialized Lab/Workshop Dept Lock** | **`306 / 306` (`100.0%`)** | **`323 / 323` (`100.0%`)** | `100.0%` |

---

## Repository Structure

```text
sundial-engine/
├── configs/
│   ├── institution_schema.json      # Calendar grid, streams, venue rules, soft constraints & SA config
│   └── atc_venue_affinity.json      # 3-tier departmental venue affinity & hard lab sub-pools
├── data/
│   ├── raw/atc/                     # Raw ATC benchmark JSON datasets
│   ├── uploads/                     # Uploaded logos & normalized custom CSV/JSON entities
│   └── processed/                   # Persisted app_state.json & exported timetable_view_data.json
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
│   │   ├── routes_settings.py       # Branding, logo upload & schema configuration routes
│   │   ├── routes_onboarding.py     # Independent CSV/JSON upload, templates & row validation
│   │   ├── routes_solve.py          # Phase 3 + Phase 4 solve endpoint & Saturday explanations
│   │   └── routes_public.py         # Public unauthenticated timetable consumer endpoint
│   └── viz/                         # Standalone static HTML/PDF timetable exporter & viewer
├── frontend/                        # React + TypeScript + Vite web application
│   ├── vite.config.ts               # Dev proxy (/api -> http://localhost:8000)
│   └── src/
│       ├── api/client.ts            # Typed fetch wrapper with Bearer token handling
│       ├── components/              # TimetableGrid, SearchableSelect, SundialMark
│       └── pages/                   # PublicLookup (/), AdminLogin (/login), StudioShell (/studio)
├── scripts/
│   └── verify_sprint2.py            # Live HTTP end-to-end API smoke test suite
└── tests/
    ├── test_optimizer.py            # Phase 4 soft-constraint & SA unit tests
    └── test_pinning_and_api.py      # Session pinning, auth, state & API unit tests
```

---

## API Reference (`src/api/`)

Interactive OpenAPI / Swagger UI documentation is available when the backend is running at **`http://localhost:8000/docs`** (ReDoc at `http://localhost:8000/redoc`).

### Health & Public Consumer

| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/health` | Public | Returns server status, active dataset mode, session count, and pin count. |
| `GET` | `/api/public/timetable` | Public | Returns branding, grid config, sorted `entities` (`cohorts`, `lecturers`, `venues`), and scheduled `sessions`. |
| `GET` | `/api/public/logo` | Public | Serves the uploaded institution logo image (`404` if none uploaded). |

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
| `GET` | `/api/onboarding/status` | Admin Bearer | Returns filename, row count, timestamp, and source (`preloaded_atc` vs `custom_upload`) per entity. |
| `GET` | `/api/onboarding/templates/{entity}` | Admin Bearer | Downloads a CSV template (`venues`, `lecturers`, or `sessions`) with exact headers and 2 sample rows. |
| `POST` | `/api/onboarding/upload/{entity}` | Admin Bearer | Uploads and normalizes a `.csv` or `.json` file for one entity without overwriting other entities. |
| `POST` | `/api/onboarding/validate` | Admin Bearer | Runs pigeonhole pre-flight and referential integrity checks, returning row-level `errors` and `warnings`. |

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

The frontend runs on **`http://localhost:5173`** and automatically proxies `/api/*` requests to `http://localhost:8000`.
- Public Timetable Front Door: `http://localhost:5173/`
- Registrar Login: `http://localhost:5173/login`
- Protected Studio: `http://localhost:5173/studio`

### 4. Standalone Pure-Python Engine & Automated Tests

```bash
# Run standalone pure-Python CSP + SA benchmark (Mode A & Mode B)
python3 src/csp/solver.py

# Run all unit tests (optimizer, session pinning, auth & API)
python3 -m unittest discover -s tests -v

# Run end-to-end HTTP smoke verification against a live uvicorn instance
python3 scripts/verify_sprint2.py
```
